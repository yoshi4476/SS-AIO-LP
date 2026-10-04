# -*- coding: utf-8 -*-
"""新しく公開した記事が、公開30日後にAI検索で引用されているかを1回だけ確かめる（週次）。

ai_cite_check は「表示が多く20位以内の語」しか聞かないため、公開したばかりの記事は
順位の記録が育つまで一度も測られなかった。ここでは公開から28〜40日の記事の狙う語
（keyword）を、鍵のあるAIに聞き、出典に自社ドメインが入るかを slug ごとに1回だけ残す。

聞き方は ai_cite_check.engines_available() をそのまま使う（30日キャッシュ・Gemini は
管制塔の台帳で月の検索予算を数える）。新しい呼び出し方は書かない。

新しい記事は30日で引用されないのが普通なので、引用0は「要対応」にしない（情報として出す）。
要対応にするのは、聞いた語がすべて失敗したとき（鍵・枠の問題で、直さないと測れない）。

  python scripts/ai_followup.py --dry          # 対象を見るだけ（AIに聞かない）
  python scripts/ai_followup.py --limit 8      # 確かめて data/ai_citations/followup.json に残す
  python scripts/ai_followup.py --report       # 残した結果を読むだけ（findings.py が呼ぶ）
"""
import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "data" / "ai_citations" / "followup.json"
MIN_AGE, MAX_AGE = 28, 40   # 週次で回すので、窓を2週分とって取りこぼしを防ぐ
LIMIT = 8                   # 1回の実行の上限（語×エンジン数だけ課金・枠を使う）
PUBLISH_SCORE = 90          # build.py が公開する点数の下限。未公開の記事は聞いても出典に出ない


def load():
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {"articles": {}, "last_run": {}}


def save(d):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _date(v):
    try:
        return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def articles():
    """articles/*.md の frontmatter（slug・keyword・date・category・score）"""
    import yaml
    out = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        m = re.match(r"^---\s*\n(.*?)\n---", p.read_text(encoding="utf-8-sig"), re.S)
        if not m:
            continue
        try:
            f = yaml.safe_load(m.group(1)) or {}
        except Exception:
            continue
        out.append({"slug": str(f.get("slug") or p.stem), "keyword": str(f.get("keyword") or "").strip(),
                    "date": _date(f.get("date")), "category": f.get("category"), "score": f.get("score")})
    return out


def targets(items, done, today, limit=LIMIT):
    """公開から28〜40日・公開済み・狙う語あり・まだ確かめていない記事。窓を出そうな古い順に limit 本"""
    out = []
    for a in items:
        if not a.get("date") or not a.get("keyword") or a["slug"] in done:
            continue
        try:
            if float(a.get("score") or 0) < PUBLISH_SCORE:
                continue
        except (TypeError, ValueError):
            continue
        age = (today - a["date"]).days
        if MIN_AGE <= age <= MAX_AGE:
            out.append(a)
    out.sort(key=lambda a: (a["date"], a["slug"]))
    return out[:limit]


def ours(urls, domain):
    """出典のうち自社ドメインのもの。サブドメイン違い（corp. と ai.）は別サイトとして数えない"""
    import ai_cite_check as AC
    dom = domain.lower().replace("www.", "")
    return [u for u in urls if AC.domain_of(u) == dom]


def measure(a, domain, engines):
    """1本分。全エンジンが失敗したら None（記録せず、窓の中なら次の週にもう一度聞く）"""
    import ai_cite_check as AC
    row, ok = {}, False
    for name, fn in engines.items():
        try:
            urls = fn(a["keyword"]) or []
        except Exception as e:
            row[name] = {"error": str(e)[:80]}
            continue
        ok = True
        mine = ours(urls, domain)
        row[name] = {"cited": bool(mine), "ours": mine[:3], "sources": sorted({AC.domain_of(u) for u in urls})[:8]}
    if not ok:
        return None
    return {"engines": row, "cited": any(r.get("cited") for r in row.values())}


def report(d, today, days=35):
    """直近に確かめた分の要約。印は last_run（全件失敗なら no）"""
    recent = {s: r for s, r in d.get("articles", {}).items()
              if (_date(r.get("checked")) or date.min) >= today - timedelta(days=days)}
    cited = [s for s, r in recent.items() if r.get("cited")]
    print(f"■ 新記事の公開30日後のAI引用（直近{days}日に確かめた分）: 引用 {len(cited)}/{len(recent)}本")
    for s in cited[:6]:
        r = recent[s]
        print(f"   ○ {s}（{r.get('kw', '')}）: " + ", ".join(n for n, e in r["engines"].items() if e.get("cited")))
    if recent and not cited:
        print("   情報: 引用はまだ0本です（新しい記事は30日では引用されないのが普通）")
    last = d.get("last_run") or {}
    if last.get("state") == "failed":
        print(f"要対応: 新記事の引用確認が全件失敗しました（{last.get('date')}・{last.get('note', '')}）")
        print("AI_FOLLOWUP_OK=no")
    elif last.get("state") == "no_engine":
        print("AI_FOLLOWUP_OK=unknown（聞けるAIがありません）")
    else:
        print("AI_FOLLOWUP_OK=yes")


def main():
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=LIMIT)
    ap.add_argument("--dry", action="store_true", help="対象を見るだけ（AIに聞かない）")
    ap.add_argument("--report", action="store_true", help="残した結果を読むだけ")
    a = ap.parse_args()
    today = date.today()
    d = load()
    if a.report:
        report(d, today)
        return 0
    done = set(d.get("articles", {}))
    ts = targets(articles(), done, today, a.limit)
    print(f"■ 公開{MIN_AGE}〜{MAX_AGE}日の未確認の記事: {len(ts)}本（上限{a.limit}本）")
    owners = {}
    for t in ts:
        owners[t["slug"]] = S.find_category_owner(t["category"]) if t.get("category") else None
        print(f"   {t['date']} {t['slug']}（{t['keyword']}）→ {owners[t['slug']] or 'サイト不明'}")
    if a.dry or not ts:
        print("AI_FOLLOWUP_OK=yes")
        return 0
    import ai_cite_check as AC
    engines = AC.engines_available()
    if not engines:
        d["last_run"] = {"date": today.isoformat(), "state": "no_engine"}
        save(d)
        print("AI_FOLLOWUP_OK=unknown（聞けるAIがありません: " + " / ".join(AC.ENGINE_KEYS.values()) + "）")
        return 0
    cfgs = S.load_all()
    checked = failed = cited = 0
    for t in ts:
        cfg = cfgs.get(owners[t["slug"]] or "")
        if not cfg:
            continue
        r = measure(t, cfg["domain"], engines)
        if r is None:
            failed += 1
            print(f"   × {t['slug']}: どのAIにも聞けませんでした")
            continue
        checked += 1
        cited += r["cited"]
        d.setdefault("articles", {})[t["slug"]] = {
            "checked": today.isoformat(), "site": owners[t["slug"]], "kw": t["keyword"],
            "published": t["date"].isoformat(), **r}
        print(f"   {'○' if r['cited'] else '－'} {t['slug']} " + " ".join(
            f"{n}:{AC._mark(e)}" for n, e in r["engines"].items()))
    state = "failed" if failed and not checked else "ok"
    d["last_run"] = {"date": today.isoformat(), "state": state, "checked": checked, "failed": failed,
                     "engines": list(engines), "note": "鍵・枠を確認" if state == "failed" else ""}
    save(d)
    print(f"AI_FOLLOWUP={cited}/{checked}（30日で引用されないのは普通。情報として残す）")
    if state == "failed":
        print("AI_FOLLOWUP_OK=no")
    else:
        print("AI_FOLLOWUP_OK=yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
