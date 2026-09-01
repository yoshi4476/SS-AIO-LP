# -*- coding: utf-8 -*-
"""被リンクが少ない記事へ、話題の合う記事からリンクを足す

内部リンクは人気記事に集まりやすく、放っておくと差が開く。実測では
1記事に最小1本・最大40本まで開いていた。リンクが少ない記事は、
順位が1ページ目の手前で止まりやすい。

記事を新しく書かずに順位を動かせる、最も手間のかからない打ち手。

置く場所を機械が決めると、まとめやFAQの中に入って読者に読まれない。
H2の1文結論の直後に置く。読者が次を知りたくなる位置と一致し、
AI検索にも文脈ごと読まれる。

使い方:
    python scripts/link_boost.py <site_id>            # 候補を出す
    python scripts/link_boost.py <site_id> --write    # 実際に足す
"""
import glob
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "articles"
sys.path.insert(0, str(ROOT / "scripts"))

LINK = re.compile(r"\]\((?:https?://[^/)]+)?(/[a-z0-9-]+/([a-z0-9-]+)/)\)")
LOW = 2          # これ以下を「孤立ぎみ」とする
ADD_PER = 2      # 1記事につき足す本数。増やしすぎると不自然になる
_NOISE = re.compile(r"[\s　・|｜:：\-—?？!！。、,.／/（）()【】\[\]]")


def norm(s):
    return _NOISE.sub("", str(s)).lower()


def load(site_id):
    import sites as S
    arts = {}
    for f in sorted(glob.glob(str(ARTICLES / "*.md"))):
        p = Path(f)
        if p.name.startswith("_"):
            continue
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
        if not m:
            continue
        fm, body = m.group(1), m.group(2)
        cat = re.search(r"^category:\s*(\S+)", fm, re.M)
        if not cat or S.find_category_owner(cat.group(1)) != site_id:
            continue
        ti = re.search(r"^title:\s*(.+)$", fm, re.M)
        kw = re.search(r"^keyword:\s*(.+)$", fm, re.M)
        arts[p.stem] = {"path": p, "title": ti.group(1).strip() if ti else p.stem,
                        "kw": kw.group(1).strip() if kw else "",
                        "cat": cat.group(1), "body": body}
    return arts


def inbound(arts):
    c = Counter()
    for f in sorted(glob.glob(str(ARTICLES / "*.md"))):
        for _, slug in LINK.findall(Path(f).read_text(encoding="utf-8-sig")):
            if slug in arts:
                c[slug] += 1
    for s in arts:
        c.setdefault(s, 0)
    return c


def words(a):
    """記事を代表する語。タイトルと狙う語から拾う"""
    src = a["title"] + " " + a["kw"]
    return {w for w in re.split(r"[\s　｜|・、。（）()【】\[\]？?！!]+", src)
            if len(w) >= 3}


def pick_spot(body, target_words):
    """置く位置を決める。H2の1文結論の直後で、話題が合うところ"""
    blocks = list(re.finditer(r"^## .+$", body, re.M))
    best = None
    for i, m in enumerate(blocks):
        end = blocks[i + 1].start() if i + 1 < len(blocks) else len(body)
        seg = body[m.start():end]
        head = m.group(0)
        # まとめ・FAQ・よくある質問には置かない。読者が読み終えた後になる
        if re.search(r"まとめ|よくある質問|FAQ", head):
            continue
        hit = sum(1 for w in target_words if w in seg)
        if hit == 0:
            continue
        # H2直下の1文結論の終わりを探す
        after = body[m.end():end]
        para = re.search(r"\n\n", after.lstrip("\n"))
        pos = m.end() + (para.end() if para else 0) + (len(after) - len(after.lstrip("\n")))
        if best is None or hit > best[0]:
            best = (hit, pos)
    return best[1] if best else None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit("使い方: python scripts/link_boost.py <site_id> [--write]")
    site = args[0]
    write = "--write" in sys.argv
    arts = load(site)
    if not arts:
        raise SystemExit(f"{site} の記事が見つかりません")
    cnt = inbound(arts)
    poor = [s for s, n in cnt.items() if n <= LOW]
    poor.sort(key=lambda s: cnt[s])
    print(f"■ {site}: {len(arts)}記事 / 被リンク{LOW}本以下 {len(poor)}記事\n")

    done = 0
    for tgt in poor:
        a = arts[tgt]
        tw = words(a)
        # 送り元候補: 同じ話題に触れていて、まだリンクしていない記事
        cands = []
        for src, b in arts.items():
            if src == tgt or f"/{tgt}/" in b["body"]:
                continue
            hit = sum(1 for w in tw if w in b["body"])
            if hit >= 2:
                cands.append((hit, cnt[src], src))
        # 話題が近く、かつ自身の被リンクが多い記事から送る（力のある記事から送る）
        cands.sort(key=lambda x: (-x[0], -x[1]))
        added = 0
        for hit, _, src in cands:
            if added >= ADD_PER:
                break
            b = arts[src]
            pos = pick_spot(b["body"], tw)
            if pos is None:
                continue
            url = f"/blog/{tgt}/" if site != "ai-lab" else f"/{a['cat']}/{tgt}/"
            line = (f"\n関連して、[{a['title']}]({url})もあわせてご確認ください。\n")
            print(f"   {tgt[:34]:<36}← {src[:32]}")
            if write:
                nb = b["body"][:pos] + line + b["body"][pos:]
                t = b["path"].read_text(encoding="utf-8-sig")
                head = t.split("---", 2)[1]
                b["path"].write_text(f"---{head}---\n{nb}", encoding="utf-8", newline="")
                arts[src]["body"] = nb
            added += 1
            done += 1
    print(f"\n   {'追加しました' if write else '候補'}: {done}本")
    if not write:
        print("   実行するには --write を付けてください")


if __name__ == "__main__":
    main()
