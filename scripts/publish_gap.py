# -*- coding: utf-8 -*-
"""手元の記事と、実際に公開されている記事のずれを見つける。

publish_changed の --since はgitの差分を見るだけで、
「本当に届いたか」は見ていない。配信が途中で止まっても気づけない。
実際、79本のうち11本しか届いていないのに誰も気づかなかった。

ここでは公開サイトのsitemapを引き、本番に無い記事を数える。

  python scripts/publish_gap.py              # ずれを一覧する
  python scripts/publish_gap.py --publish    # 足りない分を配信する
"""
import argparse
import glob
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def live_slugs(domain):
    """公開サイトのsitemapから、いま出ている記事のslugを集める"""
    for path in ("/sitemap.xml", "/sitemap-0.xml", "/blog/sitemap.xml"):
        try:
            req = urllib.request.Request(
                f"https://{domain}{path}",
                headers={"User-Agent": "SevenSenses-PublishGap/1.0 (+https://7senses.co.jp)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                xml = r.read().decode("utf-8", "replace")
        except Exception:
            continue
        locs = re.findall(r"<loc>([^<]+)</loc>", xml)
        if locs:
            return {u.rstrip("/").rsplit("/", 1)[-1] for u in locs}
    return None


def _title_matches(domain, slug, title):
    """公開ページのタイトルが、手元の記事と合っているか。
    ページが在るだけでは、直した内容が届いたかは分からない"""
    for path in (f"/blog/{slug}/", f"/blog/{slug}"):
        code, html = _get(f"https://{domain}{path}")
        if code == 200:
            m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
            return bool(m and title[:24] in m.group(1))
    return True        # 場所が違うだけかもしれない。判断できないものは古い扱いにしない


def _get(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "SevenSenses-PublishGap/1.0 (+https://7senses.co.jp)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception:
        return 0, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true", help="足りない分を配信する")
    ap.add_argument("--limit", type=int, default=40, help="1回に配信する上限")
    a = ap.parse_args()

    conf = {p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in (ROOT / "sites").glob("*.json")}
    cat_site = {k: s for s, c in conf.items() for k in (c.get("categories") or {})}

    mine = {}
    for f in sorted(glob.glob(str(ROOT / "articles" / "*.md"))):
        p = Path(f)
        t = p.read_text(encoding="utf-8-sig")
        g = lambda k: (re.search(rf"^{k}:\s*(.+)$", t, re.M) or [0, ""])[1].strip()
        score = g("score")
        if not score or int(score) < 90:      # 未審査・基準未満は配信対象外
            continue
        site = cat_site.get(g("category"))
        if site:
            # タイトルも持つ。ページが在るかだけでは、内容の更新が届いたかを
            # 見られない。実際、タイトルを直しても「配信済み」に見え、
            # 古いまま公開され続けていた
            mine.setdefault(site, []).append((p.stem, g("title").strip('"')))

    total_gap = 0
    for site, slugs in sorted(mine.items()):
        c = conf[site]
        live = live_slugs(c["domain"])
        if live is None:
            print(f"■ {site}: 公開状況を取れません（{c['domain']}）")
            continue
        missing = [s for s, _ in slugs if s not in live]
        # 在るページは、タイトルが手元と一致しているかまで見る
        stale = []
        for s, title in slugs:
            if s in live and title and not _title_matches(c["domain"], s, title):
                stale.append(s)
        gap = missing + stale
        total_gap += len(gap)
        print(f"■ {site}: 手元 {len(slugs)}本 / 公開 {len(slugs) - len(missing)}本"
              f" / 未配信 {len(missing)}本 / 内容が古い {len(stale)}本")
        for s in gap[:8]:
            print(f"     {s}")
        if len(gap) > 8:
            print(f"     …ほか {len(gap) - 8}本")

        if a.publish and gap and c.get("type") != "self-static":
            for i, s in enumerate(gap[:a.limit], 1):
                r = subprocess.run(
                    [sys.executable, str(ROOT / "scripts" / "publish.py"),
                     "--site", site, "--slug", s, "--push"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace")
                mark = "○" if r.returncode == 0 else "×"
                print(f"     [{i}] {mark} {s}", flush=True)

    print(f"\nPUBLISH_GAP={total_gap}")
    if total_gap and not a.publish:
        print("  --publish を付けると、足りない分を配信します")
    return 0


if __name__ == "__main__":
    sys.exit(main())
