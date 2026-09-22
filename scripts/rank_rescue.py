# -*- coding: utf-8 -*-
"""11〜30位で止まった記事を、実測から原因を分けて押し上げる。

新規記事は止めない。止まっている記事に手を入れる工程を、別に持つ。

**なぜ要るか**: 既存の `priority_boost` は `NEAR = (10.5, 20.5)` しか見ておらず、
21〜30位が丸ごと対象外だった。実測（28日・2026-08-23〜09-19）では
11〜20位に106語・21〜30位に138語が溜まり、合わせて表示1,496回・クリック0だった。
さらに `priority_boost` は主力商材の語（MAIN_PATTERN）に絞るため、
業種記事の多くが最初から拾われない。ここでは語で絞らず、**順位で絞る**。

**原因は3つしかない**（34本を実測して分類した）:

| 原因 | 何が起きているか | 直し方 |
|:--|:--|:--|
| `term` | 需要のある語が見出しに1つも無い | `auto_rewrite` の stuck 種別で節を足す |
| `cannibal` | 同じ語で自社の別ページが競合している | `auto_merge`（統合）か、負け側から勝ち側へリンク |
| `link` | 内部リンクが下限に届いていない | `link_boost` |

実例: 「整骨院のMEO対策」は狙った「整骨院 meo」が38位なのに、
見出しに無い「カイロ meo」で7位・表示67回を取っていた。記事が答えている
相手と、検索している相手がずれている。語を足すのではなく、**その語に答える節**を足す。

    python scripts/rank_rescue.py              # 診断（課金なし・GSCのみ）
    python scripts/rank_rescue.py --refresh    # GSCを取り直す
    python scripts/rank_rescue.py --plan       # auto_rewrite に渡る順で見る
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

CACHE = ROOT / "data" / "rank_rescue.json"
BAND = (10.5, 30.5)      # 11〜30位。ここを1ページ目へ押し上げるのが最も効く
MIN_Q_IMP = 5            # この表示回数を割る語は、需要があるとは言えない
MIN_PAGE_IMP = 15        # ページ全体の下限。偶然と区別できない量は扱わない
MAX_TERMS = 4            # 1記事に足す観点の上限。増やすほど主題がぼやける
INBOUND_FLOOR = 12       # 内部リンクの下限（priority_boost と揃える）
STALE_DAYS = 3

# 拾わない語。読者が顧客でない語と、他人の指名検索
NEVER = re.compile(r"求人|採用|募集|転職|副業|資格|年収|バイト|儲か|稼[ぐげ]|無料ダウンロード", re.I)
# 自然文の質問（AI検索経由に多い）はここでは扱わない。語を足して直すものではないため。
# 実際に「中小企業でaioツールの導入を検討しています。まずは無料」から
# 「、候補」「すい」「教えてください。」を足りない語として拾ってしまった
NL_CHARS, NL_TOKENS = 24, 5
# 語として足す価値がない断片。活用語尾・助詞の残りかす
JUNK = re.compile(r"^[ぁ-ん]{1,3}$|[。、！？]|^(こと|もの|ため|よう|など|それ|これ|どこ|いくつ|候補)$"
                  r"|(ます|です|たい|ました|ください|ている|しま)$")
MIN_TERM_IMP = 6         # 語ごとの表示合計。これ未満は偶然と区別できない
# 食い合いと呼べる条件。同じ語で2ページ出ていても、片方が52位なら奪っていない。
# 実測6件のうち4件は相手が40〜69位で、直す価値のない組だった。
# 「どちらを出すかGoogleが迷っている」と言えるのは、両方が近い順位にいるとき
CANN_MAX_POS = 30.0      # competing と言える上限。これより後ろの相手は無視
CANN_MAX_GAP = 15.0      # 2ページの順位差。開きすぎている組は迷っていない


def norm(s):
    """表記ゆれを吸収する。助詞・記号・全角半角の違いで別語と見なさない"""
    s = re.sub(r"[\s　・･／/（）\(\)｜|【】\[\]「」、。,.･]", "", s.lower())
    return s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))


def terms_of(kw):
    """語を意味の単位に割る。空白区切りだけでは自然文KWを扱えない"""
    parts = [t for t in re.split(r"[\s　]+", kw) if t]
    out = []
    for p in parts:
        # 助詞がくっついた自然文はさらに割る（kw_guard の既知の穴と同じ扱い）
        out += [x for x in re.split(r"[のでにをはがともへやか？?！!]", p) if len(x) >= 2]
    return [x for x in out if 2 <= len(x) <= 12 and not x.isdigit() and not JUNK.search(x)]


def fetch(days=28):
    """GSCから、ページ×語を取る。合計は使わないので次元つきで問題ない"""
    import gsc_detail as G
    import sites as S
    sc = G.client()
    end = date.today() - timedelta(days=3)          # 確定待ち
    start = end - timedelta(days=days - 1)
    out = {}
    for sid, cfg in S.load_all().items():
        try:
            rows = G.q(sc, cfg["domain"], str(start), str(end), ["query", "page"], 25000)
        except Exception as e:
            print(f"  {sid}: GSCから取れません（{str(e)[:50]}）")
            continue
        out[sid] = [{"kw": r["keys"][0], "url": r["keys"][1].rstrip("/") + "/",
                     "pos": r["position"], "imp": r["impressions"], "clk": r["clicks"]}
                    for r in rows]
    payload = {"at": str(date.today()), "span": [str(start), str(end)], "sites": out}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8",
                     newline="\n")
    return payload


def load(refresh=False):
    if refresh or not CACHE.is_file():
        return fetch()
    d = json.loads(CACHE.read_text(encoding="utf-8"))
    try:
        age = (date.today() - datetime.fromisoformat(d["at"]).date()).days
    except Exception:
        age = 99
    return fetch() if age > STALE_DAYS else d


def article_index():
    """原稿の索引。slug -> 見出しと本文"""
    out = {}
    for p in (ROOT / "articles").glob("*.md"):
        t = p.read_text(encoding="utf-8-sig", errors="ignore")
        m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
        fm, body = (m.group(1), t[m.end():]) if m else ("", t)

        def g(k):
            x = re.search(rf"^{k}:\s*(.+)$", fm, re.M)
            return x.group(1).strip().strip('"') if x else ""

        score = g("score")
        if not score.isdigit() or int(score) < 90:
            continue                                 # 非公開の記事は押し上げない
        slug = g("slug") or p.stem
        heads = re.findall(r"^#{2,4}\s*(.+)$", body, re.M)
        out[slug] = {"slug": slug, "file": p.name, "title": g("title"),
                     "kw": g("keyword"), "heads": heads,
                     "hay": norm(g("title") + " " + " ".join(heads)),
                     "body_hay": norm(body), "body": body}
    return out


def inbound_counts(arts):
    """どの記事が、何本の内部リンクを受けているか"""
    n = defaultdict(int)
    for a in arts.values():
        for u in set(re.findall(r"\]\((/[^)]+/)\)", a["body"])):
            n[u.rstrip("/").split("/")[-1]] += 1
    return n


def diagnose(refresh=False):
    """止まっている記事を、原因つきで返す"""
    d = load(refresh)
    arts = article_index()
    inb = inbound_counts(arts)
    owner = defaultdict(list)
    for sid, rows in d["sites"].items():
        for r in rows:
            owner[(sid, norm(r["kw"]))].append(r)

    pages = defaultdict(lambda: {"imp": 0, "clk": 0, "ps": 0.0, "qs": []})
    for sid, rows in d["sites"].items():
        for r in rows:
            k = (sid, r["url"])
            p = pages[k]
            p["imp"] += r["imp"]; p["clk"] += r["clk"]
            p["ps"] += r["pos"] * r["imp"]; p["qs"].append(r)

    out = []
    for (sid, url), p in pages.items():
        slug = url.rstrip("/").split("/")[-1]
        a = arts.get(slug)
        if not a or p["imp"] < MIN_PAGE_IMP:
            continue
        pos = p["ps"] / p["imp"]
        if not (BAND[0] <= pos <= BAND[1]):
            continue
        p["qs"].sort(key=lambda r: -r["imp"])

        miss, cann = [], []
        for r in p["qs"]:
            if r["imp"] < MIN_Q_IMP or NEVER.search(r["kw"]):
                continue
            rivals = [o for o in owner[(sid, norm(r["kw"]))] if o["url"] != url]
            if rivals:
                best = min(rivals, key=lambda o: o["pos"])
                close = (min(r["pos"], best["pos"]) <= CANN_MAX_POS
                         and abs(r["pos"] - best["pos"]) <= CANN_MAX_GAP)
                if close:
                    cann.append({"kw": r["kw"], "pos": r["pos"], "imp": r["imp"],
                                 "rival": best["url"], "rival_pos": best["pos"]})
                    continue                         # 食い合いは語を足して直すものではない
            if len(r["kw"]) > NL_CHARS or len(re.split(r"[\s　]+", r["kw"])) > NL_TOKENS:
                continue                             # 自然文の質問は語の欠落では直らない
            gap = [t for t in terms_of(r["kw"]) if norm(t) not in a["hay"]]
            if gap:
                miss.append({"kw": r["kw"], "pos": r["pos"], "imp": r["imp"], "gap": gap,
                             "in_body": all(norm(t) in a["body_hay"] for t in gap)})

        # 語ごとに表示を足し、下限に届かない語は落とす（1回だけの語に引きずられない）
        per = defaultdict(int)
        for m in miss:
            for g in m["gap"]:
                per[g] += m["imp"]
        keep = {g for g, v in per.items() if v >= MIN_TERM_IMP}
        miss = [dict(m, gap=[g for g in m["gap"] if g in keep]) for m in miss]
        miss = [m for m in miss if m["gap"]]

        kinds = []
        if miss:
            kinds.append("term")
        if cann:
            kinds.append("cannibal")
        if inb.get(slug, 0) < INBOUND_FLOOR:
            kinds.append("link")
        if not kinds:
            continue
        out.append({"site": sid, "slug": slug, "url": url, "title": a["title"],
                    "kw": a["kw"], "pos": round(pos, 1), "imp": p["imp"], "clk": p["clk"],
                    "inbound": inb.get(slug, 0), "kinds": kinds,
                    "miss": miss[:MAX_TERMS], "cannibal": cann[:3]})
    # 効く順: 表示が多く、1ページ目に近いものから
    out.sort(key=lambda x: -(x["imp"] * max(0.0, 31 - x["pos"])))
    return out, d


def items(limit=0):
    """auto_rewrite に渡す形。語が見出しに無いものだけを対象にする。

    食い合いは統合（auto_merge）の仕事、内部リンクは link_boost の仕事なので、
    ここでは文章の判断が要るものだけを返す
    """
    rows, _ = diagnose()
    out = []
    for r in rows:
        if "term" not in r["kinds"]:
            continue
        need = []
        for m in r["miss"]:
            where = "本文にはあるが見出しに無い" if m["in_body"] else "記事に一度も出ていない"
            need.append(f"・「{m['kw']}」{m['pos']:.0f}位 表示{m['imp']}回"
                        f"（足りない観点: {'／'.join(m['gap'])}／{where}）")
        out.append({"kind": "stuck", "slug": r["slug"], "site": r["site"],
                    "terms": [t for m in r["miss"] for t in m["gap"]],
                    "why": (f"{r['pos']:.1f}位・表示{r['imp']}回・クリック{r['clk']}回。"
                            f"1ページ目の手前で止まっている。"
                            f"需要のある語に記事が答えていない:\n" + "\n".join(need))})
    return out[:limit] if limit else out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="GSCを取り直す")
    ap.add_argument("--plan", action="store_true", help="auto_rewrite に渡る順で見る")
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args()

    if a.plan:
        for i, it in enumerate(items(), 1):
            print(f"{i:>2}. [{it['site']}] {it['slug']}")
            print("    " + it["why"].replace("\n", "\n    "))
        return 0

    rows, d = diagnose(a.refresh)
    span = "〜".join(d.get("span", []))
    tot_imp = sum(r["imp"] for r in rows)
    print(f"■ 11〜30位で止まっている記事（{span}）: {len(rows)}本 / 表示{tot_imp:,}回\n")
    by = defaultdict(int)
    for r in rows:
        for k in r["kinds"]:
            by[k] += 1
    print(f"  原因別: 語が見出しに無い {by['term']}本 / 食い合い {by['cannibal']}本 / "
          f"内部リンク不足 {by['link']}本\n")
    print(f"{'順位':>6}{'表示':>6}{'内部':>5}  原因          記事")
    for r in rows[:a.top]:
        print(f"{r['pos']:>5.1f}位{r['imp']:>6}{r['inbound']:>5}  "
              f"{'+'.join(r['kinds']):<14}{r['title'][:38]}")
        for m in r["miss"][:2]:
            print(f"        → 「{m['kw'][:28]}」{m['pos']:.0f}位 表示{m['imp']}"
                  f"／見出しに無い: {'・'.join(m['gap'])}")
        for c in r["cannibal"][:1]:
            print(f"        → 食い合い「{c['kw'][:24]}」{c['pos']:.0f}位 ←→ "
                  f"{c['rival'].rstrip('/').split('/')[-1][:26]} {c['rival_pos']:.0f}位")
    print(f"\n  次にやること")
    print(f"   語が見出しに無い  → python scripts/auto_rewrite.py --write（stuck種別で直る）")
    print(f"   食い合い          → python scripts/auto_merge.py")
    print(f"   内部リンク不足    → python scripts/link_boost.py --write")
    print("RESCUE_OK=" + ("no" if rows else "yes"))
    if rows:
        print(f"   ::warning::11〜30位で{len(rows)}本が止まっています"
              f"（表示{tot_imp:,}回・クリック{sum(r['clk'] for r in rows)}回）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
