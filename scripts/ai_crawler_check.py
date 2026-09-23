# -*- coding: utf-8 -*-
"""AIのクローラーが本番サイトに入れるかを、実際のUAで叩いて確かめる。

**robots.txt を読むだけでは分からない。** Cloudflare のWAFは robots.txt より手前で
落とすため、Allow と書いてあっても届いていないことがある。

**なぜ要るか**: Cloudflare は 2026-09-15 から、AIの学習用・エージェント用クローラーを
既定でブロックする方針に変えた（新規ドメイン・無料プランの既存顧客が対象）。
この既定のブロックは「学習用」と「回答用」を区別しない。OAI-SearchBot が届かなければ
ChatGPT Search は引用をやめ、PerplexityBot を塞げば Perplexity も引用をやめる。
記事の質をいくら上げても、ここが閉じていればAI検索には一切出ない。

    python scripts/ai_crawler_check.py          # 確かめる
    python scripts/ai_crawler_check.py --alert   # 塞がっていればメール/Slackで知らせる

終了コードは常に0（CLAUDE.md 8.7）。判定は AICRAWL_OK= の印で行う。
"""
import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITES = ROOT / "sites"
TIMEOUT = 20

# 実際に使われているUA。回答用（Search）と学習用（Training）を分けて見る。
# 回答用が1つでも塞がっていれば、そのAIからの引用は止まる
CRAWLERS = [
    ("OAI-SearchBot", "回答", "OAI-SearchBot/1.0 (+https://openai.com/searchbot)"),
    ("PerplexityBot", "回答", "Mozilla/5.0 (compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)"),
    ("ClaudeBot", "回答", "Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)"),
    ("GPTBot", "学習", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; GPTBot/1.2; +https://openai.com/gptbot"),
    ("Googlebot", "検索", "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"),
    ("Bingbot", "検索", "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)"),
]

HOW_TO_FIX = """  直し方（Cloudflare のダッシュボードで行う。robots.txt を直しても効かない）

    1. 該当ゾーンを開く → セキュリティ → Bots（または AI Crawl Control）
    2. 「AIボットをブロック」が有効なら外す。または Search / Agent は許可し、
       Training だけブロックに切り替える
    3. 個別に通したい場合は WAF のカスタムルールで
       OAI-SearchBot / PerplexityBot / ClaudeBot を Skip（除外）にする
    4. 保存後、この検査をもう一度実行して 200 になることを確かめる

  robots.txt に Allow と書いてあっても、WAF はその手前で落とすため効きません。
  「回答」の列が塞がっていると、記事の中身に関係なくAI検索から消えます。"""


def sites():
    out = []
    for p in sorted(SITES.glob("*.json")):
        if p.stem == "sample":
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("domain"):
            out.append((p.stem, d["domain"]))
    return out


def probe(domain, ua, path="/"):
    """(状態, 説明) を返す。届かない理由まで分けて出す"""
    req = urllib.request.Request(f"https://{domain}{path}", headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, e.reason or ""
    except Exception as e:
        return 0, str(e)[:60]


def notify(text):
    """異常なので必ず送る（--routine は付けない）。手元では notify_slack 側が止める"""
    try:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "notify_slack.py"), text],
                       timeout=60, capture_output=True, text=True)
    except Exception as e:
        print(f"  通知できませんでした: {str(e)[:80]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alert", action="store_true", help="塞がっていれば通知する")
    a = ap.parse_args()

    print("■ AIクローラーが本番に入れるか（実際のUAで確認）")
    blocked, checked = [], 0
    for site_id, domain in sites():
        marks = []
        for name, kind, ua in CRAWLERS:
            code, why = probe(domain, ua)
            checked += 1
            ok = code == 200
            if not ok:
                blocked.append((site_id, domain, name, kind, code, why))
            marks.append(f"{name}:{code if code else 'x'}")
        bad = [m for m in marks if not m.endswith(":200")]
        head = "×" if bad else "○"
        print(f"  {head} {site_id:<10} {domain}")
        print(f"      {'  '.join(marks)}")

    print()
    if not blocked:
        print(f"  {checked}件すべて 200。AI検索から見える状態です")
        print("AICRAWL_OK=yes")
        return 0

    answer_side = [b for b in blocked if b[3] == "回答"]
    print(f"  塞がっている組み合わせ {len(blocked)}件")
    for site_id, domain, name, kind, code, why in blocked:
        print(f"      {domain} / {name}（{kind}）… {code if code else '届かない'} {why}")
    print()
    if answer_side:
        who = "・".join(sorted({b[2] for b in answer_side}))
        print(f"  **回答用のクローラーが塞がっています（{who}）。"
              f"そのAIからの引用は止まります。**")
    print()
    print(HOW_TO_FIX)
    print("AICRAWL_OK=no")

    if a.alert:
        lines = [f"{b[1]} / {b[2]}（{b[3]}）… {b[4] or '届かない'}" for b in blocked]
        notify("AIクローラーが本番サイトに入れません。AI検索からの引用が止まります。\n"
               + "\n".join(lines)
               + "\n\n" + HOW_TO_FIX)
    return 0


if __name__ == "__main__":
    sys.exit(main())
