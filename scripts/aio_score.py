# -*- coding: utf-8 -*-
"""AIO対策の到達度を100点満点で採点する（3サイト共通）

使い方: python scripts/aio_score.py

「AIO対策をしている」と言うだけでは、どこが足りないか分からない。
配点を先に決めて、実測値だけで採点する。印象では動かさない。

配点の考え方:
  入口 25点 … AIが読めなければ、中身がどれだけ良くても引用されない
  構造 35点 … AIが抜き出せる形か。引用されるかを最も左右する
  信頼 15点 … 一次情報・出典・著者。誰が書いたか分からない記事は使われない
  成果 25点 … 引用の前提は検索上位。順位が取れていなければ土俵に乗らない

満点を「完璧」ではなく「この配点で測れる範囲での到達」と読むこと。
AI Overviewでの実際の引用数はGSCの生成AIレポート（2026年6月導入）を
待つ必要があり、ここでは前提条件までしか測れない。
"""
import collections
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import sites as S  # noqa: E402

# 内部リンクの数え方は score_check と同じものを使う。相対パスだけを数えると、
# 絶対URLで書かれたリンクが漏れる（実際、41本を「リンク不足」と誤判定していた）
import score_check  # noqa: E402
_INTERNAL, _ = score_check._link_patterns()

# 記事1本ごとに見るAIOの実装。AI検索が引用するときに使う手がかり
RULES = [
    ("冒頭の断言型回答", lambda b, f: b.lstrip().startswith("**")),
    ("対象読者の限定", lambda b, f: "target-reader" in b),
    ("鮮度の明示", lambda b, f: bool(re.search(r"20\d\d年\d+月時点", b))),
    ("定義ブロック", lambda b, f: "definition-box" in b),
    ("比較テーブル", lambda b, f: "|:--" in b),
    ("FAQ 5問以上", lambda b, f: b.count("<details>") >= 5),
    ("FAQの構造化データ", lambda b, f: "faq:" in f),
    ("H2が6個以上", lambda b, f: len(re.findall(r"^## ", b, re.M)) >= 6),
    ("失敗例・注意点", lambda b, f: bool(re.search(r"NG|失敗|注意|つまず|落とし穴", b))),
    ("内部リンク3本以上", lambda b, f: len(_INTERNAL.findall(b)) >= 3),
]
TRUST = [
    ("数値ファクト3箇所", lambda b, f: len(
        re.findall(r"\d[\d,\.]*(?:%|円|件|社|本|回|倍|日|年)", b)) >= 3),
    ("出典つき外部リンク", lambda b, f: len(
        re.findall(r'href="https?://(?!(?:ai|corp|lp)\.7senses)', b)) >= 2),
    ("自社の一次情報", lambda b, f: bool(
        re.search(r"当社|弊社|私たち|運用してきました|支援して", b))),
]


def articles():
    cat2site = {c: sid for sid, cfg in S.load_all().items()
                for c in cfg.get("categories", {})}
    out = collections.defaultdict(list)
    for p in sorted((ROOT / "articles").glob("*.md")):
        t = p.read_text(encoding="utf-8", errors="replace")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
        if not m:
            continue
        fm, body = m.groups()
        sc = re.search(r"^score:\s*(\d+)", fm, re.M)
        if not sc or int(sc.group(1)) < 90:
            continue
        cat = (re.search(r"^category:\s*(.+)$", fm, re.M) or [0, ""])[1].strip()
        sid = cat2site.get(cat)
        if sid:
            out[sid].append((fm, body))
    return out


def entry_score(sid, cfg):
    """入口25点。AIクローラーの許可・llms.txt・構造化データ・sitemap"""
    import urllib.request
    got, detail = 0, []

    def fetch(path):
        try:
            req = urllib.request.Request(f"https://{cfg['domain']}{path}",
                                         headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            return ""

    rb = fetch("/robots.txt")
    bots = ["GPTBot", "OAI-SearchBot", "ClaudeBot", "PerplexityBot",
            "Google-Extended", "Bingbot"]
    ok = [b for b in bots if b in rb]
    pt = round(10 * len(ok) / len(bots))
    got += pt
    detail.append(f"AIクローラーの許可 {len(ok)}/{len(bots)}種  {pt}/10")

    llms = fetch("/llms.txt")
    n = llms.count("](")
    pt = 8 if n >= 50 else (5 if n >= 10 else (2 if llms else 0))
    got += pt
    detail.append(f"llms.txt（案内）掲載{n}件  {pt}/8")

    sm = fetch("/sitemap.xml") or fetch("/sitemap-0.xml") or fetch("/wp-sitemap.xml")
    pt = 4 if sm.count("<loc>") >= 20 else (2 if sm else 0)
    got += pt
    detail.append(f"sitemap.xml  {pt}/4")

    # Googlebotを塞いでいないこと。塞ぐとAI Overviewの対象から外れる
    blocked = bool(re.search(r"User-agent:\s*\*\s*\n\s*Disallow:\s*/\s*$", rb, re.M))
    pt = 0 if blocked else 3
    got += pt
    detail.append(f"検索エンジンを塞いでいない  {pt}/3")
    return got, detail


def structure_score(arts):
    """構造35点。記事がAIに抜き出せる形になっているか"""
    if not arts:
        return 0, ["記事なし  0/35"]
    per = 35 / len(RULES)
    got, detail = 0.0, []
    for name, fn in RULES:
        hit = sum(1 for fm, b in arts if _safe(fn, b, fm))
        r = hit / len(arts)
        got += per * r
        detail.append(f"{name} {hit}/{len(arts)}本（{r * 100:.0f}%）  {per * r:.1f}/{per:.1f}")
    return got, detail


def trust_score(arts, backlinks=0):
    """信頼15点。一次情報・出典・著者と、外部からの評価"""
    if not arts:
        return 0, ["記事なし  0/15"]
    per = 10 / len(TRUST)          # 記事の中身で10点
    got, detail = 0.0, []
    for name, fn in TRUST:
        hit = sum(1 for fm, b in arts if _safe(fn, b, fm))
        r = hit / len(arts)
        got += per * r
        detail.append(f"{name} {hit}/{len(arts)}本（{r * 100:.0f}%）  {per * r:.1f}/{per:.1f}")
    # 外部からの評価5点。買えないので、実測がゼロなら素直にゼロにする
    pt = min(5, backlinks / 10 * 5) if backlinks else 0
    got += pt
    detail.append(f"外部からの被リンク {backlinks}件  {pt:.1f}/5")
    return got, detail


def result_score(sid, cfg, days=28):
    """成果25点。引用の前提になる検索順位が取れているか"""
    try:
        import gsc_detail as G
        sc = G.client()
        end = date.today() - timedelta(days=3)
        start = end - timedelta(days=days - 1)
        rows = G.q(sc, cfg["domain"], str(start), str(end), ["page"], 2000)
    except Exception as e:
        return 0, [f"GSCから取得できません（{str(e)[:40]}）  0/25"]
    if not rows:
        return 0, ["検索結果に出ているページがありません  0/25"]
    imp = sum(r["impressions"] for r in rows)
    clk = sum(r["clicks"] for r in rows)
    top10 = sum(1 for r in rows if r["position"] <= 10.5)
    top3 = sum(1 for r in rows if r["position"] <= 3.5)
    detail, got = [], 0.0

    # 1ページ目に入っている割合。AI Overviewは上位を読んで回答を作る
    r10 = top10 / len(rows)
    pt = 12 * min(r10 / 0.6, 1)      # 6割で満点
    got += pt
    detail.append(f"10位以内 {top10}/{len(rows)}ページ（{r10 * 100:.0f}%）  {pt:.1f}/12")

    r3 = top3 / len(rows)
    pt = 6 * min(r3 / 0.15, 1)       # 15%で満点
    got += pt
    detail.append(f"3位以内 {top3}ページ（{r3 * 100:.0f}%）  {pt:.1f}/6")

    ctr = clk / max(imp, 1)
    pt = 7 * min(ctr / 0.03, 1)      # 3%で満点
    got += pt
    detail.append(f"クリック率 {ctr * 100:.2f}%（表示{imp:,}回）  {pt:.1f}/7")
    return got, detail


def _safe(fn, b, fm):
    try:
        return bool(fn(b, fm))
    except Exception:
        return False


def grade(n):
    return ("A（引用される条件が整っている）" if n >= 85 else
            "B（土台はできている。順位が伸びれば引用が増える）" if n >= 70 else
            "C（構造か順位のどちらかが足りない）" if n >= 55 else
            "D（基礎から作り直しが要る）")


def main():
    arts = articles()
    print("=" * 72)
    print("■ AIO対策の到達度（100点満点・すべて実測値）")
    print(f"  測定日: {date.today().isoformat()}")
    print("=" * 72)
    total = []
    for sid, cfg in S.load_all().items():
        a = arts.get(sid, [])
        e, ed = entry_score(sid, cfg)
        s, sd = structure_score(a)
        t, td = trust_score(a)
        r, rd = result_score(sid, cfg)
        pt = e + s + t + r
        total.append(pt)
        print(f"\n■ {cfg['name']}（{cfg['domain']}）  記事 {len(a)}本")
        print(f"   総合 {pt:.0f} 点 — {grade(pt)}")
        for label, val, mx, det in (("入口", e, 25, ed), ("構造", s, 35, sd),
                                    ("信頼", t, 15, td), ("成果", r, 25, rd)):
            print(f"\n   【{label}】{val:.1f} / {mx}")
            for d in det:
                print(f"     ・{d}")
    print("\n" + "=" * 72)
    avg = sum(total) / max(len(total), 1)
    print(f"■ 3サイト平均: {avg:.0f} 点 — {grade(avg)}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
