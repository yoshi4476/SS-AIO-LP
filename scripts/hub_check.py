# -*- coding: utf-8 -*-
"""管制塔スプレッドシートを直接読めるか確かめ、中身の要約を出す

これまで管制塔へは GAS のWebアプリ経由でしか触れず、
1回の呼び出しで取れる範囲しか見られなかった。サービスアカウントに
シートを共有すれば、Sheets API で直接読める（集計も速く、GASの実行時間制限も無い）。

使い方: python scripts/hub_check.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import gcreds  # noqa: E402

SA = ROOT / "indexing-service-account.json"
HUB_SHEET = "1ew-xG28Nd-jWSorqGgwYmHoV-DCwUtI40bRH2Y4IDOQ"
SCOPE = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def main():
    from googleapiclient.discovery import build
    try:
        sv = build("sheets", "v4", credentials=gcreds.load(SA, SCOPE)).spreadsheets()
        d = sv.get(spreadsheetId=HUB_SHEET,
                   fields="properties.title,sheets.properties.title").execute()
    except Exception as e:
        if "403" in str(e):
            import json
            em = json.loads(SA.read_text(encoding="utf-8"))["client_email"]
            print("  管制塔がサービスアカウントに共有されていません")
            print(f"    共有先: {em}（閲覧者で十分）")
            print(f"    対象: https://docs.google.com/spreadsheets/d/{HUB_SHEET}/edit")
            return
        raise
    print(f"■ {d['properties']['title']}")
    for s in d["sheets"]:
        t = s["properties"]["title"]
        v = sv.values().get(spreadsheetId=HUB_SHEET, range=f"'{t}'!A1:Z",
                            valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
        head = " / ".join(str(x)[:10] for x in (v[0][:6] if v else []))
        print(f"    {t:<18} {max(0, len(v) - 1):>5}行   {head}")


if __name__ == "__main__":
    main()
