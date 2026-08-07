# -*- coding: utf-8 -*-
"""公開した記事をSNSへ配る（X / Facebook / Instagram / Threads / LinkedIn / LINE公式）

使い方:
    python scripts/post_social.py <site_id> <slug>        # 設定済みの媒体へ配信
    python scripts/post_social.py --today                 # 本日公開分をまとめて
    python scripts/post_social.py <site_id> <slug> --dry  # 投稿文と画像だけ確認

3サイトの記事を1つのアカウントから配る前提。サイトごとにアカウントを分ける場合は
環境変数の末尾にサイトIDを付ける（X_ACCESS_TOKEN_CORPORATE など）。

画像は記事のアイキャッチを使う。Instagram と Threads は画像が必須のため、
アイキャッチが無い記事は投稿しない（本文だけ流しても読まれないため）。

note は公開APIが無く、自動投稿の手段が用意されていない。規約上も自動化は
想定されていないため対象外とする（手動で転載するか、RSSを案内する）。
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sites as sites_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
X_LIMIT = 280
GRAPH = "https://graph.facebook.com/v21.0"


def env():
    d = {}
    p = ROOT / ".env"
    if p.is_file():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                d[k.strip()] = v.strip()
    return d


def is_set(v):
    """未設定と雛形（YOUR_...）を同じ扱いにする"""
    return bool(v) and not v.upper().startswith("YOUR_")


def pick(e, name, site_id):
    """サイト別の値を優先し、無ければ共通の値を使う（1アカウント運用でもそのまま動く）"""
    suf = site_id.upper().replace("-", "_")
    return e.get(f"{name}_{suf}") or e.get(name, "")


def compose(meta, url, cfg, limit=None, with_url=True):
    """投稿文を作る。タイトルの再掲だけでは読む理由にならないので要点を添える"""
    title = meta["title"]
    lead = re.sub(r"\s+", "", str(meta.get("description", "")))[:70]
    tags = " ".join(f"#{t}" for t in (cfg.get("x_tags") or [])[:2])

    def build(l):
        b = f"{title}\n\n{l}…"
        if with_url:
            b += f"\n\n{url}"
        if tags:
            b += f"\n{tags}"
        return b

    body = build(lead)
    if limit:
        # Xでは実際の長さに関わらずURLは23字で数えられる
        def length(b):
            return len(b) - (len(url) - 23 if with_url and url in b else 0)
        while length(body) > limit and len(lead) > 12:
            lead = lead[:-5]
            body = build(lead)
    return body


def image_url(meta, cfg):
    """記事のアイキャッチの公開URL（無ければ空）

    配信先によって画像の置き場が違う（コーポレートは /images/blog/…）。
    原稿は自リポジトリの慣習で書かれているため、publish.py と同じ変換をかける。
    かけないとSNSに404の画像URLを渡すことになる。
    """
    e = str(meta.get("eyecatch") or "")
    if not e:
        return ""
    if e.startswith("/") and cfg.get("images_dir"):
        import publish
        prefix = publish.image_prefix(cfg)
        e = e.replace(f"/images/{meta['slug']}/", f"{prefix}/{meta['slug']}/", 1)
    return f"https://{cfg['domain']}{e}" if e.startswith("/") else e


# ---------------- X ----------------

def x_post(text, c):
    api = "https://api.twitter.com/2/tweets"
    oauth = {"oauth_consumer_key": c["api_key"], "oauth_nonce": secrets.token_hex(16),
             "oauth_signature_method": "HMAC-SHA1", "oauth_timestamp": str(int(time.time())),
             "oauth_token": c["access_token"], "oauth_version": "1.0"}
    joined = "&".join(f"{urllib.parse.quote(k, '')}={urllib.parse.quote(str(v), '')}"
                      for k, v in sorted(oauth.items()))
    base = "&".join(["POST", urllib.parse.quote(api, ""), urllib.parse.quote(joined, "")])
    key = f"{urllib.parse.quote(c['api_secret'], '')}&{urllib.parse.quote(c['access_secret'], '')}"
    oauth["oauth_signature"] = base64.b64encode(
        hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    auth = "OAuth " + ", ".join(f'{urllib.parse.quote(k, "")}="{urllib.parse.quote(str(v), "")}"'
                                for k, v in sorted(oauth.items()))
    req = urllib.request.Request(api, data=json.dumps({"text": text}).encode("utf-8"),
                                 method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", auth)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------------- Facebook ページ ----------------

def fb_post(text, url, page_id, token):
    """linkを渡すとFacebook側がOGP画像を展開する（画像の再送は不要）"""
    api = f"{GRAPH}/{page_id}/feed"
    data = urllib.parse.urlencode({"message": text, "link": url, "access_token": token}).encode()
    with urllib.request.urlopen(urllib.request.Request(api, data=data), timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------------- Instagram / Threads ----------------

def ig_post(caption, img, ig_id, token):
    """Instagramは2段階。コンテナを作ってから公開する"""
    d = urllib.parse.urlencode({"image_url": img, "caption": caption,
                                "access_token": token}).encode()
    with urllib.request.urlopen(
            urllib.request.Request(f"{GRAPH}/{ig_id}/media", data=d), timeout=60) as r:
        cid = json.loads(r.read().decode("utf-8"))["id"]
    d2 = urllib.parse.urlencode({"creation_id": cid, "access_token": token}).encode()
    with urllib.request.urlopen(
            urllib.request.Request(f"{GRAPH}/{ig_id}/media_publish", data=d2), timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def threads_post(text, img, user_id, token):
    base = f"https://graph.threads.net/v1.0/{user_id}"
    params = {"media_type": "IMAGE" if img else "TEXT", "text": text, "access_token": token}
    if img:
        params["image_url"] = img
    with urllib.request.urlopen(
            urllib.request.Request(f"{base}/threads",
                                   data=urllib.parse.urlencode(params).encode()), timeout=60) as r:
        cid = json.loads(r.read().decode("utf-8"))["id"]
    d2 = urllib.parse.urlencode({"creation_id": cid, "access_token": token}).encode()
    with urllib.request.urlopen(
            urllib.request.Request(f"{base}/threads_publish", data=d2), timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------------- LinkedIn 会社ページ ----------------

def li_post(text, url, img, org_id, token):
    """会社ページへ投稿する。

    LinkedInはリンク付き投稿にすると相手側がOGPを展開するため、画像の再送は要らない。
    投稿主体は organizationalEntityUrn（会社ページ）で指定する。
    """
    api = "https://api.linkedin.com/rest/posts"
    body = {
        "author": f"urn:li:organization:{org_id}",
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED",
                         "targetEntities": [], "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if url:
        body["content"] = {"article": {"source": url,
                                       "title": text.splitlines()[0][:200]}}
        if img:
            body["content"]["article"]["thumbnail"] = img
    req = urllib.request.Request(api, data=json.dumps(body).encode("utf-8"), method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("LinkedIn-Version", "202405")
    req.add_header("X-Restli-Protocol-Version", "2.0.0")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.headers.get("x-restli-id") or r.status


# ---------------- LINE 公式アカウント ----------------

def line_broadcast(text, img, token):
    msgs = [{"type": "text", "text": text}]
    if img:
        msgs.insert(0, {"type": "image", "originalContentUrl": img, "previewImageUrl": img})
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/broadcast",
        data=json.dumps({"messages": msgs}).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


# ---------------- 本体 ----------------

def article(slug):
    p = ROOT / "articles" / f"{slug}.md"
    if not p.exists():
        raise SystemExit(f"記事が見つかりません: {slug}")
    m = re.match(r"^---\s*\n(.*?)\n---", p.read_text(encoding="utf-8-sig"), re.S)
    return yaml.safe_load(m.group(1))


def deliver(site_id, slug, e, dry):
    cfg = sites_mod.load(site_id)
    meta = article(slug)
    url = sites_mod.article_url(cfg, meta)
    img = image_url(meta, cfg)
    xtext = compose(meta, url, cfg, limit=X_LIMIT)
    notext = compose(meta, url, cfg, with_url=False)   # 本文にURLを置けない媒体用

    print(f"\n■ {site_id} / {slug}")
    print(f"  画像: {img or '（アイキャッチ未設定）'}")

    if dry:
        print("\n― X / LINE ―")
        print(xtext)
        print("\n― Instagram / Threads（本文にURLを置けないためプロフィール誘導）―")
        print(notext)
        return

    # X
    c = {k: pick(e, f"X_{k.upper()}", site_id) for k in
         ("api_key", "api_secret", "access_token", "access_secret")}
    if all(is_set(v) for v in c.values()):
        try:
            r = x_post(xtext, c)
            print(f"  X: 投稿 https://x.com/i/status/{(r.get('data') or {}).get('id')}")
        except Exception as ex:
            print(f"  X: 失敗 {str(ex)[:110]}")
    else:
        print("  X: スキップ（X_API_KEY / X_API_SECRET / X_ACCESS_TOKEN / X_ACCESS_SECRET）")

    # Facebook ページ
    fbt, fbp = pick(e, "FB_PAGE_TOKEN", site_id), pick(e, "FB_PAGE_ID", site_id)
    if is_set(fbt) and is_set(fbp):
        try:
            fb_post(notext, url, fbp, fbt)
            print("  Facebook: 投稿")
        except Exception as ex:
            print(f"  Facebook: 失敗 {str(ex)[:110]}")
    else:
        print("  Facebook: スキップ（FB_PAGE_TOKEN / FB_PAGE_ID）")

    # Instagram（画像必須）
    igi = pick(e, "IG_USER_ID", site_id)
    if is_set(fbt) and is_set(igi) and img:
        try:
            ig_post(notext, img, igi, fbt)
            print("  Instagram: 投稿")
        except Exception as ex:
            print(f"  Instagram: 失敗 {str(ex)[:110]}")
    else:
        print("  Instagram: スキップ（IG_USER_ID / FB_PAGE_TOKEN / アイキャッチ）")

    # Threads
    tht, thu = pick(e, "THREADS_TOKEN", site_id), pick(e, "THREADS_USER_ID", site_id)
    if is_set(tht) and is_set(thu):
        try:
            threads_post(xtext, img, thu, tht)
            print("  Threads: 投稿")
        except Exception as ex:
            print(f"  Threads: 失敗 {str(ex)[:110]}")
    else:
        print("  Threads: スキップ（THREADS_TOKEN / THREADS_USER_ID）")

    # LinkedIn 会社ページ
    lit, lio = pick(e, "LINKEDIN_TOKEN", site_id), pick(e, "LINKEDIN_ORG_ID", site_id)
    if is_set(lit) and is_set(lio):
        try:
            pid = li_post(notext, url, img, lio, lit)
            print(f"  LinkedIn: 投稿 {pid}")
        except Exception as ex:
            print(f"  LinkedIn: 失敗 {str(ex)[:110]}")
    else:
        print("  LinkedIn: スキップ（LINKEDIN_TOKEN / LINKEDIN_ORG_ID）")

    # LINE公式
    lt = pick(e, "LINE_CHANNEL_TOKEN", site_id)
    if is_set(lt):
        try:
            line_broadcast(xtext, img, lt)
            print("  LINE: 配信")
        except Exception as ex:
            print(f"  LINE: 失敗 {str(ex)[:110]}")
    else:
        print("  LINE: スキップ（LINE_CHANNEL_TOKEN）")


def main():
    e = env()
    dry = "--dry" in sys.argv
    targets = []
    if "--today" in sys.argv:
        today = date.today().isoformat()
        for p in (ROOT / "articles").glob("*.md"):
            m = re.match(r"^---\s*\n(.*?)\n---", p.read_text(encoding="utf-8-sig"), re.S)
            meta = yaml.safe_load(m.group(1)) if m else {}
            if str(meta.get("date", "")) == today:
                owner = sites_mod.find_category_owner(meta.get("category", ""))
                if owner:
                    targets.append((owner, p.stem))
    elif len(sys.argv) >= 3 and not sys.argv[1].startswith("--"):
        targets = [(sys.argv[1], sys.argv[2])]
    else:
        raise SystemExit(__doc__)

    if not targets:
        print("本日公開の記事がありません")
        return
    for site_id, slug in targets:
        deliver(site_id, slug, e, dry)


if __name__ == "__main__":
    main()
