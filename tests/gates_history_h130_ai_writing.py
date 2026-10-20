# -*- coding: utf-8 -*-
"""2026-10-20 運用者の決定「AIぽい言い回しは自動で直すこと」の門（scripts/ai_writing.py・auto_rewrite --kind aiwriting）。

- textlint が AI っぽい言い回し（誇張・「〜することができます」・箇条書きの「**札**:」・太字の札）を拾い、
  本サイトの書式の決まり（質問形の H2・==マーカー==・定義ブロック・FAQ・「」の引用・固有名詞・断り書き）は拾わない
- 機械の直しが数字・題・見出し・リンクを変えたら書かない（台帳に戻したことを残す）
- 判断の直しの検算（rewrite_guard）が悪い直しを止め、良い直しを通す（auto_rewrite --kind aiwriting --selftest）
- 公開前の品質ループが採点の前に言い回しを直し、届かなければ直しの指示に残った指摘を添える
- ワークフロー: 依存（npm ci）・週次の直し（鍵を外した中・自己診断の後）・findings の推移・書く AI への案内
本物の claude・ネットは呼ばない（AI の直しは差し替える。textlint は手元の node で動かし、無ければその確かめだけ飛ばす）。
"""
import contextlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


@contextlib.contextmanager
def patched(*items):
    old = [(o, n, getattr(o, n, None), hasattr(o, n)) for o, n, _ in items]
    try:
        for o, n, v in items:
            setattr(o, n, v)
        yield
    finally:
        for o, n, v, had in old:
            if had:
                setattr(o, n, v)
            else:
                delattr(o, n)


def quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


BAD = {
    "@textlint-ja/ai-writing/no-ai-hype-expressions": "この方法なら、問い合わせを大幅に増やせます。",
    "ja-technical-writing/ja-no-redundant-expression": "補助金の対象かどうかは、事務局に確認することができます。",
    "@textlint-ja/ai-writing/no-ai-list-formatting": "- **費用の目安**: 月3万円からです",
    "@textlint-ja/ai-writing/no-ai-emphasis-patterns": "**注意**してください。",
}

# 本サイトの書式の決まりどおりの原稿（拾ってはいけない）
GOOD = """---
title: AIO対策とは？完璧な記事より先に決める3つのこと
description: 完璧な記事を目指すより、AIの答えに引用される形を先に決めることが大事です。大幅に伸びた例もあります。
keyword: aio 対策
faq:
  - q: AIO対策は完全に無料でできますか？
    a: 完全に無料で始められる施策もあります。
---

## AIO対策とは？

**AIO対策は、AIの回答に自社の情報が引用されるように記事を整える取り組みです。**

AIO対策の手順は、検索の実績を見る、直す記事を決める、冒頭を言い切る、表を置く、FAQを整えるという順で進めます。

==確かめた結果で、打つ手は分かれます。==

<div class="definition-box">
完璧な答えを1つに絞ることができます。大幅に変わります。
</div>

中小企業基盤整備機構が公表した調査では、AIの利用が広がっています。

請求書は三つ折りにして、長3封筒に入れます。

SECURITY ACTION の宣言（★一つ星または★★二つ星）が要件です。

事務局の案内には「内容に相違がなければ承認を行います。完全に一致させてください」と書かれています。

申請書類はお客様が作成し、当社は内容の確認と助言を行います。

| 比較 | 自社で行う | 外部に任せる |
|:--|:--|:--|
| 費用 | 月0円 | 月3万円〜 |

詳しくは[料金の記事](/aio/hiyou/)をご覧ください。

```text
完璧なプロンプトで大幅に改善することができます
```

## よくある質問

### AIO対策は完全に無料でできますか？

完全に無料で始められる施策もあります。完璧な記事は要りません。
"""


def _tl():
    import ai_writing as AW
    if not AW.available():
        print("  --  textlint が入っていないため、本物の検出の確かめを飛ばします（npm ci --prefix automation/textlint）")
        return None
    return AW


def test_detects_ai_phrasing_and_ignores_house_style():
    print("\n■ AI っぽい言い回しを拾い、本サイトの書式の決まりどおりの文は拾わない（本物の textlint）")
    AW = _tl()
    if not AW:
        return
    texts = ["---\ntitle: 見本\n---\n\n" + s + "\n" for s in BAD.values()] + [GOOD]
    got = AW.detect_texts(texts)
    for (rule, sent), hits in zip(BAD.items(), got[:-1]):
        check(f"拾う: {sent[:24]}…（{rule.rsplit('/', 1)[-1]}）", rule in {h["rule"] for h in hits or []}, True)
    check("書式の決まり（質問形の H2・マーカー・定義ブロック・FAQ・引用・固有名詞・三つ折り・★★・断り書き・表・"
          "コード・フロントマター）は1件も拾わない", [(h["line"], h["rule"].rsplit("/", 1)[-1]) for h in got[-1] or []], [])
    check("行の番号は原稿の行のまま（フロントマターの行も数える）", got[0][0]["line"] if got[0] else None, 5)


def test_stopped_rules_and_lockfile():
    print("\n■ 書式の決まりとぶつかるルールは止め、止めた理由を残す。版は package-lock.json で固定")
    import ai_writing as AW
    off = AW.stopped()
    for r in ("sentence-length", "no-exclamation-question-mark", "max-kanji-continuous-len", "arabic-kanji-numbers",
              "ja-no-mixed-period", "no-doubled-joshi", "max-ten"):
        check(f"止めた: {r}", f"ja-technical-writing/{r}" in off, True)
    notes = (ROOT / "automation" / "textlint" / "RULES.txt").read_text(encoding="utf-8")
    check("止めたルールの理由が RULES.txt にある", all(r.split("/")[-1] in notes for r in off), True)
    lock = json.loads((ROOT / "automation" / "textlint" / "package-lock.json").read_text(encoding="utf-8"))
    pk = lock.get("packages") or {}
    check("版を固定（textlint 15.8.0・ja-technical-writing 12.0.2・ai-writing 1.7.0）",
          (pk.get("node_modules/textlint", {}).get("version"),
           pk.get("node_modules/textlint-rule-preset-ja-technical-writing", {}).get("version"),
           pk.get("node_modules/@textlint-ja/textlint-rule-preset-ai-writing", {}).get("version")),
          ("15.8.0", "12.0.2", "1.7.0"))
    pj = json.loads((ROOT / "automation" / "textlint" / "package.json").read_text(encoding="utf-8"))
    check("package.json は ^ や ~ を使わず版をそのまま書く",
          all(re.fullmatch(r"\d+\.\d+\.\d+", v) for v in pj["dependencies"].values()), True)
    fix = json.loads((ROOT / "automation" / "textlint" / ".textlintrc.fix.json").read_text(encoding="utf-8"))
    on = sorted(k for k, v in fix["rules"]["preset-ja-technical-writing"].items() if v is True)
    check("機械で直すのは意味の変わらないルールだけ", on,
          sorted(r.rsplit("/", 1)[-1] for r in AW.FIX_RULES))
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    check("node_modules は Git に入れない", "automation/textlint/node_modules/" in gi, True)
    import agent_guard as G
    check("記事の AI がルールを止めても戻す（守る場所）", "automation/textlint" in G.PROTECTED, True)


def test_machine_fix_keeps_numbers_title_and_links():
    print("\n■ 機械の直しが数字・題・見出し・リンクを変えたら書かない（台帳に戻したことを残す）")
    import ai_writing as AW
    art = ("---\ntitle: AI検索対策の費用の目安\nkeyword: AI検索対策 費用\n---\n\n## 費用はいくら？\n\n"
           "費用は月3万円からです。比較の表は、読み手の目が止まる場所に置きます。\n\n"
           "詳しくは[料金の記事](/aio/hiyou/)と[次の記事](/aio/a/)と[別の記事](/aio/b/)をご覧ください。\n")
    bad = {
        "数字を変える": art.replace("月3万円", "月30万円"),
        "題を変える": art.replace("費用の目安", "費用"),
        "見出しを変える": art.replace("## 費用はいくら？", "## 費用"),
        "リンクを外す": art.replace("[料金の記事](/aio/hiyou/)", "料金の記事"),
    }
    with tempfile.TemporaryDirectory() as d:
        p, log = Path(d) / "zz-aio.md", Path(d) / "auto_fix.jsonl"
        for name, out in bad.items():
            p.write_text(art, encoding="utf-8")
            with patched((AW, "FIXER", lambda t, o=out: (o, ["ja-technical-writing/ja-no-abusage"])), (AW, "LOG", log)):
                st, why = AW.machine_fix("zz-aio", path=p)
            check(f"{name}: 戻す", (st, p.read_text(encoding="utf-8") == art), ("reverted", True))
        good = art.replace("目が止まる", "目が留まる")
        p.write_text(art, encoding="utf-8")
        with patched((AW, "FIXER", lambda t: (good, ["ja-technical-writing/ja-no-abusage"])), (AW, "LOG", log)):
            st, why = AW.machine_fix("zz-aio", path=p)
        check("誤用の辞書の直しだけなら書く", (st, p.read_text(encoding="utf-8") == good), ("fixed", True))
        rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
        check("台帳に戻した4件と直した1件", [r["ok"] for r in rows], [False, False, False, False, True])
        check("台帳は ai_writing の機械の直しとして残す", {(r["by"], r["kind"]) for r in rows}, {("ai_writing", "textlint-fix")})
    tl = _tl()
    if tl:
        after, st, why, rules = tl.fix_text(art)
        check("本物の textlint の直し: 「目が止まる」→「目が留まる」だけ", (st, after == art.replace("目が止まる", "目が留まる")),
              ("fixed", True))


def test_rewrite_guard_and_selftest():
    print("\n■ 判断の直しの検算: 指摘の文だけ・指摘が減った・引用とフロントマターを変えない（悪い直しを止める）")
    import ai_writing as AW
    art = ("---\ntitle: 見本の記事の題です\n---\n\nこの方法なら、問い合わせを大幅に増やせます。\n\n"
           "事務局は「内容に相違がなければ承認を行います」と案内しています。\n\n費用は月3万円からです。\n")
    hits = [{"rule": "@textlint-ja/ai-writing/no-ai-hype-expressions", "line": 5, "col": 13,
             "message": "誇張", "sentence": "この方法なら、問い合わせを大幅に増やせます。"}]
    fake = lambda texts: [[h for h in hits if "大幅に" in t] for t in texts]   # noqa: E731  「大幅に」が残れば1件
    good = art.replace("大幅に増やせます", "増やせます")
    cases = [("指摘の文だけを言い換える", good, ""),
             ("言い回しを残す", art.replace("この方法なら、", "この方法では、"), "指摘が減っていません"),
             ("ほかの行も書き換える（20字を超える）",
              good.replace("費用は月3万円からです。", "料金の体系は、相談の内容と記事の本数で変わり、最も安い場合で月3万円からとなっております。"),
              "指摘の無い行まで"),
             ("ほかの行の句読点だけ直す（通す）", good.replace("費用は月3万円からです。", "費用は、月3万円からです。"), ""),
             ("引用を変える", good.replace("承認を行います", "承認します"), "かぎ括弧の引用"),
             ("題を変える", good.replace("見本の記事の題です", "見本の題"), "フロントマター"),
             ("行を足す", good.replace("増やせます。", "増やせます。\n\n今すぐ相談してください。"), "行の数")]
    with patched((AW, "DETECT", fake)):
        for name, after, want in cases:
            why = AW.rewrite_guard(art, after, hits, 1)
            check(f"{name}: " + ("通す" if not want else "止める"), (why.startswith(want) if want else why == "",
                                                                    bool(why) == bool(want)), (True, True))
    tl = _tl()
    if tl:
        rc, out = quiet(tl.selftest)
        check("自己診断（本物の textlint）: 悪い直しを全部止め、良い直しを通す", (rc, "NG" in out), (0, False))


def test_auto_rewrite_kind_aiwriting_wiring():
    print("\n■ auto_rewrite の種類 aiwriting: 指摘の行だけを渡し、既存の検算の後に rewrite_guard を通す")
    import auto_rewrite as A
    item = {"kind": "aiwriting", "slug": "zz-aio", "site": "ai-lab", "count": 2, "why": "AIっぽい言い回し 2か所",
            "hits": [{"rule": "@textlint-ja/ai-writing/no-ai-hype-expressions", "line": 12, "col": 3, "message": "誇張",
                      "sentence": "問い合わせを大幅に増やせます。"}]}
    prompt, allowed = A.build_prompt(item)
    check("指示に行番号と指摘の文と直し方が入る", ("12行目" in prompt, "問い合わせを大幅に増やせます。" in prompt,
                                     "数字か条件に言い換える" in prompt), (True, True, True))
    check("指示で数字・体験・引用・FAQ を作らせない／変えさせない",
          all(w in prompt for w in ("本文に無い数字は書かない", "体験", "「」の中の引用", "よくある質問")), True)
    check("増えてよい数字は無い（allowed は空）", allowed, "")
    src = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    check("既存の検算（check）の後に rewrite_guard を通す",
          src.index("ng = check(slug, before, before_warns") < src.index("ng = AW.rewrite_guard("), True)
    check("--kind aiwriting --selftest は言い回しの自己診断（ほかの書き直しの自己診断と分ける）",
          'if a.selftest and a.kind == "aiwriting":' in src and "return AW.selftest()" in src, True)
    check("名指し（--slugs）でも作れる", 'elif kind == "aiwriting" and' in src, True)


def test_items_respect_per_site_quota():
    print("\n■ 週次の候補は指摘の多い順に社ごとに4本（sites/<id>.json の ai_writing_weekly で変えられる）")
    import ai_writing as AW
    got = {f"a{i}": [{"rule": "r", "line": 1, "col": 0, "message": "m", "sentence": "s"}] * (10 - i) for i in range(6)}
    got.update({f"b{i}": [{"rule": "r", "line": 1, "col": 0, "message": "m", "sentence": "s"}] * 3 for i in range(2)})
    with patched((AW, "published", lambda sites=(): list(got)), (AW, "detect_slugs", lambda slugs: got),
                 (AW, "site_of", lambda s: "zz" if s.startswith("a") else "yy"),
                 (AW, "per_site_quota", lambda sid: 4 if sid == "zz" else 1)):
        rows = AW.items()
    check("社 zz は多い順に4本・社 yy は設定どおり1本", [x["slug"] for x in rows], ["a0", "a1", "a2", "a3", "b0"])
    check("1回に渡す指摘は12件まで（全体の数は count に残す）", (len(rows[0]["hits"]), rows[0]["count"]), (10, 10))


def test_quality_loop_polishes_before_scoring():
    print("\n■ 公開前の品質ループ: 採点の前に言い回しを直し、届かなければ残った指摘を直しの指示に添える")
    import ai_writing as AW
    import quality_loop as QL
    body = ("---\ntitle: AIO対策のはじめ方を中小企業向けに解説\nslug: zz-aio\ncategory: aio\nkeyword: aio 対策\n"
            "date: 2026-10-20\ndescription: 説明です。\n---\nこの記事は中小企業の担当者向けです。\n\n"
            "## 何から始めるか\n\n当社では、最初に検索の実績を見てから直す記事を決めています。問い合わせを大幅に増やせます。\n")
    hit = {"rule": "@textlint-ja/ai-writing/no-ai-hype-expressions", "line": 13, "col": 30, "message": "誇張",
           "sentence": "問い合わせを大幅に増やせます。"}
    fake = lambda texts: [[hit] if "大幅に" in t else [] for t in texts]   # noqa: E731
    seen = {"weak": "", "aiw": 0}
    quote = "当社では、最初に検索の実績を見てから直す記事を決めています。"

    def answer(v):
        ax = {"score": v, "quote": quote, "weaknesses": ["一次情報の数字が無い"]}
        return "```json\n" + json.dumps({"originality": ax, "extractability": ax, "decision": ax}, ensure_ascii=False) + "\n```"
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "articles").mkdir()
        p = root / "articles" / "zz-aio.md"

        def aiw_ok(slug, blocked):
            seen["aiw"] += 1
            p.write_text(p.read_text(encoding="utf-8").replace("大幅に増やせます", "増やせます"), encoding="utf-8")
            return True, "直しました（テスト）"

        def aiw_ng(slug, blocked):
            seen["aiw"] += 1
            return False, "指摘が減っていません（テスト）"

        def imp(slug, sc, blocked):
            seen["weak"] = QL.weak_text(sc)
            return False, "戻しました（テスト）"
        base = [(QL, "ARTICLES", root / "articles"), (QL, "LOG", root / "q.jsonl"), (QL, "IMPROVE", imp),
                (QL, "blocked_lines", lambda: set()), (QL, "site_of", lambda s: "ai-lab"),
                (AW, "DETECT", fake), (AW, "FIXER", lambda t: (t, [])), (AW, "available", lambda: True),
                (AW, "LOG", root / "auto_fix.jsonl")]
        # 1) 言い回しを直してから採点（届く）
        p.write_text(body, encoding="utf-8")
        with patched(*base, (QL, "ASK", lambda pr, cwd: answer(95)), (QL, "AIWRITE", aiw_ok)):
            res, out = quiet(QL.run, ["zz-aio"], "new", QL.Budget(None))
        rows = [json.loads(x) for x in (root / "q.jsonl").read_text(encoding="utf-8").splitlines()]
        check("採点の前に言い回しを直す（台帳の順: aiwriting → score → pass）",
              [r["action"] for r in rows], ["aiwriting", "score", "pass"])
        check("直した後の指摘の数を残す", (rows[0]["before"], rows[0]["after"]), (1, 0))
        check("届いた（言い回しの直しで公開を止めない）", res, {"passed": 1})
        # 2) 言い回しが残ったまま届かない → 直しの指示に残った指摘を添える
        p.write_text(body, encoding="utf-8")
        (root / "q.jsonl").unlink()
        with patched(*base, (QL, "ASK", lambda pr, cwd: answer(60)), (QL, "AIWRITE", aiw_ng)):
            res, out = quiet(QL.run, ["zz-aio"], "new", QL.Budget(None), rounds=1)
        check("直しの指示に残った言い回しを添える", ("AIっぽい言い回し" in seen["weak"], "大幅に" in seen["weak"]), (True, True))
        # 3) 公開済みの記事の採点し直しでは採点の前の直しをしない（週次の auto_rewrite --kind aiwriting の受け持ち）
        seen["aiw"] = 0
        p.write_text(body.replace("date: 2026-10-20\n", "date: 2026-10-20\nscore: 92\n"), encoding="utf-8")
        with patched(*base, (QL, "ASK", lambda pr, cwd: answer(95)), (QL, "AIWRITE", aiw_ok)):
            quiet(QL.run, ["zz-aio"], "rescore", QL.Budget(None))
        check("公開済みの採点し直しでは採点の前の直しを呼ばない", seen["aiw"], 0)
        # 4) textlint が無い回は飛ばして採点を続ける
        p.write_text(body, encoding="utf-8")
        with patched(*base, (AW, "available", lambda: False), (QL, "ASK", lambda pr, cwd: answer(95)),
                     (QL, "AIWRITE", aiw_ok)):
            res, out = quiet(QL.run, ["zz-aio"], "new", QL.Budget(None))
        check("textlint が無くても採点は続く", (res, "textlint が入っていません" in out), ({"passed": 1}, True))


def test_report_flags_increase():
    print("\n■ findings: 検出件数の推移。合計と1本あたりの両方が増えた社は要対応")
    import ai_writing as AW
    import sites as S
    got = {"a1": [{}] * 3, "a2": [{}] * 3}
    with tempfile.TemporaryDirectory() as d:
        tr = Path(d) / "trend.json"
        tr.write_text(json.dumps({"2026-W41": {"zz": {"articles": 2, "hits": 4, "failed": 0}}}), encoding="utf-8")
        with patched((AW, "available", lambda: True), (AW, "published", lambda sites=(): list(got)),
                     (AW, "detect_slugs", lambda slugs: got), (AW, "site_of", lambda s: "zz"),
                     (S, "public_id", lambda sid: sid)):
            from datetime import date
            _, out = quiet(AW.report, date(2026, 10, 20), tr)
            check("増えた → 要対応", ("要対応: zz" in out, "AI_WRITING_OK=no" in out), (True, True))
            got2 = {"a1": [{}], "a2": []}
            with patched((AW, "detect_slugs", lambda slugs: got2), (AW, "published", lambda sites=(): list(got2))):
                _, out = quiet(AW.report, date(2026, 10, 27), tr)
            check("減った → 要対応なし", ("要対応" in out, "AI_WRITING_OK=yes" in out), (False, True))
        hist = json.loads(tr.read_text(encoding="utf-8"))
        check("週ごとに件数だけを残す（記事の名前は残さない）", (sorted(hist), "a1" in tr.read_text(encoding="utf-8")),
              (["2026-W41", "2026-W43", "2026-W44"], False))
    src = (ROOT / "scripts" / "findings.py").read_text(encoding="utf-8")
    check("findings が週次に推移を見る", '"ai_writing.py --report"' in src, True)


def test_brief_and_workflows():
    print("\n■ 書く AI への案内（12行まで・止めたルールは載せない）と、ワークフローのつなぎ")
    import ai_writing as AW
    lines = AW.brief()
    check("案内は12行まで", 0 < len(lines) <= 12, True)
    check("止めたルール（疑問符・漢字の連続）は案内に無い", any("？" in x or "漢字" in x for x in lines), False)
    sb = (ROOT / "scripts" / "site_brief.py").read_text(encoding="utf-8")
    check("site_brief が案内を出す", "ai_writing.brief()" in sb, True)
    pm = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8")
    pl = (ROOT / ".github" / "workflows" / "pipeline.yml").read_text(encoding="utf-8")
    wk = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    for name, y in (("記事の枠", pm), ("救済", pl), ("週次", wk)):
        check(f"{name}: textlint を npm ci で入れる（版は lock）", "npm ci --prefix automation/textlint" in y, True)
    step = wk[wk.index("- name: 見出しを質問形へ"):wk.index("- name: 効かなかった直しを戻す")]
    check("週次の言い回しの直しは、鍵を外した手順の中（verify の後）で動く",
          step.index("agent_guard.py --verify") < step.index("--write --kind aiwriting"), True)
    check("週次: 機械の直し → 自己診断 → 判断の直しの順",
          step.index("ai_writing.py --fix --write") < step.index("--kind aiwriting --selftest")
          < step.index("--write --kind aiwriting"), True)
    lock_at, unlock_at = wk.index("id: lock_kinds"), wk.index("質問形・鮮度などの書き直しの後に作業場へ鍵を戻す")
    check("鍵を外してから戻すまでの間", lock_at < wk.index("--write --kind aiwriting") < unlock_at, True)
    check("推移の記録をコミットする", "data/ai_writing_trend.json" in wk, True)
    ql = (ROOT / "scripts" / "quality_loop.py").read_text(encoding="utf-8")
    check("公開前の品質ループは採点の前に polish を呼ぶ（公開済みの採点し直しでは呼ばない）",
          re.search(r"if not published:\n\s+#[^\n]*\n\s+polish\(slug, budget, ctx, base\)\n\s+survey\(slug, budget, base\)\n\s+sc, why = score\(slug\)", ql)
          is not None, True)
