# -*- coding: utf-8 -*-
"""運用通知（Slack Webhook → 未設定ならメールへ自動フォールバック）

使い方: python scripts/notify_slack.py "メッセージ"
優先順位:
  1. SLACK_WEBHOOK_URL が設定されていれば Slack へ送信
  2. なければ Resend でメール送信（宛先: NOTIFY_TO_EMAIL または LEAD_TO_EMAIL）
  3. どちらも未設定なら静かにスキップ（自動実行を失敗させない）

**手元で動かしても本番の宛先には送らない。** `.env` に RESEND_API_KEY と
LEAD_TO_EMAIL があるため、動作確認のつもりの実行が info.ai へ本物のメールを
出していた（`（メッセージなし）` と、引用符が壊れて `$icon` だけの本文が
実際に届いた）。送るには --force を付ける。
"""
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 引用符が壊れると、展開されないシェル変数が本文の先頭に残る。
# 中身の無い通知を送ると、次から誰も通知を読まなくなる
UNEXPANDED = re.compile(r"^\s*\$\{?\{?\s*[A-Za-z_]")


def load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def unsendable(text):
    """送ってはいけない通知かを見る。理由を返す（空なら送ってよい）"""
    t = (text or "").strip()
    if not t:
        return "本文が空です"
    if UNEXPANDED.match(t):
        return "シェル変数が展開されていません（呼び出し側の引用符を確認）"
    return ""


def main():
    load_env()
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv[1:]
    text = args[0] if args else ""

    why = unsendable(text)
    if why:
        print("送りません:", why)
        print("  受け取った本文:", repr(text[:80]))
        return

    # 手元での実行が本番の宛先に届かないようにする。
    # 定期実行は GitHub Actions 上なので、この判定で止まらない
    if not os.environ.get("GITHUB_ACTIONS") and not force:
        print("手元での実行のため送信しません（送るなら --force）")
        print("  本文:", text.splitlines()[0][:70])
        return

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
