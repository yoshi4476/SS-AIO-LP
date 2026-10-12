# -*- coding: utf-8 -*-
"""2026-10-12 の週次点検の「読み・学び・用語集・品質」の4件を直したときの門。

  1. 読み: 直せなかった読み51件のうち、声は正しく台本の側の読み（解析器）が誤っていたものが15件、
     同じ行の重複が11件、かなで読ませても聞き取りが一致しなかった（音声認識の誤り）ものが16件あった
  2. 学び: 判断が要る学びが74件（上限40）。機械が守っている学びに gate が無く、同じ学びが6件に分かれていた
  3. 用語集: 1ページにまとめた後も旧URL（1語1ページ）が表示され、14語で記事より上に出ていた
  4. 品質: 別工程の採点で一次性が80点を割った記事を、週次の書き直しが一度も選ばない作りだった
"""
import json
import re
import sys
import tempfile
from pathlib import Path

import yaml

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


# ── 1. 読み ──────────────────────────────────────
def test_yomi_compares_what_the_tagger_misreads_on_both_sides():
    import yomi_guard as Y
    print("\n■ 読み: 解析器が読み違える語は台本と聞き取りの両方をそろえ、聞き取りの英字の名前・1万以上の数もそろえる")
    sf = lambda s, h=False: Y.spoken_form(s, heard=h)
    check("数字の後の「位」は両側とも「い」（10位・9.2位）",
          ("じゅうい" in sf("10位以内"), "じゅうい" in sf("10位以内", True), "位" in sf("9.2位です")), (True, True, False))
    check("「一歩」「お得」「何が」は両側とも同じ読み",
          [sf(s) == sf(s, True) for s in ("今日の一歩です", "お得です", "何が分かる")], [True, True, True])
    check("「＋」は両側とも「プラス」", ("プラス" in sf("年月＋連番"), "プラス" in sf("年月+連番", True)), (True, True))
    check("聞き取りの「55,393」も台本と同じく万を入れる", ("ご万" in sf("55,393件"), "ご万" in sf("55,393件", True)), (True, True))
    check("聞き取りの英字の名前は台本と同じカタカナ（Search Console・Claude）",
          (sf("Search Consoleで", True) == sf("Search Consoleで"), "クロード" in sf("Claudeで", True)), (True, True))
    check("聞き取りの側に日本語の読み替え（人→ひと）は通さないまま", "人" in sf("人が決めます", True), True)
    import video_make as V
    check("声: Claude・Search Console は読みのかなで渡す",
          (V.read_text("Claudeで"), V.read_text("Search Consoleで")), ("クロードで", "サーチコンソールで"))


def test_yomi_report_counts_only_what_a_person_can_fix():
    import yomi_guard as Y
    print("\n■ 読み: 報告は重複を1件に数え、比べ方を直して解消した行と、かなで読ませても一致しない行（聞き取り）は要対応にしない")
    from datetime import date
    today = date.today().isoformat()
    rows = [{"date": today, "text": "A", "diff": [["の型", "カタ", "ホ"]]},
            {"date": today, "text": "A", "diff": [["の型", "カタ", "ホ"]]},                     # 同じ行（作り直した回）
            {"date": today, "text": "B", "diff": [["じゅう位", "クライ", ""]], "resolved": "比べ方を直した"},
            {"date": today, "text": "C", "diff": [["露地野菜", "ヤサイ", "アマツリ"]], "kana_tried": ["露地野菜"]},
            {"date": today, "text": "D", "diff": [["の下", "シタ", "モト"]]}]
    import contextlib
    import io
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "issues.jsonl"
        p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        old = Y.ISSUES
        Y.ISSUES = p
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                Y.report()
            out = buf.getvalue()
            p.write_text(json.dumps(rows[3], ensure_ascii=False) + "\n", encoding="utf-8")
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                Y.report()
        finally:
            Y.ISSUES = old
    check("要対応は人が直せる2件（重複・解消・聞き取りを除く）", "要対応: 読み上げで直せなかった読み 2件" in out, True)
    check("聞き取りの誤りは情報の行に件数だけ", "情報: かなで読ませても聞き取りが一致しなかった語 1件" in out, True)
    check("聞き取りの誤りだけなら YOMI_OK=yes", buf2.getvalue().strip().endswith("YOMI_OK=yes"), True)
    src = (ROOT / "scripts" / "yomi_guard.py").read_text(encoding="utf-8")
    check("guard: かなで作り直しても残ったずれに kana_tried を付けて残す", 'row["kana_tried"] = tried' in src, True)


# ── 2. 学び ──────────────────────────────────────
def _test_names():
    names = set()
    for p in (ROOT / "tests").glob("*.py"):
        names |= set(re.findall(r"^def (test_\w+)\(", p.read_text(encoding="utf-8"), re.M))
    return names


def test_lessons_gates_name_checks_that_exist():
    print("\n■ 学び: gate に書いた門の名前（test_…）が実在する（無い門を理由にプロンプトから外さない）")
    rows = [json.loads(x) for x in (ROOT / "data" / "lessons.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    names = _test_names()
    missing = sorted({(r["id"], t) for r in rows if r.get("status") == "active" and r.get("gate")
                      for t in re.findall(r"\btest_\w+", r["gate"]) if t not in names})
    check("active な学びの gate に書いた test_ 関数がすべてある", missing, [])
    retired = [r["id"] for r in rows if r.get("retired_why") and r.get("status") != "retired"]
    check("退役の理由（retired_why）がある行は退役している", retired, [])


# L0127: vs型の図解は「見出し|行…」の2列。6要素のリストで書いて図解が1枚欠けた（2026-10-04）
def vs_broken(diagrams):
    out = []
    for d in diagrams or []:
        if not isinstance(d, dict) or d.get("type") != "vs":
            continue
        it = d.get("items") or []
        if len(it) != 2 or not all(isinstance(x, str) and len([y for y in x.split("|") if y.strip()]) >= 2 for x in it):
            out.append(f"{d.get('name', '?')}: {len(it)}要素")
    return out


def test_lessons_vs_diagram_has_two_sides():
    print("\n■ 学び L0127: 対比（vs）の図解は「見出し|行1|行2」の2列で書く")
    check("壊れた例（6要素）を拾う", bool(vs_broken([{"type": "vs", "name": "x", "items": list("abcdef")}])), True)
    check("見出しだけの列を拾う", bool(vs_broken([{"type": "vs", "name": "x", "items": ["NG", "OK|行"]}])), True)
    check("正しい例は拾わない", vs_broken([{"type": "vs", "name": "x", "items": ["NG|行1|行2", "OK|行1"]}]), [])
    bad = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", p.read_text(encoding="utf-8-sig"), re.S)
        if not m:
            continue
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            continue
        if isinstance(fm, dict):
            bad += [f"{p.stem}: {x}" for x in vs_broken(fm.get("diagrams"))]
    check("いまの原稿の vs 図解はすべて2列", bad, [])


# ── 3. 用語集 ────────────────────────────────────
def test_glossary_old_urls_go_to_the_article_on_the_same_topic():
    import glossary as GL
    print("\n■ 用語集: 旧URL（1語1ページ）は、同じ主題の狙う記事へ301。主題を狭めた記事・狙う記事が無い語はまとめたページへ")
    cases = [("工務店のSEO", "工務店 SEO", True), ("不動産のLLMO", "LLMO 不動産", True),
             ("AIO対策の計測", "aio対策 計測方法", True), ("AIO（AI Overview Optimization）", "aioとは", True),
             ("SEO", "aio seo meo", False), ("MEO対策", "飲食店 meo対策", False),
             ("AIO対策", "aio対策 相場", False), ("AIO対策（AI Overview Optimization）", "リフォーム会社 AIO対策", False)]
    check("same_topic: 用語＋骨組みの語だけなら同じ主題", [(t, k) for t, k, w in cases if GL.same_topic(t, k) != w], [])
    terms = [{"term": "工務店のSEO", "id": "a1", "slug": "src-a", "category": "seo", "target": "aim-a",
              "target_category": "seo", "same_topic": True},
             {"term": "SEO", "id": "b2", "slug": "src-b", "category": "aio", "target": "src-b",
              "target_category": "aio", "same_topic": False}]
    check("redirects: 同じ主題は記事へ、それ以外は #id", GL.redirects(terms),
          ["/glossary/a1/  /seo/aim-a/  301", "/glossary/b2/  /glossary/#b2  301"])
    import sites as S
    real = GL.collect(S.primary())
    if len(real) >= 10:
        to_art = [ln for ln in GL.redirects(real) if "#" not in ln.split()[1]]
        check("実データ: 旧URLの一部は記事へ送る（全部を1ページへ集めない）", bool(to_art), True)


# ── 4. 品質 ──────────────────────────────────────
def test_low_originality_articles_enter_weekly_rewrite_with_facts_only():
    import auto_rewrite as A
    import rubric as R
    print("\n■ 品質: 別工程の採点で一次性が80点を割った記事を、足せる一次情報があるときだけ週1本 quality で直す")
    own = None
    for p in sorted((ROOT / "articles").glob("*.md")):
        if A.site_of(p.stem) and not p.stem.startswith("_"):
            own = p.stem
            break
    if not own:
        check("原稿が無い（この門は飛ばす）", True, True)
        return
    au = lambda o, at="2026-10-01": {"at": at, "audit": {"version": R.VERSION, "total": 60, "axes": {"originality": o},
                                                          "reason": "一次性の指摘\n\nSCORES originality=40"}}
    facts = lambda sid: [{"claim": "まだ本文に無い登録済みの一次情報 ZZ-0001"}]
    got = A.quality_items({own: au(40)}, {}, facts)
    check("一次性が80点未満・足せる一次情報あり → quality で選ぶ", [(x["kind"], x["slug"]) for x in got], [("quality", own)])
    check("指示に採点者の指摘を渡す（SCORES の行は渡さない）",
          ("一次性の指摘" in got[0]["why"], "SCORES" in got[0]["why"]), (True, False))
    check("足せる一次情報が無ければ選ばない（登録データが無いと上がらない: 2026-10-04）",
          A.quality_items({own: au(40)}, {}, lambda sid: []), [])
    check("80点以上は選ばない", A.quality_items({own: au(85)}, {}, facts), [])
    check("2回直した記事は選ばない（retire_stale --quality が統合へ）",
          A.quality_items({own: au(40)}, {own: ["2026-09-01", "2026-09-08"]}, facts), [])
    check("直した後に採点し直していなければ選ばない（採点待ち）",
          A.quality_items({own: au(40, "2026-09-01")}, {own: ["2026-09-08"]}, facts), [])
    import score_audit as SA
    d = {own: {"at": "2026-09-01"}, "x-other": {"at": "2026-09-20"}}
    check("score_audit: 直した後に採点していない記事を先に採点し直す",
          SA.rewritten_since_audit(d, {own: ["2026-09-08"], "x-other": ["2026-09-08"]}), [own])
    pub = SA.published(0)
    if pub:
        first = sorted(pub)[-1]
        check("score_audit: first の記事が先頭に来る", list(SA.published(3, 0, [first]))[0], first)
    src = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    check("週次の targets が quality_items を QUALITY_PER_RUN 本まで入れる",
          "quality_items() if x[\"slug\"] not in seen1][:QUALITY_PER_RUN]" in src, True)
