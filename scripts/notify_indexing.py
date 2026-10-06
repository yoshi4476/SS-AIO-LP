# -*- coding: utf-8 -*-
"""Google Indexing API 即時登録（Phase 7 / 公開直後に実行）

**3サイトすべてを対象にする。** 以前は AI集客ラボ の sitemap だけを見ていたため、
コーポレートと補助金は記事を出しても検索エンジンに知らせていなかった。実測では、
公開から13日以内に一度でも検索結果に出たページの割合が
AI集客ラボ72%に対しコーポレート41%と、明確に差が出ていた（2026-09-22）。

使い方:
    python scripts/notify_indexing.py             # 本日公開・更新の記事URLを通知（全サイト）
    python scripts/notify_indexing.py --site corporate
    python scripts/notify_indexing.py --all       # sitemapの全URL（初回・障害復旧用）
    python scripts/notify_indexing.py <URL> ...   # 指定URL

前提: indexing-service-account.json（対象サイトのGSCオーナー権限）
※未配置なら静かにスキップする（Actionsで未設定でも失敗させない）
お客様の社は、サービスアカウントが Search Console のオーナーになっている社だけ送る（gsc_owner_ok）。
なっていなければ送らず「要対応」を出す（記事CIの公開直後の通知から findings へ載る）。
"""
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
SA_PATH = ROOT / "indexing-service-account.json"
DAILY_CAP = 190      # APIの1日200件に対する安全マージン


def sitemap_of(cfg):
    """公開中の sitemap を読む。他サイトは手元に無いのでHTTPで取る"""
    local = ROOT / "site" / "sitemap.xml"
    import sites as S
    if cfg["id"] == S.primary() and local.is_file():
        return re.findall(r"<loc>(.*?)</loc>", local.read_text(encoding="utf-8"))
    # WordPress の sitemap は索引形式（/wp-sitemap.xml）で、平らに読むと記事が0件だった。橋渡しの一覧から取る
    if cfg.get("type") == "wordpress":
        import wp_bridge
        return wp_bridge.site_urls(cfg)
    try:
        req = urllib.request.Request(f"https://{cfg['domain']}/sitemap.xml",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return re.findall(r"<loc>(.*?)</loc>", r.read().decode("utf-8", "ignore"))
    except Exception as e:
        print(f"  {cfg['id']}: sitemapを取得できません（{str(e)[:50]}）")
        return []


def todays_urls(cfg, days=1):
    """本日（days>1 なら直近 days 日）公開・更新の記事URL。記事の site は原稿のカテゴリから決まる"""
    import sites as S
    import build
    from datetime import timedelta
    dates = "|".join(str(date.today() - timedelta(days=i)) for i in range(max(1, days)))
    out = []
    # WordPress の記事URLはパーマリンク設定が決める（組み立てると sitemap と突き合わず、通知が0件になる）
    links = {}
    if cfg.get("type") == "wordpress":
        import wp_bridge
        links = wp_bridge.url_map(cfg)
    for p in (ROOT / "articles").glob("*.md"):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
        if not m:
            continue
        fm = m.group(1)
        if not re.search(rf"^(date|dateModified|modified):\s*(?:{dates})\s*$", fm, re.M):
            continue
        cat = re.search(r"^category:\s*(\S+)", fm, re.M)
        if not cat or S.find_category_owner(cat.group(1)) != cfg["id"]:
            continue
        slug = re.search(r"^slug:\s*(\S+)", fm, re.M)
        slug = slug.group(1) if slug else p.stem
        out.append(links.get(slug) or S.article_url(cfg, {"category": cat.group(1), "slug": slug}))
    del build
    return out


def sa_email():
    try:
        import json
        return json.loads(SA_PATH.read_text(encoding="utf-8-sig")).get("client_email", "")
    except (OSError, ValueError):
        return ""


def owner_domains():
    """サービスアカウントが Search Console のオーナーになっているドメイン。読めなければ None（設定の値で判断する）。
    Indexing API はオーナーのサイトのURLしか受け付けない。先方がオーナーに足した時点で、設定を書き換えなくても送り始める"""
    try:
        import gcreds
        from googleapiclient.discovery import build as gbuild
        sc = gbuild("searchconsole", "v1", credentials=gcreds.load(
            SA_PATH, ["https://www.googleapis.com/auth/webmasters.readonly"]))
        rows = sc.sites().list().execute().get("siteEntry", [])
    except Exception:
        return None
    out = set()
    for r in rows:
        if r.get("permissionLevel") != "siteOwner":
            continue
        u = r.get("siteUrl", "")
        out.add(u.split(":", 1)[1] if u.startswith("sc-domain:") else u.split("//", 1)[-1].strip("/"))
    return out


def gsc_owner_ok(cfg, owners=None):
    """Indexing API で送ってよい社か。自社は既にオーナー。お客様は Search Console の実際の権限
    （読めたとき）か、ヒアリングで聞いた sites/<id>.json の gsc_owner"""
    import sites as S
    if not S.is_client(cfg["id"]):
        return True
    if owners is not None:
        d = cfg["domain"]
        return any(d == o or d.endswith("." + o) for o in owners)
    return cfg.get("gsc_owner") is True


def gsc_owner_todo(cfg):
    who = sa_email() or "当社のサービスアカウント"
    return (f"要対応: {cfg.get('name', cfg['id'])}（{cfg['domain']}）の Search Console に"
            f"サービスアカウント（{who}）をオーナーで追加してください。追加されるまで新しい記事を Indexing API で知らせません")


def _service():
    import gcreds
    from googleapiclient.discovery import build as gbuild
    return gbuild("indexing", "v3",
                  credentials=gcreds.load(SA_PATH, ["https://www.googleapis.com/auth/indexing"]))


def main(argv=None, cfgs=None):
    import sites as S
    argv = sys.argv[1:] if argv is None else argv
    args = [a for a in argv if not a.startswith("--")]
    only = ""
    if "--site" in argv:
        i = argv.index("--site")
        only = argv[i + 1] if len(argv) > i + 1 else ""
        args = [a for a in args if a != only]
    if not SA_PATH.exists():
        print("indexing-service-account.json 未配置のためスキップ")
        return 0

    svc = _service()
    cfgs = S.load_all() if cfgs is None else cfgs

    jobs = []
    if args:
        jobs = [("（指定URL）", args)]
    else:
        owners = owner_domains() if any(S.is_client(s) for s in cfgs) else None
        for sid, cfg in cfgs.items():
            if only and sid != only:
                continue
            # 権限の無い社に送っても 403 が並ぶだけ。送らずに、先方にお願いすることを出す
            if not gsc_owner_ok(cfg, owners):
                print(gsc_owner_todo(cfg))
                continue
            urls = sitemap_of(cfg)
            if "--all" in sys.argv:
                jobs.append((sid, urls))
            else:
                known = {u.rstrip("/") + "/" for u in urls}
                pick = [u for u in todays_urls(cfg) if u.rstrip("/") + "/" in known]
                jobs.append((sid, pick))

    total_ok = total = 0
    left = DAILY_CAP
    for sid, urls in jobs:
        if not urls:
            print(f"  {sid}: 通知対象なし")
            continue
        urls = urls[:max(0, left)]
        left -= len(urls)
        ok = 0
        for u in urls:
            try:
                svc.urlNotifications().publish(body={"url": u, "type": "URL_UPDATED"}).execute()
                ok += 1
            except Exception as e:
                print(f"  NG {u}: {str(e)[:110]}")
        total_ok += ok
        total += len(urls)
        print(f"  {sid}: {ok}/{len(urls)}件を通知")
    print(f"Indexing API通知: {total_ok}/{total}件 成功")
    return 0


if __name__ == "__main__":
    sys.exit(main())
