# -*- coding: utf-8 -*-
"""KW候補を実データから発掘する（有料ツール不要）

使い方:
    python scripts/kw_discover.py --site corporate           # 候補を表示するだけ
    python scripts/kw_discover.py --site corporate --append  # 計画ファイルと管制塔へ追加

--site を省略すると ai-lab を対象にする。採用条件は sites/*.json の owns（担当領域語）と
kw_seeds（業種×課題の起点）から自動生成するため、補充した時点で領域外のKWは混ざらない。

2つの無料の実データソースを使う:
  1. Google Search Console API — 自サイトが実際に表示されたクエリ。
     「表示はされているが専用記事がない」= 需要が実証済みの最優先KW。
  2. Googleサジェスト — 実際の検索行動から生成される候補。
     サジェストに出る = 一定の検索需要がある証拠（推測ではない）。

既存記事と重複するKWは cannibal_check の類似度で除外するため、
補充されたKWをそのまま書いてもカニバリにならない。
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cannibal_check import dice, load_articles  # noqa: E402
from kw_status import is_written, plan_keywords, written_corpus  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DUP_THRESHOLD = 0.50
MAX_APPEND = 30
UA = {"User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"}
PER_SEED = 4  # 1つの起点から採用する上限（特定業種に偏らせない）

# どのサイトでも意味を持つ汎用語。サジェストの雑音（ブランド名・無関係語）を落とすために使う
GENERIC_TERMS = ("対策", "方法", "やり方", "手順", "費用", "相場", "事例", "選び方",
                 "比較", "とは", "ポイント", "コツ", "注意点", "チェック", "改善")
# 検索者が見込み客でないKW（ブランド固有名・調べ物）はどのサイトでも除外する
BASE_NG = ("年収", "給料", "ceo", "セオリー", "湘南", "とは何", "英語", "意味", "2ch", "知恵袋")


def site_config(site_id):
    """サイトごとの発掘条件を組み立てる。

    担当領域（owns）をそのまま採用条件に使い、他サイトのownsを除外条件に使う。
    これにより「補充した時点で領域外のKWが混ざらない」状態を作る。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sites as sites_mod
    cfgs = sites_mod.load_all()
    cfg = cfgs[site_id]
    seeds = cfg.get("kw_seeds", {})
    own = tuple(t.lower() for t in cfg.get("owns", []))
    other = tuple(t.lower() for sid, c in cfgs.items() if sid != site_id
                  for t in c.get("owns", []))
    # 自サイトも使う語は除外語から外す（例: ai-lab と subsidy が共に「AI」を持つ場合）
    other = tuple(t for t in other if t not in own)
    return {
        "cfg": cfg,
        "plan": ROOT / cfg.get("kw_plan", "docs/industry-pillar-plan.md"),
        "gsc": f"https://{cfg['domain']}/",
        "industries": seeds.get("industries", []),
        "intents": seeds.get("intents", []),
        "own_terms": own,
        "domain_terms": own + GENERIC_TERMS,
        "ng_terms": BASE_NG + other,
    }


def load_env():
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def gsc_queries(site=None):
    """GSCで表示実績のあるクエリ（実データ）。未設定なら空リスト"""
    sa = ROOT / "indexing-service-account.json"
    site = site or load_env().get("GSC_SITE_URL", "https://ai.7senses.co.jp/")
    if not sa.exists():
        return []
    try:
        import gcreds
        from googleapiclient.discovery import build
        creds = gcreds.load(sa, ["https://www.googleapis.com/auth/webmasters.readonly"])
        sc = build("searchconsole", "v1", credentials=creds)
        res = sc.searchanalytics().query(siteUrl=site, body={
            "startDate": (date.today() - timedelta(days=90)).isoformat(),
            "endDate": date.today().isoformat(),
            "dimensions": ["query"], "rowLimit": 200}).execute()
        return [{"kw": r["keys"][0], "imp": int(r["impressions"]),
                 "pos": round(r["position"], 1)} for r in res.get("rows", [])]
    except Exception as e:
        # 403は「追加されていない」ではなく「権限が制限付き」であることが多い。
        # 生の例外を出すと原因が読み取れず、実際に長く放置されていた。
        if "403" in str(e) or "sufficient permission" in str(e):
            print(f"（GSC取得スキップ: {site} の権限が不足しています。"
                  "python scripts/gsc_check.py で対処手順を確認してください）")
        else:
            print(f"（GSC取得スキップ: {e}）")
        return []


def suggest(q, source="web"):
    """サジェスト（認証不要・無料）

    source="web"     Google検索のサジェスト
    source="youtube" YouTube検索のサジェスト。動画で調べられる言葉は
                     「やり方」「手順」など手を動かす前の検索が多く、
                     Google検索とは並びが変わる。
    """
    ds = "yt" if source == "youtube" else ""
    u = ("https://suggestqueries.google.com/complete/search?client=firefox&hl=ja"
         + (f"&ds={ds}" if ds else "") + "&q=" + urllib.parse.quote(q))
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=15) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))[1]
    except Exception:
        return []


# 語尾に1文字ずつ足して、サジェストの続きを引き出す。
# ラッコキーワードが「あ〜ん」で候補を広げているのと同じ考え方で、
# 1語につき取れる候補が10件前後から100件超に増える。
KANA = list("あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわ")
ALNUM = list("abcdefghijklmnopqrstuvwxyz0123456789")


def suggest_deep(q, source="web", chars=None, wait=0.25):
    """語尾を1文字ずつ変えて候補を広く集める"""
    out = list(suggest(q, source))
    for ch in (chars if chars is not None else KANA):
        got = suggest(f"{q} {ch}", source)
        out += got
        time.sleep(wait)          # 連続で叩くと弾かれるため間隔をあける
    # 順番を保ったまま重複を落とす（先に出たものほど検索需要が大きい）
    seen, uniq = set(), []
    for k in out:
        if k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq


BRAND_TERMS = ("セブンセンシズ", "セブンセンシス", "7senses", "sevensenses",
               "原口優", "原口 優", "g-ran", "gran ")


def is_brand_query(low):
    """指名検索。既に上位表示されており、記事を書く対象ではない"""
    return any(t in low for t in BRAND_TERMS)



def hub_client_enabled_but_unreadable(ledger_ok):
    """管制塔が設定されているのに読めなかったか（未設定なら手元実行なので許可する）"""
    try:
        import hub_client
        return hub_client.enabled() and not ledger_ok
    except Exception:
        return False

def is_dup(kw, arts, seen):
    if any(dice(kw, s) >= 0.75 for s in seen):
        return True
    return any(dice(kw, a["title"]) >= DUP_THRESHOLD for a in arts)


def main():
    site_id = "ai-lab"
    if "--site" in sys.argv:
        site_id = sys.argv[sys.argv.index("--site") + 1]
    S = site_config(site_id)
    if not S["industries"]:
        print(f"{site_id}: sites/{site_id}.json に kw_seeds が未定義のため発掘できません")
        return
    print(f"KW_DISCOVER_SITE={site_id}（{S['cfg']['name']}）")
    arts = load_articles()
    corpus = written_corpus()
    planned = {k for _, k in plan_keywords()}
    # 台帳（管制塔）にすでに積まれているKWも既知として扱う。
    # 計画ファイルだけを見ていたため、台帳にあるKWを「新規」として毎回積み直し、
    # 補助金サイトでは補充16件がすべて重複で、実質0件しか増えていなかった。
    ledger, ledger_ok = set(), False
    try:
        import hub_client
        if hub_client.enabled():
            ledger = {(k.get("keyword") or "").strip()
                      for k in hub_client.all_kw(strict=True) if k.get("site") == site_id}
            ledger_ok = True
        else:
            print("（管制塔が未接続のため台帳と照合しません）")
    except Exception as e:
        print(f"［警告］台帳を読めませんでした: {e}")
    seen = set(planned) | ledger
    print(f"既知KW: 計画{len(planned)}件 + 台帳{len(ledger)}件")

    # 台帳を読めないまま追記すると、既にある語を「新規」として積み直してしまう。
    # 実際にそれで補助金サイトの補充が実質0件になっていたため、追記は行わない。
    if "--append" in sys.argv and hub_client_enabled_but_unreadable(ledger_ok):
        raise SystemExit(
            "台帳を読めないため追記を中止します（重複を積むのを防ぐため）。\n"
            "  HUB_URL / HUB_SECRET を確認して再実行してください")
    proven, discovered = [], []

    # --- 1. GSC実データ（表示実績あり・記事なし = 最優先）---
    # 表示実績があっても、担当領域外・指名検索のクエリは記事にしない。
    # （例: コーポレートのGSCには前身事業の「害虫駆除」系や社名検索が大量に含まれる）
    for q in gsc_queries(S["gsc"]):
        kw = q["kw"]
        low = kw.lower()
        if is_written(kw, corpus) or is_dup(kw, arts, seen):
            continue
        if not any(t in low for t in S["own_terms"]):
            continue
        if any(t in low for t in S["ng_terms"]) or is_brand_query(low):
            continue
        seen.add(kw)
        proven.append(q)
    proven.sort(key=lambda q: -q["imp"])

    # --- 2. サジェスト（検索需要の裏付けあり）---
    # Google検索とYouTube検索の両方から集める。動画で調べられる言葉は
    # 「やり方」「手順」寄りで、Google検索とは並びが変わる。
    # --deep を付けると語尾を1文字ずつ変えて候補を広げる（取得数は増えるが時間もかかる）
    sources = ["web", "youtube"] if "--no-youtube" not in sys.argv else ["web"]
    for ind in S["industries"]:
        for it in S["intents"]:
            picked = 0
            cand = []
            for src in sources:
                cand += suggest(f"{ind} {it}", src)
            for s in cand:
                s = s.strip()
                low = s.lower()
                # 起点そのもの・短すぎる語・既出は除外し、ロングテールだけ残す
                if len(s) < 6 or s == f"{ind} {it}" or is_written(s, corpus):
                    continue
                # 業種語を含み、自社テーマの語を1つ以上含み、除外語を含まないものだけ採用
                if ind not in s or not any(t in low for t in S["domain_terms"]):
                    continue
                if any(t in low for t in S["ng_terms"]):
                    continue
                if is_dup(s, arts, seen):
                    continue
                seen.add(s)
                discovered.append(s)
                picked += 1
                if picked >= PER_SEED:
                    break
            time.sleep(0.2)  # サジェストAPIへの配慮

    # --- 2-2. 業種語だけを50音で深掘り（--deep のとき）---
    # 業種×意図の全通りで深掘りすると数万リクエストになり現実的でない。
    # 業種語だけに絞れば十数分で終わり、意図の欄には無い言い回しが拾える。
    if "--deep" in sys.argv:
        before = len(discovered)
        for ind in S["industries"]:
            cand = []
            for src in sources:
                cand += suggest_deep(ind, src)
            picked = 0
            for s in cand:
                s = s.strip()
                low = s.lower()
                if len(s) < 6 or s == ind or is_written(s, corpus):
                    continue
                if ind not in s or not any(t in low for t in S["domain_terms"]):
                    continue
                if any(t in low for t in S["ng_terms"]) or is_brand_query(low):
                    continue
                if is_dup(s, arts, seen):
                    continue
                seen.add(s)
                discovered.append(s)
                picked += 1
                if picked >= PER_SEED * 3:   # 深掘りぶんは多めに採る
                    break
        print(f"  深掘りで追加: {len(discovered) - before}件")

    print(f"KW_DISCOVER: GSC実証={len(proven)}件 / サジェスト発掘={len(discovered)}件")
    if proven:
        print("\n■ 表示実績あり・記事なし（最優先で執筆する）")
        for q in proven[:15]:
            print(f"  - {q['kw']}  （表示{q['imp']}回・平均{q['pos']}位）")
    if discovered:
        print("\n■ サジェスト由来の新規候補（検索需要の裏付けあり）")
        for s in discovered[:20]:
            print(f"  - {s}")

    if "--append" in sys.argv:
        picks = [q["kw"] for q in proven[:10]] + discovered
        picks = picks[:MAX_APPEND]
        if not picks:
            print("\n追記対象なし（新規候補が見つかりませんでした）")
            return
        line = (f"\n**自動補充 {date.today().isoformat()}"
                f"（GSC実証{len(proven[:10])}件+サジェスト{len(picks) - len(proven[:10])}件・{len(picks)}本）**: "
                + " / ".join(picks) + "\n")
        with S["plan"].open("a", encoding="utf-8") as f:
            f.write(line)
        print(f"\n{S['plan'].relative_to(ROOT).as_posix()} へ {len(picks)}件を追記しました")
        # 実行時にKWを供給しているのは管制塔の台帳なので、そちらにも積む
        try:
            import hub_client
            if hub_client.enabled():
                hub_client.add_kw(site_id, picks)
                print(f"管制塔の台帳へ {len(picks)}件を追加しました（site={site_id}）")
            else:
                print("（管制塔が未接続のため台帳への追加はスキップ）")
        except Exception as e:
            print(f"（管制塔への追加をスキップ: {e}）")


if __name__ == "__main__":
    main()
