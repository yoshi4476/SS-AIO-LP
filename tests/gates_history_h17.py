# -*- coding: utf-8 -*-
"""文中リンク（link_boost --inline・集中モードだけが使う）の門（2026-10-05）。

リンクだけの段落は1記事4本の上限に当たった記事が多く、それ以上は足せない。
本文に既にある語句を [語](/url/) で囲むだけにして、文章は1文字も変えない。
冒頭の断言・H2直下の1文結論（AIが切り出す単位）と、見出し・表・FAQ・枠には置かない。
本物の GSC・記事は触らない（一時ファイルだけ）。
"""
import json
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

import yaml

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

LINKMD = re.compile(r"\[([^\]\n]*)\]\([^)\n]*\)")
LONG = "規模によって大きく変わるため、早めの見積もりが欠かせません。この点は多くの院長が見落としがちな部分でもあり、実際に相談を受けることが多い論点です。"

INTRO = "**閉院の費用は、原状回復・廃棄・届出の3つで決まります。**\n\n冒頭でも閉院の費用に触れます。" + LONG + "\n\n"
H2_HEAD = "## 閉院の費用の内訳は？\n\n閉院の費用は原状回復と廃棄で決まり、規模で大きく変わります。\n\n"
BLOCKS = ("| 項目 | 閉院の費用 |\n|---|---|\n| 内装 | 閉院の費用の半分 |\n\n"
          "<div class=\"caution-box\">閉院の費用には注意。</div>\n\n"
          "- 閉院の費用のリスト\n- 二つ目\n\n"
          "```\n閉院の費用 コード\n```\n\n")
VALID = "院内の片付けにかかる閉院の費用は、" + LONG + "\n\n"
TAIL = ("### 閉院の費用の小見出し\n\n小見出しの下の地の文です。\n\n"
        "## よくある質問\n\n閉院の費用はまとめて払いますか。" + LONG + "\n\n"
        "<details><summary>閉院の費用は？</summary>\n\n閉院の費用は規模で変わります。" + LONG + "\n\n</details>\n")


def _body(valid=True):
    return INTRO + H2_HEAD + BLOCKS + (VALID if valid else "") + TAIL


def test_inline_link_keeps_text_and_skips_protected_zones():
    print("\n■ 文中リンクは文章を変えず、冒頭・1文結論・見出し・表・FAQ・枠・コードに置かない")
    import link_boost as LB
    ph = LB.anchor_phrases({"kw": "閉院 費用 相場", "title": "閉院費用の相場とは？規模別の目安"})
    check("狙う語の隣り合う2語から語句を作る", "閉院の費用" in ph and "閉院費用相場" in ph, True)
    check("アンカーは26字まで・5字以上", all(5 <= len(p) <= 26 for p in ph), True)
    t1 = {"kw": "閉院 費用 相場", "title": "x"}
    check("サイトの2本以上の題・狙う語に含まれる語句は使わない（送り先を言い当てない）",
          "閉院の費用" in LB.anchor_phrases(t1, ["閉院の費用 a", "b 閉院 の費用"]), False)
    check("1本だけなら使う", "閉院の費用" in LB.anchor_phrases(t1, ["閉院の費用 a"]), True)
    check("4語の狙う語から2語だけの語句は作らない（「病院 口コミ 返信 例文」→「口コミ返信」）",
          "口コミ返信" in LB.anchor_phrases({"kw": "病院 口コミ 返信 例文", "title": "x"}), False)

    body = _body()
    url = "/aio/heiin-hiyou/"
    nb, anchor = LB.inline_link(body, ph, url)
    check("置ける段落があれば1本だけ置く", (anchor, nb.count("](" + url + ")") if nb else 0), ("閉院の費用", 1))
    check("リンクの記法を外すと元の本文と1文字も違わない", LINKMD.sub(r"\1", nb), body)
    check("置いたのは見出しの後の2つ目以降の地の文", "院内の片付けにかかる[閉院の費用](" + url + ")" in nb, True)
    check("検算（タグ・導線・見出し・本文の減り）を通る", LB.inline_ok(body, nb, url, anchor), "")

    nb2, _ = LB.inline_link(_body(valid=False), ph, url)
    check("冒頭・1文結論・表・枠・箇条書き・コード・H3直下・FAQ・details には置かない", nb2, None)
    check("送り元の主題（狙う語）そのものは他の記事へ飛ばさない", LB.inline_link(body, ph, url, own="閉院 の費用")[0], None)

    short = INTRO + H2_HEAD + "短い段落の閉院の費用です。\n\n" + TAIL
    check("短い段落には置かない（見直しがリンクだけの段落と読んで本文ごと消すため）",
          LB.inline_link(short, ph, url)[0], None)
    linked = INTRO + H2_HEAD + "既に[別の記事](/aio/x/)がある段落の閉院の費用は、" + LONG + "\n\n" + TAIL
    check("既にリンクのある段落には足さない（1段落に1本まで）", LB.inline_link(linked, ph, url)[0], None)
    check("英数字の語の途中では切らない",
          LB.inline_link(INTRO + H2_HEAD + "MAIO導入の話です。" + LONG + "\n\n" + TAIL, ["AIO導入"], url)[0], None)


def _art(d, slug, kw, title, body, n_links=0):
    links = "".join(f"\n\n関連の話題は[記事{i}](/aio/link-{i}/)で詳しく扱っていて、" + LONG for i in range(n_links))
    p = Path(d) / f"{slug}.md"
    full = INTRO + H2_HEAD + body + links + "\n\n" + TAIL
    p.write_text(f"---\ntitle: {title}\nkeyword: {kw}\ncategory: aio\n---\n{full}", encoding="utf-8")
    return slug, {"path": p, "title": title, "kw": kw, "cat": "aio", "body": full}


def _para(phrase):
    return "院内の片付けにかかる" + phrase + "は、" + LONG + "\n\n"


def test_inline_link_limits():
    print("\n■ 上限: 送り先1本に2本・送り元1本に2本・同じ組は1本・リンクが多い記事は飛ばす・同じアンカーは5記事まで")
    import link_boost as LB
    keep, keep_t = LB.industry_of, LB.industry_terms
    LB.industry_of = lambda *a: set()
    LB.industry_terms = lambda *a: []
    LB._P1["h17"] = set()
    try:
        arts0 = {"c": {"kw": "ai導入補助金 2026 クリニック", "title": "AI導入補助金2026｜クリニックの締切"},
                 "o": {"kw": "別", "title": "別"}}
        LB.industry_terms = lambda text, site: ["クリニック"] if "クリニック" in text else []
        check("業種別の記事へは業種名を含む語句でだけ送る（「AI導入補助金2026」では送らない）",
              "AI導入補助金2026" in LB.phrases_for("h17", "c", arts0), False)
        LB.industry_terms = lambda *a: []
        with tempfile.TemporaryDirectory() as d:
            tg = {"t1": ("閉院 費用 相場", "閉院費用の相場とは？"),
                  "t2": ("開業 資金 調達", "開業資金の調達とは？"),
                  "t3": ("院長 退職 手続き", "院長退職の手続きとは？")}
            arts = dict(_art(d, s, kw, ti, "本文の閉院と費用。開業と資金。院長と退職。\n\n") for s, (kw, ti) in tg.items())
            every = _para("閉院の費用") + _para("開業の資金") + _para("院長の退職") + "閉院・費用・開業・資金・院長・退職・手続き。\n\n"
            for s in ("s1", "s2", "s3"):
                k, v = _art(d, s, f"別の 主題 {s}", f"別の主題{s}", every)
                arts[k] = v
            k, v = _art(d, "s_many", "別の 主題 m", "別の主題m", every, n_links=12)
            arts[k] = v
            ranks = {"t1": 10.0, "t2": 10.0, "t3": 10.0, "s1": 1.0, "s2": 2.0, "s3": 3.0, "s_many": 1.5}
            cnt = Counter({s: 0 for s in arts})
            log = Path(d) / "auto_fix.jsonl"
            before = {s: a["path"].read_text(encoding="utf-8") for s, a in arts.items()}
            n = LB.run_inline("h17", arts, ["t1", "t2", "t3"], cnt, ranks, None, True, log=log, use=Counter())
            rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
            check("台帳に足した本数ぶん残す（誰が・どの記事に・何を）", len(rows), n)
            check("台帳に送り元とアンカー", all(r["by"] == "link_boost" and r["kind"] == "link_inline"
                                         and r.get("src") and r.get("anchor") for r in rows), True)
            per_tgt = Counter(r["slug"] for r in rows)
            per_src = Counter(r["src"] for r in rows)
            pairs = Counter((r["src"], r["slug"]) for r in rows)
            check("何かは足す", n > 0, True)
            check("送り先1本に2本まで", max(per_tgt.values()) <= LB.ADD_PER, True)
            check("送り元1本に2本まで", max(per_src.values()) <= LB.INLINE_PER_SRC, True)
            check("同じ送り先は1記事に1本", max(pairs.values()), 1)
            check("内部リンクが多すぎる記事からは送らない", "s_many" in per_src, False)
            check("アンカーは26字まで", all(len(r["anchor"]) <= 26 for r in rows), True)
            for s, a in arts.items():
                after = a["path"].read_text(encoding="utf-8")
                if after != before[s]:
                    check(f"{s}: 書いた原稿もリンクの記法を外すと元と同じ",
                          LINKMD.sub(r"\1", after) == LINKMD.sub(r"\1", before[s]), True)

            arts2 = dict(_art(d, s, kw, ti, "本文の閉院と費用。\n\n") for s, (kw, ti) in list(tg.items())[:1])
            k, v = _art(d, "s9", "別の 主題 9", "別の主題9", every)
            arts2[k] = v
            full = Counter({p.lower(): 5 for p in LB.anchor_phrases({"kw": tg["t1"][0], "title": tg["t1"][1]})})
            check("同じアンカーが既に5記事にあれば足さない",
                  LB.run_inline("h17", arts2, ["t1"], Counter({"t1": 0, "s9": 0}), {"t1": 9.0, "s9": 1.0},
                                None, False, use=full), 0)
            check("送り先より下位の記事からは送らない",
                  LB.run_inline("h17", arts2, ["t1"], Counter({"t1": 0, "s9": 0}), {"t1": 9.0, "s9": 12.0},
                                None, False, use=Counter()), 0)
    finally:
        LB.industry_of, LB.industry_terms = keep, keep_t


def test_inline_is_focus_mode_only_and_reviewed():
    print("\n■ 指定しなければ今の動きのまま。使うのは集中モードだけで、見直しが偏りを数える")
    import auto_review as ar
    import focus_report as F
    import link_boost as LB
    src = (ROOT / "scripts" / "link_boost.py").read_text(encoding="utf-8")
    main = src[src.index("def main():"):]
    check("run_inline は --inline のときだけ呼ばれる", re.findall(r"\n(\s*)if inline:\n\s*done = run_inline\(", main) != [], True)
    check("main から run_inline を呼ぶのは1か所", main.count("run_inline("), 1)
    with tempfile.TemporaryDirectory() as d:
        log = Path(d) / "a.jsonl"
        LB.note("t", "s", "link_band", log=log)
        row = json.loads(log.read_text(encoding="utf-8"))
        check("従来の台帳の行は形が変わらない", sorted(row), ["at", "by", "kind", "note", "ok", "slug"])

    wf = ROOT / ".github" / "workflows"
    for name in ("weekly-optimize.yml", "pipeline-multi.yml"):
        check(f"{name} は --inline を使わない", "--inline" in (wf / name).read_text(encoding="utf-8"), False)
    y = yaml.safe_load((wf / "focus-mode.yml").read_text(encoding="utf-8"))
    steps = y["jobs"]["focus"]["steps"]
    names = [s.get("name", "") for s in steps]
    runs = [str(s.get("run", "")) for s in steps]
    i_link = next(i for i, r in enumerate(runs) if "--inline" in r)
    check("集中モードは 4〜20位へ文中リンク（--band=4-20 --inline --write）", "--band=4-20 --inline --write" in runs[i_link], True)
    check("文中リンクの後に見直し（auto_review --fix）",
          any("auto_review.py --fix" in r for r in runs[i_link + 1:]), True)
    check("見直しの名前は変えていない", "自動修正の見直し（積み上がりと言い回しの偏り）" in names, True)

    with tempfile.TemporaryDirectory() as d:
        ps = []
        for i in range(ar.MAX_SAME_ANCHOR + 1):
            p = Path(d) / f"a{i}.md"
            p.write_text("---\ntitle: x\n---\n本文の[閉院費用](/aio/t1/)です。[開業資金](/aio/t2/)。\n", encoding="utf-8")
            ps.append(p)
        log = Path(d) / "auto_fix.jsonl"
        log.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in (
            {"by": "link_boost", "kind": "link_inline", "slug": "t1", "anchor": "閉院費用"},
            {"by": "link_boost", "kind": "link_band", "slug": "t2"})) + "\n", encoding="utf-8")
        check("文中リンクのアンカーが上限を超える記事数で使われていれば偏りとして出す",
              ar.inline_anchor_bias(ps, log=log), {"閉院費用": ar.MAX_SAME_ANCHOR + 1})
        check("上限以内なら偏りは無い", ar.inline_anchor_bias(ps[:ar.MAX_SAME_ANCHOR], log=log), {})
        log.write_text(json.dumps({"at": "2026-10-06 10:00", "by": "link_boost", "kind": "link_inline",
                                   "slug": "t1", "ok": True}, ensure_ascii=False) + "\n", encoding="utf-8")
        _, touched = F.focus_edits("2026-10-05", log=log)
        check("集中モードの効き測定は文中リンクを受けた記事を対照群に入れない", "t1" in touched, True)
