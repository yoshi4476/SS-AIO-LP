# -*- coding: utf-8 -*-
"""Googleビジネスプロフィール（Googleマップの店舗情報）を、サイト設定から揃える（訪日客向け）。

**なぜ要るか**: 訪日客の入口はほぼ Google マップ。店の属性（英語メニューあり・カード可・
Wi-Fi・ベジタリアン対応など）と説明文が、地図での表示と絞り込みに使われる。
人が管理画面で直すと抜け漏れが出るので、sites/<id>.json の gbp に書いたとおりに揃える。

**先に知っておくこと（Googleの仕様）**:
  - 説明文は1言語しか持てない。訪日客の画面では Google が自動翻訳して見せる。
    多言語の説明文を別々に持つ仕組みは無い（だから説明文は日本語で正確に書く）
  - 使える属性は業種（カテゴリ）ごとに違う。--attrs で、その店で使える属性の一覧を出してから設定する

鍵（クライアントごとに1回だけ・先方の Google アカウントで許可する）:
  1. gbp-client.json（当社の OAuth クライアント・デスクトップ型）をこのフォルダに置く
  2. python scripts/gbp.py --auth --site <id>   → gbp-token-<id>.json（コミットされない）

  python scripts/gbp.py --check --site <id>     # つながるか・店舗の一覧
  python scripts/gbp.py --attrs --site <id>     # その店で設定できる属性の一覧
  python scripts/gbp.py --sync  --site <id>     # sites/<id>.json の gbp に揃える（差分があるものだけ）
設定例（sites/<id>.json）:
  "gbp": {"location": "locations/1234567890", "account": "accounts/111",
          "description": "…（日本語・750字まで）", "attributes": {"attributes/pay_credit_card_types_accepted": ["visa"]}}
出す印: GBP_OK=yes/no/unset
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
CLIENT = ROOT / "gbp-client.json"
SCOPES = ["https://www.googleapis.com/auth/business.manage"]
INFO = "https://mybusinessbusinessinformation.googleapis.com/v1"
ACCT = "https://mybusinessaccountmanagement.googleapis.com/v1"
V4 = "https://mybusiness.googleapis.com/v4"


def token_path(site):
    return ROOT / f"gbp-token-{site}.json"


def creds(site):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    p = token_path(site)
    if not p.is_file():
        return None
    c = Credentials.from_authorized_user_file(str(p), SCOPES)
    if not c.valid and c.refresh_token:
        c.refresh(Request())
        p.write_text(c.to_json(), encoding="utf-8")
    return c


def auth(site):
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not CLIENT.is_file():
        raise SystemExit("gbp-client.json がありません（Google Cloud の OAuth クライアント・デスクトップ型）")
    c = InstalledAppFlow.from_client_secrets_file(str(CLIENT), SCOPES).run_local_server(port=0)
    token_path(site).write_text(c.to_json(), encoding="utf-8")
    print(f"  {token_path(site).name} を作りました（コミットされません）")


def call(c, method, url, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Bearer {c.token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        t = r.read().decode("utf-8")
        return json.loads(t) if t else {}


def reviews(site, page_size=50):
    """口コミの一覧（v4）。[{name, reviewer, rating, comment, reply, time}]"""
    import sites as S
    c = creds(site)
    g = S.load(site).get("gbp") or {}
    if not c or not g.get("account") or not g.get("location"):
        return None
    loc = g["location"].split("/")[-1]
    d = call(c, "GET", f"{V4}/{g['account']}/locations/{loc}/reviews?pageSize={page_size}")
    out = []
    for r in d.get("reviews", []):
        out.append({"name": r.get("name", ""), "reviewer": (r.get("reviewer") or {}).get("displayName", ""),
                    "rating": r.get("starRating", ""), "comment": r.get("comment", ""),
                    "reply": (r.get("reviewReply") or {}).get("comment", ""), "time": r.get("createTime", "")})
    return out


def reply(site, review_name, text):
    c = creds(site)
    if not c:
        raise SystemExit("鍵がありません（--auth）")
    return call(c, "PUT", f"{V4}/{review_name}/reply", {"comment": text})


def main():
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--auth", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--attrs", action="store_true")
    ap.add_argument("--sync", action="store_true")
    a = ap.parse_args()
    if a.auth:
        auth(a.site)
        return 0
    c = creds(a.site)
    g = S.load(a.site).get("gbp") or {}
    if not c:
        print(f"  {token_path(a.site).name} がありません（先方の Google アカウントで --auth を1回）")
        print("GBP_OK=unset")
        return 0
    if a.check:
        accts = call(c, "GET", f"{ACCT}/accounts").get("accounts", [])
        for ac in accts:
            locs = call(c, "GET", f"{INFO}/{ac['name']}/locations?readMask=name,title,storefrontAddress&pageSize=100").get("locations", [])
            print(f"  {ac['name']} {ac.get('accountName', '')}: 店舗 {len(locs)}")
            for l in locs:
                print(f"     {l['name']}  {l.get('title', '')}")
        print("GBP_OK=yes")
        return 0
    if not g.get("location"):
        print("  sites/<id>.json に gbp.location がありません（--check で店舗の名前を確かめて書く）")
        print("GBP_OK=unset")
        return 0
    if a.attrs:
        q = urllib.parse.urlencode({"parent": g["location"], "languageCode": "ja", "pageSize": 200})
        for m in call(c, "GET", f"{INFO}/attributes?{q}").get("attributeMetadata", []):
            print(f"  {m.get('parent', m.get('attributeId', ''))}  {m.get('displayName', '')}  {m.get('valueType', '')}")
        print("GBP_OK=yes")
        return 0
    if a.sync:
        changed = []
        cur = call(c, "GET", f"{INFO}/{g['location']}?readMask=profile")
        want = (g.get("description") or "").strip()
        if want and (cur.get("profile") or {}).get("description", "").strip() != want:
            if len(want) > 750:
                raise SystemExit("説明文は750字まで（Googleの上限）")
            call(c, "PATCH", f"{INFO}/{g['location']}?updateMask=profile.description", {"profile": {"description": want}})
            changed.append("説明文")
        attrs = g.get("attributes") or {}
        if attrs:
            now = {x["name"]: x.get("values") for x in call(c, "GET", f"{INFO}/{g['location']}/attributes").get("attributes", [])}
            diff = {k: v for k, v in attrs.items() if now.get(k) != (v if isinstance(v, list) else [v])}
            if diff:
                body = {"name": f"{g['location']}/attributes",
                        "attributes": [{"name": k, "values": v if isinstance(v, list) else [v]} for k, v in diff.items()]}
                call(c, "PATCH", f"{INFO}/{g['location']}/attributes?attributeMask=" + ",".join(diff), body)
                changed.append(f"属性{len(diff)}件")
        print(f"  {'更新: ' + '・'.join(changed) if changed else '差分なし'}")
        print("GBP_OK=yes")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
