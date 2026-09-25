# -*- coding: utf-8 -*-
"""自社の計測結果を、そのまま一次データのページにする（手入力なし）。

**なぜ要るか**: AIが根拠に選ぶのは「そこにしか無い数字」で、これが引用を
取る最大の手だと CLAUDE.md にも書いてある。それなのに公開している独立した
データページは1本だけだった（2026-09-23 実測）。手で集計する形にしていた
ため、増えるはずがなかった。

このサイトは毎日GSCとGA4を計測している。その結果自体が、他社の持っていない
一次データになる。日本語で「AI検索経由の流入を実数で公開している企業」は
まだ少ない。集計は毎週自動で走るので、手間はかからない。

作るデータ:
  aio-ctr-by-rank    順位帯ごとの実測クリック率（3サイト合算・母数は表示回数）
  ai-referral        生成AI経由のセッション（ChatGPT・Perplexity・Gemini…）
  index-speed        公開から検索に出るまでの日数の分布

数字はすべて実測。母数と集計期間を必ず添える（景品表示法）。
母数が足りないものは作らない。

    python scripts/data_auto.py             # 何ができるか見る
    python scripts/data_auto.py --write     # data/datasets/ に書き、ページを作る
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

OUT = ROOT / "data" / "datasets"
MIN_N = 100          # 母数がこれ未満なら公開しない（割合を出す資格が無い）
DAYS = 90            # 集計期間。短いと季節の癖が出る


def is_client(site_id):
    """受託運用のクライアントか（data/clients/<id>/ がある）。
    クライアントの実数は、その会社の数字。運用会社名義の一次データとして公開すると、
    他社の計測を自社の実績として出すことになる"""
    return (ROOT / "data" / "clients" / str(site_id)).is_dir()


def own_sites():
    """運用会社が自分で運営しているサイトだけ（一次データの集計対象）"""
    import sites as S
    return [c for c in S.load_all().values() if not is_client(c["id"])]


def own_categories():
    return {k for c in own_sites() for k in (c.get("categories") or {})}


def _own_article(text, cats):
    m = re.search(r"^category:\s*(\S+)", text, re.M)
    return bool(m) and m.group(1).strip().strip('"') in cats


def _spans(days):
    end = date.today() - timedelta(days=3)          # GSCの確定待ち
    return end - timedelta(days=days - 1), end


def ctr_by_rank(days=DAYS):
    """順位帯ごとの実測クリック率。母数は表示回数。

    「n位のクリック率は何%」という数字は、公開されているものが古いか
    海外のもので、日本語・BtoB・2026年の実測はほとんど無い。
    自社3サイトの実測をそのまま出す。
    """
    import gsc_detail as G
    sc = G.client()
    start, end = _spans(days)
    # GSCの順位は平均なので小数（3.5・10.4）。整数の閉区間だと帯の間と100位超が黙って落ち、
    # 公開する母数が欠ける。下限を含み上限を含まない帯にする
    bands = [(1, 4, "1〜3位"), (4, 11, "4〜10位"), (11, 21, "11〜20位"),
             (21, 31, "21〜30位"), (31, float("inf"), "31位以下")]
    agg = {b[2]: [0, 0] for b in bands}              # [表示, クリック]
    for cfg in own_sites():
        try:
            rows = G.q(sc, cfg["domain"], str(start), str(end), ["query", "page"], 25000,
                       raise_errors=True)
        except Exception as e:
            # 1サイト欠けたまま「3サイト合算」として公開すると、事実と違う数字になる。作らない
            print(f"  {cfg['id']}: GSCから取れません（{str(e)[:40]}）")
            return None
        for r in rows:
            for lo, hi, lab in bands:
                if lo <= r["position"] < hi:
                    agg[lab][0] += r["impressions"]
                    agg[lab][1] += r["clicks"]
                    break
    rows_out, total = [], 0
    for _, _, lab in bands:
        imp, clk = agg[lab]
        total += imp
        if imp < 30:
            continue
        rows_out.append({"label": lab, "value": round(clk / imp * 100, 2),
                         "num": clk, "den": imp,
                         "window": f"{start}〜{end}の{days}日間",
                         "note": "3サイト合算", "row_start": str(start)[:7],
                         "row_end": str(end)[:7]})
    if total < MIN_N or len(rows_out) < 3:
        return None
    return {
        "slug": "kensaku-juni-ctr",
        "title": f"検索順位ごとの実測クリック率（表示{total:,}回の集計）",
        "description": ("セブンセンシズが運営する3サイトのSearch Consoleから、"
                        "検索順位の帯ごとに表示回数とクリック数を集計しました。"
                        "日本語・中小企業向けの実測値です。"),
        "n": total, "n_unit": "回（表示）",
        "period": f"{start}〜{end}", "start": str(start), "end": str(end),
        "method": (f"Search Console の query×page 次元を{days}日分取得し、"
                   "平均掲載順位の帯ごとに表示回数とクリック数を合計。"
                   "クリック率＝クリック数÷表示回数。表示30回未満の帯は除外"),
        "unit": "%", "categories": ["aio", "seo"],
        "den_label": "表示回数", "num_label": "クリック", "neg_label": "非クリック",
        "rows": rows_out,
    }


def ai_referral(days=DAYS):
    """生成AI経由のセッション。実数で出す（割合にできる母数が無い）"""
    try:
        import daily_kpi as K
    except Exception:
        return None
    src = getattr(K, "AI_SOURCES", None) or {
        "chatgpt": ["chatgpt.com", "chat.openai.com"], "perplexity": ["perplexity.ai"],
        "gemini": ["gemini.google.com"], "copilot": ["copilot.microsoft.com"],
        "claude": ["claude.ai"]}
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (DateRange, Dimension,
                                                        Metric, RunReportRequest)
        import gcreds
    except Exception:
        return None
    sa = ROOT / "indexing-service-account.json"
    if not sa.is_file():
        return None
    cli = BetaAnalyticsDataClient(credentials=gcreds.load(
        sa, ["https://www.googleapis.com/auth/analytics.readonly"]))
    tally = defaultdict(int)
    for cfg in own_sites():
        prop = str(cfg.get("ga4_property_id") or "").strip()
        if not prop:
            continue
        try:
            rep = cli.run_report(RunReportRequest(
                property=f"properties/{prop}",
                date_ranges=[DateRange(start_date=f"{days}daysAgo", end_date="yesterday")],
                dimensions=[Dimension(name="sessionSource")],
                metrics=[Metric(name="sessions")]))
        except Exception:
            return None            # 欠けたまま「3サイト合算」と出さない
        for r in rep.rows:
            host = r.dimension_values[0].value.lower()
            for name, hosts in src.items():
                if any(h in host for h in hosts):
                    tally[name] += int(r.metric_values[0].value)
    total = sum(tally.values())
    if total < 10:
        return None
    start, end = _spans(days)
    return {
        "slug": "ai-keiyu-ryunyu",
        "title": f"生成AI経由の流入（{days}日で{total:,}セッション）",
        "description": ("ChatGPT・Perplexity・Gemini などの生成AIから"
                        "自社3サイトへ来たセッション数を、GA4の参照元で集計しました。"),
        "n": total, "n_unit": "セッション",
        "period": f"{start}〜{end}", "start": str(start), "end": str(end),
        "method": ("GA4 の sessionSource を参照元ホスト名で分類し、"
                   "生成AIのドメインに一致したセッションを合計"),
        "unit": "セッション", "categories": ["aio"],
        "den_label": "セッション", "num_label": "流入", "neg_label": "",
        "rows": [{"label": k, "value": v, "num": v, "den": total,
                  "window": f"{start}〜{end}", "note": "3サイト合算",
                  "row_start": str(start)[:7], "row_end": str(end)[:7]}
                 for k, v in sorted(tally.items(), key=lambda x: -x[1])],
    }


def sentence_of(ds):
    """引用用の一文。これが無いと一次情報として登録されず、記事から使われない。

    誰が・いつ・何件を・どう測ったかを1文に収める。AIが引用するときに
    出典と母数がその1文だけで足りる形にする（母数の無い割合は使われない）。
    """
    head = ", ".join(f"{r['label']}{r['value']}{ds['unit']}" for r in ds["rows"][:4])
    return (f"セブンセンシズ株式会社が{ds['period']}に自社3サイトで計測した"
            # 母数はカンマ無しで書く。add_fact が claim の中に母数の数字が
            # あるかを文字列で照合するため、7,015 と 7015 が一致しない
            f"{ds['n']}{ds['n_unit']}をもとに集計した「{ds['title'].split('（')[0]}」では、"
            f"{head}でした（{ds['method']}）。")


def index_speed(days=DAYS):
    """記事を公開してから検索結果に出るまでの日数。

    「記事はいつ順位がつくか」は誰もが知りたいのに、日本語の実測が少ない。
    公開日ごとに、その後の期間で一度でも表示されたかを数える。
    """
    import gsc_detail as G
    sc = G.client()
    start, end = _spans(days)
    seen = set()
    cats = own_categories()
    for cfg in own_sites():
        try:
            rows = G.q(sc, cfg["domain"], str(start), str(end), ["page"], 25000,
                       raise_errors=True)
        except Exception:
            # 取れなかったサイトの記事が全部「検索に出ていない」に数えられる。作らない
            return None
        for r in rows:
            seen.add(r["keys"][0].rstrip("/").split("/")[-1])

    bands = [(0, 13, "0〜13日"), (14, 27, "14〜27日"),
             (28, 41, "28〜41日"), (42, 999, "42日以上")]
    agg = {b[2]: [0, 0] for b in bands}          # [公開本数, 検索に出た本数]
    for p in (ROOT / "articles").glob("*.md"):
        if p.name.startswith("_"):
            continue
        t2 = p.read_text(encoding="utf-8-sig", errors="ignore")[:1500]
        if not re.search(r"^score:\s*(9[0-9]|100)\s*$", t2, re.M):
            continue
        if not _own_article(t2, cats):
            continue
        dm = re.search(r"^date:\s*(\d{4})-(\d{2})-(\d{2})", t2, re.M)
        sl = re.search(r"^slug:\s*(\S+)", t2, re.M)
        if not dm:
            continue
        slug = sl.group(1) if sl else p.stem
        age = (date.today() - date(int(dm.group(1)), int(dm.group(2)),
                                   int(dm.group(3)))).days
        for lo, hi, lab in bands:
            if lo <= age <= hi:
                agg[lab][0] += 1
                agg[lab][1] += 1 if slug in seen else 0
                break

    rows_out, total = [], 0
    for _, _, lab in bands:
        n, ok = agg[lab]
        total += n
        if n < 10:
            continue
        rows_out.append({"label": lab, "value": round(ok / n * 100, 1),
                         "num": ok, "den": n,
                         "window": f"{start}〜{end}",
                         "note": "3サイト合算", "row_start": str(start)[:7],
                         "row_end": str(end)[:7]})
    if total < MIN_N or len(rows_out) < 3:
        return None
    return {
        "slug": "kiji-hyouji-madeno-nissuu",
        "title": f"記事を公開してから検索結果に出るまでの日数（{total}本の集計）",
        "description": ("セブンセンシズが運営する3サイトの記事について、"
                        "公開からの経過日数ごとに、Search Consoleで一度でも"
                        "表示された記事の割合を集計しました。"),
        "n": total, "n_unit": "本",
        "period": f"{start}〜{end}", "start": str(start), "end": str(end),
        "method": (f"公開日からの経過日数で記事を区分し、直近{days}日の"
                   "Search Console（page次元）に1回でも表示が記録された記事を"
                   "「検索結果に出た」として数えた。10本未満の区分は除外"),
        "unit": "%", "categories": ["seo", "aio"],
        "den_label": "記事数", "num_label": "検索に出た", "neg_label": "出ていない",
        "rows": rows_out,
    }


def links_by_rank(days=DAYS):
    """順位帯ごとの内部リンク本数。通説（上位ほど多い）と実測が合うかを出す"""
    import statistics as st
    import gsc_detail as G
    sc = G.client()
    start, end = _spans(days)
    pos = defaultdict(lambda: [0, 0.0])
    cats = own_categories()
    for cfg in own_sites():
        try:
            rows = G.q(sc, cfg["domain"], str(start), str(end), ["page"], 25000,
                       raise_errors=True)
        except Exception:
            return None            # 欠けたまま「3サイト」の実測として出さない
        for r in rows:
            s = r["keys"][0].rstrip("/").split("/")[-1]
            pos[s][0] += r["impressions"]
            pos[s][1] += r["position"] * r["impressions"]

    inb = defaultdict(int)
    for p in (ROOT / "articles").glob("*.md"):
        body = p.read_text(encoding="utf-8-sig", errors="ignore")
        if not _own_article(body[:1500], cats):
            continue
        for u in set(re.findall(r"\]\((/[^)]+/)\)", body)):
            inb[u.rstrip("/").split("/")[-1]] += 1

    # 加重平均の順位は小数。上限を含まない帯にして、10〜11位などを落とさない
    bands = [(1, 11, "1〜10位"), (11, 21, "11〜20位"),
             (21, 31, "21〜30位"), (31, float("inf"), "31位以下")]
    rows_out, total = [], 0
    for lo, hi, lab in bands:
        vals = [inb.get(s, 0) for s, (imp, ps) in pos.items()
                if imp >= 10 and lo <= ps / imp < hi]
        if len(vals) < 5:
            continue
        total += len(vals)
        rows_out.append({"label": lab, "value": round(st.median(vals), 1),
                         "num": len(vals), "den": len(vals),
                         "window": f"{start}〜{end}",
                         "note": f"{len(vals)}本の中央値",
                         "row_start": str(start)[:7], "row_end": str(end)[:7]})
    if len(rows_out) < 3 or total < 30:
        return None
    return {
        "slug": "juni-naibu-link",
        "title": f"検索順位ごとの内部リンク本数（{total}本の集計）",
        "description": ("「上位の記事ほど内部リンクが多い」と言われますが、"
                        "自社3サイトで実測すると必ずしもそうではありませんでした。"
                        "順位帯ごとに、その記事が受けている内部リンクの中央値を出しています。"),
        "n": total, "n_unit": "本",
        "period": f"{start}〜{end}", "start": str(start), "end": str(end),
        "method": ("Search Console の page 次元で表示10回以上の記事を対象に、"
                   "表示回数で重みづけした平均掲載順位で区分し、"
                   "原稿内の内部リンク（他記事へのリンク）を受けている本数の中央値を出した。"
                   "5本未満の区分は除外"),
        "unit": "本", "categories": ["seo", "aio"],
        "den_label": "記事数", "num_label": "記事数", "neg_label": "",
        "rows": rows_out,
    }


BUILDERS = [("順位ごとのクリック率", ctr_by_rank), ("生成AI経由の流入", ai_referral),
            ("公開から検索に出るまでの日数", index_speed),
            ("順位ごとの内部リンク本数", links_by_rank)]
# 切り口の追加分（業種別・手法別・質問形見出し・自動修正の効き）。母数の決まりは同じ
try:
    import data_auto_more as _more
    BUILDERS += _more.BUILDERS
except Exception as _e:
    print(f"  （追加の切り口を読めません: {str(_e)[:50]}）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--days", type=int, default=DAYS)
    a = ap.parse_args()

    made = []
    for name, fn in BUILDERS:
        try:
            ds = fn(a.days)
        except Exception as e:
            print(f"  {name}: 作れません（{str(e)[:60]}）")
            continue
        if not ds:
            print(f"  {name}: 母数が足りないか、計測が取れないため作りません")
            continue
        print(f"  {name}: {ds['title']}")
        for r in ds["rows"][:6]:
            print(f"      {r['label']:<10}{r['value']:>8} {ds['unit']}  "
                  f"（{r['num']:,}/{r['den']:,}）")
        made.append(ds)

    if not a.write:
        print(f"\n  {len(made)}件を作れます。--write で data/datasets/ に書き、ページを作ります")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    today = str(date.today())
    for ds in made:
        p = OUT / f"{ds['slug']}.json"
        if p.is_file():
            try:
                old = json.loads(p.read_text(encoding="utf-8"))
                ds["published"] = old.get("published", today)
            except Exception:
                ds["published"] = today
        else:
            ds["published"] = today
        ds["modified"] = today
        ds["sentence"] = ds.get("sentence") or sentence_of(ds)
        p.write_text(json.dumps(ds, ensure_ascii=False, indent=1),
                     encoding="utf-8", newline="\n")
        print(f"  書きました: data/datasets/{ds['slug']}.json")

    import subprocess
    r = subprocess.run([sys.executable, "scripts/data_intake.py", "--rebuild"],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print((r.stdout or "").strip()[-600:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
