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
    href = c.get("url") or "/lp/"
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

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
            print(f"   見送り {p.stem[:34]:<36}{ng}")
            skip += 1
            continue
        print(f"   {p.stem[:34]:<36}いま{have}箇所 → {len(ps)}箇所を追加")
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
    import json
    import time
    log = ROOT / "automation" / "logs" / "auto_fix.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8", newline="") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M"), "by": "cta_fill",
                            "slug": slug, "kind": "cta", "ok": True,
                            "note": "CTAを2箇所目まで足した"}, ensure_ascii=False) + NL)


if __name__ == "__main__":
    sys.exit(main())
