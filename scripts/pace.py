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

■ 運用者の設定（兆候とは別の理由）
  sites/<id>.json の daily_articles（0〜2）。1日の本数は「兆候の判定」と「設定」の小さい方。
  設定で浮いた枠は、spare_slot が "rewrite_main" の社だけ主力の記事の書き直しに回す（slot()）。
  兆候・手動の対策で止めた枠は書き直しにも回さない。設定で減らした社は一覧で「要対応」にしない
  （2026-10-09 運用者の決定: 補助金は新しい記事を1日1本にし、浮いた1枠で主力の記事を書き直す）

    python scripts/pace.py                 # 測って見るだけ
    python scripts/pace.py --write         # 判定を残す（週次）
    python scripts/pace.py --quota <site>  # 今日の本数（日次の枠が読む）
    python scripts/pace.py --slot <site> <その日の何本目（0始まり）>   # SLOT=write|rewrite|skip（日次の枠が読む）
    python scripts/pace.py --manual <site> "<理由>"   # 手動による対策を受けたときに0本にする
    python scripts/pace.py --manual <site> --clear   # 解除（再審査が通った後）
出す印: PACE_OK=yes|no（兆候・手動の対策で1本でも落としたサイトがあれば no。運用者の設定は数えない）
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
SITES = ROOT / "sites"
SPARE_REWRITE = "rewrite_main"
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


def _site(sid):
    """その社の設定。お客様の社は公開の印（公開の id・本数だけ）に非公開の置き場の設定を重ねたもの（sites.load_all）。
    社の id で聞かれても公開の id で聞かれても同じ設定を返す（非公開のデータが取れない回は公開の印だけ）"""
    d = _json(SITES / f"{sid}.json")
    if d and not d.get("client"):
        return d
    try:
        import sites as S
        full = S.load_all().get(S.resolve(sid))
    except Exception:
        full = None
    return full or d


def _manual():
    """手動による対策の記録 {社: …}。お客様の社の行は非公開のリポジトリ（理由の文に社の事情が入る）"""
    import client_private as CP
    return CP.load_dict("data/pace_manual.json", pub=MANUAL)


def setting(sid):
    """運用者が sites/<id>.json の daily_articles に決めた1日の本数（0〜2）。無い・読めないときは既定の2本"""
    v = _site(sid).get("daily_articles")
    if isinstance(v, bool) or not isinstance(v, int):
        return DEFAULT
    return max(0, min(DEFAULT, v))


def signal_quota(sid):
    """量産の兆候（週次の判定）と手動による対策から決まる本数。手動が最優先。記録が無い・古いときは既定の2本"""
    if (_manual().get(sid) or {}).get("quota") is not None:
        return int(_manual()[sid]["quota"])
    import client_private as CP
    st = CP.load_dict("data/pace_state.json", pub=STATE).get(sid) or {}
    if st.get("date", "") < (date.today() - timedelta(days=STATE_DAYS)).isoformat():
        return DEFAULT
    return int(st.get("quota", DEFAULT))


def quota(sid):
    """日次の枠が読む本数＝兆候の判定と運用者の設定の小さい方（本数の点検・救済・在庫の1か月分も同じ数を使う）"""
    return min(signal_quota(sid), setting(sid))


def slot(sid, rank):
    """その日の rank 本目（0始まり）の枠で何をするか。(write|rewrite|skip, 理由)。
    運用者の設定で浮いた枠だけを書き直しに回す。兆候・手動の対策で止めた枠は書き直さない
    （量産と見られている週に、既存記事の書き換えまで増やさない）"""
    sig, mine = signal_quota(sid), setting(sid)
    if rank < min(sig, mine):
        return "write", f"1日{min(sig, mine)}本のうち{rank + 1}本目"
    if rank >= sig:
        why = "手動による対策" if (_manual().get(sid) or {}).get("quota") is not None else "量産の兆候"
        return "skip", f"今週1日{sig}本（{why}。python scripts/pace.py で理由を確認）"
    if _site(sid).get("spare_slot") == SPARE_REWRITE:
        return "rewrite", f"新しい記事は1日{mine}本（運用者の設定）。浮いた枠で主力の記事を書き直す"
    return "skip", f"新しい記事は1日{mine}本（運用者の設定）"


def report_line(sid, name, r):
    """一覧の1行と「要対応」か。要対応は兆候・手動の対策で落とした社だけ（運用者の設定は理由が別）"""
    mine = setting(sid)
    flagged = r["quota"] < DEFAULT
    tail = "（運用者の設定）" if mine < DEFAULT and mine <= r["quota"] else ""
    return (f"  {'要対応:' if flagged else '○'} {name} — 1日{min(r['quota'], mine)}本{tail}（新しい記事{r['new']}本・"
            f"{r['how']} 未登録{r['not_indexed_rate']:.0%}・重複{r['duplicates']}・同型{r['pairs']}組・"
            f"表示{r['imp'][0]:,}→{r['imp'][1]:,}）"), flagged


def _sitemap(domain):
    """URL検査には配信先の正規の形（末尾スラッシュの有無）で渡す。違う形だと「リダイレクト」としか出ない"""
    try:
        with urllib.request.urlopen(urllib.request.Request(
                f"https://{domain}/sitemap.xml", headers={"User-Agent": "Mozilla/5.0"}), timeout=25) as r:
            urls = re.findall(r"<loc>(.*?)</loc>", r.read().decode("utf-8", "ignore"))
    except Exception:
        return {}
    return {urlparse(u).path.rstrip("/") + "/": u for u in urls}


# URL検査の結果の控え（同じ週次の中で2回検査しないため）。週次は findings（表示）と pace --write（保存）で
# 2回 measure を呼び、3サイト120本・1本約6秒の検査を2回繰り返していた（2026-10-05: 774秒＋約750秒）。
# 控えは一時フォルダに置く（お客様の URL を含むので public のリポジトリに置かない）。失敗した検査は控えない
INSPECT_CACHE = "pace_inspect_cache.json"
INSPECT_TTL = 6 * 3600
# 同時に投げる本数。URL検査の上限は1プロパティ毎分600回・1日2,000回で、6本同時でも毎分60回ほど
INSPECT_WORKERS = 6


def _inspect_cache_path():
    import tempfile
    return Path(tempfile.gettempdir()) / INSPECT_CACHE


def _inspect_cache():
    try:
        return json.loads(_inspect_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def coverage(cfg, paths, now=None):
    """URL検査で索引の状態を見る（英語の状態名で判定する。日本語は表記が変わりうる）。
    同じ URL を6時間以内に検査し直さない（控え）。検査は INSPECT_WORKERS 本ずつ同時に投げ、結果は paths の順で返す"""
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    import index_status as IX
    sc = IX.client()       # 鍵が無い・読めないときは今までどおりここで止まる（呼び出し側が「測れません」にする）
    site_url = f"https://{cfg['domain']}/"
    sm = _sitemap(cfg["domain"])
    urls = {p: sm.get(p) or f"https://{cfg['domain']}{p}" for p in paths[:INSPECT_MAX]}
    now = time.time() if now is None else now
    cache = _inspect_cache()
    out = {}
    for p, url in urls.items():
        hit = cache.get(url)
        if isinstance(hit, list) and len(hit) == 2 and now - float(hit[0]) < INSPECT_TTL:
            out[p] = hit[1]
    todo = [p for p in urls if p not in out]
    local = threading.local()

    def one(p):
        # 検査の窓口はスレッドごとに作る（httplib2 は同時に使えない）
        c = getattr(local, "sc", None)
        if c is None:
            c = local.sc = IX.client()
        try:
            r = c.urlInspection().index().inspect(
                body={"inspectionUrl": urls[p], "siteUrl": site_url, "languageCode": "en-US"}).execute()
            return p, r.get("inspectionResult", {}).get("indexStatusResult", {}).get("coverageState", "")
        except Exception as e:
            return p, f"ERROR {str(e)[:40]}"

    if todo:
        with ThreadPoolExecutor(max_workers=min(INSPECT_WORKERS, len(todo))) as ex:
            for p, v in ex.map(one, todo):
                out[p] = v
                if not v.startswith("ERROR"):
                    cache[urls[p]] = [now, v]
        try:
            _inspect_cache_path().write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return {p: out[p] for p in urls}


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
    ap.add_argument("--slot", nargs=2, metavar=("SITE", "RANK"))
    ap.add_argument("--manual", nargs="+", metavar=("SITE", "REASON"))
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--no-inspect", action="store_true", help="URL検査を使わない（試すとき）")
    a = ap.parse_args()
    if a.quota:
        print(quota(a.quota))           # 日次の枠（CI の select）が呼ぶ。標準ライブラリだけで動く
        return 0
    if a.slot:
        mode, why = slot(a.slot[0], int(a.slot[1]))     # 同じく select が pip の前に呼ぶ
        print(f"SLOT={mode}\nSLOT_WHY={why}")
        return 0
    if a.manual:
        m = _manual()
        sid = a.manual[0]
        if a.clear:
            m.pop(sid, None)
            print(f"{sid}: 手動の停止を解除しました（次の週次の判定から通常に戻ります）")
        else:
            m[sid] = {"quota": 0, "reason": " ".join(a.manual[1:]) or "手動による対策", "at": date.today().isoformat()}
            print(f"{sid}: 新しい記事を止めました（手動による対策）。解除は --manual {sid} --clear")
        import client_private as CP
        CP.save_dict("data/pace_manual.json", m, CP.site_key,
                     dump=lambda o: json.dumps(o, ensure_ascii=False, indent=1) + "\n", pub=MANUAL)
        return 0
    import content_yield as CY
    import sites as S
    end = date.today() - timedelta(days=3)
    arts = [x for x in (CY._fm(p) for p in (ROOT / "articles").glob("*.md")) if x and x["score"] >= 90]
    manual = _manual()
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
            r["quota"] = min(r["quota"], int(manual[sid].get("quota") or 0))
            r["signals"].insert(0, f"手動による対策: {manual[sid].get('reason')}（{manual[sid].get('at')}）")
        ran += 1
        # 残すのは兆候の判定だけ（運用者の設定は sites/<id>.json にあり、quota() が読むときに重ねる）
        state[sid] = r
        line, flagged = report_line(sid, cfg.get("name", sid), r)
        print(line)
        if r["states"]:
            print("      索引の内訳: " + "／".join(f"{k} {v}" for k, v in sorted(r["states"].items(), key=lambda x: -x[1])))
        for s in r["signals"]:
            print(f"      兆候: {s}")
        low += flagged
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
