# -*- coding: utf-8 -*-
"""2026-11-12 運用者の決定（h163 の続き）。題の書き直し（title）の効きを表示・順位で測っていたため、
題が狙うクリック率が上がっても「効かない」と出て、直す前のクリックがほぼ0の記事ばかりでは差も出なかった。
同じ条件（直す前の順位帯・クリック率が目安の半分未満）の触っていない記事でも、28日でクリック率が0.87%→2.76%に
上がっていた（平均への戻り）。そこで:
  1. title はクリック率で判定する。対照は直す前の条件がそろった触っていない記事。クリックの母数が足りない・
     表示が消えた記事は「判定できない」とし、効いた・効かないに数えず、戻しもしない
  2. 題の書き直しの候補は、目安のクリック率まで上がれば28日でクリックが3本以上増える記事だけ
     （11月12日の週次で題を直した10本は、目安まで上がっても1本あたり0.2〜1.4本しか増えない記事だった）"""
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

AT = date.today() - timedelta(days=40)


def _series(imp, pos, clk_before, clk_after, imp_after=None):
    """直した日 AT の前後。clk_* は日の番号 i（前は負・後は正）からその日のクリック数を返す関数"""
    out = {}
    for i in range(-60, 45):
        n = imp if i <= 0 else (imp if imp_after is None else imp_after)
        c = (clk_before if i < 0 else clk_after)(i) if n else 0
        out[(AT + timedelta(days=i)).isoformat()] = [n, c, pos * n]
    return out


ZERO = lambda i: 0
EVERY4 = lambda i: 1 if i % 4 == 0 else 0       # 28日で7本（表示280回で2.5%）
DAILY = lambda i: 1                              # 28日で28本（10%）


def _world():
    daily = {}
    for k in range(12):      # 直す前のクリック率が低い（目安の半分未満）。何もしなくても後で2.5%に上がる
        daily[f"zz-low{k}"] = _series(10, 7.0, ZERO, EVERY4)
    for k in range(12):      # 直す前のクリック率が高い。後も同じ
        daily[f"zz-high{k}"] = _series(10, 7.0, DAILY, DAILY)
    for k in range(5):
        daily[f"zz-up{k}"] = _series(10, 7.0, ZERO, DAILY)        # 対照の上がり幅を大きく超えた
        daily[f"zz-same{k}"] = _series(10, 7.0, ZERO, EVERY4)     # 対照と同じだけ上がった
        daily[f"zz-small{k}"] = _series(1, 7.0, ZERO, ZERO)       # 表示28回。クリックの母数が足りない
        daily[f"zz-gone{k}"] = _series(10, 7.0, ZERO, ZERO, imp_after=0)   # 直した後に表示が消えた
    daily["zz-down"] = _series(10, 7.0, DAILY, lambda i: 1 if i in (5, 20) else 0)   # 28本 → 2本
    pubs = {s: AT - timedelta(days=90) for s in daily}
    return daily, pubs


def test_title_judged_by_ctr_against_same_condition_controls():
    import effect_ab as EA
    print("\n■ 題の書き直しの効きはクリック率で、直す前の条件がそろった触っていない記事と比べる")
    daily, pubs = _world()
    today = date.today()
    acts = [{"slug": f"zz-{w}{k}", "at": AT.isoformat(), "kind": "title"} for w in ("up", "same", "small", "gone")
            for k in range(5)] + [{"slug": "zz-down", "at": AT.isoformat(), "kind": "title"}]
    one = lambda s: EA.title_ctr(daily, s, AT, 28, today, acts, pubs)
    up, same, small, gone, down = one("zz-up0"), one("zz-same0"), one("zz-small0"), one("zz-gone0"), one("zz-down")
    check("対照は直す前の条件がそろった記事だけ（クリック率の低い12本。高い記事・書き直した記事は入らない）",
          (up["status"], up["ctrl_n"]), ("ok", 12))
    check("効かなかったときに見込むクリック = 後の表示 × (前のクリック率 + 対照の上がり幅)", round(up["exp_clk"], 1), 7.0)
    check("対照の上がり幅を大きく超えたら「効いた」", up["ctr_verdict"], "効いた")
    check("対照と同じだけ上がっただけなら「効かない」（平均への戻りを効いたと読まない）", same["ctr_verdict"], "効かない")
    check("クリックの母数が足りなければ「判定できない」", small["ctr_verdict"], "判定できない")
    check("直した後に表示が消えた記事は「判定できない」（題が原因でない消え方）", gone["status"], "表示が消えた")
    check("クリック率が対照の見込みを大きく割ったら「悪化」", down["ctr_verdict"], "悪化")

    res = EA.rewrite_effects(acts[:5], daily, today, pubs=pubs, touched=acts)
    check("種類の判定: 表示・順位が対照と同じでも、クリック率が上がった題は「効いた」",
          res["kinds"]["title"]["verdict"], "効いた")
    res = EA.rewrite_effects(acts[5:10], daily, today, pubs=pubs, touched=acts)
    check("種類の判定: 対照と同じだけ上がっただけなら「効かない」", res["kinds"]["title"]["verdict"], "効かない")
    res = EA.rewrite_effects(acts[10:15], daily, today, pubs=pubs, touched=acts)
    check("種類の判定: クリックの合計が足りなければ「判定できない」（効かないに数えない）",
          res["kinds"]["title"]["verdict"], "判定できない")
    res = EA.rewrite_effects(acts[15:20], daily, today, pubs=pubs, touched=acts)
    check("種類の判定: 表示が消えた記事だけなら「判定できない」",
          (res["kinds"]["title"]["verdict"], res["kinds"]["title"]["unknown"]), ("判定できない", 5))
    res = EA.rewrite_effects([dict(a, kind="title（浮き枠）") for a in acts[:5]], daily, today, pubs=pubs, touched=acts)
    check("浮いた枠の題の直しも同じ物差し", res["kinds"]["title（浮き枠）"]["verdict"], "効いた")


def test_title_rollback_only_when_ctr_clearly_worse():
    import effect_ab as EA
    import rewrite_rollback as R
    import client_private as CP
    print("\n■ 題を戻すのはクリック率が対照の見込みをはっきり割ったときだけ。判定できない題は戻さない")
    daily, pubs = _world()
    ent = [{"slug": s, "at": f"{AT.isoformat()} 10:00", "by": "auto_rewrite", "kind": "title", "ok": True,
            "note": "直しました", "before_title": "前の題", "after_title": "後の題"}
           for s in ("zz-down", "zz-small0", "zz-gone0", "zz-same0")]
    calls, saved = [], []
    with tempfile.TemporaryDirectory() as td, \
            mock.patch.object(R, "entries", lambda: ent), \
            mock.patch.object(R, "published", lambda: pubs), \
            mock.patch.object(R, "DECIDED", Path(td) / "d.json"), \
            mock.patch.object(R, "restore", lambda slug, d: calls.append(slug) or True), \
            mock.patch.object(EA, "daily_by_slug", lambda: (daily, None, None)), \
            mock.patch.object(EA, "rewrites", lambda *a: []), \
            mock.patch.object(CP, "load_dict", lambda *a, **k: {}), \
            mock.patch.object(CP, "save_dict", lambda rel, dd, *a, **k: saved.append(dict(dd))), \
            mock.patch.object(CP, "append_jsonl", lambda *a, **k: None), \
            mock.patch.object(sys, "argv", ["rewrite_rollback.py", "--write"]):
        with redirect_stdout(io.StringIO()) as o:
            R.main()
    out = o.getvalue()
    got = saved[-1] if saved else {}
    check("戻したのはクリック率が見込みを割った1本だけ（表示が消えた・母数が足りない・対照並みは戻さない）", calls, ["zz-down"])
    check("判定できない題も判定済みにし（同じ28日は何度見ても同じ）、印を残す",
          sorted(k.split("@")[0] for k, v in got.items() if v.get("unknown")), ["zz-gone0", "zz-small0"])
    check("出す印に判定できない本数がある", ("ROLLED_BACK=1" in out, "UNKNOWN=2" in out), (True, True))
    check("台帳の形（ratio・control・pos_gain・rolled_back）を保つ",
          all({"ratio", "control", "pos_gain", "rolled_back"} <= set(v) for v in got.values()), True)
    src = (ROOT / "scripts" / "learn.py").read_text(encoding="utf-8")
    check("学び（戻された割合）に判定できない題を数えない", 'not r.get("unknown")' in src, True)


def test_title_candidates_need_three_more_clicks():
    import rank_up
    import sites
    print("\n■ 題の書き直しの候補は、目安のクリック率まで上がれば28日でクリックが3本以上増える記事だけ")
    check("下限は3本", rank_up.TITLE_MIN_GAIN, 3)
    check("増える見込み = 表示 × 目安のクリック率 − いまのクリック（7位・表示100・クリック0 → 3.5本）",
          round(rank_up.title_gain(100, 0, 7.0), 2), 3.5)
    fm = "---\ntitle: {t}\nkeyword: {k}\ndate: 2026-08-01\n---\n本文\n"
    texts = {"zz-big": fm.format(t="経理代行の費用相場｜月額の目安", k="経理代行 費用"),
             "zz-tiny": fm.format(t="記帳代行の費用｜月額の目安", k="記帳代行 費用"),
             "zz-deco": fm.format(t="記帳代行の選び方【2026年】", k="記帳代行 選び方")}
    pg = lambda s, pos, imp, clk, kw: {"slug": s, "url": f"https://zz.example/{s}", "pos": pos, "imp": imp,
                                        "clicks": clk, "kws": [(kw, pos, imp)], "urls": 1}
    pages = {p["url"]: p for p in (pg("zz-big", 7.0, 120, 0, "経理代行 費用"), pg("zz-tiny", 7.0, 40, 0, "記帳代行 費用"),
                                   pg("zz-deco", 6.0, 40, 0, "記帳代行 選び方"))}
    with mock.patch.object(rank_up, "fetch", lambda domain, days=28: pages), \
            mock.patch.object(rank_up, "articles", lambda: texts), \
            mock.patch.object(sites, "load_all", lambda: {"client-zz": {"id": "client-zz", "domain": "zz.example"}}):
        got = {x["slug"]: x["kind"] for x in rank_up.human_items()}
    check("7位・表示120・クリック0（4.2本増える見込み）は候補", got.get("zz-big"), "title")
    check("7位・表示40・クリック0（1.4本）は候補にしない", got.get("zz-tiny") == "title", False)
    check("飾りの年号でも、増える見込みが3本未満なら候補にしない", got.get("zz-deco") == "title", False)
    doc = (ROOT / "docs" / "pipeline" / "08-weekly.md").read_text(encoding="utf-8")
    check("文書（8.11）に判定の物差しと候補の下限がある",
          ("題の書き直しの効きはクリック率で判定する" in doc, "TITLE_MIN_GAIN" in doc), (True, True))
