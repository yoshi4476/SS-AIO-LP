# -*- coding: utf-8 -*-
"""ニュースレター（Resend の一斉配信）を送る前に、管制塔の「配信除外」に入っている人を購読者から外す。

補助金サイトの /unsubscribe/ で配信停止した人は、管制塔の「配信除外」に入るだけで、
AI集客ラボのニュースレター（Resend の購読者）には残っていた。差出人は同じセブンセンシズ株式会社なので、
「止めたのに別の名前で届く」ことになる（2026-10-08）。そこで送る直前に購読者を管制塔に照らし、
当たった人を Resend 側で配信停止（unsubscribed）にする。Resend の一斉配信は、配信停止の人には送らない。

照らし合わせ（メールアドレス・会社のドメイン）は管制塔の excluded_ と同じ判定を GAS 側で行う（ここで真似しない）。
管制塔に照らせなかったら送らない（停止した人に届くよりは、1回休んで知らせるほうがよい）。

    python scripts/newsletter_exclude.py --dry   # 購読者のうち配信除外に当たる人を数えるだけ（Resend は変えない）
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
API = "https://api.resend.com"
UA = "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"   # Cloudflare が既定の UA を遮断する（error 1010）
PAGE = 100


class NotChecked(RuntimeError):
    """配信除外と照らせなかった（このときは送らない）"""


def _req(key, method, path, body=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                          "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def subscribers(key, call=_req):
    """配信停止になっていない購読者のメールアドレス（id つき）。100件ずつたどる"""
    out, after = [], ""
    for _ in range(200):                                   # 2万人で打ち切る（無限に回らない）
        q = {"limit": PAGE}
        if after:
            q["after"] = after
        r = call(key, "GET", "/contacts?" + urllib.parse.urlencode(q))
        rows = r.get("data") or []
        out += [{"id": c.get("id", ""), "email": str(c.get("email") or "").strip().lower()}
                for c in rows if c.get("email") and not c.get("unsubscribed")]
        if not r.get("has_more") or not rows:
            break
        after = rows[-1].get("id", "")
    return out


def excluded(emails, post=None):
    """管制塔に照らして、配信除外に当たるメールアドレスの集合。照らせなければ NotChecked"""
    if not emails:
        return set()
    if post is None:
        import hub_client as HC
        if not HC.enabled():
            raise NotChecked("HUB_URL が無いので、管制塔の配信除外と照らせません")
        post = HC._post
    try:
        r = post({"action": "newsletter_excluded", "emails": sorted(emails)}) or {}
    except Exception as e:                                 # 通信の失敗も「照らせなかった」
        raise NotChecked(f"管制塔に照らせませんでした（{type(e).__name__}: {str(e)[:120]}）")
    # 管制塔の GAS が古いと、この action を知らずにフォームの受付に流れて ok:false が返る
    if not r.get("ok") or not isinstance(r.get("excluded"), list):
        raise NotChecked(f"管制塔が配信除外を返しませんでした（{str(r)[:160]}）。contact.hub.gs を配り直してください")
    return {str(x).strip().lower() for x in r["excluded"]}


def apply(key, call=_req, post=None):
    """配信除外に当たる購読者を Resend で配信停止にする。外した人数を返す。照らせなければ NotChecked"""
    subs = subscribers(key, call)
    hit = excluded({s["email"] for s in subs}, post)
    n = 0
    for s in subs:
        if s["email"] in hit:
            call(key, "PATCH", "/contacts/" + urllib.parse.quote(s["id"] or s["email"], safe="@"), {"unsubscribed": True})
            n += 1
    print(f"NEWSLETTER_EXCLUDE=購読者{len(subs)}人のうち配信除外{n}人を配信停止にしました")
    return n


def main():
    key = os.environ.get("RESEND_API_KEY", "")
    if not key:
        print("RESEND_API_KEY がありません")
        return 1
    if "--dry" in sys.argv:
        subs = subscribers(key)
        hit = excluded({s["email"] for s in subs})
        print(f"購読者{len(subs)}人のうち配信除外に当たる人: {len(hit)}人（Resend は変えていません）")
        return 0
    apply(key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
