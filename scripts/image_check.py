# -*- coding: utf-8 -*-
"""図解・アイキャッチの崩れを、描いた元の文字列から確かめる。

画像は Pillow で描くので、描き直さなくても「収まったか」は同じ計算で分かる。
make_diagram / make_eyecatch の収め方（縮小の下限・折り返し）をそのまま呼び、
下限まで縮めても箱からはみ出す文字列を見つける。OCR は使わない
（重い依存を入れずに済み、崩れの原因が原稿のどの文字列かまで言えるため）。

見るもの:
  1. はみ出し … 下限の文字サイズでも枠に収まらない題・項目。flow 型は折り返した行が
     番号の丸や箱の下端にかかるもの。項目数が型の上限を超えて黙って切られるもの。
     新しい型（steps・matrix・cycle・funnel・bars・pyramid・tree）は描く関数そのものを
     保存せずに走らせて測る（描く側は収まらなければ止まるので、ここで先に知らせる）
  2. list 型の「|」 … list は段を分けない。原稿の意図（ラベル|説明）と絵がずれる
  3. 英語だけの文字列 … 画像に英語を入れない決まり（CLAUDE.md 画像ルール）。
     AI/SEO などの略語と製品名は除く
  4. 画像ファイルの欠け … フロントマターの eyecatch / diagrams にあるのに無いもの
  5. bars の数字 … 本文・表に同じ値で無い数字（描く側は描かずに止める）
  6. 新しい記事（make_diagram.DIAGRAM_RULES_FROM 以降）… 同じ型の重なり・宣言した図の置き忘れ

    python scripts/image_check.py              # 直近7日に描いた・書いた記事
    python scripts/image_check.py --days 30
    python scripts/image_check.py --all        # 全記事
    python scripts/image_check.py <slug> ...   # 指定の記事

終了コード: 見つかっても0（印 IMAGE_OK= で判定）。フォントが無く測れないときだけ1。
"""
import argparse
import functools
import re
import sys
import time
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_diagram as MD  # noqa: E402
import make_eyecatch as ME  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "articles"
SITE = ROOT / "site"

# 同じ大きさのフォントを何千回も読み直すと全記事で数分かかる。読み込みだけを使い回す
MD.font = functools.lru_cache(maxsize=None)(MD.font)
ME.font = functools.lru_cache(maxsize=None)(ME.font)

# 画像に出してよい英字。略語は短く読み手が知っているもの、製品・制度名は訳すと別物になる
ALLOWED_WORDS = {
    "ai", "aio", "seo", "meo", "llmo", "lp", "gbp", "url",
    "google", "chatgpt", "gemini", "claude", "perplexity", "copilot", "bing", "yahoo",
    "instagram", "facebook", "youtube", "tiktok", "twitter", "threads", "line", "meta",
    "notion", "slack", "excel", "canva", "freee", "kintone", "shopify", "wordpress",
    "iphone", "android", "suumo", "athome", "jgrants", "jcip",
    "saas", "btob", "btoc", "faq", "faqpage",
}
# 語ごとには許さず、この並びのときだけ許す名前（「SECURITY」単独は英語の見出しになる）
ALLOWED_PHRASES = ["SECURITY ACTION", "Search Console", "AI Overview"]
# 枠の判定は fit_font の目標幅（右に余白を残す幅）ではなく、実際の箱の端で行う。
# 目標幅を超えても余白に食い込むだけで、見た目は崩れていない（実物を見て確かめた）
EDGE_PX = 6              # 箱の端からこれより近い文字は「端に付いている」と見なす
FLOW_BOX_TOP = 70        # 番号の丸の下端（箱の上端から）。これより上に文字が来ると丸に重なる
FLOW_BOX_H = 200
SLACK_PX = 4             # 文字の高さはフォントサイズより少し小さい。その分は重なりと数えない


def _draw():
    """描く側と同じ倍率で文字の幅を測る下地（1倍で測ると、描いた幅と少しずれる）"""
    return MD.Pen()


def frontmatter(path):
    m = re.match(r"^---\s*\n(.*?)\n---", path.read_text(encoding="utf-8-sig"), re.S)
    if not m:
        return None
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None


# 頭にこれが付いた指摘は知らせるだけで、IMAGE_OK を no にしない。
# list の「|」は描画時に「：」へ置き換わるので絵は崩れない（2026-10-04 に実物で確認）
NOTE = "注意 "


def english_only(text):
    """「|」で段に分けた各段のうち、英字だけで書かれ、許可外の4文字以上の語を含むものの語を返す。
    名前は段をまたいで書かれることがある（「SECURITY|ACTION」）ので、分ける前に外す"""
    s = str(text)
    for ph in ALLOWED_PHRASES:
        s = re.sub(r"[\s|]+".join(map(re.escape, ph.split())), " ", s, flags=re.I)
    bad = []
    for seg in s.split("|"):
        seg = seg.strip()
        if not seg or any(ord(c) >= 128 for c in seg):
            continue
        bad += [w for w in re.findall(r"[A-Za-z]+", seg)
                if len(w) > 3 and w.lower() not in ALLOWED_WORDS]
    return bad


def _too_wide(d, text, width, minimum):
    return d.textlength(text, font=MD.font(minimum)) > width


def diagram_problems(dg, d=None, body=None):
    """図解1枚の宣言から、崩れの原因を [文] で返す。描いたときと同じ計算で測る。
    body（記事の本文）があれば bars の数字も本文と突き合わせる"""
    d = d or _draw()
    out = []
    name = dg.get("name", "?")
    dtype = dg.get("type", "flow")
    title = str(dg.get("title", ""))
    items = [str(x) for x in (dg.get("items") or [])]
    W = MD.W

    if dtype in MD.TYPES and dtype not in MD.OLD_TYPES:
        # 新しい型は、描く関数を保存せずに走らせる（宣言の誤り・本文に無い数字・収まらない文字）
        out += MD.render("zz-image-check", dg, body=body, save=False)
        for text in MD.all_texts(dg):
            bad = english_only(text)
            if bad:
                out.append(f"{name}: 英語だけの文字列があります（{'・'.join(bad)}）… {text[:30]}")
        return out

    if _too_wide(d, title, W - 68 - 20, 20):
        out.append(f"{name}: 題が長すぎて枠の端に届くか、はみ出します（{len(title)}字）")

    if dtype == "list":
        if not 3 <= len(items) <= 6:
            out.append(f"{name}: list 型は3〜6項目です（{len(items)}項目。7個目以降は描かれません）")
        for it in items:
            if "|" in it:
                out.append(f"{NOTE}{name}: list 型の項目に「|」があります（段は分かれず「：」で描かれる）… {it[:30]}")
            if _too_wide(d, it.replace("|", "："), W - 60 - 140 - EDGE_PX, 16):
                out.append(f"{name}: 項目が長すぎて枠の端に届くか、はみ出します … {it[:30]}")
    elif dtype == "flow":
        if not 2 <= len(items) <= 5:
            out.append(f"{name}: flow 型は2〜5項目です（{len(items)}項目。6個目以降は描かれません）")
        n = min(max(len(items), 1), 5)
        bw = (W - 60 * 2 - 34 * (n - 1)) // n
        for it in items[:5]:
            lines, tf = MD.flow_lines(d, it, bw - 28)
            k = len(lines)
            lh = MD.flow_lh(lines, tf)
            half = (k - 1) * lh / 2 + tf.size / 2
            if 118 - half < FLOW_BOX_TOP - SLACK_PX or 118 + half > FLOW_BOX_H + SLACK_PX:
                out.append(f"{name}: 項目が{k}行に折り返され、箱からはみ出します … {it[:30]}")
    elif dtype == "vs":
        if len(items) != 2:
            out.append(f"{name}: vs 型は左右の2項目です（{len(items)}項目）")
        cw = (W - 120 - 24) // 2
        for col in items[:2]:
            parts = col.split("|")
            if len(parts) < 2:
                out.append(f"{name}: vs 型は「見出し|行1|行2」の形です … {col[:30]}")
            if _too_wide(d, parts[0], cw - EDGE_PX * 2, 16):
                out.append(f"{name}: 見出しが長すぎて枠の端に届くか、はみ出します … {parts[0][:30]}")
            for row in parts[1:]:
                if _too_wide(d, row, cw - 64 - EDGE_PX, 16):
                    out.append(f"{name}: 行が長すぎて枠の端に届くか、はみ出します … {row[:30]}")
    else:
        out.append(f"{name}: 未対応の型 {dtype}（{' / '.join(MD.TYPES)}）")

    for text in [title] + items:
        bad = english_only(text)
        if bad:
            out.append(f"{name}: 英語だけの文字列があります（{'・'.join(bad)}）… {text[:30]}")
    return out


def eyecatch_problems(title, d=None):
    # アイキャッチは等倍で描く（記事の頭の最大の画像なので重くしない）。測るのも等倍の下地で
    d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    lines, tf = ME.wrap_title(d, str(title), ME.W - 160)
    if any(d.textlength(x, font=tf) > ME.W - 80 - EDGE_PX for x in lines):
        return [f"eyecatch: 題が最小の文字でも2行に収まりません（{len(str(title))}字）"]
    return []


def article_problems(meta, slug, site_root=SITE, body=None):
    """1記事の画像の崩れ・欠けを返す。eyecatch は自前で描いた .png だけ測る（写真は測れない）"""
    d = _draw()
    out = []
    if body is None:
        body = MD.article_body(slug)
    eye = meta.get("eyecatch")
    if eye:
        if not (site_root / str(eye).lstrip("/")).exists():
            out.append(f"画像がありません: {eye}")
        elif str(eye).endswith(f"/{slug}/eyecatch.png") and meta.get("title"):
            out += eyecatch_problems(meta["title"], d)
    for dg in meta.get("diagrams") or []:
        if not isinstance(dg, dict):
            out.append("diagrams の書き方が壊れています")
            continue
        f = site_root / "images" / slug / f"{dg.get('name', '')}.png"
        if not f.exists():
            out.append(f"画像がありません: /images/{slug}/{dg.get('name')}.png")
        out += diagram_problems(dg, d, body=body)
    # 新しい記事だけの決まり（同じ型の重なり・宣言した図の置き忘れ）。描く側・ビルドと同じ判定を使う
    out += [p for p in MD.article_problems(meta, body, site_root, slug)
            if p.startswith(("同じ型の図", "宣言した図を本文に"))]
    return out


def targets(slugs, days, everything):
    paths = sorted(ARTICLES.glob("*.md"))
    if slugs:
        return [p for p in paths if p.stem in set(slugs)]
    if everything:
        return paths
    since = time.time() - days * 86400

    def recent(p):
        if p.stat().st_mtime >= since:
            return True
        img = SITE / "images" / p.stem
        return img.is_dir() and any(f.stat().st_mtime >= since for f in img.glob("*.png"))
    return [p for p in paths if recent(p)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--notes", action="store_true", help="崩れない注意（list の「|」）も一覧に出す")
    a = ap.parse_args()

    try:
        MD.font(16)
    except SystemExit as e:
        print(f"  測れません: {e}")
        print("IMAGE_OK=unknown")
        return 1

    paths = targets(a.slugs, a.days, a.all)
    scope = "指定の記事" if a.slugs else ("全記事" if a.all else f"直近{a.days}日")
    print(f"■ 画像の崩れ（{scope}・{len(paths)}本）")
    print("  OCRは使いません。描いたときと同じ計算で、元の文字列が枠に収まるかを測ります")
    found = notes = 0
    for p in paths:
        meta = frontmatter(p)
        if meta is None:
            continue
        probs = article_problems(meta, p.stem)
        ng = [s for s in probs if not s.startswith(NOTE)]
        notes += len(probs) - len(ng)
        shown = probs if a.notes else ng
        if shown:
            found += len(ng)
            print(f"  {'×' if ng else '・'} {p.stem}")
            for s in shown:
                print(f"      {s}")
    print()
    if notes:
        print(f"  注意 {notes}件（list 型の「|」。絵は崩れない。--notes で一覧）")
    if not found:
        print(f"  {len(paths)}本とも崩れ・欠けは見つかりませんでした")
        print("IMAGE_OK=yes")
        return 0
    print(f"  崩れ・欠け {found}件。原稿の diagrams を直して "
          "python scripts/make_images.py <slug> で描き直してください")
    print("IMAGE_OK=no")
    return 0


if __name__ == "__main__":
    sys.exit(main())
