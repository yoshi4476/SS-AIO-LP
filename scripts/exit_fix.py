# -*- coding: utf-8 -*-
"""離脱が最も大きい区画の手前に、軽い導線を機械で置く（出口の最適化）。

**なぜ要るか**: ヒートマップ（section_view_<区画>）で「どこで読者が落ちるか」は
毎月分かるのに、直すのは人だった。落ちる直前に次の行き先（無料診断）が無ければ、
そこで終わる。区画の到達数が前の区画から最も減る位置を見つけ、その手前に導線が
無ければ1つだけ足す。デザインは触らない（既存の cta-mini と同じ見た目）。

対象: data-area を持つ固定ページ（/lp/ ・ トップ など）。記事は cta_fill が担当。
  python scripts/exit_fix.py            # どこに何を置くか
  python scripts/exit_fix.py --write
出す印: EXIT_OK=yes / EXIT_ADDED=<件>。台帳: automation/logs/auto_fix.jsonl
検算: タグの開閉数が変わらない／同じ区画に2つ置かない（data-exit-cta で判定）
"""
import argparse
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
SITE = ROOT / "site"
LOG = ROOT / "automation" / "logs" / "auto_fix.jsonl"
MIN_VIEWS = 50          # 先頭区画の到達がこれ未満のページは判断しない
MIN_DROP_PT = 25        # 前の区画から何ポイント落ちたら「出口」と見るか
CTA_PAT = re.compile(r'href="[^"]*#(contact|diagnosis)[^"]*"')


def section_views(prop, days=28):
    """{page_path: {区画slug: 到達数}}"""
    import gcreds
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
    ga = BetaAnalyticsDataClient(credentials=gcreds.load(ROOT / "indexing-service-account.json",
                                                        ["https://www.googleapis.com/auth/analytics.readonly"]))
    end = date.today() - timedelta(days=1)
    rep = ga.run_report(RunReportRequest(
        property=f"properties/{prop}",
        date_ranges=[DateRange(start_date=(end - timedelta(days=days)).isoformat(), end_date=end.isoformat())],
        dimensions=[Dimension(name="eventName"), Dimension(name="pagePath")],
        metrics=[Metric(name="eventCount")], limit=400))
    out = {}
    for r in rep.rows:
        name, page = r.dimension_values[0].value, r.dimension_values[1].value
        if name.startswith("section_view_"):
            out.setdefault(page, {})[name[len("section_view_"):]] = int(r.metric_values[0].value)
    return out


def worst_exit(order, views):
    """(落ちる直前の区画slug, 落ちる区画slug, 落差pt)。無ければ None"""
    base = max(views.values()) if views else 0
    if base < MIN_VIEWS:
        return None
    prev, best = None, None
    for slug, _ in order:
        v = views.get(slug)
        if v is None:
            continue
        if prev is not None:
            drop = round((prev[1] - v) / base * 100)
            if drop >= MIN_DROP_PT and (best is None or drop > best[2]):
                best = (prev[0], slug, drop)
        prev = (slug, v)
    return best


def block(page_path):
    return ('<div class="cta-mini" data-exit-cta="1" style="text-align:center;margin:28px auto;max-width:720px">'
            '<p style="margin:0 0 10px;font-weight:700">ここまで読んで「自社の場合は？」と思った方へ</p>'
            '<a class="cta-button" href="/lp/#diagnosis" data-cta="exit_diagnosis" '
            'style="display:inline-block;padding:12px 26px;border-radius:8px;background:#1b4fa0;color:#fff;text-decoration:none;font-weight:700">'
            '3分の無料診断で確かめる</a></div>\n')


def apply(page_path, exit_slug, write):
    f = SITE / page_path.strip("/") / "index.html" if page_path != "/" else SITE / "index.html"
    if not f.is_file():
        return False, "ファイルが無い"
    html = f.read_text(encoding="utf-8")
    # 落ちる区画の開始タグを探す（data-area-id か data-area の slug）
    import report_heat as RH
    tags = list(re.finditer(r"<[^>]*data-area=[^>]*>", html))
    target = None
    for m in tags:
        aid = re.search(r'data-area-id="([^"]*)"', m.group(0))
        lab = re.search(r'data-area="([^"]*)"', m.group(0))
        s = RH.slug_id(aid.group(1)) if aid else RH.slug_id(lab.group(1) if lab else "")
        if s == exit_slug:
            target = m
            break
    if not target:
        return False, "区画が見つからない"
    before = html[:target.start()]
    # 直前の区画（落ちる区画の手前）に、既に導線があるか
    prev_start = max((m.start() for m in tags if m.start() < target.start()), default=0)
    if CTA_PAT.search(html[prev_start:target.start()]) or 'data-exit-cta="1"' in html[prev_start:target.start()]:
        return False, "手前に導線が既にある"
    b = block(page_path)
    # 足すブロック自身の開閉が釣り合っていれば、ページ側の釣り合いも崩れない
    if b.count("<") != 2 * b.count("</"):
        return False, "タグの数が合わない"
    new = before + b + html[target.start():]
    if write:
        f.write_text(new, encoding="utf-8", newline="\n")
    return True, "導線を置いた"


def main():
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--site", default="")
    a = ap.parse_args()
    import report_heat as RH
    order = RH.area_map()
    added = 0
    for sid, cfg in S.load_all().items():
        if a.site and sid != a.site:
            continue
        if sid != S.primary() or not cfg.get("ga4_property_id"):
            continue                       # 固定ページの実体があるのは本リポジトリのサイトだけ
        try:
            views = section_views(cfg["ga4_property_id"])
        except Exception as e:
            print(f"   {sid}: GA4 を読めません（{str(e)[:60]}）")
            continue
        for page_path, seq in order.items():
            v = views.get(page_path) or {}
            w = worst_exit(seq, v)
            if not w:
                continue
            name = dict(seq).get(w[1], w[1])
            print(f"   {page_path:<12} 「{name}」の手前で {w[2]}pt 落ちる")
            ok, why = apply(page_path, w[1], a.write)
            print(f"      {'○' if ok else '－'} {why}")
            if ok and a.write:
                added += 1
                LOG.parent.mkdir(parents=True, exist_ok=True)
                with LOG.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M"), "by": "exit_fix", "slug": page_path,
                                         "kind": "exit", "ok": True, "note": f"「{name}」の手前に導線（落差{w[2]}pt）"},
                                        ensure_ascii=False) + "\n")
    print(f"EXIT_OK=yes\nEXIT_ADDED={added}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
