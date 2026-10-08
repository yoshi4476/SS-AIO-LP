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
# questions_only: 問いの形の行だけを載せ、根拠のページも載せた問いの答えだけで数える。
# 調べた問いの1つ目は記事の題そのもので、題が問いの形でないと「AI導入補助金の申請代行を京都で頼む前に…」のような
# 題が問いとして並び、しかも記事が取り下げられた後も旧題のまま残った（2026-10-08）。ページの「調べ方」に書いた
# 「はい・いいえで答えられる問い」と合わせる。根拠を載せない問いの分まで数えると「N問聞いたところ…」と合わない
QUESTION = re.compile(r"([?？]|ますか|ませんか|ですか|でしょうか)\s*$")
SITE = {
    "subsidy": {"url": "/research/ai-hojokin/", "topic": "補助金", "article": "/blog/{slug}/", "questions_only": True,
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


def is_question(q):
    return bool(QUESTION.search(str(q).strip()))


def _final_url(site):
    """取り下げ・統合で 301 を書いた記事の URL を、最後の転送先へ（data/retractions.jsonl。retract が配信先へ写す元）。
    調べた記事の多くは後で取り下げ・統合され、調査ページのリンクが転送を経由し、旧題も残っていた"""
    moves = {}
    f = MAIN / "data" / "retractions.jsonl"
    for ln in f.read_text(encoding="utf-8").splitlines() if f.is_file() else []:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get("site") == site and r.get("from") and r.get("to"):
            moves[r["from"]] = r["to"]

    def final(u):
        seen = set()
        while u in moves and u not in seen:
            seen.add(u)
            u = moves[u]
        return u
    return final


def _title(slug):
    """記事の今の題（原稿の title）。原稿が無ければ空"""
    for p in (MAIN / "articles" / f"{slug}.md", MAIN / "articles" / "_legacy" / f"{slug}.md"):
        if p.is_file():
            m = re.search(r'^title:\s*"?(.+?)"?\s*$', p.read_text(encoding="utf-8"), re.M)
            return m.group(1).strip() if m else ""
    return ""


def data(site, domain):
    """ページの中身（サイトに依存しない形）。材料が足りなければ None"""
    import sys
    sys.path.insert(0, str(MAIN / "scripts"))
    import subsidy_survey as SV
    import sites as S
    cfg = SITE[site]
    final = _final_url(site)
    rows, engines, dates, src = [], set(), [], Counter()
    for p in _survey_files(site):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not r.get("stance"):
            continue
        dates.append(r["date"])
        now_title = ""
        if cfg["article"]:
            url = cfg["article"].format(slug=r["slug"])
            if final(url) != url:
                url = final(url)
                now_title = _title(url.strip("/").split("/")[-1])
        else:
            try:
                art = (MAIN / "articles" / f"{r['slug']}.md").read_text(encoding="utf-8")
                cat = (re.search(r"^category:\s*(\S+)", art, re.M) or [0, ""])[1]
                url = S.article_url(S.load(site), {"slug": r["slug"], "category": cat}).replace(domain, "")
            except Exception:
                url = ""
        # 検索から外した記事（noindex）へは調査のページからもリンクしない（問いと答えの集計は調査の結果なので残す）
        import noindex
        if url and noindex.is_hidden(url.rstrip("/").split("/")[-1]):
            url = ""
        shown = set()
        for q, by in r["stance"].items():
            c = Counter(v["label"] for v in by.values())
            if c["yes"] + c["cond"] + c["no"] < MIN_DECIDED:
                continue
            if cfg.get("questions_only") and not is_question(q):
                continue
            shown.add(q)
            engines |= set(by)
            answers = {e: {"label": LABEL.get((by.get(e) or {}).get("label"), "結論が読み取れず"),
                           "quote": re.sub(r"[*#`>]", "", (by.get(e) or {}).get("quote", ""))[:120]}
                       for e in by}
            rows.append({"q": q, "url": url, "date": r["date"], "answers": answers, "now_title": now_title,
                         "split": len([k for k in ("yes", "cond", "no") if c[k]]) >= 2,
                         "decided": c["yes"] + c["cond"] + c["no"]})
        rec = dict(r, answers={q: a for q, a in r.get("answers", {}).items() if q in shown}) if cfg.get("questions_only") else r
        for k, v in SV.tally(rec)["sources"].items():
            src[k] += v
    if len(rows) < MIN_ROWS:
        return None
    period = f"{min(dates)}〜{max(dates)}" if min(dates) != max(dates) else min(dates)
    who = "・".join(sorted(engines))
    split = sum(r["split"] for r in rows)
    n_ans = sum(r["decided"] for r in rows)
    total = sum(src.values()) or 1
    title = f"AIに{cfg['topic']}のことを聞くと答えは割れる｜{len(rows)}問の調査（当社調べ）"
    import desc_fill as DF
    # 説明文は100字以上（Bing が100字未満を「短すぎる」と指摘する）。足すのは数えた件数だけ
    desc = DF.extend(f"当社が{period}に{who}へ{cfg['topic']}の問いを{len(rows)}問聞いた結果。{split}問でAIどうしの結論が分かれました。"
                     f"問いごとの答えと根拠、確かめ方をまとめています。", [f"結論を読み取れた回答は{n_ans}件です。"])
    import research_cite as RC
    h1 = f"AIに{cfg['topic']}のことを聞くと、答えはどれくらい割れるか"
    # コーポレートは会社そのものなので社名だけ。他の2サイトは「社名（サイト名）」で、どのサイトの調査か分かるようにする
    org = RC.org_label("" if site == "corporate" else S.load(site).get("name", ""))
    cite = {"line": RC.cite_line(org, h1, max(dates), domain + cfg["url"]), "terms": RC.TERMS, "org": org}
    return {"site": site, "url": cfg["url"], "title": title, "description": desc, "cite": cite,
            "h1": h1,
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
    import sys
    sys.path.insert(0, str(MAIN / "scripts"))
    import research_cite as RC
    esc = lambda s: html.escape(str(s), quote=True)
    trs = []
    for r in d["rows"]:
        if r.get("now_title") and r["url"]:
            # 調べた記事が統合・取り下げで移ったとき: 問いは聞いたときの文のまま、リンクは移った先の記事を今の題で出す
            q = f'{esc(r["q"])}<br><small>記事: <a href="{esc(r["url"])}">{esc(r["now_title"])}</a></small>'
        else:
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
  <h2>引用する場合</h2>
  {RC.box_html(d["cite"]["line"])}
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
            "usageInfo": d["domain"] + d["url"] + "#cite",
            # Search Console が「license がありません」と知らせるため。引用の条件の枠（#cite）を指す（research_cite.license_url と同じ）
            "license": d["domain"] + d["url"] + "#cite",
            "creator": {"@type": "Organization", "name": "セブンセンシズ株式会社", "url": "https://corp.7senses.co.jp/"}}


TOP_MARK = ("<!--research:top-->", "<!--/research:top-->")
KINDS = {"public": "公的機関（go.jp など）", "private": "民間のサイト", "media": "報道・SNS・動画", "own": "当社のサイト"}


def top_html(d):
    """補助金サイトのトップに置く、調査の要点の小さなグラフ2つ。数字はすべて d（調査のデータ）から読む（手で書かない）。
    図は CSS だけで描き、画像を増やさない。図は role="img" と説明を持ち、同じことを図の下に文字でも書く"""
    esc = lambda s: html.escape(str(s), quote=True)
    n, split = len(d["rows"]), d["split"]
    who = "・".join(d["engines"])
    s = d["sources"]
    total = sum(s.values()) or 1
    pct = lambda k: s.get(k, 0) * 100 // total          # 調査ページの public_pct と同じ切り捨て
    pct_txt = lambda k: f"{pct(k)}%" if pct(k) or not s.get(k) else "1%未満"
    jp = lambda iso: re.sub(r"(\d{4})-0?(\d{1,2})-0?(\d{1,2})", r"\1年\2月\3日", iso)
    when = jp(d["period"])
    same = n - split
    cells = "".join(f'<i class="{"is-split" if i < split else ""}"></i>' for i in range(n))
    said1 = f"調べた{n}問のうち{split}問で、{who}の結論が分かれました。残りの{same}問は結論が同じでした。"
    order = sorted((k for k in KINDS if s.get(k)), key=lambda k: -s[k])
    bars = "".join(
        f'<li class="{"is-em" if k == "public" else ""}"><span class="rs-l">{KINDS[k]}</span>'
        f'<span class="rs-v">{s[k]}件<small>（{pct_txt(k)}）</small></span>'
        f'<span class="rs-t"><span style="width:{s[k] * 100 / total:.1f}%"></span></span></li>' for k in order)
    said2 = (f"AIが根拠にしたページ{total}件のうち、公的機関のページは{s.get('public', 0)}件（{d['public_pct']}%）、"
             f"民間のサイトは{s.get('private', 0)}件（{pct_txt('private')}）でした。")
    return f'''<section id="research" class="rs" aria-labelledby="rs-h" style="background:var(--bg2)">
<style>
#research .rs-grid{{display:grid;grid-template-columns:.9fr 1.1fr;gap:20px;margin-top:30px}}
@media(max-width:860px){{#research .rs-grid{{grid-template-columns:1fr}}}}
#research .rs-card{{margin:0;min-width:0;background:#fff;border:1px solid var(--line);border-radius:var(--radius);padding:24px 24px 20px;box-shadow:var(--shadow)}}
#research .rs-k{{font-size:14px;font-weight:700;color:var(--navy);margin-bottom:12px}}
#research .rs-big{{font-family:var(--num);color:var(--navy);line-height:1.1;margin-bottom:14px}}
#research .rs-big b{{font-size:52px;font-weight:600;letter-spacing:.02em}}
#research .rs-big small{{font-family:var(--sans);font-size:15px;color:var(--muted);margin-left:6px}}
#research .rs-cells{{display:grid;grid-template-columns:repeat({min(n, 25)},1fr);gap:3px;max-width:420px}}
#research .rs-cells i{{display:block;height:26px;border-radius:4px;background:#ebe5d6}}
#research .rs-cells i.is-split{{background:var(--navy2)}}
#research .rs-key{{display:flex;flex-wrap:wrap;gap:6px 16px;margin-top:10px;font-size:13px;color:var(--muted)}}
#research .rs-key span::before{{content:"";display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:6px;vertical-align:-1px;background:#ebe5d6}}
#research .rs-key span.is-split::before{{background:var(--navy2)}}
#research .rs-bars{{list-style:none;margin:0;padding:0;display:grid;gap:12px}}
#research .rs-bars li{{display:grid;grid-template-columns:1fr auto;gap:4px 12px;align-items:baseline;font-size:14px}}
#research .rs-l{{color:var(--text)}}
#research .rs-v{{font-family:var(--num);font-size:17px;color:var(--text);white-space:nowrap}}
#research .rs-v small{{font-family:var(--sans);font-size:12.5px;color:var(--muted);margin-left:2px}}
#research .rs-t{{grid-column:1/-1;display:block;height:12px;border-radius:6px;background:#f1ece0;overflow:hidden}}
#research .rs-t span{{display:block;height:100%;min-width:3px;border-radius:6px;background:#c9bfa6}}
#research li.is-em .rs-l{{font-weight:700;color:var(--navy)}}
#research li.is-em .rs-t span{{background:var(--navy2)}}
#research figcaption{{margin-top:14px;padding-top:12px;border-top:1px dashed var(--line);font-size:14px;color:var(--muted);line-height:1.8}}
#research .rs-note{{margin-top:22px;font-size:14px;color:var(--muted);max-width:860px}}
#research .rs-cta{{margin-top:18px}}
</style>
  <div class="wrap rev">
    <p class="kicker">Research</p>
    <h2 id="rs-h">補助金をAIに聞くと、<br class="sp"><span class="accent">答えは割れます</span></h2>
    <p class="lead">当社が{esc(when)}に{esc(who)}へ、補助金について読者が聞きそうな問いを{n}問聞き、AIの結論と、根拠にしたページを数えました（当社調べ）。</p>
    <div class="rs-grid">
      <figure class="rs-card">
        <p class="rs-k">AIどうしで結論が分かれた問い</p>
        <div role="img" aria-label="{esc(said1)}">
          <p class="rs-big"><b>{split}</b>問<small>／{n}問中</small></p>
          <div class="rs-cells">{cells}</div>
          <p class="rs-key"><span class="is-split">結論が分かれた {split}問</span><span>結論が同じ {same}問</span></p>
        </div>
        <figcaption>{esc(said1)}</figcaption>
      </figure>
      <figure class="rs-card">
        <p class="rs-k">AIが根拠にしたページの種類（{total}件）</p>
        <ol class="rs-bars" role="img" aria-label="{esc(said2)}">{bars}</ol>
        <figcaption>{esc(said2)}</figcaption>
      </figure>
    </div>
    <p class="rs-note">AIの答えは、申請の可否を決める根拠になりません。補助の対象・金額・締切は、公募要領と事務局のページで確かめてください。調べた日は{esc(when)}で、その日の1回の結果です。</p>
    <p class="rs-cta"><a class="btn btn-ghost" href="{d["url"]}" data-cta="top_research">問いごとの答えと根拠を見る</a></p>
  </div>
</section>'''


def put_top(root: Path, domain: str, site="subsidy"):
    """トップ（index.html）の目印のあいだに top_html を入れ直す（配信のたびに pages.py が呼ぶ）。
    目印が無ければ何もしない。材料が足りなければ目印のあいだを空にする（古い数字を残さない）"""
    f = root / "index.html"
    if not f.is_file():
        return "トップがありません"
    t = f.read_bytes().decode("utf-8", "surrogateescape")
    a, b = TOP_MARK
    i, j = t.find(a), t.find(b)
    if i < 0 or j < i:
        return "目印（<!--research:top-->）がありません"
    d = data(site, domain)
    nl = "\r\n" if "\r\n" in t else "\n"
    body = (nl + top_html(d).replace("\n", nl) + nl) if d else ""
    if t[i + len(a):j] == body:
        return "変わりません"
    f.write_bytes((t[:i + len(a)] + body + t[j:]).encode("utf-8", "surrogateescape"))
    return "入れ直しました" if d else "材料が足りないので空にしました"


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
