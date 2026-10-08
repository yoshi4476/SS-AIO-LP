# -*- coding: utf-8 -*-
"""検索から外す記事（noindex）を1か所で決め、4つの描き方と週次の道具が同じに扱う。

**なぜ要るか**: 2026-10-08 の調査で、担当領域の外の記事が検索に出ていた。コーポレートでは銀行の通帳・
ゆうちょの記帳の5本がサイトの表示の約4割（28日・page 次元 1,576/4,097回・問い合わせ0）、AI集客ラボでは
整骨院の保険・クリニックの建築、補助金では補助金でない電子申請の記事。URL を消すと 404 になり、
張られたリンクの評価も失う。そこで URL は残し（200 のまま）、検索の索引と自社の導線から外す。

記事のフロントマターに書く（理由と日付も残す。いつ・なぜ外したかを後から読めるように）:
  noindex: true
  noindex_reason: 担当領域の外（銀行の通帳の記帳。経理の外注を考える読者ではない）
  noindex_date: 2026-10-08

効き方（AI集客ラボ build.py・コーポレート nextjs-json・補助金 external-html・CONFLUX external-md で同じ）:
  - head に <meta name="robots" content="noindex,follow">。nextjs-json は記事の JSON の noindex を先方の
    記事ページが generateMetadata で robots にする（nextjs_app が blog.ts と記事ページに足す）。
    external-md はフロントマターの robots と noindex（先方の雛形が head に出す）
  - sitemap.xml・llms.txt・一覧・関連記事・前後の記事・テーマ・業種ハブ・まとめのページ（比較表・用語集・FAQ の集約）に出さない
  - 他の記事からの内部リンクは、リンクの記法だけ外して文は残す（unlink）。描く・配信するときにも外す
    （週次の道具がリンクを戻しても、公開されるページには出ない）
  - 週次の自動の直し（書き直し・統合・取り下げ・押し上げ・内部リンク・CTA・一次情報の引用・訳・動画・SNS）が触らない

  python scripts/noindex.py                    # 外している記事の一覧
  python scripts/noindex.py --links            # 外した記事へまだ張られている内部リンク（原稿）
  python scripts/noindex.py --unlink --write   # それを外す（文は残す。auto_review.guard で検算してから書く）
"""
import functools
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "articles"
sys.path.insert(0, str(ROOT / "scripts"))

FIELD = "noindex"
ROBOTS = "noindex,follow"
_ON = re.compile(r"^noindex:\s*(?:true|yes|1)\s*$", re.M | re.I)
_ROBOTS_RX = re.compile(r'<meta\s+name="robots"\s+content="[^"]*"\s*/?>\s*', re.I)
# 画像（![alt](…)）は対象にしない。リンクの文字に ] を含む書き方はこのサイトの原稿に無い
_MD_LINK = re.compile(r"(?<!!)\[([^\]\n]+)\]\(([^)\s]+)\)")
_HTML_LINK = re.compile(r'<a\b[^>]*?\bhref="([^"]+)"[^>]*>(.*?)</a>', re.S)


def on(meta):
    """フロントマター（dict）が noindex か"""
    v = (meta or {}).get(FIELD)
    return v is True or str(v).strip().lower() in ("true", "yes", "1")


def hidden_fm(fm_text):
    """フロントマターの文字列（--- の間）が noindex か。正規表現でフロントマターを読む道具用"""
    return bool(_ON.search(fm_text or ""))


def _front(text):
    m = re.match(r"^﻿?---\s*\n(.*?)\n---", text or "", re.S)
    return m.group(1) if m else ""


def hidden_text(text):
    """原稿の全文（フロントマターつき）が noindex か"""
    return hidden_fm(_front(text))


@functools.lru_cache(maxsize=1)
def slugs():
    """noindex の記事の slug（articles/ 直下）"""
    out = set()
    for p in ARTICLES.glob("*.md"):
        if p.name.startswith("_"):
            continue
        try:
            if hidden_text(p.read_text(encoding="utf-8-sig", errors="replace")):
                out.add(p.stem)
        except OSError:
            continue
    return frozenset(out)


def reset():
    """原稿を書き換えた後に読み直す"""
    slugs.cache_clear()
    _domains.cache_clear()


def is_hidden(slug):
    return bool(slug) and str(slug) in slugs()


def drop(items, key="slug"):
    """一覧から noindex の記事を除く（文字列の一覧でも、{key: slug} の一覧でも）"""
    hid = slugs()
    return [x for x in items or [] if (x if isinstance(x, str) else (x or {}).get(key)) not in hid]


def live(slug_set):
    """配信先にある記事の集合から noindex を除く（まとめのページ・関連の材料）"""
    return set(slug_set or ()) - set(slugs())


# ── head の robots ─────────────────────────────────
def robots_meta():
    return f'<meta name="robots" content="{ROBOTS}">'


def set_robots(page):
    """robots の meta を noindex,follow の1つにする（見え方の指定 max-* は noindex には意味が無いので外す）"""
    if "</head>" not in page:
        return page
    found = list(_ROBOTS_RX.finditer(page))
    if not found:
        return page.replace("</head>", robots_meta() + "\n</head>", 1)
    for m in reversed(found[1:]):
        page = page[:m.start()] + page[m.end():]
    m = found[0]
    tail = page[m.start():m.end()][len(page[m.start():m.end()].rstrip()):]
    return page[:m.start()] + robots_meta() + tail + page[m.end():]


def page_hidden(html):
    """描いたページが noindex か（配信先の一覧づくり・関連記事選びが読む）"""
    return bool(re.search(r'<meta\s+name="robots"\s+content="[^"]*noindex', html or "", re.I))


def md_front(fm):
    """external-md のフロントマター（先方の雛形が head に robots を出す）"""
    fm = dict(fm)
    fm["robots"] = "noindex, follow"
    fm[FIELD] = True
    return fm


def nextjs_fields(out):
    """nextjs-json の記事 JSON（先方の記事ページが robots にし、一覧・関連・サイトマップから外す）"""
    out = dict(out)
    out[FIELD] = True
    out["robots"] = {"index": False, "follow": True}
    return out


# 先方（Next.js）の記事の読み込み（src/lib/blog.ts）と記事ページ（src/app/blog/[slug]/page.tsx）に、
# noindex の記事を「ページは作る・一覧と関連とサイトマップには出さない・head は noindex」にする数行を足す。
# コーポレートの形（posts = readAll()・getPost・generateStaticParams）だけを扱い、形が違えば何も書かない
_NJ_MARK = "管制塔の scripts/noindex.py"
_NJ_TYPE = "  noindex?: boolean; // 検索から外した記事（{mark}）。ページは作り、一覧・関連・サイトマップには出さない\n"
_NJ_POSTS = ("// 検索から外した記事（noindex）も記事ページは作る（URL を 404 にしない）。一覧・関連・前後・サイトマップは\n"
             "// posts（外した記事を除く）を使う。{mark} が足した行\n"
             "export const allPosts: BlogPost[] = readAll();\n"
             "export const posts: BlogPost[] = allPosts.filter((p) => !p.noindex);")
_NJ_ANY = ("\n\n/** 検索から外した記事も含めて探す（記事ページだけが使う。{mark}） */\n"
           "export function getAnyPost(slug: string) {{\n  return allPosts.find((p) => p.slug === slug);\n}}")
_NJ_ROBOTS = "\n    ...(post.noindex ? { robots: { index: false, follow: true } } : {}),"


def nextjs_app(dest, write=True):
    """(書いたファイル, 問題)。問題が空でなければ何も書いていない（要対応として知らせる）"""
    dest = Path(dest)
    src = dest / "src" if (dest / "src" / "app").is_dir() else dest
    blog, page = src / "lib" / "blog.ts", src / "app" / "blog" / "[slug]" / "page.tsx"
    if not (blog.is_file() and page.is_file()):
        return [], "記事の読み込み（lib/blog.ts）か記事ページ（app/blog/[slug]/page.tsx）が見つかりません"
    b0, p0 = blog.read_text(encoding="utf-8"), page.read_text(encoding="utf-8")
    b, p = b0, p0
    if "allPosts" not in b:
        mark = _NJ_MARK
        t = re.search(r"export type BlogPost = \{.*?\n\};", b, re.S)
        line = "export const posts: BlogPost[] = readAll();"
        g = re.search(r"(export function getPost\(slug: string\) \{\n\s*return posts\.find\(\(p\) => p\.slug === slug\);\n\})", b)
        r = "const base = getPost(slug);"
        if not (t and line in b and g and r in b):
            return [], "lib/blog.ts の形が想定と違います（posts = readAll()・getPost・relatedPosts）"
        b = b[:t.end() - 2] + _NJ_TYPE.format(mark=mark) + b[t.end() - 2:]
        b = b.replace(line, _NJ_POSTS.format(mark=mark), 1)
        b = b.replace(g.group(1), g.group(1) + _NJ_ANY.format(mark=mark), 1)
        b = b.replace(r, "const base = getAnyPost(slug);", 1)
    if "getAnyPost" not in p:
        imp = re.search(r'import \{([^}]*)\} from "@/lib/blog";', p)
        gen = "return posts.map((p) => ({ slug: p.slug }));"
        meta = re.search(r"export async function generateMetadata\([^)]*\)[^{]*\{.*?\n  return \{", p, re.S)
        if not (imp and re.search(r"\bposts,", imp.group(1)) and re.search(r"\bgetPost,", imp.group(1))
                and gen in p and meta):
            return [], "記事ページ（app/blog/[slug]/page.tsx）の形が想定と違います"
        names = re.sub(r"\bposts,", "allPosts,", imp.group(1), count=1)
        names = re.sub(r"\bgetPost,", "getAnyPost,", names, count=1)
        p = p[:imp.start(1)] + names + p[imp.end(1):]
        p = p.replace(gen, "return allPosts.map((p) => ({ slug: p.slug }));", 1)
        p = re.sub(r"\bgetPost\(slug\)", "getAnyPost(slug)", p)
        meta = re.search(r"export async function generateMetadata\([^)]*\)[^{]*\{.*?\n  return \{", p, re.S)
        p = p[:meta.end()] + _NJ_ROBOTS + p[meta.end():]
    written = []
    for f, old, new in ((blog, b0, b), (page, p0, p)):
        if new != old:
            if write:
                f.write_text(new, encoding="utf-8", newline="\n")
            written.append(f)
    return written, ""


# ── 配信先の sitemap.xml・llms.txt から外す ──────────────────
def prune_sitemap(text, hidden=None):
    """sitemap.xml から noindex の記事の <url> を外す"""
    hid = set(slugs() if hidden is None else hidden)

    def keep(m):
        loc = re.search(r"<loc>\s*([^<]+?)\s*</loc>", m.group(0))
        return "" if loc and target_slug(loc.group(1)) in hid else m.group(0)
    return re.sub(r"[ \t]*<url>.*?</url>[ \t]*\n?", keep, text or "", flags=re.S)


def prune_llms(text, hidden=None):
    """llms.txt から noindex の記事の行（- [題](URL): …）を外す"""
    hid = set(slugs() if hidden is None else hidden)
    out = []
    for ln in (text or "").split("\n"):
        m = re.match(r"^\s*-\s*\[[^\]\n]*\]\(([^)\s]+)\)", ln)
        if m and target_slug(m.group(1)) in hid:
            continue
        out.append(ln)
    return "\n".join(out)


# ── 内部リンクを外す（文は残す）──────────────────────────
@functools.lru_cache(maxsize=1)
def _domains():
    try:
        import sites as S
        return frozenset(c["domain"].lower() for c in S.load_all().values() if c.get("domain"))
    except Exception:
        return frozenset()


def target_slug(url):
    """内部リンクの行き先の slug（自社のドメインか / で始まるものだけ。画像・外部は空）"""
    u = (url or "").strip()
    if u.startswith("//"):
        return ""
    if u.startswith("http://") or u.startswith("https://"):
        host = urlsplit(u).netloc.lower().split(":")[0]
        if host.startswith("www."):
            host = host[4:]
        if host not in _domains():
            return ""
    elif not u.startswith("/"):
        return ""
    segs = [s for s in urlsplit(u).path.split("/") if s]
    if not segs or "." in segs[-1]:
        return ""
    return segs[-1]


def unlink(text, hidden=None, kinds=("md", "html")):
    """noindex の記事への内部リンクを外し、リンクの文字は文として残す。(新しい本文, 外した数)"""
    hid = set(slugs() if hidden is None else hidden)
    if not hid or not text:
        return text, 0
    n = 0

    def md(m):
        nonlocal n
        if target_slug(m.group(2)) in hid:
            n += 1
            return m.group(1)
        return m.group(0)

    def html(m):
        nonlocal n
        if target_slug(m.group(1)) in hid:
            n += 1
            return m.group(2)
        return m.group(0)
    if "md" in kinds:
        text = _MD_LINK.sub(md, text)
    if "html" in kinds:
        text = _HTML_LINK.sub(html, text)
    return text, n


def links(hidden=None):
    """原稿で、noindex の記事へまだ張られている内部リンク。[(送り元の slug, 行き先の slug)]"""
    hid = set(slugs() if hidden is None else hidden)
    out = []
    for p in sorted(ARTICLES.glob("*.md")):
        if p.name.startswith("_"):
            continue
        t = p.read_text(encoding="utf-8-sig", errors="replace")
        for m in _MD_LINK.finditer(t):
            s = target_slug(m.group(2))
            if s in hid:
                out.append((p.stem, s))
        for m in _HTML_LINK.finditer(t):
            s = target_slug(m.group(1))
            if s in hid:
                out.append((p.stem, s))
    return out


def unlink_all(write=False, hidden=None):
    """原稿の全記事から noindex の記事への内部リンクを外す。auto_review.guard（本文の減り・タグ・導線・見出し）を
    通った記事だけ書く。[(slug, 外した数, 見送りの理由)]"""
    import auto_review as AR
    out = []
    for p in sorted(ARTICLES.glob("*.md")):
        if p.name.startswith("_"):
            continue
        raw = p.read_bytes().decode("utf-8")
        new, n = unlink(raw, hidden)
        if not n:
            continue
        cut = lambda s: re.sub(r"^---\s*\n.*?\n---\s*\n", "", s, count=1, flags=re.S)
        # HTML の <a> を外すとタグの数は変わる（外すのが目的）。検算はそれを外した後の本文を「前」として、
        # Markdown のリンクの記法だけが減ったかを見る。文字は残るので、減るのは記法の分だけ
        body_b, body_a = cut(unlink(raw, hidden, kinds=("html",))[0]), cut(new)
        why = AR.guard(_front(raw), body_b, body_a, len(body_b) - len(body_a))
        # 内部リンク3本の下限は、外した記事へのリンクを数えない（もともと行き先が検索に出ない）
        if why == "内部リンクが3本を割る":
            why = ""
        out.append((p.stem, n, why))
        if write and not why:
            p.write_bytes(new.encode("utf-8"))
    return out


def main():
    a = sys.argv[1:]
    hid = sorted(slugs())
    if "--links" in a:
        got = links()
        for src, dst in got:
            print(f"  {src} → {dst}")
        print(f"NOINDEX_LINKS={len(got)}")
        return 0
    if "--unlink" in a:
        rows = unlink_all(write="--write" in a)
        for slug, n, why in rows:
            print(f"  {'見送り' if why else ('外した' if '--write' in a else '外す')} {slug}: {n}本"
                  + (f"（{why}）" if why else ""))
        print(f"NOINDEX_UNLINK={sum(n for _, n, why in rows if not why)}（{len(rows)}記事）")
        return 0
    import sites as S
    by = {}
    for s in hid:
        m = re.search(r"^category:\s*(\S+)", _front((ARTICLES / f"{s}.md").read_text(encoding="utf-8-sig")), re.M)
        by.setdefault(S.find_category_owner(m.group(1)) if m else "?", []).append(s)
    for site, ss in sorted(by.items()):
        print(f"■ {site}: {len(ss)}本")
        for s in ss:
            print(f"  {s}")
    print(f"NOINDEX={len(hid)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
