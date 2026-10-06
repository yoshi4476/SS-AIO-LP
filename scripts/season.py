# -*- coding: utf-8 -*-
"""季節の山に合わせて、未着手の語を前へ出す（花見・紅葉・連休・補助金の公募期など）。

**なぜ要るか**: 検索の山は毎年だいたい同じ月に来る。山の月に記事を出しても、
インデックスと評価が追いつくのに数週間かかるので間に合わない。
前年からの GSC の月別表示で「山の月」を語ごとに求め、**山の6〜10週前**に当たる語を
台帳の先頭（優先度A）に出す。季節の語が無い月は何もしない。

判定: その語を含む検索の月別表示のうち、最大の月が平均の2倍以上なら「季節の語」。
      GSC は16か月分まで取れる（前年の同じ月が無いサイトは判定しない）。

  python scripts/season.py                 # 見るだけ
  python scripts/season.py --write         # 直接接続があれば台帳の優先度を A に
出す印: SEASON_OK=yes / SEASON_UP=<件>。結果: docs/season-<site>.md
      と data/season/<site>.json（山の月だけ。自社サイト以外の社の「今の時期の特集」を aggregate_pages が作る）
"""
import argparse
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
DOCS = ROOT / "docs"
PEAK_RATIO = 2.0
LEAD_WEEKS = (6, 10)
MIN_IMP = 30


def _tokens(s):
    return {t for t in re.findall(r"[一-龥ァ-ヶー]{2,}|[A-Za-z][A-Za-z0-9]{2,}", str(s).lower())}


def peaks(sc, domain):
    """{語のトークン: (山の月, 山の表示, 月平均)}。query×date を月へ畳む"""
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=480)
    by = defaultdict(lambda: defaultdict(int))
    for dim_start in range(0, 480, 90):                      # 90日ずつ（1回の行数上限を避ける）
        s = start + timedelta(days=dim_start)
        e = min(end, s + timedelta(days=89))
        body = {"startDate": s.isoformat(), "endDate": e.isoformat(), "dimensions": ["query", "date"], "rowLimit": 25000}
        try:
            rows = sc.searchanalytics().query(siteUrl=f"https://{domain}/", body=body).execute().get("rows", [])
        except Exception:
            continue
        for r in rows:
            q, d = r["keys"]
            for t in _tokens(q):
                by[t][int(d[5:7])] += int(r["impressions"])
    out = {}
    span = len({m for months in by.values() for m in months})
    peaks.span = span                                         # 何か月分のデータがあったか（呼び出し側が表示する）
    for t, months in by.items():
        total = sum(months.values())
        if total < MIN_IMP or len(months) < 6:
            continue
        m, v = max(months.items(), key=lambda kv: kv[1])
        avg = total / 12
        if v >= avg * PEAK_RATIO:
            out[t] = (m, v, round(avg))
    return out


def upcoming(peak_month):
    """山の月の初日が、今日から6〜10週後に入るか"""
    today = date.today()
    y = today.year + (1 if peak_month < today.month else 0)
    first = date(y, peak_month, 1)
    weeks = (first - today).days / 7
    return LEAD_WEEKS[0] <= weeks <= LEAD_WEEKS[1]


# ---------- 季節の特集（自社サイト以外の社にも出す。aggregate_pages が読む） ----------
STORE = ROOT / "data" / "season"
WINDOW_MONTHS = 3        # 今月から3か月のうちに山が来る主題を「今の時期」とする
FEATURE_MIN = 3          # 3本未満の主題は特集にしない（topics.MIN と同じ。薄い一覧を作らない）
FEATURE_MAX = 6


def save_peaks(site_id, pk, span, words):
    """山の月だけを残す。表示回数は残さない（お客様の検索の数字を公開リポジトリに置かない）。
    その社の記事の狙う語・題に出てくる語だけに絞る（特集は記事を束ねるだけなので、ほかの語は要らない）"""
    import json
    STORE.mkdir(parents=True, exist_ok=True)
    peaks_ = {t: m for t, (m, _, _) in sorted(pk.items()) if t in words}
    (STORE / f"{site_id}.json").write_text(json.dumps(
        {"made": date.today().isoformat(), "span": int(span), "peak_ratio": PEAK_RATIO, "peaks": peaks_},
        ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")


def feature(site_id, metas, today=None):
    """今の時期の特集。[{term, month, members}]。12か月分の検索データがそろうまでは作らない（判定前）"""
    import json
    p = STORE / f"{site_id}.json"
    if not p.is_file():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return []
    if int(d.get("span") or 0) < 12:
        return []
    today = today or date.today()
    months = [(today.month - 1 + i) % 12 + 1 for i in range(WINDOW_MONTHS)]
    out, used = [], set()
    for t, m in sorted((d.get("peaks") or {}).items(), key=lambda kv: (months.index(kv[1]) if kv[1] in months else 99, kv[0])):
        if m not in months:
            continue
        ms = [x for x in metas if x["slug"] not in used
              and t in _tokens(f'{x.get("keyword", "")} {x.get("title", "")}')]
        if len(ms) < FEATURE_MIN:
            continue
        out.append({"term": t, "month": m, "members": sorted(ms, key=lambda x: str(x.get("date", "")), reverse=True)})
        used.update(x["slug"] for x in ms)
        if len(out) >= FEATURE_MAX:
            break
    return out


def page_html(groups, url_of, ratio=PEAK_RATIO):
    """特集のページの中身。文は検索データ（山の月）と記事の題だけで作る"""
    import html as _h
    import json
    blocks = []
    for g in groups:
        lis = "".join(f'<li><a href="{url_of(m)}">{_h.escape(m["title"])}</a>'
                      f'<span class="cnt">{str(m.get("date", ""))[:7]}</span></li>' for m in g["members"])
        blocks.append(f'<div class="latest-block"><div class="cat-head"><h2>{g["month"]}月に検索が増える「{_h.escape(g["term"])}」</h2>'
                      f'<span class="cnt">{len(g["members"])}本</span></div><ul class="hub-list">{lis}</ul></div>')
    flat = [m for g in groups for m in g["members"]]
    ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": "今の時期の特集",
          "mainEntity": {"@type": "ItemList", "numberOfItems": len(flat),
                         "itemListElement": [{"@type": "ListItem", "position": i + 1, "url": url_of(m), "name": m["title"]}
                                             for i, m in enumerate(flat)]}}
    return ('<div class="latest-block" data-cat="new">'
            f'<p class="hub-lead">このサイトの検索データで、毎年この時期に検索が月平均の{ratio:g}倍以上に増えるテーマの記事をまとめています。'
            '検索が増える前に読んでおくと、準備が間に合います。</p></div>' + "\n".join(blocks)
            + '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>")


def _site_words(cfg):
    try:
        import wp_bridge
        return set().union(*[_tokens(f'{m.get("keyword", "")} {m.get("title", "")}') for m, _, _ in wp_bridge._site_articles(cfg)] or [set()])
    except Exception:
        return set()


def main():
    import gsc_detail as G
    import hub_client as HC
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--site", default="")
    a = ap.parse_args()
    try:
        sc = G.client()
    except Exception as e:
        print(f"GSC を読めません（{str(e)[:60]}）\nSEASON_OK=unknown")
        return 0
    todo = [r for r in HC.all_kw() if str(r.get("status", "")).strip() == "未着手"]
    direct = False
    try:
        import hub_sheets as HS
        direct = HS.available()
    except Exception:
        pass
    up_total = 0
    DOCS.mkdir(exist_ok=True)
    for sid, cfg in S.load_all().items():
        if a.site and sid != a.site:
            continue
        pk = peaks(sc, cfg["domain"])
        save_peaks(sid, pk, getattr(peaks, "span", 0), _site_words(cfg))
        if getattr(peaks, "span", 0) < 12:
            # 「季節の語が0」ではなく「まだ判定できない」。1年分そろうまでは山の月が決まらないので台帳も触らない
            print(f"■ {cfg['name']}: 検索データが{peaks.span}か月分しか無いため、季節の山はまだ判定できません（12か月分で判定）")
            continue
        hot = {t: v for t, v in pk.items() if upcoming(v[0])}
        picks = []
        for r in todo:
            if r.get("site") != sid:
                continue
            hit = [t for t in _tokens(r["keyword"]) if t in hot]
            if hit:
                picks.append((r["keyword"], hit[0], hot[hit[0]]))
        lines = [f"# 季節の山（{cfg['name']}・{date.today()}）", "",
                 f"季節の語 {len(pk)}個（山が平均の{PEAK_RATIO:.0f}倍以上）。うち6〜10週後に山が来るもの {len(hot)}個。", "",
                 "| 語 | 山の月 | 山の表示 | 月平均 |", "|:--|--:|--:|--:|"]
        lines += [f"| {t} | {m}月 | {v:,} | {avg:,} |" for t, (m, v, avg) in sorted(pk.items(), key=lambda kv: kv[1][0])[:60]]
        lines += ["", "## 前へ出す未着手の語", ""] + [f"- {kw}（{t}・{m}月が山）" for kw, t, (m, _, _) in picks] + [""]
        (DOCS / f"season-{sid}.md").write_text("\n".join(lines), encoding="utf-8")
        n = 0
        if a.write and direct and picks:
            sheet = HS.rows("KW台帳", HS.KW_COLS)
            want = {kw for kw, _, _ in picks}
            for i, s in enumerate(sheet):
                if str(s[0]) == sid and str(s[1]) in want and str(s[3] or "B") != "A":
                    HS._set("KW台帳", i + 2, 4, "A")
                    n += 1
        up_total += n
        print(f"■ {cfg['name']}: 季節の語 {len(pk)} / 6〜10週後に山 {len(hot)} / 前へ出す未着手 {len(picks)}本"
              + (f"（台帳を{n}件書き換え）" if a.write and direct else ""))
    print(f"SEASON_OK=yes\nSEASON_UP={up_total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
