# -*- coding: utf-8 -*-
"""CTAが足りない記事に、2箇所目を入れる。

**なぜ要るか**: CLAUDE.md は「CTA 最低2箇所」と決めているのに検査が無く、
公開136本のうち59本（43%）が2箇所未満だった（2026-09-23 実測）。
別工程の採点でも、デザイン観点が11本中11本で足切りになった主因がこれ。
読み終えた人の行き先が1つしか無い記事は、そこで離脱する。

置く場所は「まとめ」の直前。読者が結論まで読んだ直後で、
自然に次へ進める位置にする。まとめが無ければ最後のH2の直前。

文言は記事ごとに書かない。サイト設定の CTA をそのまま使う
（記事ごとに書くと、同じ一文がサイト中に並ぶ。8.6節の失敗と同じ）。

    python scripts/cta_fill.py            # どこに入るか見る
    python scripts/cta_fill.py --write
    python scripts/cta_fill.py --relink [--write]   # 相談ボタンの行き先をサイト設定の cta.url にそろえる
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

NEED = 2
NL = chr(10)


def cta_html(site_id):
    """サイト設定の文言でCTAを1つ作る"""
    import sites as S
    cfg = S.load_all().get(site_id) or {}
    # 設定は cfg["cta"] = {label, url, note} の形。ここを読み違えると
    # 3サイトとも同じ文言になり、サイトごとの売り物が伝わらない
    c = cfg.get("cta") or {}
    label = c.get("label") or "無料で相談する"
    # /lp/ は AI集客ラボにしか無い。ほかの社の記事に入ると相談のボタンが 404 になる（2026-10-08: 2本）。
    # 配信先の見た目（お客様の社 の .cta-inline など）への読み替えは配信の時に publish.py が行う
    href = c.get("url") or ("/lp/" if cfg.get("type") == "self-static" else f"https://{cfg.get('domain', '')}/")
    lead = (cfg.get("cta_desc") or c.get("note")
            or "ここまでの内容を自社に当てはめると何から着手すべきかを、無料で確認できます。")
    if not lead.endswith(("。", "！", "？")):
        lead += "。"
    return (f'<div class="cta-box"><p>{lead}</p>'
            f'<a class="cta-button" href="{href}">{label}</a></div>')


def spots(body, n):
    """入れる位置を n 箇所。読み終える直前と、記事の中ほど。

    1箇所しか返さないと、CTAが0の記事は1のままで基準（2箇所）に届かない。
    実際、183本に足したのに169本が1箇所のまま残った（2026-09-23）。
    """
    heads = list(re.finditer(r"^## .+$", body, re.M))
    if not heads:
        return []
    ends, mids = [], []
    for m in heads:
        if re.search(r"まとめ|よくある質問|FAQ", m.group(0)):
            ends.append(m.start())
    # 記事の中ほど。冒頭と末尾は避ける（冒頭は読む前、末尾は ends と重なる）
    body_heads = [m for m in heads
                  if not re.search(r"まとめ|よくある質問|FAQ", m.group(0))]
    if len(body_heads) >= 3:
        mids.append(body_heads[len(body_heads) // 2].start())
    cand = ([ends[0]] if ends else [heads[-1].start()]) + mids
    # すでにCTAが直前にある位置には入れない。入れると同じ箱が2つ並ぶ
    # （実測1本。基準の「2箇所」は満たすが、読者には同じ広告が連続して見える）
    cand = [p for p in cand if "cta-button" not in body[max(0, p - 400):p]] or cand
    # 後ろから入れる（前に入れると後ろの位置がずれる）
    return sorted(set(cand), reverse=True)[:n]


def check(before, after, added=1):
    """壊れていないか。link_boost と同じ考え方で、塊の数を見る"""
    for pat, label in ((r"^\|", "表の行"), (r"^#{2,4} ", "見出し"),
                       (r"^\s*[-*] ", "箇条書き")):
        if len(re.findall(pat, before, re.M)) != len(re.findall(pat, after, re.M)):
            return f"{label}の数が変わった"
    if after.count("cta-button") != before.count("cta-button") + added:
        return f"CTAが{added}つ増えていない"
    if len(after) <= len(before):
        return "本文が増えていない"
    return ""


import private_store as PS  # noqa: E402  お客様の社の記事の slug は CI のログに出さない


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--relink", action="store_true", help="相談ボタンの行き先をサイト設定の cta.url にそろえる")
    a = ap.parse_args()
    if a.relink:
        return relink(a.write)

    import sites as S
    done = skip = 0
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
        import noindex
        if noindex.hidden_fm(fm):       # 検索から外した記事（noindex）には手を入れない
            continue
        if body.count("cta-button") >= NEED:
            continue
        cat = re.search(r"^category:\s*(\S+)", fm, re.M)
        sid = S.find_category_owner(cat.group(1)) if cat else ""
        if not sid:
            continue
        have = body.count("cta-button")
        need = NEED - have
        ps = spots(body, need)
        if not ps:
            skip += 1
            continue
        block = cta_html(sid)
        nb = body
        for pos in ps:                      # 後ろから入れる
            nb = (nb[:pos].rstrip(NL) + NL * 2 + block + NL * 2
                  + nb[pos:].lstrip(NL))
        ng = check(body, nb, len(ps))
        if ng:
            print(f"   見送り {PS.shown(p.stem)[:34]:<36}{ng}")
            skip += 1
            continue
        print(f"   {PS.shown(p.stem)[:34]:<36}いま{have}箇所 → {len(ps)}箇所を追加")
        if a.write:
            p.write_text(f"---{NL}{fm}{NL}---{NL}{nb}", encoding="utf-8", newline="")
            _note(p.stem, sid)
        done += 1
    print(f"\n   {'追加しました' if a.write else '対象'}: {done}本 / 見送り {skip}本")
    if not a.write and done:
        print("   実行するには --write を付けてください")
    print("CTA_FILL=" + str(done))
    return 0


def _note(slug, site_id):
    import time
    import client_private as CP
    # お客様の記事の行は public の台帳に書かない（client_private の置き場へ）
    CP.append_jsonl(ROOT / "automation" / "logs" / "auto_fix.jsonl",
                    {"at": time.strftime("%Y-%m-%d %H:%M"), "by": "cta_fill", "slug": slug, "kind": "cta", "ok": True,
                     "note": "CTAを2箇所目まで足した"}, sid=site_id)


# ── 相談ボタンの行き先をサイト設定にそろえる ────────────────────────
# ボタンは原稿に書き込むので、cta.url を変えても既存の記事は前の行き先のまま残る。
# コーポレートは /contact/（/contact へ 308 で転送）のまま262か所が残り、転送を挟んだうえ、
# 先方の計測（pathname が /contact のときだけ入口として数える）にも数えられていなかった（2026-10-08）
_TAG = re.compile(r"<a\b[^>]*>")
_HREF = re.compile(r'\bhref="([^"]*)"')


def _old_form(href, cur):
    """href が今の行き先 cur と同じ場所の古い形か（同じホストで、パスの末尾の / だけが違い、クエリも # も無い）。
    クエリや # の付いたリンク・別の場所へのボタンは、意図して付けたものなので触らない"""
    from urllib.parse import urlsplit
    a, b = urlsplit(href), urlsplit(cur)
    return (a.scheme in ("http", "https") and a.netloc == b.netloc and not a.query and not a.fragment
            and a.path != b.path and a.path.rstrip("/") == b.path.rstrip("/"))


def _relink_text(text, cur):
    n = 0

    def fix(m):
        nonlocal n
        tag = m.group(0)
        h = _HREF.search(tag)
        if not re.search(r'\bclass="[^"]*\bcta-button\b', tag) or not h or not _old_form(h.group(1), cur):
            return tag
        n += 1
        return tag[:h.start(1)] + cur + tag[h.end(1):]
    return _TAG.sub(fix, text), n


def stale_links(write=False):
    """相談ボタン（class="cta-button"）の行き先が、サイト設定の cta.url と同じ場所の古い形のままの記事。
    [(slug, 件数)]。write なら今の行き先に差し替える（アンカーと文は変えない）"""
    import sites as S
    conf = S.load_all()
    out = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        if p.name.startswith("_"):
            continue
        t = p.read_bytes().decode("utf-8")
        cat = re.search(r"^category:\s*(\S+)", t, re.M)
        cur = (((conf.get(S.find_category_owner(cat.group(1)) if cat else "") or {}).get("cta") or {}).get("url") or "")
        if not cur.startswith("http"):
            continue
        new, n = _relink_text(t, cur)
        if n:
            out.append((p.stem, n))
            if write:
                p.write_bytes(new.encode("utf-8"))
    return out


def relink(write=False):
    got = stale_links(write)
    print(f"  相談ボタンの行き先を{'差し替えた' if write else '差し替える候補'}: {len(got)}本（{sum(n for _, n in got)}か所）")
    print("CTA_RELINK=" + str(sum(n for _, n in got)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
