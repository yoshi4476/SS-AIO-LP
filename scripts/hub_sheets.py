# -*- coding: utf-8 -*-
"""管制塔（スプレッドシート）を Sheets API で直接読み書きする（GAS を経由しない）。

**なぜ要るか**: これまで管制塔へは Apps Script のWebアプリ経由でしか触れず、
1回の呼び出しで取れる範囲と実行時間に上限があった（302 の先で一時的な 404/5xx も出る）。
サービスアカウントにシートを共有すれば、Sheets API で直接読み書きできる。
GAS 側の関数（nextKw_ / claimKw_ / addKw_ …）と**同じ列・同じ判定**で動かす。

使い方（hub_client が自動で選ぶ。直接が使えなければ従来の GAS に落ちる）:
  HUB_DIRECT=1 を環境変数か .env に置くと直接を優先する
  python scripts/hub_sheets.py --check     # 読めるか・書けるか（書き込みは試さない）
"""
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
SA = ROOT / "indexing-service-account.json"
SCOPE = ["https://www.googleapis.com/auth/spreadsheets"]
KW_COLS = 11        # KW台帳: サイト, キーワード, 状態, 優先度, 想定カテゴリ, 狙い, 登録日, 着手日, 公開日, 記事URL, 備考
_SV = None


def sheet_id():
    import hub_client as HC
    sid = HC._clean(HC.ENV.get("HUB_SHEET_ID", ""))
    if not sid:
        try:
            import hub_check
            sid = hub_check.HUB_SHEET
        except Exception:
            sid = ""
    return sid


def available():
    import hub_client as HC
    return SA.is_file() and bool(sheet_id()) and HC._clean(HC.ENV.get("HUB_DIRECT", "")) in ("1", "true", "yes")


def _svc():
    global _SV
    if _SV is None:
        import gcreds
        from googleapiclient.discovery import build
        _SV = build("sheets", "v4", credentials=gcreds.load(SA, SCOPE), cache_discovery=False).spreadsheets()
    return _SV


def _now():
    # GAS は new Date() をシートの時刻（JST）で書く。CI は UTC なので、素の now() だと9時間ずれる
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")


def norm_kw(s):
    """GAS の normKw_ と同じ: 全角英数を半角に、空白・記号を落として小文字に。
    落とす記号が1つでも違うと、GAS なら弾く重複（「〜とは？」と「〜とは」）を直接接続では通してしまう"""
    s = str(s or "")
    s = "".join(chr(ord(c) - 0xFEE0) if "Ａ" <= c <= "Ｚ" or "ａ" <= c <= "ｚ" or "０" <= c <= "９" else c for c in s)
    return re.sub(r"[\s　・|｜:：\-—?？!！。、,.／/（）()【】\[\]]", "", s).lower()


def rows(tab, cols):
    v = _svc().values().get(spreadsheetId=sheet_id(), range=f"'{tab}'!A2:{chr(64 + cols)}",
                            valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    return [r + [""] * (cols - len(r)) for r in v]


def _set(tab, row, col, value):
    _svc().values().update(spreadsheetId=sheet_id(), range=f"'{tab}'!{chr(64 + col)}{row}",
                           valueInputOption="USER_ENTERED", body={"values": [[value]]}).execute()


def _append(tab, values):
    _svc().values().append(spreadsheetId=sheet_id(), range=f"'{tab}'!A1", valueInputOption="USER_ENTERED",
                           insertDataOption="INSERT_ROWS", body={"values": [values]}).execute()


# ── KW台帳 ────────────────────────────────────────────
def all_kw():
    return [{"site": r[0], "keyword": r[1], "status": str(r[2]).strip(), "priority": r[3] or "B",
             "category": r[4], "aim": r[5], "url": r[9]} for r in rows("KW台帳", KW_COLS) if r[1]]


def kw_status(site=""):
    rs = [r for r in all_kw() if not site or r["site"] == site]
    c = lambda s: sum(1 for r in rs if r["status"] == s)
    return {"ok": True, "site": site or "all", "total": len(rs), "todo": c("未着手"), "doing": c("執筆中"), "done": c("公開済み")}


def _conflicts(site, keyword, rs, self_i):
    """GAS の kwConflict_ と同じ: 生きている行のうち、完全一致か前方の包含。(同じサイト, 他サイト)"""
    n = norm_kw(keyword)
    same, cross = [], []
    for j, r in enumerate(rs):
        if j == self_i or str(r[2]).strip() in ("対象外", "取り下げ"):
            continue
        m = norm_kw(r[1])
        if not m or not (m == n or m.startswith(n) or n.startswith(m)):
            continue
        rec = {"site": r[0], "keyword": r[1], "status": str(r[2]).strip(), "url": r[9]}
        (same if str(r[0]) == str(site) else cross).append(rec)
    return same, cross


def next_kw(site):
    rs = rows("KW台帳", KW_COLS)
    cands = sorted([(i, r) for i, r in enumerate(rs)
                    if r[1] and (not site or str(r[0]) == site) and str(r[2]).strip() == "未着手"],
                   key=lambda x: str(x[1][3] or "B"))
    if not cands:
        return {"ok": True, "keyword": None, "remaining": 0, "need_replenish": True}
    blocked = []
    for i, c in cands:
        same, cross = _conflicts(c[0], c[1], rs, i)
        if same:                                    # 同じサイトに生きている同じ語（包含を含む）がある
            blocked.append({"keyword": c[1], "why": "着手禁止（同じサイトに同じ語がある）"})
            continue
        return {"ok": True, "keyword": c[1], "category": c[4], "aim": c[5], "site": c[0],
                "remaining": len(cands), "need_replenish": len(cands) <= 5,
                "cross_site_warning": cross, "skipped_conflict": blocked}
    return {"ok": True, "keyword": None, "remaining": len(cands), "need_replenish": True, "skipped_conflict": blocked,
            "note": "未着手のKWはすべて既存記事と食い合います。台帳の補充が必要です"}


def claim_kw(site, keyword):
    rs = rows("KW台帳", KW_COLS)
    n = norm_kw(keyword)
    for i, r in enumerate(rs):
        if str(r[0]) != site or norm_kw(r[1]) != n:
            continue
        dup = [{"site": x[0], "keyword": x[1], "status": str(x[2]).strip(), "url": x[9]}
               for j, x in enumerate(rs) if j != i and norm_kw(x[1]) == n and str(x[2]).strip() not in ("対象外", "取り下げ")]
        if dup:
            return {"ok": False, "error": "同じ語が台帳にすでにあります。書くと順位が割れます", "conflicts": dup}
        _set("KW台帳", i + 2, 3, "執筆中")
        _set("KW台帳", i + 2, 8, _now())
        return {"ok": True}
    return {"ok": False, "error": f"KWが見つかりません: {keyword}"}


def unclaim_kw(site, keywords):
    rs, n = rows("KW台帳", KW_COLS), 0
    want = {norm_kw(k) for k in keywords or []}
    for i, r in enumerate(rs):
        if str(r[0]) == site and norm_kw(r[1]) in want and str(r[2]).strip() == "執筆中":
            _set("KW台帳", i + 2, 3, "未着手")
            _set("KW台帳", i + 2, 8, "")
            n += 1
    return {"ok": True, "unclaimed": n}


def retire_kw(site, keywords, reason="", force=False):
    rs, n = rows("KW台帳", KW_COLS), 0
    want = set(keywords or [])
    for i, r in enumerate(rs):
        if str(r[0]) != site or str(r[1]) not in want:
            continue
        if str(r[2]).strip() == "公開済み":
            if not force:
                continue
            _set("KW台帳", i + 2, 3, "取り下げ")
            _set("KW台帳", i + 2, 11, reason or "サイトから取り下げ")
        else:
            _set("KW台帳", i + 2, 3, "対象外")
            _set("KW台帳", i + 2, 11, reason or "担当領域が異なるため取り下げ")
        n += 1
    return {"ok": True, "retired": n}


def add_kw(site, keywords):
    """表記ゆれを吸収して重複を弾く（他サイトの生きている語も弾く）"""
    live = {norm_kw(r["keyword"]) for r in all_kw() if r["status"] not in ("対象外", "取り下げ")}
    added = []
    for k0 in keywords or []:
        # GAS と同じく、語だけの文字列と {keyword, priority, category, aim, note} の両方を受ける
        # （kw_plan・seed_hub は優先度つきの辞書で渡す）
        kw = k0 if isinstance(k0, dict) else {"keyword": k0}
        k = norm_kw(kw.get("keyword"))
        if not k or k in live:
            continue
        _append("KW台帳", [site, kw["keyword"], "未着手", kw.get("priority") or "B", kw.get("category") or "",
                          kw.get("aim") or "", _now(), "", "", "", kw.get("note") or "自動補充"])
        live.add(k)
        added.append(kw["keyword"])
    return {"ok": True, "added": len(added), "keywords": added}


# ── ログ ─────────────────────────────────────────────
def _site_label(site):
    try:
        import sites as S
        return S.load(site)["name"]
    except Exception:
        return site


def publish_log(**b):
    _append("記事作成ログ", [_now(), _site_label(b.get("site", "")), b.get("title", ""), b.get("keyword", ""),
                          b.get("category", ""), b.get("score", ""), b.get("chars", ""), b.get("url", ""), b.get("note", "")])
    if b.get("keyword"):
        # 完全一致だと「aio 診断」と「aio診断」の表記ゆれで台帳が公開済みにならない（GAS の publishLog_ と同じく正規化）
        # 完全一致の行を優先し、無ければ生きている（対象外・取り下げでない）行に当てる
        want = norm_kw(b["keyword"])
        hit = -1
        for i, r in enumerate(rows("KW台帳", KW_COLS)):
            if str(r[0]) != b.get("site") or norm_kw(r[1]) != want:
                continue
            if str(r[1]) == b["keyword"]:
                hit = i
                break
            if hit < 0 and str(r[2]).strip() not in ("対象外", "取り下げ"):
                hit = i
        if hit >= 0:
            _set("KW台帳", hit + 2, 3, "公開済み")
            _set("KW台帳", hit + 2, 9, _now())
            _set("KW台帳", hit + 2, 10, b.get("url", ""))
    return {"ok": True}


def error_log(site, phase, message, fix="", status="未対応"):
    msg = str(message or "").strip()
    for r in rows("エラーログ", 6):
        if str(r[3]).strip() == msg and str(r[2]).strip() == str(phase or "") and str(r[5]).strip() == "未対応":
            return {"ok": True, "skipped": "same_open"}
    _append("エラーログ", [_now(), _site_label(site) if site else "", phase or "", msg, fix or "", status])
    return {"ok": True}


def rewrite_log(site, article, reason, summary, pos_before="", pos_after="", effect=""):
    # サイト列は ID のまま（GAS の rewriteLog_ と同じ）。rewrite_effect は ID で行を探すため、
    # 表示名で書くと後順位・効果が埋まらない
    _append("リライトログ", [_now(), site, article, reason, summary, pos_before, pos_after, effect])
    return {"ok": True}


def check():
    import hub_client as HC
    print(f"  サービスアカウント: {'あり' if SA.is_file() else '無し'} / シートID: {'あり' if sheet_id() else '無し'}"
          f" / HUB_DIRECT: {HC._clean(HC.ENV.get('HUB_DIRECT', '')) or '未設定'}")
    try:
        st = kw_status()
        print(f"  KW台帳: 全{st['total']} / 未着手{st['todo']} / 執筆中{st['doing']} / 公開済み{st['done']}（直接読めます）")
        print("HUB_SHEETS_OK=yes")
    except Exception as e:
        print(f"  直接読めません（{str(e)[:80]}）。シートをサービスアカウントに「編集者」で共有してください")
        print("HUB_SHEETS_OK=no")
    return 0


if __name__ == "__main__":
    sys.exit(check() if "--check" in sys.argv else 0)
