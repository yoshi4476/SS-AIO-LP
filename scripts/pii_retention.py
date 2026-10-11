# -*- coding: utf-8 -*-
"""個人情報の保存期間を過ぎた行から、お名前・メール・電話・本文などの個人の情報だけを消す（管制塔の pii_retention）。

持っていなければ漏れない（2026-10-11 運用者「顧客情報が漏れないように」「自動ですべて」）。消すのは個人の情報の列だけで、
日付・サイト・種別・会社名・温度・対応状況は残す（件数の集計と効果の測定は変わらない）。期間は contact.hub.gs の PII_DAYS:
  問い合わせの相談 3年（既存客・契約中・成約は消さない）／売り込み・テスト・対応不要 1年
  AI紹介チェックのメール 1年・IPアドレス 90日（1日の回数の上限にしか使わない）／自動回答のメール 1年

    python scripts/pii_retention.py           # 消す件数を見るだけ
    python scripts/pii_retention.py --apply   # 消す（週次の findings が呼ぶ）
出す印: PII_RETENTION_OK=yes（消した・消すものが無い）/ unknown（管制塔に届かない）。件数だけを出す
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
LABEL = {"lead": "問い合わせ（相談・3年）", "noise": "問い合わせ（売り込み・テスト・対応不要・1年）",
         "check_mail": "AI紹介チェックのメール（1年）", "check_ip": "AI紹介チェックのIPアドレス（90日）",
         "review": "自動回答のメール（1年）"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    import hub_client as HC
    r = HC._post({"action": "pii_retention", "dry": not a.apply}) or {}
    if not r.get("ok"):
        print(f"PII_RETENTION_OK=unknown（管制塔に届きません: {r.get('error', '応答なし')}）")
        return 0
    n = sum(int(r.get(k) or 0) for k in LABEL)
    for k, lab in LABEL.items():
        if r.get(k):
            print(f"  {lab}: {r[k]}行{'を消しました' if a.apply else 'が期限を過ぎています'}")
    print(f"PII_RETENTION_OK=yes（{'消した' if a.apply else '期限を過ぎた'}行 {n}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
