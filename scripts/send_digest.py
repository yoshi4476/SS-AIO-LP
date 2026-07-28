# -*- coding: utf-8 -*-
"""週1ニュースレター（ダイジェスト）配信スクリプト。

使い方:
    python scripts/send_digest.py --demo   # 送信せずHTMLを reports/digest-preview.html に出力
    python scripts/send_digest.py          # Resend Broadcastで購読者リストへ送信

必要な環境変数（.env）:
    RESEND_API_KEY / RESEND_AUDIENCE_ID / LEAD_FROM_EMAIL

スケジュール例（毎週月曜9:00 JST）:
    GitHub Actions: cron "0 0 * * 1" / Windows: schtasks weekly MON 09:00
"""
import json
import os
import re
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_URL = "https://ai.7senses.co.jp"  # ドメイン取得後に差し替え（build.pyと合わせる）
SITE_NAME = "AI集客ラボ"
DAYS = 8  # 直近何日分の記事を載せるか


def load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def recent_articles():
    import yaml
    items = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        if p.name.startswith("_"):
            continue
        m = re.match(r"^---\s*\n(.*?)\n---", p.read_text(encoding="utf-8-sig"), re.S)
        if not m:
            continue
        meta = yaml.safe_load(m.group(1))
        if (meta.get("score") or 0) < 90:
            continue
        pub = date.fromisoformat(str(meta["date"]))
        if pub >= date.today() - timedelta(days=DAYS):
            items.append(meta)
    return sorted(items, key=lambda m: str(m["date"]), reverse=True)


def digest_html(items):
    rows = "".join(
        f'<tr><td style="padding:14px 0;border-bottom:1px solid #e5e7eb;">'
        f'<a href="{SITE_URL}/{m["category"]}/{m["slug"]}/" '
        f'style="font-size:16px;font-weight:bold;color:#0b2447;text-decoration:none;">{m["title"]}</a>'
        f'<div style="font-size:13px;color:#556;margin-top:4px;">{m["description"]}</div></td></tr>'
        for m in items)
    today = date.today()
    return f"""<div style="font-family:sans-serif;max-width:600px;margin:auto;padding:24px;">
<h1 style="font-size:20px;color:#0b2447;">{SITE_NAME} 週刊ダイジェスト</h1>
<p style="font-size:14px;color:#334;">今週公開したAI集客（AIO・LLMO・SEO・MEO）の実践記事をお届けします。（{today.year}年{today.month}月{today.day}日号）</p>
<table style="width:100%;border-collapse:collapse;">{rows}</table>
<p style="margin-top:24px;"><a href="{SITE_URL}/lp/" style="display:inline-block;background:#2563eb;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;">無料の現状分析を申し込む</a></p>
<p style="font-size:11px;color:#889;margin-top:24px;">発行: セブンセンシズ株式会社（{SITE_NAME}）<br>
配信停止は {{{{{{RESEND_UNSUBSCRIBE_URL}}}}}} から行えます。</p>
</div>"""


def main():
    load_env()
    items = recent_articles()
    if not items:
        print("直近の新着記事がないため配信をスキップします")
        return
    html = digest_html(items)
    today = date.today()
    subject = f"【{SITE_NAME}】今週のAI集客まとめ（{today.month}/{today.day}号・{len(items)}本）"

    if "--demo" in sys.argv:
        out = ROOT / "reports" / "digest-preview.html"
        out.parent.mkdir(exist_ok=True)
        out.write_text(html.replace("{{{RESEND_UNSUBSCRIBE_URL}}}", "#"), encoding="utf-8")
        print(f"デモ出力: {out}（件名: {subject} / {len(items)}本）")
        return

    key, aud, sender = (os.environ.get(k) for k in ("RESEND_API_KEY", "RESEND_AUDIENCE_ID", "LEAD_FROM_EMAIL"))
    if not all([key, aud, sender]):
        raise SystemExit("環境変数 RESEND_API_KEY / RESEND_AUDIENCE_ID / LEAD_FROM_EMAIL を設定してください")

    def api(path, body):
        req = urllib.request.Request(
            f"https://api.resend.com{path}", method="POST",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return json.load(r)

    created = api("/broadcasts", {
        "audience_id": aud, "from": sender, "subject": subject, "html": html})
    api(f"/broadcasts/{created['id']}/send", {})
    print(f"配信完了: {subject}（{len(items)}本）")


if __name__ == "__main__":
    main()
