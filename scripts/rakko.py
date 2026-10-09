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
    python scripts/rakko.py "経理代行" --site corporate            # サジェスト（社の上限で数える）
    python scripts/rakko.py "経理代行" --site corporate --related  # 関連キーワード
    python scripts/rakko.py --check               # 今月の消費（社ごと）・上限・止めた回数・残高

残高は GET /v1/account/info で読める（クレジットは消費しない）。使用量・利用履歴を返す口は無い
（2026-10-08 公式の資料 v1.21.0 で確認）。そのため使用量は、こちらが1回ごとに数えた記録で見る。

**上限（2026-10-08 運用者の決定。超えるなら呼ばない＝ハードストップ）**:
1サイト 月150（sites/<id>.json の rakko_monthly_cap で上書き）／全体 月600／1回 150。
1サイトの150は目的ごとの枠に分ける: 上位ページの見出し・共起語 70／実際の質問 30／候補の一括検索数 30／
季節の推移・予備 20（rakko_budget で上書き）。単価の資料が無い機能は使わない。
自動課金（オートチャージ）なので、尽きて止まることは無い。止めるのはここだけ。
課金の呼び出しは allow(社, 見積もり) を通った後だけ call() が行う。通っていなければ控え
（data/rakko_cache）にある応答だけを返し、ラッコには問い合わせない（週次の kw_discover はこの形）。

**数え方（手元とCIで同じ合計）**: 1回ごとに data/rakko_spend.jsonl（Git に置かない）へ社と環境つきで書き、
管制塔の「ラッコ利用」タブ（rakko_usage / rakko_log）へ差分を写す。判断は「この環境の記録」と
「管制塔の合計」の大きい方。CI は管制塔に届かないとき呼ばない（手元の消費が見えないため）。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://api.rakkokeyword.com"
JST = timezone(timedelta(hours=9))

SITE_CAP = 150     # 1サイト1か月。sites/<id>.json の rakko_monthly_cap で社ごとに変えられる
TOTAL_CAP = 600    # 全体1か月（4社分）
RUN_CAP = 150      # 1回。1サイトの月の上限より大きい1回は意味が無い

# 1サイト月150の内訳（目的ごとの枠。2026-10-08 運用者の決定）。sites/<id>.json の rakko_budget で上書きできる。
# rakko_monthly_cap だけを変えた社は、この比で伸び縮みする。この回の計画に無い目的では呼ばない
BUDGET_SPLIT = {"headline": 70, "qa": 30, "volume": 30, "reserve": 20}
PURPOSES = {"headline": "見出し・共起語", "qa": "実際の質問", "volume": "一括検索数", "reserve": "季節の推移・予備"}
# 経路の既定の目的。同じ経路を別の目的で使うとき（季節の推移を一括調査で取る等）は call(..., purpose=) で渡す
PURPOSE_OF = {"/v1/headline": "headline", "/v1/co-occurrence": "headline",
              "/v1/question-search": "qa", "/v1/other-keywords": "qa",
              "/v1/search-volume": "volume",
              "/v1/suggest-keywords": "reserve", "/v1/related-keywords": "reserve"}

# 1回の呼び出しのクレジット（公式の資料 https://api.rakkokeyword.com/docs v1.21.0。API経由の倍率込み）。
# 値段の資料が無い経路は呼ばない（見積もりも上限も効かなくなる）。使う経路を増やすときはここに足す
PRICE = {"/v1/suggest-keywords": 1.5, "/v1/related-keywords": 1.5, "/v1/question-search": 1.5,
         "/v1/other-keywords": 22.5, "/v1/headline": 3.0, "/v1/co-occurrence": 3.0}
FREE = ("/status", "/results", "/histories", "/v1/metadata/", "/v1/account/")
BULK_MIN = 15.0      # 一括調査（search-volume）1回の最低料金
BULK_PER_KW = 0.03   # 一括調査の1語。SEO難易度を付けると 1語 +0.75


def price(path, body=None, method="POST"):
    """1回の呼び出しの値段の上限。None は値段が分からない（呼ばない）"""
    if any(x in path for x in FREE):
        return 0.0
    if path == "/v1/search-volume":
        b = body or {}
        per = BULK_PER_KW + (0.75 if b.get("seoDifficulty") else 0.0)
        return max(BULK_MIN, round(per * len(b.get("keywords") or []), 2))
    return PRICE.get(path)


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


SPEND_LOG = ROOT / "data" / "rakko_spend.jsonl"   # 1行1回（社・環境つき）。月の合計を出すため


def this_month():
    return datetime.now(JST).strftime("%Y-%m")


def env_name():
    return "ci" if os.environ.get("GITHUB_ACTIONS") else "local"


def _log_spend(path, credit, site=None, **extra):
    if not credit and not extra.get("blocked"):
        return
    try:
        SPEND_LOG.parent.mkdir(parents=True, exist_ok=True)
        row = {"at": datetime.now(JST).isoformat(timespec="seconds"), "path": path, "credit": credit,
               "site": site or "", "env": env_name(), **extra}
        with SPEND_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def ledger(month=None):
    """その月の記録（この環境）。month は 'YYYY-MM'（省略時は今月）"""
    month = month or this_month()
    if not SPEND_LOG.exists():
        return []
    rows = []
    for ln in SPEND_LOG.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(ln))
        except Exception:
            continue
    # 門の検査が偽の通信で書いた記録（/v1/x と同じ秒の記録）は数えない。
    # 2026-10-03 まで検査が本物の台帳に書いており、手元で600行以上積まれていた
    # （10月の生の合計 847.5 のうち 652.5 がこれ。実際の消費は 195）
    fake = {r.get("at") for r in rows if r.get("path") == "/v1/x"}
    return [r for r in rows if str(r.get("at", "")).startswith(month) and r.get("at") not in fake]


def purpose_of(r):
    return r.get("purpose") or PURPOSE_OF.get(r.get("path") or "", "reserve")


def month_spent(month=None, site=None, purpose=None):
    """その月に使ったクレジット（この環境の記録）。site を渡すとその社の分だけ、purpose でその目的の分だけ。
    社の無い行（2026-10-08 より前の記録）は全体の合計にだけ数え、推定で社に割り振らない"""
    return round(sum(float(r.get("credit") or 0) for r in ledger(month)
                     if (site is None or (r.get("site") or "") == site)
                     and (purpose is None or purpose_of(r) == purpose)), 2)


def by_key(month=None):
    """{(社, 目的): クレジット}（この環境の記録）"""
    out = Counter()
    for r in ledger(month):
        out[(r.get("site") or "", purpose_of(r))] += float(r.get("credit") or 0)
    return {k: round(v, 2) for k, v in out.items() if v}


def spent():
    return CONSUMED


def over_budget():
    return BUDGET is not None and CONSUMED >= BUDGET


# ── 上限（ハードストップ） ───────────────────────────────
# allow() が通したときだけ立つ {site, limit, used, plimit: {目的: 残り}, pused}。立っていなければ課金の呼び出しはしない
_GRANT = None
_SAID = set()
REASONS = {
    "no_site": "社を指定していない課金の呼び出しは行いません",
    "run_cap": f"見積もりが1回の上限 {RUN_CAP} を超えます",
    "site_cap": "この社の今月の上限を超えます",
    "total_cap": f"全体の今月の上限 {TOTAL_CAP} を超えます",
    "shared": "CI では管制塔の台帳が読めないと手元の消費が見えないため、呼びません",
    "bucket": "どの目的も今月の枠を超えます",
}


def _hub(body):
    """管制塔（手元とCIで共通の台帳）。届かない・まだ配っていない（action を知らない）ときは None"""
    try:
        import hub_client
        if not hub_client.enabled():
            return None
        d = hub_client._post(body)
    except Exception:
        return None
    return d if isinstance(d, dict) and d.get("ok") is True and d.get("rakko") is True else None


def shared_usage(month=None):
    """管制塔の台帳のその月（{total, sites, purposes, envs, blocked}）。読めなければ None"""
    return _hub({"action": "rakko_usage", "month": month or this_month()})


def sync_shared(month=None):
    """この環境の記録のうち、管制塔に写っていない分（差分）を写し、写した後の台帳を返す。
    1回ごとに写すと遅く、途中で落ちると写し漏れる。差分で写せば、いつ・どこで写しても合計が揃う"""
    month = month or this_month()
    u = shared_usage(month)
    if u is None:
        return None
    mine = (u.get("envs") or {}).get(env_name()) or {}
    sent = False
    for (site, purpose), credit in by_key(month).items():
        gap = round(credit - float(mine.get(f"{site}|{purpose}") or 0), 2)
        if gap > 0:
            sent = _hub({"action": "rakko_log", "site": site, "env": env_name(), "credit": gap,
                         "purpose": purpose, "note": "記録の写し"}) is not None or sent
    return shared_usage(month) if sent else u


def usage(site, month=None, shared=None):
    """判断に使うその月の消費。この環境の記録と管制塔の合計の、大きい方（社・全体・目的ごと）"""
    sh = shared or {}
    hp = (sh.get("purposes") or {}).get(site) or {}
    return {"site": max(month_spent(month, site), float((sh.get("sites") or {}).get(site) or 0)),
            "total": max(month_spent(month), float(sh.get("total") or 0)),
            "purposes": {p: max(month_spent(month, site, p), float(hp.get(p) or 0)) for p in BUDGET_SPLIT},
            "shared": shared is not None}


def _site_cfg(site):
    try:
        import sites
        return sites.load_all().get(site) or {}
    except Exception:
        return {}


def _num(v, default):
    try:
        return float(v) if v is not None and float(v) >= 0 else float(default)
    except (TypeError, ValueError):
        return float(default)


def site_cap(site):
    return _num(_site_cfg(site).get("rakko_monthly_cap"), SITE_CAP)


def budget_split(site):
    """目的ごとの月の枠。rakko_budget があればそれ、無ければ既定の比（社の上限に合わせて伸び縮み）"""
    cap = site_cap(site)
    out = {p: round(v * cap / SITE_CAP, 2) for p, v in BUDGET_SPLIT.items()}
    for p, v in (_site_cfg(site).get("rakko_budget") or {}).items():
        if p in out:
            out[p] = _num(v, out[p])
    return out


def note_block(site, why, est):
    """止めた記録。週次の findings と月次のまとめが回数を数える"""
    _log_spend("", 0, site, blocked=why, est=round(est, 2))
    _hub({"action": "rakko_log", "site": site, "env": env_name(), "credit": 0,
          "note": f"止めた:{why} 見積もり{est:.0f}"})


def allow(site, est, dry=False, purpose="reserve"):
    """課金の前に必ず通す（ハードストップ）。est は見積もり（数なら purpose の目的、{目的: クレジット} も可）。

    1. 目的ごとの枠: その社の今月の目的の消費＋見積もりが枠を超える目的では呼ばない（他の目的は続ける）
    2. 残った見積もりで、社の今月＋見積もりが社の上限を、全体の今月＋見積もりが全体の上限を、
       見積もりが1回の上限を超えるなら何も呼ばない
    通ったときだけ call() が、残りの枠（社・全体・1回・目的の小さい方）まで課金の呼び出しを行う。
    見積もりが外れても枠を超える呼び出しはしない。計画に無い目的でも呼ばない。
    戻り値は、見積もったすべての目的が通ったか。dry は判定を見せるだけ（許可も止めた記録も残さない）"""
    global _GRANT
    _GRANT = None
    _SAID.clear()
    parts = {p: round(float(v), 2) for p, v in (est.items() if isinstance(est, dict) else [(purpose, est)]) if v}
    month = this_month()
    u = usage(site, month, shared_usage(month) if dry else sync_shared(month))
    cap = site_cap(site) if site else 0.0
    split = budget_split(site) if site else {}
    skip = [p for p, v in parts.items() if p not in split or u["purposes"].get(p, 0) + v > split[p] + 1e-9]
    go = round(sum(v for p, v in parts.items() if p not in skip), 2)
    print(f"   ラッコの見積もり: 約{sum(parts.values()):.0f}クレジット ／ {site or '（社の指定なし）'} の今月 {u['site']:.0f}"
          f" / 上限 {cap:.0f} ／ 全体の今月 {u['total']:.0f} / 上限 {TOTAL_CAP}"
          f"（{'管制塔の台帳と照合' if u['shared'] else 'この環境の記録だけ。管制塔の台帳に届きません'}）")
    if split:
        print("   目的ごとの枠（今月＋見積もり / 枠）: " + " ／ ".join(
            f"{PURPOSES[p]} {u['purposes'].get(p, 0):.0f}＋{parts.get(p, 0):.0f} / {split[p]:.0f}" for p in split))
    why = ("no_site" if not site else "bucket" if parts and not go else "run_cap" if go > RUN_CAP
           else "site_cap" if u["site"] + go > cap else "total_cap" if u["total"] + go > TOTAL_CAP
           else "shared" if not u["shared"] and env_name() == "ci" else "")
    for p in skip if site else ():
        print(f"   {PURPOSES.get(p, p)}: 今月の枠を超えるため、この目的では呼びません")
        print(f"RAKKO_BUCKET=skip:{p}")
        if not dry:
            note_block(site, "bucket:" + p, parts[p])
    print(f"RAKKO_GUARD={why or ('bucket' if skip else 'ok')}")
    if why:
        print(f"   {REASONS[why]}。ラッコは呼ばず、無料の材料（サジェスト・Search Console・控え）だけで続けます")
        if not dry and why != "bucket":
            note_block(site, why, go)
        return False
    if not dry:
        _GRANT = {"site": site, "limit": round(min(RUN_CAP, cap - u["site"], TOTAL_CAP - u["total"]), 2), "used": 0.0,
                  "plimit": {p: round(split[p] - u["purposes"].get(p, 0), 2) for p in parts if p not in skip},
                  "pused": Counter()}
    return not skip


def granted(purpose=None):
    """この回は課金の呼び出しを許されているか（allow を通ったか。purpose を渡すとその目的で）"""
    return _GRANT is not None and (purpose is None or purpose in _GRANT["plimit"])


def _say(key, msg):
    if key not in _SAID:
        _SAID.add(key)
        print(msg)


def _room(cost, purpose):
    """この呼び出しをしてよいか（allow が出した枠の残り）"""
    g = _GRANT
    if g is None:
        _say("no_grant", "  ラッコ: 上限の確認（rakko.allow）を通っていないため呼びません。控えにある応答だけを使います")
        return False
    lim = g["plimit"].get(purpose)
    if lim is None:
        _say("plan:" + purpose, f"  ラッコ: この回の計画に無い目的（{PURPOSES.get(purpose, purpose)}）では呼びません")
        return False
    if g["used"] + cost > g["limit"] + 1e-9 or g["pused"][purpose] + cost > lim + 1e-9:
        if "limit" not in _SAID:
            note_block(g["site"], "run_limit", g["used"] + cost)
            print("RAKKO_GUARD=run_limit")
        _say("limit", f"  ラッコ: この回の枠に達したため、以降は呼びません（{PURPOSES.get(purpose, purpose)}）")
        return False
    return True


def _spend(purpose, credit):
    if _GRANT is not None:
        _GRANT["used"] += credit
        _GRANT["pused"][purpose] += credit


def month_report(month=None):
    """社ごとのその月の消費・上限・目的ごとの枠・止めた回数（週次の findings と月次のまとめが読む）。(行, 要対応か)"""
    month = month or this_month()
    shared = shared_usage(month)
    try:
        import sites
        ids = set(sites.load_all())
    except Exception:
        ids = set()
    ids |= {s for s, _ in by_key(month) if s} | set((shared or {}).get("sites") or {})
    blocked = Counter(r.get("site") or "" for r in ledger(month) if r.get("blocked"))
    for s, n in ((shared or {}).get("blocked") or {}).items():
        blocked[s] = max(blocked[s], int(n or 0))
    total = usage("", month, shared)["total"]
    head = "今月の消費" if month == this_month() else "消費"
    lines = [f"{head}（{month}）合計: {total:.1f} / 上限 {TOTAL_CAP}"
             f"（{'管制塔の台帳と照合' if shared else 'この環境の記録だけ。管制塔の台帳に届きません'}）"]
    over = total >= TOTAL_CAP or blocked[""] > 0
    if month_spent(month, ""):
        lines.append(f"{head} 社の記録なし: {month_spent(month, ''):.1f}（社を書く前の記録。全体の合計にだけ数える）")
    for s in sorted(ids):
        u, cap, b, split = usage(s, month, shared), site_cap(s), blocked.get(s, 0), budget_split(s)
        lines.append(f"{head} {s}: {u['site']:.1f} / 上限 {cap:.0f}（"
                     + "・".join(f"{PURPOSES[p]} {u['purposes'][p]:.0f}/{split[p]:.0f}" for p in split) + "）"
                     + (f" 止めた {b}回" if b else ""))
        over = over or u["site"] >= cap or b > 0
    return lines, over


def account():
    """残高とオートチャージの設定（GET /v1/account/info。クレジットは消費しない）。読めなければ None"""
    res = call("/v1/account/info", method="GET")
    return (((res or {}).get("data") or {}).get("credit")) or None


# 応答をディスクに残す。条件の調整のたびに取り直していたため、計画作成を
# 十数回やり直して約1,000クレジットを無駄にした。同じ問い合わせは期限内なら
# 課金なしで返す。一括調査（search-volume）の登録・状況確認は毎回違うので残さない
CACHE_DIR = ROOT / "data" / "rakko_cache"
CACHE_DAYS = 30     # 週次補充は毎週同じ起点で聞くので、30日あれば月1回しか課金されない
NO_CACHE = ("/v1/search-volume", "/status", "/histories", "/metadata/", "/account/")


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


def call(path, body=None, method="POST", purpose=None):
    """ラッコへの問い合わせはすべてここを通る（ここ以外に通信の口を作らない）。
    控えにあれば課金なしで返す。課金の呼び出しは allow() の枠の中でだけ行う。
    purpose は目的の枠（省略時は経路の既定。PURPOSE_OF）"""
    global _OUT_OF_CREDIT
    global CONSUMED
    key = api_key()
    if not key or _OUT_OF_CREDIT:
        return None
    hit = _cache_get(path, body, method)
    if hit is not None:
        return hit
    cost = price(path, body, method)
    if cost is None:
        _say("unpriced:" + path, f"  ラッコ: 単価の資料が無い経路（{path}）は呼びません。rakko.PRICE に公式の単価を足してください")
        return None
    purpose = purpose or PURPOSE_OF.get(path, "reserve")
    if cost and not _room(cost, purpose):
        return None
    if over_budget():
        return None
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-API-Key": key, "Content-Type": "application/json"})
    for i in range(len(RETRY_WAIT) + 1):
        if i and cost and not _room(cost, purpose):
            return None
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                res = json.load(r)
                _cache_put(path, body, method, res)
                meta = (res or {}).get("meta") or {}
                # 消費の記載が無い応答は、値段の上限を使ったものとして数える（安全側）
                credit = float(meta["consumedCredit"]) if meta.get("consumedCredit") is not None else cost
                CONSUMED += credit
                _spend(purpose, credit)
                _log_spend(path, credit, (_GRANT or {}).get("site"), purpose=purpose)
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
            # 時間切れは、向こうで処理されて課金だけ済んでいることがある。この回の枠では使ったものとして数える
            if cost:
                _spend(purpose, cost)
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


SUGGEST = "/v1/suggest-keywords"
RELATED = "/v1/related-keywords"


def suggest_body(keyword, modes=None, limit=100):
    """サジェストの問い合わせの中身。控え（キャッシュ）の鍵になるので、見積もり・dry-run も必ずこれで作る。
    kw_plan は別の中身で控えを引いていたため、取得済みの語も「未取得」と数え、dry-run で控えを使えなかった（2026-10-08）"""
    return {"keyword": keyword, "modes": modes or ["google", "youtube"],
            "increaseKeyword": True,          # 50音展開ぶんも含める
            "sortBy": "searchVolume", "orderBy": "desc", "limit": limit}


def related_body(keyword, limit=100):
    return {"keyword": keyword, "matchType": "partialMatch",
            "sortBy": "searchVolume", "orderBy": "desc", "limit": limit}


def suggest(keyword, modes=None, limit=100):
    """サジェスト。modes は google / bing / youtube などを複数指定できる"""
    return _rows(call(SUGGEST, suggest_body(keyword, modes, limit)))


def related(keyword, limit=100):
    """関連キーワード（部分一致）"""
    return _rows(call(RELATED, related_body(keyword, limit)))


HEADLINE = "/v1/headline"
COOCCUR = "/v1/co-occurrence"
QUESTION = "/v1/question-search"


def headline_body(keyword):
    """検索上位ページの見出し（h1〜h4・上位20ページ）。1回3クレジット（公式の資料 v1.21.0）"""
    return {"keyword": keyword, "h1": True, "h2": True, "h3": True, "h4": False, "limit": 20}


def cooccur_body(keyword):
    """検索上位ページの共起語。ページごとの詳細（URL・題）は要らないので取らない。1回3クレジット"""
    return {"keyword": keyword, "getDetails": False, "sortBy": "siteCountTotal", "orderBy": "desc", "limit": 60}


def question_body(keyword):
    """その語を含む実際の質問（相対需要の高い順）。1回1.5クレジット"""
    return {"keyword": keyword, "sortBy": "relativeDemand", "orderBy": "desc", "limit": 50}


def headline(keyword):
    """上位ページの見出しの応答（data: summary・items[].page・metrics・headlines）。呼べなければ None"""
    return call(HEADLINE, headline_body(keyword))


def cooccur(keyword):
    """共起語の応答（data: items[].word・metrics）。呼べなければ None"""
    return call(COOCCUR, cooccur_body(keyword))


def questions(keyword):
    """よくある質問（data: items[].question・metrics.relativeDemand）。FAQの候補に使う"""
    return _rows(call(QUESTION, question_body(keyword)))


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
        # 消費はキーが無くても数える（CI にはキーが無いが、管制塔の台帳から手元の消費が見える）
        print(f"  ラッコの上限: 1サイト月{SITE_CAP}・全体月{TOTAL_CAP}・1回{RUN_CAP}（超えるなら呼ばない）")
        lines, over = month_report()
        for ln in lines:
            print("  " + ln)
        if not enabled():
            print("  RAKKO_API_KEY が未設定です（.env）")
            print("  取得: ラッコキーワード → マイページ → API → キー発行")
            print("        スタンダードプラン以上でのみ発行できます")
        else:
            c = account()
            if c:
                ac = c.get("autoCharge") or {}
                print(f"  残高 {c.get('balance')} クレジット（オートチャージ: "
                      + (f"有効・残り{ac.get('thresholdAmount')}で{ac.get('purchaseAmount')}を購入" if ac.get("enabled") else "無効")
                      + "）")
            else:
                print("  残高を読めません（キーか接続を確かめてください）")
            if exhausted():
                print("  クレジットが尽きています（契約管理ページで追加購入できます）")
        print("RAKKO_MONTH=%s" % ("over" if over else "ok"))
        return

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    site = sys.argv[sys.argv.index("--site") + 1] if "--site" in sys.argv[:-1] else ""
    args = [a for a in args if a != site]
    if not args:
        raise SystemExit('使い方: python scripts/rakko.py "<キーワード>" --site <id> [--related|--questions]')
    kw = args[0]
    if not enabled():
        print("  RAKKO_API_KEY が未設定のため、無料のサジェストだけで動いています")
        return
    allow(site, 1.5, purpose="qa" if "--questions" in sys.argv else "reserve")   # 通らなければ控えだけを見せる
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
    sync_shared()


if __name__ == "__main__":
    main()
