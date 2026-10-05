# -*- coding: utf-8 -*-
"""GA4 のカスタムディメンション（イベントの範囲）を登録する。

site.js などが出来事に付けている値（最後に触った項目・フォームの種類・ボタンのID・記事のパス・ツール）は、
GA4 の「カスタム定義」に登録しないと Data API から読めない。登録されていなかったため、
form_abandon がどの項目で起きたか、記事の入力欄がどの記事で使われたかを集計できなかった（2026-10-05）。

  python scripts/ga4_dims.py                  # 何を登録するかを見るだけ（既定）
  python scripts/ga4_dims.py --apply          # 登録する（サービスアカウントにプロパティの編集権限が要る）
  python scripts/ga4_dims.py --site ai-lab    # 1サイトだけ

登録は足すだけで、既存の定義は変えない。登録した日より前の出来事には値が付かない（GA4 の仕様）。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

API = "https://analyticsadmin.googleapis.com/v1beta"
# (パラメータ名, 表示名)。lead_route は funnel.py の送信の内訳に要る
DIMS = [
    ("last_field", "最後に触った項目"),
    ("form_type", "フォームの種類"),
    ("cta_id", "ボタンのID"),
    ("page_path", "出来事のページ（記事のパス）"),
    ("tool", "ツール"),
    ("lead_route", "送信の経路"),
]


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--site")
    a = ap.parse_args()
    conf = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "sites").glob("*.json"))}
    targets = [(k, c["ga4_property_id"]) for k, c in conf.items()
               if c.get("ga4_property_id") and (not a.site or k == a.site)]
    if not targets:
        print("対象のプロパティがありません")
        return 1
    s = session()
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
