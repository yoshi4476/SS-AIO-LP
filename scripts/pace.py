# -*- coding: utf-8 -*-
"""「量産と見られている」かを Google の公式の定義にもとづいて毎週測り、1サイトの1日の本数（既定2本）を自動で決める

■ 定義（一次情報・2026-09-29 に確認）
  Google のスパムポリシー「大量生成されたコンテンツの不正使用（Scaled content abuse）」
  https://developers.google.com/search/docs/essentials/spam-policies
    「検索順位の操作を主な目的として、ユーザーの役に立たないページを大量に生成すること。
     作り方を問わず、ほとんど価値のないオリジナルでないコンテンツを大量に作ることに当たる」
    例: 生成AIなどで価値を加えずに多数のページを生成する／他ページの内容をつなぎ合わせる
       ／大量生成を隠すために複数サイトを作る
    検出: 自動のシステムと、必要に応じて人の確認（手動による対策）。
    通知: 手動による対策は Search Console の「手動による対策」レポートとメッセージで通知される。
  生成AIのコンテンツ https://developers.google.com/search/docs/fundamentals/using-gen-ai-content
    「生成AIで価値を加えずに多数のページを生成すると、大量生成の不正使用のポリシーに違反することがある」

■ 何で判定するか
  確定: 手動による対策（Scaled content abuse）が付いたとき。**Search Console API には手動による対策を
        読む手段が無い**（API は検索実績・sitemap・サイト・URL検査のみ）。通知を受けた人が
        data/pace_manual.json に1行書くと、その日から0本にする（下の --manual）。
  兆候（自動のシステムの判定が表に出たもの。URL検査API とGSCの実績で測る）:
    1. 新しい記事が索引されない … 公開14〜45日の記事を URL検査で見て、
       「Crawled - currently not indexed」「Discovered - currently not indexed」の割合が50%超
       （Google が見たうえで登録しない＝価値が低いと判断された状態が表に出る）
    2. 重複と判定された … 同じ記事群で「Duplicate …」（Google が別のページを正規と判断）が2本以上
       （つなぎ合わせ・同じ内容の量産に当たる）
    3. 同型の記事 … 直近30日の記事どうしで本文の重なり25%以上が3組以上
       （「価値を加えずに多数のページを生成」の自社側の指紋。scaled_guard と同じ測り方）
    4. サイト全体の表示の急落 … 直近28日の表示がその前の28日より20%以上少ない
       （季節や他の要因でも起きるので、単独では強く扱わない）
  URL検査が使えないときは、1 の代わりに「28日間の表示が0の割合」を使う（代替と明記する）。

■ 本数
  兆候0 → 2本／兆候1〜2 → 1本／兆候3以上・未登録70%超・手動による対策 → 0本
  0本でも統合・書き直し・内部リンクの週次は回る。判定は data/pace_state.json（14日で失効）。
  次の週に兆候が消えれば自動で2本に戻る。

    python scripts/pace.py                 # 測って見るだけ
    python scripts/pace.py --write         # 判定を残す（週次）
    python scripts/pace.py --quota <site>  # 今日の本数（日次の枠が読む）
    python scripts/pace.py --manual <site> "<理由>"   # 手動による対策を受けたときに0本にする
    python scripts/pace.py --manual <site> --clear   # 解除（再審査が通った後）
出す印: PACE_OK=yes|no（1本でも落としたサイトがあれば no）
"""
import argparse
import json
import re
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STATE = ROOT / "data" / "pace_state.json"
MANUAL = ROOT / "data" / "pace_manual.json"
DEFAULT, STATE_DAYS = 2, 14
NOTIDX_MAX, NOTIDX_SEVERE, MIN_NEW, INSPECT_MAX = 0.50, 0.70, 6, 40
DUP_MAX = 2
SIM, PAIRS_MAX = 0.25, 3
DROP = 0.20
NOT_INDEXED = ("Crawled - currently not indexed", "Discovered - currently not indexed")


def _json(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def quota(sid):
    """日次の枠が読む本数。手動による対策が最優先。記録が無い・古いときは既定の2本"""
    if (_json(MANUAL).get(sid) or {}).get("quota") is not None:
        return int(_json(MANUAL)[sid]["quota"])
    import client_private as CP
    st = CP.load_dict("data/pace_state.json", pub=STATE).get(sid) or {}
    if st.get("date", "") < (date.today() - timedelta(days=STATE_DAYS)).isoformat():
        return DEFAULT
    return int(st.get("quota", DEFAULT))


def _sitemap(domain):
    """URL検査には配信先の正規の形（末尾スラッシュの有無）で渡す。違う形だと「リダイレクト」としか出ない"""
    try:
        with urllib.request.urlopen(urllib.request.Request(
                f"https://{domain}/sitemap.xml", headers={"User-Agent": "Mozilla/5.0"}), timeout=25) as r:
            urls = re.findall(r"<loc>(.*?)</loc>", r.read().decode("utf-8", "ignore"))
    except Exception:
        return {}
    return {urlparse(u).path.rstrip("/") + "/": u for u in urls}


def coverage(cfg, paths):
    """URL検査で索引の状態を見る（英語の状態名で判定する。日本語は表記が変わりうる）"""
    import index_status as IX
    sc = IX.client()
    site_url = f"https://{cfg['domain']}/"
    sm = _sitemap(cfg["domain"])
    out = {}
    for p in paths[:INSPECT_MAX]:
        url = sm.get(p) or f"https://{cfg['domain']}{p}"
        try:
            r = sc.urlInspection().index().inspect(
                body={"inspectionUrl": url, "siteUrl": site_url, "languageCode": "en-US"}).execute()
            out[p] = r.get("inspectionResult", {}).get("indexStatusResult", {}).get("coverageState", "")
        except Exception as e:
            out[p] = f"ERROR {str(e)[:40]}"
    return out


def spread(items, k):
    """公開日の順に並べ、端から端まで等間隔に k 本選ぶ。
    名前順の先頭だけを見ると公開時期が偏り（2026-10-05: コーポレートは80本中40本）、
    未登録が固まった時期を見落とすか、そこだけを見る"""
    items = sorted(items, key=lambda a: (a["date"], a["slug"]))
    if len(items) <= k:
        return items
    return [items[round(i * (len(items) - 1) / (k - 1))] for i in range(k)]


def measure(sid, cfg, arts, end, use_inspect=True):
    import content_yield as CY
    import sites as S
    sig = []
    lo, hi = (end - timedelta(days=45)).isoformat(), (end - timedelta(days=14)).isoformat()
    new = [a for a in arts if a["date"] and lo <= a["date"] <= hi]
    paths = [CY._path(S.article_url(cfg, a)) for a in new]
    cov, how = {}, "URL検査"
    if use_inspect and len(new) >= MIN_NEW:
        cov = coverage(cfg, [CY._path(S.article_url(cfg, a)) for a in spread(new, INSPECT_MAX)])
        if sum(1 for v in cov.values() if v.startswith("ERROR")) > len(cov) / 2:
            cov, how = {}, "代替（表示0の割合）"
    cur = CY.pages(cfg, end - timedelta(days=27), end)
    prev = CY.pages(cfg, end - timedelta(days=55), end - timedelta(days=28))
    # 1. 索引されない
    if cov:
        judged = [v for v in cov.values() if not v.startswith("ERROR")]
        notidx = [v for v in judged if v in NOT_INDEXED]
        dup = [v for v in judged if v.startswith("Duplicate")]
        rate = len(notidx) / len(judged) if judged else 0.0
        n_judged = len(judged)
    else:
        how = "代替（表示0の割合）" if len(new) >= MIN_NEW else "判定なし（新しい記事が少ない）"
        zero = [p for p in paths if cur.get(p, (0, 0))[0] == 0]
        rate = len(zero) / len(new) if len(new) >= MIN_NEW else 0.0
        notidx, dup, n_judged = zero, [], len(new)
    if n_judged >= MIN_NEW and rate > NOTIDX_MAX:
        sig.append(f"新しい記事{n_judged}本のうち{len(notidx)}本（{rate:.0%}）が索引されていない（{how}）")
    # 2. 重複と判定
    if len(dup) >= DUP_MAX:
        sig.append(f"新しい記事{len(dup)}本が Google に重複と判定された（別のページを正規と判断）")
    # 3. 同型の記事
    import scaled_guard as SG
    corp = SG.corpus()
    recent = [a["slug"] for a in arts if a["date"] >= (end - timedelta(days=30)).isoformat() and a["slug"] in corp]
    pairs = sum(1 for i, x in enumerate(recent) for y in recent[i + 1:]
                if SG.jaccard(corp[x]["grams"], corp[y]["grams"]) >= SIM)
    if pairs >= PAIRS_MAX:
        sig.append(f"直近30日の記事どうしで本文の重なり{SIM:.0%}以上が{pairs}組（価値を加えない量産の指紋）")
    # 4. 表示の急落
    ic, ip = sum(v[0] for v in cur.values()), sum(v[0] for v in prev.values())
    if ip >= 300 and ic < ip * (1 - DROP):
        sig.append(f"サイト全体の表示が{ip:,}→{ic:,}回（{ic / ip - 1:+.0%}）")
    q = DEFAULT
    if sig:
        q = 1
    if len(sig) >= 3 or (n_judged >= MIN_NEW and rate > NOTIDX_SEVERE and cov):
        q = 0
    states = {}
    for v in (cov or {}).values():
        states[v] = states.get(v, 0) + 1
    return {"quota": q, "signals": sig, "date": date.today().isoformat(), "how": how,
            "new": len(new), "judged": n_judged, "not_indexed_rate": round(rate, 2),
            "duplicates": len(dup), "pairs": pairs, "imp": [ip, ic], "states": states}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--quota", metavar="SITE")
    ap.add_argument("--manual", nargs="+", metavar=("SITE", "REASON"))
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--no-inspect", action="store_true", help="URL検査を使わない（試すとき）")
    a = ap.parse_args()
    if a.quota:
        print(quota(a.quota))           # 日次の枠（CI の select）が呼ぶ。標準ライブラリだけで動く
        return 0
    if a.manual:
        m = _json(MANUAL)
        sid = a.manual[0]
        if a.clear:
            m.pop(sid, None)
            print(f"{sid}: 手動の停止を解除しました（次の週次の判定から通常に戻ります）")
        else:
            m[sid] = {"quota": 0, "reason": " ".join(a.manual[1:]) or "手動による対策", "at": date.today().isoformat()}
            print(f"{sid}: 新しい記事を止めました（手動による対策）。解除は --manual {sid} --clear")
        MANUAL.write_text(json.dumps(m, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return 0
    import content_yield as CY
    import sites as S
    end = date.today() - timedelta(days=3)
    arts = [x for x in (CY._fm(p) for p in (ROOT / "articles").glob("*.md")) if x and x["score"] >= 90]
    manual = _json(MANUAL)
    state, ran, low = {}, 0, 0
    print("■ 量産と見られている兆候（Google の大量生成の不正使用の定義にもとづく）と、1日の本数\n")
    for sid, cfg in S.load_all().items():
        own = [x for x in arts if S.find_category_owner(x["category"]) == sid]
        if not own:
            continue
        try:
            r = measure(sid, cfg, own, end, use_inspect=not a.no_inspect)
        except Exception as e:
            print(f"  {cfg.get('name', sid)}: 測れません（{str(e)[:60]}）→ 既定の{DEFAULT}本のまま")
            continue
        if sid in manual:
            r["quota"] = 0
            r["signals"].insert(0, f"手動による対策: {manual[sid].get('reason')}（{manual[sid].get('at')}）")
        ran += 1
        state[sid] = r
        mark = "○" if r["quota"] == DEFAULT else "要対応:"
        print(f"  {mark} {cfg.get('name', sid)} — 1日{r['quota']}本（新しい記事{r['new']}本・{r['how']}"
              f" 未登録{r['not_indexed_rate']:.0%}・重複{r['duplicates']}・同型{r['pairs']}組・表示{r['imp'][0]:,}→{r['imp'][1]:,}）")
        if r["states"]:
            print("      索引の内訳: " + "／".join(f"{k} {v}" for k, v in sorted(r["states"].items(), key=lambda x: -x[1])))
        for s in r["signals"]:
            print(f"      兆候: {s}")
        low += r["quota"] < DEFAULT
    if not ran:
        print("  どのサイトも測れませんでした")
        return 1
    if a.write:
        # お客様の社の兆候（URL検査の内訳・表示の推移）は public に置かない（client_private の置き場へ）
        import client_private as CP
        CP.save_dict("data/pace_state.json", state, CP.site_key, pub=STATE)
    print(f"\nPACE_OK={'no' if low else 'yes'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
