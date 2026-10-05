# -*- coding: utf-8 -*-
"""短すぎる説明文（description）を、記事自身の文で100〜150字に足す。

Bing Webmaster Tools が AI集客ラボの54ページを「メタ説明が短すぎる」と指摘した
（2026-10-05。手元の集計では noindex を除く231ページのうち98ページが100字未満）。
日本語は1字の情報量が多く、Google の表示も120字前後で切れるため、目標は100〜150字に置く
（Bing の150〜160字は英語の目安）。

足すのは、その記事の冒頭の断言段落と、最初のH2直下の1文結論にある文そのものだけ。
新しい内容・数字は作らない（AIに書かせると事実と違う説明文が検索結果に出る）。
文の途中では切らない。足せる文で100字に届かない記事は触らずに一覧に出す。

  python scripts/desc_fill.py                 # 何をどう足すかを見る（--dry と同じ）
  python scripts/desc_fill.py --write         # 原稿の description を書き換え、台帳に残す
  python scripts/desc_fill.py --site subsidy  # サイトを絞る
  python scripts/desc_fill.py --audit <dir>   # 生成済みHTMLの説明文の字数を数える（noindex を除く）
"""
import argparse
import collections
import html
import io
import json
import re
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

ARTICLES = ROOT / "articles"
LOG = ROOT / "automation" / "logs" / "auto_fix.jsonl"
MIN, MAX = 100, 150
GATE_MAX = 160          # build・score_check・seo_audit の門の上限。目標の150字はこれより内側に置く

# 前の文を受けて初めて意味が通る書き出し。説明文だけを読んだ人には何を指すか分からない
DEPENDENT = re.compile(r"^(これ|それ|この|その|こう|そう|ここ|そこ|あれ|また|さらに|一方|つまり|なお|ただし|しかし|"
                       r"そして|ですから|だから|本記事|以下|下記|次の|上記|前述|後述|前者|後者|いずれ|どちら|両者|多くは)")
# 記事の案内文（「〜を解説します」「〜へリンクしています」）と問いかけだけの文。説明文の末尾に既に
# 「〜を解説します」があり、2つ並ぶと中身が増えないまま字数だけが増える
META = re.compile(r"(解説|紹介|整理|まとめ|お伝え)(します|しました|しています|ています)。$|リンクしています|か。$")
# 説明文の1文とこれ以上似た文は「同じことの言い直し」として足さない（冒頭の断言は説明文の1文目と同じ主張が多い）
SAME = 0.4
NUM = re.compile(r"\d[\d,，.．]*")


def plain(md):
    """Markdown・HTMLの記法を外し、読者に見える文字だけにする"""
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("**", "").replace("==", "")
    t = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])", r"\1", t)
    # 改行は段落の折り返しなので詰める。英字の間の空白（「AIO SEO」）は残す
    t = re.sub(r"\s*\n\s*", "", html.unescape(t))
    return re.sub(r"[ \t　]+", " ", t).strip()


def sentences(text):
    """「。」「！」「？」で文に分ける。かっこの中の句点では切らない"""
    out, buf, depth = [], "", 0
    for ch in text:
        buf += ch
        if ch in "「（(『":
            depth += 1
        elif ch in "」）)』":
            depth = max(0, depth - 1)
        elif ch in "。！？" and depth == 0:
            out.append(buf.strip())
            buf = ""
    return out     # 句点で終わらない残り（buf）は文の途中なので捨てる


def split(text):
    m = re.match(r"^(---\s*\n)(.*?)(\n---\s*\n)(.*)$", text, re.S)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3), m.group(4)


def paragraphs(body):
    return [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]


def is_prose(p):
    return not p.startswith(("<", "|", "-", "*", "#", "!", ">", "```", "1.")) or p.startswith("**")


def sources(body):
    """足してよい文の候補（出どころつき）。冒頭の断言段落の文 → 最初のH2の1文結論の順"""
    paras = paragraphs(body)
    out = []
    lead = next((p for p in paras if is_prose(p) and not p.startswith("#")), "")
    if lead and not lead.startswith("##"):
        out += [("冒頭", s) for s in sentences(plain(lead))]
    # 2本目以降のH2の1文結論は、冒頭と最初のH2では150字に収まらないときの控え。
    # どれも「切り出しても意味が通る」ように書く決まり（第6章）の文なので、単独で読める
    heads = list(re.finditer(r"^## .+$", body, re.M))
    for k, m in enumerate(heads):
        end = heads[k + 1].start() if k + 1 < len(heads) else len(body)
        first = next((p for p in paragraphs(body[m.end():end]) if is_prose(p) and not p.startswith("#")), "")
        got = sentences(plain(first))
        if got:
            out.append(("H2結論" if k == 0 else f"H2結論{k + 1}", got[0]))
    return out


def dice(a, b):
    A = {a[i:i + 2] for i in range(len(a) - 1)}
    B = {b[i:i + 2] for i in range(len(b) - 1)}
    return 2 * len(A & B) / (len(A) + len(B)) if A and B else 0.0


def fill(desc, body, lo=MIN, hi=MAX):
    """(新しい説明文, 足した文の一覧, 届かなかった理由)。足す必要が無ければ説明文はそのまま"""
    desc = str(desc or "").strip()
    if len(desc) >= lo:
        return desc, [], ""
    if not desc.endswith(("。", "！", "？")):
        return desc, [], "説明文が文の途中で終わっている"
    new, added = desc, []
    for src, s in sources(body):
        if len(new) >= lo:
            break
        if DEPENDENT.match(s) or META.search(s) or len(s) < 12 or "http" in s:
            continue
        # 説明文に既に同じことが書いてある文は足さない（同じ文が2度並ぶ）
        if any(dice(s, d) >= SAME for d in sentences(desc)) or any(dice(s, a) >= SAME for _, a in added):
            continue
        if len(new) + len(s) > hi:
            continue
        new += s
        added.append((src, s))
    if len(new) < lo:
        return desc, [], f"足せる文で{lo}字に届かない（{len(new)}字）"
    return new, added, ""


def clip(desc, hi=MAX):
    """hi 字を超える説明文は、hi 字以内の最後の句点で切る（文の途中では切らない）"""
    desc = re.sub(r"\s+", " ", str(desc or "")).strip()
    if len(desc) <= hi:
        return desc
    cut = max(desc[:hi].rfind(c) for c in "。！？")
    return desc[:cut + 1] if cut >= 0 else desc[:hi]     # 短くなった分は extend が中身の文で足す


def extend(base, extras, lo=MIN, hi=MAX):
    """一覧・ハブの説明文を lo 字まで足す。extras はそのページの中身（本数・業種・問い）から作った文。
    hi 字に収まる文だけを順に足し、lo 字に届いたら止める。
    要素を list/tuple にすると「言い換えの候補」で、収まる最初の1つだけを使う
    （「主な質問は〜」を3問版・1問版で渡し、同じ型の文が2つ並ばないようにする）"""
    out = clip(base, hi)
    for alts in extras:
        if len(out) >= lo:
            break
        if out and not out.endswith(("。", "！", "？")):
            out += "。"
        for s in (alts if isinstance(alts, (list, tuple)) else [alts]):
            s = re.sub(r"\s+", " ", str(s or "")).strip()
            if s and s not in out and len(out) + len(s) <= hi:
                out += s
                break
    return out


def named(head, names, tail, most=3):
    """「主な質問は「A」「B」です。」の言い換え候補（多い順）。extend にそのまま渡す"""
    names = [n for n in dict.fromkeys(str(x).strip() for x in names) if n][:most]
    return ["%s%s%s" % (head, "".join(f"「{n}」" for n in names[:k]), tail) for k in range(len(names), 0, -1)]


def verify(old, new, body, added, lo=MIN, hi=MAX):
    """機械が足した説明文を機械が検算する。1つでも外れたら書かない"""
    pb = plain(body)
    if not new.startswith(old):
        return "元の説明文が残っていない"
    for _, s in added:
        if s not in pb:
            return f"本文に無い文: {s[:20]}"
    if new[len(old):] != "".join(s for _, s in added):
        return "足した文以外の文字が入った"
    if not lo <= len(new) <= hi:
        return f"{len(new)}字（{lo}〜{hi}字）"
    if not new.endswith(("。", "！", "？")):
        return "文の途中で終わっている"
    have = set(NUM.findall(old)) | set(NUM.findall(pb))
    extra = [n for n in NUM.findall(new) if n not in have]
    if extra:
        return f"本文に無い数字: {extra[:3]}"
    return ""


def yaml_scalar(v):
    """1行の YAML 値。そのまま書いて読み戻せないもの（「: 」を含む等）は引用符で包む"""
    try:
        if yaml.safe_load(f"k: {v}") == {"k": v}:
            return v
    except yaml.YAMLError:
        pass
    return json.dumps(v, ensure_ascii=False)


def set_description(text, new):
    parts = split(text)
    head = parts[1]
    lines = head.split("\n")
    i = next(i for i, l in enumerate(lines) if l.startswith("description:"))
    j = i + 1                       # 折り返した値（>- や続き行）も1行に置き換える
    while j < len(lines) and lines[j].startswith((" ", "\t")):
        j += 1
    lines[i:j] = [f"description: {yaml_scalar(new)}"]
    return parts[0] + "\n".join(lines) + parts[2] + parts[3]


def plan(site=None, slug=None, lo=MIN, hi=MAX):
    import sites as S
    rows = []
    for p in sorted(ARTICLES.glob("*.md")):
        if slug and p.stem != slug:
            continue
        text = io.open(p, encoding="utf-8-sig").read()
        parts = split(text)
        if not parts:
            continue
        meta = yaml.safe_load(parts[1]) or {}
        owner = S.find_category_owner(meta.get("category")) or ""
        if site and owner != site:
            continue
        old = str(meta.get("description") or "").strip()
        if len(old) >= lo:
            continue
        new, added, why = fill(old, parts[3], lo, hi)
        top = hi
        if why and hi < GATE_MAX:
            # 150字に収まる文が無い記事だけ、門の上限（160字）まで広げる。100字未満のまま残すと
            # サイト監査の門（説明文が短すぎる）で公開が止まる
            new, added, why = fill(old, parts[3], lo, GATE_MAX)
            top = GATE_MAX
        ng = why or verify(old, new, parts[3], added, lo, top)
        rows.append({"path": p, "slug": p.stem, "site": owner, "category": meta.get("category", ""),
                     "old": old, "new": new, "added": added, "ng": ng, "text": text, "body": parts[3]})
    return rows


def write(rows):
    import auto_review as AR
    done = 0
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with io.open(LOG, "a", encoding="utf-8", newline="\n") as lg:
        for r in rows:
            if r["ng"]:
                continue
            after = set_description(r["text"], r["new"])
            a = split(after)
            # 本文には1文字も触れていないことを、見直しの検算（タグ・導線・見出し・本文の減り）で確かめる
            ng = AR.guard(split(r["text"])[1], r["body"], a[3], 0)
            if not ng and str((yaml.safe_load(a[1]) or {}).get("description")) != r["new"]:
                ng = "書き換えた説明文を読み戻せない"
            if ng:
                r["ng"] = ng
                continue
            io.open(r["path"], "w", encoding="utf-8", newline="").write(after)
            lg.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M"), "by": "desc_fill", "slug": r["slug"],
                                 "kind": "desc_fill", "ok": True,
                                 "note": f"説明文 {len(r['old'])}→{len(r['new'])}字（"
                                         + "・".join(s for s, _ in r["added"]) + "の文を足す）",
                                 "before_description": r["old"]}, ensure_ascii=False) + "\n")
            done += 1
    return done


def audit(root, lo=MIN):
    """生成済みのHTMLで、説明文が lo 字未満のページを数える（noindex は検索に出ないので除く）"""
    root = Path(root)
    short, total = [], 0
    for f in sorted(root.rglob("*.html")):
        rel = f.relative_to(root).as_posix()
        if any(x in rel.split("/") for x in ("node_modules", ".git", ".next")):
            continue
        t = f.read_text(encoding="utf-8", errors="ignore")
        if "<html" not in t[:2000].lower() or re.search(r'<meta[^>]+name="robots"[^>]+noindex', t):
            continue
        m = (re.search(r'<meta\s+name="description"\s+content="([^"]*)"', t)
             or re.search(r'<meta\s+content="([^"]*)"\s+name="description"', t))
        total += 1
        d = html.unescape(m.group(1)) if m else ""
        if len(d) < lo:
            short.append((len(d), rel, d))
    return total, short


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--dry", action="store_true", help="見るだけ（既定）")
    ap.add_argument("--site")
    ap.add_argument("--slug")
    ap.add_argument("--audit", help="生成済みサイトのフォルダ")
    ap.add_argument("--min", type=int, default=MIN)
    a = ap.parse_args()
    if a.audit:
        total, short = audit(a.audit, a.min)
        kinds = collections.Counter(r.split("/")[0] if "/" in r else r for _, r, _ in short)
        print(f"DESC_AUDIT pages={total} short={len(short)}（{a.min}字未満）")
        for k, n in kinds.most_common():
            print(f"  {k}: {n}")
        for n, r, d in short:
            print(f"  {n:>3}字 {r}  {d[:50]}")
        return
    rows = plan(a.site, a.slug, a.min)
    ok = [r for r in rows if not r["ng"]]
    by = collections.Counter((r["site"], r["category"]) for r in ok)
    for r in rows:
        mark = "NG " + r["ng"] if r["ng"] else f"{len(r['old'])}→{len(r['new'])}字"
        print(f"[{r['site']}] {r['slug']}: {mark}")
        if not r["ng"] and not a.write:
            print(f"    前: {r['old']}")
            for src, s in r["added"]:
                print(f"    足す（{src}）: {s}")
    if a.write:
        n = write(rows)
        print(f"DESC_FILL written={n}")
    print(f"DESC_FILL 対象={len(rows)} 足せる={len(ok)} 足せない={len(rows) - len(ok)} "
          + " ".join(f"{s}/{c}={n}" for (s, c), n in sorted(by.items())))


if __name__ == "__main__":
    main()
