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
    python scripts/link_boost.py <site_id> --band=4-20 --inline   # 文中リンク（集中モードだけが使う）

--inline は段落を足さない。送り元の本文に既にある語句（送り先の狙う語・題の主要な語句）を
[語](/url/) で囲むだけで、文字は1文字も変えない。リンクだけの段落は上限（4本）に
当たった記事が多く、それ以上は足せないため。
"""
import glob
import io
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
import shorten_anchors as sa  # noqa: E402

LINK = re.compile(r"\]\((?:https?://[^/)]+)?(/[a-z0-9-]+/([a-z0-9-]+)/?)\)")
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


def parse_band(argv):
    """--band=4-10 → (4.0, 10.0)。指定が無ければ None（既定の動きは変えない）"""
    v = next((x.split("=", 1)[1] for x in argv if x.startswith("--band=")), "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)", v)
    if not m:
        return None
    lo, hi = float(m.group(1)), float(m.group(2))
    return (lo, hi) if 0 < lo <= hi else None


def band_targets(site, arts, cnt, lo, hi, pages=None):
    """順位が lo〜hi 位で被リンクが下限に届かない記事と、各記事より上にいる記事の順位。

    送り元を「その記事より上位の記事」に限るのは、評価を上から流すため。
    下位の記事から足しても、4〜10位の記事を押し上げる力にならない"""
    import rank_up
    if pages is None:
        import sites as S
        pages = rank_up.fetch(S.load(site)["domain"])
    pos = {}
    for d in pages.values():
        s = d["slug"]
        if s in arts and (s not in pos or d["imp"] > pos[s][1]):
            pos[s] = (d["pos"], d["imp"])
    out = []
    for s, (p, imp) in pos.items():
        if lo - 0.5 < p <= hi + 0.5 and imp >= rank_up.MIN_IMP and cnt.get(s, 0) < RESCUE_FLOOR:
            out.append((s, p, imp, cnt.get(s, 0)))
    out.sort(key=lambda x: -(x[2] * max(0.0, hi + 1 - x[1])))
    return out, {s: v[0] for s, v in pos.items()}


def industry_of(text, site_id):
    """その記事が扱う業種。語が重ならない記事同士をつなぐ手がかりにする"""
    try:
        import coverage as CV
    except Exception:
        return set()
    hay = CV._norm(text)
    out = set()
    for i in CV.industries(site_id):
        for s in [i["name"]] + (i.get("synonyms") or []):
            if CV._norm(s) and CV._norm(s) in hay:
                out.add(i["slug"])
                break
    return out


def note(tgt, src, kind, anchor=None, log=None):
    """何をしたかを台帳に残す（CLAUDE.md 8.6 の決まり）。

    残さないと、あとで効果を測れない。実際 effect_ab は
    link_boost の記録が1件も無いため、内部リンクが効いたかを判定できなかった。
    文中リンクはアンカーも残す（auto_review がサイト全体の偏りをこれで数える）。
    """
    import json
    import time
    log = Path(log) if log else ROOT / "automation" / "logs" / "auto_fix.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": time.strftime("%Y-%m-%d %H:%M"), "by": "link_boost", "slug": tgt, "kind": kind,
           "ok": True, "note": f"{src} から内部リンクを1本"}
    if anchor:
        row.update(src=src, anchor=anchor, note=f"{src} の本文の「{anchor}」を文中リンクに")
    with io.open(log, "a", encoding="utf-8", newline="") as f:
        f.write(json.dumps(row, ensure_ascii=False) + NL_CH)


def insert_ok(before, after):
    """1本挿し込んだ結果が壊れていないか。崩れていれば理由を返す（空なら合格）。

    link_boost は書き込み後の検算を持たない唯一の自動修正だった。
    実際にこれが表を壊している（リンク文が表に直結し、パイプ記号のまま
    本文に出た）。auto_review が週次で拾うまで、壊れたまま配信されていた。
    """
    # 塊の数が変わってはいけない。増えるのは段落1つだけ
    for pat, label in ((r"^\|", "表の行"), (r"^#{2,4} ", "見出し"),
                       (r"^\s*[-*] ", "箇条書き"), (r"^\s*\d+\. ", "番号リスト")):
        b = len(re.findall(pat, before, re.M))
        a = len(re.findall(pat, after, re.M))
        if b != a:
            return f"{label}の数が変わった（{b}→{a}）"
    for tag in ("<figure", "</figure>", "<div", "</div>", "<details", "</details>",
                "<table", "</table>", "cta-button"):
        if before.count(tag) != after.count(tag):
            return f"{tag} の数が変わった"
    # 表・箇条書き・見出しに直結していないか（空行が要る）
    # 増えた分だけを見る。記事に元からある「リンクつきの箇条書きの次の行も箇条書き」まで数えていたため、
    # ほぼ全部の挿し込みが見送られていた（2026-09-28 の週次で29件・押し上げのリンクが入らなかった）
    # 行頭の空白は [ \t]*。\s* だと改行にも一致し、空行をはさんだ箇条書きまで「直結」と数えていた
    glued = r"^(.*\]\(/[^)]+/\)[^\n]*)\n(?=[|#]|[ \t]*[-*] |[ \t]*\d+\. )"
    def n_glued(s):
        return sum(1 for m in re.finditer(glued, s, re.M) if m.group(1).strip())
    if n_glued(after) > n_glued(before):
        return "挿し込んだ行が次の塊に直結している（前後に空行が要る）"
    if len(after) <= len(before):
        return "本文が増えていない"
    return ""


# --inline の上限。1回に1つの送り元へ足す文中リンクの本数
INLINE_PER_SRC = 2
# これより短い語句は話題を言い当てない（「経理代行」を全部リンクにすると、どこへ飛ぶか読めない）
INLINE_MIN = 5
_HTML_BLOCK = re.compile(r"<(div|details|figure|table|aside|section|ul|ol|blockquote)\b", re.I)
_HTML_CLOSE = re.compile(r"</(div|details|figure|table|aside|section|ul|ol|blockquote)>", re.I)
_LISTISH = re.compile(r"^[ \t]*(?:[-*+]|\d+\.)[ \t]|^[ \t]*[|>#!]", re.M)


def anchor_phrases(a, others=()):
    """送り先を言い当てる語句（長い順）。本文にそのまま現れたときだけアンカーにする。

    狙う語の隣り合う語のうち、欠けるのが1語までのもの（「歯科医院 閉院 費用」→「閉院費用」
    「歯科医院の閉院」…）と題の主部。2語だけを拾うと「病院 口コミ 返信 例文」から「口コミ返信」が
    でき、一般のMEOの文脈から病院向けの記事へ飛ばしていた（2026-10-05 の dry）。
    others（他の記事の題・狙う語）の2本以上に含まれる語句は外す。サイトでよく使う語で、
    送り先を言い当てない。1本でも外すと、実測で ai-lab・corporate の候補が0本になった"""
    out = set()
    kw = a.get("kw", "").strip()
    toks = [t for t in re.split(r"[\s　]+", kw) if t]
    if len(toks) == 1:
        out.add(toks[0])
    span = max(2, len(toks) - 1)
    for i in range(len(toks)):
        for j in range(i + span, len(toks) + 1):
            part = toks[i:j]
            out |= {" ".join(part), "".join(part), "の".join(part)}
    head = re.sub(r"[【\[][^】\]]*[】\]]", "", a.get("title", ""))
    head = re.split(r"[｜|：:]", head)[0].strip()
    out.add(head)
    # 「◯◯とは？」の題は「◯◯」が本文に現れる形
    out.add(re.sub(r"とは[？?]?.*$", "", head).strip())
    others = [_norm_kw(o) for o in others]
    ok = {p for p in out if INLINE_MIN <= len(p) <= sa.MAX and not re.search(r"[\[\]()<>*`=|#\n]", p)
          and sum(1 for o in others if _norm_kw(p) in o) < 2}
    return sorted(ok, key=lambda p: (-len(p), p))


def inline_spots(body):
    """文中リンクを置いてよい段落の (start, end)。

    置かないもの: 冒頭（最初のH2より前＝断言段落・対象読者・鮮度）、見出し直下の1文結論、
    まとめ・FAQの区画、見出し・表・箇条書き・引用・コード、行頭が < の枠とその中、
    既にリンクやHTMLタグを含む段落（1段落に1本まで）"""
    out = []
    h2 = re.search(r"^## ", body, re.M)
    if not h2:
        return out
    depth, fence, after_head, skip_sec = 0, False, False, False
    for m in re.finditer(r"(?:^[ \t]*\S[^\n]*(?:\n|$))+", body, re.M):
        blk = m.group(0).rstrip("\n")
        s = blk.lstrip()
        fences = len(re.findall(r"^[ \t]*```", blk, re.M))
        if fence or fences:
            fence = fence != (fences % 2 == 1)
            continue
        opens, closes = len(_HTML_BLOCK.findall(blk)), len(_HTML_CLOSE.findall(blk))
        inside = depth > 0
        depth = max(0, depth + opens - closes)
        if s.startswith("#"):
            if s.startswith("## "):
                skip_sec = bool(ln.SKIP_H2.search(s.split("\n", 1)[0]))
            after_head = "\n" not in blk     # 見出しに本文が直結していれば、その本文が1文結論
            continue
        # 図・表・枠は1文結論の席を埋めない（見出しの後で最初に来る地の文を1文結論とみなす）
        if inside or s.startswith("<") or opens or _LISTISH.search(blk):
            continue
        if m.start() < h2.start():
            continue
        if after_head:
            after_head = False
            continue
        if skip_sec or re.search(r"[<>\[\]`]", blk):
            continue
        out.append((m.start(), m.start() + len(blk)))
    return out


def _norm_kw(s):
    return re.sub(r"[\s　]+", "", s or "").lower()


def inline_link(body, phrases, url, own=""):
    """本文にある語句を [語](url) で囲んだ本文と、囲んだ語句。置ける所が無ければ (None, None)。

    own は送り元の狙う語。送り元の主題そのものを他の記事へ飛ばさない"""
    own = _norm_kw(own)
    spots = inline_spots(body)
    for ph in phrases:
        p = _norm_kw(ph)
        if own and (p in own or own in p):
            continue
        for s, e in spots:
            para = body[s:e]
            for m in re.finditer(re.escape(ph), para, re.I):
                if "\n" in m.group(0):
                    continue
                a0, a1 = s + m.start(), s + m.end()
                # 英数字の語の途中では切らない（aio が aiox の一部になる）
                if re.match(r"[A-Za-z0-9]", body[a0]) and a0 > 0 and re.match(r"[A-Za-z0-9]", body[a0 - 1]):
                    continue
                if re.match(r"[A-Za-z0-9]", body[a1 - 1]) and re.match(r"[A-Za-z0-9]", body[a1:a1 + 1] or " "):
                    continue
                anchor = body[a0:a1]
                nb = body[:a0] + "[" + anchor + "](" + url + ")" + body[a1:]
                if inline_ok(body, nb, url, anchor):
                    continue
                return nb, anchor
    return None, None


def unlink(after, url, anchor):
    """足した文中リンクの記法だけを外す（文章が1文字も変わっていないことの検算に使う）"""
    return after.replace("[" + anchor + "](" + url + ")", anchor, 1)


def inline_ok(before, after, url, anchor):
    """文中リンクの検算。崩れていれば理由を返す（空なら合格）"""
    if unlink(after, url, anchor) != before:
        return "リンクの記法を外すと元の本文に戻らない"
    ng = ar.guard("", before, after, 0) or insert_ok(before, after)
    if ng:
        return ng
    # 短い段落にリンクが入ると、見直し（auto_review --fix）が「リンクだけの段落」と読んで
    # 段落ごと消す。消されるのは元からある本文なので、そう読まれる形には置かない
    def n_para(s):
        return sum(1 for m in ar.LINK_PARA.finditer(s) if not ar.KEEP.search(m.group(0)))
    if n_para(after) != n_para(before):
        return "リンクだけの段落と読まれる"
    return ""


_P1 = {}


def _page1(site):
    """検索1ページ目（10位以内）にいる記事の slug。取れなければ空（順序は従来どおり）"""
    if site in _P1:
        return _P1[site]
    out = set()
    try:
        import rank_up
        import sites as S
        for url, v in rank_up.fetch(S.load(site)["domain"]).items():
            if (v.get("pos") or 99) <= 10:
                out.add(url.rstrip("/").split("/")[-1])
    except Exception:
        pass
    _P1[site] = out
    return out


def linkable(slug, arts, recs=None):
    """送り先にしてよい記事か（監修の記録があり、公開の門を通る）。
    監修待ち・足切りの記事は公開されないので、張ると別リポジトリの社では404になる（2026-09-25）"""
    import editorial_review
    import publish
    if not editorial_review.reviewed(slug, recs):
        return False
    return publish.gate_ok(publish.read_meta(arts[slug]["path"]) or {})


def sources(site, tgt, arts, cnt, ranks=None):
    """送り元の候補（近い順）。ranks を渡すと、送り先より上位の記事だけ"""
    a = arts[tgt]
    tw = words(a)
    # 送り元候補: 同じ話題に触れていて、まだリンクしていない記事
    cands = []
    tgt_ind = industry_of(a["title"] + a["kw"], site)
    for src, b in arts.items():
        if src == tgt or f"/{tgt}/" in b["body"]:
            continue
        if ranks is not None and not ranks.get(src, 999) < ranks.get(tgt, 0):
            continue
        hit = sum(1 for w in tw if w in b["body"])
        # 短い語だけの一致は話題が近いとは限らない。言い当てる語を必ず含める
        key = distinctive(a)
        if hit >= 2 and (not key or any(w in b["body"] for w in key)):
            cands.append((hit, cnt[src], src))
            continue
        # 語が重ならなくても、同じ業種を扱う記事なら読者の次の行き先になる。
        # これが無いと、語の重なりが無い記事は送り元が見つからず、
        # 被リンクが下限に届かないまま止まる（実測23本）
        if tgt_ind and tgt_ind & industry_of(b["title"] + b["kw"], site):
            cands.append((1, cnt[src], src))
    # 話題が近く、**検索1ページ目にいる記事**から先に送る（評価は上から流れる）。
    # 同じ近さなら自身の被リンクが多い記事を優先する
    p1 = _page1(site)
    cands.sort(key=lambda x: (-x[0], -(x[2] in p1), -x[1]))
    return cands


def industry_terms(text, site_id):
    """その文が扱う業種の語（名前・別名）"""
    try:
        import coverage as CV
        inds = CV.industries(site_id)
    except Exception:
        return []
    hay = _norm_kw(text)
    return [w for i in inds for w in [i["name"]] + (i.get("synonyms") or []) if _norm_kw(w) and _norm_kw(w) in hay]


def phrases_for(site, tgt, arts):
    """送り先のアンカー候補。業種別の記事へは業種名を含む語句でだけ送る。
    含めないと「AI導入補助金2026」がクリニック向けの記事へ飛んでいた（2026-10-05 の dry）"""
    a = arts[tgt]
    ph = anchor_phrases(a, [o["title"] + " " + o["kw"] for s, o in arts.items() if s != tgt])
    terms = [_norm_kw(t) for t in industry_terms(a["kw"], site)]
    if terms:
        ph = [p for p in ph if any(t in _norm_kw(p) for t in terms)]
    return ph


def run_inline(site, arts, poor, cnt, ranks, pre, write, log=None, use=None):
    """送り先ごとに、上位の近い記事の本文にある語句を文中リンクにする。足した本数を返す。

    上限: 送り先1本につき ADD_PER、送り元1本につき INLINE_PER_SRC、同じ送り先へは1記事1本、
    アンカーは shorten_anchors.MAX 字まで、同じアンカーは auto_review.MAX_SAME_ANCHOR 記事まで"""
    use = ar.anchor_use() if use is None else use
    per_src = Counter()
    done = 0
    for tgt in poor:
        a = arts[tgt]
        phrases = phrases_for(site, tgt, arts)
        if not phrases:
            continue
        url = f"{pre.rstrip('/')}/{tgt}/" if pre else f"/{a['cat']}/{tgt}/"
        added = 0
        for _, _, src in sources(site, tgt, arts, cnt, ranks):
            if added >= ADD_PER:
                break
            b = arts[src]
            if per_src[src] >= INLINE_PER_SRC or f"/{tgt}/" in b["body"]:
                continue
            if (len(ar.link_slugs(b["body"])) >= ar.MAX_INTERNAL_LINKS
                    or len(ar.scan(b["path"])[2]) > ar.MAX_LINK_PARA):
                continue
            ok = [p for p in phrases if use[p.lower()] < ar.MAX_SAME_ANCHOR]
            nb, anchor = inline_link(b["body"], ok, url, b.get("kw", ""))
            if not nb or use[anchor.lower()] >= ar.MAX_SAME_ANCHOR:
                continue
            print(f"   {tgt[:34]:<36}← {src[:32]}「{anchor}」")
            if write:
                t = b["path"].read_text(encoding="utf-8-sig")
                head = t.split("---", 2)[1]
                b["path"].write_text(f"---{head}---\n{nb}", encoding="utf-8", newline="")
                note(tgt, src, "link_inline", anchor=anchor, log=log)
            # 見るだけの実行でも本文を進める（同じ記事への上限を見込みに反映するため）
            b["body"] = nb
            use[anchor.lower()] += 1
            per_src[src] += 1
            added += 1
            done += 1
    return done


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit("使い方: python scripts/link_boost.py <site_id> [--write]")
    site = args[0]
    write = "--write" in sys.argv
    rescue = "--rescue" in sys.argv
    band = parse_band(sys.argv)
    # 文中リンクは集中モードの対象（4〜20位）へ、上位の記事からだけ送る
    inline = "--inline" in sys.argv
    if inline:
        rescue = False
        band = band or (4.0, 20.0)
    ranks = {}
    arts = load(site)
    if not arts:
        raise SystemExit(f"{site} の記事が見つかりません")
    cnt = inbound(arts)
    # --only=<slug>: 公開直後の1本だけに当てる（新記事は被リンク0で始まり、
    # 週次を待つと最大6日そのまま。インデックスと評価の立ち上がりが遅れる）
    only = next((x.split("=", 1)[1] for x in sys.argv if x.startswith("--only=")), "")
    if only:
        # 対象が決まっているので順位で選び直さない。rescue_targets は GSC を読むため、
        # 鍵の無い記事CIでは毎回ここで落ちていた（--rescue は1本あたりの上限にだけ効かせる）
        poor = [only] if only in arts else []
        if not poor:
            print(f"   --only の記事が見つかりません: {only}")
        else:
            if not linkable(only, arts):
                print(f"   {only} は監修の記録が無いか公開の基準（score・観点の足切り）を通っていない（未公開）ため、リンクを張りません")
                poor = []
    elif band:
        try:
            tg, ranks = band_targets(site, arts, cnt, *band)
        except Exception as e:
            # GSC が読めないときは0本で終える（順位の分からない記事へ「上位から」は送れない）
            print(f"   {site}: 順位を取れないため見送ります（{str(e)[:60]}）")
            tg = []
        tg = [t for t in tg if linkable(t[0], arts)]
        poor = [s for s, _, _, _ in tg]
        print(f"■ {site}: {band[0]:g}〜{band[1]:g}位で被リンクが{RESCUE_FLOOR}本未満 {len(poor)}記事（送り元は上位の記事だけ）")
        for s, pos, imp, n in tg:
            print(f"     {pos:>5.1f}位 表示{imp:>4}  被リンク{n:>3}本  {arts[s]['title'][:34]}")
    elif rescue:
        tg = [t for t in rescue_targets(site, arts, cnt) if linkable(t[0], arts)]
        poor = [s for s, _, _, _ in tg]
        print(f"■ {site}: 11〜30位で止まり、被リンクが{RESCUE_FLOOR}本未満 {len(poor)}記事")
        for s, pos, imp, n in tg:
            print(f"     {pos:>5.1f}位 表示{imp:>4}  被リンク{n:>3}本  {arts[s]['title'][:34]}")
    else:
        import editorial_review
        _recs = editorial_review.load()
        poor = [s for s, n in cnt.items() if n <= LOW and linkable(s, arts, _recs)]
        poor.sort(key=lambda s: cnt[s])
        print(f"■ {site}: {len(arts)}記事 / 被リンク{LOW}本以下 {len(poor)}記事")
    import sites as S
    pre = S.load(site).get("url_prefix")
    done = 0
    if inline:
        done = run_inline(site, arts, poor, cnt, ranks, pre, write)
        print(f"\n   {'文中リンクを足しました' if write else '文中リンクの候補'}: {done}本")
        if not write:
            print("   実行するには --write を付けてください")
        return
    for tgt in poor:
        a = arts[tgt]
        tw = words(a)
        cands = sources(site, tgt, arts, cnt, ranks if band else None)
        added = 0
        cap = RESCUE_ADD if rescue else ADD_PER   # --band は ADD_PER（週2回走るので1回は少なめ）
        for hit, _, src in cands:
            if added >= cap:
                break
            b = arts[src]
            # 送り元がすでにリンクだけの段落を上限（auto_review.MAX_LINK_PARA）まで持っていれば足さない。
            # 足すと見直しがすぐ外し、足しては消すを繰り返す（2026-09-28: 1記事16本まで積み上がった）
            if len(ar.scan(b["path"])[2]) >= ar.MAX_LINK_PARA:
                continue
            pos = pick_spot(b["body"], tw)
            if pos is None:
                continue
            # URLの形はサイト設定で決まる。サイトIDで決め打ちすると、接頭辞が /blog でない
            # （または無い）クライアントの記事へ /blog/ で送り、配信先で404になる
            url = f"{pre.rstrip('/')}/{tgt}/" if pre else f"/{a['cat']}/{tgt}/"
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
                ng = insert_ok(b["body"], nb)
                if ng:
                    print(f"      見送り（{ng}）")
                    continue
                t = b["path"].read_text(encoding="utf-8-sig")
                head = t.split("---", 2)[1]
                b["path"].write_text(f"---{head}---\n{nb}", encoding="utf-8", newline="")
                arts[src]["body"] = nb
                # 候補を見るだけの実行で台帳に書くと、effect_ab が当てていない記事を介入群に数える
                note(tgt, src, "link_band" if band else "link_rescue" if rescue else "link")
            added += 1
            done += 1
    print(f"\n   {'追加しました' if write else '候補'}: {done}本")
    if not write:
        print("   実行するには --write を付けてください")


if __name__ == "__main__":
    main()
