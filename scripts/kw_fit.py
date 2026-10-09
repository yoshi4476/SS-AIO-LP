# -*- coding: utf-8 -*-
"""その語が、そのサイトの担当領域の語か（記事にしてよいか）を1か所で決める。

**なぜ要るか**: 語を台帳に積む道具が8つあり、それぞれが別の基準で「担当領域」を見ていた。
2026-10-08 に運用者が「Search Console と GA4 を見ると全く関係ない語が選ばれている」と指摘し、調べると:
  - コーポレート: 「記帳 やり方 ゆうちょ」など銀行の通帳の記事が、サイトの表示の約4割（28日・page 次元 1,576/4,097回）。
    「記帳」（帳簿づけ）と通帳の記帳が同じ字で、担当領域語の部分一致だけで通っていた
  - AI集客ラボ: 「歯科医院 閉院 費用」「整骨院 費用 保険」。kw_discover が業種名＋汎用語（費用・やり方・事例）を、
    ai_kw_research が業種名だけを担当領域とみなしていた
  - 補助金: 「建設業 電子申請 閲覧」「個人事業主 開業届 電子申請」。「申請」が補助金の文脈なしで通っていた
積む・選ぶ・書く前・書いた後の入口は、すべてここを通す（基準が分かれていると、どこか1つから漏れる）。

判定（上から順に、最初に当たったもので決める）:
  2 関係ない … 記事にしない。台帳に積まない・次に書く語に選ばない・書いた記事は配信しない
       検索演算子入り（「-一覧」）／見込み客でない（求人・仕事内容…）／他社の製品・サービス名／
       打ち出しから外した語（drop_kw）・除外語（ng_terms）／担当の外の文脈（kw_off）／
       同じ字で別の意味の担当領域語（kw_needs の文脈が無い）／同じ組の別サイトの担当領域語だけを含む
  1 担当領域語なし … 自動で拾う工程（kw_discover・ai_kw_research）は積まない。人や計画が選んだ語は通す
                     （「クリニック 症状 ページ 作り方」のように担当領域語を含まない主力の語がある）
  0 担当領域の語

sites/<id>.json に書くもの（どちらも正規表現の断片。大文字小文字・全角半角は区別しない）:
  kw_needs  {"記帳": "代行|仕訳|…"} … その担当領域語は、この文脈の語と一緒のときだけ担当領域とみなす
  kw_off    ["通帳|ゆうちょ", …]   … これを含む語は、担当領域語があっても担当の外

  python scripts/kw_fit.py "記帳 やり方 ゆうちょ" --site corporate   # 1語を判定（終了コード＝判定）
  python scripts/kw_fit.py --ledger                                  # 台帳の未着手・執筆中で止める語の一覧（読むだけ）
  python scripts/kw_fit.py --ledger --retire                         # 一覧の未着手を「対象外」にする（運用者が確かめてから）
"""
import argparse
import functools
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# 求職者・副業の検索。読者は顧客ではない。「時給」「給料」は入れない（「記帳 代行 相場 時給」は外注の値段を
# 比べる買い手の語）。「パート」は「パートナー」を拾わない
NOT_BUYER = re.compile(r"求人|転職|副業|在宅ワーク|年収|未経験|パート(?!ナー)|バイト|面接|志望動機|仕事内容"
                       r"|一般職|総合職|事務職|経理職|バックオフィス職")   # 職種の検索（2026-10-09 計画に「三菱商事 バックオフィス職 一般職」が入った）
# 他社の製品・サービス名。その名前で検索する人はその製品を使いたい人
RIVALS = ("freee", "フリー会計", "マネーフォワード", "money forward", "弥生", "やよい", "ジョブカン", "楽楽精算",
          "楽楽明細", "奉行", "pca", "jdl", "tkc", "ドットコム", "misoca", "board", "invoice", "バクラク",
          "concur", "コンカー", "sweeep", "tokium", "sansan", "bill one", "kintone", "salesforce", "hubspot",
          "canva", "chatgpt plus", "kinmaq", "キンマク", "レジーナ", "湘南美容", "levo", "かんたん集客",
          "web集客ラボ", "gmo")
# 集客の媒体（ポータル）。AI集客ラボは「ポータル依存から抜ける」を書くので、入口では止めない（計画では外す）
PORTALS = ("ホットペッパー", "エキテン", "ぐるなび", "食べログ", "リクルート", "indeed", "タウンページ", "ミツモア",
           "くらしのマーケット")
OPERATOR = re.compile(r"(^|\s)-\S")
LIVE = ("未着手", "執筆中")


def norm(s):
    """全角半角・大文字小文字をそろえる（「ｍｅｏ」と「meo」、「ＡＴＭ」と「atm」を同じにする）"""
    return unicodedata.normalize("NFKC", str(s or "")).lower()


def flat(s):
    """空白を除いた形。検索語は「補助 金」「経理 代行」のように語の途中で切れて届く"""
    return re.sub(r"\s+", "", norm(s))


@functools.lru_cache(maxsize=None)
def _rules(site):
    """サイトの判定材料。設定の無い社は None（止めない）"""
    try:
        import sites as S
        cfgs = S.load_all()
        group = S.group_of(site) if site in cfgs else []
    except Exception:
        return None
    cfg = cfgs.get(site)
    if not cfg:
        return None
    own = tuple(t for t in (flat(x) for x in cfg.get("owns") or []) if t)
    other = {}
    for sid in group:
        if sid == site or sid not in cfgs:
            continue
        terms = tuple(t for t in (flat(x) for x in cfgs[sid].get("owns") or []) if t and t not in own)
        if terms:
            other[sid] = terms
    rx = lambda xs: re.compile("|".join(f"(?:{norm(x)})" for x in xs if str(x).strip())) if any(
        str(x).strip() for x in xs) else None
    needs = {flat(k): re.compile(norm(v)) for k, v in (cfg.get("kw_needs") or {}).items() if k and v}
    return {"own": own, "other": other, "needs": needs, "off": rx(cfg.get("kw_off") or []),
            "drop": tuple(flat(x) for x in (cfg.get("drop_kw") or []) + (cfg.get("ng_terms") or []) if x)}


_RIVALS = tuple(flat(t) for t in RIVALS)


def judge(kw, site):
    """(判定, 理由)。2=関係ない・1=担当領域語なし・0=担当領域の語"""
    low, fl = norm(kw), flat(kw)
    R = _rules(site)
    if R is None or not fl:
        return 0, ""
    if OPERATOR.search(low):
        return 2, "検索演算子の入った語（検索結果の調べ方そのもの）"
    m = NOT_BUYER.search(fl)
    if m:
        return 2, f"見込み客でない（{m.group(0)}）"
    t = next((t for t in _RIVALS if t in fl), None)
    if t:
        return 2, f"他社の製品・サービス名（{t}）"
    t = next((t for t in R["drop"] if t in fl), None)
    if t:
        return 2, f"打ち出しから外した語・除外語（{t}）"
    m = R["off"].search(low) if R["off"] else None
    if m:
        return 2, f"担当の外の文脈（{m.group(0)}）"
    heads = [h for h in R["own"] if h in fl]
    if heads:
        free = [h for h in heads if not any(k in h for k in R["needs"])]
        if free:
            return 0, ""
        keys = [k for k in R["needs"] if any(k in h for h in heads)]
        if any(R["needs"][k].search(fl) for k in keys):
            return 0, ""
        return 2, f"「{keys[0]}」が別の意味で使われている（その意味を示す語が無い）"
    for sid, terms in R["other"].items():
        t = next((t for t in terms if t in fl), None)
        if t:
            return 2, f"別のサイト（{sid}）の担当領域（{t}）"
    return 1, "担当領域語を含まない"


def ledger_unfit(rows, site=""):
    """台帳の未着手・執筆中のうち、判定2の行。(行, 判定, 理由)"""
    out = []
    for r in rows or []:
        if site and r.get("site") != site:
            continue
        if str(r.get("status", "")).strip() not in LIVE:
            continue
        lv, why = judge(r.get("keyword", ""), r.get("site", ""))
        if lv >= 2:
            out.append((r, lv, why))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("keyword", nargs="?", default="")
    ap.add_argument("--site", default="")
    ap.add_argument("--ledger", action="store_true", help="台帳の未着手・執筆中で止める語の一覧（読むだけ）")
    ap.add_argument("--retire", action="store_true", help="一覧の未着手を「対象外」にする（執筆中は触らない）")
    a = ap.parse_args()
    if not a.ledger:
        lv, why = judge(a.keyword, a.site)
        print(f"■ 担当領域の判定: 「{a.keyword}」（{a.site}）→ {lv}"
              + {0: "（担当領域の語）", 1: f"（{why}）", 2: f"（関係ない: {why}）"}[lv])
        return lv
    import hub_client as HC
    try:
        rows = HC.all_kw(strict=True)
    except Exception as e:
        print(f"KW_FIT_LEDGER=unknown（台帳を読めません: {str(e)[:60]}）")
        return 0
    bad = ledger_unfit(rows, a.site)
    for r, _lv, why in bad:
        print(f"  [{r.get('site')}] {r.get('keyword')}（{r.get('status')}）… {why}")
    print(f"KW_FIT_LEDGER={len(bad)}")
    if a.retire:
        by = {}
        for r, _lv, why in bad:
            if str(r.get("status", "")).strip() == "未着手":
                by.setdefault(r["site"], []).append((r["keyword"], why))
        for site, items in by.items():
            for kw, why in items:
                HC.retire_kw(site, [kw], f"担当領域の外（kw_fit: {why}）")
            print(f"  {site}: {len(items)}件を対象外にしました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
