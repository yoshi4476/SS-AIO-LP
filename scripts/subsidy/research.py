# -*- coding: utf-8 -*-
"""「AIに聞いた調査」のデータページ（3サイト共通）。

subsidy_survey.py が記事ごとに残した聞き取りの結果を、サイトごとに1ページにまとめる。
  補助金サイト   /research/ai-hojokin/   … pages.py が同じ枠で出す（build）
  AI集客ラボ     /research/ai-answers/   … build.py が業種別AI調査と同じ枠で出す（data + html_body）
  コーポレート   /research/ai-answers    … Next.js のページが JSON を読んで描く（data → research_publish.py）

載せるのは「AIが何と答えたか」と「何を根拠にしたか」の集計だけ。AIの答えが正しいかは判定しない
（当社が正誤を決めると、公式の要件と違う判断を当社の見解として広めてしまう）。
"""
import csv
import html
import io
import json
import re
from collections import Counter
from pathlib import Path

MAIN = Path(__file__).resolve().parents[2]
LABEL = {"yes": "はい（対象になる・できる）", "cond": "条件による", "no": "いいえ（対象外・できない）"}
MIN_DECIDED = 2          # 結論が読み取れた回答がこれ未満の問いは載せない（割れ方を語れない）
MIN_ROWS = 5             # 問いがこれ未満ならページを作らない（薄いページを出さない）
SITE = {
    "subsidy": {"url": "/research/ai-hojokin/", "topic": "補助金", "article": "/blog/{slug}/",
                "readout": ("<p><b>AIの答えは、申請の可否を決める根拠になりません。</b>補助の対象・金額・締切は、公募要領と事務局のページで決まります。"
                            "AIが根拠にしたページの多くは民間のサイトで、公募要領より古い情報や、特定の製品をすすめる内容が含まれることがあります。</p>"
                            "<p>AIに聞いて答えが分かれたときは、その問いの言葉で公募要領を検索し、事務局の「よくある質問」で確かめてください。"
                            "判断に迷う点は、申請の前に登録支援事業者へ確認するのが確実です。</p>")},
    "ai-lab": {"url": "/research/ai-answers/", "topic": "集客・AI検索", "article": None,
               "readout": ("<p><b>AIの答えは、同じ問いでもAIによって結論が分かれることがあります。</b>"
                           "とくに医療・不動産の広告の決まりや、口コミの扱いのように規則が関わる問いは、AIの答えだけで判断せず、"
                           "根拠になった規則（厚生労働省のガイドラインや、各サービスの規約）で確かめてください。</p>")},
    "corporate": {"url": "/research/ai-answers", "topic": "経理・バックオフィス", "article": None,
                  "readout": ("<p><b>経理の実務は、会社の規模や業種、使っている会計ソフトで答えが変わります。</b>"
                              "AIの答えが分かれた問いは、税務の扱いなら国税庁のページで、社内の手順なら顧問の税理士に確かめてください。</p>")},
}


def _survey_files(site):
    if site == "subsidy":
        return sorted((MAIN / "data" / "subsidy_survey").glob("*.json"))
    return sorted((MAIN / "data" / "ai_survey" / site).glob("*.json"))


def data(site, domain):
    """ページの中身（サイトに依存しない形）。材料が足りなければ None"""
    import sys
    sys.path.insert(0, str(MAIN / "scripts"))
    import subsidy_survey as SV
    import sites as S
    cfg = SITE[site]
    rows, engines, dates, src = [], set(), [], Counter()
    for p in _survey_files(site):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not r.get("stance"):
            continue
        dates.append(r["date"])
        for k, v in SV.tally(r)["sources"].items():
            src[k] += v
        if cfg["article"]:
            url = cfg["article"].format(slug=r["slug"])
        else:
            try:
                art = (MAIN / "articles" / f"{r['slug']}.md").read_text(encoding="utf-8")
                cat = (re.search(r"^category:\s*(\S+)", art, re.M) or [0, ""])[1]
                url = S.article_url(S.load(site), {"slug": r["slug"], "category": cat}).replace(domain, "")
            except Exception:
                url = ""
        for q, by in r["stance"].items():
            c = Counter(v["label"] for v in by.values())
            if c["yes"] + c["cond"] + c["no"] < MIN_DECIDED:
                continue
            engines |= set(by)
            answers = {e: {"label": LABEL.get((by.get(e) or {}).get("label"), "結論が読み取れず"),
                           "quote": re.sub(r"[*#`>]", "", (by.get(e) or {}).get("quote", ""))[:120]}
                       for e in by}
            rows.append({"q": q, "url": url, "date": r["date"], "answers": answers,
                         "split": len([k for k in ("yes", "cond", "no") if c[k]]) >= 2,
                         "decided": c["yes"] + c["cond"] + c["no"]})
    if len(rows) < MIN_ROWS:
        return None
    period = f"{min(dates)}〜{max(dates)}" if min(dates) != max(dates) else min(dates)
    who = "・".join(sorted(engines))
    split = sum(r["split"] for r in rows)
    n_ans = sum(r["decided"] for r in rows)
    total = sum(src.values()) or 1
    title = f"AIに{cfg['topic']}のことを聞くと答えは割れる｜{len(rows)}問の調査（当社調べ）"
    desc = (f"当社が{period}に{who}へ{cfg['topic']}の問いを{len(rows)}問聞いた結果。{split}問でAIどうしの結論が分かれました。"
            f"問いごとの答えと根拠、確かめ方をまとめています。")
    return {"site": site, "url": cfg["url"], "title": title, "description": desc,
            "h1": f"AIに{cfg['topic']}のことを聞くと、答えはどれくらい割れるか",
            "lead": f"当社が{who}に{cfg['topic']}の問いを{len(rows)}問聞き、答えの結論と根拠にしたページを集計しました（当社調べ）。",
            "period": period, "engines": sorted(engines), "rows": rows, "split": split, "answers": n_ans,
            "sources": dict(src), "public_pct": src["public"] * 100 // total, "readout_html": cfg["readout"],
            "lastmod": max(dates), "domain": domain}


def csv_text(d):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["調べた日", "問い", "AI", "結論", "根拠の一文", "記事"])
    for r in d["rows"]:
        for e in d["engines"]:
            a = r["answers"].get(e) or {"label": "（聞けず）", "quote": ""}
            w.writerow([r["date"], r["q"], e, a["label"], a["quote"], (d["domain"] + r["url"]) if r["url"] else ""])
    return "﻿" + buf.getvalue()


def html_body(d):
    esc = lambda s: html.escape(str(s), quote=True)
    trs = []
    for r in d["rows"]:
        q = f'<a href="{esc(r["url"])}">{esc(r["q"])}</a>' if r["url"] else esc(r["q"])
        cells = "".join(
            f'<td><b>{esc(r["answers"][e]["label"])}</b><br><small>「{esc(r["answers"][e]["quote"][:70])}」</small></td>'
            if e in r["answers"] and r["answers"][e]["quote"] else
            f'<td><small>{esc((r["answers"].get(e) or {}).get("label", "（聞けず）"))}</small></td>'
            for e in d["engines"])
        trs.append(f'<tr><th scope="row">{q}</th>{cells}</tr>')
    s = d["sources"]
    return f'''
  <div class="hub"><b>要点:</b> 当社が{d["period"]}に{"・".join(d["engines"])}へ問いを{len(d["rows"])}問聞いたところ、
  <b>{d["split"]}問でAIどうしの結論が分かれました</b>（結論が読み取れた{d["answers"]}回答の集計）。
  AIが根拠に挙げたページ{sum(s.values())}件のうち、公的機関（go.jp など）のページは{s.get("public", 0)}件（{d["public_pct"]}%）でした。</div>
  <section>
  <h2>AIは何と答えたか（問いごと）</h2>
  <p>同じ問いでも、AIによって結論が違うことがあります。下の表は、各AIの答えの結論と、その根拠になった一文です。</p>
  <div style="overflow-x:auto"><table>
  <thead><tr><th scope="col">問い</th>{"".join(f'<th scope="col">{esc(e)}</th>' for e in d["engines"])}</tr></thead>
  <tbody>
  {"".join(trs)}
  </tbody></table></div>
  <p><a href="{d["url"]}data.csv" download>この表のデータ（CSV）</a>。引用するときは、調べた日とAIの名前を添えてください。</p>
  </section>
  <section>
  <h2>この結果の読み方</h2>
  {d["readout_html"]}
  </section>
  <section>
  <h2>調べ方と限界</h2>
  <ul>
  <li>調べた日: {d["period"]}。AIの答えは日によって変わります。これはその日の1回の結果です。</li>
  <li>聞いたAI: {"・".join(d["engines"])}（いずれも検索つきで回答させ、根拠にしたページのURLを残しました）。</li>
  <li>問い: 当サイトの記事で扱っている読者の質問から、「はい・いいえ」で答えられるものを選びました。</li>
  <li>答えの読み分け: 結論を「はい・条件による・いいえ」に分ける作業を2回独立に行い、2回が一致し、
  根拠の一文が答えの本文にあるものだけを数えました。一致しなかった答えは「結論が読み取れず」としています。</li>
  <li>当社は、AIの答えが正しいかを判定していません。この表は「AIが何と答えたか」の記録です。</li>
  </ul>
  </section>'''


def dataset_ld(d):
    return {"@type": "Dataset", "name": d["title"], "description": d["description"], "url": d["domain"] + d["url"],
            "temporalCoverage": d["period"].replace("〜", "/"),
            "distribution": {"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": d["domain"] + d["url"] + "data.csv"},
            "creator": {"@type": "Organization", "name": "セブンセンシズ株式会社"}}


def build(root: Path, domain: str, shell, site="subsidy"):
    """静的なサイトに書き出す（補助金サイトの pages.py から）。書いたら (url, lastmod, llms の1行)"""
    d = data(site, domain)
    if not d:
        return None
    out = root / d["url"].strip("/")
    out.mkdir(parents=True, exist_ok=True)
    (out / "data.csv").write_text(csv_text(d), encoding="utf-8")
    extra = ",\n      " + json.dumps(dataset_ld(d), ensure_ascii=False)
    (out / "index.html").write_text(shell(d["url"], d["title"], d["description"], d["h1"], d["lead"],
                                          html_body(d), "AIへの聞き取り調査", extra), encoding="utf-8")
    return d["url"], d["lastmod"], f"- [{d['title']}]({domain}{d['url']}): {d['description'][:90]}"
