# -*- coding: utf-8 -*-
"""3か月ごとの業種調査（data/research/<業種>-summary.json）を、前回の回と比べる。

見るのは2つ: 出典の種類の割合の変化（ポイント差）と、上位ドメイン（portal_top）の入れ替わり。
数字は集計そのものから出す（推定・補正はしない）。

前回の値は git の履歴から取る（控えを別に持つと、控えと本体がずれる）。
今の作業ツリーの値と、調査日（date）が MIN_DAYS 日以上前の版のうち最も新しいものを比べる。
同じ回の途中の版（数日違い）を前回と取り違えないため。

比べ方の前提:
- 種類の割合は、両方の回で答えたAIだけで数える（by_engine）。前回 ChatGPT が利用上限で
  0件だった回と比べると、AIの顔ぶれの違いが「出典の変化」に見えてしまうため
- 回答の数（answered の合計）が MIN_ANSWERS 未満の回は比べない（数件の差で割合が大きく動く）

  python scripts/research_diff.py                 # docs/research-diff-<YYYY-MM>.md を書く
  python scripts/research_diff.py --min-days 0    # 同じ回の途中の版とも比べる（動作確認用）
"""
import argparse
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESEARCH = ROOT / "data" / "research"
DOCS = ROOT / "docs"
MIN_DAYS = 45        # 3か月ごとの回。同じ回の途中の版（数日違い）は前回にしない
MIN_ANSWERS = 20
MOVE_PT = 5.0        # 要約に出す変化の大きさ（ポイント）
LABEL = {"clinic": "事業者の公式サイト", "portal": "予約・比較・紹介サイト", "review": "口コミ・地図",
         "public": "公的機関・業界団体", "maker": "メーカー・企業", "media": "ニュース・メディア・まとめ記事",
         "video": "動画・SNS", "wiki": "百科事典", "other": "その他"}


def _git(*args):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout if r.returncode == 0 else ""


def _d(s):
    try:
        return date.fromisoformat(str(s.get("date"))[:10])
    except (ValueError, TypeError, AttributeError):
        return None


def deepen(since):
    """CI の checkout は履歴1件だけ（shallow）。前回の回まで取り寄せる。失敗しても止めない"""
    if _git("rev-parse", "--is-shallow-repository").strip() == "true":
        _git("fetch", "-q", f"--shallow-since={since.isoformat()}", "origin")


def previous(path, cur, min_days=MIN_DAYS):
    """git の履歴から、調査日が cur より min_days 日以上前の版のうち最も新しいもの"""
    cd = _d(cur)
    if not cd:
        return None
    rel = path.relative_to(ROOT).as_posix()
    for h in _git("log", "--format=%H", "--", rel).split():
        try:
            s = json.loads(_git("show", f"{h}:{rel}") or "null")
        except json.JSONDecodeError:
            continue
        pd = _d(s) if isinstance(s, dict) else None
        if pd and (cd - pd).days >= min_days:
            return s
    return None


def answers(s):
    return sum((s.get("answered") or {}).values())


def shares(s, engines):
    """指定したAIだけで数えた、出典の種類の割合（%）と出典の件数"""
    c = {}
    for e in engines:
        for k, n in ((s.get("by_engine") or {}).get(e) or {}).items():
            c[k] = c.get(k, 0) + n
    tot = sum(c.values())
    return ({k: n * 100 / tot for k, n in c.items()} if tot else {}), tot


def compare(prev, cur, min_answers=MIN_ANSWERS):
    """前回と今回の差。比べられなければ reason だけを返す"""
    if not prev:
        return {"reason": "前回の回がありません"}
    na, nb = answers(prev), answers(cur)
    if na < min_answers or nb < min_answers:
        return {"reason": f"回答が少ないため比べません（前回{na}・今回{nb}、{min_answers}未満）"}
    common = sorted(set((prev.get("by_engine") or {})) & set((cur.get("by_engine") or {}))
                    & {e for e, n in (prev.get("answered") or {}).items() if n}
                    & {e for e, n in (cur.get("answered") or {}).items() if n})
    if not common:
        return {"reason": "両方の回で答えたAIがありません"}
    sa, ta = shares(prev, common)
    sb, tb = shares(cur, common)
    rows = sorted(({"type": k, "prev": round(sa.get(k, 0), 1), "cur": round(sb.get(k, 0), 1),
                    "pt": round(sb.get(k, 0) - sa.get(k, 0), 1)} for k in set(sa) | set(sb)),
                  key=lambda r: (-abs(r["pt"]), r["type"]))
    top_a = [d for d, _ in (prev.get("portal_top") or [])]
    top_b = [d for d, _ in (cur.get("portal_top") or [])]
    return {"engines": common, "sources": (ta, tb), "answers": (na, nb), "rows": rows,
            "entered": [d for d in top_b if d not in top_a], "left": [d for d in top_a if d not in top_b],
            "dates": (prev.get("date"), cur.get("date")),
            # 上位サイトは全AIで数えた順位しか残っていない。AIの顔ぶれが違えば入れ替わりにその影響が混ざる
            "mixed": {e for e, n in (prev.get("answered") or {}).items() if n}
            != {e for e, n in (cur.get("answered") or {}).items() if n}}


def markdown(results, month):
    out = [f"# 業種調査の前回との差（{month}）", "",
           "AIの回答の出典を、前回の調査の回と比べた結果です。割合は両方の回で答えたAIだけで数えています"
           f"（AIの顔ぶれの違いを変化と取り違えないため）。回答が{MIN_ANSWERS}未満の回は比べていません。", ""]
    skipped = []
    for slug, name, r in results:
        if "reason" in r:
            skipped.append(f"- {name}（{slug}）: {r['reason']}")
            continue
        (da, db), (ta, tb), (na, nb) = r["dates"], r["sources"], r["answers"]
        out += [f"## {name}（{slug}）", "",
                f"前回 {da}（回答{na}・出典{ta}件）→ 今回 {db}（回答{nb}・出典{tb}件）。比べたAI: {'・'.join(r['engines'])}", "",
                "| 出典の種類 | 前回 | 今回 | 差（ポイント） |", "|:--|--:|--:|--:|"]
        out += [f"| {LABEL.get(x['type'], x['type'])} | {x['prev']}% | {x['cur']}% | {x['pt']:+.1f} |" for x in r["rows"]]
        out += ["", f"上位の紹介・比較サイト（上位10）: 入った {', '.join(r['entered']) or 'なし'} ／ "
                    f"外れた {', '.join(r['left']) or 'なし'}"
                + ("（全AIで数えた順位。AIの顔ぶれが前回と違うため、入れ替わりにはその影響が混ざります）" if r["mixed"] else ""), ""]
    if skipped:
        out += ["## 比べなかった業種", ""] + skipped + [""]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-days", type=int, default=MIN_DAYS)
    ap.add_argument("--no-write", action="store_true", help="標準出力だけ（docs に書かない）")
    a = ap.parse_args()
    paths = sorted(RESEARCH.glob("*-summary.json"))
    deepen(date.today() - timedelta(days=200))
    results = []
    for p in paths:
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        slug = p.name[:-len("-summary.json")]
        results.append((slug, cur.get("name") or slug, compare(previous(p, cur, a.min_days), cur)))
    done = [x for x in results if "reason" not in x[2]]
    print(f"■ 業種調査の前回との差: 比べた業種 {len(done)}/{len(results)}")
    for slug, name, r in done:
        big = [f"{LABEL.get(x['type'], x['type'])} {x['pt']:+.1f}pt" for x in r["rows"] if abs(x["pt"]) >= MOVE_PT]
        swap = len(r["entered"])
        print(f"   {name}: " + ("、".join(big[:3]) or f"{MOVE_PT:.0f}ポイント以上の変化なし")
              + (f"／上位サイトの入れ替わり {swap}件" if swap else ""))
    if not a.no_write:
        month = f"{date.today():%Y-%m}"
        DOCS.mkdir(parents=True, exist_ok=True)
        f = DOCS / f"research-diff-{month}.md"
        f.write_text(markdown(results, month), encoding="utf-8")
        print(f"記録: {f.relative_to(ROOT).as_posix()}")
    print(f"RESEARCH_DIFF={len(done)}/{len(results)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
