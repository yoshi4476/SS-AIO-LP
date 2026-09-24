# -*- coding: utf-8 -*-
"""AI検索で答えが出る語を、実データから毎週さがし、台帳へ積む。

**なぜ要るか**: AI Overview の表示率は全体で13.7%だが、**質問形のクエリでは64.7%**
（arXiv 2605.14021・55,393クエリ）。AI検索に引用される記事を書くには、
「AIが答えを出す語」を狙って書く必要がある。これまでその調査は人がしていた。

材料は3つ。上から順に確かで、上から順に安い。
  1. GSC の実績     … 自サイトが既に表示されている質問形の語（需要が実証済み・無料）
  2. サジェスト     … 起点（core × 業種）に「とは/方法/違い/費用」を足した候補（無料）
  3. AIに聞く       … 上位の語を検索つきのAI（Gemini）に投げ、誰が出典かを記録する
                       （課金。1サイト --probe 語まで。キーが無ければ飛ばす）

点のつけ方（高いほど先に書く）:
  質問形 +2 / 開く理由（kw_intent）/ 表示回数の対数 / 4〜30位にいる +1〜2 /
  AIが答えを出していて自社が出典に無い +3（取りに行く価値がいちばん高い）

  python scripts/ai_kw_research.py --site ai-lab            # 候補を見る（AIには聞かない）
  python scripts/ai_kw_research.py --all --probe 8          # AIにも聞く（1サイト8語）
  python scripts/ai_kw_research.py --all --probe 8 --append # 台帳へ積む
結果: data/ai_kw/<site>.json と docs/ai-kw-<site>.md。印は AI_KW_OK=yes/no。
"""
import argparse
import json
import math
import re
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "data" / "ai_kw"
DOCS = ROOT / "docs"

# 質問形＝AIが答えを出しやすい形。語尾だけでなく語中でも見る
Q_PAT = re.compile(r"とは|方法|やり方|違い|いつ|いくら|どう|なぜ|何|比較|おすすめ|費用|相場|"
                   r"できる|必要|条件|手順|注意点|デメリット|メリット|対策|理由|選び方|\?|？")
SUFFIXES = ("とは", "方法", "違い", "費用", "注意点", "できない")
MAX_SEEDS = 12          # サジェストを引く起点の上限（無料だが時間がかかる）
MAX_APPEND = 10         # 1回で台帳へ積む上限
BAND = ((4, 10, 1.0), (11, 20, 2.0), (21, 30, 1.0))


def _norm(s):
    return re.sub(r"[\s　・･／/（）()｜|【】\[\]「」、。,.\-‐－—_]", "", str(s).lower())


def score(kw, imp, pos, ai):
    import kw_intent
    pts = 0.0
    if Q_PAT.search(kw):
        pts += 2
    pts += max(-2, min(3, kw_intent.score(kw)[0]))
    pts += math.log10(max(imp, 1) + 1)
    for lo, hi, w in BAND:
        if pos and lo <= pos <= hi:
            pts += w
    if ai and ai.get("answered") and not ai.get("ours"):
        pts += 3
    return round(pts, 1)


def from_gsc(cfg):
    import kw_discover as KD
    rows = KD.gsc_queries(f"https://{cfg['domain']}/")
    return [{"kw": r["kw"], "imp": r["imp"], "pos": r["pos"], "src": "gsc"}
            for r in rows if Q_PAT.search(r["kw"]) and r["imp"] >= 5]


def from_suggest(cfg):
    import kw_discover as KD
    seeds = cfg.get("kw_seeds") or {}
    cores = seeds.get("core") or (cfg.get("owns") or [])[:2]
    inds = (seeds.get("priority") or seeds.get("industries") or [])[:4]
    starts = [f"{i} {c}" for i in inds for c in cores][:MAX_SEEDS] or cores[:MAX_SEEDS]
    out, seen = [], set()
    for s in starts:
        for suf in SUFFIXES:
            for q in KD.suggest(f"{s} {suf}"):
                k = _norm(q)
                if k in seen or not Q_PAT.search(q):
                    continue
                seen.add(k)
                out.append({"kw": q, "imp": 0, "pos": None, "src": "suggest"})
            time.sleep(0.2)
    return out


def in_territory(kw, cfg):
    owns = [o.lower() for o in cfg.get("owns") or []]
    inds = [i.lower() for i in (cfg.get("kw_seeds") or {}).get("industries") or []]
    low = kw.lower()
    return any(o in low for o in owns) or any(i in low for i in inds)


def probe(kw, dom):
    """検索つきのAIに聞き、答えが出たか・出典に自社が入るかを返す"""
    import ai_cite_check as AC
    urls = AC.ask_gemini(kw) or []
    doms = sorted({AC.domain_of(u) for u in urls if u})
    return {"answered": bool(doms), "ours": dom in doms, "sources": doms[:8]}


def research(sid, cfg, probe_n=0):
    import kw_discover as KD
    dom = cfg["domain"].lower().replace("www.", "")
    try:
        import brand_search
        brand = brand_search.BRAND
    except Exception:
        brand = None
    arts = KD.load_articles()
    corpus = KD.written_corpus()
    cands, seen = [], set()
    for r in from_gsc(cfg) + from_suggest(cfg):
        k = _norm(r["kw"])
        if k in seen or len(r["kw"]) < 4:
            continue
        seen.add(k)
        if brand is not None and brand.search(r["kw"]):
            continue                              # 指名検索は調べる意味が無い
        if not in_territory(r["kw"], cfg):
            continue
        r["written"] = bool(KD.is_written(r["kw"], corpus) or KD.is_dup(r["kw"], arts, set()))
        r["ai"] = None
        r["score"] = score(r["kw"], r["imp"], r["pos"], None)
        cands.append(r)
    cands.sort(key=lambda x: -x["score"])

    # AIに聞くのは上位だけ。既に書いた語も聞く（引用されているかは、それ自体が知りたい）
    asked = 0
    if probe_n:
        for r in cands:
            if asked >= probe_n:
                break
            try:
                r["ai"] = probe(r["kw"], dom)
            except Exception as e:
                r["ai"] = {"error": str(e)[:80]}
            asked += 1
            r["score"] = score(r["kw"], r["imp"], r["pos"], r["ai"])
        cands.sort(key=lambda x: -x["score"])
    return cands, asked


def write_docs(sid, cfg, cands, asked):
    DOCS.mkdir(exist_ok=True)
    lines = [f"# AI検索ワード調査: {cfg['name']}（{date.today()}）", "",
             f"候補 {len(cands)}語・AIに聞いた {asked}語。点が高いほど先に書く。", "",
             "| 点 | 語 | 表示 | 順位 | 出所 | AIの答え | 自社が出典 | 既に記事 |", "|--:|:--|--:|--:|:--|:--|:--|:--|"]
    for r in cands[:60]:
        ai = r.get("ai") or {}
        lines.append(f"| {r['score']} | {r['kw']} | {r['imp']} | {r['pos'] or '-'} | {r['src']} | "
                     f"{'出る' if ai.get('answered') else ('-' if not ai else '出ない')} | "
                     f"{'○' if ai.get('ours') else '-'} | {'○' if r['written'] else '-'} |")
    (DOCS / f"ai-kw-{sid}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def append(sid, cands):
    import hub_client as HC
    if not HC.enabled():
        return 0, "HUB_URL 未設定"
    try:
        have = {_norm(k.get("keyword", k) if isinstance(k, dict) else k) for k in HC.all_kw(strict=True)}
    except Exception as e:
        return 0, f"台帳を読めません（{str(e)[:40]}）— 重複を防げないので積まない"
    picks = [r["kw"] for r in cands if not r["written"] and _norm(r["kw"]) not in have][:MAX_APPEND]
    if picks:
        HC.add_kw(sid, picks)
    return len(picks), ""


def main():
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--probe", type=int, default=0, help="AIに聞く語数（1サイト）。0なら聞かない")
    ap.add_argument("--append", action="store_true")
    a = ap.parse_args()
    import ai_cite_check as AC
    if a.probe and not AC._env("GEMINI_API_KEY"):
        print("GEMINI_API_KEY が無いため、AIには聞きません（候補の抽出だけ行います）")
        a.probe = 0
    targets = S.load_all() if a.all or not a.site else {a.site: S.load(a.site)}
    OUT.mkdir(parents=True, exist_ok=True)
    ok, total = True, 0
    for sid, cfg in targets.items():
        try:
            cands, asked = research(sid, cfg, a.probe)
        except Exception as e:
            print(f"   {sid}: 調査できません（{str(e)[:80]}）")
            ok = False
            continue
        (OUT / f"{sid}.json").write_text(json.dumps(
            {"date": date.today().isoformat(), "asked": asked, "items": cands[:200]},
            ensure_ascii=False, indent=2), encoding="utf-8")
        write_docs(sid, cfg, cands, asked)
        gsc = sum(1 for c in cands if c["src"] == "gsc")
        got = sum(1 for c in cands if (c.get("ai") or {}).get("answered"))
        ours = sum(1 for c in cands if (c.get("ai") or {}).get("ours"))
        print(f"■ {cfg['name']}: 候補 {len(cands)}語（GSC {gsc}・サジェスト {len(cands) - gsc}）"
              f" / AIに聞いた {asked}語 → 答えが出る {got}・自社が出典 {ours}")
        for r in cands[:8]:
            ai = r.get("ai") or {}
            print(f"   {r['score']:>4} {r['kw'][:34]:<34} 表示{r['imp']:>5} "
                  f"{('%.0f位' % r['pos']) if r['pos'] else '   -':>5} "
                  f"{'AI:出る' if ai.get('answered') else ''}{'(自社)' if ai.get('ours') else ''}"
                  f"{' 既存' if r['written'] else ''}")
        if a.append:
            n, why = append(sid, cands)
            total += n
            print(f"   台帳へ {n}語を積みました" + (f"（{why}）" if why else ""))
    print(f"AI_KW_OK={'yes' if ok else 'no'}")
    if a.append:
        print(f"AI_KW_ADDED={total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
