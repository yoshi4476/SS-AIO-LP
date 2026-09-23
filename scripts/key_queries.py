# -*- coding: utf-8 -*-
"""主要クエリを宣言し、順位を毎週追い、上がっていない語に手を割り当てる。

**なぜ要るか**: 既存の `rank_up` と `rank_rescue` はページ単位で動く。
「この案件の主要クエリはこれ」という宣言がどこにも無いため、
何を上げたかったのかが記録に残らず、上がったかどうかも後から言えない。
実際、AIO運用の成果を「主要クエリの平均順位が開始時より上がったか」で
数えたが、その主要クエリの一覧はこのリポジトリのどこにも無かった。

**圏外の扱い（ここで固定する）**: GSCは表示が発生した語しか返さない。
返ってこない語は「検索結果に出ていない」とみなし、**101位として扱う**。
「出ていない」と「出ているがGSCが返さない」は区別できないため、
順位が付いた時点を「上がった」と数える。この定義を公開するデータにも書く。

    python scripts/key_queries.py --init --site ai-lab   # 主要クエリを作る
    python scripts/key_queries.py --track                # 週次。順位を記録する
    python scripts/key_queries.py                        # いまの状況を見る

終了コードは常に0（CLAUDE.md 8.7）。判定は KEYQ_OK= の印で行う。
"""
import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

REG = ROOT / "data" / "key_queries.json"
HIST = ROOT / "data" / "key_query_history.jsonl"
SITES = ROOT / "sites"
ARTICLES = ROOT / "articles"

OUT = 101.0          # 検索結果に出ていない語の扱い。定義を1か所に固定する
MIN_IMP = 3          # これ未満の表示は順位が安定しないので主要クエリにしない
DEFAULT_N = 30       # 1サイトの主要クエリ数の上限
CANN_MAX_POS = 30.0  # 食い合いとみなす上限順位（rank_rescue と同じ）
CANN_MAX_GAP = 15.0  # 2ページの順位差がこれを超えれば偶然とみなす


def sites():
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(SITES.glob("*.json"))}


def load():
    return json.loads(REG.read_text(encoding="utf-8")) if REG.is_file() else {}


def save(d):
    REG.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def norm(s):
    """表記ゆれを吸収する。ハイフン・長音・空白の違いで別語にしない"""
    return re.sub(r"[\s\-‐-―ー_]+", "", str(s)).lower()


def fetch(domain, days=28, dims=("query",)):
    """GSCから取る。**順位はquery次元でしか取れない**ので、ここでは合計を出さない。

    query次元は検索数の少ない語を落とす。合計を出すとその分だけ小さく出るため、
    このファイルでは合計を一切計算しない（CLAUDE.md 0.1 のGSCの落とし穴）。
    """
    import gsc_detail as G
    sc = G.client()
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=days - 1)
    rows = G.q(sc, domain, start.isoformat(), end.isoformat(), dims=list(dims), limit=5000)
    return [G.row(r) for r in rows]


def owns_of(cfg):
    got = cfg.get("owns") or []
    seeds = cfg.get("kw_seeds") or {}
    return [norm(x) for x in list(got) + list(seeds.get("core") or [])]


def keywords_of_site(site_id, cfg):
    """記事の keyword: を集める。どのサイトの記事かは category: で決まる（site: は無い）"""
    cats = set(cfg.get("categories") or {})
    out = {}
    for p in ARTICLES.glob("*.md"):
        head = p.read_text(encoding="utf-8", errors="replace")[:1200]
        m = re.search(r"^keyword:\s*(.+)$", head, re.M)
        c = re.search(r"^category:\s*(.+)$", head, re.M)
        if not (m and c) or c.group(1).strip() not in cats:
            continue
        out[norm(m.group(1).strip())] = (m.group(1).strip(), p.stem)
    return out


def init(site_id, cfg, limit=DEFAULT_N):
    """主要クエリを作る。宣言した語（keyword:）と、実際に表示が出ている語の両方から取る"""
    declared = keywords_of_site(site_id, cfg)
    rows = fetch(cfg["domain"])
    seen, picked = set(), []
    by_q = {norm(r["k"][0]): r for r in rows}

    # 表示の出ている語を先に置く。アルファベット順で切ると、
    # 実測できる語が落ちて圏外の語だけが残る（実際にそうなった）
    def rank(kv):
        r = by_q.get(kv[0])
        return (0, -r["imp"], r["pos"]) if r else (1, 0, 0)

    for nq, (raw, slug) in sorted(declared.items(), key=rank):
        r = by_q.get(nq)
        pos = round(r["pos"], 1) if r else OUT
        picked.append({"q": raw, "base": pos, "base_at": date.today().isoformat(),
                       "from": "宣言", "slug": slug})
        seen.add(nq)

    owns = owns_of(cfg)
    for r in sorted(rows, key=lambda x: -x["imp"]):
        nq = norm(r["k"][0])
        if nq in seen or r["imp"] < MIN_IMP:
            continue
        if owns and not any(o in nq for o in owns):
            continue
        picked.append({"q": r["k"][0], "base": round(r["pos"], 1),
                       "base_at": date.today().isoformat(), "from": "実績", "slug": ""})
        seen.add(nq)
        if len(picked) >= limit:
            break

    d = load()
    d[site_id] = {"since": date.today().isoformat(), "queries": picked[:limit]}
    save(d)
    print(f"  {site_id}: 主要クエリ {len(d[site_id]['queries'])}語を登録しました "
          f"（宣言 {sum(1 for x in picked[:limit] if x['from'] == '宣言')}語 / "
          f"実績 {sum(1 for x in picked[:limit] if x['from'] == '実績')}語）")
    return d[site_id]


def cause(q, pos, rows_pq, titles):
    """上がっていない語に、既存のどの工程を当てるかを決める"""
    nq = norm(q)
    pages = [r for r in rows_pq if norm(r["k"][1]) == nq]
    if not pages:
        return "記事が無い", "その語に答える記事を書く（kw_guard を通してから）"
    # 2ページ出ているだけでは食い合いではない。順位が離れていれば、
    # 片方はたまたま出ているだけ。rank_rescue と同じ基準（30位以内・差15以内）に揃える
    if len(pages) >= 2:
        ps = sorted(p["pos"] for p in pages)
        if ps[0] <= CANN_MAX_POS and ps[1] - ps[0] <= CANN_MAX_GAP:
            return "食い合い", "auto_merge（統合）か、負け側から勝ち側へリンク"
    slug = pages[0]["k"][0].rstrip("/").rsplit("/", 1)[-1]
    t = titles.get(slug, "")
    if t and not any(w and norm(w) in norm(t) for w in re.split(r"\s+", q)):
        return "語がタイトルに無い", "auto_rewrite（タイトルと見出しに語を入れる）"
    if pos > 30:
        return "内容が足りない", "auto_rewrite の stuck 種別（その語に答える節を足す）"
    return "抽出構造・一次データ", "冒頭の断言・H2直下の1文結論・一次データを足す"


def titles_map():
    out = {}
    for p in ARTICLES.glob("*.md"):
        m = re.search(r"^title:\s*(.+)$", p.read_text(encoding="utf-8", errors="replace")[:1200], re.M)
        if m:
            out[p.stem] = m.group(1).strip()
    return out


def track(only=""):
    reg, allsites, titles = load(), sites(), titles_map()
    if not reg:
        print("  主要クエリが未登録です。--init --site <id> で作ってください")
        print("KEYQ_OK=yes")
        return 0
    today, stuck_all, up_all, tot = date.today().isoformat(), [], 0, 0
    lines = []
    # 同じ日に2回走ると履歴が二重になる。当日分を落としてから書き直す
    keep = [l for l in (HIST.read_text(encoding="utf-8").splitlines() if HIST.is_file() else [])
            if l.strip() and json.loads(l).get("at") != today]
    HIST.write_text(chr(10).join(keep) + (chr(10) if keep else ""), encoding="utf-8")
    with HIST.open("a", encoding="utf-8") as fh:
        for site_id, blk in sorted(reg.items()):
            if only and site_id != only:
                continue
            cfg = allsites.get(site_id)
            if not cfg:
                continue
            rows = fetch(cfg["domain"])
            by_q = {norm(r["k"][0]): r for r in rows}
            rows_pq = fetch(cfg["domain"], dims=("page", "query"))
            up, same, down, stuck = 0, 0, 0, []
            for item in blk["queries"]:
                r = by_q.get(norm(item["q"]))
                pos = round(r["pos"], 1) if r else OUT
                imp = r["imp"] if r else 0
                fh.write(json.dumps({"at": today, "site": site_id, "q": item["q"],
                                     "pos": pos, "imp": imp,
                                     "clicks": r["clicks"] if r else 0}, ensure_ascii=False) + "\n")
                base = item.get("base", OUT)
                if pos < base - 0.5:
                    up += 1
                elif pos > base + 0.5:
                    down += 1
                    stuck.append((item["q"], base, pos))
                else:
                    same += 1
                    stuck.append((item["q"], base, pos))
            n = len(blk["queries"])
            tot += n
            up_all += up
            lines.append(f"  {site_id}: {n}語中 上がった{up} / 変わらず{same} / 下がった{down}"
                         f"（起点 {blk['since']}）")
            for q, base, pos in stuck[:6]:
                c, how = cause(q, pos, rows_pq, titles)
                b = "圏外" if base >= OUT else f"{base:g}位"
                p = "圏外" if pos >= OUT else f"{pos:g}位"
                lines.append(f"      {q}（{b}→{p}） … {c} → {how}")
                stuck_all.append((site_id, q, c))
    print("■ 主要クエリの推移")
    for l in lines:
        print(l)
    if tot:
        print(f"  合計 {tot}語中 {up_all}語が起点より上がりました（{up_all / tot * 100:.1f}%）")
    print(f"KEYQ_OK={'yes' if not stuck_all else 'no'}")
    if stuck_all:
        print(f"  上がっていない語 {len(stuck_all)}件に、上の工程を当ててください")
    return 0


def show():
    reg = load()
    if not reg:
        print("  主要クエリが未登録です。--init --site <id> で作ってください")
        return 0
    for site_id, blk in sorted(reg.items()):
        print(f"■ {site_id}（起点 {blk['since']}・{len(blk['queries'])}語）")
        for x in blk["queries"][:12]:
            b = "圏外" if x["base"] >= OUT else f"{x['base']:g}位"
            print(f"     {x['q']}  起点 {b}  [{x['from']}]")
        if len(blk["queries"]) > 12:
            print(f"     …ほか {len(blk['queries']) - 12}語")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true", help="主要クエリを作る")
    ap.add_argument("--track", action="store_true", help="順位を記録する（週次）")
    ap.add_argument("--site", default="", help="サイトID")
    ap.add_argument("--limit", type=int, default=DEFAULT_N)
    a = ap.parse_args()
    if a.init:
        allsites = sites()
        for sid, cfg in allsites.items():
            if a.site and sid != a.site:
                continue
            init(sid, cfg, a.limit)
        return 0
    if a.track:
        return track(a.site)
    return show()


if __name__ == "__main__":
    sys.exit(main())
