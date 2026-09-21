# -*- coding: utf-8 -*-
"""ラッコキーワードAPIのクライアント

無料のサジェスト取得（suggestqueries）でも候補は集まるが、
検索ボリュームが分からないため「どれから書くか」の判断ができない。
ラッコのAPIはボリューム付きで返すので、優先順位をつけられる。

APIキーは .env の RAKKO_API_KEY。未設定なら黙って何も返さず、
呼び出し側は従来どおり無料のサジェストだけで動く（キー待ちで止めない）。

  仕様: https://api.rakkokeyword.com/docs
  対応プラン: スタンダード（月2,475円〜）以上。API経由はクレジット消費1.5倍。

使い方:
    python scripts/rakko.py "経理代行"            # サジェスト
    python scripts/rakko.py "経理代行" --related  # 関連キーワード
    python scripts/rakko.py --check               # キーが通るかの確認

残クレジットはAPIからは取れない。ラッコの契約管理ページで見ること。
尽きると 402 が返り、そこで打ち切って無料のサジェストに切り替える。
"""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://api.rakkokeyword.com"


def api_key():
    p = ROOT / ".env"
    if not p.is_file():
        return ""
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("RAKKO_API_KEY="):
            v = line.split("=", 1)[1].strip().strip("'\"")
            return "" if v.upper().startswith("YOUR_") else v
    return ""


def enabled():
    return bool(api_key())


# クレジットが尽きると 402 が返る。1件目で分かるのに、残りの起点でも
# 叩き続けていた（38件ぶん無駄に往復する）。一度尽きたら以降は呼ばない。
# リトライでは解消しないため、待っても意味がない
_OUT_OF_CREDIT = False


def exhausted():
    """このプロセスでクレジット切れを踏んだか"""
    return _OUT_OF_CREDIT


RETRY_WAIT = (5, 15, 30)   # 5xx のときの待ち秒。実測で 502/503/504 が数分続いた

# このプロセスで使ったクレジット。自動課金を入れると尽きずに請求が伸びるので、
# 呼び出し側が上限をかけられるように数えておく（応答の meta.consumedCredit を足す）
CONSUMED = 0.0
BUDGET = None      # None なら上限なし。数値を入れると、超えた時点で以降の呼び出しを止める


SPEND_LOG = ROOT / "data" / "rakko_spend.jsonl"   # 1行1回。月の合計を出すため
MONTHLY_BUDGET = 1000                             # 3,000の1/3。超えたら知らせる（止めはしない）


def _log_spend(path, credit):
    if not credit:
        return
    try:
        SPEND_LOG.parent.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        with SPEND_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"),
                                "path": path, "credit": credit}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def month_spent(month=None):
    """その月に使ったクレジット。month は 'YYYY-MM'（省略時は今月）"""
    from datetime import date
    month = month or date.today().strftime("%Y-%m")
    total = 0.0
    if not SPEND_LOG.exists():
        return 0.0
    for ln in SPEND_LOG.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(ln)
            if str(r.get("at", "")).startswith(month):
                total += float(r.get("credit") or 0)
        except Exception:
            continue
    return total


def spent():
    return CONSUMED


def over_budget():
    return BUDGET is not None and CONSUMED >= BUDGET


# 応答をディスクに残す。条件の調整のたびに取り直していたため、計画作成を
# 十数回やり直して約1,000クレジットを無駄にした。同じ問い合わせは期限内なら
# 課金なしで返す。一括調査（search-volume）の登録・状況確認は毎回違うので残さない
CACHE_DIR = ROOT / "data" / "rakko_cache"
CACHE_DAYS = 30     # 週次補充は毎週同じ起点で聞くので、30日あれば月1回しか課金されない
NO_CACHE = ("/v1/search-volume", "/status", "/histories", "/metadata/")


def _cache_path(path, body, method):
    import hashlib
    key = json.dumps([method, path, body], ensure_ascii=False, sort_keys=True)
    return CACHE_DIR / (hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")


def _cache_get(path, body, method):
    if any(x in path for x in NO_CACHE):
        return None
    p = _cache_path(path, body, method)
    if not p.exists():
        return None
    import time as _t
    if _t.time() - p.stat().st_mtime > CACHE_DAYS * 86400:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _cache_put(path, body, method, res):
    if any(x in path for x in NO_CACHE) or not res or not res.get("result"):
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(path, body, method).write_text(
        json.dumps(res, ensure_ascii=False), encoding="utf-8")


def call(path, body=None, method="POST"):
    global _OUT_OF_CREDIT
    global CONSUMED
    key = api_key()
    if not key or _OUT_OF_CREDIT:
        return None
    hit = _cache_get(path, body, method)
    if hit is not None:
        return hit
    if over_budget():
        return None
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-API-Key": key, "Content-Type": "application/json"})
    for i in range(len(RETRY_WAIT) + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                res = json.load(r)
                _cache_put(path, body, method, res)
                credit = float(((res or {}).get("meta") or {}).get("consumedCredit") or 0)
                CONSUMED += credit
                _log_spend(path, credit)
                if over_budget():
                    print(f"  ラッコの消費が上限 {BUDGET} クレジットに達しました。以降の呼び出しは行いません")
                return res
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")
            # 5xx はHTMLのエラーページで返る。本文を出しても読めないので状態だけ出す
            short = detail[:200] if not detail.lstrip().startswith("<") else "（サーバー側のエラー）"
            if e.code == 402:
                print(f"  ラッコAPI 402: {short}")
                _OUT_OF_CREDIT = True
                print("  クレジットが尽きました。以降の呼び出しは行いません")
                print("  （無料のサジェストだけで発掘を続けます。記事作成は止まりません）")
                return None
            if 500 <= e.code < 600 and i < len(RETRY_WAIT):
                print(f"  ラッコAPI {e.code} {short}。{RETRY_WAIT[i]}秒待ってやり直します（{i + 2}/{len(RETRY_WAIT) + 1}）")
                time.sleep(RETRY_WAIT[i])
                continue
            print(f"  ラッコAPI {e.code}: {short}")
            return None
        except Exception as e:
            if i < len(RETRY_WAIT):
                print(f"  ラッコAPI 通信失敗（{type(e).__name__}）。{RETRY_WAIT[i]}秒待ってやり直します")
                time.sleep(RETRY_WAIT[i])
                continue
            print(f"  ラッコAPI 通信失敗: {str(e)[:100]}")
            return None
    return None


def _rows(res):
    """レスポンスからキーワード行を取り出す。data の形が版によって違うため吸収する"""
    if not res or not res.get("result"):
        return []
    d = res.get("data") or {}
    for k in ("keywords", "suggestKeywords", "relatedKeywords", "items", "list"):
        v = d.get(k)
        if isinstance(v, list):
            return v
    # data 直下がリストの場合
    return d if isinstance(d, list) else []


def suggest(keyword, modes=None, limit=100):
    """サジェスト。modes は google / bing / youtube などを複数指定できる"""
    res = call("/v1/suggest-keywords", {
        "keyword": keyword, "modes": modes or ["google", "youtube"],
        "increaseKeyword": True,          # 50音展開ぶんも含める
        "sortBy": "searchVolume", "orderBy": "desc", "limit": limit})
    return _rows(res)


def related(keyword, limit=100):
    """関連キーワード（部分一致）"""
    res = call("/v1/related-keywords", {
        "keyword": keyword, "matchType": "partialMatch",
        "sortBy": "searchVolume", "orderBy": "desc", "limit": limit})
    return _rows(res)


def questions(keyword):
    """よくある質問。FAQの見出しづくりに使える"""
    return _rows(call("/v1/question-search", {"keyword": keyword}))


def metrics(r):
    """1行から (月間ボリューム, SEO難易度) を取り出す。

    現行のAPIは metrics の下に入れて返す（searchVolume / seoDifficulty）。
    以前は1階層上だけを見ていたため、キーが通っていてもボリュームが
    すべて None になり、入れた意味が無くなっていた。両方の置き方を見る。
    """
    if isinstance(r, str):
        return None, None
    m = r.get("metrics") or {}
    vol = m.get("searchVolume", r.get("searchVolume", r.get("volume")))
    kd = m.get("seoDifficulty", r.get("seoDifficulty", r.get("difficulty")))
    return vol, kd


def as_pairs(rows):
    """(キーワード, 月間ボリューム) の形に揃える。キー名の違いを吸収する"""
    out = []
    for r in rows:
        if isinstance(r, str):
            out.append((r, None))
            continue
        kw = r.get("keyword") or r.get("word") or r.get("name")
        vol, _ = metrics(r)
        if kw:
            out.append((kw, vol))
    return out


def as_rows(rows):
    """(キーワード, 月間ボリューム, SEO難易度) の形。優先順位づけに使う"""
    out = []
    for r in rows:
        kw = r if isinstance(r, str) else (r.get("keyword") or r.get("word") or r.get("name"))
        if kw:
            vol, kd = metrics(r)
            out.append((kw, vol, kd))
    return out


def main():
    if "--check" in sys.argv:
        if not enabled():
            print("  RAKKO_API_KEY が未設定です（.env）")
            print("  取得: ラッコキーワード → マイページ → API → キー発行")
            print("        スタンダードプラン以上でのみ発行できます")
            return
        res = call("/v1/metadata/languages", method="GET")
        print("  キー設定あり /", "接続OK" if res else "接続できません")
        if exhausted():
            print("  クレジットが尽きています（契約管理ページで追加購入できます）")
        print(f"  今月の消費（手元の記録）: {month_spent():.0f} クレジット / 目安 {MONTHLY_BUDGET}")
        print("RAKKO_MONTH=%s" % ("over" if month_spent() > MONTHLY_BUDGET else "ok"))
        return

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit('使い方: python scripts/rakko.py "<キーワード>" [--related|--questions]')
    kw = args[0]
    if not enabled():
        print("  RAKKO_API_KEY が未設定のため、無料のサジェストだけで動いています")
        return
    if "--related" in sys.argv:
        rows, label = related(kw), "関連キーワード"
    elif "--questions" in sys.argv:
        rows, label = questions(kw), "よくある質問"
    else:
        rows, label = suggest(kw), "サジェスト"
    rs = as_rows(rows)
    print(f"■ {label}「{kw}」 {len(rs)}件（月間検索数 / SEO難易度）")
    for k, v, kd in rs[:40]:
        print(f"    {str(v) if v is not None else '—':>7} {('KD' + str(kd)) if kd is not None else '':>6}  {k}")


if __name__ == "__main__":
    main()
