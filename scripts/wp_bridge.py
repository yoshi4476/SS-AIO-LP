# -*- coding: utf-8 -*-
"""WordPress の社を、最初の接続のあとは人の手なしで回すための橋渡し（管制塔の側）。

先方に置くのは automation/wordpress/ss-quality-gate.php の1つだけ。品質ゲートに加えて、
ss/v1 の REST を持つ（書き込みは編集者以上かつアプリケーションパスワードでの認証だけ）:

  GET  /ss/v1/urls       公開URLの一覧（パーマリンク）。認証なし
  GET  /ss/v1/status     版・自己更新の状態・設定の有無
  POST /ss/v1/redirects  統合した記事の301（同じサイトのパスだけ）
  POST /ss/v1/settings   llms.txt・IndexNow の鍵・GA4 の測定ID・スマホの固定ボタン
  POST /ss/v1/update     自己更新を今すぐ試す（ふだんは日に1回、先方の WordPress が自分で見る）

**なぜ要るか**: WordPress は記事のURLをパーマリンク設定が決め、sitemap は索引形式（/wp-sitemap.xml）で、
_redirects も llms.txt も置けない。静的サイト向けの道具（sitemap を平らな一覧として読む・URL を
接頭辞で組み立てる・配信先に _redirects を書く）は、どれも WordPress では0件か404になっていた。

  python scripts/wp_bridge.py --site <id> --sync     # llms.txt・鍵・GA4 と、業種ハブ・用語集の固定ページを揃える
  python scripts/wp_bridge.py --check                # WordPress の社の版と自己更新の状態（WPBRIDGE_OK=）
  python scripts/wp_bridge.py --sign                 # プラグインに署名して案内（ss-bridge.json）を作る
  python scripts/wp_bridge.py --keygen               # 署名の鍵を作る（最初の1回だけ・鍵の中身は出力しない）
"""
import argparse
import base64
import hashlib
import html as H
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
PLUGIN = ROOT / "automation" / "wordpress" / "ss-quality-gate.php"
MANIFEST = ROOT / "automation" / "wordpress" / "ss-bridge.json"
# 先方のプラグインが日に1回見に来る場所（AI集客ラボの公開フォルダ /wp/）
RELEASE_BASE = "https://ai.7senses.co.jp/wp/"
UA = {"User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"}
HUB_PARENT = ("industry", "業種から探す")
GLOSSARY = ("glossary", "用語集")


def is_wp(cfg):
    return (cfg or {}).get("type") == "wordpress"


def _has_auth(cfg):
    try:
        import publish
        publish._wp_auth(cfg)
        return True
    except SystemExit:
        return False


def call(cfg, path, data=None, method=None):
    """橋渡しの REST（認証つき）。publish._wp_call を通す（試験は _wp_call を差し替えて偽の WordPress にする）"""
    import publish
    return publish._wp_call(cfg, "/ss/v1/" + path.lstrip("/"), data, method)


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


# ---------- 公開URL ----------

def sitemap_entries(domain, max_children=60):
    """本番の sitemap の (URL, lastmod)。索引形式（WordPress の /wp-sitemap.xml・Yoast の sitemap_index.xml）なら子を辿る。
    平らな sitemap では従来どおり（<url> を読むだけ）"""
    xml = _get(f"https://{domain}/sitemap.xml")
    if "<sitemapindex" in xml:
        out = []
        for loc in re.findall(r"<sitemap>\s*<loc>\s*(.*?)\s*</loc>", xml, re.S)[:max_children]:
            try:
                out += _entries(_get(H.unescape(loc)))
            except Exception as e:
                print(f"  {domain}: 子の sitemap を読めません（{H.unescape(loc)[:60]}・{type(e).__name__}）")
        return out
    return _entries(xml)


def _entries(xml):
    out = []
    for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
        loc = re.search(r"<loc>\s*(.*?)\s*</loc>", block, re.S)
        mod = re.search(r"<lastmod>\s*(.*?)\s*</lastmod>", block, re.S)
        if loc:
            out.append((H.unescape(loc.group(1)), mod.group(1)[:10] if mod else ""))
    return out


def url_rows(cfg, fallback=True):
    """WordPress の公開URL（[{url, slug, type, modified, managed}]）。

    橋渡しの /urls を読む（パーマリンクそのもの）。認証があれば publish._wp_call 経由、
    無ければ認証なしで読む（公開済みの一覧なので鍵は要らない）。fallback=False なら橋渡しだけを見る
    """
    rows = None
    if _has_auth(cfg) or not fallback:
        try:
            page, rows = 1, []
            while page <= 20:
                got = call(cfg, f"urls?page={page}")
                if not (isinstance(got, dict) and isinstance(got.get("urls"), list)):
                    rows = None if page == 1 else rows
                    break
                rows += got["urls"]
                if page >= int(got.get("pages") or 1):
                    break
                page += 1
        except SystemExit:
            rows = None
    if rows is None and fallback:
        try:
            import publish
            root = publish._wp_root(cfg)
            rows, page = [], 1
            while page <= 20:
                got = json.loads(_get(f"{root}/ss/v1/urls?page={page}"))
                rows += got.get("urls") or []
                if page >= int(got.get("pages") or 1):
                    break
                page += 1
        except Exception:
            rows = None
    if rows is None and fallback:
        # 橋渡しの無い古い版でも、sitemap 索引から公開URLは取れる（slug は URL の最後の区切りから）
        try:
            rows = [{"url": u, "slug": urllib.parse.urlsplit(u).path.rstrip("/").rsplit("/", 1)[-1],
                     "type": "post", "modified": m, "managed": False} for u, m in sitemap_entries(cfg["domain"])]
        except Exception as e:
            print(f"  {cfg['id']}: 公開URLを取得できません（{type(e).__name__}）")
            rows = []
    return rows or []


def site_urls(cfg):
    """通知・巡回に使う公開URLの一覧。WordPress は橋渡し、ほかは sitemap（索引形式なら子まで辿る）"""
    if is_wp(cfg):
        return [r["url"] for r in url_rows(cfg)]
    return [u for u, _ in sitemap_entries(cfg["domain"])]


def url_map(cfg, rows=None):
    """記事の slug → 公開URL（投稿だけ。固定ページと slug が重なっても記事を指す）"""
    rows = url_rows(cfg) if rows is None else rows
    return {r["slug"]: r["url"] for r in rows if r.get("type") == "post" and r.get("slug")}


def post_link(cfg, slug):
    """公開済みの記事のパーマリンク（WordPress の REST から。無ければ空）"""
    import publish
    try:
        found = publish._wp_call(cfg, f"posts?slug={slug}&status=publish&per_page=1&_fields=link")
    except SystemExit:
        found = None
    if isinstance(found, list) and found and found[0].get("link"):
        return found[0]["link"]
    return url_map(cfg).get(slug, "")


def article_url(cfg, meta):
    """記事の公開URL。WordPress はパーマリンク設定が決めるので、組み立てずに先方へ聞く"""
    import sites as S
    if is_wp(cfg):
        return post_link(cfg, meta["slug"]) or S.article_url(cfg, meta)
    return S.article_url(cfg, meta)


def rewrite_links(html, rows, skip=("/industry/", "/glossary/")):
    """本文の内部リンク（/<カテゴリ>/<slug>/ や /blog/<slug>/）を、WordPress の実際のパーマリンクへ置き換える。
    原稿は静的サイトの組み方で書かれており、そのままでは /%postname%/ の社で404になる"""
    by_slug = url_map(None, rows)

    def repl(m):
        path, slug, frag = m.group(1), m.group(2), m.group(3) or ""
        if slug not in by_slug or any(path.startswith(s) for s in skip):
            return m.group(0)
        return f'href="{by_slug[slug]}{frag}"'
    return re.sub(r'href="(/(?:[A-Za-z0-9_-]+/)*?([A-Za-z0-9_-]+)/)(#[^"]*)?"', repl, html)


# ---------- 転送・設定 ----------

def to_path(cfg, url):
    """同じサイトのURL・パスを、転送表に入れるパスにする（別ドメインは None）"""
    p = urllib.parse.urlsplit(url)
    if p.netloc and p.netloc.lower() not in (cfg["domain"].lower(), "www." + cfg["domain"].lower()):
        return None
    path = p.path or "/"
    if not path.startswith("/") or path.startswith("//"):
        return None
    return urllib.parse.quote(path, safe="/%-._~!$&'()*+,;=:@")


def add_redirects(cfg, pairs):
    """[(旧URL, 新URL)] を先方の転送表へ足す。戻り値は (足した数, 先方が受け付けなかった行)"""
    rows = []
    for a, b in pairs:
        pa, pb = to_path(cfg, a), to_path(cfg, b)
        if pa and pb and pa.rstrip("/") != pb.rstrip("/"):
            rows.append({"from": pa, "to": pb})
    if not rows:
        return 0, []
    res = call(cfg, "redirects", {"add": rows}, "POST")
    rej = res.get("rejected") or [] if isinstance(res, dict) else []
    return len(rows) - len(rej), rej


def _site_articles(cfg):
    """その社の記事で、公開の基準を満たすもの（[(meta, body, path)]）"""
    import publish
    import sites as S
    out = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        if p.name.startswith("_"):
            continue
        try:
            meta, body = publish.parse_article(p)
        except Exception:
            continue
        if not isinstance(meta, dict) or S.find_category_owner(meta.get("category", "")) != cfg["id"]:
            continue
        if publish.gate_ok(meta):
            out.append((meta, body, p))
    return out


def llms_text(cfg, rows, arts=None):
    """llms.txt の中身。公開済みの記事（橋渡しの一覧にあるもの）と、管制塔が作った固定ページだけを載せる"""
    arts = _site_articles(cfg) if arts is None else arts
    by_slug = url_map(cfg, rows)
    lines = [f"# {cfg.get('name', cfg['domain'])}"]
    about = cfg.get("theme") or cfg.get("audience") or ""
    if about:
        lines.append(f"> {about}")
    items = [f"- [{m['title']}]({by_slug[m['slug']]}): {m.get('description', '')}"
             for m, _, _ in arts if m.get("slug") in by_slug]
    if items:
        lines += ["", "## 記事"] + items
    pages = [r["url"] for r in rows if r.get("managed")]
    if pages:
        lines += ["", "## まとめのページ"] + [f"- {u}" for u in pages]
    return "\n".join(lines) + "\n"


def indexnow_key():
    try:
        import notify_indexnow as NI
        return NI.find_key(NI.load_env())
    except Exception:
        return ""


def ga4_id(cfg):
    v = str(cfg.get("ga4_measurement_id") or "").strip()
    return v if re.fullmatch(r"G-[A-Z0-9]{4,20}", v) else ""


def push_settings(cfg, rows=None):
    """llms.txt・IndexNow の鍵・GA4 の測定ID・スマホの固定ボタンを先方へ送る（何度送っても同じ）"""
    rows = url_rows(cfg) if rows is None else rows
    data = {"llms": llms_text(cfg, rows)}
    key = indexnow_key()
    if key:
        data["indexnow_key"] = key
    if ga4_id(cfg):
        data["ga4"] = ga4_id(cfg)
    # Bing の確認コード（同意のある社だけ）。プラグイン 2.0.1 以降が /BingSiteAuth.xml として返す
    if cfg.get("bing_consent") is True:
        import bing_webmaster
        code = bing_webmaster.auth_code(cfg)
        if code:
            data["bing_auth"] = code
    st = cfg.get("cta_sticky") or {}
    if st.get("url") and st.get("label") and to_path(cfg, st["url"]):
        data["sticky"] = {"url": to_path(cfg, st["url"]), "label": st["label"],
                          "label_b": st.get("label_b", ""), "cta": st.get("cta", "article_sticky")}
    return call(cfg, "settings", data, "POST")


# ---------- 固定ページ（業種ハブ・用語集） ----------

def _split_ld(html):
    """本文の <script type="application/ld+json"> を外し、JSON として読めたものを返す。
    本文に <script> を残すと、unfiltered_html の無い投稿者では WordPress が消す"""
    lds = []

    def take(m):
        try:
            lds.append(json.loads(m.group(1)))
        except ValueError:
            pass
        return ""
    body = re.sub(r'<script type="application/ld\+json">(.*?)</script>', take, html, flags=re.S)
    return body, lds


def upsert_page(cfg, slug, title, html, parent=0):
    """管制塔が持つ固定ページを作る・直す。同じ slug の先方のページ（_ss_managed の無いもの）は触らない。
    戻り値は (ページID, 状態)。状態は created / updated / taken"""
    import publish
    body, lds = _split_ld(html)
    found = publish._wp_call(cfg, f"pages?slug={slug}&parent={parent}&status=publish,draft,private"
                                  f"&context=edit&_fields=id,meta&per_page=1")
    payload = {"title": title, "slug": slug, "parent": parent, "status": "publish", "content": body,
               "meta": {"_ss_managed": "1",
                        "_ss_jsonld": json.dumps(lds[0] if len(lds) == 1 else lds, ensure_ascii=False) if lds else ""}}
    if isinstance(found, list) and found:
        if str((found[0].get("meta") or {}).get("_ss_managed") or "") != "1":
            return found[0]["id"], "taken"
        res = publish._wp_call(cfg, f"pages/{found[0]['id']}", payload, method="POST")
        return res.get("id", found[0]["id"]), "updated"
    res = publish._wp_call(cfg, "pages", payload, method="POST")
    return res.get("id", 0), "created"


def _tile(m, link, cats):
    return (f'<li><a href="{link}">{H.escape(m["title"])}</a> '
            f'<span class="tag">{H.escape(cats.get(m["category"], m["category"]))}</span></li>')


def hub_pages(cfg, arts, rows):
    """業種ハブの (slug, 題名, 本文, 子のFAQ) の一覧。本文は industry_hub と同じ関数で組む（AI集客ラボの LP・調査への案内は外す）"""
    import industry_hub as IH
    by_slug = url_map(cfg, rows)
    metas = [m for m, _, _ in arts if m.get("slug") in by_slug]
    cats = cfg.get("categories") or {}
    inds, mn = IH.load()
    g = IH.group(metas, inds)
    live = [(i, g[i["slug"]]) for i in inds if len(g.get(i["slug"], [])) >= mn]
    cat_links = _category_links(cfg, cats)
    out = []
    for ind, ms in live:
        body = IH.hub_body(ind, ms, {c: (n, "") for c, n in cats.items()},
                           lambda m: _tile(m, by_slug[m["slug"]], cats),
                           cat_url=lambda c: cat_links.get(c, ""), extras=False)
        fq = IH.faq_body(ind, ms, lambda m: by_slug[m["slug"]])
        faq = None
        if fq:
            fhtml, fld = fq
            faq = (f'{ind["name"]}のよくある質問', fhtml + '<script type="application/ld+json">'
                   + json.dumps(fld, ensure_ascii=False) + "</script>")
        out.append((ind["slug"], f'{ind["name"]}の記事', body, faq, len(ms)))
    return out, g


def _category_links(cfg, cats):
    """カテゴリの一覧ページのURL（WordPress のカテゴリのリンク）。取れなければ載せない"""
    import publish
    out = {}
    for c in cats:
        try:
            got = publish._wp_call(cfg, f"categories?slug={c}&_fields=link&per_page=1")
        except SystemExit:
            continue
        if isinstance(got, list) and got and got[0].get("link"):
            out[c] = got[0]["link"]
    return out


def glossary_page(cfg, arts, rows):
    """用語集の本文（記事の定義ブロックを集めたもの。10語未満なら None）"""
    import glossary as GL
    by_slug = url_map(cfg, rows)
    terms = GL.collect(cfg["id"], {m["slug"] for m, _, _ in arts if m["slug"] in by_slug})
    if len(terms) < 10:
        return None
    page = GL.index_html(terms, base=f"/{GLOSSARY[0]}/", site_url=f"https://{cfg['domain']}",
                         rel_all=GL.related_all(terms))
    return rewrite_links(page, rows)


def sync_pages(cfg, rows=None, arts=None):
    """業種ハブ（/industry/ と /industry/<業種>/・/industry/<業種>/faq/）と用語集（/glossary/）を固定ページで揃える。
    要対応（先方の同名ページがある等）の行を返す"""
    import publish
    rows = url_rows(cfg) if rows is None else rows
    arts = _site_articles(cfg) if arts is None else arts
    notes, made = [], []
    hubs, g = hub_pages(cfg, arts, rows)
    if hubs:
        lis = "".join(f'<li><a href="/{HUB_PARENT[0]}/{s}/">{H.escape(t)}</a>（{n}本）</li>' for s, t, _, _, n in hubs)
        idx = (f'<p>業種ごとに、記事をまとめています。</p><ul class="hub-list">{lis}</ul>')
        pid, st = upsert_page(cfg, HUB_PARENT[0], HUB_PARENT[1], idx)
        made.append((HUB_PARENT[0], st))
        if st == "taken":
            notes.append(f"要対応: {cfg['id']} に先方の固定ページ /{HUB_PARENT[0]}/ があるため、業種のまとめを作れません")
        else:
            keep = set()
            for s, t, body, faq, _ in hubs:
                cid, cst = upsert_page(cfg, s, t, body, parent=pid)
                made.append((f"{HUB_PARENT[0]}/{s}", cst))
                keep.add(s)
                if faq and cst != "taken":
                    _, fst = upsert_page(cfg, "faq", faq[0], faq[1], parent=cid)
                    made.append((f"{HUB_PARENT[0]}/{s}/faq", fst))
            # 本数が下限を割った業種のページは下書きに戻す（中身の薄いページを公開し続けない）
            kids = publish._wp_call(cfg, f"pages?parent={pid}&status=publish&context=edit&_fields=id,slug,meta&per_page=100")
            for k in kids if isinstance(kids, list) else []:
                if k.get("slug") not in keep and str((k.get("meta") or {}).get("_ss_managed") or "") == "1":
                    publish._wp_call(cfg, f"pages/{k['id']}", {"status": "draft"}, method="POST")
                    made.append((f"{HUB_PARENT[0]}/{k.get('slug')}", "drafted"))
    gl = glossary_page(cfg, arts, rows)
    if gl:
        _, st = upsert_page(cfg, GLOSSARY[0], GLOSSARY[1], gl)
        made.append((GLOSSARY[0], st))
        if st == "taken":
            notes.append(f"要対応: {cfg['id']} に先方の固定ページ /{GLOSSARY[0]}/ があるため、用語集を作れません")
    for path, st in made:
        print(f"  /{path}/: {st}")
    return notes


def sync_if_stale(cfg, rows, hours=20):
    """記事を公開したついでに、業種のまとめ・用語集を作り直す（1日1回まで）。
    WordPress の社には週次のビルドが無いので、ここで回さないとまとめのページが古いまま残る"""
    from datetime import datetime, timedelta, timezone
    tops = {HUB_PARENT[0], GLOSSARY[0]}
    mods = [r.get("modified") or "" for r in rows
            if r.get("managed") and urllib.parse.urlsplit(r["url"]).path.strip("/") in tops]
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    try:
        if mods and max(datetime.fromisoformat(m) for m in mods) > since:
            return []
    except ValueError:
        pass
    return sync_pages(cfg)


# ---------- 版と自己更新 ----------

def plugin_bytes():
    """配る中身。改行は LF に揃える（Windows の作業コピーで CRLF になっても署名が変わらないように）"""
    return PLUGIN.read_bytes().replace(b"\r\n", b"\n")


def plugin_version(text=None):
    t = text if text is not None else plugin_bytes().decode("utf-8")
    m = re.search(r"^const SSB_VERSION = '(\d+\.\d+\.\d+)';", t, re.M)
    return m.group(1) if m else ""


def _sign_key():
    v = os.environ.get("WP_BRIDGE_SIGN_KEY", "")
    if not v and (ROOT / ".env").is_file():
        for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("WP_BRIDGE_SIGN_KEY="):
                v = line.split("=", 1)[1]
    return v.strip().strip('"').strip("'")


def sign(seed_b64=None, out=MANIFEST):
    """プラグインに Ed25519 で署名し、案内（版・URL・sha256・署名）を書く。鍵の中身は出力しない"""
    from nacl.signing import SigningKey
    seed = base64.b64decode(seed_b64 or _sign_key())
    if len(seed) != 32:
        raise SystemExit("WP_BRIDGE_SIGN_KEY がありません（python scripts/wp_bridge.py --keygen で作る）")
    body = plugin_bytes()
    sk = SigningKey(seed)
    pub = base64.b64encode(bytes(sk.verify_key)).decode()
    if f"define('SSB_PUBKEY', '{pub}')" not in body.decode("utf-8"):
        raise SystemExit("プラグインの SSB_PUBKEY が署名の鍵と合いません（--keygen で書き込んだ鍵で署名すること）")
    man = {"version": plugin_version(body.decode("utf-8")), "url": RELEASE_BASE + "ss-quality-gate.php",
           "sha256": hashlib.sha256(body).hexdigest(), "sig": base64.b64encode(sk.sign(body).signature).decode()}
    out.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return man


def manifest_ok():
    """案内がいまのプラグインに対して作られたものか（直したのに署名し直していないと、先方へ届かない）"""
    if not MANIFEST.is_file():
        return None
    try:
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except ValueError:
        return False
    body = plugin_bytes()
    return man.get("sha256") == hashlib.sha256(body).hexdigest() and man.get("version") == plugin_version()


def publish_release(site_dir):
    """build.py が呼ぶ: 署名が今のプラグインと合うときだけ、/wp/ に本体と案内を置く。
    合わないものを置くと、先方は署名の検査で弾くだけなので害は無いが、届かないことに気づけない"""
    ok = manifest_ok()
    if ok is None:
        return False
    if not ok:
        print("WARN: WordPress のプラグインを直したのに署名し直していません（python scripts/wp_bridge.py --sign）")
        return False
    d = Path(site_dir) / "wp"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ss-quality-gate.php").write_bytes(plugin_bytes())
    (d / "ss-bridge.json").write_bytes(MANIFEST.read_bytes())
    return True


def keygen(register=False):
    """署名の鍵を作る。秘密鍵は .env（WP_BRIDGE_SIGN_KEY）だけに置き、公開鍵をプラグインに書く。どちらも画面に出さない"""
    from nacl.signing import SigningKey
    if _sign_key():
        raise SystemExit("WP_BRIDGE_SIGN_KEY は既にあります。鍵を替えると、配った先のプラグインが更新を受け付けなくなります")
    sk = SigningKey.generate()
    seed = base64.b64encode(bytes(sk)).decode()
    pub = base64.b64encode(bytes(sk.verify_key)).decode()
    env = ROOT / ".env"
    cur = env.read_text(encoding="utf-8-sig") if env.is_file() else ""
    env.write_text(cur.rstrip("\n") + ("\n" if cur else "") + f"WP_BRIDGE_SIGN_KEY={seed}\n", encoding="utf-8")
    t = PLUGIN.read_text(encoding="utf-8")
    t = re.sub(r"define\('SSB_PUBKEY', '[^']*'\)", f"define('SSB_PUBKEY', '{pub}')", t, count=1)
    PLUGIN.write_text(t, encoding="utf-8", newline="\n")
    print("署名の鍵を作りました（秘密鍵は .env の WP_BRIDGE_SIGN_KEY、公開鍵はプラグインの SSB_PUBKEY）")
    if register:
        import subprocess
        r = subprocess.run(["gh", "secret", "set", "WP_BRIDGE_SIGN_KEY"], input=seed, text=True,
                           capture_output=True, cwd=ROOT)
        print("GitHub の Secret に登録しました" if r.returncode == 0 else "GitHub の Secret に登録できませんでした")
    print("次に: python scripts/wp_bridge.py --sign → 案内をコミット")


def check(cfgs):
    """WordPress の社のプラグインが最新か・自己更新が止まっていないか。止まっていれば要対応"""
    latest = plugin_version()
    wps = [c for c in cfgs.values() if is_wp(c)]
    if not wps:
        print("WPBRIDGE_OK=unset")
        return []
    bad = []
    for c in wps:
        try:
            st = call(c, "status")
        except SystemExit as e:
            bad.append(f"要対応: {c['id']} の橋渡しに届きません（プラグインが無い・古い・鍵が違う）: {str(e)[:80]}")
            continue
        if not isinstance(st, dict) or not st.get("version"):
            bad.append(f"要対応: {c['id']} の WordPress に橋渡し（ss/v1）がありません。"
                       "automation/wordpress/ss-quality-gate.php を mu-plugins に置いてください")
            continue
        up = st.get("update") or {}
        print(f"  {c['id']}: 版 {st['version']}（最新 {latest}）・自己更新 {up.get('state', '未実行')}")
        if st["version"] != latest:
            why = {"blocked": "サーバーがファイルの書き換えを許していません",
                   "nokey": "プラグインに公開鍵が無く、署名を確かめられません",
                   "error": up.get("msg", "")}.get(up.get("state"), "まだ更新を見に行っていません")
            bad.append(f"要対応: {c['id']} の WordPress のプラグインが古い版です（{st['version']} → {latest}・{why}）。"
                       "最新の ss-quality-gate.php を mu-plugins へ置き直してください")
    for b in bad:
        print(b)
    print("WPBRIDGE_OK=" + ("no" if bad else "yes"))
    return bad


def main():
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--sync", action="store_true", help="設定（llms.txt・鍵・GA4）と固定ページを揃える")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--sign", action="store_true")
    ap.add_argument("--keygen", action="store_true")
    ap.add_argument("--register", action="store_true", help="--keygen で作った秘密鍵を GitHub の Secret にも登録する")
    a = ap.parse_args()
    if a.keygen:
        keygen(a.register)
        return 0
    if a.sign:
        m = sign()
        print(f"署名しました: 版 {m['version']}（{MANIFEST.relative_to(ROOT)}）")
        return 0
    cfgs = S.load_all()
    if a.check:
        check({k: v for k, v in cfgs.items() if not a.site or k == a.site})
        return 0
    if a.sync:
        notes = []
        for sid, cfg in cfgs.items():
            if not is_wp(cfg) or (a.site and sid != a.site):
                continue
            print(f"■ {cfg['name']}（WordPress / {cfg['domain']}）")
            rows = url_rows(cfg)
            arts = _site_articles(cfg)
            notes += sync_pages(cfg, rows, arts)
            res = push_settings(cfg, url_rows(cfg))
            print(f"  設定: {', '.join((res or {}).get('saved') or []) or '—'}")
        for n in notes:
            print(n)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
