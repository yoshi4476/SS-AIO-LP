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
    HS = None
    try:
        import hub_sheets as HS
        # 実際に1行でも書けたかは hub_sheets が持つ。ここで立てると、書く前の失敗
        # （認証・403・404）まで「途中まで書けた」と扱い、記録が GAS に落ちずに消えていた
        HS.WROTE = False
        if not HS.available():
            return None
        if action == "next_kw":
            return HS.next_kw(p.get("site", ""))
        if action == "all_kw":
            return {"ok": True, "keywords": HS.all_kw()}
        if action == "kw_status":
            return HS.kw_status(p.get("site", ""))
        if action == "claim_kw":
            return HS.claim_kw(p.get("site", ""), p.get("keyword", ""), p.get("ctx"))
        if action == "unclaim_kw":
            return HS.unclaim_kw(p.get("site", ""), p.get("keywords") or [])
        if action == "retire_kw":
            return HS.retire_kw(p.get("site", ""), p.get("keywords") or [], p.get("reason", ""), bool(p.get("force")))
        if action == "add_kw":
            return HS.add_kw(p.get("site", ""), p.get("keywords") or [], p.get("ctx"))
        if action == "kw_overlaps":
            return HS.kw_overlaps()
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
        # 行を足すだけの記録は、途中まで書けているかもしれない。GAS でやり直すと
        # 同じ公開・同じリライトが2行になり、本数を二重に数える。落とし直さず失敗で返す
        if HS is not None and getattr(HS, "WROTE", False) and action in ("publish_log", "rewrite_log"):
            print(f"  管制塔への直接記録が途中で失敗しました（{type(e).__name__}）。二重計上を避けるため GAS では記録し直しません")
            return {"ok": False, "error": f"direct: {type(e).__name__}: {str(e)[:120]}"}
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
    # 打ち出しから外したテーマ（sites/<id>.json の drop_kw）の語は書かない。
    # 2026-10-02 に AI集客ラボは MEO を打ち出さず SEO・AIO・LLMO に絞ると決めた
    drop = _drop_pattern(site)
    # 担当領域の外（kw_fit の判定2）の語も書かない。台帳に残った「記帳 やり方 ゆうちょ」
    # 「保険代理店 選び方」を、台帳を書き換えずに選ばないようにする（2026-10-08）
    unfit = _unfit(site)
    dropped = lambda k: bool(drop and re.search(drop, k.lower()))
    bad = lambda k: dropped(k) or unfit(k)
    if _norm(kw0) in aiq and (not pat or re.search(pat, kw0.lower())) and not bad(kw0):
        return got
    try:
        rows = all_kw()
    except Exception:
        return None if bad(kw0) else got
    todo = [r for r in rows or []
            if r.get("site") == site and str(r.get("status", "")).strip() == "未着手"
            and str(r.get("keyword", ""))
            and not bad(str(r.get("keyword", "")))]
    if bad(kw0):
        if not todo:
            return None
        r0 = todo[0]
        got = dict(got)
        got.update({"keyword": str(r0["keyword"]), "aim": r0.get("aim", ""), "category": r0.get("category", ""),
                    "picked_by": "打ち出し外の語を飛ばした" if dropped(kw0) else "担当領域の外の語を飛ばした"})
        kw0 = got["keyword"]

    # 同じ規則に当たる語の中では、15位以内に届きそうな細い語を先に書く（kw_reach の段。
    # 段が同じなら台帳の並びのまま）。公開1〜4週に15位以内へ入った記事だけが6週以降も残った（2026-10-05）
    try:
        import kw_reach
        held = kw_reach.held_queries(site)
        reach_band = lambda k: kw_reach.band(kw_reach.reach(k, held=held))
        todo.sort(key=lambda r: -reach_band(str(r["keyword"])))
    except Exception:
        reach_band = None

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
    # 検索の実績で4〜30位・表示10回以上なのに狙う記事が無かった語（kw_plan が積んだ・data/kw_origin.json の proven）。
    # 需要と届く見込みが実測で分かっている語を、台帳の並びや語の形の規則より先に書く（2026-10-09 運用者の決定）
    proven = _proven_targets(site)
    if proven:
        hit = pick(lambda k: _norm(k) in proven, "実証済みの語（4〜30位）")
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
    if reach_band and reach_band(kw0) < 0:
        # 台帳の先頭が広い語（「aio対策」のような1語）なら、同じ主力の中で届く語を先に書く。
        # 広い語は山の週でも20位より下にとどまり、6週で消えた
        hit = pick(lambda k: reach_band(k) > 0 and (not pat or re.search(pat, k.lower())), "15位に届く細い語")
        if hit:
            return hit
    if pat:
        if re.search(pat, kw0.lower()):
            return got                   # すでに主力の語ならそのまま
        hit = pick(lambda k: bool(re.search(pat, k.lower())), "主力優先")
        if hit:
            return hit
    return got                           # 主力の語が尽きていれば、あるものを書く


def _drop_pattern(site):
    """sites/<id>.json の drop_kw（打ち出しから外した語）を1つの正規表現にする。無ければ空"""
    import re
    try:
        import sites as _S           # お客様の社の設定は非公開の置き場の分を重ねて読む
        cfg = _S.load_all().get(site) or {}
    except Exception:
        return ""
    words = [w for w in cfg.get("drop_kw") or [] if w]
    return "|".join(re.escape(w.lower()) for w in words)


def _unfit(site):
    """担当領域の外（kw_fit の判定2）の語か、を返す関数。判定を読み込めなければ止めない"""
    try:
        import kw_fit
    except Exception:
        return lambda k: False
    return lambda k: kw_fit.judge(k, site)[0] >= 2


def _norm(s):
    import re
    return re.sub(r"[\s　・･／/（）()｜|【】\[\]「」、。,.\-‐－—_]", "", str(s).lower())


def _proven_targets(site):
    """kw_plan が積んだ語のうち、検索の実績で4〜30位にいた（実証済みの）語。お客様の社の分は置き場から合わせて読む"""
    try:
        import client_private as CP
        d = CP.load_dict("data/kw_origin.json").get(site) or {}
    except Exception:
        return set()
    return {_norm(v.get("kw", "")) for v in d.values() if isinstance(v, dict) and v.get("proven")} - {""}


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


def kw_context():
    """重複を見る組と地域（sites.kw_context）。読めなければ None（管制塔は全社を1つの組として扱い、従来どおり弾く）"""
    try:
        import sites
        return sites.kw_context()
    except Exception:
        return None


def claim_kw(site, keyword):
    return _post({"action": "claim_kw", "site": site, "keyword": keyword, "ctx": kw_context()}) if enabled() else None


def retire_kw(site, keywords, reason, force=False):
    """食い合い等で書けないKWを台帳から退避する（状態を「対象外」にする）"""
    if not enabled():
        return None
    return _post({"action": "retire_kw", "site": site, "keywords": keywords,
                  "reason": reason, "force": force})


def add_kw(site, keywords):
    """同じ組（自社3サイト・同じお客様）の語は弾き、組の違う社と重なった語は登録して「KW重複の確認」に残す。
    担当領域の外の語（kw_fit の判定2）は台帳へ送らない。積む道具が8つあり、どれか1つの基準が甘いと
    そこから漏れる（「記帳 やり方 ゆうちょ」がコーポレートの表示の4割になった。2026-10-08）"""
    if not enabled():
        return None
    unfit, keep, skipped = _unfit(site), [], []
    for k in keywords or []:
        kw = str(k.get("keyword", "") if isinstance(k, dict) else k)
        if unfit(kw):
            import kw_fit
            skipped.append({"keyword": kw, "why": kw_fit.judge(kw, site)[1]})
        else:
            keep.append(k)
    if not keep:
        return {"ok": True, "added": 0, "keywords": [], "skipped_unfit": skipped}
    r = _post({"action": "add_kw", "site": site, "keywords": keep, "ctx": kw_context()})
    return dict(r, skipped_unfit=skipped) if skipped and isinstance(r, dict) else r


def kw_overlaps():
    """「KW重複の確認」の行。古い管制塔（rows を返さない）は None"""
    d = _get({"action": "kw_overlaps"})
    return d.get("rows") if isinstance(d, dict) and isinstance(d.get("rows"), list) else None


def overlaps_report():
    """週次の findings が呼ぶ。未確認の重複を要対応として出す（見つかっても終了コードは0。印で知らせる）"""
    if not enabled():
        print("KW_OVERLAP_OK=unset（HUB_URL が未設定）")
        return 0
    try:
        got = kw_overlaps()
    except Exception as e:
        print(f"  管制塔を読めません（{type(e).__name__}）")
        print("KW_OVERLAP_OK=unknown")
        return 0
    if got is None:
        print("  管制塔が「KW重複の確認」に対応していません（automation/gas/hub.gs を配布してください）")
        print("KW_OVERLAP_OK=unknown")
        return 0
    todo = [r for r in got if str(r.get("status") or "").strip() in ("", "未確認")]
    print(f"■ KW重複の確認（組の違う社が同じ語を持っている）: 未確認 {len(todo)}件 / 全{len(got)}件")
    # お客様の社を含む組は語を出さない（CI のログ・通知は public の実行記録に残る。語は管制塔の表で見る）
    import sites as _S
    mine = [r for r in todo if _S.is_client(r.get("site_a")) or _S.is_client(r.get("site_b"))]
    for r in [r for r in todo if r not in mine][:30]:
        print(f"  - 「{r.get('keyword')}」 {r.get('site_a')}（{r.get('region_a') or '地域不明'}・先に登録）"
              f" ↔ {r.get('site_b')}（{r.get('region_b') or '地域不明'}）")
    if mine:
        print(f"  - お客様の社を含む重複 {len(mine)}件（語は管制塔の「KW重複の確認」の表で見てください）")
    if todo:
        print(f"要対応: 組の違う社が同じ語を持っています（未確認{len(todo)}件）。管制塔の「KW重複の確認」で"
              "状態を「両方使う」か「片方を外す」にしてください")
    print("KW_OVERLAP_OK=" + ("no" if todo else "yes"))
    return 0


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
    if sys.argv[1:2] == ["overlaps"]:
        return overlaps_report()
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
        # 管制塔は失敗しても {ok:false} を返す（error_log は例外なら None）。見ずに「記録しました」と出さない
        r = error_log("", site, " ".join(sys.argv[3:]))
        if r and r.get("ok"):
            print("エラーログへ記録しました" + ("（同じ内容が未対応で残っているため積みません）"
                                                if r.get("skipped") else ""))
        else:
            print(f"エラーログへ記録できませんでした: {(r or {}).get('error', '管制塔に接続できません')}")
    else:
        raise SystemExit(
            "使い方: python scripts/hub_client.py [status|next|all] [site]\n"
            "        python scripts/hub_client.py error_log <phase> <message>")


if __name__ == "__main__":
    main()
