# -*- coding: utf-8 -*-
"""集中モード（4週間・focus-mode.yml）の効き目を、順位帯ごとに並べる。

運用者の決定（2026-10-05）: 表示の7割が4〜20位にある（GSC 2026-09-02〜09-29・3サイト合計で
4〜10位 201ページ・表示3,956・CTR 2.5%／11〜20位 125ページ・表示2,470・CTR 1.1%）。
4週間だけ、週次に上乗せして4〜10位の題と11〜30位の欠けた問いを直す。

数字は2通りで測って一致したものだけを出す（CLAUDE.md 0.1）:
  A: page 次元（28日の合計。順位は GSC の28日平均）
  B: date×page 次元（日ごとの行をページごとに足し、順位は表示で重みづけ）
  A と B の表示・クリックの合計が1%を超えて食い違えば、その回の数字は出さない。
  query 次元は使わない（検索数の少ない語が落ちて少なく出る）。
  page 次元は指名検索・ボットを分けられない。指名の多い記事が混ざる前提で、
  直した記事と触っていない記事（対照群）の差で読む。

  python scripts/focus_report.py --status   # FOCUS=active|before|expired（ワークフローが読む）
  python scripts/focus_report.py --write    # 直近28日を測って data/focus_mode.json に残す
  python scripts/focus_report.py --line     # 週次の findings に載せる1行（情報。要対応ではない）
  python scripts/focus_report.py --final    # 4週間のまとめを docs/focus-mode-result.md に書く
"""
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
CONF = ROOT / "data" / "focus_mode.json"
DOC = ROOT / "docs" / "focus-mode-result.md"
LOG = ROOT / "automation" / "logs" / "auto_fix.jsonl"
TAG = "focus"
BANDS = ["1-3", "4-10", "11-20", "21+"]
TOL = 0.01
LAG = 3   # GSC の確定まで


def load_conf(path=None):
    return json.loads(Path(path or CONF).read_text(encoding="utf-8"))


def save_conf(conf, path=None):
    Path(path or CONF).write_text(json.dumps(conf, ensure_ascii=False, indent=1) + "\n",
                                  encoding="utf-8", newline="\n")


def status(conf, today=None):
    """before（始まる前）/ active（期間中）/ expired（until を過ぎた）"""
    t = str(today or date.today())
    if t < conf["start"]:
        return "before"
    return "active" if t <= conf["until"] else "expired"


def band(pos):
    """境目は整数（3.2位は4〜10位）。運用者の決定の数字（201ページ・3,956表示）はこの切り方で出ている。
    rank_up.BANDS の 3.5 区切りで数えると 200ページ・3,914表示になり、開始前の数字と合わない"""
    if pos <= 3:
        return "1-3"
    if pos <= 10:
        return "4-10"
    if pos <= 20:
        return "11-20"
    return "21+"


def slug_of(url):
    return url.rstrip("/").rsplit("/", 1)[-1]


def _rows(sc, domain, start, end, dims):
    """ページ送りつきで全行を取る（25,000行で切れたまま合計すると少なく出る）"""
    out, at = [], 0
    while True:
        body = {"startDate": str(start), "endDate": str(end), "dimensions": dims,
                "rowLimit": 25000, "startRow": at}
        rows = sc.searchanalytics().query(siteUrl=f"https://{domain}/", body=body).execute().get("rows", [])
        out += rows
        if len(rows) < 25000:
            return out
        at += 25000


def merge(rows, page_key):
    """URL ごとに足す。末尾スラッシュの有無で2行に分かれた同じページは1つにする"""
    pages = {}
    for r in rows:
        url = r["keys"][page_key].rstrip("/")
        p = pages.setdefault(url, {"imp": 0, "clk": 0, "ps": 0.0})
        p["imp"] += r["impressions"]
        p["clk"] += r["clicks"]
        p["ps"] += r["position"] * r["impressions"]
    for p in pages.values():
        p["pos"] = p.pop("ps") / p["imp"] if p["imp"] else 99.0
    return pages


def summarize(pages):
    out = {b: {"pages": 0, "imp": 0, "clk": 0} for b in BANDS}
    for p in pages.values():
        if not p["imp"]:
            continue
        s = out[band(p["pos"])]
        s["pages"] += 1
        s["imp"] += p["imp"]
        s["clk"] += p["clk"]
    for s in out.values():
        s["ctr"] = round(s["clk"] / s["imp"] * 100, 2) if s["imp"] else 0.0
    return out


def agree(a, b, tol=TOL):
    """A と B の表示・クリックの合計が許容差に収まるか。食い違いの説明を返す（空なら一致）"""
    bad = []
    for k in ("imp", "clk"):
        x, y = sum(s[k] for s in a.values()), sum(s[k] for s in b.values())
        m = max(x, y)
        if m and abs(x - y) / m > tol:
            bad.append(f"{k}: A={x} B={y}")
    return "／".join(bad)


def measure(start, end):
    """サイトごとに2通りで測る。{site: (A, B)}。読めなかったサイトは入れない（0件と区別する）"""
    import gsc_detail as G
    import sites as S
    sc = G.client()
    out = {}
    for sid, cfg in S.load_all().items():
        dom = cfg.get("domain")
        if not dom or sid == "sample":
            continue
        try:
            out[sid] = (merge(_rows(sc, dom, start, end, ["page"]), 0),
                        merge(_rows(sc, dom, start, end, ["date", "page"]), 1))
        except Exception as e:
            print(f"  {sid}: 読めませんでした（{str(e)[:60]}）")
    return out


def union(per_site, keep, i):
    out = {}
    for sid in keep:
        out.update(per_site[sid][i])
    return out


def focus_edits(start, log=None):
    """集中モードが直した記事（検算を通った分だけ）と、期間中に auto_rewrite が直した全記事"""
    f = Path(log) if log else LOG
    mine, any_ = set(), set()
    if not f.is_file():
        return mine, any_
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if str(d.get("at", ""))[:10] < start:
            continue
        if d.get("by") == "auto_rewrite" and d.get("ok") and str(d.get("note", "")).startswith("直しました"):
            any_.add(d.get("slug", ""))
            if d.get("tag") == TAG:
                mine.add(d.get("slug", ""))
        if d.get("by") == "link_boost" and d.get("kind") == "link_band":
            any_.add(d.get("slug", ""))
    return mine, any_


def group(pages, slugs):
    s = {"pages": 0, "imp": 0, "clk": 0, "ps": 0.0}
    for url, p in pages.items():
        if slug_of(url) in slugs:
            s["pages"] += 1
            s["imp"] += p["imp"]
            s["clk"] += p["clk"]
            s["ps"] += p["pos"] * p["imp"]
    s["pos"] = round(s.pop("ps") / s["imp"], 1) if s["imp"] else None
    s["ctr"] = round(s["clk"] / s["imp"] * 100, 2) if s["imp"] else 0.0
    return s


def groups(base, now, start, log=None):
    """直した記事と、対照群（期間中にどの書き直しも内部リンクの上乗せも受けていない記事）"""
    arts = {p.stem for p in (ROOT / "articles").glob("*.md")}
    mine, touched = focus_edits(start, log)
    seen = {slug_of(u) for u in base} & {slug_of(u) for u in now} & arts
    ctrl = seen - touched
    return {"edited": {"n": len(mine), "before": group(base, mine), "after": group(now, mine)},
            "control": {"n": len(ctrl), "before": group(base, ctrl), "after": group(now, ctrl)}}


def window(today=None):
    end = (today or date.today()) - timedelta(days=LAG)
    return end - timedelta(days=27), end


def run(conf, today=None):
    """開始前の28日と直近28日を測り、2通りが一致した回だけ記録の形で返す"""
    b0, b1 = conf["baseline"]
    s, e = window(today)
    import sites as S
    base, now = measure(b0, b1), measure(s, e)
    # 片方の期間だけ読めたサイトを混ぜると、増減が読めない。両方で読めたサイトだけで比べる
    keep = sorted(set(base) & set(now))
    failed = sorted(x for x in S.load_all() if x != "sample" and x not in keep)
    base_a, base_b = union(base, keep, 0), union(base, keep, 1)
    now_a, now_b = union(now, keep, 0), union(now, keep, 1)
    rec = {"measured": str(today or date.today()), "window": [str(s), str(e)],
           "sites": keep, "excluded_sites": failed,
           "baseline": summarize(base_a), "current": summarize(now_a)}
    # 読めたサイトが無いと A も B も0で「一致」してしまう。0件を数字として残さない
    why = ("どのサイトも読めませんでした" if not keep else
           agree(rec["baseline"], summarize(base_b)) or agree(rec["current"], summarize(now_b)))
    if why:
        rec["disagree"] = why
        return rec
    rec["groups"] = groups(base_a, now_a, conf["start"])
    return rec


def table(rec):
    lines = ["| 順位帯 | ページ（前→今） | 表示（前→今） | クリック（前→今） | CTR（前→今） |",
             "|:--|--:|--:|--:|--:|"]
    for b in BANDS:
        x, y = rec["baseline"][b], rec["current"][b]
        lines.append(f"| {b}位 | {x['pages']}→{y['pages']} | {x['imp']:,}→{y['imp']:,} | "
                     f"{x['clk']:,}→{y['clk']:,} | {x['ctr']:.1f}%→{y['ctr']:.1f}% |")
    g = rec.get("groups")
    if g:
        lines += ["", "| 群 | 本数 | 表示（前→今） | クリック（前→今） | CTR（前→今） | 平均順位（前→今） |",
                  "|:--|--:|--:|--:|--:|--:|"]
        for k, name in (("edited", "集中モードで直した記事"), ("control", "触っていない記事（対照群）")):
            x, y = g[k]["before"], g[k]["after"]
            lines.append(f"| {name} | {g[k]['n']} | {x['imp']:,}→{y['imp']:,} | {x['clk']:,}→{y['clk']:,} | "
                         f"{x['ctr']:.1f}%→{y['ctr']:.1f}% | {x['pos'] or '-'}→{y['pos'] or '-'} |")
    return "\n".join(lines)


def week_no(conf, day):
    return (date.fromisoformat(day) - date.fromisoformat(conf["start"])).days // 7 + 1


def line(conf, today=None):
    """週次の通知に載せる1行。期間外は空（集中モードが終われば週次の通知は元に戻る）。
    通知の絞り込み（notify_slack.NEEDS_ATTENTION）に当たる語を使わない＝これだけでは送られない"""
    if status(conf, today) != "active":
        return ""
    reps = conf.get("reports") or {}
    if not reps:
        return f"情報: 集中モード実施中（〜{conf['until']}）。まだ測っていません"
    r = reps[max(reps)]
    if r.get("disagree"):
        return f"情報: 集中モード 第{week_no(conf, r['measured'])}週。2通りの計測が合わないため数字は出しません"
    c, b = r["current"], r["baseline"]
    out = (f"情報: 集中モード 第{week_no(conf, r['measured'])}週（{r['window'][0]}〜{r['window'][1]}）"
           f" 4〜10位 CTR {b['4-10']['ctr']:.1f}%→{c['4-10']['ctr']:.1f}%"
           f"・11〜20位 CTR {b['11-20']['ctr']:.1f}%→{c['11-20']['ctr']:.1f}%")
    g = r.get("groups")
    if g:
        e, k = g["edited"], g["control"]
        out += (f"／直した{e['n']}本 クリック{e['before']['clk']}→{e['after']['clk']}"
                f"・対照群{k['n']}本 クリック{k['before']['clk']}→{k['after']['clk']}")
    return out


def render(conf):
    reps = conf.get("reports") or {}
    b0, b1 = conf["baseline"]
    out = [f"# 集中モードの結果（{conf['start']}〜{conf['until']}）", "",
           f"開始前の28日（{b0}〜{b1}）と、毎週の直近28日を順位帯ごとに並べた。",
           "数字は GSC の page 次元と date×page 次元の2通りで測り、表示・クリックの合計が1%以内で一致した回だけを載せる。",
           "page 次元は指名検索・ボットを分けられないため、直した記事と対照群（期間中に書き直し・上乗せの内部リンクを受けていない記事）の差で読む。",
           "直近28日には開始前の日が混ざる週がある（4週目の測定で初めて全部が期間中になる）。", ""]
    for k in sorted(reps):
        r = reps[k]
        out += [f"## {r['measured']} 測定（{r['window'][0]}〜{r['window'][1]}）", ""]
        if r.get("excluded_sites"):
            out.append(f"読めなかったサイト（両方の期間から外した）: {', '.join(r['excluded_sites'])}")
            out.append("")
        if r.get("disagree"):
            out += [f"2通りの計測が一致しなかったため、この回の数字は使わない（{r['disagree']}）", ""]
            continue
        out += [table(r), ""]
    if not reps:
        out += ["測定の記録がありません。", ""]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--line", action="store_true")
    ap.add_argument("--final", action="store_true")
    a = ap.parse_args()
    if not CONF.is_file():
        print("FOCUS=none")
        return 0
    conf = load_conf()
    st = status(conf)
    if a.status:
        print(f"FOCUS={st}")
        return 0
    if a.line:
        s = line(conf)
        if s:
            print(s)
        return 0
    if a.write or a.final:
        if a.final and conf.get("final_written"):
            print(f"まとめは {conf['final_written']} に書き済みです")
            return 0
        if a.write and st != "active":
            print(f"集中モードの期間外です（{st}）。測りません")
            return 0
        rec = run(conf)
        # 週2回走るので、同じ週は後の回で上書きする（並べるのは週ごと）
        conf.setdefault("reports", {})[f"w{week_no(conf, rec['measured']):02d}"] = rec
        if rec.get("disagree"):
            print(f"2通りの計測が一致しません（{rec['disagree']}）。この回の数字は使いません")
        else:
            print(table(rec))
        if a.final:
            DOC.parent.mkdir(parents=True, exist_ok=True)
            DOC.write_text(render(conf) + "\n", encoding="utf-8", newline="\n")
            conf["final_written"] = rec["measured"]
            print(f"\n  まとめ: {DOC.relative_to(ROOT).as_posix()}")
        save_conf(conf)
        return 0
    print(f"FOCUS={st}（--write / --line / --final）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
