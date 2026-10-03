# -*- coding: utf-8 -*-
"""過去の誤りの棚卸し（サイト・HTML・配信）のうち、本番を見ないと確かめられないもの。

  1. _redirects の自社ドメイン宛ての転送先が本番で200か（2026-08-04/08-17: 行き先が消えていた。
     2026-10-03: 転送先が向こうで改名され2段の転送になっていた）
  2. 最新の記事ページの画像・og:image が本番で200か（2026-07-30: /images/blog/ が抜けて全画像404）
  3. 本番の llms.txt に sitemap の記事が全部載っているか（2026-08-05: コーポレートは0本だった）
  4. 本番の robots.txt が3サイトで同じクローラーを許可しているか（2026-08-07: 6種と13種）
  5. 本番の記事に旧ドメイン www.7senses.co.jp へのリンクが無いか（2026-08-04）

判定の部品は tests/gates_history_a.py と共通（同じ検出器で手元と本番を見る）。
見つかったら HISTA_OK=no（終了コード0）。本番に1件も届かず検査できなければ終了コード1。
"""
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126"}
DOMAINS = {"ai-lab": "ai.7senses.co.jp", "subsidy": "lp.7senses.co.jp", "corporate": "corp.7senses.co.jp"}
BUDGET = 58          # 本番への要求の上限（重くしない・ボット扱いされない）
_used = [0]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def fetch(url, follow=True, head=False):
    """(状態コード, 本文)。予算切れ・届かないときは (None, "")"""
    if _used[0] >= BUDGET:
        return None, ""
    _used[0] += 1
    op = urllib.request.build_opener() if follow else urllib.request.build_opener(_NoRedirect)
    try:
        with op.open(urllib.request.Request(url, headers=UA, method="HEAD" if head else "GET"), timeout=15) as r:
            return r.status, "" if head else r.read(800000).decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return None, ""


def main():
    import gates_history_a as G
    import sites as S
    found, reached = [], 0

    # 4. robots.txt
    agents = {}
    for sid, dom in DOMAINS.items():
        st, body = fetch(f"https://{dom}/robots.txt")
        if st == 200:
            reached += 1
            agents[sid] = G.robots_agents(body)
    if "ai-lab" in agents:
        for sid, a in agents.items():
            diff = sorted(set(agents["ai-lab"]) ^ set(a)) + sorted(k for k in set(agents["ai-lab"]) & set(a) if agents["ai-lab"][k] != a[k])
            if diff:
                found.append(f"robots.txt が ai-lab と食い違う {sid}: {', '.join(diff[:8])}")

    # 3. llms.txt と sitemap、2・5 は sitemap の最新記事で見る
    cats = "|".join(map(re.escape, S.load("ai-lab").get("categories", {})))
    pats = {"ai-lab": rf"https://ai\.7senses\.co\.jp/(?:{cats})/([a-z0-9-]+)/",
            "subsidy": r"https://lp\.7senses\.co\.jp/blog/(?!category/)([a-z0-9-]+)/?",
            "corporate": r"https://corp\.7senses\.co\.jp/blog/(?!theme\b)([a-z0-9-]+)/?"}
    latest = {}
    for sid, dom in DOMAINS.items():
        st1, sm = fetch(f"https://{dom}/sitemap.xml")
        st2, ll = fetch(f"https://{dom}/llms.txt")
        if st1 != 200:
            continue
        reached += 1
        arts = re.findall(pats[sid], sm)
        if st2 != 200:
            found.append(f"llms.txt が開けない {dom}（HTTP {st2}）")
        elif arts:
            gap = G.llms_gap(ll, sm, pats[sid])
            if gap:
                found.append(f"llms.txt に載っていない記事 {dom}: {len(gap)}本（{', '.join(gap[:5])}）")
        locs = [m.group(0) for m in re.finditer(pats[sid], sm)]
        latest[sid] = locs[-2:] if locs else []

    for sid, urls in latest.items():
        dom = DOMAINS[sid]
        for u in urls:
            st, html = fetch(u)
            if st != 200:
                found.append(f"sitemap の記事が開けない {u}（HTTP {st}）")
                continue
            if G.old_domain_links(html):
                found.append(f"旧ドメイン www.7senses.co.jp へのリンク {u}")
            imgs = []
            for a, b in G.IMG_RX.findall(G.strip_code(html)):
                src = a or b
                if src.startswith("/") and not src.startswith("//"):
                    src = f"https://{dom}{src}"
                if src.startswith(f"https://{dom}/") and src not in imgs:
                    imgs.append(src)
            for src in imgs[:3]:
                s, _ = fetch(src, head=True)
                if s == 405:
                    s, _ = fetch(src)
                if s is not None and s != 200:
                    found.append(f"画像が開けない {src}（HTTP {s}・{u}）")

    # 1. 自社ドメイン宛ての転送先
    rules = G.parse_redirects((ROOT / "site" / "_redirects").read_text(encoding="utf-8"))
    targets = []
    for src, dst, code in rules:
        if "*" in dst or ":" in dst.split("//", 1)[-1]:
            continue
        if dst.startswith("/"):
            dst = "https://ai.7senses.co.jp" + dst
        if re.match(r"https://(ai|lp|corp)\.7senses\.co\.jp/", dst) and dst not in targets:
            targets.append(dst)
    for dst in targets[:max(0, BUDGET - _used[0])]:
        st, _ = fetch(dst, follow=False)
        if st is None:
            continue
        reached += 1
        if st != 200:
            found.append(f"転送先が200でない {dst}（HTTP {st}{'・2段の転送' if st in (301, 302, 308) else ''}）")

    print(f"■ 本番の配信の検査（要求 {_used[0]}回）")
    for f in found:
        print(f"  - {f}")
    if not reached:
        print("本番に1件も届きませんでした（検査できず）")
        return 1
    print(f"HISTA_OK={'no' if found else 'yes'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
