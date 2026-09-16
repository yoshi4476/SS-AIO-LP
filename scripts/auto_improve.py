# -*- coding: utf-8 -*-
"""効果測定から出た「やること」のうち、機械で直せるものを自動で当てる。

人が毎週判断すると、判断の基準がその日の気分で変わり、何が効いたのかを
後から検証できなくなる。条件で決まるものは機械に任せる。

自動で直すのは内部リンクだけにしている。表示は出ているのに順位が
足りない記事へ、関連記事からリンクを送る。これは足しても記事の主張が
変わらず、間違っても害が小さい。

タイトルの書き換えと、検索意図の見直しは自動化しない。文章の判断が要り、
機械が当てると主張のずれた記事が量産される。こちらは指示だけ出す。

  python scripts/auto_improve.py            # 何をするかだけ出す
  python scripts/auto_improve.py --write    # 実際に当てる
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
MAX_PER_RUN = 12          # 一度に触る本数。多いと何が効いたか分からなくなる


def inbound(slug, texts):
    n = 0
    for s, t in texts.items():
        if s == slug:
            continue
        if re.search(r"\]\([^)]*/%s/?[)#]" % re.escape(slug), t):
            n += 1
    return n


def add_links(slug, texts, want=3, write=False):
    """その記事へ、話題の近い記事からリンクを送る"""
    target = texts.get(slug, "")
    if not target:
        return 0, []
    ttl = (re.search(r"^title:\s*(.+)$", target, re.M) or [0, ""])[1].strip()
    kw = (re.search(r"^keyword:\s*(.+)$", target, re.M) or [0, ""])[1].strip()
    cat = (re.search(r"^category:\s*(.+)$", target, re.M) or [0, ""])[1].strip()
    words = [w for w in re.split(r"[\s　]+", kw) if len(w) >= 2]
    if not words:
        return 0, []
    url = None
    try:
        import sites as sites_mod
        site = sites_mod.find_category_owner(cat)
        cfg = sites_mod.load(site)
        url = sites_mod.article_url(cfg, {"slug": slug, "category": cat})
    except Exception:
        pass
    if not url:
        return 0, []
    # 同じサイトで、狙う語に触れていて、まだリンクしていない記事
    cands = []
    for s, t in texts.items():
        if s == slug or slug in t:
            continue
        c2 = (re.search(r"^category:\s*(.+)$", t, re.M) or [0, ""])[1].strip()
        try:
            if sites_mod.find_category_owner(c2) != site:
                continue
        except Exception:
            continue
        body = t.split("---", 2)[-1]
        hits = sum(1 for w in words if w in body)
        if hits >= max(1, len(words) - 1):
            cands.append((hits, len(body), s))
    cands.sort(reverse=True)
    import auto_review as ar
    import cannibal_check as cc
    import link_new as ln
    done = []
    for _, _, s in cands[:want]:
        t = texts[s]
        m = list(re.finditer(r"^## .+$", t, re.M))
        if len(m) < 3:
            continue
        pos = m[len(m) // 2].start()          # 中ほどの見出しの前に置く
        # 言い回しは link_new の型から選ぶ。自前の一文をここで書くと、
        # 同じ文がサイト中に並ぶ。実測で1つの型が全体の41.5%を占めた
        h2 = ar.h2_before(t, pos)
        fit = cc.dice(ln.topic(h2), ln.topic(ttl)) if h2 else 0.0
        line = ln.sentence(ttl, url, abs(hash(s + slug)) % 8, fit)
        if write:
            p = ROOT / "articles" / f"{s}.md"
            p.write_text(t[:pos] + line + "\n\n" + t[pos:],
                         encoding="utf-8", newline="")
            texts[s] = p.read_text(encoding="utf-8")
            record("auto_improve", s, "%s へ内部リンク（%s）" % (slug, line[:24]))
        done.append(s)
    return len(done), done


LOG = ROOT / "automation" / "logs" / "auto_fix.jsonl"


def record(by, slug, what):
    """当てた修正を1行ずつ残す。後から何をしたか追えないと見直せない"""
    import datetime
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8", newline="") as f:
        f.write(json.dumps({"when": datetime.datetime.now().isoformat(),
                            "by": by, "slug": slug, "what": what},
                           ensure_ascii=False) + "\n")


def human_items(days=28, until=None):
    """文章の判断が要るものを、全件そのまま返す。

    画面に出すときは8件で打ち切っているため、出力を読み取る側が
    残りを取りこぼしていた（27件のうち8件しか拾えていなかった）。
    """
    import effect
    acts = effect.actions(effect.collect(days, until))
    return [{"kind": x["do"], "slug": x["slug"], "why": x["why"], "how": x["how"]}
            for x in acts if x["do"] in ("title", "review")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--until", default="")
    a = ap.parse_args()

    import effect
    rows = effect.collect(a.days, a.until or None)
    acts = effect.actions(rows)
    by = {}
    for x in acts:
        by.setdefault(x["do"], []).append(x)

    print("■ 効果測定から出たやること: %d件" % len(acts))
    for k, label in (("links", "内部リンクを足す（自動）"),
                     ("title", "タイトルを直す（人が判断）"),
                     ("review", "検索意図を見直す（人が判断）")):
        print("   %-22s %d件" % (label, len(by.get(k, []))))

    texts = {p.stem: p.read_text(encoding="utf-8", errors="replace")
             for p in (ROOT / "articles").glob("*.md")}
    print("\n■ 内部リンクの補充")
    total = 0
    for x in by.get("links", [])[:MAX_PER_RUN]:
        now = inbound(x["slug"], texts)
        n, done = add_links(x["slug"], texts, want=max(0, 6 - now), write=a.write)
        total += n
        print("   %-34s 被リンク%d本 → %s%d本 %s"
              % (x["slug"][:34], now, "+" if n else "", n,
                 "（" + ", ".join(s[:18] for s in done) + "）" if done else "候補なし"))
    print("   %s %d本にリンクを足しました" % ("" if a.write else "（確認のみ）", total))

    hand = by.get("title", []) + by.get("review", [])
    if hand:
        print("\n■ 人が判断すること（自動では直しません）")
        for x in hand[:8]:
            print("   [%s] %-32s %s" % (x["do"], x["slug"][:32], x["why"]))
            print("        → %s" % x["how"])
        if len(hand) > 8:
            print("   …ほか%d件" % (len(hand) - 8))
    if not a.write:
        print("\n  --write を付けると内部リンクを実際に足します")
        return 0

    # 当てたら必ず見直す。1本ずつは正しくても、積み上がると記事が壊れる。
    # 見直しを人の判断に委ねると、忙しい週に飛ばされて溜まっていく
    print()
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "auto_review.py"),
                        "--fix"], cwd=ROOT, text=True, encoding="utf-8",
                       errors="ignore")
    if r.returncode != 0:
        print("\n  見直しで止まりました。git checkout -- articles/ で戻せます")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
