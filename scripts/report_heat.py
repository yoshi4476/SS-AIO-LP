# -*- coding: utf-8 -*-
"""ヒートマップ（どこまで読まれ、どこで離脱したか）を作る。

**なぜ作り直したか**: これまでは到達数の多い順に並べていた。
多い順に並べると、上から下へ読む動きが表に現れず、
**「どこで離脱したか」が読み取れない**。実際、トップページで
「mv 100% → hero 3%」のように、ページ上の位置と無関係な並びになっていた。

**直し方**: 並び順はサイトのHTMLから取る。`data-area` が書かれている順が
そのままページ上の順序なので、それに沿って並べる。
日本語の区画名も同じHTMLから取れるので、`mv` `whynow` のような
英字の内部名ではなく「メインビジュアル」「なぜ今か」と出す。

GA4のイベント名は site/js/site.js の slugId() で作られる。
**同じ規則をここでも使う**（片方だけ変えると対応が取れなくなる）。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"


def slug_id(s):
    """site/js/site.js の slugId() と同じ規則。片方だけ変えないこと"""
    s = re.sub(r"[^\w]+", "_", str(s or ""), flags=re.UNICODE)
    s = re.sub(r"^_+|_+$", "", s)[:30]
    return s or "x"


def area_map():
    """ページごとの区画の並びと日本語名。

    返すもの: {"/lp/": [(slug, "ヒーロー"), (slug, "課題共感"), …]}
    HTMLに書かれている順がページ上の順序。
    """
    out = {}
    for f in SITE.rglob("index.html"):
        html = f.read_text(encoding="utf-8", errors="ignore")
        # **1つの要素から対で読む。** data-area と data-area-id を別々に拾うと
        # 同じ区画が2件に増える（実際に /lp/ が15区画→30区画になった）
        areas = []
        for tag in re.findall(r"<[^>]*data-area=[^>]*>", html):
            lab = re.search(r'data-area="([^"]*)"', tag)
            aid = re.search(r'data-area-id="([^"]*)"', tag)
            if lab:
                areas.append((aid.group(1) if aid else None, lab.group(1)))
        if not areas:
            continue
        path = "/" + str(f.parent.relative_to(SITE)).replace("\\", "/").strip(".")
        path = (path.rstrip("/") + "/") if path != "/" else "/"
        seen, ordered = set(), []
        for aid, lab in areas:
            s = slug_id(aid) if aid else slug_id(lab)
            if s in seen:
                continue
            seen.add(s)
            ordered.append((s, lab))
        out[path] = ordered
    return out


def heat_html(sections, muted="#6b7a8d"):
    """到達のヒートマップ。**ページ上の順に並べ、落ち幅の大きい所を名指しする。**

    sections: monthly_report が GA4 から作る [{name, page, n, pct}, …]
    """
    if not sections:
        return ('<p class="note">区画ごとの到達が計測されていません。'
                '各区画に <code>data-area</code> を設置すると、翌月から'
                '離脱位置が特定できます。</p>')

    amap = area_map()
    by_page = {}
    for s in sections:
        by_page.setdefault(s.get("page") or "/", {})[s["name"]] = s["n"]

    blocks = []
    for page, counts in sorted(by_page.items(), key=lambda kv: -sum(kv[1].values())):
        order = amap.get(page) or amap.get(page.rstrip("/") + "/") or []
        # HTMLに無い区画（消した区画など）は後ろにまとめる
        known = [(s, lab) for s, lab in order if s in counts]
        # いまのHTMLに無い区画（消した区画・別ページの区画）。
        # 内部名のままだと読む人が迷うので、そうと分かるよう添える
        extra = [(s, f'{s}<span style="color:#9aa7b8">（現在このページに無い区画）</span>')
                 for s in counts if s not in {k for k, _ in order}]
        rows_src = known + extra
        if not rows_src:
            continue
        base = counts[rows_src[0][0]] or 1

        rows, prev, worst = [], None, (0, "")
        for slug, label in rows_src:
            n = counts[slug]
            pct = round(n / base * 100)
            drop = (prev - pct) if prev is not None else 0
            if drop > worst[0]:
                worst = (drop, label)
            col = "#0d9488" if pct >= 60 else ("#2563eb" if pct >= 30 else "#dc2626")
            note = (f'<b style="color:#dc2626">−{drop}pt</b>'
                    if drop >= 15 else (f'<span style="color:{muted}">−{drop}pt</span>'
                                        if drop > 0 else ""))
            # 棒の列に幅を与える。与えないと100%でも数ミリにしかならず、
            # 「どこで落ちたか」が目で追えない
            rows.append(
                f'<tr><td>{label}</td><td class="num">{n}</td>'
                f'<td class="num">{pct}%</td>'
                f'<td style="width:38%"><div style="background:{col};height:13px;'
                f'width:{max(pct, 2)}%;border-radius:3px"></div></td>'
                f'<td>{note}</td></tr>')
            prev = pct

        lead = (f'この順はページの上から下です。'
                f'最も大きく落ちるのは<b>「{worst[1]}」の手前で −{worst[0]}pt</b>。'
                if worst[0] else "この順はページの上から下です。")
        blocks.append(
            f'<p style="font-size:9pt;margin:6px 0 4px">'
            f'<b>ページ: <code>{page}</code></b>　{lead}</p>'
            f'<table><thead><tr><th>区画（上から順）</th><th>到達</th>'
            f'<th>到達率</th><th style="width:38%">到達率の帯</th>'
            f'<th>前の区画からの落ち</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')

    if not blocks:
        return '<p class="note">区画の並びをサイトから読み取れませんでした。</p>'
    # **1ページに詰めない。** ページごとに紙を分ける。
    # 区画が15ある /lp/ と6ある / を1枚に載せると、必ず溢れる
    out = [blocks[0]]
    for b in blocks[1:]:
        out.append('</div><div class="sheet">'
                   '<div class="sec"><span class="no">10</span>'
                   '<h2>ページのどこで離脱しているか（続き）</h2>'
                   '<div class="gold"></div></div>' + b)
    return "".join(out)


def depth_html(depths):
    """スクロール到達（25/50/75/90%）。区画を置いていないページでも見える指標"""
    if not depths:
        return ""
    base = depths.get("25") or max(depths.values() or [1]) or 1
    rows = []
    for k in ("25", "50", "75", "90"):
        n = depths.get(k, 0)
        pct = round(n / base * 100) if base else 0
        col = "#0d9488" if pct >= 60 else ("#2563eb" if pct >= 30 else "#dc2626")
        rows.append(f'<tr><td>{k}%まで読んだ</td><td class="num">{n}</td>'
                    f'<td class="num">{pct}%</td>'
                    f'<td><div style="background:{col};height:11px;'
                    f'width:{max(pct, 2)}%;border-radius:2px"></div></td></tr>')
    return ('<h3>読み進めた深さ（全ページ合計）</h3>'
            '<table><thead><tr><th>深さ</th><th>回数</th>'
            '<th>25%到達を100%とした割合</th><th></th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def main():
    m = area_map()
    print(f"■ 区画を置いているページ: {len(m)}件")
    for page, areas in sorted(m.items(), key=lambda kv: -len(kv[1]))[:8]:
        print(f"   {page}  {len(areas)}区画")
        for s, lab in areas[:4]:
            print(f"      {s:<22} {lab}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
