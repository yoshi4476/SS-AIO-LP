# -*- coding: utf-8 -*-
"""補助金サイトの「AIに補助金のことを聞いた調査」のページ（/research/ai-hojokin/）。

subsidy_survey.py が記事ごとに残した聞き取りの結果（data/subsidy_survey/*.json）を1ページにまとめる。
pages.py（補助金サイトの一覧・業種・制度のページ）から呼ばれ、同じ枠（ヘッダー・著者・サイドバー・フッター）で出す。

載せるのは「AIが何と答えたか」と「何を根拠にしたか」の集計だけ。AIの答えが正しいかは判定しない
（当社が正誤を決めると、公式の要件と違う判断を当社の見解として広めてしまう）。
"""
import html
import json
import re
from collections import Counter
from pathlib import Path

MAIN = Path(__file__).resolve().parents[2]
SURVEY = MAIN / "data" / "subsidy_survey"
URL = "/research/ai-hojokin/"
LABEL = {"yes": "はい（対象になる・できる）", "cond": "条件による", "no": "いいえ（対象外・できない）"}
MIN_DECIDED = 2          # 結論が読み取れた回答がこれ未満の問いは載せない（割れ方を語れない）


def _load():
    import sys
    sys.path.insert(0, str(MAIN / "scripts"))
    import subsidy_survey as SV
    recs = []
    for p in sorted(SURVEY.glob("*.json")):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if r.get("stance"):
            recs.append(r)
    return recs, SV


def build(root: Path, domain: str, shell):
    """ページを書き出す。shell(title, desc, h1, lead, body_html, crumb_leaf, jsonld_extra) は pages.py の枠。
    書いたら (url, lastmod, llms の1行) を返す。材料が足りなければ None（ページを作らない）"""
    recs, SV = _load()
    rows, engines, dates = [], set(), []
    src = Counter()
    for r in recs:
        dates.append(r["date"])
        t = SV.tally(r)
        for k, v in t["sources"].items():
            src[k] += v
        for q, by in r["stance"].items():
            c = Counter(v["label"] for v in by.values())
            decided = c["yes"] + c["cond"] + c["no"]
            if decided < MIN_DECIDED:
                continue
            engines |= set(by)
            rows.append((r["slug"], q, by, c))
    if len(rows) < 5:
        return None
    period = f"{min(dates)}〜{max(dates)}" if min(dates) != max(dates) else min(dates)
    split = sum(1 for _, _, _, c in rows if len([k for k in ("yes", "cond", "no") if c[k]]) >= 2)
    n_ans = sum(sum(c[k] for k in ("yes", "cond", "no")) for *_, c in rows)
    who = "・".join(sorted(engines))
    total_src = sum(src.values()) or 1

    def esc(s):
        return html.escape(str(s), quote=True)

    trs = []
    for slug, q, by, c in rows:
        cells = []
        for e in sorted(engines):
            v = by.get(e) or {}
            lab = v.get("label")
            if lab in LABEL:
                quote = re.sub(r"[*#`>]", "", v.get("quote", ""))[:70]
                cells.append(f'<td><b>{esc(LABEL[lab])}</b><br><small>「{esc(quote)}」</small></td>')
            else:
                cells.append('<td><small>結論が読み取れず</small></td>')
        trs.append(f'<tr><th scope="row"><a href="/blog/{esc(slug)}/">{esc(q)}</a></th>{"".join(cells)}</tr>')
    body = f'''
  <div class="hub"><b>要点:</b> 当社が{period}に{who}へ補助金の問いを{len(rows)}問聞いたところ、
  <b>{split}問でAIどうしの結論が分かれました</b>（結論が読み取れた{n_ans}回答の集計）。
  AIが根拠に挙げたページ{sum(src.values())}件のうち、公的機関（go.jp など）のページは{src["public"]}件
  （{src["public"] * 100 // total_src}%）で、残りの多くは支援業者・ツール会社などの民間サイトでした。</div>
  <section>
  <h2>AIは何と答えたか（問いごと）</h2>
  <p>同じ問いでも、AIによって結論が違うことがあります。下の表は、各AIの答えの結論と、その根拠になった一文です。
  問いの文をクリックすると、その問いを扱った記事に進みます。</p>
  <div style="overflow-x:auto"><table>
  <thead><tr><th scope="col">問い</th>{"".join(f'<th scope="col">{esc(e)}</th>' for e in sorted(engines))}</tr></thead>
  <tbody>
  {"".join(trs)}
  </tbody></table></div>
  </section>
  <section>
  <h2>この結果の読み方</h2>
  <p><b>AIの答えは、申請の可否を決める根拠になりません。</b>補助の対象・金額・締切は、公募要領と事務局のページで決まります。
  AIが根拠にしたページの多くは民間のサイトで、公募要領より古い情報や、特定の製品をすすめる内容が含まれることがあります。</p>
  <p>AIに聞いて答えが分かれたときは、その問いの言葉で公募要領を検索し、事務局の「よくある質問」で確かめてください。
  判断に迷う点は、申請の前に登録支援事業者へ確認するのが確実です。</p>
  </section>
  <section>
  <h2>調べ方と限界</h2>
  <ul>
  <li>調べた日: {period}。AIの答えは日によって変わります。これはその日の1回の結果です。</li>
  <li>聞いたAI: {who}（いずれも検索つきで回答させ、根拠にしたページのURLを残しました）。</li>
  <li>問い: 当サイトの記事で扱っている読者の質問から、「はい・いいえ」で答えられるものを選びました。</li>
  <li>答えの読み分け: 答えの結論を「はい・条件による・いいえ」に分ける作業を2回独立に行い、2回が一致し、
  根拠の一文が答えの本文にあるものだけを数えました。一致しなかった答えは「結論が読み取れず」としています。</li>
  <li>当社は、AIの答えが正しいかを判定していません。この表は「AIが何と答えたか」の記録です。</li>
  </ul>
  </section>'''
    title = f"AIに補助金のことを聞くと答えは割れる｜{len(rows)}問の調査（当社調べ）"
    desc = (f"当社が{period}に{who}へ補助金の問いを{len(rows)}問聞いた結果。{split}問でAIどうしの結論が分かれ、"
            f"根拠の多くは民間サイトでした。問いごとの答えと、確かめ方をまとめています。")
    dataset = (',\n      { "@type": "Dataset", "name": ' + json.dumps(title, ensure_ascii=False)
               + ', "description": ' + json.dumps(desc, ensure_ascii=False)
               + f', "url": "{domain}{URL}", "temporalCoverage": "{period.replace("〜", "/")}"'
               + ', "creator": { "@type": "Organization", "name": "セブンセンシズ株式会社" } }')
    out = root / URL.strip("/")
    out.mkdir(parents=True, exist_ok=True)
    # 表をそのまま使えるように CSV も置く（引用・再集計のため。根拠の一文も付ける）
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["調べた日", "問い", "AI", "結論", "根拠の一文", "記事"])
    for r in recs:
        for q, by in r["stance"].items():
            if not any(q == x[1] for x in rows):
                continue
            for e, v in sorted(by.items()):
                w.writerow([r["date"], q, e, LABEL.get(v.get("label"), "結論が読み取れず"),
                            re.sub(r"[*#`>]", "", v.get("quote", "")), f"{domain}/blog/{r['slug']}/"])
    (out / "data.csv").write_text("﻿" + buf.getvalue(), encoding="utf-8")
    body += (f'\n  <p><a href="{URL}data.csv" download>この表のデータ（CSV）</a>。'
             '引用するときは、調べた日とAIの名前を添えてください。</p>')
    (out / "index.html").write_text(shell(URL, title, desc, "AIに補助金のことを聞くと、答えはどれくらい割れるか",
                                          f"当社が{who}に補助金の問いを{len(rows)}問聞き、答えの結論と根拠にしたページを集計しました（当社調べ）。",
                                          body, "AIへの聞き取り調査", dataset), encoding="utf-8")
    return URL, max(dates), f"- [{title}]({domain}{URL}): {desc[:90]}"
