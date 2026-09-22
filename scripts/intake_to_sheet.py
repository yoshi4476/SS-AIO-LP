# -*- coding: utf-8 -*-
"""一次データの記入シートを、管制塔のスプレッドシートにタブとして作る。

Excelを配ると、どこに置いたか分からなくなり、記入も止まる。
管制塔（普段見ているスプレッドシート）に置けば、開いてすぐ書ける。

作るタブは5つ。**埋めるのは黄色いセルの数字だけ**で、
何を数えるか・どう判定するかは記入済みにする。

書き終えたら `--pull` で読み取り、data/datasets/ に入れて公開する。
Excelの経路（data_intake.py）と同じ検査を通すので、
母数10未満の割合や個社が分かる情報は止まる。

    python scripts/intake_to_sheet.py            # タブを作る
    python scripts/intake_to_sheet.py --pull     # 書かれた内容を取り込む
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

SA = ROOT / "indexing-service-account.json"
SCOPE = ["https://www.googleapis.com/auth/spreadsheets"]
PREFIX = "一次データ"

HEAD = ["項目", "値", "分子", "分母", "判定の条件", "判定期間・月", "開始", "終了", "備考"]

# タブ名 -> (概要, データ行, 注意書き)
PLANS = {
    f"{PREFIX}1_口コミ増加": {
        "overview": [
            ("slug", "meo-kuchikomi-zouka-gyoushu"),
            ("題名", "業種別の口コミ増加件数"),
            ("説明", "G-ranで運用した店舗について、運用開始前後の口コミ件数の変化を業種別に集計しました。"),
            ("母数（件数）", ""),
            ("母数の単位", "店舗"),
            ("対象期間（開始）", ""),
            ("対象期間（終了）", ""),
            ("集計方法・出典",
             "G-ranの管理画面から運用開始日・開始時の口コミ件数・6か月後の口コミ件数を取り出し、業種ごとに増加数の中央値を算出"),
            ("値の単位", "件"),
            ("関連カテゴリ", "meo"),
            ("分母の呼び名", "店舗数"),
        ],
        "rows": [
            ["飲食店", "", "", "", "運用開始から6か月後の口コミ件数 − 開始時", "6", "", "", ""],
            ["整骨院・接骨院", "", "", "", "同上", "6", "", "", ""],
            ["クリニック", "", "", "", "同上", "6", "", "", ""],
            ["歯科医院", "", "", "", "同上", "6", "", "", ""],
            ["美容室・サロン", "", "", "", "同上", "6", "", "", ""],
        ],
        "note": "業種は10店舗以上そろったものだけ残してください。10未満は行ごと削除します（個社が特定されるため）。",
    },
    f"{PREFIX}2_効果までの月数": {
        "overview": [
            ("slug", "meo-kouka-madeno-tsukisuu"),
            ("題名", "MEO運用を始めてから順位が上がるまでの月数"),
            ("説明", "G-ranで運用した店舗について、主要キーワードの順位が運用開始時より上がった月を集計しました。"),
            ("母数（件数）", ""),
            ("母数の単位", "店舗"),
            ("対象期間（開始）", ""),
            ("対象期間（終了）", ""),
            ("集計方法・出典",
             "運用開始月を0として、主要キーワードの平均順位が開始時より上がった最初の月を店舗ごとに記録し、月ごとの到達割合を算出"),
            ("値の単位", "%"),
            ("関連カテゴリ", "meo"),
            ("分母の呼び名", "店舗数"),
            ("分子の呼び名", "順位が上がった"),
        ],
        "rows": [
            ["1か月以内", "", "", "", "主要KWの平均順位が開始時より上がった", "1", "", "", "累計"],
            ["3か月以内", "", "", "", "同上", "3", "", "", "累計"],
            ["6か月以内", "", "", "", "同上", "6", "", "", "累計"],
            ["12か月以内", "", "", "", "同上", "12", "", "", "累計"],
        ],
        "note": "累計で書きます（3か月以内には1か月以内も含む）。分子＝到達した店舗数、分母＝全店舗数。",
    },
    f"{PREFIX}3_不採択の理由": {
        "overview": [
            ("slug", "hojokin-fusaitaku-riyuu"),
            ("題名", "AI導入補助金で不採択になった理由の内訳"),
            ("説明", "当社が支援した申請のうち不採択となった案件について、事務局の通知と面談記録から理由を分類しました。"),
            ("母数（件数）", ""),
            ("母数の単位", "件"),
            ("対象期間（開始）", ""),
            ("対象期間（終了）", ""),
            ("集計方法・出典",
             "支援した申請の一覧から不採択の案件を抽出し、通知に記載された理由と申請時の記録を突き合わせて分類。複数ある場合は主たる理由1つに寄せた"),
            ("値の単位", "件"),
            ("関連カテゴリ", "hojokin"),
            ("分母の呼び名", "不採択件数"),
        ],
        "rows": [
            ["事業計画の数値根拠が弱い", "", "", "", "", "", "", "", ""],
            ["対象要件を満たしていない", "", "", "", "", "", "", "", ""],
            ["導入ツールが対象外", "", "", "", "", "", "", "", ""],
            ["書類の不備・期限", "", "", "", "", "", "", "", ""],
            ["その他", "", "", "", "", "", "", "", ""],
        ],
        "note": "分類は実際の通知の言葉に合わせて増減して構いません。値＝件数。",
    },
    f"{PREFIX}4_交付までの日数": {
        "overview": [
            ("slug", "hojokin-koufu-madeno-nissuu"),
            ("題名", "申請から交付決定までの日数"),
            ("説明", "当社が支援した申請について、申請日から交付決定日までの日数を集計しました。"),
            ("母数（件数）", ""),
            ("母数の単位", "件"),
            ("対象期間（開始）", ""),
            ("対象期間（終了）", ""),
            ("集計方法・出典",
             "支援した申請の一覧から、申請日と交付決定日が両方記録されている案件を抽出し、日数の分布を算出"),
            ("値の単位", "件"),
            ("関連カテゴリ", "hojokin"),
            ("分母の呼び名", "案件数"),
        ],
        "rows": [
            ["30日以内", "", "", "", "", "", "", "", "公募回を書いてください"],
            ["31〜60日", "", "", "", "", "", "", "", ""],
            ["61〜90日", "", "", "", "", "", "", "", ""],
            ["91日以上", "", "", "", "", "", "", "", ""],
        ],
        "note": "公募回によって差が出ます。備考に公募回を書いてください。",
    },
    f"{PREFIX}5_月次決算の日数": {
        "overview": [
            ("slug", "keiri-bpo-getsuji-nissuu"),
            ("題名", "経理BPO導入前後の月次決算の所要日数"),
            ("説明", "経理BPOを導入した企業について、月次決算が締まるまでの日数を導入前後で比べました。"),
            ("母数（件数）", "10"),
            ("母数の単位", "社"),
            ("対象期間（開始）", ""),
            ("対象期間（終了）", ""),
            ("集計方法・出典", "導入前3か月と導入後3か月の平均所要日数を社ごとに出し、その中央値を比較"),
            ("値の単位", "日"),
            ("関連カテゴリ", "blog"),
            ("分母の呼び名", "社数"),
        ],
        "rows": [
            ["導入前", "", "", "10", "月末から決算が締まるまでの日数", "3", "", "", "10社の中央値"],
            ["導入後", "", "", "10", "同上", "3", "", "", "10社の中央値。個社差が大きい"],
        ],
        "note": "母数10社なので割合では書きません。「◯日短縮」とも書かず、前後2行を出して読者に引き算させます。",
    },
}


def _sheet_id():
    env = dict(os.environ)
    f = ROOT / ".env"
    if f.is_file():
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.match(r"^([A-Z0-9_]+)\s*=\s*(.*)$", line.strip())
            if m:
                env.setdefault(m.group(1), m.group(2).strip().strip('"\''))
    return env.get("SPREADSHEET_ID", "")


def _svc():
    import gcreds
    from googleapiclient.discovery import build
    return build("sheets", "v4", credentials=gcreds.load(SA, SCOPE))


def push():
    sid = _sheet_id()
    if not sid or not SA.is_file():
        print("  SPREADSHEET_ID か サービスアカウントがありません")
        return 1
    svc = _svc()
    meta = svc.spreadsheets().get(spreadsheetId=sid).execute()
    have = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}

    add = [{"addSheet": {"properties": {"title": t}}}
           for t in PLANS if t not in have]
    if add:
        svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": add}).execute()
        meta = svc.spreadsheets().get(spreadsheetId=sid).execute()
        have = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}

    for title, plan in PLANS.items():
        rows = [["■ この表について", plan["note"]], [""]]
        rows.append(["■ 概要（黄色いセルを埋めてください）", ""])
        for k, v in plan["overview"]:
            rows.append([k, v])
        rows += [[""], ["■ データ（黄色いセルを埋めてください）"], HEAD]
        rows += plan["rows"]
        rows.append([""] * len(HEAD))
        svc.spreadsheets().values().update(
            spreadsheetId=sid, range=f"'{title}'!A1",
            valueInputOption="RAW", body={"values": rows}).execute()

        # 見た目: 見出しを太字に、記入欄を黄色に
        gid = have[title]
        ov_start = 4                      # 概要の1行目（0始まり）
        ov_end = ov_start + len(plan["overview"])
        dt_head = ov_end + 2
        dt_start = dt_head + 1
        dt_end = dt_start + len(plan["rows"]) + 1
        reqs = [
            {"repeatCell": {
                "range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold"}},
            {"repeatCell": {
                "range": {"sheetId": gid, "startRowIndex": dt_head,
                          "endRowIndex": dt_head + 1},
                "cell": {"userEnteredFormat": {
                    "textFormat": {"bold": True, "foregroundColor":
                                   {"red": 1, "green": 1, "blue": 1}},
                    "backgroundColor": {"red": 0.04, "green": 0.14, "blue": 0.27}}},
                "fields": "userEnteredFormat(textFormat,backgroundColor)"}},
            {"repeatCell": {
                "range": {"sheetId": gid, "startRowIndex": ov_start, "endRowIndex": ov_end,
                          "startColumnIndex": 1, "endColumnIndex": 2},
                "cell": {"userEnteredFormat": {"backgroundColor":
                                               {"red": 1, "green": 0.98, "blue": 0.85}}},
                "fields": "userEnteredFormat.backgroundColor"}},
            {"repeatCell": {
                "range": {"sheetId": gid, "startRowIndex": dt_start, "endRowIndex": dt_end,
                          "startColumnIndex": 1, "endColumnIndex": 4},
                "cell": {"userEnteredFormat": {"backgroundColor":
                                               {"red": 1, "green": 0.98, "blue": 0.85}}},
                "fields": "userEnteredFormat.backgroundColor"}},
            {"updateDimensionProperties": {
                "range": {"sheetId": gid, "dimension": "COLUMNS",
                          "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 210}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {
                "range": {"sheetId": gid, "dimension": "COLUMNS",
                          "startIndex": 4, "endIndex": 5},
                "properties": {"pixelSize": 300}, "fields": "pixelSize"}},
        ]
        svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": reqs}).execute()
        print(f"  作成: {title}")
    print(f"{chr(10)}  https://docs.google.com/spreadsheets/d/{sid}/edit")
    print("  黄色いセルを埋めたら python scripts/intake_to_sheet.py --pull で取り込みます")
    return 0


def pull():
    """書かれた内容を読み、data_intake と同じ検査を通して公開する"""
    sid = _sheet_id()
    if not sid:
        print("  SPREADSHEET_ID がありません")
        return 1
    svc = _svc()
    import data_intake as DI
    made = 0
    for title, plan in PLANS.items():
        try:
            got = svc.spreadsheets().values().get(
                spreadsheetId=sid, range=f"'{title}'!A1:I60").execute().get("values", [])
        except Exception as e:
            print(f"  {title}: 読めません（{str(e)[:50]}）")
            continue
        ov, rows, mode = {}, [], ""
        for r in got:
            a = (r[0] if r else "").strip()
            if a.startswith("■ 概要"):
                mode = "ov"; continue
            if a.startswith("■ データ"):
                mode = "dt"; continue
            if a.startswith("■"):
                mode = ""; continue
            if mode == "ov" and a:
                ov[a] = (r[1] if len(r) > 1 else "").strip()
            elif mode == "dt" and a and a != "項目":
                rows.append([(r[i] if len(r) > i else "").strip()
                             for i in range(len(HEAD))])
        vals = [x for x in rows if x[1]]
        if not vals:
            print(f"  {title}: まだ数字が入っていません")
            continue
        ds = _to_dataset(ov, vals)
        ng = _check(ds)
        if ng:
            print(f"  {title}: 公開しません → {ng}")
            continue
        out = ROOT / "data" / "datasets" / f"{ds['slug']}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(ds, ensure_ascii=False, indent=1),
                       encoding="utf-8", newline="\n")
        print(f"  {title}: data/datasets/{ds['slug']}.json に書きました（{len(vals)}行）")
        made += 1
    if made:
        import subprocess
        subprocess.run([sys.executable, "scripts/data_intake.py", "--rebuild"],
                       cwd=ROOT, check=False)
    print(f"{chr(10)}  公開したデータ: {made}件")
    return 0


def _to_dataset(ov, rows):
    from datetime import date
    def num(x):
        try:
            return float(str(x).replace(",", ""))
        except Exception:
            return None
    today = str(date.today())
    return {
        "slug": ov.get("slug", ""), "title": ov.get("題名", ""),
        "description": ov.get("説明", ""),
        "n": int(num(ov.get("母数（件数）")) or 0),
        "n_unit": ov.get("母数の単位", "件"),
        "period": f"{ov.get('対象期間（開始）', '')}〜{ov.get('対象期間（終了）', '')}",
        "start": ov.get("対象期間（開始）", ""), "end": ov.get("対象期間（終了）", ""),
        "method": ov.get("集計方法・出典", ""), "unit": ov.get("値の単位", ""),
        "categories": [c.strip() for c in ov.get("関連カテゴリ", "").split(",") if c.strip()],
        "den_label": ov.get("分母の呼び名", ""), "num_label": ov.get("分子の呼び名", ""),
        "neg_label": ov.get("差の呼び名", ""),
        "published": today, "modified": today, "sentence": "",
        "rows": [{"label": r[0], "value": num(r[1]), "num": num(r[2]), "den": num(r[3]),
                  "window": r[4], "months": num(r[5]), "row_start": r[6],
                  "row_end": r[7], "note": r[8]} for r in rows],
    }


def _check(ds):
    """公開してよいか。data_intake と同じ考え方で止める"""
    if not ds["slug"] or not re.fullmatch(r"[a-z0-9-]+", ds["slug"]):
        return "slug が英小文字・数字・ハイフンではありません"
    if not ds["n"]:
        return "母数（件数）が空です"
    if not ds["start"] or not ds["end"]:
        return "対象期間が空です"
    if not ds["method"]:
        return "集計方法・出典が空です"
    if ds["unit"] in ("%", "％") and ds["n"] < 10:
        return f"母数{ds['n']}で割合は公開できません（実数で書いてください）"
    for r in ds["rows"]:
        if r["value"] is None:
            return f"「{r['label']}」の値が数字ではありません"
        if ds["unit"] in ("%", "％") and (r["num"] is None or r["den"] is None):
            return f"「{r['label']}」に分子・分母がありません（割合には必要です）"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pull", action="store_true", help="書かれた内容を取り込む")
    a = ap.parse_args()
    return pull() if a.pull else push()


if __name__ == "__main__":
    sys.exit(main())
