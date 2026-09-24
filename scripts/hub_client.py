# -*- coding: utf-8 -*-
"""管制塔（GASスプレッドシート）との通信

記事工場（GitHub Actions）から、キーワードの取得・着手記録・公開記録を行う。
HUB_URL が未設定の場合はローカルのKWリスト（docs/*.md）にフォールバックするため、
管制塔が未設置でもパイプラインは止まらない。

使い方（単体確認）:
    python scripts/hub_client.py status
    python scripts/hub_client.py next corporate
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"}
TIMEOUT = 30


def _env():
    env = dict(os.environ)
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                env.setdefault(k.strip(), v.strip())
    return env


def _clean(v):
    """環境変数にBOM（﻿）が混入していても安全に読めるようにする"""
    return (v or "").replace("﻿", "").strip()


ENV = _env()
HUB_URL = _clean(ENV.get("HUB_URL", ""))
HUB_SECRET = _clean(ENV.get("HUB_SECRET", ""))


def enabled():
    return bool(HUB_URL)


RETRY_WAIT = (3, 8, 15)   # Apps Script は302の先で一時的に404/5xxを返すことがある。今日2回起きた


def _open(req):
    """管制塔へつなぐ。一時的な 404/5xx・通信断は待ってやり直す。
    取り下げの直後の追加でこれに当たり、未着手が0件のまま残るところだった"""
    import time
    for i in range(len(RETRY_WAIT) + 1):
        try:
            return urllib.request.urlopen(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as e:
            if e.code not in (404, 429, 500, 502, 503, 504) or i >= len(RETRY_WAIT):
                raise
            print(f"  管制塔 {e.code}。{RETRY_WAIT[i]}秒待ってやり直します（{i + 2}/{len(RETRY_WAIT) + 1}）")
        except (urllib.error.URLError, TimeoutError) as e:
            if i >= len(RETRY_WAIT):
                raise
            print(f"  管制塔に接続できません（{type(e).__name__}）。{RETRY_WAIT[i]}秒待ってやり直します")
        time.sleep(RETRY_WAIT[i])


def _direct(action, p):
    """Sheets API で直接（hub_sheets）。使えない・失敗したら None を返して GAS に落とす"""
    try:
        import hub_sheets as HS
        if not HS.available():
            return None
        if action == "next_kw":
            return HS.next_kw(p.get("site", ""))
        if action == "all_kw":
            return {"ok": True, "keywords": HS.all_kw()}
        if action == "kw_status":
            return HS.kw_status(p.get("site", ""))
        if action == "claim_kw":
            return HS.claim_kw(p.get("site", ""), p.get("keyword", ""))
        if action == "unclaim_kw":
            return HS.unclaim_kw(p.get("site", ""), p.get("keywords") or [])
        if action == "retire_kw":
            return HS.retire_kw(p.get("site", ""), p.get("keywords") or [], p.get("reason", ""), bool(p.get("force")))
        if action == "add_kw":
            return HS.add_kw(p.get("site", ""), p.get("keywords") or [])
        if action == "publish_log":
            return HS.publish_log(**{k: v for k, v in p.items() if k not in ("action", "secret")})
        if action == "error_log":
            return HS.error_log(p.get("site", ""), p.get("phase", ""), p.get("message", ""), p.get("fix", ""),
                                p.get("status", "未対応"))
        if action == "rewrite_log":
            return HS.rewrite_log(p.get("site", ""), p.get("article", ""), p.get("reason", ""), p.get("summary", ""),
                                  p.get("posBefore", ""), p.get("posAfter", ""), p.get("effect", ""))
        return None                                   # それ以外は GAS へ
    except Exception as e:
        print(f"  管制塔へ直接つなげません（{type(e).__name__}）。GAS 経由に切り替えます")
        return None


def _get(params):
    d = _direct(params.get("action", ""), params)
    if d is not None:
        return d
    url = HUB_URL + ("&" if "?" in HUB_URL else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with _open(req) as r:
        return json.load(r)


def _post(body):
    d = _direct(body.get("action", ""), body)
    if d is not None:
        return d
    body = dict(body)
    body["secret"] = HUB_SECRET
    req = urllib.request.Request(
        HUB_URL, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={**UA, "Content-Type": "application/json"})
    with _open(req) as r:
        return json.load(r)


def _main_offer_pattern(site):
    """そのサイトの主力に当たる語の目印。sites/<site>.json の main_offer と対にする"""
    return {
        # 主力は AIO。chatgpt・生成ai を入れると ai-marketing の語まで拾い、
        # 主力カテゴリが増えない（実測で aio が21%まで落ちた）
        "ai-lab": r"aio|llmo|ai検索|ai overview|生成エンジン|ai引用",
        "subsidy": r"ai導入補助金|ai補助金",
        "corporate": r"bpo|経理代行|記帳代行",
    }.get(site, "")


def next_kw(site):
    """次に書くKWを取得。管制塔が使えなければ None を返す（呼び出し側でローカルにフォールバック）

    台帳は優先度の順に返すが、いま台帳にある語はすべて優先度Bで、
    実質は行の並び順になっている。主力から離れた古い語が先に出てしまうため、
    ここで主力の語を先に拾う。配信済みの管制塔コードは優先度付きの追加に
    対応しておらず、台帳側では順序を変えられない。
    """
    if not enabled():
        return None
    try:
        got = _get({"action": "next_kw", "site": site})
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        print(f"管制塔に接続できません（ローカルのKWリストを使います）: {e}")
        return None
    pat = _main_offer_pattern(site)
    if not isinstance(got, dict) or not got.get("keyword"):
        return got
    import re
    # AIが答えを出していて自社が出典に無い語（ai_kw_research が週次で記録）を
    # 最優先で書く。AI Overview は質問形のクエリで64.7%出る。取りに行く価値が
    # いちばん高い語を、台帳の並び順に埋もれさせない
    aiq = _ai_targets(site)
    kw0 = str(got["keyword"])
    if _norm(kw0) in aiq and (not pat or re.search(pat, kw0.lower())):
        return got
    try:
        rows = all_kw()
    except Exception:
        return got
    todo = [r for r in rows or []
            if r.get("site") == site and str(r.get("status", "")).strip() == "未着手"
            and str(r.get("keyword", ""))]

    def pick(rule, why):
        for r in todo:
            kw = str(r["keyword"])
            if rule(kw):
                out = dict(got)
                out.update({"keyword": kw, "aim": r.get("aim", ""),
                            "category": r.get("category", ""), "picked_by": why})
                return out
        return None

    if aiq:
        hit = (pick(lambda k: _norm(k) in aiq and (not pat or re.search(pat, k.lower())), "AI回答×主力")
               or pick(lambda k: _norm(k) in aiq, "AI回答あり"))
        if hit:
            return hit
    # 「開かないと済まない語」（kw_intent で強）を、弱い語より先に書く。
    # 同じ順位でもクリック率が5倍違う。台帳の並び（登録順）に任せない
    try:
        import kw_intent
        strong = lambda k: kw_intent.verdict(k)[0] == "強"
        if not strong(kw0):
            hit = (pick(lambda k: strong(k) and (not pat or re.search(pat, k.lower())), "強い語×主力")
                   or pick(strong, "強い語"))
            if hit:
                return hit
    except Exception:
        pass
    if pat:
        if re.search(pat, kw0.lower()):
            return got                   # すでに主力の語ならそのまま
        hit = pick(lambda k: bool(re.search(pat, k.lower())), "主力優先")
        if hit:
            return hit
    return got                           # 主力の語が尽きていれば、あるものを書く


def _norm(s):
    import re
    return re.sub(r"[\s　・･／/（）()｜|【】\[\]「」、。,.\-‐－—_]", "", str(s).lower())


def _ai_targets(site):
    """data/ai_kw/<site>.json のうち「AIが答えを出し、自社が出典に無い」語"""
    p = ROOT / "data" / "ai_kw" / f"{site}.json"
    if not p.is_file():
        return set()
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return set()
    return {_norm(r["kw"]) for r in d.get("items", [])
            if (r.get("ai") or {}).get("answered") and not (r.get("ai") or {}).get("ours")}


def all_kw(strict=False):
    """台帳の全KWを返す。

    既定では失敗を空リストで返す（表示系がこれで落ちないように）。
    ただし「空」と「読めなかった」を区別できないため、重複判定など
    誤ると実害が出る用途では strict=True で例外を投げさせること。
    実際に、読めなかったのを「台帳は空」と解釈して重複を積み続けていた。
    """
    if not enabled():
        if strict:
            raise RuntimeError("HUB_URL が未設定です")
        return []
    try:
        d = _get({"action": "all_kw"})
        # GAS は失敗しても {ok:false} で返す。keywords が無いのを「台帳が空」と読まない
        if strict and (d.get("ok") is False or "keywords" not in d):
            raise RuntimeError(d.get("error") or "台帳を読めませんでした")
        return d.get("keywords", [])
    except Exception:
        if strict:
            raise
        return []


def status(site=""):
    if not enabled():
        return {"ok": False, "error": "HUB_URL 未設定"}
    return _get({"action": "kw_status", "site": site})


def claim_kw(site, keyword):
    return _post({"action": "claim_kw", "site": site, "keyword": keyword}) if enabled() else None


def retire_kw(site, keywords, reason, force=False):
    """食い合い等で書けないKWを台帳から退避する（状態を「対象外」にする）"""
    if not enabled():
        return None
    return _post({"action": "retire_kw", "site": site, "keywords": keywords,
                  "reason": reason, "force": force})


def add_kw(site, keywords):
    return _post({"action": "add_kw", "site": site, "keywords": keywords}) if enabled() else None


def publish_log(**kw):
    """公開結果を記録。失敗してもパイプラインは止めない"""
    if not enabled():
        return None
    try:
        return _post({"action": "publish_log", **kw})
    except Exception as e:
        print(f"管制塔への公開記録に失敗（記事の公開は完了しています）: {e}")
        return None


def error_log(site, phase, message, fix="", status="未対応"):
    """詰まりを台帳に残す。fix に「次に何をすればいいか」を書く。
    原因だけ残しても、時間が経つと本人にも次の一手が分からなくなる"""
    if not enabled():
        return None
    try:
        return _post({"action": "error_log", "site": site, "phase": phase,
                      "message": message, "fix": fix, "status": status})
    except Exception:
        return None


def rewrite_effect(rows):
    """リライトログの後順位・効果を埋める。rows: [{site, article, posAfter, effect}]"""
    return _post({"action": "rewrite_effect", "rows": rows}) if enabled() else None


def error_sync(phase, messages):
    """今回出なかった同じ工程の「未対応」を「解消」にする（増えるだけの表を止める）"""
    return _post({"action": "error_sync", "phase": phase, "messages": list(messages)}) if enabled() else None


def rewrite_log(site, article, reason, summary, pos_before="", pos_after="", effect=""):
    """リライトの記録。前後の順位を残さないと効いたか判定できない。
    受け取り側のキーは posBefore / posAfter。名前が違うと黙って空欄になる"""
    if not enabled():
        return None
    try:
        return _post({"action": "rewrite_log", "site": site, "article": article,
                      "reason": reason, "summary": summary,
                      "posBefore": pos_before, "posAfter": pos_after, "effect": effect})
    except Exception:
        return None


def main():
    if not enabled():
        raise SystemExit("HUB_URL が未設定です（.env または環境変数に設定してください）")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    site = sys.argv[2] if len(sys.argv) > 2 else ""
    if cmd == "status":
        import sites as sites_mod
        for s in ([site] if site else list(sites_mod.load_all())):
            r = status(s)
            print(f"{s:10s} 全{r.get('total', 0):3d}件  未着手{r.get('todo', 0):3d}  "
                  f"執筆中{r.get('doing', 0):2d}  公開済み{r.get('done', 0):3d}")
    elif cmd in ("next", "next_kw"):         # 手順書は next_kw の名で案内している
        print(json.dumps(next_kw(site), ensure_ascii=False, indent=2))
    elif cmd == "all":
        for k in all_kw():
            print(f"{k['site']:10s} {k['status']:6s} {k['keyword']}")
    elif cmd == "error_sync":
        # 使い方: hub_client.py error_sync <phase> <TODOを1行ずつ書いたファイル>
        from pathlib import Path as _P
        f = _P(sys.argv[3]) if len(sys.argv) > 3 else None
        msgs = [x.strip() for x in f.read_text(encoding="utf-8").splitlines() if x.strip()] if f and f.exists() else []
        print(error_sync(site, msgs))
    elif cmd == "error_log":
        # 使い方: hub_client.py error_log <phase> <message...>
        error_log("", site, " ".join(sys.argv[3:]))
        print("エラーログへ記録しました")
    else:
        raise SystemExit(
            "使い方: python scripts/hub_client.py [status|next|all] [site]\n"
            "        python scripts/hub_client.py error_log <phase> <message>")


if __name__ == "__main__":
    main()
