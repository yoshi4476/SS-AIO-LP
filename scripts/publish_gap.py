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
sys.path.insert(0, str(ROOT / "scripts"))
import publish  # noqa: E402


def live_slugs_wp(domain):
    """WordPressは REST API から公開済みのslugを取る。

    sitemap から拾おうとすると、WordPress標準は /wp-sitemap.xml、
    Yoastは /sitemap_index.xml と入口が分かれるうえ、どちらも
    インデックス形式で子を辿る必要がある。RESTなら1回で確実に取れる。
    公開記事の一覧は認証なしで読める。
    """
    out, page = set(), 1
    while page <= 20:
        url = (f"https://{domain}/wp-json/wp/v2/posts"
               f"?per_page=100&page={page}&status=publish&_fields=slug")
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "SevenSenses-PublishGap/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                rows = json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            return None if page == 1 else out
        if not isinstance(rows, list) or not rows:
            break
        out |= {x.get("slug", "") for x in rows if x.get("slug")}
        if len(rows) < 100:
            break
        page += 1
    return out


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


def live_manifest(domain):
    """公開サイトに置かれた、配信済み原稿の指紋一覧。

    配信のたびに publish.py が更新する。まだ無いサイトでは空になり、
    その場合はタイトルと本文の突き合わせに切り替える。
    """
    code, body = _get(f"https://{domain}/article-manifest.json")
    if code != 200:
        return None
    try:
        d = json.loads(body)
        return d if isinstance(d, dict) else None
    except ValueError:
        return None


def source_hash(md_path):
    import hashlib
    return hashlib.sha1(Path(md_path).read_bytes()).hexdigest()[:12]


def recently_edited(days=2):
    """ここ数日で手を入れた記事。指紋がまだ無いサイト向けの受け皿。

    指紋の記録は配信時に始まるので、仕組みを入れた直後は空になる。
    その間に本文だけ直した記事は、タイトルが同じなので取りこぼされる。
    直近の編集分だけを配信し直せば、1周で指紋が揃って以降は正確に判定できる。
    """
    r = subprocess.run(
        ["git", "log", f"--since={days} days ago", "--name-only", "--pretty=",
         "--", "articles/"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    return {Path(l).stem for l in r.stdout.split() if l.endswith(".md")}


def _flat(s):
    """飾りを落として、地の文だけを続いた1本の文字列にする。

    markdown の **太字** は公開側で <strong>太字</strong> になる。
    どちらからも記号とタグを落とせば、同じ地の文が残って突き合わせられる。
    """
    s = re.sub(r"<[^>]+>", "", s)                     # HTMLタグ
    s = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", s)  # 画像・リンクは文字だけ残す
    s = re.sub(r"[*=_`#|>~\-]", "", s)                # 装飾記号・表の罫線
    return re.sub(r"\s+", "", s)


def _fragments(md_text, n=3, size=24):
    """本文から、離れた位置の地の文をいくつか取り出す。

    タイトルだけを比べると、本文だけを直したときに「配信済み」に見える。
    実際、リード導線を全記事に足したのに1本も届かなかった。
    """
    body = _flat(md_text.split("---", 2)[-1])
    if len(body) < size * 4:
        return []
    # 端は定型（冒頭の断言・まとめ）になりやすい。中ほどから拾う
    return [body[int(len(body) * r):int(len(body) * r) + size]
            for r in (0.35, 0.60, 0.85)][:n]


def _live_matches(domain, slug, title, frags):
    """公開ページが手元の記事と合っているか。タイトルと本文の両方を見る。

    戻り値は (合っているか, 理由)。取得できないときは古い扱いにしない。
    """
    for path in (f"/blog/{slug}/", f"/blog/{slug}"):
        code, html = _get(f"https://{domain}{path}")
        if code != 200:
            continue
        m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
        if title and not (m and title[:24] in m.group(1)):
            return False, "タイトル"
        if frags:
            flat = _flat(html)
            miss = [f for f in frags if f not in flat]
            # 1つだけの不一致は、公開側の整形の違いで起こりうる。2つ以上を不一致とみなす
            if len(miss) >= 2:
                return False, "本文"
        return True, ""
    return True, ""    # 場所が違うだけかもしれない。判断できないものは古い扱いにしない


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
        # 未審査・基準未満・観点の足切りは配信対象外（判定は publish.py と同じ関数）
        meta = publish.read_meta(p)
        if not meta or not publish.gate_ok(meta):
            continue
        site = cat_site.get(g("category"))
        if site:
            # タイトルも持つ。ページが在るかだけでは、内容の更新が届いたかを
            # 見られない。実際、タイトルを直しても「配信済み」に見え、
            # 古いまま公開され続けていた
            mine.setdefault(site, []).append(
                (p.stem, g("title").strip('"'), _fragments(t), source_hash(p)))

    total_gap = 0
    for site, slugs in sorted(mine.items()):
        c = conf[site]
        live = (live_slugs_wp(c["domain"]) if c.get("type") == "wordpress"
                else live_slugs(c["domain"]))
        if live is None:
            print(f"■ {site}: 公開状況を取れません（{c['domain']}）")
            continue
        missing = [s for s, _, _, _ in slugs if s not in live]
        # 在るページは、配信時に残した指紋と突き合わせる。
        # 指紋がまだ無いサイトでは、タイトルと本文で判断する
        # 自前でビルドするサイトは同じリポジトリで完結し、配信という工程が無い。
        # 「届いたか」を問う対象ではないので、内容の照合はしない
        if c.get("type") == "self-static":
            print(f"■ {site}: 手元 {len(slugs)}本 / 自前ビルドのため照合しません")
            continue
        man = None if c.get("type") == "wordpress" else live_manifest(c["domain"])
        fresh = set() if man is not None else recently_edited()
        stale, why = [], {}
        for s, title, frags, h in slugs:
            if s not in live:
                continue
            if man is not None:
                if man.get(s) != h:
                    stale.append(s)
                    why[s] = "未記録" if s not in man else "内容"
                continue
            # 指紋がまだ無い間は、直近で手を入れた記事を配信し直す。
            # 本文だけの修正はタイトル比較では見つけられないため
            if s in fresh:
                stale.append(s)
                why[s] = "直近の修正が未達"
                continue
            ok, reason = _live_matches(c["domain"], s, title, frags)
            if not ok:
                stale.append(s)
                why[s] = reason
        gap = missing + stale
        total_gap += len(gap)
        print(f"■ {site}: 手元 {len(slugs)}本 / 公開 {len(slugs) - len(missing)}本"
              f" / 未配信 {len(missing)}本 / 内容が古い {len(stale)}本")
        for s in gap[:8]:
            print(f"     {s}（{why.get(s, '未配信')}）")
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
