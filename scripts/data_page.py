# -*- coding: utf-8 -*-
"""自社で測った数字を、そのまま公開ページにする。

被リンクが実質ゼロだった。90日間で外部サイトからの流入は、
ドメイン管理画面と検索アグリゲータを除くと0件。外部に頼める相手が
いない以上、引用される理由を自分で作るほかない。

小さい会社が自力で用意できる「引用される資産」は一次データである。
AI検索経由の流入を実数で公開している日本企業はまだ少ない。
他社のAIO記事が数字を探すとき、出典として選ばれうる。

数字はすべてGA4とSearch Consoleの実測から作る。手で書かない。
割合には必ず母数と集計期間を添える（景品表示法。推計値を実績として
出さないため）。

  python scripts/data_page.py            # site/data/index.html を作る
  python scripts/data_page.py --dry-run  # 中身だけ確認する
"""
import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
SHELL = ROOT / "site" / "lab" / "index.html"
OUT = ROOT / "site" / "data" / "index.html"

AI_SOURCES = {"ChatGPT": ("chatgpt", "openai"), "Claude": ("claude.ai",),
              "Gemini": ("gemini", "bard"), "Perplexity": ("perplexity",),
              "Copilot": ("copilot",)}


def ga_sessions(prop, days):
    import gcreds
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (DateRange, Dimension, Metric,
                                                    RunReportRequest)
    cl = BetaAnalyticsDataClient(credentials=gcreds.load(
        ROOT / "indexing-service-account.json",
        ["https://www.googleapis.com/auth/analytics.readonly"]))
    r = cl.run_report(RunReportRequest(
        property="properties/" + str(prop),
        date_ranges=[DateRange(start_date=f"{days}daysAgo", end_date="yesterday")],
        dimensions=[Dimension(name="sessionSource")],
        metrics=[Metric(name="sessions")], limit=300))
    return [(x.dimension_values[0].value.lower(), int(x.metric_values[0].value))
            for x in r.rows]


def gsc_bands(domain, start, end):
    import gcreds
    from googleapiclient.discovery import build
    sc = build("searchconsole", "v1", credentials=gcreds.load(
        ROOT / "indexing-service-account.json",
        ["https://www.googleapis.com/auth/webmasters.readonly"]))
    rows = sc.searchanalytics().query(siteUrl=f"https://{domain}/", body={
        "startDate": start.isoformat(), "endDate": end.isoformat(),
        "dimensions": ["page"], "rowLimit": 5000}).execute().get("rows", [])
    return [r for r in rows if r["keys"][0].rstrip("/").count("/") >= 4]


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_body(days=28):
    conf = {p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in (ROOT / "sites").glob("*.json")}
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=days - 1)

    # 1. AI検索経由の流入。実数と母数を並べる
    ai_tot, all_tot = {k: 0 for k in AI_SOURCES}, 0
    for c in conf.values():
        prop = c.get("ga4_property_id")
        if not prop:
            continue
        for src, n in ga_sessions(prop, days):
            all_tot += n
            for name, keys in AI_SOURCES.items():
                if any(k in src for k in keys):
                    ai_tot[name] += n
                    break
    ai_sum = sum(ai_tot.values())

    # 2. 順位帯ごとの実測クリック率
    B = [("1〜3位", 0, 3.5), ("4〜5位", 3.5, 5.5), ("6〜10位", 5.5, 10.5),
         ("11〜20位", 10.5, 20.5), ("21位以下", 20.5, 999)]
    agg = {b[0]: [0, 0, 0] for b in B}
    for c in conf.values():
        for r in gsc_bands(c["domain"], start, end):
            for n, lo, hi in B:
                if lo <= r["position"] < hi:
                    a = agg[n]
                    a[0] += 1
                    a[1] += int(r["impressions"])
                    a[2] += int(r["clicks"])
                    break

    arts = len(list((ROOT / "articles").glob("*.md")))
    period = f"{start.isoformat()}〜{end.isoformat()}（{days}日間）"

    h = [f'''<main class="lab">
<section class="hero">
<span class="kicker">OPEN DATA</span>
<h1>AI検索の実測データ</h1>
<p class="lead">セブンセンシズが運営する3サイトで実際に計測した数字を、そのまま公開しています。
推計値や業界平均ではありません。手で書き換えず、GA4とSearch Consoleから自動で更新しています。</p>
<p class="freshness">集計期間: {esc(period)}／対象: 自社運営3サイト・記事{arts}本／最終更新: {date.today().isoformat()}</p>
</section>

<section class="section">
<h2>1. 生成AI経由の流入（実数）</h2>
<p>AI検索から自社サイトに何人来ているかを、参照元ドメインで数えた実数です。
<strong>母数は同じ期間の全セッション{all_tot:,}件</strong>で、そのうちAI経由は{ai_sum:,}件
（{ai_sum / all_tot * 100:.1f}%）でした。</p>
<table><thead><tr><th>生成AI</th><th>セッション数</th><th>全体に占める割合</th></tr></thead><tbody>''']
    for name in AI_SOURCES:
        n = ai_tot[name]
        pct = n / all_tot * 100 if all_tot else 0
        h.append(f"<tr><td>{esc(name)}</td><td>{n:,}</td><td>{pct:.2f}%</td></tr>")
    h.append('''</tbody></table>
<p>母数が小さいため、割合は参考値です。実数をそのまま載せているのは、
割合だけでは規模が分からず、比較に使えないためです。</p>
</section>

<section class="section">
<h2>2. 検索順位ごとの実測クリック率</h2>
<p>自社3サイトの記事ページを、Search Consoleの平均掲載順位で分けて集計しました。
<strong>一般に公開されているCTR表とは値が異なります</strong>。AI Overviewの表示や
検索語の性質によって、同じ順位でもクリック率は変わります。</p>
<table><thead><tr><th>順位帯</th><th>ページ数</th><th>表示回数</th><th>クリック</th><th>クリック率</th></tr></thead><tbody>''')
    for n, _, _ in B:
        p_, i_, c_ = agg[n]
        h.append(f"<tr><td>{esc(n)}</td><td>{p_}</td><td>{i_:,}</td><td>{c_:,}</td>"
                 f"<td>{c_ / i_ * 100 if i_ else 0:.2f}%</td></tr>")
    h.append('''</tbody></table>
<p>ページ数が少ない帯の数値は揺れます。判断に使う場合は表示回数の欄も併せてご覧ください。</p>
</section>

<section class="section">
<h2>この数字の使い方</h2>
<p>出典を明記いただければ、記事・資料への引用は自由です。
リンクなしの転載でも構いませんが、<strong>集計期間と母数は必ず添えてください</strong>。
数字だけが独り歩きすると、読んだ方の判断を誤らせます。</p>
<p>出典表記の例: セブンセンシズ株式会社「AI検索の実測データ」
（https://ai.7senses.co.jp/data/、集計期間: ''' + esc(period) + '''）</p>
</section>
</main>''')
    return "\n".join(h)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--days", type=int, default=28)
    a = ap.parse_args()

    body = build_body(a.days)
    if a.dry_run:
        print(re.sub(r"<[^>]+>", " ", body)[:1400])
        return 0

    shell = SHELL.read_text(encoding="utf-8")
    head = shell[:shell.index("<main")]
    tail = shell[shell.index("</main>") + len("</main>"):]
    head = head.replace("実装ラボ｜このサイト自体をAIO対策の実験場にしています",
                        "AI検索の実測データ｜自社3サイトの計測結果を公開")
    head = re.sub(r'<link rel="canonical" href="[^"]*"',
                  '<link rel="canonical" href="https://ai.7senses.co.jp/data/"', head)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(head + body + tail, encoding="utf-8", newline="")
    print(f"作成: {OUT.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
