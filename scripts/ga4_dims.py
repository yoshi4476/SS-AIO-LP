# -*- coding: utf-8 -*-
"""GA4 のカスタムディメンション（イベントの範囲）を登録する。拡張計測の「フォームの操作」を止める。

site.js などが出来事に付けている値（最後に触った項目・フォームの種類・ボタンのID・記事のパス・ツール）は、
GA4 の「カスタム定義」に登録しないと Data API から読めない。登録されていなかったため、
form_abandon がどの項目で起きたか、記事の入力欄がどの記事で使われたかを集計できなかった（2026-10-05）。

  python scripts/ga4_dims.py                  # 何を登録するかを見るだけ（既定）
  python scripts/ga4_dims.py --apply          # 登録する（サービスアカウントにプロパティの編集権限が要る）
  python scripts/ga4_dims.py --site ai-lab    # 1サイトだけ
  python scripts/ga4_dims.py --forms-off [--apply]   # 自前の計測が出ている社だけ、拡張計測の「フォームの操作」を止める

登録は足すだけで、既存の定義は変えない。登録した日より前の出来事には値が付かない（GA4 の仕様）。

**拡張計測の「フォームの操作」**: GA4 が自動で送る form_start・form_submit は、自前の計測（site.js・
コーポレートの ContactForm・補助金のフォーム・CONFLUX の Measure.tsx）と同じ名前で、入力開始と送信が2重に出る
（AI集客ラボ /contact/ の 10/7: form_start 2・form_submit 2 で、問い合わせは1件）。止めるのは、自前の計測が
実際に出ている（種類つきの form_start と、離脱・種類つきの送信・問い合わせのどれか）と GA4 で確かめた社だけ。
確かめられない社は変えずに知らせる（止めると入力開始が0になり、数えられなくなる）。止めた日と変える前の値は
data/ga4_settings.json に残し、ファネル・月次レポートが「この日より前は重なっている」と添える。
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

API = "https://analyticsadmin.googleapis.com/v1beta"
API_ALPHA = "https://analyticsadmin.googleapis.com/v1alpha"      # 拡張計測の設定は v1alpha にしかない
SETTINGS = ROOT / "data" / "ga4_settings.json"
# (パラメータ名, 表示名)。lead_route は funnel.py の送信の内訳に要る。cta_kind はコーポレートの入口の種類
# （contact / doc / tool / diagnosis。月次レポートの「うち問い合わせ方向」をこれで数える）。
# 表示名に記号（全角の括弧など）は使えない（400「alphanumeric, underscore, or space」。CONFLUX で page_path が落ちた）
DIMS = [
    ("last_field", "最後に触った項目"),
    ("form_type", "フォームの種類"),
    ("cta_id", "ボタンのID"),
    ("cta_kind", "入口の種類"),
    ("page_path", "出来事のページ 記事のパス"),
    ("tool", "ツール"),
    ("lead_route", "送信の経路"),
]
VERIFY_DAYS = 14        # 自前の計測が出ているかを見る日数（今日を含む）


def session():
    import gcreds
    from google.auth.transport.requests import AuthorizedSession
    return AuthorizedSession(gcreds.load(ROOT / "indexing-service-account.json",
                                         ["https://www.googleapis.com/auth/analytics.edit"]))


def why(r):
    """403 の理由を分ける。API が無効なのか（GCP で有効にする）、権限が無いのか（GA4 で編集者を付ける）で直す人が違う"""
    try:
        e = r.json().get("error", {})
    except Exception:
        return str(r.status_code)
    if any(isinstance(d, dict) and d.get("reason") == "SERVICE_DISABLED" for d in e.get("details", [])):
        return "API_DISABLED"
    return f'{r.status_code} {e.get("status", "")}'


def existing(s, prop):
    r = s.get(f"{API}/properties/{prop}/customDimensions", params={"pageSize": 200})
    if not r.ok:
        raise RuntimeError(why(r))
    return {d["parameterName"] for d in r.json().get("customDimensions", [])}


# ── 拡張計測の「フォームの操作」 ─────────────────────────────

def own_form_counts(prop, days=VERIFY_DAYS):
    """自前の計測だけが送る出来事の件数（直近 days 日・今日を含む）。
    種類（form_type）つきの form_start・form_submit、form_abandon（GA4 は送らない）、問い合わせ（lead_capture・generate_lead）。
    form_type が GA4 に未登録なら種類つきは数えられない（0）"""
    import gcreds
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (DateRange, Dimension, Filter, FilterExpression, Metric,
                                                    RunReportRequest)
    cl = BetaAnalyticsDataClient(credentials=gcreds.load(ROOT / "indexing-service-account.json",
                                                         ["https://www.googleapis.com/auth/analytics.readonly"]))
    names = ["form_start", "form_submit", "form_abandon", "lead_capture", "generate_lead"]
    filt = FilterExpression(filter=Filter(field_name="eventName", in_list_filter=Filter.InListFilter(values=names)))
    rng = [DateRange(start_date=f"{days - 1}daysAgo", end_date="today")]
    out = {"typed_start": 0, "typed_submit": 0, "abandon": 0, "leads": 0, "types": []}
    try:
        r = cl.run_report(RunReportRequest(property=f"properties/{prop}", date_ranges=rng,
                                           dimensions=[Dimension(name="eventName"), Dimension(name="customEvent:form_type")],
                                           metrics=[Metric(name="eventCount")], dimension_filter=filt, limit=1000))
        rows = [(x.dimension_values[0].value, x.dimension_values[1].value, int(x.metric_values[0].value)) for x in r.rows]
    except Exception as e:
        if "not a valid dimension" not in str(e):
            raise
        r = cl.run_report(RunReportRequest(property=f"properties/{prop}", date_ranges=rng,
                                           dimensions=[Dimension(name="eventName")], metrics=[Metric(name="eventCount")],
                                           dimension_filter=filt, limit=100))
        rows = [(x.dimension_values[0].value, "", int(x.metric_values[0].value)) for x in r.rows]
    for ev, ft, n in rows:
        typed = ft not in ("", "(not set)")
        if ev == "form_start" and typed:
            out["typed_start"] += n
            out["types"].append(ft)
        elif ev == "form_submit" and typed:
            out["typed_submit"] += n
        elif ev == "form_abandon":
            out["abandon"] += n
        elif ev in ("lead_capture", "generate_lead"):
            out["leads"] += n
    out["types"] = sorted(set(out["types"]))
    return out


def verified(c):
    """(止めてよいか, 理由)。自前の form_start（種類つき）が出ていて、離脱・種類つきの送信・問い合わせのどれかも出ていること。
    form_start が無いまま止めると、入力開始を数える出来事が1つも無くなる"""
    if not c:
        return False, "GA4 から読めませんでした"
    if not c.get("typed_start"):
        return False, "自前の form_start（種類つき）がまだ出ていません"
    if not (c.get("abandon") or c.get("typed_submit") or c.get("leads")):
        return False, "自前の離脱・送信がまだ出ていません"
    return True, (f"自前の form_start {c['typed_start']}件・離脱 {c.get('abandon', 0)}件・"
                  f"種類つきの送信 {c.get('typed_submit', 0)}件・問い合わせ {c.get('leads', 0)}件")


def _record(site, entry):
    try:
        d = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {"_why": "GA4 の管理設定を変えた記録（ga4_dims.py --forms-off）。ファネル・月次レポートが、"
                     "止めた日より前の入力開始・送信には拡張計測の分が重なっていると添える"}
    d.setdefault("form_interactions_off", {})[site] = entry
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


def forms_off(s, site, prop, apply, counts=own_form_counts, today=None):
    """1社分。自前の計測を確かめてから、Web のデータストリームの formInteractionsEnabled を false にする"""
    res = {"site": site, "changed": False, "streams": []}
    r = s.get(f"{API_ALPHA}/properties/{prop}/dataStreams")
    if not r.ok:
        res["why"] = f"データストリームを読めません（{why(r)}）"
        print(f"■ {site}（{prop}）: {res['why']}")
        return res
    webs = [x["name"] for x in r.json().get("dataStreams", []) if x.get("type") == "WEB_DATA_STREAM"]
    settings = {}
    for name in webs:
        g = s.get(f"{API_ALPHA}/{name}/enhancedMeasurementSettings")
        if g.ok:
            settings[name] = g.json()
    on = [n for n, v in settings.items() if v.get("formInteractionsEnabled")]
    if not on:
        res["why"], res["off_already"] = "フォームの操作はもう止まっています", True
        print(f"■ {site}（{prop}）: {res['why']}")
        return res
    try:
        c = counts(prop)
    except Exception as e:
        c, res["why"] = None, f"GA4 から読めません（{str(e)[:60]}）"
    ok, reason = verified(c)
    res["why"], res["verified"] = res.get("why") or reason, ok
    print(f"■ {site}（{prop}）: {'止めます' if ok else '変えません'} … {reason}")
    if not ok or not apply:
        return res
    for name in on:
        p = s.patch(f"{API_ALPHA}/{name}/enhancedMeasurementSettings", params={"updateMask": "formInteractionsEnabled"},
                    json={"formInteractionsEnabled": False})
        if not p.ok:
            print(f"   変えられません: {name}（{why(p)}）")
            continue
        print(f"   止めました: {name}（formInteractionsEnabled: true → false）")
        res["changed"] = True
        res["streams"].append(name)
        _record(site, {"at": today or date.today().isoformat(), "stream": name,
                       "before": settings[name], "seen": {k: v for k, v in (c or {}).items() if v}})
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--site")
    ap.add_argument("--forms-off", action="store_true", help="拡張計測の「フォームの操作」を止める（確かめた社だけ）")
    a = ap.parse_args()
    import sites as _S             # 計測の ID はお客様の社だと非公開の置き場にある（load_all が重ねる）
    conf = _S.load_all()
    targets = [(k, c["ga4_property_id"]) for k, c in conf.items()
               if c.get("ga4_property_id") and (not a.site or k == a.site)]
    if not targets:
        print("対象のプロパティがありません")
        return 1
    s = session()
    if a.forms_off:
        # 確かめられた社は、--apply の無い回（見るだけ）では要対応にしない
        kept = [r for r in (forms_off(s, site, prop, a.apply) for site, prop in targets)
                if not r["changed"] and not r.get("off_already") and (a.apply or not r.get("verified"))]
        for r in kept:
            print(f"要対応: {r['site']} の拡張計測（フォームの操作）は止めていません（{r.get('why')}）。"
                  "自前の計測が出てから --forms-off --apply をやり直す")
        print("FORMS_OFF_OK=" + ("no" if kept else "yes"))
        return 0
    denied, disabled = [], False
    for site, prop in targets:
        try:
            have = existing(s, prop)
        except Exception as e:
            print(f"■ {site}（{prop}）: 一覧を読めません（{str(e)[:60]}）")
            if str(e) == "API_DISABLED":
                disabled = True
            denied.append(site)
            continue
        todo = [d for d in DIMS if d[0] not in have]
        print(f"■ {site}（{prop}）: 登録済み {len([d for d in DIMS if d[0] in have])} / 未登録 {len(todo)}")
        for name, label in todo:
            if not a.apply:
                print(f"   登録する予定: {name}（{label}）")
                continue
            r = s.post(f"{API}/properties/{prop}/customDimensions",
                       json={"parameterName": name, "displayName": label, "scope": "EVENT"})
            if r.ok:
                print(f"   登録しました: {name}")
            else:
                print(f"   登録できません: {name}（{r.status_code}）")
                if r.status_code == 403:
                    denied.append(site)
                    break
    if disabled:
        print("\n■ サービスアカウントの GCP プロジェクトで Google Analytics Admin API が有効になっていません")
        print("   GCP の「API とサービス」で Google Analytics Admin API を有効にし、"
              "GA4 でサービスアカウントにプロパティの「編集者」を付けてから --apply をやり直す")
    if denied:
        print("\n■ 登録できませんでした。人が GA4 の画面で登録する場合")
        print("   管理 → (プロパティ) データの表示 → カスタム定義 → カスタムディメンションを作成")
        print("   範囲: イベント。ディメンション名とイベントパラメータに次をそれぞれ入れる: "
              + " / ".join(n for n, _ in DIMS))
        print("   または、サービスアカウントにプロパティの「編集者」を付けてから --apply をやり直す")
        print(f"   対象: {', '.join(sorted(set(denied)))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
