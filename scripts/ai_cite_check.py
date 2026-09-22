# -*- coding: utf-8 -*-
"""AI検索に本当に引用されているかを、AIに聞いて確かめる（推定ではなく実測）。

ai_citation_check.py は GSC の CTR の歪みから「取られている疑い」を出すだけで、
引用の有無は分からなかった（cited: None）。ここでは主要な検索語を検索つきのAIに
投げ、回答の出典に自社URLが入るかを記録する。

使うエンジン（キーがあるものだけ。無ければ飛ばす）:
  OPENAI_API_KEY      … ChatGPT（Responses API + web_search）
  GEMINI_API_KEY      … Gemini（Google 検索グラウンディング）
  PERPLEXITY_API_KEY  … Perplexity（sonar）

課金の上限: 1回の実行で MAX_QUERIES 語 × エンジン数。月1回。試行錯誤で本番を叩かない
（`--limit 1` で1語だけ試して応答の形を見る）。

  python scripts/ai_cite_check.py                 # 全サイト・各20語
  python scripts/ai_cite_check.py --site ai-lab --limit 1
結果: data/ai_citations/YYYY-MM.json の "measured" に足す。AI_CITED=<引用数>/<語数> を出す。
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "data" / "ai_citations"
RANKS = ROOT / "data" / "ranks"
MAX_QUERIES = 20          # 1サイト1回あたり
TIMEOUT = 90


def _env(key):
    v = os.environ.get(key, "")
    if v:
        return v.strip()
    env = ROOT / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _post(url, body, headers, timeout=TIMEOUT):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 何が悪いか（モデル名・ツール名・キーの制限）は本文にしか書かれていない
        body = e.read().decode("utf-8", "ignore")[:300].replace(chr(10), " ")
        # 何が悪いかで対処が違う。まとめて「失敗」にすると原因が分からない
        hint = {404: "モデル名が古い（GEMINI_MODEL で指定できます）",
                429: "枠切れ。検索つきの呼び出しは無料枠では足りません",
                503: "一時的な混雑。しばらく待つと通ります",
                401: "鍵が正しくありません",
                403: "鍵に権限がありません"}.get(e.code, "")
        raise RuntimeError(f"HTTP {e.code}: {hint}｜{body}") from None


def _mark(r):
    """引用の有無と、失敗なら理由の要点。対処が違うので区別して出す"""
    if r.get("cited"):
        return "引用"
    e = str(r.get("error") or "")
    if not e:
        return "無"
    for code, label in (("429", "枠切れ"), ("503", "混雑"), ("404", "モデル名"), ("401", "鍵"), ("403", "権限")):
        if code in e:
            return label
    return "失敗"


def _final_url(u):
    """Gemini の出典はリダイレクトURL。実際の行き先まで追う"""
    try:
        req = urllib.request.Request(u, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.geturl()
    except Exception:
        return u


def ask_openai(q):
    key = _env("OPENAI_API_KEY")
    if not key:
        return None
    d = _post("https://api.openai.com/v1/responses",
              {"model": "gpt-4.1-mini", "tools": [{"type": "web_search_preview"}], "input": q},
              {"Authorization": f"Bearer {key}"})
    urls = []
    for o in d.get("output", []):
        for c in o.get("content", []) or []:
            for a in c.get("annotations", []) or []:
                if a.get("type") == "url_citation" and a.get("url"):
                    urls.append(a["url"])
    return urls


def ask_gemini(q):
    key = _env("GEMINI_API_KEY")
    if not key:
        return None
    # モデル名は変わる。gemini-2.5-flash は新規利用が止まり404になった（2026-09-23）。
    # 環境変数で差し替えられるようにして、次に変わったとき直さずに済ませる
    model = _env("GEMINI_MODEL") or "gemini-3.6-flash"
    d = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
              {"contents": [{"parts": [{"text": q}]}], "tools": [{"google_search": {}}]}, {})
    urls = []
    for cand in d.get("candidates", []):
        for ch in (cand.get("groundingMetadata") or {}).get("groundingChunks", []) or []:
            u = (ch.get("web") or {}).get("uri")
            if u:
                urls.append(_final_url(u) if "grounding-api-redirect" in u else u)
    return urls


def ask_perplexity(q):
    key = _env("PERPLEXITY_API_KEY")
    if not key:
        return None
    d = _post("https://api.perplexity.ai/chat/completions",
              {"model": "sonar", "messages": [{"role": "user", "content": q}]},
              {"Authorization": f"Bearer {key}"})
    urls = list(d.get("citations") or [])
    for s in d.get("search_results") or []:
        if s.get("url"):
            urls.append(s["url"])
    return urls


ENGINES = {"ChatGPT": ask_openai, "Gemini": ask_gemini, "Perplexity": ask_perplexity}


def queries_for(site_id, limit):
    """表示が多く、20位以内にいる語（引用の前提は上位表示）。

    **指名検索は外す。** 社名で聞けば自社が出るのは当たり前で、引用されて
    いるかの測定にならない。実際、コーポレートは3語とも「セブンセンシズ」で、
    しかも重複していた（2026-09-23）。課金して無意味な質問を投げるところだった。
    表記ゆれを吸収して重複も落とす。
    """
    f = RANKS / f"{site_id}.json"
    if not f.is_file():
        return []
    hist = json.loads(f.read_text(encoding="utf-8"))
    rows = hist[sorted(hist)[-1]]
    rows = [r for r in rows if r.get("pos", 99) <= 20 and len(r.get("kw", "")) >= 3]
    rows.sort(key=lambda r: -r.get("imp", 0))
    try:
        import brand_search
        brand = brand_search.BRAND
    except Exception:
        brand = None
    seen, out = set(), []
    for r in rows:
        kw = r["kw"]
        if brand is not None and brand.search(kw):
            continue                       # 指名検索は測る意味がない
        key = re.sub(r"[\s　・･／/（）()｜|【】\[\]「」、。,.\-‐－—ー_]", "", kw.lower())
        if key in seen:
            continue                       # 表記ゆれの重複
        seen.add(key)
        out.append(kw)
        if len(out) >= limit:
            break
    return out


def domain_of(u):
    m = re.match(r"https?://([^/]+)", u or "")
    return (m.group(1) if m else "").lower().replace("www.", "")


def main():
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--limit", type=int, default=MAX_QUERIES)
    a = ap.parse_args()
    engines = {k: v for k, v in ENGINES.items() if _env({"ChatGPT": "OPENAI_API_KEY", "Gemini": "GEMINI_API_KEY", "Perplexity": "PERPLEXITY_API_KEY"}[k])}
    if not engines:
        print("AI_CITE=skipped（APIキーが無い: OPENAI_API_KEY / GEMINI_API_KEY / PERPLEXITY_API_KEY のどれか）")
        return 0
    print(f"■ 引用の実測: エンジン {', '.join(engines)} / 1サイト{a.limit}語まで")
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{date.today():%Y-%m}.json"
    d = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"date": date.today().isoformat(), "sites": {}}
    measured = d.setdefault("measured", {"date": date.today().isoformat(), "engines": list(engines), "sites": {}})
    total_q = total_cited = 0
    for sid, cfg in S.load_all().items():
        if a.site and sid != a.site:
            continue
        dom = cfg["domain"].lower().replace("www.", "")
        qs = queries_for(sid, a.limit)
        if not qs:
            print(f"   {sid}: 順位の記録が無く語を選べません（rank_track を先に）")
            continue
        items, cited = [], 0
        for q in qs:
            row = {"kw": q, "engines": {}}
            hit = False
            for name, fn in engines.items():
                try:
                    urls = fn(q) or []
                except Exception as e:
                    row["engines"][name] = {"error": str(e)[:80]}
                    continue
                ours = [u for u in urls if domain_of(u) == dom]
                row["engines"][name] = {"cited": bool(ours), "ours": ours[:3],
                                        "sources": sorted({domain_of(u) for u in urls})[:8]}
                hit = hit or bool(ours)
            row["cited"] = hit
            cited += hit
            items.append(row)
            print(f"   {'○' if hit else '－'} {q[:30]:<30} " + " ".join(
                f"{n}:{_mark(r)}" for n, r in row["engines"].items()))
        measured["sites"][sid] = {"queries": len(qs), "cited": cited, "items": items}
        total_q += len(qs); total_cited += cited
        print(f"   {cfg['name']}: 引用 {cited}/{len(qs)}語")
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"AI_CITED={total_cited}/{total_q}")
    print(f"記録: {p.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
