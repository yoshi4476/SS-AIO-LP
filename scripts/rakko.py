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
    python scripts/rakko.py --check               # キーの有無と残クレジット
"""
import json
import sys
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


def call(path, body=None, method="POST"):
    key = api_key()
    if not key:
        return None
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-API-Key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:200]
        print(f"  ラッコAPI {e.code}: {detail}")
        return None
    except Exception as e:
        print(f"  ラッコAPI 通信失敗: {str(e)[:100]}")
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


def as_pairs(rows):
    """(キーワード, 月間ボリューム) の形に揃える。キー名の違いを吸収する"""
    out = []
    for r in rows:
        if isinstance(r, str):
            out.append((r, None))
            continue
        kw = r.get("keyword") or r.get("word") or r.get("name")
        vol = r.get("searchVolume", r.get("volume"))
        if kw:
            out.append((kw, vol))
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
    pairs = as_pairs(rows)
    print(f"■ {label}「{kw}」 {len(pairs)}件")
    for k, v in pairs[:40]:
        print(f"    {str(v) if v is not None else '—':>7}  {k}")


if __name__ == "__main__":
    main()
