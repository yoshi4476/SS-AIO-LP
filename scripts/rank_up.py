# -*- coding: utf-8 -*-
"""順位を上げることだけに絞った工程。毎週これを回す。

順位はGoogleが決めるので約束できない。できるのは「こちら側でやれることを、
漏れなく、同じ基準で続ける」ことだけ。ここではその中身を固定する。

狙うのは11〜20位。1ページ目に最も近く、上がればクリックが数倍になる層。
実測でAI集客ラボは、この層に72ページ・1,711表示があってクリックは18回だった。

■ データの取り方を1か所に固定する
GSCは見る次元で数字が変わる。query次元は検索数の少ない語を返さないため、
実態より小さく出る（実測: page次元50クリックが query次元では0と出た）。
この誤りを繰り返さないよう、**取得はこのファイルの fetch() だけで行う**。

■ やること（すべて機械で確かめられるもの）
  1. 内部リンクを下限まで集める      … 評価が集まらないと順位は動かない
  2. 狙う語がタイトルに入っているか   … 入っていないと内容が合っていても出ない
  3. 同じ語で自社の別ページが出ていないか … 競合すると両方とも上がらない
  4. 最終更新が古すぎないか          … 鮮度は順位にも引用にも効く
  5. 直したら検索エンジンへ再通知     … 知らせないと反映が遅れる

■ 効果を必ず記録する
直しただけで終わると、効いたかどうかが分からない。直した日と順位を
data/rank_up.json に残し、次回の実行で前後を比べる。

  python scripts/rank_up.py            # 何をすべきか見る
  python scripts/rank_up.py --write    # 機械で直せるものを直す
  python scripts/rank_up.py --effect   # 前回直したものがどうなったか
"""
import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
LOG = ROOT / "data" / "rank_up.json"

NEAR = (10.5, 20.5)     # 1ページ目に最も近い層
MIN_IMP = 20            # これ未満は偶然と区別できない
INBOUND_FLOOR = 12      # 被リンクの下限
STALE_DAYS = 120        # 最終更新がこれより古ければ鮮度を疑う


def fetch(domain, days=28):
    """GSCからページごとの実績を取る。**取得はここだけで行う。**

    次元を変えると数字が変わる。実測で page×query は page次元より
    クリックが3〜4割少なく出た（検索数の少ない語をGSCが返さないため）。
    この食い違いに気づかず query 次元だけを見て「クリックが出ていない」と
    判断し、誤った結論を出した。同じことを繰り返さないよう、次のように分ける。

      表示・クリック・順位 … page次元（欠落しない）
      その記事の検索語     … page×query（欠落するが、語を知るには十分）

    両方をここで取り、page次元の数字を正とする。
    """
    import gsc_detail as G
    sc = G.client()
    end = date.today() - timedelta(days=3)      # 確定分
    start = end - timedelta(days=days - 1)

    # URLをそのまま鍵にする。末尾だけをslugにすると、
    # /aio/ と /seo/ の同名ページや、カテゴリ一覧とトップが1つに潰れる。
    # 実測で121行が119ページに減り、表示が314回ぶん消えていた
    # 同じページが「末尾スラッシュあり/なし」で2行に分かれることがある。
    # 上書きすると片方の表示が消える（実測で corporate の2ページ・37表示が消えた）。
    # 足し合わせ、順位は表示回数で重みづけする
    pages = {}
    for r in G.q(sc, domain, str(start), str(end), ["page"], 25000):
        url = r["keys"][0].rstrip("/")
        d = pages.get(url)
        if d is None:
            pages[url] = {"imp": r["impressions"], "clicks": r["clicks"],
                          "pos": r["position"], "url": url,
                          "slug": url.rsplit("/", 1)[-1], "kws": [], "urls": 1}
        else:
            tot = d["imp"] + r["impressions"]
            d["pos"] = ((d["pos"] * d["imp"] + r["position"] * r["impressions"])
                        / max(1, tot))
            d["imp"] = tot
            d["clicks"] += r["clicks"]
            d["urls"] += 1
    for r in G.q(sc, domain, str(start), str(end), ["page", "query"], 25000):
        url = r["keys"][0].rstrip("/")
        if url in pages:
            pages[url]["kws"].append((r["keys"][1], r["position"], r["impressions"]))
    for d in pages.values():
        d["kws"].sort(key=lambda x: (-x[2], x[1]))
    return pages


def articles():
    return {p.stem: p.read_text(encoding="utf-8-sig", errors="replace")
            for p in (ROOT / "articles").glob("*.md")}


def inbound(slug, texts):
    pat = re.compile(r"\]\((?:https?://[^/)]+)?/[a-z0-9/-]*" + re.escape(slug) + r"/?\)")
    return sum(1 for k, t in texts.items() if k != slug and pat.search(t))


def fm_of(text):
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    return m.group(1) if m else ""


def field(text, key):
    return (re.search(rf"^{key}:\s*(.+)$", fm_of(text), re.M) or [0, ""])[1].strip().strip('"')


def diagnose(slug, d, texts, all_pages):
    """そのページの順位が上がらない理由を、確かめられるものだけ挙げる"""
    out = []
    t = texts.get(slug, "")
    kw = d["kws"][0][0] if d["kws"] else ""

    n = inbound(slug, texts)
    if n < INBOUND_FLOOR:
        out.append(("links", f"内部リンク{n}本（下限{INBOUND_FLOOR}本）", INBOUND_FLOOR - n))

    title = field(t, "title")
    parts = [w for w in re.split(r"[\s　]+", kw) if len(w) >= 2]
    if parts and not all(w.lower() in title.lower() for w in parts):
        miss = [w for w in parts if w.lower() not in title.lower()]
        out.append(("title", f"タイトルに「{' '.join(miss)}」が無い", 0))

    # 同じ語で自社の別ページが出ていないか
    rivals = []
    for d2 in all_pages.values():
        s2 = d2["slug"]
        if s2 == slug:
            continue
        for k2, p2, i2 in d2["kws"][:5]:
            if k2 == kw and i2 >= 5:
                rivals.append((s2, p2, i2))
    if rivals:
        rivals.sort(key=lambda x: x[1])
        out.append(("rival", f"「{kw}」に自社の{len(rivals)}ページが競合"
                             f"（最上位 {rivals[0][0]} {rivals[0][1]:.0f}位）", 0))

    mod = field(t, "modified") or field(t, "date")
    try:
        old = (date.today() - date.fromisoformat(mod)).days
        if old > STALE_DAYS:
            out.append(("stale", f"最終更新から{old}日", 0))
    except ValueError:
        pass
    return out


def load_log():
    try:
        return json.loads(LOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_log(d):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def show_effect(pages_by_site):
    log = load_log()
    if not log:
        print("  まだ記録がありません（--write を実行すると記録されます）")
        return
    print(f"  {'記事':<34}{'直した日':<12}{'直前':>7}{'いま':>7}{'動き':>8}")
    print("  " + "-" * 70)
    up = down = same = 0
    for slug, rec in sorted(log.items(), key=lambda kv: kv[1].get("at", "")):
        now = None
        for pages in pages_by_site.values():
            for d in pages.values():
                if d["slug"] == slug:
                    now = d["pos"]
                    break
            if now is not None:
                break
        if now is None:
            continue
        before = rec.get("pos")
        diff = before - now if before else 0
        mark = f"{diff:+.1f}位" if before else "―"
        if before:
            up += diff > 0.5
            down += diff < -0.5
            same += abs(diff) <= 0.5
        print(f"  {slug[:32]:<34}{rec.get('at','')[:10]:<12}"
              f"{before or 0:>6.1f}位{now:>6.1f}位{mark:>8}")
    print("  " + "-" * 70)
    print(f"  上がった {up} / 下がった {down} / 変わらず {same}")
    print("\n  ※ 順位はGoogleが決める。反映に数週間かかり、競合の動きも混ざる")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--effect", action="store_true")
    ap.add_argument("--site", default="")
    ap.add_argument("--limit", type=int, default=12)
    a = ap.parse_args()
    import sites as S

    by_site = {}
    for sid, cfg in S.load_all().items():
        if a.site and sid != a.site:
            continue
        try:
            by_site[sid] = fetch(cfg["domain"])
        except Exception as e:
            print(f"  {sid}: GSCから取れません（{str(e)[:50]}）")

    if a.effect:
        print("■ 前に直したページが、その後どうなったか\n")
        show_effect(by_site)
        return 0

    texts = articles()
    log = load_log()
    print(f"■ 1ページ目に最も近い層（{NEAR[0]:.0f}〜{NEAR[1]:.0f}位・表示{MIN_IMP}回以上）\n")
    added = human = 0
    for sid, pages in by_site.items():
        near = {d["slug"]: d for d in pages.values()
                if NEAR[0] < d["pos"] <= NEAR[1] and d["imp"] >= MIN_IMP
                and d["slug"] in texts}
        if not near:
            continue
        print(f"  ── {S.load(sid)['name'][:20]}  {len(near)}ページ")
        for slug, d in sorted(near.items(), key=lambda kv: -kv[1]["imp"])[:a.limit]:
            issues = diagnose(slug, d, texts, pages)
            head = (f"  {d['pos']:>5.1f}位 表示{d['imp']:>4} ｸﾘｯｸ{d['clicks']:>3}  "
                    f"{slug[:30]}")
            print(head)
            for kind, msg, need in issues:
                print(f"        ・{msg}")
                if kind == "links" and a.write and need:
                    import priority_boost as P
                    kws = [(k, p, i) for k, p, i in d["kws"][:3]]
                    n = P.send_links(slug, P.topic_words(slug, kws, texts), need, texts)
                    added += n
                    print(f"          → 内部リンクを{n}本足しました")
                elif kind in ("title", "rival"):
                    human += 1
            if a.write:
                log[slug] = {"at": date.today().isoformat(), "pos": round(d["pos"], 1),
                             "imp": d["imp"], "site": sid}
        print()

    if a.write:
        save_log(log)
        print(f"  内部リンクを計{added}本足し、{len(log)}件を記録しました")
        print("  次: python scripts/notify_indexnow.py で検索エンジンへ再通知")
        print("      python scripts/rank_up.py --effect で数週間後に効果を見る")
    else:
        print("  --write を付けると、内部リンクの不足を埋めて記録します")
    if human:
        print(f"  人の判断が要るもの: {human}件（タイトル・競合の解消）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
