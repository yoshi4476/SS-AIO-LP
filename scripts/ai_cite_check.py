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
    # Cloudflare 配下のAPIは Python の既定の UA を弾く（2026-07-28 Resend で error 1010）
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)", **headers})
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


LIMITS = ROOT / "data" / "ai_cache" / "_limits.json"


class UsageLimit(RuntimeError):
    """サブスクの利用上限。until（datetime）まで呼んでも失敗する"""
    def __init__(self, engine, until):
        super().__init__(f"{engine} は利用上限です（{until:%m-%d %H:%M} まで）")
        self.engine, self.until = engine, until


def limit_until(engine):
    """記録された上限の終わり（過ぎていれば None）"""
    from datetime import datetime
    try:
        t = datetime.fromisoformat(json.loads(LIMITS.read_text(encoding="utf-8"))[engine])
        return t if t > datetime.now() else None
    except Exception:
        return None


def _note_limit(engine, text):
    """「try again at 2:53 AM」から再開時刻を読み、記録する。読めなければ1時間後とする
    （2026-10-03: 上限に気づかず50問ずつ失敗し続け、17業種の ChatGPT の回答が0件のまま完了扱いになった）"""
    from datetime import datetime, timedelta
    now = datetime.now()
    until = now + timedelta(hours=1)
    m = re.search(r"try again at (\d{1,2}):(\d{2})\s*(AM|PM)", text or "", re.I)
    if m:
        h = int(m.group(1)) % 12 + (12 if m.group(3).upper() == "PM" else 0)
        until = now.replace(hour=h, minute=int(m.group(2)), second=0, microsecond=0)
        if until <= now:
            until += timedelta(days=1)
    until += timedelta(minutes=5)
    try:
        d = json.loads(LIMITS.read_text(encoding="utf-8")) if LIMITS.is_file() else {}
    except Exception:
        d = {}
    d[engine] = until.isoformat(timespec="minutes")
    LIMITS.parent.mkdir(parents=True, exist_ok=True)
    LIMITS.write_text(json.dumps(d), encoding="utf-8")
    return until


def ask_chatgpt_codex(q):
    """ChatGPT のサブスク（Codex CLI の Web検索）で聞く。課金APIは使わない。
    出典は構造で返らないので、参照したURLを1行ずつ書かせて拾う（本文中のリンクも拾う）"""
    import shutil
    import subprocess
    import tempfile
    exe = shutil.which("codex") or shutil.which("codex.cmd")
    if not exe:
        return None
    until = limit_until("ChatGPT")
    if until:
        raise UsageLimit("ChatGPT", until)
    prompt = (f"次の質問に、Web検索をして日本語で答えてください。\n質問: {q}\n\n"
              "答えの最後に、検索で見て根拠にしたページのURLを全部、1行に1つずつ `SOURCE: <URL>` の形で書いてください。")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        # 指示は標準入力で渡す（Windows の codex.cmd は引数の改行で切れる）
        r = subprocess.run([exe, "--search", "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only",
                            "-c", 'model_reasoning_effort="low"', "-"], input=prompt, cwd=tmp, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=420)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "")
        if "usage limit" in err.lower():
            raise UsageLimit("ChatGPT", _note_limit("ChatGPT", err))
        raise RuntimeError(f"codex exec が失敗しました: {err[-160:]}")
    out = r.stdout or ""
    TEXT[("ask_chatgpt_codex", q)] = out
    urls = re.findall(r"SOURCE:\s*<?(https?://[^\s>)]+)", out) or re.findall(r"\]\((https?://[^)\s]+)\)", out)
    return list(dict.fromkeys(urls))


def subscription_engines():
    """課金APIを使わない聞き方: ChatGPT（サブスクの Codex）・Gemini（無料枠のAPIキー）・Claude（サブスクの Claude Code）"""
    out = {}
    import shutil
    if shutil.which("codex") or shutil.which("codex.cmd"):
        out["ChatGPT"] = _cached("ChatGPT-sub", ask_chatgpt_codex)
    # Gemini は入れない。検索つき回答は無料枠では使えず（公式の料金表: Free Tier は "Not available"。2026-10-04 確認）、
    # 月5,000回までの検索料0円は AI診断と自動処理で分け合う。この聞き方を使う業種調査（月約1,700問）は量が多すぎる
    if _claude_cli_ready():
        out["Claude"] = _cached("Claude-sub", ask_claude_cli)
    return out


GEMINI = {"usage": None, "local": 0}
GEMINI_PER_CALL = 10        # 1回の質問で行われうる検索の見込み。残りがこれ未満なら呼ばない


def gemini_budget_ok():
    """月の検索回数の残りがあるか（管制塔の台帳で AI診断と合わせて数える）。台帳に届かなければ呼ばない"""
    if not _env("GEMINI_API_KEY") or _env("GEMINI_OFF") == "1":
        return False
    if GEMINI["usage"] is None:
        try:
            import hub_client
            u = hub_client._post({"action": "gemini_usage"}) or {}
        except Exception:
            u = {}
        GEMINI["usage"] = u if u.get("ok") else {}
    u = GEMINI["usage"]
    if not u:
        return False
    n = GEMINI["local"] + GEMINI_PER_CALL
    return u["batch"] + n <= u["batchCap"] and u["total"] + n <= u["monthCap"]


def gemini_note(searches):
    """実際に行われた検索の回数を台帳に残す（料金は検索1回ごと。1つの質問で何回も検索されうる）"""
    GEMINI["local"] += searches
    try:
        import hub_client
        hub_client._post({"action": "gemini_log", "job": Path(sys.argv[0]).stem, "searches": searches})
    except Exception:
        pass


def ask_gemini(q):
    key = _env("GEMINI_API_KEY")
    if not key or not gemini_budget_ok():
        return None
    # モデル名は変わる。gemini-2.5-flash は新規利用が止まり404になった（2026-09-23）。
    # 環境変数で差し替えられるようにして、次に変わったとき直さずに済ませる
    model = _env("GEMINI_MODEL") or "gemini-3.6-flash"
    d = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
              {"contents": [{"parts": [{"text": q}]}], "tools": [{"google_search": {}}]}, {})
    gemini_note(max(1, sum(len((c.get("groundingMetadata") or {}).get("webSearchQueries") or [])
                           for c in d.get("candidates", []))))
    TEXT[("ask_gemini", q)] = "".join(pt.get("text", "") for c in d.get("candidates", [])
                                      for pt in ((c.get("content") or {}).get("parts") or []))
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
    # 2026-10 に旧 /chat/completions（sonar）は 403 になり、Agent API の /v1/responses へ移った。
    # 出典は output の search_results に入る
    d = _post("https://api.perplexity.ai/v1/responses",
              {"preset": "fast", "input": q},
              {"Authorization": f"Bearer {key}"})
    urls = []
    for o in d.get("output") or []:
        for s in o.get("results") or []:
            if s.get("url"):
                urls.append(s["url"])
        for c in o.get("content") or []:
            for an in c.get("annotations") or []:
                if an.get("url"):
                    urls.append(an["url"])
    return urls


def ask_claude(q):
    """Claude（Anthropic Messages API + web_search）。出典は web_search_result の url"""
    # ANTHROPIC_API_KEY は入れると記事の執筆が従量課金に切り替わるスイッチなので、計測は別の名前にする
    key = _env("CLAUDE_CITE_API_KEY")
    if not key:
        return ask_claude_cli(q)
    model = _env("ANTHROPIC_MODEL") or "claude-sonnet-5-5"
    d = _post("https://api.anthropic.com/v1/messages",
              {"model": model, "max_tokens": 1024,
               "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
               "messages": [{"role": "user", "content": q}]},
              {"x-api-key": key, "anthropic-version": "2023-06-01"})
    urls = []
    for blk in d.get("content", []):
        if blk.get("type") == "web_search_tool_result":
            for r in blk.get("content", []) or []:
                if isinstance(r, dict) and r.get("url"):
                    urls.append(r["url"])
        for c in blk.get("citations", []) or []:
            if isinstance(c, dict) and c.get("url"):
                urls.append(c["url"])
    return urls


def ask_claude_cli(q):
    """鍵が無ければ Claude Code（サブスク）に検索させる。CI は CLAUDE_CODE_OAUTH_TOKEN で動く。
    API の web_search と違い出典は構造で返らないので、使った出典を1行ずつ書かせて拾う"""
    import shutil
    import subprocess
    import tempfile
    exe = shutil.which("claude") or shutil.which("claude.cmd")
    if not exe or (os.environ.get("GITHUB_ACTIONS") and not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")):
        return None
    prompt = (f"次の質問に、Web検索をして日本語で答えてください。\n質問: {q}\n\n"
              "答えの最後に、検索で見て根拠にしたページのURLを全部、1行に1つずつ "
              "`SOURCE: <URL>` の形で書いてください。")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        # 質問は標準入力で渡す。Windows の claude.cmd は改行を含む引数を途中で切り、出典の指示が届かなかった
        r = subprocess.run([exe, "-p", "--allowedTools", "WebSearch",
                            "--model", _env("CLAUDE_CITE_MODEL") or "claude-sonnet-5-5"],
                           input=prompt, cwd=tmp, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"claude -p が失敗しました: {(r.stderr or r.stdout)[:120]}")
    TEXT[("ask_claude_cli", q)] = r.stdout or ""
    return re.findall(r"SOURCE:\s*<?(https?://[^\s>]+)", r.stdout)


def ask_grok(q):
    """Grok（xAI Chat Completions + Live Search）。出典は citations"""
    key = _env("XAI_API_KEY")
    if not key:
        return None
    model = _env("XAI_MODEL") or "grok-4"
    d = _post("https://api.x.ai/v1/chat/completions",
              {"model": model, "messages": [{"role": "user", "content": q}],
               "search_parameters": {"mode": "on", "return_citations": True}},
              {"Authorization": f"Bearer {key}"})
    return [u for u in (d.get("citations") or []) if isinstance(u, str)]


# 検索つきのAI。鍵があるものだけ使う（無ければ飛ばす）。Google以外も全部ここに並べる
ENGINES = {"ChatGPT": ask_openai, "Gemini": ask_gemini, "Perplexity": ask_perplexity,
           "Claude": ask_claude, "Grok": ask_grok}
ENGINE_KEYS = {"ChatGPT": "OPENAI_API_KEY", "Gemini": "GEMINI_API_KEY", "Perplexity": "PERPLEXITY_API_KEY",
               "Claude": "CLAUDE_CITE_API_KEY", "Grok": "XAI_API_KEY"}


CACHE_DIR = ROOT / "data" / "ai_cache"
CACHE_DAYS = 30


TEXT = {}          # (関数名, 質問) → 答えの本文。出典URLだけでなく「何と答えたか」を数える調査が使う
NEED_TEXT = False  # True のとき、本文の無い古いキャッシュは使わずに聞き直す


def answer_text(fn, q):
    return TEXT.get((getattr(fn, "__name__", fn), q), "")


def cache_file(name, q, site=None):
    """答えの置き場。お客様の社（site）の質問は public に置かない（client_private の置き場の data/ai_cache/）。
    お客様向けの質問文と答えが public に残っていた（2026-10-08 の点検）"""
    import hashlib
    p = CACHE_DIR / name / (hashlib.md5(("%s\n%s" % (name, q)).encode("utf-8")).hexdigest() + ".json")
    if site:
        import client_private as CP
        if CP.is_private(site):
            return CP.private_path(site, f"data/ai_cache/{name}/{p.name}")
    return p


def _cache_files(name, q, site=None):
    """読む順。お客様の社は置き場を先に見て、無ければ public（自社の工程が同じ語を聞いた答え）も使う"""
    own = cache_file(name, q, site)
    pub = cache_file(name, q)
    return [own] if own == pub else [own, pub]


def cached(name, q, days=CACHE_DAYS, site=None):
    """キャッシュにある答え（出典URL）。無い・古いなら None。
    課金の前に「この問いは新しく聞くことになるか」を数えるため（compete の月の上限）。days=None は古さを問わない"""
    import time as _t
    for p in _cache_files(name, q, site):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if days is not None and _t.time() - d.get("at", 0) >= days * 86400:
            continue
        return d.get("urls") or []
    return None


def _cached(name, fn, site=None):
    """同じエンジンに同じ質問をしたら、30日は前の答え（出典URL）を使う。
    語の調査（ai_kw_research）・引用の実測（週次/月次）・共起語（cooccur）が同じ語を
    別々に聞いていて、同じ課金を何度もしていた。失敗（例外）はキャッシュしない。
    答えの本文も残す（読み分けの根拠を後から確かめられるように）。site がお客様の社なら答えは置き場へ"""
    import time as _t

    def wrap(q):
        for p in _cache_files(name, q, site):
            if not p.is_file():
                continue
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                if _t.time() - d.get("at", 0) < CACHE_DAYS * 86400 and (d.get("text") or not NEED_TEXT):
                    if d.get("text"):
                        TEXT[(fn.__name__, q)] = d["text"]
                    return d.get("urls") or []
            except Exception:
                pass
        urls = fn(q)
        if urls is not None:
            p = cache_file(name, q, site)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"q": q, "at": _t.time(), "urls": urls, "text": answer_text(fn, q)},
                                    ensure_ascii=False), encoding="utf-8")
        return urls
    wrap.__name__ = fn.__name__
    return wrap


def engines_available(site=None):
    """聞けるAI。site（どの社の質問か）を渡すと、お客様の社の答えは public に置かない"""
    return {k: _cached(k, v, site=site) for k, v in ENGINES.items()
            if (_env(ENGINE_KEYS[k]) or (k == "Claude" and _claude_cli_ready()))
            and (k != "Gemini" or gemini_budget_ok())}     # 検索つきは有料。月の検索回数の残りがあるときだけ


def _claude_cli_ready():
    """鍵が無くても、サブスクの Claude Code が使えれば Claude も測る"""
    import shutil
    if not (shutil.which("claude") or shutil.which("claude.cmd")):
        return False
    return not os.environ.get("GITHUB_ACTIONS") or bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))


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
    engines = engines_available()
    if not engines:
        print("AI_CITE=skipped（APIキーが無い: " + " / ".join(ENGINE_KEYS.values()) + " のどれか）")
        return 0
    print(f"■ 引用の実測: エンジン {', '.join(engines)} / 1サイト{a.limit}語まで")
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{date.today():%Y-%m}.json"
    # お客様の社の分（語・出典）は public に置かず data/clients/<id>/private/ に分けてある（読むときに合わせる）
    import client_private as CP
    d = CP.load_citations(p.name)
    d.setdefault("date", date.today().isoformat())
    measured = d.setdefault("measured", {"date": date.today().isoformat(), "engines": list(engines), "sites": {}})
    measured.setdefault("sites", {})
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
        site_engines = engines_available(site=sid)      # お客様の社の答えは置き場へ
        for q in qs:
            row = {"kw": q, "engines": {}}
            hit = False
            for name, fn in site_engines.items():
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
    CP.save_citations(p.name, d)
    print(f"AI_CITED={total_cited}/{total_q}")
    print(f"記録: {p.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
