# -*- coding: utf-8 -*-
"""できあがったレポートをメールで送る。

月次レポートは1サイトずつ別便で送る作りだったため、まとめて渡したいときに
何通も操作が要った。ここでは Desktop/レポート一式 の中身をまとめて送る。

添付の上限は1通40MB（Resend）。超えるときは分けるよう促す。

  python scripts/send_reports.py --dry-run   # 送らずに内容だけ確認
  python scripts/send_reports.py             # 月次と週次を2通で送る
"""
import argparse
import base64
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = Path.home() / "Desktop" / "レポート一式"
LIMIT = 38 * 1024 * 1024      # 40MBが上限。余白を見て38MBで止める


def env(key, default=""):
    t = (ROOT / ".env").read_text(encoding="utf-8", errors="replace")
    m = re.search(rf"^{key}\s*=\s*(.*)$", t, re.M)
    return (m.group(1).strip().strip('"').strip("'") if m else default) or default


def send(subject, text, files, to, dry=False):
    total = sum(f.stat().st_size for f in files)
    if total > LIMIT:
        print(f"  × {subject}: 添付が{total/1024/1024:.1f}MBで上限を超えます。分けてください")
        return False
    print(f"  {'（確認）' if dry else ''}{subject}")
    print(f"     宛先 {to} / 添付 {len(files)}件 / {total/1024/1024:.1f}MB")
    for f in files:
        print(f"       - {f.name}")
    if dry:
        return True
    key, frm = env("RESEND_API_KEY"), env("LEAD_FROM_EMAIL")
    if not key or "YOUR_" in key or not frm:
        print("     × RESEND_API_KEY / LEAD_FROM_EMAIL が未設定です")
        return False
    payload = json.dumps({
        "from": frm, "to": [to], "subject": subject, "text": text,
        "attachments": [{"filename": f.name,
                         "content": base64.b64encode(f.read_bytes()).decode()}
                        for f in files],
    }).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 # CloudflareがPython既定のUAを1010で弾く
                 "User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            print(f"     ○ 送信しました（HTTP {r.status}）")
            return True
    except Exception as e:
        body = getattr(e, "read", lambda: b"")().decode("utf-8", "replace")[:200]
        print(f"     × 送信できません: {e} {body}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--to", default="")
    a = ap.parse_args()
    to = a.to or env("LEAD_TO_EMAIL", "info.ai@7senses.co.jp")

    if not SRC.is_dir():
        print(f"{SRC} がありません")
        return 1
    monthly = sorted(p for p in SRC.iterdir() if p.name.startswith("月次"))
    weekly = sorted(p for p in SRC.iterdir() if p.name.startswith("週次"))
    if not (monthly or weekly):
        print("送るファイルがありません")
        return 1

    ok = True
    if monthly:
        ok &= send(
            f"【セブンセンシズ】月次レポート一式（{len(monthly)}件）",
            "これまでに作成した月次レポートをまとめてお送りします。\n\n"
            "・AI集客ラボ / コーポレート / 補助金サポートの各サイト\n"
            "・3サイト横断のグループレポート\n\n"
            "2026年6月はコーポレートと補助金のサイトが立ち上がる前のため、"
            "ラボと横断のみです。\n"
            "8月分には「週次の順位推移」と「次に狙う検索語と、選んだ理由」を"
            "新しく入れています。\n\n"
            f"作成: {date.today()}／出典: Search Console・GA4の実測",
            monthly, to, a.dry_run)
    if weekly:
        ok &= send(
            f"【セブンセンシズ】週次レポート（{len(weekly)}件）",
            "週次レポートをお送りします。ブラウザで開いてご覧ください。\n\n"
            "月次では、直した結果が出たのか分からないまま次の月に入ります。\n"
            "週単位で順位・表示・クリックを見ると、直した翌週に効いたかが分かります。\n\n"
            "順位の折れ線は上下を反転して描いています。"
            "線が上がっていれば順位が改善しています。\n\n"
            f"作成: {date.today()}／出典: Search Console・GA4の実測",
            weekly, to, a.dry_run)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
