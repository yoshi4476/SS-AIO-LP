# -*- coding: utf-8 -*-
"""サイト構成の案を、実測から機械が作る。

**なぜ要るか**: 「次に何を作るか」を人が考えていた。1本ずつ選ぶと、同じ
マスに記事が重なり、空いたマスが残る（実測でクリニック21本・工務店AIO 0本）。
面の欠けは、その分野を扱うサイトとして評価されない直接の原因になる。

盤面（coverage）・止まっている記事（rank_rescue）・達成率（guarantee）を
まとめ、月次レポートに「来月つくるもの」として出す。
提案は次の4種類だけ。どれも実測が根拠で、思いつきは混ぜない。

  新しい記事      空いているマス（業種×手法）から、優先業種を先に
  新しいハブ      記事が5本たまったのにハブが無い業種
  書き足し        1ページ目の手前で止まり、需要のある語に答えていない記事
  統合            同じ語で2ページが競合している組

    python scripts/structure_plan.py            # 案を見る
    python scripts/structure_plan.py --html     # 月次レポート用のHTML
"""
import argparse
import html as H
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

MAX_PER_KIND = 6


def plan(site_id):
    """その サイトで来月やるべきことを、根拠つきで返す"""
    out = []

    # 1) 空いているマス → 新しい記事
    try:
        import coverage as CV
        cells, inds, cs, arts, _ = CV.matrix(site_id)
        rows = []
        for i in inds:
            ind_imp = sum(cells[(i["slug"], c)]["imp"] for c in cs)
            for c in cs:
                n = len(cells[(i["slug"], c)]["slugs"])
                if n > CV.THIN:
                    continue
                score = (3 if i.get("priority") else 0) + (2 if n == 0 else 0)
                score += min(3.0, ind_imp / 200.0)
                rows.append((score, i, c, n, ind_imp))
        rows.sort(key=lambda x: -x[0])
        for score, i, c, n, imp in rows[:MAX_PER_KIND]:
            out.append({
                "kind": "新しい記事",
                "what": f"{i['name']} × {c}",
                "why": (f"いま{n}本。"
                        + (f"この業種は表示{imp:,}回の実績があります。" if imp else "")
                        + ("優先業種です。" if i.get("priority") else "")),
                "how": f"python scripts/kw_guard.py \"{i['name']} {c}\" --site {site_id}",
                "score": round(score, 1),
            })
    except Exception as e:
        out.append({"kind": "盤面", "what": "盤面を作れません",
                    "why": str(e)[:80], "how": "", "score": 0})

    # 2) 記事がたまったのにハブが無い業種 → 新しいハブ
    try:
        import industry_hub as IH
        import json
        d = json.loads((ROOT / "data" / "industries.json").read_text(encoding="utf-8"))
        floor = int(d.get("_min_articles") or 5)
        made = {p.name for p in (ROOT / "site" / "industry").glob("*") if p.is_dir()}
        for i in (d.get("industries") or []):
            n = len(cells and [s for c in cs for s in cells[(i["slug"], c)]["slugs"]] or [])
            if n >= floor and i["slug"] not in made:
                out.append({"kind": "新しいハブ", "what": f"/industry/{i['slug']}/",
                            "why": f"{i['name']} の記事が{n}本たまっています（下限{floor}本）",
                            "how": "python scripts/build.py", "score": 2.0})
    except Exception:
        pass

    # 3) 止まっている記事 → 書き足し
    try:
        import rank_rescue as RR
        rows, _ = RR.diagnose()
        for r in [x for x in rows if x["site"] == site_id][:MAX_PER_KIND]:
            need = "、".join(t for m in r.get("miss", []) for t in m["gap"])[:60]
            out.append({
                "kind": "書き足し", "what": r["title"][:40],
                "why": (f"{r['pos']:.1f}位・表示{r['imp']}回でクリック{r['clk']}回。"
                        + (f"「{need}」に答える節がありません。" if need else "")),
                "how": "python scripts/auto_rewrite.py --write",
                "score": round(r["imp"] / 50.0, 1),
            })
    except Exception:
        pass

    # 4) 食い合い → 統合か差別化
    try:
        import rank_rescue as RR2
        rows2, _ = RR2.diagnose()
        for r in [x for x in rows2 if x["site"] == site_id and x.get("cannibal")][:3]:
            c = r["cannibal"][0]
            rival = c["rival"].rstrip("/").split("/")[-1]
            out.append({
                "kind": "統合の検討", "what": f"{r['title'][:28]} ←→ {rival[:24]}",
                "why": (f"「{c['kw']}」で{c['pos']:.0f}位と{c['rival_pos']:.0f}位。"
                        "同じ語に2ページが出ています。"),
                "how": "python scripts/auto_merge.py",
                "score": round(c["imp"] / 20.0, 1),
            })
    except Exception:
        pass

    out.sort(key=lambda x: -x["score"])
    return out


def as_html(sites=("ai-lab",)):
    parts = ['<h3 style="margin-top:16px">来月つくるもの（実測からの提案）</h3>']
    for sid in sites:
        rows = plan(sid)
        if not rows:
            continue
        parts.append(f'<p style="font-size:9pt;margin:6px 0">対象: {H.escape(sid)}</p>')
        parts.append('<table style="font-size:9pt;width:100%;border-collapse:collapse">'
                     '<tr><th style="text-align:left">種類</th>'
                     '<th style="text-align:left">つくるもの</th>'
                     '<th style="text-align:left">根拠</th></tr>')
        for r in rows[:10]:
            parts.append(
                "<tr>"
                f'<td style="border-top:1px solid #ddd">{H.escape(r["kind"])}</td>'
                f'<td style="border-top:1px solid #ddd">{H.escape(str(r["what"]))}</td>'
                f'<td style="border-top:1px solid #ddd">{H.escape(str(r["why"]))}</td>'
                "</tr>")
        parts.append("</table>")
    parts.append('<p style="font-size:8pt;color:#666">'
                 "※ すべて Search Console の実測と公開記事の集計から機械が作っています。"
                 "着手前に kw_guard（食い合い）と kw_intent（開く理由）を通してください。</p>")
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--html", action="store_true")
    a = ap.parse_args()
    sites = [a.site] if a.site else ["ai-lab", "corporate", "subsidy"]
    if a.html:
        print(as_html(sites))
        return 0
    total = 0
    for sid in sites:
        rows = plan(sid)
        total += len(rows)
        print(f"\n■ {sid} — 来月つくるもの {len(rows)}件\n")
        print(f"{'点':>5}  {'種類':<10}{'つくるもの':<34}根拠")
        for r in rows[:10]:
            print(f"{r['score']:>5.1f}  {r['kind']:<10}{str(r['what'])[:32]:<34}{r['why'][:52]}")
    print(f"\nSTRUCTURE_PLAN={total}")
    print("STRUCTURE_OK=" + ("no" if total else "yes"))
    if total:
        print(f"   ::warning::サイト構成の提案が{total}件あります（月次レポートに載ります）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
