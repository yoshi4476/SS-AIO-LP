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
    try:
        req = urllib.request.Request(f"https://{cfg['domain']}/sitemap.xml",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return re.findall(r"<loc>(.*?)</loc>", r.read().decode("utf-8", "ignore"))
    except Exception as e:
        print(f"  {cfg['id']}: sitemapを取得できません（{str(e)[:50]}）")
        return []


def todays_urls(cfg):
    """本日公開・更新の記事URL。記事の site は原稿のカテゴリから決まる"""
    import sites as S
    import build
    today = str(date.today())
    out = []
    for p in (ROOT / "articles").glob("*.md"):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
        if not m:
            continue
        fm = m.group(1)
        if not re.search(rf"^(date|dateModified|modified):\s*{today}\s*$", fm, re.M):
            continue
        cat = re.search(r"^category:\s*(\S+)", fm, re.M)
        if not cat or S.find_category_owner(cat.group(1)) != cfg["id"]:
            continue
        slug = re.search(r"^slug:\s*(\S+)", fm, re.M)
        out.append(S.article_url(cfg, {"category": cat.group(1),
                                       "slug": slug.group(1) if slug else p.stem}))
    del build
    return out


def main():
    import sites as S
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    only = ""
    if "--site" in sys.argv:
        i = sys.argv.index("--site")
        only = sys.argv[i + 1] if len(sys.argv) > i + 1 else ""
        args = [a for a in args if a != only]
    if not SA_PATH.exists():
        print("indexing-service-account.json 未配置のためスキップ")
        return 0

    import gcreds
    from googleapiclient.discovery import build as gbuild
    svc = gbuild("indexing", "v3",
                 credentials=gcreds.load(SA_PATH, ["https://www.googleapis.com/auth/indexing"]))

    jobs = []
    if args:
        jobs = [("（指定URL）", args)]
    else:
        for sid, cfg in S.load_all().items():
            if only and sid != only:
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
