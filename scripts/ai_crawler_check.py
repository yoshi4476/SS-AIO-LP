# -*- coding: utf-8 -*-
"""AIのクローラーが本番サイトに入れるかを、robots.txt と実際のUAの両方で確かめる。

**robots.txt を読むだけでは分からない。** Cloudflare のWAFは robots.txt より手前で
落とすため、Allow と書いてあっても届いていないことがある。
**逆に、UAで叩くだけでも足りない。** Cloudflare の「管理された robots.txt」は
配信時に AI 向けの Disallow を先頭へ差し込むため、原稿の robots.txt が正しくても
本番では塞がっていることがある。Google-Extended は取りに来るUAが無い（robots.txt の
印だけ）ので、こちらでしか見られない。

**なぜ要るか**: Cloudflare は 2026-09-15 から、AIの学習用・エージェント用クローラーを
既定でブロックする方針に変えた（新規ドメイン・無料プランの既存顧客が対象）。
この既定のブロックは「学習用」と「回答用」を区別しない。OAI-SearchBot が届かなければ
ChatGPT Search は引用をやめ、PerplexityBot を塞げば Perplexity も引用をやめる。
記事の質をいくら上げても、ここが閉じていればAI検索には一切出ない。

    python scripts/ai_crawler_check.py          # 確かめる
    python scripts/ai_crawler_check.py --alert   # 塞がっていればメール/Slackで知らせる

終了コードは常に0（CLAUDE.md 8.7）。判定は AI_CRAWLER_OK= の印で行う。
"""
import argparse
import json
import re
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

# robots.txt で塞がれていないかを見る印。Google-Extended は Gemini の学習用の印で、
# 取りに来るUAは無い（Googlebot が取る）ため、UAで叩く一覧には入れない
ROBOTS_AGENTS = ["GPTBot", "OAI-SearchBot", "ClaudeBot", "PerplexityBot",
                 "Google-Extended", "Googlebot"]


def _groups(text):
    """robots.txt を [(user-agent の集合, [(allow?, パターン)])] に分ける。
    連続した User-agent 行は1つのグループ（RFC 9309）"""
    groups, agents, rules, in_rules = [], [], [], False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, val = (s.strip() for s in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if in_rules:                 # 規則の後の User-agent は新しいグループの始まり
                groups.append((agents, rules))
                agents, rules, in_rules = [], [], False
            agents.append(val.lower())
        elif key in ("allow", "disallow"):
            if not agents:               # どのグループにも属さない規則は無視する（Google と同じ）
                continue
            in_rules = True
            if val:                      # 空の Disallow は「何も塞がない」
                rules.append((key == "allow", val))
    if agents:
        groups.append((agents, rules))
    return groups


def _match_len(pattern, path):
    """パターンが path に当たれば長さ（優先度）を、当たらなければ -1 を返す。* と $ に対応"""
    rx = "^" + re.escape(pattern).replace(r"\*", ".*")
    if rx.endswith(r"\$"):
        rx = rx[:-2] + "$"
    return len(pattern) if re.match(rx, path) else -1


def robots_allows(text, agent, path="/"):
    """agent が path を取ってよいか。Google の解釈に合わせる:
    名前の一致するグループを全部まとめて使い（無ければ *）、最も長く当たる規則が勝つ。
    同じ長さなら Allow が勝つ"""
    agent = agent.lower()
    groups = _groups(text)
    rules = [r for ags, rs in groups if agent in ags for r in rs]
    if not any(agent in ags for ags, _ in groups):
        rules = [r for ags, rs in groups if "*" in ags for r in rs]
    best = (-1, True)
    for allow, pat in rules:
        n = _match_len(pat, path)
        if n > best[0] or (n == best[0] and n >= 0 and allow):
            best = (n, allow)
    return best[1]


def fetch_robots(domain):
    """(状態, 本文)。取れなければ本文は None"""
    req = urllib.request.Request(f"https://{domain}/robots.txt",
                                 headers={"User-Agent": CRAWLERS[-1][2]})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None


ROBOTS_FIX = """  robots.txt の直し方

    1. 原稿（site/robots.txt など）に、そのクローラーの Disallow: / が無いか見る
    2. 原稿が正しいのに本番で塞がっている場合は、Cloudflare の「管理された robots.txt」
       （AI Crawl Control）が配信時に Disallow を差し込んでいる。ダッシュボードで外す
    3. Googlebot が塞がると検索とAI Overviewの両方から消える。最優先で直す"""

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
    # お客様の社のドメインは非公開の置き場の設定（sites.load_all が重ねる。公開側の印には無い）
    import sites as S
    return [(sid, d["domain"]) for sid, d in S.load_all().items() if sid != "sample" and d.get("domain")]


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

    print("■ robots.txt で塞がれていないか（本番で配信されているものを読む）")
    robots_bad = []
    for site_id, domain in sites():
        code, text = fetch_robots(domain)
        if text is None:
            # 4xx は「制限なし」、5xx・届かないは「全部禁止」と Google は扱う
            if 400 <= code < 500:
                print(f"  ○ {site_id:<10} robots.txt なし（{code}）… 制限なしとして扱われます")
                continue
            robots_bad.append((site_id, domain, "robots.txt", code or "届かない"))
            print(f"  × {site_id:<10} robots.txt が取れません（{code or '届かない'}）"
                  "… Google は全部禁止として扱います")
            continue
        ng = [a for a in ROBOTS_AGENTS if not robots_allows(text, a, "/")]
        for a in ng:
            robots_bad.append((site_id, domain, a, "Disallow"))
        print(f"  {'×' if ng else '○'} {site_id:<10} {domain}"
              + (f"  塞がれている: {'・'.join(ng)}" if ng else f"  {len(ROBOTS_AGENTS)}種とも許可"))
    print()

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
    if not blocked and not robots_bad:
        print(f"  robots.txt {len(ROBOTS_AGENTS)}種・実際の応答 {checked}件すべて通っています。"
              "AI検索から見える状態です")
        print("AI_CRAWLER_OK=yes")
        return 0

    answer_side = [b for b in blocked if b[3] == "回答"]
    print(f"  塞がっている組み合わせ {len(blocked) + len(robots_bad)}件")
    for site_id, domain, name, why in robots_bad:
        print(f"      {domain} / {name}（robots.txt）… {why}")
    for site_id, domain, name, kind, code, why in blocked:
        print(f"      {domain} / {name}（{kind}）… {code if code else '届かない'} {why}")
    print()
    if answer_side:
        who = "・".join(sorted({b[2] for b in answer_side}))
        print(f"  **回答用のクローラーが塞がっています（{who}）。"
              f"そのAIからの引用は止まります。**")
    print()
    if robots_bad:
        print(ROBOTS_FIX)
    if blocked:
        print(HOW_TO_FIX)
    print("AI_CRAWLER_OK=no")

    if a.alert:
        lines = ([f"{b[1]} / {b[2]}（robots.txt）… {b[3]}" for b in robots_bad]
                 + [f"{b[1]} / {b[2]}（{b[3]}）… {b[4] or '届かない'}" for b in blocked])
        notify("AIクローラーが本番サイトに入れません。AI検索からの引用が止まります。\n"
               + "\n".join(lines)
               + "\n\n" + (ROBOTS_FIX + "\n\n" if robots_bad else "")
               + (HOW_TO_FIX if blocked else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
