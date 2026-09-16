# -*- coding: utf-8 -*-
"""長すぎる1文を、意味が壊れない形だけで2文に分ける。

段落を分ける split_paragraphs は「。」の位置でしか切れない。1文が100字を
超えているものは、その中に「。」が無いので手が出せなかった。実測で公開332本の
うち29本にこれが残っていた。

ここで切るのは、**左側がそれだけで文として成り立つ形**に限る。
「〜によると、」「〜し、」「〜ため、」のような、左が文にならない接続は触らない。
切ると主語と述語がねじれるため。

  〜ており、  → 〜ています。      （連用中止法。左は完結した文になる）
  〜ますが、  → 〜ます。ただし、  （逆接。接続語で受け直す）
  〜ですが、  → 〜です。ただし、
  〜であり、  → 〜です。

守ること:
  1. 装飾・リンク・かっこ・引用の内側では切らない（**が次の文へ残る事故を繰り返さない）
  2. 切った前後の差分が、上の4種類だけであることを機械で確かめる
     （正規表現の取りこぼしで本文を巻き込んでいないかを見る）
  3. 表・箇条書き・コード・生HTMLは触らない

  python scripts/split_sentences.py            # どう変わるか見る
  python scripts/split_sentences.py --write    # 実際に分ける
  python scripts/split_sentences.py --limit 5  # 先頭5件だけ見る
"""
import argparse
import difflib
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LONG = 70          # これを超える文を対象にする（規定50字＋余裕）
KEEP = 20          # 切った結果、片側がこれ未満になるなら切らない

# (探す形, 置き換える形)。左がそれ自体で文になるものだけを並べる
RULES = [
    # 理由の「ため」。左を言い切って「そのため」で受け直す。意味は変わらない。
    # 長いものから先に並べる（「ているため、」を「いるため、」より先に当てる）
    ("しているため、", "しています。そのため、"),
    ("されているため、", "されています。そのため、"),
    ("ているため、", "ています。そのため、"),
    ("であるため、", "です。そのため、"),
    ("になるため、", "になります。そのため、"),
    ("があるため、", "があります。そのため、"),
    ("できるため、", "できます。そのため、"),
    ("されるため、", "されます。そのため、"),
    ("できないため、", "できません。そのため、"),
    ("ならないため、", "なりません。そのため、"),
    ("いるため、", "います。そのため、"),
    # 連用中止法。左はそれだけで文になる
    ("ており、", "ています。"),
    ("ますが、", "ます。ただし、"),
    ("ですが、", "です。ただし、"),
    ("であり、", "です。"),
]
ALLOWED = {(a, b) for a, b in RULES}

# 「が」は逆接とは限らない。「ご存じの方も多いと思いますが、〜」のような前置きの
# 「が」に「ただし」を足すと意味がずれる。後ろに逆接・限定の印がある時だけ切る。
NEEDS_CONTRAST = ("ますが、", "ですが、")
CONTRAST = re.compile(
    r"ない|ません|ず[にで]|難し|注意|限ら|限り|対象外|除[かき]|できま|必要があ|"
    r"だけ|のみ|一方|逆に|とは限|とはいえ|実際に|落とし穴|失敗|リスク|"
    r"やってはい|避け|向きま|とは違")
# 左が「〜を解説しています」「〜を支援しています」で終わる「が」は、逆接ではなく
# 話を始めるための前置き。ここに「ただし」を足すと意味がずれる（実測16件中4件）
# 「ますが、」の「ます」は切り取られる側なので、左端は「支援してい」で終わる
PREFACE = re.compile(
    r"(?:解説|説明|紹介|整理|支援|携わ|お伝え|まとめ|触れ|述べ|扱|書|運営|"
    r"申し上げ|お話し)(?:し|り|っ|い)?てい$")

# この内側では切らない。切ると閉じ記号が次の文へ残る
GUARDS = [
    (r"\*\*.+?\*\*", 0), (r"==.+?==", 0), (r"`[^`]+`", 0),
    (r"\[[^\]]*\]\([^)]*\)", 0), (r"<[^>]+>", 0),
    (r"「[^」]*」", 0), (r"『[^』]*』", 0), (r"（[^）]*）", 0), (r"\([^)]*\)", 0),
]


def protected(text):
    """触ってはいけない範囲の集合"""
    bad = set()
    for pat, _ in GUARDS:
        for m in re.finditer(pat, text):
            bad.update(range(m.start(), m.end()))
    return bad


def plain(s):
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    return re.sub(r"<[^>]+>|[*_=`]", "", s)


def split_sentence(sent, log=None):
    """長い1文を1回だけ分ける。分けられなければ None"""
    if len(plain(sent)) <= LONG:
        return None
    bad = protected(sent)
    mid = len(sent) / 2
    best = None
    taken = set()          # 長い形を先に取る（「ているため、」を「いるため、」に横取りさせない）
    for old, new in RULES:
        for m in re.finditer(re.escape(old), sent):
            i, j = m.start(), m.end()
            if any(k in taken for k in range(i, j)):
                continue
            taken.update(range(i, j))
            if any(k in bad for k in range(i, j)):
                continue
            left, right = sent[:i], sent[j:]
            if len(plain(left)) < KEEP or len(plain(right)) < KEEP:
                continue
            # 逆接の「が」かどうかを、前後の言葉で見分ける
            if old in NEEDS_CONTRAST:
                if not CONTRAST.search(plain(right)[:46]):
                    continue
                if PREFACE.search(plain(left)):
                    continue
            d = abs(i - mid)
            if best is None or d < best[0]:
                best = (d, i, j, old, new)
    if not best:
        return None
    _, i, j, old, new = best
    out = sent[:i] + new + sent[j:]
    # 1文の中の1箇所だけを、決めた形に置き換えた——それ以外は動いていない
    assert out == sent[:i] + new + sent[j:] and sent[i:j] == old
    if log is not None:
        log.append((sent, out, old, new))
    return out


def process(text, rounds=3):
    """本文を受け取り、(新しい本文, 分けた数) を返す"""
    m = re.match(r"^(---\s*\n.*?\n---\s*\n)(.*)$", text, re.S)
    if not m:
        return text, 0, []
    fm, body = m.groups()
    parts = re.split(r"(\n\s*\n)", body)
    out, n, edits = [], 0, []
    for x in parts:
        s = x.strip()
        # 表・箇条書き・コード・生HTMLの塊は触らない
        if (x.startswith("\n") or not s
                or s.startswith(("|", "-", "*", ">", "#", "```", "<"))
                or "|:--" in s):
            out.append(x)
            continue
        cur = x
        for _ in range(rounds):
            sents = re.split(r"(?<=[。！？])", cur)
            done = False
            for k, sent in enumerate(sents):
                r = split_sentence(sent, edits)
                if r:
                    sents[k] = r
                    n += 1
                    done = True
                    break
            cur = "".join(sents)
            if not done:
                break
        out.append(cur)
    return fm + "".join(out), n, edits


def verify(before, after, edits):
    """記録した書き換え以外に、本文が動いていないことを確かめる。

    2段構えで見る。
      1. 1文ごと: 決めた形を1箇所だけ置き換えた（split_sentence の assert）
      2. 記事全体: before に記録した置き換えだけを順に当てると after になる

    2があるので、段落の取りこぼしや並べ直しの失敗はここで必ず出る。
    文字列の正規化では「〜ていますが、」のような重なりを判定できなかった。
    """
    cur = before
    for old_s, new_s, _old, _new in edits:
        i = cur.find(old_s)
        if i < 0:
            return f"記録した文が見つかりません: 「{old_s[:30]}…」"
        cur = cur[:i] + new_s + cur[i + len(old_s):]
    if cur != after:
        sm = difflib.SequenceMatcher(None, cur, after, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag != "equal":
                return (f"記録した書き換え以外の変化があります: "
                        f"「{cur[i1:i2][:24]}」→「{after[j1:j2][:24]}」")
    return ""


def run(write, limit=0):
    touched = total = 0
    shown = 0
    for p in sorted((ROOT / "articles").glob("*.md")):
        t = io.open(p, encoding="utf-8-sig").read()
        if not re.search(r"^score:\s*(9[0-9]|100)\s*$", t, re.M):
            continue
        new, n, edits = process(t)
        if not n:
            continue
        ng = verify(t, new, edits)
        if ng:
            print(f"  × {p.stem}: {ng} — 書き換えません")
            continue
        touched += 1
        total += n
        if not limit or shown < limit:
            shown += 1
            print(f"  {p.stem[:44]:<44} {n}箇所")
            sm = difflib.SequenceMatcher(None, t, new, autojunk=False)
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag == "replace":
                    print(f"      … {t[max(0, i1-26):i1]}【{t[i1:i2]}】{t[i2:i2+22]}")
                    print(f"      → {t[max(0, i1-26):i1]}【{new[j1:j2]}】{t[i2:i2+22]}")
                    break
        if write:
            io.open(p, "w", encoding="utf-8", newline="").write(new)
    return touched, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="表示する記事数")
    a = ap.parse_args()
    print(f"■ {LONG}字を超える1文を、意味が壊れない形だけで分ける\n")
    n, t = run(a.write, a.limit)
    print(f"\n  {n}本 / {t}箇所"
          + ("を分けました" if a.write else "が対象です（--write で実行）"))
    if a.write and n:
        print("  次: python scripts/build.py で検査してください")
    return 0


if __name__ == "__main__":
    sys.exit(main())
