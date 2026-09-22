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
import auto_review as ar  # noqa: E402
import cannibal_check as cc  # noqa: E402
import link_new as ln  # noqa: E402

LINK = re.compile(r"\]\((?:https?://[^/)]+)?(/[a-z0-9-]+/([a-z0-9-]+)/)\)")
# しきい値。実測に合わせる。90日間で一度も検索結果に出ていない88本は
# 被リンクの平均が3.7〜4.6本、出ている記事は5.9〜8.8本だった。
# 2本以下だけを拾っていては、出ていない記事のほとんどに届かない。
LOW = 5
ADD_PER = 2      # 1記事につき足す本数。増やしすぎると不自然になる
# --rescue: 順位で止まっている記事を優先する経路。被リンク5本以下という条件では
# 拾えなかった。実測（2026-09-22）で11〜30位に止まる27本の被リンクは2〜18本で、
# LOW=5 に該当したのは3本だけだった。順位が近いほど1本の効きが大きいので、
# 「少ない順」ではなく「1ページ目に近く表示が多い順」に配る
RESCUE_FLOOR = 12
RESCUE_ADD = 3   # 1回で足す上限。週次で回るうちに下限へ寄せる（8.6の振動防止と同じ考え）
NL_CH = chr(10)
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
    """記事を代表する語。タイトルと狙う語から拾う

    タイトルだけを記号で割ると「専門知識ゼロで始める5つの方法」のような
    長い塊になり、他の記事に丸ごと現れない。狙う語は空白区切りなので、
    そこからも語を取り、短い語まで拾えるようにする。
    """
    sep = r"[\s　｜|・、。（）()【】\[\]？?！!]+"
    out = {w for w in re.split(sep, a["title"]) if len(w) >= 3}
    out |= {w for w in re.split(sep, a["kw"]) if len(w) >= 2}
    return out


def distinctive(a):
    """その記事を言い当てる語。これが無い記事からは送らない

    タイトルの断片は「AIO対策との違いと5種類の対応ポイント」のように長く、
    他の記事に丸ごと現れない。これを必須にすると候補がゼロになる。
    狙う語は空白区切りの短い語なので、そちらから取る。
    """
    sep = r"[\s　｜|・、。（）()【】\[\]？?！!]+"
    return {w for w in re.split(sep, a["kw"]) if len(w) >= 3}


# リンクだけで成り立つ段落。ここに重ねるとリンク集になり、読者もAIも読み飛ばす
LINK_PARA = re.compile(r"^(?:関連して、|関連する内容を|近い論点を|あわせて読む)[^\n]*\]\([^\n]*$", re.M)


def pick_spot(body, target_words):
    """置く位置を決める。H2の1文結論の直後で、話題が合うところ

    同じ区画に二重で置かない。リンクが並ぶとリンク集になり、
    読者は読み飛ばし、AIも文脈ごと拾えなくなる。
    """
    blocks = list(re.finditer(r"^## .+$", body, re.M))
    best = None
    for i, m in enumerate(blocks):
        end = blocks[i + 1].start() if i + 1 < len(blocks) else len(body)
        seg = body[m.start():end]
        head = m.group(0)
        # まとめ・FAQ・よくある質問には置かない。読者が読み終えた後になる
        if re.search(r"まとめ|よくある質問|FAQ", head):
            continue
        # すでにリンクだけの段落がある区画は避ける（積み上がりの防止）
        if LINK_PARA.search(seg):
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


def rescue_targets(site, arts, cnt):
    """11〜30位で止まり、被リンクが下限に届いていない記事を、効く順に返す"""
    import rank_rescue as RR
    rows, _ = RR.diagnose()
    out = []
    for r in rows:
        if r["site"] != site or r["slug"] not in arts:
            continue
        if cnt.get(r["slug"], 0) >= RESCUE_FLOOR:
            continue
        out.append((r["slug"], r["pos"], r["imp"], cnt.get(r["slug"], 0)))
    out.sort(key=lambda x: -(x[2] * max(0.0, 31 - x[1])))
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit("使い方: python scripts/link_boost.py <site_id> [--write]")
    site = args[0]
    write = "--write" in sys.argv
    rescue = "--rescue" in sys.argv
    arts = load(site)
    if not arts:
        raise SystemExit(f"{site} の記事が見つかりません")
    cnt = inbound(arts)
    if rescue:
        tg = rescue_targets(site, arts, cnt)
        poor = [s for s, _, _, _ in tg]
        print(f"■ {site}: 11〜30位で止まり、被リンクが{RESCUE_FLOOR}本未満 {len(poor)}記事")
        for s, pos, imp, n in tg:
            print(f"     {pos:>5.1f}位 表示{imp:>4}  被リンク{n:>3}本  {arts[s]['title'][:34]}")
    else:
        poor = [s for s, n in cnt.items() if n <= LOW]
        poor.sort(key=lambda s: cnt[s])
        print(f"■ {site}: {len(arts)}記事 / 被リンク{LOW}本以下 {len(poor)}記事")

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
            # 短い語だけの一致は話題が近いとは限らない。言い当てる語を必ず含める
            key = distinctive(a)
            if hit >= 2 and (not key or any(w in b["body"] for w in key)):
                cands.append((hit, cnt[src], src))
        # 話題が近く、かつ自身の被リンクが多い記事から送る（力のある記事から送る）
        cands.sort(key=lambda x: (-x[0], -x[1]))
        added = 0
        cap = RESCUE_ADD if rescue else ADD_PER
        for hit, _, src in cands:
            if added >= cap:
                break
            b = arts[src]
            pos = pick_spot(b["body"], tw)
            if pos is None:
                continue
            url = f"/blog/{tgt}/" if site != "ai-lab" else f"/{a['cat']}/{tgt}/"
            # 言い回しは link_new の型から選ぶ。ここで自前の一文を書くと、
            # 同じ文がサイト中に並ぶ。実測で1つの型が全体の41.5%を占めた
            h2 = ar.h2_before(b["body"], pos)
            fit = cc.dice(ln.topic(h2), ln.topic(a["title"])) if h2 else 0.0
            line = "\n" + ln.sentence(a["title"], url,
                                      abs(hash(src + tgt)) % 8, fit) + "\n"
            print(f"   {tgt[:34]:<36}← {src[:32]}")
            if write:
                # 前後に必ず空行を1つ作る。直結すると次の塊（表・箇条書き・見出し）が
                # 段落の続きとして扱われ、表がパイプ記号のまま本文に出る
                # （CLAUDE.md の装飾ルール。実測62箇所。ここでも3箇所やってしまった）
                nb = (b["body"][:pos].rstrip(NL_CH) + NL_CH * 2
                      + line.strip() + NL_CH * 2 + b["body"][pos:].lstrip(NL_CH))
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
