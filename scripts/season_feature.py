# -*- coding: utf-8 -*-
"""業種ごとの「今のうちに」と言える時期に、特集を自動で出す（暦は data/season_calendar.json）。

    python scripts/season_feature.py                 # 今日の特集と、今週始まった特集を見る
    python scripts/season_feature.py --kw            # 期間中の特集の語を台帳へ積む（kw_guard を通った語だけ・週次）
    python scripts/season_feature.py --events        # Google の検索の更新を見る（日次）
    python scripts/season_feature.py --events --send # コアアップデートなら購読者へ知らせる

出すところ:
  - 業種LP・業種ページ・トップ: 期間中は「今の時期の特集」の枠（build.py が apply() を呼ぶ。1ページ1つ）
  - 週刊ニュースレター: 特集が始まった週は先頭に載せる（send_digest.py が newsletter() を呼ぶ）
  - 記事: 特集の語を優先度Aで台帳へ（--kw）
  - Google の更新: 検索ステータスの発表から1日以内に、購読者へ公式の発表と確かめ方を知らせる（--events --send）
メールは購読を申し込んだ人（Resend の購読者リスト）だけに送る。問い合わせやツールの利用者には送らない。
"""
import html
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
CAL = ROOT / "data" / "season_calendar.json"
SITE_URL = "https://ai.7senses.co.jp"
JST = timezone(timedelta(hours=9))
E = html.escape
FOOT = ("発行: セブンセンシズ株式会社（AI集客ラボ）<br>〒537-0003 大阪府大阪市東成区神路1丁目7-4 コンフォートビル901・902"
        "<br>info.ai@7senses.co.jp ／ TEL 06-4305-7547<br>このメールは、AI集客ラボのニュースレターに登録いただいた方へお送りしています。"
        "配信停止は {{{RESEND_UNSUBSCRIBE_URL}}} から行えます。")


def today_jst():
    return datetime.now(JST).date()


def load():
    return json.loads(CAL.read_text(encoding="utf-8"))["entries"]


def _md(d):
    return d.strftime("%m-%d")


def _in(md, a, b):
    return a <= md <= b if a <= b else (md >= a or md <= b)


def active(today=None, entries=None):
    today = today or today_jst()
    return sorted([e for e in (entries or load()) if any(_in(_md(today), a, b) for a, b in e["windows"])],
                  key=lambda e: e["rank"])


def started(today=None, days=7, entries=None):
    """直近 days 日のうちに期間が始まった特集（週刊ニュースレターの先頭に載せる分）"""
    today = today or today_jst()
    out = []
    for e in entries or load():
        for a, _ in e["windows"]:
            if a == "01-01" and e["windows"] == [["01-01", "12-31"]]:
                continue                                # 通年の特集は「始まり」が無い
            m, d = map(int, a.split("-"))
            if any(today - timedelta(days=days) < date(y, m, d) <= today for y in (today.year, today.year - 1)):
                out.append(e)
                break
    return sorted(out, key=lambda e: e["rank"])


def pick(kind, key="", today=None, entries=None):
    """そのページに出す特集を1つ（無ければ None）"""
    for e in active(today, entries):
        if kind == "top" and e.get("top"):
            return e
        if kind in ("lp", "hub") and ("*" in e[kind + "s"] or key in e[kind + "s"]):
            return e
    return None


_ARTS = None


def related(e, n=3):
    """特集の語を題に含む、公開済みのAI集客ラボの記事（新しい順）"""
    global _ARTS
    if not e.get("match"):
        return []
    if _ARTS is None:
        import yaml
        import sites
        site = sites.load(sites.primary())
        cats = sites.valid_categories(site)
        _ARTS = []
        for p in (ROOT / "articles").glob("*.md"):
            m = re.match(r"^---\s*\n(.*?)\n---", p.read_text(encoding="utf-8-sig"), re.S)
            if not m:
                continue
            try:
                meta = yaml.safe_load(m.group(1)) or {}
            except Exception:
                continue
            if (meta.get("score") or 0) >= 90 and meta.get("category") in cats and meta.get("title"):
                _ARTS.append((str(meta.get("date", "")), meta["title"], sites.article_url(site, meta).replace(SITE_URL, "")))
        _ARTS.sort(reverse=True)
    return [(t, u) for _, t, u in _ARTS if any(w in t for w in e["match"])][:n]


def box_html(e):
    arts = related(e)
    li = "".join(f'<li><a href="{E(u)}" data-cta="season_{e["id"]}_article">{E(t)}</a></li>' for t, u in arts)
    cl = (f'<a class="btn btn-ghost" href="/download/?ind={e["checklist"]}" data-cta="season_{e["id"]}_checklist">'
          f'チェックリスト（PDF）を受け取る</a>') if e.get("checklist") else ""
    return ('<!-- season -->\n<section class="season-box" aria-label="今の時期の特集" data-season="' + e["id"] + '">'
            '<div class="season-in">'
            f'<p class="season-kicker"><span>今の時期の特集</span>{E(e["label"])}</p>'
            f'<h2>{E(e["title"])}</h2><p class="season-lead">{E(e["lead"])}</p>'
            + (f'<ul class="season-arts">{li}</ul>' if li else "")
            + '<div class="season-btns">'
            f'<a class="btn btn-primary" href="/tools/ai-check/" data-cta="season_{e["id"]}_ai">AI診断で確かめる</a>'
            f'<a class="btn btn-ghost" href="/tools/url-check/" data-cta="season_{e["id"]}_url">URL診断で確かめる</a>{cl}'
            f'<a class="btn btn-ghost" href="/lp/#form" data-cta="season_{e["id"]}_consult">無料で相談する</a>'
            '</div></div></section>\n<!-- /season -->')


EMPTY = "<!-- season --><!-- /season -->"
MARK = re.compile(r"<!-- season -->.*?<!-- /season -->", re.S)


def _put(s, block, hero_rx):
    """印があれば差し替え、無ければヒーローの直後に入れる"""
    if MARK.search(s):
        return MARK.sub(lambda m: block, s, count=1)
    m = re.search(hero_rx, s)
    if not m:
        return s
    end = s.find("</section>", m.end())
    if end < 0:
        return s
    end += len("</section>")
    return s[:end] + "\n" + block + s[end:]


def apply(site: Path, today=None):
    """トップ・業種LP・業種ページの特集の枠をそろえる。変えたファイル数を返す"""
    entries = load()
    n = 0
    jobs = [(site / "index.html", "top", "", r'<section class="section" data-area="無料ツール"')]
    jobs += [(p, "lp", p.parent.name, r'<section class="lx-hero') for p in sorted((site / "lp").glob("*/index.html"))]
    jobs += [(p, "hub", p.parent.name, r'<section class="hero">') for p in sorted((site / "industry").glob("*/index.html"))]
    for p, kind, key, hero in jobs:
        s = p.read_text(encoding="utf-8")
        # 業種ページに調査の要点の図（build.py の rsh-top）があれば、特集はその後ろ（図を見出しの近くに残す）
        if kind == "hub" and '<section class="section rsh-top">' in s:
            hero = r'<section class="section rsh-top">'
        e = pick(kind, key, today, entries)
        new = _put(s, box_html(e) if e else EMPTY, hero)
        if new != s:
            p.write_text(new, encoding="utf-8", newline="")
            n += 1
    return n


def newsletter(today=None):
    """今週始まった特集（週刊ニュースレターの先頭）。(件名に使う題, HTML) か None"""
    es = started(today)
    if not es:
        return None
    blocks = []
    for e in es:
        arts = related(e)
        li = "".join(f'<li style="margin:4px 0;"><a href="{SITE_URL}{E(u)}" style="color:#2563eb;">{E(t)}</a></li>'
                     for t, u in arts)
        cl = (f' ／ <a href="{SITE_URL}/download/?ind={e["checklist"]}" style="color:#2563eb;">業種別チェックリスト（PDF）</a>'
              if e.get("checklist") else "")
        blocks.append(
            '<div style="background:#eaf2fe;border-radius:10px;padding:18px 20px;margin:0 0 18px;">'
            f'<p style="margin:0 0 4px;font-size:12px;color:#2563eb;font-weight:bold;">今の時期の特集｜{E(e["label"])}</p>'
            f'<p style="margin:0 0 8px;font-size:17px;font-weight:bold;color:#0b2447;">{E(e["title"])}</p>'
            f'<p style="margin:0 0 10px;font-size:14px;color:#334;line-height:1.8;">{E(e["lead"])}</p>'
            + (f'<ul style="margin:0 0 10px;padding-left:18px;font-size:14px;">{li}</ul>' if li else "")
            + f'<p style="margin:0;font-size:14px;"><a href="{SITE_URL}/tools/ai-check/" style="color:#2563eb;font-weight:bold;">AI診断で確かめる（無料）</a>'
            f' ／ <a href="{SITE_URL}/tools/url-check/" style="color:#2563eb;">URL診断</a>{cl}</p></div>')
    return es[0]["title"], "".join(blocks)


# ---------- 記事の語 ----------
def add_kws(today=None):
    import hub_client as HC
    picks, seen = [], set()
    for e in active(today):
        for k in e.get("kws", []):
            if k["keyword"] in seen:
                continue
            seen.add(k["keyword"])
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / "kw_guard.py"), k["keyword"], "--site", "ai-lab"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode == 0:
                picks.append({"keyword": k["keyword"], "priority": "A", "category": k.get("category", ""),
                              "note": "季節の特集: " + e["id"]})
            else:
                print(f"  見送り（食い合い審査 {r.returncode}）: {k['keyword']}")
    added = (HC.add_kw("ai-lab", picks) or {}).get("added", 0) if picks else 0
    print(f"SEASON_KW_ADDED={added}（候補 {len(picks)}）")
    return added


# ---------- Google の検索の更新 ----------
INCIDENTS = "https://status.search.google.com/incidents.json"


def ranking_updates(now=None, hours=26, data=None):
    """直近 hours 時間に始まった、検索順位（Ranking）の更新"""
    now = now or datetime.now(timezone.utc)
    if data is None:
        req = urllib.request.Request(INCIDENTS, headers={"User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    out = []
    for i in data:
        if i.get("service_name") != "Ranking" or not i.get("begin"):
            continue
        begin = datetime.fromisoformat(i["begin"].replace("Z", "+00:00"))
        if now - timedelta(hours=hours) < begin <= now:
            out.append({"id": i.get("id", ""), "desc": i.get("external_desc", ""), "begin": begin,
                        "core": "core update" in i.get("external_desc", "").lower(),
                        "url": "https://status.search.google.com/" + i.get("uri", "")})
    return out


def update_mail(u):
    d = u["begin"].astimezone(JST)
    subject = f"【AI集客ラボ】Googleが検索の更新（{u['desc']}）を始めました"
    body = ('<div style="font-family:sans-serif;max-width:600px;margin:auto;padding:24px;color:#334;line-height:1.8;font-size:14px;">'
            f'<h1 style="font-size:19px;color:#0b2447;">Googleが検索の更新を始めました（{d.month}月{d.day}日）</h1>'
            f'<p>Googleは{d.month}月{d.day}日に「{E(u["desc"])}」を始めたと発表しました。'
            f'<a href="{u["url"]}" style="color:#2563eb;">Google 検索ステータス ダッシュボードの発表</a></p>'
            '<p>更新の間は、検索の順位が上下します。順位やアクセスを見比べるのは、更新が終わったとGoogleが発表してからにしてください。'
            '途中の数字で慌ててページを直すと、何が効いたのか分からなくなります。</p>'
            '<p>更新の前と後で、御社のサイトが読まれる状態か、AIにどう紹介されているかは、無料で確かめられます。</p>'
            f'<p><a href="{SITE_URL}/tools/url-check/" style="display:inline-block;background:#2563eb;color:#fff;padding:10px 20px;'
            'border-radius:8px;text-decoration:none;font-weight:bold;">URL診断で確かめる</a> '
            f'<a href="{SITE_URL}/tools/ai-check/" style="color:#2563eb;font-weight:bold;margin-left:8px;">AI診断で確かめる</a></p>'
            f'<p style="font-size:11px;color:#889;margin-top:24px;">{FOOT}</p></div>')
    return subject, body


def broadcast(subject, body):
    key, aud, sender = (os.environ.get(k) for k in ("RESEND_API_KEY", "RESEND_AUDIENCE_ID", "LEAD_FROM_EMAIL"))
    if not all([key, aud, sender]):
        print("SEASON_MAIL=skip（RESEND_API_KEY / RESEND_AUDIENCE_ID / LEAD_FROM_EMAIL が無い）")
        return False

    def api(path, payload):
        req = urllib.request.Request(f"https://api.resend.com{path}", method="POST", data=json.dumps(payload).encode(),
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                              "User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)

    # 補助金サイトなどで配信停止した人（管制塔の「配信除外」）を、送る前に購読者から外す。照らせなければ送らない
    import newsletter_exclude as NE
    try:
        NE.apply(key)
    except NE.NotChecked as e:
        print(f"SEASON_MAIL=skip（{e}）")
        return False
    created = api("/broadcasts", {"audience_id": aud, "from": sender, "subject": subject, "html": body})
    api(f"/broadcasts/{created['id']}/send", {})
    print(f"SEASON_MAIL=sent {subject}")
    return True


def events(send=False):
    import hub_client as HC
    ups = ranking_updates()
    for u in ups:
        print(f"SEASON_EVENT={u['desc']}（{u['begin'].astimezone(JST):%Y-%m-%d %H:%M} JST）{u['url']}")
        if not u["core"]:
            continue                                    # スパム対策の更新は知らせるだけ（多くのサイトに関係しない）
        d = u["begin"].astimezone(JST)
        kw = f"googleコアアップデート {d.year}年{d.month}月 影響"
        HC.add_kw("ai-lab", [{"keyword": kw, "priority": "A", "category": "seo", "note": "検索の更新: " + u["desc"]}])
        # 手元の実行では本番の購読者に送らない（CLAUDE.md 8.7）
        if send and os.environ.get("GITHUB_ACTIONS"):
            broadcast(*update_mail(u))
    if not ups:
        print("SEASON_EVENT=none")
    return ups


def main():
    if "--kw" in sys.argv:
        add_kws()
        return 0
    if "--events" in sys.argv:
        events(send="--send" in sys.argv)
        return 0
    t = today_jst()
    print(f"今日（{t}）の特集:", ", ".join(e["id"] for e in active(t)) or "なし")
    print("今週始まった特集:", ", ".join(e["id"] for e in started(t)) or "なし")
    for kind, key in [("top", "")] + [("lp", k) for k in ("medical", "fudosan", "koumuten", "shigyou")]:
        e = pick(kind, key, t)
        print(f"  {kind}:{key or '-'} → {e['id'] if e else 'なし'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
