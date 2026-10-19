# -*- coding: utf-8 -*-
"""Core Web Vitals を毎週実測し、閾値を割ったページを知らせる。

**なぜ要るか**: 8.4節に「LCP≤2.5s / INP≤200ms / CLS≤0.1」と書いてあるが、
実測する工程が無かった。速度は順位の前提で、崩れても「何も起きない」形で
現れる（実際、Webフォントで LCP 7〜13秒だった期間があった）。

PageSpeed Insights API（鍵なしで使える。1日の上限は低いので、1サイト2URL・週1回）。
フィールドデータ（実利用者・28日）があればそれを、無ければラボ値を使う。
ラボ値は1回ごとに大きく揺れるので、基準を割った回だけ同じURLを測り直し（合わせて3回まで・60秒あけて）、
中央値で判定する（lab_verdict / settled / remeasure）。基準内の1回目と実利用者の値は測り直さない。

  python scripts/cwv_check.py            # 3サイト × トップ＋記事1本（PageSpeed）と、実利用者の値（CrUX）
  python scripts/cwv_check.py --site ai-lab --url https://ai.7senses.co.jp/lp/
  python scripts/cwv_check.py --crux     # CrUX だけ
出す印: CWV_OK=yes/no。割った項目は「要対応:」で始める。記録: data/cwv.jsonl

**実利用者の値（CrUX API）**: PageSpeed の1URL・1回の計測は揺れるうえ、ラボ値は実際の読者の端末と違う。
Chrome UX Report（実際に Chrome で開いた人の28日間の75パーセンタイル）を、origin（PHONE/DESKTOP）と
表示の多いURL上位で取り、履歴（25週）で「基準を割った」「悪化が続いている」を見つける。
アクセスの少ないURLは 404（データ無し）が返る。これは遅いという意味ではないので、判定に使わない。
記録: data/cwv_crux/<site>.json（お客様の社は .gitignore）。出す印: CRUX_OK=yes/no/unset。
API が使えなかった（鍵の制限・未有効化）ときは CRUX_OK=unknown を出して終了コード1。
"""
import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
LOG = ROOT / "data" / "cwv.jsonl"
API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
LIMITS = {"LCP": 2500, "INP": 200, "CLS": 0.1}
UA = {"User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0; +https://ai.7senses.co.jp/)"}
# ラボ値（Lighthouse の見積もり）は1回ごとに大きく揺れる。2026-10-12 の ai-lab のトップは、同じ日に
# LCP 4.7秒・1.7秒・1.7秒。計測タグ（169KB）が最初の描画より先に読まれた回だけ、その分が見積もりに入る。
# 基準を割った回だけ測り直し、3回の中央値で判定する（実利用者の値 field は28日の集計なので1回）
LAB_RUNS = 3
PSI_GAP = 60          # 同じURLを続けて頼むと PageSpeed は直前の結果を返す（18秒後は同じ fetchTime、50秒後は新しい結果）


def _key(names=("PAGESPEED_API_KEY", "YOUTUBE_API_KEY")):
    """鍵なしは 1分あたりの上限が低く 429 になる。Google Cloud の APIキーで上限が上がる
    （PAGESPEED_API_KEY。無ければ同じプロジェクトの YOUTUBE_API_KEY を試す）"""
    import os
    for k in names:
        v = os.environ.get(k, "")
        if not v:
            env = ROOT / ".env"
            if env.is_file():
                for ln in env.read_text(encoding="utf-8-sig").splitlines():
                    if ln.startswith(k + "="):
                        v = ln.split("=", 1)[1].strip().strip('"')
        if v:
            return v
    return ""


_SA_TOKEN = None


def _sa_token():
    """サービスアカウントの鍵があれば、それで呼ぶ（キーのある別プロジェクトでは API が無効で 403 だった。
    鍵のプロジェクト ss-aio-media では有効にしてある）。PageSpeed の OAuth の範囲は openid"""
    global _SA_TOKEN
    if _SA_TOKEN is None:
        _SA_TOKEN = ""
        sa = ROOT / "indexing-service-account.json"
        if sa.is_file():
            try:
                import gcreds
                import google.auth.transport.requests as gr
                c = gcreds.load(sa, ["openid"])
                c.refresh(gr.Request())
                _SA_TOKEN = c.token
            except Exception as e:
                print(f"   サービスアカウントで鍵を取れません: {str(e)[:120]}")
                _SA_TOKEN = ""
    return _SA_TOKEN


def measure(url, strategy="mobile"):
    params = {"url": url, "strategy": strategy, "category": "performance"}
    # CI では 403 の理由が分からず「鍵を足してください」と誤った指示を出した。
    # 経路を順に試し、落ちたら Google の返した理由をそのまま出す
    routes = []
    if _sa_token():
        routes.append(("サービスアカウント", {}, {"Authorization": f"Bearer {_sa_token()}"}))
    if _key():
        routes.append(("APIキー", {"key": _key()}, {}))
    routes.append(("鍵なし", {}, {}))
    errs = []
    for name, extra, headers in routes:
        q = urllib.parse.urlencode({**params, **extra})
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{API}?{q}", headers=headers), timeout=120) as r:
                d = json.loads(r.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
            except Exception:
                msg = ""
            errs.append(f"{name}={e.code} {msg[:90]}")
    else:
        raise RuntimeError(" / ".join(errs))
    out = {"url": url, "strategy": strategy, "source": "lab"}
    field = (d.get("loadingExperience") or {}).get("metrics") or {}
    if field:
        out["source"] = "field"
        out["LCP"] = (field.get("LARGEST_CONTENTFUL_PAINT_MS") or {}).get("percentile")
        out["INP"] = (field.get("INTERACTION_TO_NEXT_PAINT") or {}).get("percentile")
        cls = (field.get("CUMULATIVE_LAYOUT_SHIFT_SCORE") or {}).get("percentile")
        out["CLS"] = cls / 100 if cls is not None else None
    audits = ((d.get("lighthouseResult") or {}).get("audits") or {})
    if out.get("LCP") is None:
        out["LCP"] = (audits.get("largest-contentful-paint") or {}).get("numericValue")
    if out.get("CLS") is None:
        out["CLS"] = (audits.get("cumulative-layout-shift") or {}).get("numericValue")
    if out.get("INP") is None:
        out["INP"] = (audits.get("interaction-to-next-paint") or {}).get("numericValue")  # ラボでは出ないことが多い
    out["score"] = round(((d.get("lighthouseResult") or {}).get("categories") or {})
                         .get("performance", {}).get("score", 0) * 100)
    out["_fetched"] = (d.get("lighthouseResult") or {}).get("fetchTime") or ""   # 記録には残さない（_ で始まる）
    return out


def sample_urls(cfg):
    """トップと、sitemap の末尾の記事1本"""
    import re
    urls = [f"https://{cfg['domain']}/"]
    try:
        # Python の既定の名乗り（Python-urllib）は Cloudflare が 403 で断り、記事が1本も測られていなかった
        # （2026-10-12 まで data/cwv.jsonl はトップだけ）
        req = urllib.request.Request(f"https://{cfg['domain']}/sitemap.xml", headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            locs = re.findall(r"<loc>(.*?)</loc>", r.read().decode("utf-8"))
        pre = (cfg.get("url_prefix") or "").strip("/")
        art = [u for u in locs if u.count("/") >= 4 and (not pre or f"/{pre}/" in u)]
        if art:
            urls.append(art[-1])          # 新しめの記事（末尾）
    except Exception:
        pass
    return urls


def over_limits(m):
    """1回の計測で基準を割った指標"""
    return [k for k, lim in LIMITS.items() if m.get(k) is not None and m[k] > lim]


def lab_verdict(runs):
    """同じURLを測った回（1〜LAB_RUNS 回）の中央値で判定する。戻り値: (基準を割った指標, 指標ごとの中央値)"""
    med = {}
    for k in LIMITS:
        vals = [r[k] for r in runs if r.get(k) is not None]
        if vals:
            med[k] = statistics.median(vals)
    return [k for k, lim in LIMITS.items() if k in med and med[k] > lim], med


def settled(runs):
    """もう測り直さなくてよいか。実利用者の値（field）・1回目が基準内なら1回で決める。
    1回目が基準を割ったラボ値は、どの指標も過半（3回中2回）が同じ側にそろうまで測る"""
    if not runs or runs[0].get("source") != "lab" or len(runs) >= LAB_RUNS:
        return True
    if len(runs) == 1 and not over_limits(runs[0]):
        return True
    need = LAB_RUNS // 2 + 1
    for k, lim in LIMITS.items():
        vals = [r[k] for r in runs if r.get(k) is not None]
        n_over = sum(v > lim for v in vals)
        if vals and n_over < need and len(vals) - n_over < need:
            return False
    return True


def remeasure(pages, measure_fn=None, clock=None, sleep=None, on_run=None):
    """基準を割ったラボ値のページだけ、決まるまで測り直す。pages は {"url", "runs", "at"} の list（その場で足す）。
    同じURLは PSI_GAP 秒あけ、PageSpeed の控え（同じ fetchTime）が返ったら数えない。on_run(page, m) は数えた回ごと"""
    measure_fn, clock, sleep = measure_fn or measure, clock or time.monotonic, sleep or time.sleep
    for _ in range(LAB_RUNS - 1):
        for p in pages:
            if settled(p["runs"]):
                continue
            wait = PSI_GAP - (clock() - p["at"])
            if wait > 0:
                sleep(wait)
            try:
                m = measure_fn(p["url"])
            except Exception as e:
                p.setdefault("errors", []).append(str(e)[:200])
                continue
            finally:
                p["at"] = clock()
            if m.get("_fetched") and m["_fetched"] in {r.get("_fetched") for r in p["runs"]}:
                p["cached"] = p.get("cached", 0) + 1
                continue
            p["runs"].append(m)
            if on_run:
                on_run(p, m)
    return pages


# ---- 実利用者の値（Chrome UX Report API） ----
# https://developer.chrome.com/docs/crux/api ・ https://developer.chrome.com/docs/crux/history-api
# 認証は APIキーだけ（サービスアカウントのトークンは 400 になった。2026-10-07 実測）。上限は 1プロジェクト150回/分
CRUX_API = "https://chromeuxreport.googleapis.com/v1/records:"
CRUX_DIR = ROOT / "data" / "cwv_crux"
CRUX_KEYS = ("CRUX_API_KEY", "PAGESPEED_API_KEY", "YOUTUBE_API_KEY")
CRUX_METRICS = {"LCP": "largest_contentful_paint", "INP": "interaction_to_next_paint",
                "CLS": "cumulative_layout_shift"}
FORMS = ("PHONE", "DESKTOP")
TOP_URLS = 5          # 表示の多いURL。多くしても、アクセスの少ないURLはデータ無しが返るだけ
HIST_WEEKS = 25
TREND_RATIO = 1.2     # 直近が、それより前の週の中央値の1.2倍以上
CRUX_PAUSE = 0.45     # 1プロジェクト150回/分の内側
TREND_NEAR = 0.8     # かつ基準の8割を超えたら「悪化が続いている」（基準のはるか内側の揺れは知らせない）


class CruxUnavailable(Exception):
    """API そのものが使えない（鍵の制限・API の未有効化）。1件ずつの失敗と分ける"""


def _crux_post(method, body, key):
    """応答の dict。データ無し（404）は None。401/403 は CruxUnavailable、それ以外の失敗は RuntimeError"""
    req = urllib.request.Request(f"{CRUX_API}{method}?key={urllib.parse.quote(key)}",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read().decode("utf-8")).get("error", {})
            except Exception:
                err = {}
            if e.code == 404:
                return None
            reason = ((err.get("details") or [{}])[0] or {}).get("reason", "")
            msg = f"{e.code} {reason} {(err.get('message') or '')[:120]}".strip()
            if e.code in (401, 403):
                raise CruxUnavailable(msg)
            if e.code == 429 and attempt == 0:
                time.sleep(30)
                continue
            raise RuntimeError(msg)
    raise RuntimeError("429")


def _num(v):
    """p75 は数値、CLS は小数2桁の文字列で返る。履歴の欠けは null、密度は "NaN" """
    if v is None or v == "NaN":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ymd(d):
    return f"{d['year']:04d}-{d['month']:02d}-{d['day']:02d}" if d else ""


def parse_current(resp):
    rec = (resp or {}).get("record") or {}
    m = rec.get("metrics") or {}
    out = {k: _num(((m.get(n) or {}).get("percentiles") or {}).get("p75")) for k, n in CRUX_METRICS.items()}
    cp = rec.get("collectionPeriod") or {}
    out["period"] = [_ymd(cp.get("firstDate")), _ymd(cp.get("lastDate"))]
    return out


def parse_history(resp):
    rec = (resp or {}).get("record") or {}
    m = rec.get("metrics") or {}
    periods = rec.get("collectionPeriods") or (resp or {}).get("collectionPeriods") or []
    out = {"weeks": [_ymd(p.get("lastDate")) for p in periods]}
    for k, n in CRUX_METRICS.items():
        vals = [_num(v) for v in (((m.get(n) or {}).get("percentilesTimeseries") or {}).get("p75s") or [])]
        out[k] = vals
    return out


def judge(metric, current, series):
    """1つの指標の判定。(印, 文) を返す。データが無ければ ("nodata", "")（遅いとは言わない）。
    bad=今の値が基準を割っている / worse=基準の内側だが、それまでの週より悪化が続いている / ok"""
    lim = LIMITS[metric]
    series = list(series or [])
    if current is None:
        current = series[-1] if series else None   # 最新の週が欠けていれば、古い値で判定しない
    if current is None:
        return "nodata", ""
    pts = [v for v in series[:-1] if v is not None]
    if current > lim:
        good = [i for i, v in enumerate(series[:-1]) if v is not None and v <= lim]
        ago = f"（{len(series) - 1 - good[-1]}週前は基準内）" if good else ""
        return "bad", f"{metric} {_fmt(metric, current)}（基準 {_fmt(metric, lim)}）{ago}"
    base = pts[:-3] if len(pts) > 3 else []
    if len(base) >= 8:
        b = sorted(base)[len(base) // 2]
        recent = [v for v in series[-4:] if v is not None]
        if (b > 0 and current >= b * TREND_RATIO and current > lim * TREND_NEAR
                and len(recent) >= 3 and all(v > b for v in recent)):
            return "worse", f"{metric} {_fmt(metric, b)}→{_fmt(metric, current)}（基準 {_fmt(metric, lim)} に近づいています）"
    return "ok", ""


def _fmt(metric, v):
    if v is None:
        return "—"
    return f"{v:.2f}" if metric == "CLS" else (f"{v / 1000:.1f}秒" if metric == "LCP" else f"{round(v)}ms")


def top_urls(sid, cfg, n=TOP_URLS, days=28):
    """表示の多いURL（data/ranks/<site>.json の直近28日。語ごとの表示を URL で足す）。そのサイトのドメインだけ"""
    p = ROOT / "data" / "ranks" / f"{sid}.json"
    if not p.is_file():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    host = (cfg.get("domain") or "").lower()
    tot = {}
    for k in sorted(d)[-days:]:
        for r in d.get(k) or []:
            u = r.get("url") or ""
            if urllib.parse.urlparse(u).netloc.lower() == host:
                tot[u] = tot.get(u, 0) + (r.get("imp") or 0)
    return [u for u, _ in sorted(tot.items(), key=lambda x: -x[1])[:n]]


def crux_site(sid, cfg, key):
    """1サイト分を取って判定する。戻り値: (記録の dict, 要対応の文の list)"""
    pause = CRUX_PAUSE
    origin = f"https://{cfg['domain']}"
    targets = [("origin", origin, f) for f in FORMS] + [("url", u, f) for u in top_urls(sid, cfg) for f in FORMS]
    rows, flags = [], []
    for kind, ident, form in targets:
        body = {kind: ident, "formFactor": form, "metrics": list(CRUX_METRICS.values())}
        row = {"kind": kind, "id": ident, "form": form}
        try:
            cur = _crux_post("queryRecord", body, key)
            time.sleep(pause)
            if cur is None:
                row["status"] = "nodata"
                rows.append(row)
                continue
            hist = _crux_post("queryHistoryRecord", {**body, "collectionPeriodCount": HIST_WEEKS}, key)
            time.sleep(pause)
        except CruxUnavailable:
            raise
        except Exception as e:
            row.update(status="error", error=str(e)[:160])
            rows.append(row)
            continue
        row["status"] = "ok"
        row["current"] = parse_current(cur)
        row["history"] = parse_history(hist) if hist else {"weeks": []}
        row["judge"] = {}
        for m in CRUX_METRICS:
            mark, txt = judge(m, row["current"].get(m), row["history"].get(m))
            row["judge"][m] = mark
            if mark in ("bad", "worse"):
                what = "基準を割っています" if mark == "bad" else "悪化が続いています"
                # お客様の社は公開の id で出し、ページの URL は出さない（知らせる文は CI のログにも出る）
                import sites as S
                client = S.is_client(sid)
                page = "サイト全体" if kind == "origin" else ("（お客様のページ）" if client else ident)
                where = f"{S.public_id(sid) if client else sid} {page} {form}"
                flags.append(f"要対応: 実利用者の表示速度が{what}（CrUX・75パーセンタイル）: {where} … {txt}")
        rows.append(row)
    return {"site": sid, "origin": origin, "limits": LIMITS, "targets": rows}, flags


def crux_path(sid):
    """CrUX のスナップショットの置き場。お客様の社は非公開の置き場（CI のキャッシュ）。public に URL を書かない"""
    import client_private as CP
    import sites as S
    if not S.is_client(sid):
        return CRUX_DIR / f"{sid}.json"
    return CP.site_file(sid, f"data/cwv_crux/{sid}.json")


def save_crux(sid, rec, today=None):
    """スナップショットで上書きし、origin の今の値だけ log に積む（履歴は API が25週を返すので持たない）"""
    p = crux_path(sid)
    p.parent.mkdir(parents=True, exist_ok=True)
    old = {}
    if p.is_file():
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            old = {}
    today = today or date.today().isoformat()
    # 取れなかった（error）ページは、前の回の値を取得日つきで残す。以前は全部失敗した週（5xx・429）に
    # 前の週の値を消し、月次レポートが「実利用者のデータはまだありません」と出していた（2026-10-07 再現）
    prev = {(t.get("kind"), t.get("id"), t.get("form")): t for t in old.get("targets") or []
            if t.get("status") in ("ok", "nodata")}
    targets = []
    for t in rec["targets"]:
        o = prev.get((t["kind"], t["id"], t["form"]))
        if t["status"] == "error" and o:
            targets.append({**o, "stale_from": o.get("stale_from") or old.get("updated", ""),
                            "error": t.get("error", "")})
        else:
            targets.append(t)
    rec = {**rec, "targets": targets}
    entry = {"date": today}
    for t in rec["targets"]:
        if t["kind"] == "origin":
            entry[t["form"]] = ("error" if t.get("stale_from") else
                                {k: t["current"].get(k) for k in CRUX_METRICS} if t["status"] == "ok" else t["status"])
    log = [x for x in (old.get("log") or []) if x.get("date") != today] + [entry]
    p.write_text(json.dumps({**rec, "updated": today, "log": log[-104:]}, ensure_ascii=False, indent=1) + "\n",
                 encoding="utf-8")
    return p


def crux_fix(err):
    """CrUX API が使えない理由から、人がする1つの作業を書く（週次の要対応に載る。CRUX_OK=unknown の印だけでは
    理由が届かず、2026-10-12 の通知は「測れませんでした」だけだった）。データ不足（404）はここに来ない"""
    if "SERVICE_DISABLED" in err:
        what = ("鍵のプロジェクトで Chrome UX Report API が有効になっていません（SERVICE_DISABLED）。"
                "Google Cloud の「APIとサービス」でその鍵のプロジェクトの Chrome UX Report API を有効にするか、"
                "有効なプロジェクトで作った鍵を Secret CRUX_API_KEY に登録してください")
    elif "API_KEY_SERVICE_BLOCKED" in err:
        what = ("鍵の「APIの制限」で Chrome UX Report API が許可されていません（API_KEY_SERVICE_BLOCKED）。"
                "鍵の制限に Chrome UX Report API を足すか、別の鍵を Secret CRUX_API_KEY に登録してください")
    else:
        what = f"鍵か API の設定を確かめてください（{err[:60]}）"
    return f"実利用者の表示速度（CrUX）を測れません: {what}"


def run_crux(site=""):
    """CrUX の検査。戻り値は終了コード（API が使えなかったときだけ1）"""
    import sites as S
    key = _key(CRUX_KEYS)
    if not key:
        print("CrUX: APIキーがありません（CRUX_API_KEY / PAGESPEED_API_KEY / YOUTUBE_API_KEY）")
        print("CRUX_OK=unset")
        return 0
    flags, n_ok, n_nodata, n_err = [], 0, 0, 0
    for sid, cfg in S.load_all().items():
        if (site and sid != site) or not cfg.get("domain"):
            continue
        try:
            rec, fl = crux_site(sid, cfg, key)
        except CruxUnavailable as e:
            print(f"   CrUX API が使えません: {e}")
            print(f"要対応: {crux_fix(str(e))}")
            print("CRUX_OK=unknown")
            return 1
        save_crux(sid, rec)
        flags += fl
        for t in rec["targets"]:
            n_ok += t["status"] == "ok"
            n_nodata += t["status"] == "nodata"
            n_err += t["status"] == "error"
            label = "サイト全体" if t["kind"] == "origin" else t["id"][:60]
            # お客様の社は公開の id で出し、ページの URL は出さない（CI のログは public）
            name = S.public_id(sid) if S.is_client(sid) else sid
            if S.is_client(sid) and t["kind"] != "origin":
                label = "（お客様のページ）"
            if t["status"] == "ok":
                c = t["current"]
                print(f"   [{name:<9}] {t['form']:<7} {label:<60} LCP {_fmt('LCP', c.get('LCP'))} "
                      f"INP {_fmt('INP', c.get('INP'))} CLS {_fmt('CLS', c.get('CLS'))}")
            else:
                print(f"   [{name:<9}] {t['form']:<7} {label:<60} "
                      + ("データ無し（アクセスが少ない。遅いという意味ではない）" if t["status"] == "nodata"
                         else f"取れませんでした {t.get('error', '')}"))
    print(f"CrUX: データあり {n_ok}件・データ無し {n_nodata}件・取得失敗 {n_err}件")
    for f in flags:
        print(f)
    if n_err and not (n_ok or n_nodata):
        print("CRUX_OK=unknown")
        return 1
    if flags:
        print("CRUX_OK=no")
    elif n_ok:
        print("CRUX_OK=yes")
    else:
        print("CRUX_OK=unset（実利用者のデータがまだどこにもありません。アクセスが増えると Google が出します）")
    return 0


def crux_html(sid):
    """月次レポートの「実際の利用者の表示速度」の中身。記録が無ければ ""（節を出さない）"""
    import html as H
    p = crux_path(sid)
    if not p.is_file():
        return ""
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return ""
    ok = [t for t in d.get("targets") or [] if t.get("status") == "ok"]
    nodata = [t for t in d.get("targets") or [] if t.get("status") == "nodata"]
    out = ['<p style="font-size:9.5pt">実際に Chrome でページを開いた人の、直近28日間の75パーセンタイルです'
           '（Chrome UX Report）。「良好」の基準は LCP 2.5秒以下・INP 200ms以下・CLS 0.1以下です。'
           f'取得日: {H.escape(d.get("updated", ""))}</p>']
    errors = [t for t in d.get("targets") or [] if t.get("status") == "error"]
    if not ok:
        if errors and not nodata:
            out.append('<div class="callout"><b>この回は実利用者の値を取得できませんでした。</b>'
                       'データが無いという意味でも、遅いという意味でもありません。</div>')
        else:
            out.append('<div class="callout"><b>実利用者のデータはまだありません。</b>アクセスが一定数に届くまで、'
                       'Google はデータを出しません。遅いという意味ではありません。</div>')
        return "\n".join(out)
    cell = (lambda t, m: f'{_fmt(m, t["current"].get(m))}'
            + {"bad": " ×", "worse": " △"}.get((t.get("judge") or {}).get(m), ""))
    tr = "".join(f'<tr><td>{"サイト全体" if t["kind"] == "origin" else H.escape(t["id"].split("://", 1)[-1])}</td>'
                 f'<td>{"スマホ" if t["form"] == "PHONE" else "パソコン"}</td>'
                 + "".join(f'<td class="num">{cell(t, m)}</td>' for m in CRUX_METRICS) + '</tr>' for t in ok)
    out.append('<table><tr><th>ページ</th><th>端末</th><th>LCP</th><th>INP</th><th>CLS</th></tr>' + tr + '</table>')
    note = '× は基準を割っている、△ は基準内だがそれまでの週より悪化が続いている指標です。'
    if nodata:
        note += (f'ほかに {len({t["id"] for t in nodata})} ページはアクセスが少なくデータがありません'
                 '（遅いという意味ではありません）。')
    stale = sorted({t["stale_from"] for t in ok if t.get("stale_from")})
    if stale:
        note += f'この回に取れなかったページは、前回（{H.escape("・".join(stale))}）の値です。'
    out.append(f'<p class="note">{note}</p>')
    return "\n".join(out)


def main():
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--url", default="")
    ap.add_argument("--crux", action="store_true", help="CrUX（実利用者の値）だけ")
    ap.add_argument("--no-crux", action="store_true")
    a = ap.parse_args()
    if a.crux:
        return run_crux(a.site)
    bad, rows, pages = [], [], []
    missed = []          # 1ページでも測れなかったサイト（公開の id）

    def record(p, m):
        rows.append({"date": date.today().isoformat(), "site": p["sid"],
                     **{k: v for k, v in m.items() if not k.startswith("_")}})
        over = over_limits(m)
        again = f"（{len(p['runs'])}回目）" if len(p["runs"]) > 1 else ""
        print(f"   {'×' if over else '○'} [{p['name']:<9}] {p['shown'][:52]:<52} 総合{m['score']:>3} "
              f"LCP {m.get('LCP') and round(m['LCP'])}ms INP {m.get('INP') and round(m['INP'])}ms "
              f"CLS {m.get('CLS') and round(m['CLS'], 3)}（{m['source']}）{again}")

    for sid, cfg in S.load_all().items():
        if a.site and sid != a.site:
            continue
        # お客様の社は公開の id で出し、URL は出さない（CI のログは public）
        client = S.is_client(sid)
        for url in ([a.url] if a.url else sample_urls(cfg)):
            name, shown_url = (S.public_id(sid), "（お客様のページ）") if client else (sid, url)
            try:
                m = measure(url)
            except Exception as e:
                print(f"   {name}: 計測できません {shown_url[:50]} ({str(e)[:300]})")
                if name not in missed:
                    missed.append(name)
                continue
            p = {"sid": sid, "url": url, "name": name, "shown": shown_url, "runs": [m], "at": time.monotonic()}
            pages.append(p)
            record(p, m)
            time.sleep(2)
    remeasure(pages, on_run=record)
    for p in pages:
        over, med = lab_verdict(p["runs"])
        n = len(p["runs"])
        if n > 1:
            vals = "・".join(f"{r['LCP'] / 1000:.1f}" for r in p["runs"] if r.get("LCP") is not None)
            print(f"     → [{p['name']}] {n}回の中央値で判定: LCP {_fmt('LCP', med.get('LCP'))}（{vals}秒）"
                  f"{'・基準を割っています' if over else '・基準内'}")
        if p.get("cached"):
            print(f"     → [{p['name']}] 測り直しに直前の控えが返った回は数えませんでした（{p['cached']}回）")
        if over:
            how = (f"（{n}回の中央値: " if n > 1 else "（実利用者の28日の値: "
                   if p["runs"][0].get("source") == "field" else "（1回だけの値・測り直せず: ")
            bad.append(f"{p['name']} {p['shown']} … " + "・".join(over) + how
                       + "・".join(f"{k} {_fmt(k, med[k])}" for k in over) + "）")
    # お客様の社の行は非公開の置き場へ（public の data/cwv.jsonl にドメインの URL を書かない。2026-10-12）
    import client_private as CP
    LOG.parent.mkdir(exist_ok=True)
    for r in rows:
        CP.append_jsonl(LOG, r, sid=r["site"])
    for b in bad:
        print(f"要対応: 表示速度が基準を割っています: {b}")
    if not rows:
        print("CWV_OK=unknown（計測できませんでした。429=鍵なしの上限、403=Google Cloud で "
              "「PageSpeed Insights API」が未有効。有効にするか PAGESPEED_API_KEY を設定）")
    elif bad:
        print("CWV_OK=no")
    elif missed:
        # 測れたページが基準内でも、測れなかったサイトがあるのに yes と出さない（2026-10-20）
        print(f"CWV_OK=unknown（測れなかったサイト: {'・'.join(missed)}）")
    else:
        print("CWV_OK=yes")
    if a.no_crux or a.url:
        return 0
    return run_crux(a.site)


if __name__ == "__main__":
    sys.exit(main())
