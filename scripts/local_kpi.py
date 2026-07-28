# -*- coding: utf-8 -*-
"""ローカルKPI集計（公開前でも回る学習ループの土台）

GA4/GSCが未稼働の間も、リポジトリ内の事実だけで kpi_feedback.md の
「サイト概況」「今日の主な動き」を毎実行後に自動更新する。
GA4/GSC稼働後は Daily KPI Report がこのセクションを実データで上書きする。

使い方: python scripts/local_kpi.py （run_pipeline.ps1 の末尾から自動実行）
"""
import re
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CATS = {"aio": "AIO・LLMO", "seo": "SEO", "meo": "MEO", "ai-marketing": "AI集客"}


def load_metas():
    pub, blocked = [], []
    for p in sorted((ROOT / "articles").glob("*.md")):
        if p.name.startswith("_"):
            continue
        text = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
        if not m:
            continue
        meta = yaml.safe_load(m.group(1))
        body = re.sub(r"\s|<[^>]+>", "", re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", m.group(2)))
        meta["_chars"] = len(body)
        (pub if meta.get("score", 0) >= 90 else blocked).append(meta)
    return pub, blocked


def pillar_progress(pub):
    plan = ROOT / "docs" / "industry-pillar-plan.md"
    if not plan.exists():
        return None
    # 計画書のKW行数（3業種×10 = 30想定）に対する公開記事数の目安
    return f"{len(pub)}本 / 目標30本+既存"


def main():
    pub, blocked = load_metas()
    today = date.today()
    week_ago = today - timedelta(days=7)
    recent = [m for m in pub if date.fromisoformat(str(m["date"])) >= week_ago]
    today_posts = [m for m in pub if str(m["date"]) == today.isoformat()]
    cat_counts = "、".join(
        f"{label}{sum(1 for m in pub if m['category'] == c)}本" for c, label in CATS.items())
    avg_score = round(sum(m.get("score", 0) for m in pub) / len(pub), 1) if pub else 0
    avg_chars = round(sum(m["_chars"] for m in pub) / len(pub)) if pub else 0

    overview = f"""## サイト概況

| 指標 | 値 | 備考 |
|:----|:--|:----|
| 累計公開記事数 | {len(pub)}本 | カテゴリ内訳: {cat_counts} |
| 直近7日の公開 | {len(recent)}本 | 目標: 週14本（毎日2本） |
| 品質スコア平均 | {avg_score}点 | 公開基準90点・推奨95点 |
| 平均文字数 | {avg_chars:,}字 | 基準5,000字以上 |
| 非公開（審査未達） | {len(blocked)}本 | {"、".join(m["slug"] for m in blocked) if blocked else "なし"} |
| DR / KW数 / AI計測 | — | GA4・GSC・Ahrefs稼働後に自動反映 |

## 今日の主な動き

- {today.isoformat()} 公開: {"、".join(m["title"] for m in today_posts) if today_posts else "本日分は未公開（8:00/19:00の実行結果を確認）"}
"""

    fb = ROOT / "kpi_feedback.md"
    text = fb.read_text(encoding="utf-8-sig")
    text = re.sub(r"^# KPIフィードバック（自動更新: .*?）",
                  f"# KPIフィードバック（自動更新: {today.isoformat()} ローカル集計）", text, count=1)
    text = re.sub(r"## サイト概況.*?(?=## 成功パターン)", overview + "\n", text, flags=re.S)
    fb.write_text(text, encoding="utf-8")
    print(f"kpi_feedback.md 更新: 公開{len(pub)}本 / 直近7日{len(recent)}本 / 平均{avg_score}点・{avg_chars:,}字")


if __name__ == "__main__":
    main()
