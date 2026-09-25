# -*- coding: utf-8 -*-
"""3倍の計画を台帳にし、毎月「道筋どおりか」を機械が確かめる。

**約束できないこと**: 順位も流入も Google が決める。3倍は目標であって保証ではない。
**約束できること**: 効く順（実測）に打ち手を並べ、全部を自動で回し、
毎月どこまで来たかを数字で出し、遅れたら「どの手が効いていないか」を知らせること。

打ち手は、実測で効くと分かっている順に置く（CLAUDE.md 0.3節）:
  YouTube での言及 0.71 > リンクの無いWeb言及 0.66 > 指名検索 0.39 > 被リンク 0.22
  質問形の見出し +4.2位（自社データ）／検索語の性質でCTRが5倍違う（自社データ）

  python scripts/growth_plan.py --init          # 先月を起点に、6か月で3倍の道筋を書く
  python scripts/growth_plan.py --check         # 先月の実績を道筋と比べる（月次CIが呼ぶ）
  python scripts/growth_plan.py                 # 台帳を見る
出す印: GROWTH_OK=yes/no/unknown。遅れは「要対応:」で始める（findings に載る）
台帳: reports/growth_plan.json / 説明: docs/growth-plan.md
"""
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
PLAN = ROOT / "reports" / "growth_plan.json"
DOC = ROOT / "docs" / "growth-plan.md"
METRICS = (("sessions", "セッション"), ("clicks", "検索クリック"), ("cv", "リード"), ("ai", "AI経由参照"))
MULT, MONTHS = 3.0, 6
LATE = 0.8            # 道筋の8割を割ったら遅れ

# 打ち手。auto は毎週/毎月の自動工程が担う。human は相手や判断が要る
LEVERS = [
    ("YouTubeでの言及", "auto", "article_videos（週次）", "記事を短い動画にして上げる。相関0.71で最上位",
     "youtube-token.json を1回だけ作る（作るまで動画は溜まるだけ）"),
    ("質問形・買い手の語を先に書く", "auto", "ai_kw_research → next_kw", "AIが答えを出し自社が出典に無い語を最優先で執筆"),
    ("業種×手法の面", "auto", "structure_plan → report_actions", "空いているマスの語を台帳へ積み、業種ハブを作る"),
    ("一次データの公開", "auto", "data_auto（週次）", "そこにしか無い数字。AIが根拠に選ぶ最大の手"),
    ("1ページ目手前の押し上げ", "auto", "rank_up / rank_rescue / link_boost（週次）", "11〜30位の記事に内部リンク・節を足す"),
    ("軽い入口のCTA", "auto", "cta_mid（サイト設定）", "中ほどは診断へ。補助金は2.7%→測定中"),
    ("リンクの無いWeb言及", "human", "mentions --check（消えていないかの監視だけ自動）",
     "掲載先を増やすのは相手がある。social_post のキューを人が投稿する"),
    ("フォームの離脱", "human", "funnel（計測は自動）", "コーポレートはフォームを開いた7人中1人しか送っていない。項目の見直しは判断が要る"),
]


def month_label(d):
    return f"{d.year}-{d.month:02d}"


def prev_month(label, k=1):
    y, m = map(int, label.split("-"))
    for _ in range(k):
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return f"{y}-{m:02d}"


def next_month(label, k=1):
    y, m = map(int, label.split("-"))
    for _ in range(k):
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return f"{y}-{m:02d}"


def measure(label):
    """その月の3サイト合算（group_report と同じ取り方）。取れなければ None"""
    import group_report as G
    import sites as S
    tot = {k: 0 for k, _ in METRICS}
    for cfg in S.load_all().values():
        s = G.fetch_site(cfg, [label])
        m = s["months"][0]
        # 片方だけ欠けたサイトを0で足すと、合計が小さく出て「遅れ」や小さい起点になる。
        # sessions/clicks は月次の取得が通ったときだけ入る。ai は GA4 が落ちると0のまま残る
        if "clicks" not in m:
            return None
        tot["clicks"] += int(m.get("clicks") or 0)
        # GA4 を持たない社は GA 分を数えない（クリックだけ足す）。None にすると
        # 1社でも未設定があるだけで計画が恒久的に取れなくなる。止めるのは一時的な取得失敗だけ
        if not cfg.get("ga4_property_id"):
            continue
        if "sessions" not in m or s.get("ga_error"):
            return None
        tot["sessions"] += int(m.get("sessions") or 0)
        tot["cv"] += int(m.get("cv") or 0)
        tot["ai"] += int(s.get("ai") or 0)
    return tot


def path_for(base, k):
    """k か月目の道筋。等比で MONTHS か月後に MULT 倍"""
    f = MULT ** (min(k, MONTHS) / MONTHS)
    return {m: max(int(round(base[m] * f)), base[m] + (1 if base[m] else 0)) for m, _ in METRICS}


def write_doc(plan, checks):
    lines = [f"# 3倍計画（起点 {plan['baseline_month']} → {plan['target_month']}）", "",
             "順位も流入も Google が決めるため、3倍は目標であって保証ではない。"
             "約束するのは、効く順に打ち手を全部自動で回し、毎月の遅れを数字で知らせること。", "",
             "## 道筋", "", "| 月 | " + " | ".join(n for _, n in METRICS) + " |", "|:--|" + "--:|" * len(METRICS)]
    for k in range(0, MONTHS + 1):
        lab = next_month(plan["baseline_month"], k)
        p = path_for(plan["baseline"], k)
        lines.append(f"| {lab}{'（起点）' if k == 0 else ''} | " + " | ".join(f"{p[m]:,}" for m, _ in METRICS) + " |")
    if checks:
        lines += ["", "## 実績", "", "| 月 | " + " | ".join(f"{n}（実績/道筋）" for _, n in METRICS) + " | 判定 |",
                  "|:--|" + "--:|" * len(METRICS) + ":--|"]
        for lab, c in sorted(checks.items()):
            lines.append(f"| {lab} | " + " | ".join(f"{c['actual'][m]:,} / {c['path'][m]:,}" for m, _ in METRICS)
                         + f" | {'道筋どおり' if c['ok'] else '遅れ: ' + '・'.join(c['late'])} |")
    lines += ["", "## 打ち手（効く順）", "", "| 打ち手 | 担当 | 工程 | 中身 |", "|:--|:--|:--|:--|"]
    for name, who, tool, what, *rest in LEVERS:
        lines.append(f"| {name} | {'自動' if who == 'auto' else '人'} | {tool} | {what}" + (f"（{rest[0]}）" if rest else "") + " |")
    DOC.parent.mkdir(exist_ok=True)
    DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--month", default="", help="起点や照合の月（YYYY-MM）。既定は先月")
    a = ap.parse_args()
    last_full = a.month or prev_month(month_label(date.today()))
    plan = json.loads(PLAN.read_text(encoding="utf-8")) if PLAN.is_file() else None

    if a.init or plan is None:
        base = measure(last_full)
        if not base:
            print("GROWTH_OK=unknown（起点の数字が取れません。GA4/GSC の設定を確認）")
            return 0
        plan = {"baseline_month": last_full, "baseline": base, "multiple": MULT, "months": MONTHS,
                "target_month": next_month(last_full, MONTHS), "checks": {}}
        PLAN.parent.mkdir(exist_ok=True)
        PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        write_doc(plan, plan["checks"])
        print(f"■ 起点 {last_full}: " + " / ".join(f"{n} {base[m]:,}" for m, n in METRICS))
        print(f"   {plan['target_month']} に3倍: " + " / ".join(f"{n} {path_for(base, MONTHS)[m]:,}" for m, n in METRICS))
        print("GROWTH_OK=yes")
        return 0

    if a.check:
        y0, m0 = map(int, plan["baseline_month"].split("-"))
        y1, m1 = map(int, last_full.split("-"))
        k = (y1 - y0) * 12 + (m1 - m0)
        if k <= 0:
            print(f"GROWTH_OK=yes（{last_full} は起点の月。照合は翌月から）")
            return 0
        actual = measure(last_full)
        if not actual:
            print("GROWTH_OK=unknown（先月の数字が取れません）")
            return 0
        path = path_for(plan["baseline"], k)
        late = [n for m, n in METRICS if path[m] and actual[m] < path[m] * LATE]
        ok = not late
        plan.setdefault("checks", {})[last_full] = {"actual": actual, "path": path, "ok": ok, "late": late}
        PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        write_doc(plan, plan["checks"])
        print(f"■ {last_full}（{k}か月目）: " + " / ".join(
            f"{n} {actual[m]:,}（道筋 {path[m]:,}）" for m, n in METRICS))
        if late:
            print(f"要対応: 3倍計画から遅れ（{'・'.join(late)}）。効いていない打ち手を effect_ab で切り分ける")
        print(f"GROWTH_OK={'yes' if ok else 'no'}")
        return 0

    write_doc(plan, plan.get("checks", {}))
    print(f"起点 {plan['baseline_month']} → {plan['target_month']} に{plan['multiple']:.0f}倍。詳細: docs/growth-plan.md")
    print("GROWTH_OK=yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
