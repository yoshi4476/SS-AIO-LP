# -*- coding: utf-8 -*-
"""過去の誤りの棚卸し（動画・取り下げ）のうち、本番を見ないと確かめられないもの。

  1. 動画の説明欄の記事URLが本番で200を返し、そのサイトの sitemap.xml に載っているか
     （2026-09-23〜28: /blogai-hojokin-… や存在しない ai.7senses.co.jp のURLを案内していた）
  2. 取り下げを「完了」にした記事の旧URLが、本番で301/404になっているか
     （2026-09-25: 配信方式を存在しないキーで見て、配信先から外さないまま完了扱いにしていた）

見つかったら HISTB_OK=no（終了コード0）。本番に1件も届かず検査できなければ終了コード1。
"""
import io
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def status(url, loc=None):
    """転送をたどらずに状態コードを返す。届かなければ None。loc を渡すと転送先を入れる"""
    op = urllib.request.build_opener(_NoRedirect)
    try:
        return op.open(urllib.request.Request(url, headers=UA, method="GET"), timeout=20).status
    except urllib.error.HTTPError as e:
        if loc is not None:
            loc.append(e.headers.get("Location") or "")
        return e.code
    except Exception:
        return None


def sitemap_urls(domain, cache={}):
    if domain not in cache:
        try:
            with urllib.request.urlopen(urllib.request.Request(f"https://{domain}/sitemap.xml", headers=UA), timeout=20) as r:
                cache[domain] = {u.strip() for u in re.findall(r"<loc>([^<]+)</loc>", r.read().decode("utf-8", "ignore"))}
        except Exception:
            cache[domain] = None
    return cache[domain]


def video_urls():
    """上げた動画の説明欄の記事URL（youtube_upload.describe と同じ組み立て）"""
    import contextlib
    import social_post as SP
    import youtube_upload as YU
    vids = json.loads((ROOT / "data" / "videos.json").read_text(encoding="utf-8"))
    out = []
    for slug, v in vids.items():
        if not (v.get("youtube") or (v.get("short") or {}).get("youtube")):
            continue
        a = SP.article(slug)
        if not a:
            continue
        with contextlib.redirect_stdout(io.StringIO()):
            desc = YU.describe(slug)[0]
        m = re.search(r"▼ 記事はこちら\n(\S+)", desc)
        out.append((slug, SP.site_of(a["category"])[1].get("domain", ""), m.group(1) if m else ""))
    return out


def main():
    bad, reached = [], 0
    print("■ 動画の説明欄の記事URL")
    for slug, dom, url in video_urls():
        if not url:
            bad.append(f"{slug}: 説明欄に記事URLが無い")
            continue
        loc = []
        st = status(url, loc)
        reached += st is not None
        sm = sitemap_urls(dom)
        # 末尾スラッシュを外すだけの転送（Next.js の配信先）は、たどった先が200なら壊れていない
        if st in (301, 308) and loc and loc[0].rstrip("/") and url.rstrip("/").endswith(loc[0].rstrip("/")):
            st = status(url.rstrip("/"))
            print(f"  注意 {slug}: 末尾スラッシュの転送を1回挟む {url}")
        if st is None:
            print(f"  ?  {slug}: 届かない {url}")
        elif st != 200:
            bad.append(f"{slug}: {url} が {st}")
        if sm is not None and url not in sm and url.rstrip("/") not in sm:
            bad.append(f"{slug}: {url} が {dom} の sitemap.xml に無い")
    print("■ 取り下げ済みの旧URL")
    import sites as S
    f = ROOT / "data" / "retractions.jsonl"
    rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()] if f.is_file() else []
    for r in rows:
        if not r.get("done_at"):
            continue
        try:
            dom = S.load(r["site"])["domain"]
        except Exception:
            bad.append(f"{r['site']}/{r['slug']}: サイト設定が無い")
            continue
        url = f"https://{dom}{r['from']}"
        st = status(url)
        reached += st is not None
        if st is None:
            print(f"  ?  {r['slug']}: 届かない {url}")
        elif st == 200:
            bad.append(f"{r['site']}/{r['slug']}: 完了にしたのに旧URLが200のまま（{url}）")
    for x in bad:
        print(f"  NG {x}")
    if not reached:
        print("HISTB_OK=unknown （本番に1件も届きませんでした）")
        return 1
    print("HISTB_OK=" + ("no" if bad else "yes"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
