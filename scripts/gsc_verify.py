# -*- coding: utf-8 -*-
"""お客様の社の Search Console の所有権を、当社のサービスアカウントが自分で確かめる（2026-11-18）

以前は「先方がサービスアカウントをオーナーに足す」のを待つしかなく、足されるまで
食い合いの検査（kw_guard）が Search Console を読めず、Indexing API でも知らせられなかった。
配信先の直下へはファイルを置ける（IndexNow の鍵・Bing の確認ファイルと同じ）ので、
Google の確認ファイル（google<英数>.html）を配信と一緒に置き、本番に出たら
Site Verification API で所有権を確かめ、Search Console にプロパティ（https://<ドメイン>/）を足す。

  token(domain)   置く確認ファイルの {名前: 中身}。search_connect.files_for が配信のたびに足す
                  （Google は後からも確かめ直すので、確認の後も置いたままにする）
  connect(cfg)    本番に出ていれば確かめる。state: verified / waiting（まだ出ていない）/
                  disabled（当社の Google Cloud で API が無効）/ manual（WordPress は直下に置けない）/ error

WordPress は投稿者の権限の鍵だけで直下にファイルを置けないので、今までどおり先方にお願いする。
"""
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

SCOPE_VERIFY = "https://www.googleapis.com/auth/siteverification"
SCOPE_GSC = "https://www.googleapis.com/auth/webmasters"
ENABLE_URL = "https://console.developers.google.com/apis/api/siteverification.googleapis.com/overview"


def _site(domain):
    return {"type": "SITE", "identifier": f"https://{domain.lower()}/"}


def _build(api, version, scope):
    import gcreds
    import notify_indexing as NX
    from googleapiclient.discovery import build
    return build(api, version, credentials=gcreds.load(NX.SA_PATH, [scope]), cache_discovery=False)


def _disabled(e):
    s = str(getattr(e, "content", b"") or e)
    return "has not been used" in s or "is disabled" in s or "SERVICE_DISABLED" in s


def token(domain, sv=None):
    """確認ファイルの名前（google<英数>.html）。取れなければ None（鍵が無い・API が無効・通信の失敗）"""
    import notify_indexing as NX
    if sv is None and not NX.SA_PATH.is_file():
        return None
    try:
        sv = sv or _build("siteVerification", "v1", SCOPE_VERIFY)
        return sv.webResource().getToken(body={"site": _site(domain), "verificationMethod": "FILE"}).execute()["token"]
    except Exception as e:
        print(f"  Search Console の確認ファイルを取れません（{'API が無効' if _disabled(e) else str(e)[:80]}）")
        return None


def file_body(name):
    return f"google-site-verification: {name}"


def files_for(domain):
    name = token(domain)
    return {name: file_body(name)} if name else {}


def live(domain, name):
    try:
        req = urllib.request.Request(f"https://{domain}/{name}", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", "ignore")
    except Exception:
        return ""


def connect(cfg, sv=None, sc=None, fetch=None):
    """本番に確認ファイルが出ていれば所有権を確かめ、Search Console にプロパティを足す"""
    dom = cfg["domain"].lower()
    r = {"site": cfg["id"], "domain": dom, "state": "verified", "msg": ""}
    if cfg.get("type") == "wordpress":
        r["state"] = "manual"
        return r
    fetch = fetch or live
    try:
        sv = sv or _build("siteVerification", "v1", SCOPE_VERIFY)
        name = sv.webResource().getToken(body={"site": _site(dom), "verificationMethod": "FILE"}).execute()["token"]
        if file_body(name) not in fetch(dom, name):
            r["state"], r["msg"] = "waiting", f"https://{dom}/{name}"
            return r
        sv.webResource().insert(verificationMethod="FILE", body={"site": _site(dom)}).execute()
        sc = sc or _build("searchconsole", "v1", SCOPE_GSC)
        sc.sites().add(siteUrl=f"https://{dom}/").execute()
    except Exception as e:
        r["state"] = "disabled" if _disabled(e) else "error"
        r["msg"] = str(getattr(e, "content", b"") or e)[:160]
    return r


def todo(cfg, r, who, weekly=False):
    """connect の結果から出す行。配信の直後の待ち（waiting）は確認中、人が動くものは要対応。
    週次の点検（weekly）で まだ出ていないのは、配信と一緒に置けていない＝人が見る"""
    name = cfg.get("name", cfg["id"])
    if r["state"] == "waiting" and not weekly:
        return (f"確認中: {name} の Search Console の確認ファイル（{r['msg']}）が本番に出るのを待っています"
                "（記事の配信と一緒に置きます。出たらサービスアカウントが自分でオーナーになります）")
    if r["state"] == "waiting":
        return (f"要対応: {name} の Search Console の確認ファイル（{r['msg']}）が本番に出ていません"
                "（配信先の公開フォルダの直下に置かれているか確かめてください）")
    if r["state"] == "disabled":
        return (f"要対応: 当社の Google Cloud で Site Verification API が無効のため、{name} の Search Console の"
                f"所有権を自動で確かめられません。{ENABLE_URL} で「有効にする」を押してください（無料）")
    if r["state"] == "error":
        return (f"要対応: {name} の Search Console の所有権を自動で確かめられませんでした（{r['msg'][:100]}）。"
                f"続くときは、先方にサービスアカウント（{who}）をオーナーで追加してもらってください")
    return (f"要対応: {name}（{cfg['domain']}）の Search Console に"
            f"サービスアカウント（{who}）をオーナーで追加してください（WordPress は確認ファイルを直下に置けません）")
