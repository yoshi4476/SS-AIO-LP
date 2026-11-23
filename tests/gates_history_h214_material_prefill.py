# -*- coding: utf-8 -*-
"""2026-11-23 運用者「シートなどは自動で埋めるように」。材料の質問シートを、社の公開ページから自動で埋める（material_prefill）。
作らないこと: 当社の記事と見本のページは読まない／引用がページに無い答え・引用に無い数字の答えは捨てる／登録は plan を通す。
埋めた答えはシートの答えの欄に出典つきで入り、質問が変わらない週は読み直さない。本物の claude とネットは呼ばない。"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

PAGE = ("<html><body><nav>メニュー</nav><main><h1>会社概要</h1><p>当社は2011年に大阪で設立し、"
        "サーバー・ドメインは最初からお客様の名義で用意していただきます。</p>" + "本文。" * 80 + "</main></body></html>")


def _fetch(url):
    if url.endswith("sitemap.xml"):
        return ("<urlset><url><loc>https://x.example/</loc></url><url><loc>https://x.example/company/</loc></url>"
                "<url><loc>https://x.example/column/our-article/</loc></url>"
                "<url><loc>https://x.example/samples/shop/</loc></url></urlset>")
    return PAGE


def test_material_prefill_from_public_pages():
    import material_prefill as MP
    import material_sheet as M
    import sites as S
    print("\n■ 材料の質問シート: 社の公開ページから、引用で確かめた答えだけを自動で埋める")
    check("読まない: 当社の記事（slug が同じ）と他社向けの見本",
          MP.pick_urls(["https://x.example/company/", "https://x.example/column/our-article/",
                        "https://x.example/samples/shop/"], {"our-article"}), ["https://x.example/company/"])
    pages = [("https://x.example/company/", MP.text_of(PAGE))]
    good = {"no": 1, "answer": "2011年に大阪で設立した会社です", "url": "https://x.example/company/",
            "quote": "当社は2011年に大阪で設立し"}
    check("確かめ: 引用がページにあり数字も引用にある答えは使う", MP.verify(good, pages)[0], True)
    check("確かめ: 引用に無い数字（作った数字）は捨てる",
          MP.verify(dict(good, answer="2011年設立で、これまで300社を支援しました"), pages), (False, "引用に無い数字: 300"))
    check("確かめ: ページに無い引用は捨てる", MP.verify(dict(good, quote="当社は創業100年の老舗です"), pages)[0], False)

    rows = [("req:a:0", "記事「a」", "会社の設立の年は？", ""), ("req:a:1", "記事「a」", "支援した社数は？", ""),
            ("tpl:voice", "お客様の声", "声", "")]
    reply = "答えです。\n" + json.dumps({"answers": [good, {"no": 2, "answer": "これまで300社を支援", "url": "https://x.example/company/",
                                                        "quote": "当社は2011年に大阪で設立し"}]}, ensure_ascii=False)
    wrote = []
    with tempfile.TemporaryDirectory() as td:
        rec = Path(td) / "prefill.json"
        with mock.patch.object(S, "load_all", lambda: {"xco": {"id": "xco", "domain": "x.example"}}), \
                mock.patch.object(S, "public_id", lambda s: s), \
                mock.patch.object(M, "rows_for", lambda s, r: rows), mock.patch.object(M, "requests_of", lambda s: {}), \
                mock.patch.object(MP, "own_article_slugs", lambda: {"our-article"}), \
                mock.patch.object(MP, "record_path", lambda s: rec), \
                mock.patch.object(M, "plan", lambda site, ans, ask=None: ([{"no": a["no"], "claim": a["answer"]} for a in ans], [], [])), \
                mock.patch.object(M, "write", lambda site, f, e, today=None, source="": wrote.append((len(f), source))):
            asked = []
            n, dropped = MP.run("xco", write=True, ask=lambda p: asked.append(p) or reply, fetch=_fetch, today="2026-11-23")
            check("登録するのは確かめを通った1件だけ（作った数字の答えは捨てる）", (n, [d[:3] for d in dropped]), (1, ["問2:"]))
            check("出どころに公開ページからの自動記入と書く", wrote and "公開ページから自動記入" in wrote[0][1], True)
            check("AI に渡すのは社のページだけ（当社の記事・見本の本文を渡さない）・お客様の声は聞かない",
                  ("our-article" in asked[0], "samples" in asked[0], "声" in asked[0].split("公開ページ:")[0].split("質問:")[1]),
                  (False, False, False))
            r = json.loads(rec.read_text(encoding="utf-8"))
            check("記録に、埋めた答えと出典が残る", (r["req:a:0"]["url"], "req:a:1" in r), ("https://x.example/company/", False))
            asked.clear()
            MP.run("xco", write=True, ask=lambda p: asked.append(p) or reply, fetch=_fetch)
            check("質問が前の回と同じ週は読み直さない（claude を呼ばない）", asked, [])
            from openpyxl import Workbook
            wb = Workbook()
            ws = M.question_tab(wb, "xco", "X社", "2026-11-23", rows[:2], filled=r)
            check("シート: 埋めた答えを答えの欄に「可」で入れ、目安の欄に出典を書く",
                  (ws.cell(5, 5).value, ws.cell(5, 8).value, "x.example/company" in ws.cell(5, 4).value, ws.cell(6, 5).value),
                  (good["answer"], "可", True, ""))
    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    i_lock, i_fill = wf.find("書き直し・統合の前に作業場から鍵を外す"), wf.find("material_prefill.py --write --no-push")
    i_prot, i_mail = wf.find("- name: 書き直し・統合の後に触ってはいけない場所を戻す"), wf.find("material_sheet.py --mail")
    check("週次: 鍵を外した間に埋め（外のページを AI に読ませる）、鍵を戻した後に送ってからシートをメールする",
          0 < i_lock < i_fill < i_prot < i_mail, True)
