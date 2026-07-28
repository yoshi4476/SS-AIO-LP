# -*- coding: utf-8 -*-
"""KW候補を実データから発掘する（有料ツール不要）

使い方:
    python scripts/kw_discover.py           # 候補を表示するだけ
    python scripts/kw_discover.py --append  # docs/industry-pillar-plan.md へ追記

2つの無料の実データソースを使う:
  1. Google Search Console API — 自サイトが実際に表示されたクエリ。
     「表示はされているが専用記事がない」= 需要が実証済みの最優先KW。
  2. Googleサジェスト — 実際の検索行動から生成される候補。
     サジェストに出る = 一定の検索需要がある証拠（推測ではない）。

既存記事と重複するKWは cannibal_check の類似度で除外するため、
補充されたKWをそのまま書いてもカニバリにならない。
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cannibal_check import dice, load_articles  # noqa: E402
from kw_status import is_written, plan_keywords, written_corpus  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "docs" / "industry-pillar-plan.md"
DUP_THRESHOLD = 0.50
MAX_APPEND = 30
UA = {"User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"}

# サジェスト展開の起点（業種 × 課題）。実サイトのテーマに直結する語だけを使う
INDUSTRIES = ["クリニック", "歯科医院", "整骨院", "税理士", "士業", "工務店",
              "リフォーム", "不動産", "美容室", "飲食店"]
INTENTS = ["集客", "MEO対策", "SEO", "AI検索 対策", "口コミ 増やす", "ホームページ"]
PER_SEED = 4  # 1つの起点から採用する上限（特定業種に偏らせない）

# サジェストは表記ゆれ・ブランド名・無関係語を含むため、自社テーマの語を必ず1つ含むものだけ残す
DOMAIN_TERMS = ("集客", "集患", "meo", "seo", "aio", "llmo", "ai", "口コミ", "レビュー",
                "ホームページ", "hp", "ウェブ", "web", "サイト", "対策", "方法", "やり方",
                "増やす", "費用", "相場", "事例", "マップ", "google", "グーグル", "sns",
                "インスタ", "広告", "予約", "新規", "リピート", "患者", "顧客", "問い合わせ")
# 検索者が自社の見込み客でないKW（求職・ブランド固有名など）は除外する
NG_TERMS = ("求人", "転職", "バイト", "年収", "給料", "採用", "ceo", "セオリー", "湘南",
            "とは何", "英語", "意味")


def load_env():
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def gsc_queries():
    """GSCで表示実績のあるクエリ（実データ）。未設定なら空リスト"""
    sa = ROOT / "indexing-service-account.json"
    env = load_env()
    site = env.get("GSC_SITE_URL", "https://ai.7senses.co.jp/")
    if not sa.exists():
        return []
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds = service_account.Credentials.from_service_account_file(
            str(sa), scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
        sc = build("searchconsole", "v1", credentials=creds)
        res = sc.searchanalytics().query(siteUrl=site, body={
            "startDate": (date.today() - timedelta(days=90)).isoformat(),
            "endDate": date.today().isoformat(),
            "dimensions": ["query"], "rowLimit": 200}).execute()
        return [{"kw": r["keys"][0], "imp": int(r["impressions"]),
                 "pos": round(r["position"], 1)} for r in res.get("rows", [])]
    except Exception as e:
        print(f"（GSC取得スキップ: {e}）")
        return []


def suggest(q):
    """Googleサジェスト（認証不要・無料）"""
    u = ("https://suggestqueries.google.com/complete/search?client=firefox&hl=ja&q="
         + urllib.parse.quote(q))
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=15) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))[1]
    except Exception:
        return []


def is_dup(kw, arts, seen):
    if any(dice(kw, s) >= 0.75 for s in seen):
        return True
    return any(dice(kw, a["title"]) >= DUP_THRESHOLD for a in arts)


def main():
    arts = load_articles()
    corpus = written_corpus()
    planned = {k for _, k in plan_keywords()}
    seen = set(planned)
    proven, discovered = [], []

    # --- 1. GSC実データ（表示実績あり・記事なし = 最優先）---
    for q in gsc_queries():
        kw = q["kw"]
        if is_written(kw, corpus) or is_dup(kw, arts, seen):
            continue
        seen.add(kw)
        proven.append(q)
    proven.sort(key=lambda q: -q["imp"])

    # --- 2. Googleサジェスト（検索需要の裏付けあり）---
    for ind in INDUSTRIES:
        for it in INTENTS:
            picked = 0
            for s in suggest(f"{ind} {it}"):
                s = s.strip()
                low = s.lower()
                # 起点そのもの・短すぎる語・既出は除外し、ロングテールだけ残す
                if len(s) < 6 or s == f"{ind} {it}" or is_written(s, corpus):
                    continue
                # 業種語を含み、自社テーマの語を1つ以上含み、除外語を含まないものだけ採用
                if ind not in s or not any(t in low for t in DOMAIN_TERMS):
                    continue
                if any(t in low for t in NG_TERMS):
                    continue
                if is_dup(s, arts, seen):
                    continue
                seen.add(s)
                discovered.append(s)
                picked += 1
                if picked >= PER_SEED:
                    break
            time.sleep(0.2)  # サジェストAPIへの配慮

    print(f"KW_DISCOVER: GSC実証={len(proven)}件 / サジェスト発掘={len(discovered)}件")
    if proven:
        print("\n■ 表示実績あり・記事なし（最優先で執筆する）")
        for q in proven[:15]:
            print(f"  - {q['kw']}  （表示{q['imp']}回・平均{q['pos']}位）")
    if discovered:
        print("\n■ サジェスト由来の新規候補（検索需要の裏付けあり）")
        for s in discovered[:20]:
            print(f"  - {s}")

    if "--append" in sys.argv:
        picks = [q["kw"] for q in proven[:10]] + discovered
        picks = picks[:MAX_APPEND]
        if not picks:
            print("\n追記対象なし（新規候補が見つかりませんでした）")
            return
        line = (f"\n**自動補充 {date.today().isoformat()}"
                f"（GSC実証{len(proven[:10])}件+サジェスト{len(picks) - len(proven[:10])}件・{len(picks)}本）**: "
                + " / ".join(picks) + "\n")
        with PLAN.open("a", encoding="utf-8") as f:
            f.write(line)
        print(f"\ndocs/industry-pillar-plan.md へ {len(picks)}件を追記しました")


if __name__ == "__main__":
    main()
