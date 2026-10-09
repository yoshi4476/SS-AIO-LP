# -*- coding: utf-8 -*-
"""GEO（生成エンジン最適化）の下ごしらえができているかを、実物で検査する。

AI Overview だけでなく、ChatGPT・Perplexity・Claude・Copilot・Gemini など
生成エンジン全般から引用されるための条件を見る。順位とは別の軸なので、
GSCだけでは分からない。ここでは公開ページを実際に取得して確かめる。

見るのは次の5つ。どれも「引用する側が読めるか」に直結する。

  1. AIクローラーが弾かれていないか（robots.txt と、実際の応答）
  2. 生成エンジン向けの案内（llms.txt）が記事数に追いついているか
  3. 引用しやすい構造か（冒頭の断定・見出し直下の結論・FAQ・表）
  4. 出典つきの数字があるか（引用される側の根拠）
  5. 鮮度が示されているか（生成エンジンは古い情報を避ける）

  python scripts/geo_check.py                # 3サイトを検査
  python scripts/geo_check.py --site ai-lab  # 1サイトだけ
"""
import argparse
import json
import random
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 生成エンジンのクローラー。名乗って取りに行き、弾かれないかを見る
BOTS = {
    "ChatGPT": "Mozilla/5.0 (compatible; GPTBot/1.1; +https://openai.com/gptbot)",
    "ChatGPT検索": "Mozilla/5.0 (compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot)",
    "Claude": "Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)",
    "Perplexity": "Mozilla/5.0 (compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)",
    "Google拡張": "Mozilla/5.0 (compatible; Google-Extended/1.0)",
    "Bing/Copilot": "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
}
UA = "SevenSenses-GeoCheck/1.0 (+https://7senses.co.jp)"


def get(url, ua=UA, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def article_slugs(site_id):
    """その社の記事（公開基準を満たす原稿）の slug。
    sitemap の深さ（/ の数）で記事を決めていたため、業種ハブ・用語集・調査・事例のページまで記事に数え、
    ai-lab の llms.txt を「74%」と誤って出していた（2026-10-07。原稿の記事で数えると 146/146 本＝100%）"""
    sys.path.insert(0, str(ROOT / "scripts"))
    import publish as P
    import sites as S
    out = set()
    for p in (ROOT / "articles").glob("*.md"):
        if p.name.startswith("_"):
            continue
        m = P.read_meta(p)
        if m and S.find_category_owner(m.get("category", "")) == site_id and P.gate_ok(m):
            out.add(p.stem)
    return out


def _norm(u):
    return u.split("#")[0].split("?")[0].rstrip("/")


def article_urls(sitemap_xml, slugs):
    """sitemap のURLのうち、末尾がその社の記事の slug のもの（WordPress のパーマリンクでも同じに数える）"""
    return [u for u in re.findall(r"<loc>([^<]+)</loc>", sitemap_xml) if _norm(u).rsplit("/", 1)[-1] in slugs]


def article_coverage(sitemap_xml, llms_text, slugs):
    """(llms.txt に載っている記事の数, sitemap にある記事の数, 載っていない記事のURL)"""
    arts = article_urls(sitemap_xml, slugs)
    listed = {_norm(u) for u in re.findall(r"\((https?://[^)\s]+)\)", llms_text)}
    miss = [u for u in arts if _norm(u) not in listed]
    return len(arts) - len(miss), len(arts), miss


def sample_articles(sitemap_xml, slugs, n=3):
    """sitemap から、その社の記事のURLを何本か拾う（記事でないページは拾わない）"""
    arts = article_urls(sitemap_xml, slugs)
    random.seed(0)                       # 毎回同じ標本にして、前回と比べられるようにする
    return random.sample(arts, min(n, len(arts))) if arts else []


def check_structure(html):
    """引用しやすい構造かを見る。生成エンジンは切り出せる形を好む"""
    body = re.sub(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", "", html,
                  flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", body)
    h2 = re.findall(r"<h2[^>]*>(.*?)</h2>", body, re.S | re.I)
    return {
        "見出し": len(h2),
        "FAQ": bool(re.search(r'"@type"\s*:\s*"FAQPage"', html)),
        "記事情報": bool(re.search(r'"@type"\s*:\s*"(BlogPosting|Article)"', html)),
        "パンくず": bool(re.search(r'"@type"\s*:\s*"BreadcrumbList"', html)),
        "更新日": bool(re.search(r'"dateModified"', html)),
        "比較表": bool(re.search(r"<table", body, re.I)),
        "出典リンク": len(re.findall(r'<a[^>]+href="https?://(?!(?:[a-z-]+\.)?7senses\.co\.jp)', body, re.I)),
        "鮮度表記": bool(re.search(r"20\d\d年\s*\d+月時点", text)),
        "数字": len(re.findall(r"\d+(?:\.\d+)?\s*(?:%|％|件|本|社|円|倍|位)", text)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site")
    ap.add_argument("--articles", type=int, default=3, help="1サイトあたり調べる記事数")
    a = ap.parse_args()

    import sites as _S
    conf = _S.load_all()
    ng = []
    for site, c in sorted(conf.items()):
        if a.site and site != a.site:
            continue
        d = c["domain"]
        print(f"\n{'=' * 60}\n■ {c.get('name', site)}（{d}）\n{'=' * 60}")

        # 1. 生成エンジンのクローラーが実際に取れるか
        print("  ▼ 生成エンジンから読めるか")
        blocked = []
        for name, ua in BOTS.items():
            code, _ = get(f"https://{d}/", ua=ua)
            mark = "OK" if code == 200 else f"NG({code})"
            if code != 200:
                blocked.append(name)
            print(f"     {name:<14} {mark}")
        if blocked:
            ng.append(f"{site}: {'/'.join(blocked)} が読めません")

        # 2. 案内ファイルが記事数に追いついているか（sitemap にある、その社の記事のうち llms.txt に載っている割合）
        code, llms = get(f"https://{d}/llms.txt")
        _, xml = get(f"https://{d}/sitemap.xml")
        slugs = article_slugs(site)
        listed, total, miss = article_coverage(xml, llms if code == 200 else "", slugs)
        rate = (listed / total * 100) if total else 0
        print("\n  ▼ 生成エンジン向けの案内（llms.txt）")
        print(f"     掲載 {listed}件 / 記事 {total}本（{rate:.0f}%）" + (f"  例: {miss[0]}" if miss else ""))
        if total and rate < 80:
            ng.append(f"{site}: llms.txt の掲載が {rate:.0f}% しかありません")

        # 3〜5. 記事の中身が引用に耐えるか
        print(f"\n  ▼ 引用しやすい作りか（{a.articles}本を抽出）")
        for u in sample_articles(xml, slugs, a.articles):
            code, html = get(u)
            if code != 200:
                print(f"     取得できません（{code}）: {u}")
                continue
            s = check_structure(html)
            slug = u.rstrip("/").rsplit("/", 1)[-1][:30]
            miss = [k for k in ("FAQ", "記事情報", "パンくず", "更新日", "鮮度表記") if not s[k]]
            print(f"     {slug:<32} 見出し{s['見出し']:>2} 表{'○' if s['比較表'] else '×'}"
                  f" 出典{s['出典リンク']:>2} 数字{s['数字']:>3}"
                  + (f"  欠け: {'/'.join(miss)}" if miss else "  欠けなし"))
            if miss:
                ng.append(f"{site}/{slug}: {'/'.join(miss)} が無い")

    print(f"\n{'=' * 60}")
    if ng:
        print(f"GEO_OK=no（{len(ng)}件）")
        for x in ng[:12]:
            print(f"  - {x}")
    else:
        print("GEO_OK=yes（生成エンジンから読め、引用に必要な形が揃っています）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
