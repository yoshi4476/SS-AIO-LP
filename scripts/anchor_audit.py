# -*- coding: utf-8 -*-
"""内部リンクのアンカーが、リンク先の狙う語を含んでいるかを検査する

検索エンジンは、そのページへ向けられたリンクの文言でページの主題を判断する。
「こちら」や記事タイトルの丸写しばかりだと、狙う語との結びつきが作られない。

実例: 「AIO診断」という完全一致のリンクが、記事ではなく診断ツールへ94本
向いていた。記事15.7位に対しツールが40.6位で並走し、どちらも伸びなかった。

ただし入れすぎは逆効果になる。同じ語のリンクを大量に貼ると、自然に集まった
リンクには見えない。1記事あたり1〜2本を目安にする。

使い方:
    python scripts/anchor_audit.py                 # 全体を見る
    python scripts/anchor_audit.py --fix           # 直す候補を出す（書き換えない）
    python scripts/anchor_audit.py --fix --write   # 実際に書き換える
"""
import glob
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "articles"

# この本数を超えて同じ語のアンカーを貼らない。増やすほど不自然になる
MAX_EXACT = 2
# 被リンクがこれ未満の記事は、まず本数を増やすほうが先
MIN_INBOUND = 3

LINK = re.compile(r"\[([^\]\[]+)\]\((?:https?://[^/)]+)?(/[a-z0-9-]+/([a-z0-9-]+)/)\)")
_NOISE = re.compile(r"[\s　・|｜:：\-—?？!！。、,.／/（）()【】\[\]]")


def norm(s):
    return _NOISE.sub("", str(s)).lower()


def front(text):
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    return m.group(1) if m else ""


def load():
    """記事ごとの狙う語と、受けているアンカーを集める"""
    arts = {}
    for f in sorted(glob.glob(str(ARTICLES / "*.md"))):
        p = Path(f)
        if p.name.startswith("_"):
            continue
        t = p.read_text(encoding="utf-8-sig")
        fm = front(t)
        kw = re.search(r"^keyword:\s*(.+)$", fm, re.M)
        ti = re.search(r"^title:\s*(.+)$", fm, re.M)
        arts[p.stem] = {
            "kw": kw.group(1).strip() if kw else "",
            "title": ti.group(1).strip() if ti else p.stem,
            "in": [],      # (リンク元slug, アンカー)
        }
    for f in sorted(glob.glob(str(ARTICLES / "*.md"))):
        src = Path(f)
        if src.name.startswith("_"):
            continue
        body = src.read_text(encoding="utf-8-sig")
        for anchor, _, slug in LINK.findall(body):
            if slug in arts and slug != src.stem:
                arts[slug]["in"].append((src.stem, anchor))
    return arts


def tokens(kw):
    """狙う語を単語に分ける。「AI導入補助金 申請 やり方」は3語の集合"""
    return [norm(x) for x in re.split(r"[\s　]+", str(kw)) if norm(x)]


def judge(a):
    """狙う語を含むアンカーの本数を返す。

    狙う語は空白区切りの検索語なので、連結した文字列では照合できない。
    全ての語がアンカーに含まれていれば、その語との結びつきは作れている。
    """
    if not a["kw"]:
        return None
    ts = tokens(a["kw"])
    if not ts:
        return None
    return sum(1 for _, x in a["in"] if all(t in norm(x) for t in ts))


def natural_anchor(kw, title):
    """狙う語を全部含む、読めるアンカーを作る。

    語をそのまま並べると日本語として壊れる（「〜よくあるのポイント」など）。
    タイトルが語を全部含んでいればタイトルを使い、含まないときだけ
    足りない語を前に添える。それでも作れない場合は None を返して見送る。
    """
    ts = tokens(kw)
    for cand in (re.split(r"[｜|]", title)[0].strip(), title.strip()):
        if cand and all(t in norm(cand) for t in ts) and len(cand) <= 34:
            return cand
    # タイトルで作れない場合は自動生成しない。狙う語を機械的につなぐと
    # 「よくあるのAI導入補助金の申請に失敗する〜」のような壊れた日本語になる。
    # 不自然なアンカーは読者に不信感を与え、順位にも効かない。
    return None


def main():
    arts = load()
    nokw = [s for s, a in arts.items() if not a["kw"]]
    zero, few, ok = [], [], []
    for s, a in arts.items():
        n = judge(a)
        if n is None:
            continue
        if not a["in"]:
            continue
        (zero if n == 0 else (few if n < MAX_EXACT else ok)).append((s, a, n))
    zero.sort(key=lambda x: -len(x[1]["in"]))

    print(f"■ 内部リンクのアンカー検査（{len(arts)}記事）")
    print(f"   狙う語を含むアンカーが0本   {len(zero):>3}本  ← ここが順位を抑えている")
    print(f"   1本だけ                    {len(few):>3}本")
    print(f"   2本以上（十分）             {len(ok):>3}本")
    if nokw:
        print(f"   keyword 未設定             {len(nokw):>3}本  {' '.join(nokw[:5])}")

    if "--fix" not in sys.argv:
        print("\n   直す候補を見るには --fix を付けてください")
        return

    write = "--write" in sys.argv
    print(f"\n■ 書き換え候補（被リンク{MIN_INBOUND}本以上）")
    done = 0
    for slug, a, _ in zero:
        if len(a["in"]) < MIN_INBOUND:
            continue
        # リンク元は、アンカーが一番あいまいなものから選ぶ
        cand = sorted(a["in"], key=lambda x: (norm(a["title"]) in norm(x[1]), len(x[1])))
        src, old = cand[0]
        new = natural_anchor(a["kw"], a["title"])
        if not new or norm(new) == norm(old):
            continue
        f = ARTICLES / (src + ".md")
        t = f.read_text(encoding="utf-8-sig")
        # 同じアンカーが複数あっても、1本だけ差し替える
        pat = re.compile(r"\[" + re.escape(old) + r"\]\((?:https?://[^/)]+)?(/[a-z0-9-]+/"
                         + re.escape(slug) + r"/)\)")
        m = pat.search(t)
        if not m:
            continue
        print(f"   {src[:28]:<30} 「{old[:26]}」→「{new[:26]}」")
        if write:
            f.write_text(t[:m.start()] + f"[{new}]({m.group(1)})" + t[m.end():],
                         encoding="utf-8", newline="")
        done += 1
    print(f"\n   {'書き換えました' if write else '候補'}: {done}本")
    if not write and done:
        print("   実行するには --write を付けてください")

    # タイトルから作れないものは、リンク元の文脈に合わせて手で書く。
    # 機械で語をつなぐと日本語が壊れ、読者の不信を招くだけで順位にも効かない
    rest = [(s, a) for s, a, _ in zero if not natural_anchor(a["kw"], a["title"])]
    if rest:
        print(f"\n■ 手で書く必要があるもの: {len(rest)}本")
        for s, a in rest:
            srcs = ", ".join(x[0] for x in a["in"][:3]) or "（被リンクなし）"
            print(f"   {s[:30]:<32}狙う語「{a['kw'][:22]}」")
            print(f"   {'':<32}リンク元: {srcs}")


if __name__ == "__main__":
    main()
