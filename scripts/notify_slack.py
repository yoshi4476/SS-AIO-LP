# -*- coding: utf-8 -*-
"""Slack Incoming Webhook通知

使い方: python scripts/notify_slack.py "メッセージ"
環境変数 SLACK_WEBHOOK_URL 未設定時は静かにスキップ（自動実行を失敗させない）
"""
import json
import os
import sys
import urllib.request


def main():
    url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not url:
        print("SLACK_WEBHOOK_URL 未設定 — 通知スキップ")
        return
    text = sys.argv[1] if len(sys.argv) > 1 else "（メッセージなし）"
    req = urllib.request.Request(
        url, data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        print("Slack通知:", r.status)


if __name__ == "__main__":
    main()
