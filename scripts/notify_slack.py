# -*- coding: utf-8 -*-
"""運用通知（Slack Webhook → 未設定ならメールへ自動フォールバック）

使い方: python scripts/notify_slack.py "メッセージ"
優先順位:
  1. SLACK_WEBHOOK_URL が設定されていれば Slack へ送信
  2. なければ Resend でメール送信（宛先: NOTIFY_TO_EMAIL または LEAD_TO_EMAIL）
  3. どちらも未設定なら静かにスキップ（自動実行を失敗させない）
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def main():
    load_env()
    text = sys.argv[1] if len(sys.argv) > 1 else "（メッセージなし）"

    slack = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if slack:
        req = urllib.request.Request(
            slack, data=json.dumps({"text": text}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            print("Slack通知:", r.status)
        return

    key = os.environ.get("RESEND_API_KEY", "").strip()
    to = (os.environ.get("NOTIFY_TO_EMAIL") or os.environ.get("LEAD_TO_EMAIL") or "").strip()
    frm = os.environ.get("LEAD_FROM_EMAIL", "AI集客ラボ <info@ai.7senses.co.jp>").strip()
    if not key or "YOUR_" in key or not to:
        print("SLACK_WEBHOOK_URL / RESEND_API_KEY 未設定 — 通知スキップ")
        return
    subject = text.splitlines()[0][:60]
    body = json.dumps({
        "from": frm, "to": [to],
        "subject": f"【自動運用】{subject}",
        "text": text + "\n\n--\nAI集客ラボ 自動運用システム",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 # CloudflareがデフォルトUAを遮断する（error 1010）ためUA必須
                 "User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"})
    with urllib.request.urlopen(req) as r:
        print("メール通知:", r.status, "→", to)


if __name__ == "__main__":
    main()
