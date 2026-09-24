# -*- coding: utf-8 -*-
"""保証できることを、数字で示す。

**順位そのものは保証できない。** 決めるのはGoogleで、アルゴリズムの更新も
競合の動きもこちらの外側にある。それを「保証する」と言うのは嘘になる。

保証できるのは**順位を決める要因のうち、こちら側にあるものを毎回100%満たすこと**。
この道具は、その達成率を出し、足りない分を直す道具の名前まで書く。

  こちら側にある（保証する）      記事の作り・構造化データ・内部リンク・
                                 表示速度・インデックス通知・面の広さ
  こちらの外側（保証しない）      順位・競合の動き・アルゴリズム更新・
                                 外部被リンク（相手がある）

達成率100%は「上位表示される」ではなく「やれることに抜けが無い」という意味。
そこまでは機械が毎週詰める。

    python scripts/guarantee.py           # 達成率と、足りない分
    python scripts/guarantee.py --todo    # 直す手順だけを出す
"""
import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

INBOUND_FLOOR = 12


def published():
    """公開済みの記事。slug -> 本文つき"""
    out = {}
    for p in sorted((ROOT / "articles").glob("*.md")):
        if p.name.startswith("_"):
            continue
        t = p.read_text(encoding="utf-8-sig", errors="ignore")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
        if not m:
            continue
        fm, body = m.group(1), m.group(2)
        sc = re.search(r"^score:\s*(\d+)", fm, re.M)
        if not sc or int(sc.group(1)) < 90:
            continue
        slug = (re.search(r"^slug:\s*(\S+)", fm, re.M) or [None, p.stem])[1] \
            if re.search(r"^slug:\s*(\S+)", fm, re.M) else p.stem
        out[slug] = {"fm": fm, "body": body, "path": p}
    return out


def article_checks(arts):
    """記事ごとの決定的検査（score_check の21項目）"""
    import score_check as SC
    bad = defaultdict(list)
    total = ok = 0
    for slug in arts:
        try:
            checks = SC.run(slug)
        except Exception as e:
            bad["採点できない"].append(f"{slug}（{str(e)[:40]}）")
            total += 1
            continue
        total += 1
        fails = [c[0] for c in checks if not c[1] and not c[3]]
        if fails:
            for f in fails:
                bad[f].append(slug)
        else:
            ok += 1
    return ok, total, bad


def inbound_counts(arts):
    n = defaultdict(int)
    for a in arts.values():
        for u in set(re.findall(r"\]\((/[^)]+/)\)", a["body"])):
            n[u.rstrip("/").split("/")[-1]] += 1
    return n


# ページの種類ごとに、あるべき構造化データ。記事の型を全ページに求めると、
# 著者ページやデータページが不合格になり、達成率が意味を持たなくなる
EXPECT = [
    (r"^data/",      {"Dataset"},                  "一次データ"),
    (r"^industry/",  {"CollectionPage"},           "業種ハブ"),
    (r"^author/",    {"ProfilePage"},              "著者"),
    (r"^diagnosis/", {"BreadcrumbList"},           "診断"),
    (r"^glossary/",  {"DefinedTerm"},              "用語集"),
    (r"^compare/",   {"ItemList"},                 "比較表"),
    (r"^topics/",    {"CollectionPage"},           "テーマ"),
    (r"",            {"BlogPosting", "BreadcrumbList"}, "記事"),
]


def schema_coverage():
    """生成HTMLの構造化データ。種類ごとに、あるべき型が出ているか"""
    import glob
    pages = broken = ok = 0
    miss = []
    for p in glob.glob(str(ROOT / "site" / "*" / "*" / "index.html")):
        rel = Path(p).relative_to(ROOT / "site").as_posix()
        need = next(n for pat, n, _ in EXPECT if re.search(pat, rel))
        pages += 1
        h = Path(p).read_text(encoding="utf-8", errors="replace")
        m = re.search(r'<script type="application/ld\+json">(.*?)</script>', h, re.S)
        if not m:
            miss.append(rel)
            continue
        try:
            d = json.loads(m.group(1))
        except Exception:
            broken += 1
            miss.append(rel + "（壊れている）")
            continue
        types = {g.get("@type") for g in (d.get("@graph") or [d])}
        if need <= types:
            ok += 1
        else:
            miss.append(f"{rel}（{'/'.join(sorted(need - types))} が無い）")
    return ok, pages, broken, miss


def site_checks():
    """サイト単位の要因。外部への通知・基盤・面の広さ"""
    rows = []
    site = ROOT / "site"
    rb = (site / "robots.txt").read_text(encoding="utf-8", errors="ignore") \
        if (site / "robots.txt").is_file() else ""
    bots = ["GPTBot", "OAI-SearchBot", "ClaudeBot", "PerplexityBot",
            "Google-Extended", "Bingbot"]
    miss = [b for b in bots if b not in rb]
    rows.append(("AIクローラーの許可", not miss,
                 "許可済み" if not miss else f"未記載: {'/'.join(miss)}",
                 "site/robots.txt に追記"))

    llms = (site / "llms.txt").read_text(encoding="utf-8", errors="ignore") \
        if (site / "llms.txt").is_file() else ""
    sm = (site / "sitemap.xml").read_text(encoding="utf-8", errors="ignore") \
        if (site / "sitemap.xml").is_file() else ""
    n_sm = len(re.findall(r"<loc>", sm))
    rows.append(("sitemap が生成されている", n_sm > 0, f"{n_sm}URL", "python scripts/build.py"))
    rows.append(("llms.txt がある", bool(llms.strip()), f"{len(llms):,}字",
                 "python scripts/build.py"))

    keys = list(ROOT.glob("site/*.txt"))
    idx = [k for k in keys if re.fullmatch(r"[0-9a-f]{16,64}", k.stem)]
    rows.append(("IndexNow の鍵が置いてある", bool(idx),
                 idx[0].name if idx else "なし", "鍵ファイルを site/ に置く"))

    ds = list((ROOT / "data" / "datasets").glob("*.json"))
    rows.append(("一次データを公開している", len(ds) >= 3, f"{len(ds)}件",
                 "python scripts/data_auto.py --write"))

    led = ROOT / "data" / "published.json"
    rows.append(("公開の門が閉まっている", led.is_file(),
                 "台帳あり" if led.is_file() else "台帳なし",
                 "python scripts/build.py"))
    return rows


def coverage_gaps():
    try:
        import coverage as CV
    except Exception:
        return []
    out = []
    for sid in ("ai-lab", "corporate", "subsidy"):
        try:
            cells, inds, cs, arts, _ = CV.matrix(sid)
        except Exception:
            continue
        empty = sum(1 for i in inds for c in cs if not cells[(i["slug"], c)]["slugs"])
        pri = [i for i in inds if i.get("priority")] or inds
        pri_empty = sum(1 for i in pri for c in cs if not cells[(i["slug"], c)]["slugs"])
        out.append((sid, empty, len(inds) * len(cs), pri_empty, len(pri) * len(cs)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--todo", action="store_true", help="直す手順だけを出す")
    a = ap.parse_args()

    arts = published()
    ok_a, n_a, bad = article_checks(arts)
    inb = inbound_counts(arts)
    # 全記事は「辿り着ける」ことが基準（3本以上）。12本は1ページ目の手前で
    # 止まっている記事に効く水準なので、その記事だけに当てる
    n_inb3 = sum(1 for s in arts if inb.get(s, 0) >= 3)
    try:
        import rank_rescue as RR
        stuck = [r["slug"] for r in RR.diagnose()[0]]
    except Exception:
        stuck = []
    n_stuck_ok = sum(1 for s in stuck if inb.get(s, 0) >= INBOUND_FLOOR)
    ok_s, n_pages, broken, schema_miss = schema_coverage()
    sites = site_checks()
    gaps = coverage_gaps()

    items = [
        ("記事の作り（21項目すべてPASS）", ok_a, n_a,
         "python scripts/auto_rewrite.py --write"),
        ("内部リンクが3本以上（全記事）", n_inb3, len(arts),
         "python scripts/link_boost.py <site> --write"),
        # 「12本以上」は達成率に数えない。うちのデータが支えていないため。
        # 実測（2026-09-23）では 1〜10位の記事の被リンク中央値が5本で、
        # 11〜30位で止まっている記事の9〜10本より少なかった。
        # ただし1〜10位は3本しかなく、これで逆だと結論するのも早い。
        # 根拠が無い基準を「保証する要因」に混ぜると、達成率の意味が壊れる
        ("構造化データが揃い、壊れていない", ok_s, n_pages,
         "python scripts/build.py"),
    ]
    for name, ok, det, how in sites:
        items.append((name, 1 if ok else 0, 1, how))
    for sid, empty, total, pri_empty, pri_total in gaps:
        # 全マスを埋めるのは目標であって基準ではない。優先業種だけを必須にする
        items.append((f"優先業種の盤面（{sid}）", pri_total - pri_empty, max(1, pri_total),
                      f"python scripts/coverage.py --site {sid} --gaps 10"))

    done = sum(x[1] for x in items)
    need = sum(x[2] for x in items)
    rate = done / need * 100 if need else 0

    if not a.todo:
        print("■ こちら側で決まる要因の達成率\n")
        print(f"{'要因':<34}{'達成':>10}{'率':>8}")
        for name, ok, tot, how in items:
            r = ok / tot * 100 if tot else 0
            mark = "○" if ok == tot else "×"
            print(f"{mark} {name[:32]:<32}{ok:>5}/{tot:<4}{r:>7.1f}%")
        print(f"\n  合計 {done}/{need}  達成率 {rate:.1f}%")
        print("\n  ※ 達成率100%は「上位表示される」ではありません。")
        print("     「順位を決める要因のうち、こちら側にあるものに抜けが無い」という意味です。")
        print("     順位・競合の動き・アルゴリズム更新・外部被リンクは、こちらでは決まりません。")

    short = [x for x in items if x[1] < x[2]]
    if short:
        print(f"\n■ 足りない分（{len(short)}項目）")
        for name, ok, tot, how in sorted(short, key=lambda x: (x[1] - x[2])):
            print(f"  {name}  あと{tot - ok}  →  {how}")
    if bad and not a.todo:
        print("\n■ 記事の作りで落ちている内訳")
        for k, v in sorted(bad.items(), key=lambda x: -len(x[1]))[:8]:
            print(f"  {len(v):>3}本  {k}")
            print(f"        例: {', '.join(v[:3])}")
    if not a.todo:
        print(chr(10) + f"  参考: 止まっている記事{len(stuck)}本のうち、内部リンク12本以上は"
              f"{n_stuck_ok}本。ただし12本という基準はうちのデータで裏づけが取れていません"
              "（1〜10位の中央値5本 < 11〜30位の9〜10本。ただし1〜10位はn=3）")

    if schema_miss and not a.todo:
        print(f"\n■ 構造化データが足りないページ（{len(schema_miss)}件）")
        for x in schema_miss[:6]:
            print(f"  {x}")
    if broken:
        print(f"\n  ::warning::壊れた構造化データが{broken}ページあります")

    print(f"GUARANTEE_RATE={rate:.1f}")
    print("GUARANTEE_OK=" + ("yes" if rate >= 99.5 else "no"))
    if rate < 99.5:
        print(f"   ::warning::こちら側で決まる要因の達成率が{rate:.1f}%です。"
              "100%になるまでは、やれることに抜けがあります")
    return 0


if __name__ == "__main__":
    sys.exit(main())
