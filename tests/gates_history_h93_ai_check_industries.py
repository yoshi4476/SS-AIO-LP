# -*- coding: utf-8 -*-
"""2026-10-11 運用者「AI に 3 つの質問をして確かめるの業種が少なすぎる あらゆる業種できるようにして」。

AI紹介チェック（/tools/ai-check/・許可した別事業のサイトの同じ診断）の業種は、10業種の選択＋「その他」で別の欄に書く2段の形だった。
1つの欄に打つか候補（約240業種）から選ぶ形にし、候補に無い業種もそのまま使えるようにした。候補・業種別の案内のキーへの
対応づけ・自由入力の確かめは functions/_industries.js の1か所で、画面は GET /api/ai-check から候補を読む。
"""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from test_gates import check, ROOT

FN = ROOT / "functions"
NODE = r"""
import { pathToFileURL } from "node:url";
const m = await import(pathToFileURL(process.argv[2]).href);
const all = m.GROUPS.flatMap(([, xs]) => xs);
const bad = ["https://evil.example", "<script>", "12345", "", "あ".repeat(21), "a@b.jp", "x;y"];
const seps = ["歯科（矯正）", "税理士/会計士", "美容室、理容室", "整骨院／鍼灸院"];
console.log(JSON.stringify({
  n: all.length, groups: m.GROUPS.length, dup: all.length - new Set(all).size,
  failing: all.filter((w) => !m.cleanWord(w)),
  bad: bad.map((w) => m.cleanWord(w)),
  keys: ["歯科医院", "内科", "不動産会社", "工務店", "外壁塗装", "税理士事務所", "社労士事務所", "行政書士事務所", "司法書士事務所",
         "法律事務所", "美容室", "居酒屋"].map(m.keyOf),
  words: ["dental", "歯科医院", "内科", "動物病院", "ＡＢＣ歯科", "税理士事務所", "法律事務所"].map(m.searchWord),
  seps: seps.map(m.cleanWord),
  odd: ["toString", "constructor", "__proto__"].map(m.keyOf),
}));
"""


def test_any_industry_can_be_checked():
    print("\n■ AI紹介チェック: どの業種でも入れられる（候補は全業種・候補に無い業種もそのまま）")
    node = shutil.which("node")
    if node:
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / "h.mjs"
            h.write_text(NODE, encoding="utf-8")
            r = subprocess.run([node, str(h), str(FN / "_industries.js")], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=60)
        if r.returncode:
            raise AssertionError("業種の一覧を動かせません: " + (r.stderr or r.stdout)[-300:])
        o = json.loads(r.stdout.strip().splitlines()[-1])
        check("候補は200業種以上・12分野以上・重複なし", (o["n"] >= 200, o["groups"] >= 12, o["dup"]), (True, True, 0))
        check("候補はすべて入力の確かめを通る", o["failing"], [])
        check("URL・タグ・数字だけ・空・21文字以上・記号は止める", o["bad"], [""] * 7)
        check("業種別の案内がある10業種は、言い換えも案内のキーにつながる（ほかは案内なし）",
              o["keys"], ["dental", "clinic", "fudosan", "koumuten", "reform", "zeirishi", "sharoushi", "gyousei", "shihou",
                          "bengoshi", "", ""])
        check("AI に聞く言い方: これまでの選択肢はこれまでどおり（歯科医院→歯医者・税理士事務所→税理士・法律事務所→弁護士）、"
              "ほかは入力のまま（全角は半角にそろえる）",
              o["words"], ["歯医者", "歯医者", "内科", "動物病院", "ABC歯科", "税理士", "弁護士"])
        check("括弧・／・読点の入った業種名は区切りを整えて受け付ける", o["seps"],
              ["歯科 矯正", "税理士 会計士", "美容室 理容室", "整骨院 鍼灸院"])
        check("toString などの元の名前を業種の案内と取り違えない", o["odd"], ["", "", ""])
    else:
        print("  WARN  node が無いため業種の一覧は動かせません")
    api = (FN / "api" / "ai-check.js").read_text(encoding="utf-8")
    check("受付は業種の一覧を1か所（_industries.js）から読み、自前の一覧を持たない",
          ('from "../_industries.js"' in api, bool(re.search(r"^const WORDS\s*=", api, re.M))), (True, False))
    check("業種名が無いときは案内のある業種のキーだけを受ける（「その他」のまま AI に聞かない）",
          'keyOf(ind) ? searchWord(ind) : ""' in api, True)
    check("記号・URL の入った業種名は断る（長さは切らずに確かめる。切ると途中で切れた語が AI と台帳に入る）",
          ("業種は20文字以内の言葉で入れてください" in api, 'String(d.word || "").trim().slice(0, 60)' in api), (True, True))
    check("後追いのメールのため、台帳に業種のキーも残す", "ind: key, area, cited" in api, True)
    check("GET は候補を返し、許可した別事業のサイトにだけ読ませる",
          ("industries: GROUPS" in api, api.count("return partner ? withCors(res, partner.origin) : res;") >= 2), (True, True))
    page = (ROOT / "site" / "tools" / "ai-check" / "index.html").read_text(encoding="utf-8")
    check("画面: 業種は1つの欄（候補つき）で、選択と「その他」の欄は無い",
          ('name="word" required maxlength="20" list="ac-industries"' in page, '<datalist id="ac-industries">' in page,
           'name="industry"' in page, "その他の業種名" in page), (True, True, False, False))
    js = (ROOT / "site" / "js" / "ai-check.js").read_text(encoding="utf-8")
    check("画面: 候補は受付から読み、案内のチェックリストは受付が決めた業種のキー（d.ind）で選ぶ",
          ("fillIndustries(c.industries)" in js, "CHECKLIST[d.ind]" in js, "data.industry" in js), (True, True, False))
    check("画面: 候補に分野名を付けない（Firefox で業種名が出ない）・候補が崩れてもロボットよけは置く・自由入力を計測に送らない",
          ("o.label" in js, "try { if (c) fillIndustries(c.industries); } catch (x) {}" in js, "data.word" in js),
          (False, True, False))
    check("画面: スクリプトの版の印を変えた（7日間ブラウザに残る古いスクリプトを読ませない）",
          "ai-check.js?v=20261004c" in page, False)
