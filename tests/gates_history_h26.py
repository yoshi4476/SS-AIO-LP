# -*- coding: utf-8 -*-
"""効果判定（effect_ab）の対照群を公開からの日数でそろえ、early の書き直しも28日で戻す（2026-10-05）。

どの記事も公開1〜3週で表示の山、4〜6週で山の約1/4に落ちる（3サイト共通）。effect_ab は対照群に
公開の古い記事と記事以外のページ（トップ・カテゴリ・著者・用語集）を混ぜていたため、公開から日の浅い記事を
直す手（auto_rewrite --kind early は公開14〜35日が対象）は自然な落ち込みの分だけ「効かない」と読まれた。
rewrite_rollback と同じ物差し（effect_ab.cohort）にそろえ、early も題と同じ条件で戻す。
Search Console・台帳・記事には触れない（日別の表示と原稿は手元で作る）。
"""
import hashlib
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path

from test_gates import check, ROOT


def _curve(age):
    """公開からの日数ごとの表示（1〜3週で山・4〜6週で山の1/4・その後は少し）"""
    w = age // 7
    return 0 if age < 0 else (40 if w <= 2 else 10 if w <= 5 else 8)


def _world(at):
    """直した記事 fixed（公開21日）・同じ週数の記事12本・公開の古い記事30本・記事以外のページ"""
    pubs, daily = {}, {}

    def add(slug, pub, scale_after=1.0, flat=None, pos=(10.0, 10.0)):
        pubs[slug] = pub
        d = daily.setdefault(slug, {})
        for i in range(-60, 45):
            day = at + timedelta(days=i)
            v = flat if flat is not None else _curve((day - pub).days)
            v = v * (scale_after if day > at else 1.0)
            d[day.isoformat()] = [v, 0, (pos[1] if day > at else pos[0]) * v]
    add("fixed", at - timedelta(days=21))
    for k in range(12):
        add(f"young{k}", at - timedelta(days=21 + (k % 13) - 6))
    for k in range(30):
        add(f"old{k}", at - timedelta(days=200 + k), flat=30)
    daily["top"] = {(at + timedelta(days=i)).isoformat(): [100, 0, 1000.0] for i in range(-60, 45)}
    return pubs, daily, add


def test_effect_ab_controls_match_age_and_skip_pages():
    import effect_ab as EA
    import rewrite_rollback as R
    print("\n■ effect_ab: 対照群は公開からの日数が近い記事だけ（記事以外は外す・10本未満は保留）")
    at = date.today() - timedelta(days=40)
    pubs, daily, _ = _world(at)
    cs = EA.cohort(daily, "fixed", at, pubs, [], 28)
    check("対照は同じ週数（±7日）の記事だけ。古い記事・トップは入らない",
          sorted(cs), sorted(f"young{k}" for k in range(12)))
    check("公開日の分からないページ（トップ・カテゴリ等）は判定しない", EA.cohort(daily, "top", at, pubs, [], 28), None)
    acts = [{"slug": "young0", "at": (at + timedelta(days=5)).isoformat()},
            {"slug": "young1", "at": (at - timedelta(days=40)).isoformat()}]
    check("比べる前後の期間に手を打った記事だけ外す", len(EA.cohort(daily, "fixed", at, pubs, acts, 28)), 11)
    check("題を戻す判定と同じ関数・同じ下限（重複させない）",
          (sorted(R.controls(daily, "fixed", at, pubs, [])) ==
           sorted(EA.change(daily, s, at, 28)[0] for s in cs), R.min_controls(), EA.MIN_CTRL), (True, 10, 10))

    # 経過の落ち込みだけの early を5本: 旧の物差しでは「効かない」、新では対照と同じ動き（倍率1.0）
    acts = []
    for k in range(5):
        s = f"early{k}"
        pubs[s] = at - timedelta(days=21)
        daily[s] = dict(daily["fixed"])
        acts.append({"slug": s, "at": at.isoformat(), "kind": "early"})
    res = EA.rewrite_effects(acts, daily, date.today(), pubs=pubs)
    k = res["kinds"]["early"]
    check("年齢をそろえると経過の落ち込みは両群に入り、効き目の倍率は1.0（対照の本数を残す）",
          (k["judged"], 0.9 <= k["net_imp"] <= 1.1, k["control_n"], k["held"]), (5, True, 13, 0))
    old_like = {s: v for s, v in pubs.items() if not s.startswith("young")}
    res2 = EA.rewrite_effects(acts, daily, date.today(), pubs=old_like)
    k2 = res2["kinds"]["early"]
    check("同じ週数の記事が10本に満たなければ保留（判定済みに数えない）",
          (k2["judged"], k2["held"], k2["verdict"], {x["status"] for x in res2["items"]}),
          (0, 5, "判定前", {"対照群が足りない"}))
    rows = EA.kind_effects([dict(a, kind="link") for a in acts], daily, 21, pubs, others=[])
    import statistics
    old_ctrl = statistics.median(EA.change(daily, s, at, 21)[0] for s in daily if not s.startswith("early"))
    check("施策ごとの判定（--rewrites 以外）も同じ物差し: 前の対照（全ページ）では8割を割り、同じ週数ならほぼ同じ",
          [(r[0], r[1], r[2] / old_ctrl < 0.8, 0.8 <= r[2] / r[3] <= 1.25, r[6]) for r in rows],
          [("link", 5, True, True, 0)])
    rows = EA.kind_effects([dict(a, kind="link") for a in acts], daily, 21, old_like, others=[])
    check("施策ごとの判定も対照が10本未満なら保留", [(r[0], r[1], r[6]) for r in rows], [("link", 0, 5)])

    # 内部リンク・CTA はほぼ全記事に入る。期間内のそれで対照を外すと判定が永久に保留になる（実測 51件中35件）
    cta = [{"slug": f"young{i}", "at": at.isoformat(), "kind": "cta"} for i in range(12)]
    k3 = EA.rewrite_effects(acts, daily, date.today(), pubs=pubs)["kinds"]["early"]
    rows = EA.kind_effects([dict(a, kind="link") for a in acts] + cta, daily, 21, pubs, others=[])
    check("書き直しの判定は内部リンク・CTA を受けた記事も対照に残し、施策ごとの判定は同じ施策を受けた記事だけ外す",
          (k3["control_n"], {r[0]: r[7] for r in rows if r[1]}), (13, {"link": 13}))


BEFORE = """---
title: 工務店のMEOの始め方
keyword: 工務店 MEO
faq:
  - q: MEOとは？
    a: 地図検索の対策です。
date: 2026-08-01
---
工務店のMEOは地図検索の対策です。

## 始め方
本文A。

## 費用
本文B。

## よくある質問

<div class="faq">
<details><summary>MEOとは？</summary><p class="faq-a">地図検索の対策です。</p></details>
</div>
"""
LINK = "関連して、[口コミ返信の型](/aio/x/)もあわせてご確認ください。\n\n"


def _after_early(text, add_h2=False):
    t = text.replace("title: 工務店のMEOの始め方", "title: 工務店のMEOの始め方と口コミ返信")
    t = t.replace("    a: 地図検索の対策です。\n", "    a: 地図検索の対策です。\n  - q: 工務店の口コミ返信は？\n    a: 24時間以内に返します。\n")
    t = t.replace("</p></details>\n</div>", "</p></details>\n<details><summary>工務店の口コミ返信は？</summary>"
                  "<p class=\"faq-a\">24時間以内に返します。</p></details>\n</div>")
    if add_h2:
        return t.replace("## よくある質問", "## 口コミ返信のやり方\n口コミ返信は24時間以内に返します。\n\n## よくある質問")
    return t.replace("## 費用", "## 口コミ返信の費用")


def _with_link(text):
    return text.replace("本文A。\n\n", "本文A。\n\n" + LINK)


def test_early_undo_only_its_parts():
    import rewrite_rollback as R
    print("\n■ rewrite_rollback: early で変えた部分（題・H2の1本・FAQ）だけを戻す")
    d = {"after_title": "工務店のMEOの始め方と口コミ返信"}
    for name, add_h2 in (("H2の言い換え", False), ("H2を1本足した", True)):
        now = _with_link(_after_early(BEFORE, add_h2))
        got, why = R.undo_early(BEFORE, now, d)
        check(f"{name}: 題・H2・FAQ を戻し、後から入った内部リンクは残す", (got, why), (_with_link(BEFORE), ""))
    moved = _after_early(BEFORE).replace("## 始め方", "## 始め方の手順")
    check("early の後に別の見出しも変わっていたら戻さない（理由を返す）",
          R.undo_early(BEFORE, moved, d)[0], None)
    retitled = _after_early(BEFORE).replace("始め方と口コミ返信", "始め方2026")
    check("early の後に題がまた変わっていたら戻さない", R.undo_early(BEFORE, retitled, d)[0], None)


def test_early_rollback_condition_and_later_rewrites():
    import effect_ab as EA
    import rewrite_rollback as R
    print("\n■ rewrite_rollback: early も28日・同じ週数の対照で判定し、効かなければ戻す")
    at = date.today() - timedelta(days=40)
    pubs, daily, add = _world(at)
    add("worse", at - timedelta(days=21), scale_after=0.5)
    add("ranked", at - timedelta(days=21), scale_after=0.5, pos=(20.0, 10.0))
    add("relinked", at - timedelta(days=21), scale_after=0.5)
    real = (R.ROOT, R.LOG, R.DECIDED, R.published, EA.daily_by_slug, EA.interventions, sys.argv)
    with tempfile.TemporaryDirectory() as td:
        r = Path(td)
        (r / "articles").mkdir()
        (r / "data" / "rewrite_before").mkdir(parents=True)
        lines = []
        for slug in ("worse", "ranked", "relinked"):
            bp = r / "data" / "rewrite_before" / f"{slug}@{at}.md"
            bp.write_bytes(BEFORE.encode("utf-8"))
            after = _after_early(BEFORE).encode("utf-8")
            (r / "articles" / f"{slug}.md").write_bytes(after)
            lines.append({"at": f"{at} 10:00", "by": "auto_rewrite", "slug": slug, "kind": "early", "ok": True,
                          "note": "直しました（工務店の… → 工務店の…）", "before_title": "工務店のMEOの始め方",
                          "after_title": "工務店のMEOの始め方と口コミ返信",
                          "before_path": bp.relative_to(r).as_posix(), "after_sha": hashlib.sha1(after).hexdigest()})
        # relinked はその後に内部リンクが足され、さらに別の書き直し（aio）が入った
        rel = r / "articles" / "relinked.md"
        rel.write_text(_with_link(rel.read_text(encoding="utf-8")), encoding="utf-8", newline="")
        lines.append({"at": f"{at + timedelta(days=10)} 10:00", "by": "auto_rewrite", "slug": "relinked",
                      "kind": "aio", "ok": True, "note": "直しました（…）"})
        log = r / "auto_fix.jsonl"
        log.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines), encoding="utf-8")
        try:
            R.ROOT, R.LOG, R.DECIDED = r, log, r / "decided.json"
            R.published = lambda: pubs
            EA.daily_by_slug = lambda: (daily, None, None)
            EA.interventions = lambda: [{"slug": x["slug"], "at": x["at"][:10], "kind": x["kind"]} for x in lines]
            check("early は戻す候補に入る（before_path がある分）",
                  sorted(d["slug"] for d in R.entries()), ["ranked", "relinked", "worse"])
            sys.argv = ["rewrite_rollback.py", "--write"]
            with redirect_stdout(io.StringIO()) as o:
                R.main()
            out = o.getvalue()
            got = json.loads(R.DECIDED.read_text(encoding="utf-8"))
            check("表示が対照の8割を割り順位も上がっていなければ、直す前へ戻す（だれも触っていなければ原稿ごと）",
                  ((r / "articles" / "worse.md").read_text(encoding="utf-8") == BEFORE,
                   got[f"worse@{at}"]["rolled_back"], got[f"worse@{at}"]["kind"], got[f"worse@{at}"]["control_n"]),
                  (True, True, "early", 13))
            check("順位が上がっていれば戻さない",
                  ((r / "articles" / "ranked.md").read_text(encoding="utf-8") == _after_early(BEFORE),
                   got[f"ranked@{at}"]["rolled_back"]), (True, False))
            check("後から別の書き直しが入っていたら戻さず要対応",
                  (rel.read_text(encoding="utf-8") == _with_link(_after_early(BEFORE)),
                   got[f"relinked@{at}"]["rolled_back"], "要対応: relinked" in out), (True, False, True))
            # 書き直しが無く内部リンクだけ足された記事は、early の部分だけ戻す
            lines.pop()
            log.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                ok = R.restore("relinked", lines[2])
            check("内部リンクの追加だけなら early の部分だけ戻し、リンクは残す",
                  (ok, rel.read_text(encoding="utf-8") == _with_link(BEFORE)), (True, True))
        finally:
            R.ROOT, R.LOG, R.DECIDED, R.published, EA.daily_by_slug, EA.interventions, sys.argv = real


def test_learn_reads_only_same_age_title_decisions():
    import learn as L
    print("\n■ learn: 題の戻しの学びは、同じ週数の対照で判定した題の分だけを数える")
    old = {f"a{i}@2026-08-25": {"ratio": 0.3, "control": 1.6, "pos_gain": 0, "rolled_back": True} for i in range(6)}
    early = {f"e{i}@2026-09-01": {"ratio": 0.3, "control": 0.9, "pos_gain": 0, "rolled_back": True,
                                  "control_n": 12, "kind": "early"} for i in range(6)}
    title = {f"t{i}@2026-09-01": {"ratio": 0.3, "control": 0.9, "pos_gain": 0, "rolled_back": i < 4,
                                  "control_n": 12, "kind": "title"} for i in range(6)}
    real = L.DATA
    with tempfile.TemporaryDirectory() as td:
        try:
            L.DATA = Path(td)
            for data, want in (({**old, **early}, 0), ({**old, **early, **title}, 1)):
                (Path(td) / "rollback_decisions.json").write_text(json.dumps(data), encoding="utf-8")
                check(f"旧の物差しの判定・early を数えない（学び {want}件）", len(L.rollback_signal()), want)
            check("学びの根拠は題の判定の本数", "4/6本" in L.rollback_signal()[0][5], True)
        finally:
            L.DATA = real
