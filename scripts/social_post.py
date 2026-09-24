# -*- coding: utf-8 -*-
"""記事と一次データから、SNSの投稿文を作ってキューに積む。

**APIで自動投稿しない作りにしている。** 理由は3つ。
  1. X は 2026-02-06 に新規開発者向けの無料枠を廃止した。リンク付きの投稿は
     1件 $0.20 かかる（3サイト×2本/日で月36ドル、10社まで増やすと月120ドル）
  2. Facebook / Threads は無料だが、他社のページへ投稿するには Meta の審査
     （Advanced Access）が要り、数週間かかる
  3. そもそも実測で、AI検索での可視性と相関するのは YouTube での言及(0.712)と
     リンクの無いWeb言及(0.656)で、SNSの自動投稿は調査対象にすら入っていない

**投稿文を作って渡す形にすれば、権限も審査も課金も要らない。**
クライアントは自分のアカウントで貼るだけで、こちらは何も預からない。
クライアントが増えても設定は増えない。

    python scripts/social_post.py --article <slug>    # 1本ぶん作る
    python scripts/social_post.py --new               # 未処理の新着をまとめて
    python scripts/social_post.py --pending           # 貼っていない分を見る
    python scripts/social_post.py --done <id>         # 貼ったら消す
    python scripts/social_post.py --md                # 貼り付け用に書き出す
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
QUEUE = ROOT / "data" / "social_queue.jsonl"
OUTMD = ROOT / "automation" / "logs" / "social_queue.md"

# 媒体ごとの字数。Xは全角140字ぶん（280の半分）で、リンクは23字ぶん消費する
LIMITS = {"x": 250, "facebook": 600, "threads": 480, "linkedin": 1200}


def _plain(s):
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = s.replace("**", "").replace("==", "").replace("*", "")
    return re.sub(r"\s+", " ", re.sub(r"[#`|]", "", s)).strip()


def sites():
    import sites as S
    return S.load_all()


def article(slug):
    p = ROOT / "articles" / f"{slug}.md"
    if not p.is_file():
        return None
    t = p.read_text(encoding="utf-8-sig")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
    if not m:
        return None
    fm, body = m.group(1), m.group(2)

    def g(k):
        x = re.search(rf"^{k}:\s*(.+)$", fm, re.M)
        return x.group(1).strip().strip('"') if x else ""

    sc = g("score")
    if not sc.isdigit() or int(sc) < 90:
        return None                      # 公開していない記事は投稿しない
    # 見出しの直下にある1文結論。記事の主張がここに入っている
    leads = []
    heads = [(mm.group(1).strip(), mm.end()) for mm in re.finditer(r"^##\s+(.+)$", body, re.M)]
    for i, (h, pos) in enumerate(heads):
        rest = body[pos:heads[i + 1][1]] if i + 1 < len(heads) else body[pos:pos + 700]
        for ln in rest.split("\n"):
            ln = ln.strip()
            if not ln or ln.startswith(("<", "|", "#", "!", "[")) or re.match(r"^[-*+]\s|^\d+\.\s", ln):
                continue
            s = _plain(ln)
            if re.match(r"^(関連|あわせて|近い論点|前提となる|つまずき|費用の目安|選ぶときの)", s):
                continue
            # 1文結論は太字の1文だが、同じ行に続きの文まで書かれていることがある。
            # 長さで落とすと、いちばん大事な最初の見出しの結論が消える（実際に消えた）
            if len(s) > 120:
                s = re.split(r"(?<=。)", s)[0]
            if 20 <= len(s) <= 120:
                leads.append(s)
            break
    return {"slug": slug, "title": g("title"), "desc": _plain(g("description")),
            "category": g("category"), "leads": leads, "date": g("date")}


def site_of(cat):
    for sid, cfg in sites().items():
        if cat in (cfg.get("categories") or {}):
            return sid, cfg
    return "", {}


def compose(a):
    """媒体ごとの投稿文。**本文に書かれていることしか書かない**（数字を作らない）"""
    sid, cfg = site_of(a["category"])
    # url_prefix は "/blog"（末尾スラッシュなし）か未設定。素直に連結すると
    # /blogai-hojokin-... という壊れたURLになる。ai-lab は未設定で、
    # 記事URLが /<カテゴリ>/<slug>/ の形（CLAUDE.md 3.3）
    pre = (cfg.get("url_prefix") or f'/{a["category"]}').strip("/")
    url = f'https://{cfg.get("domain", "")}/{pre}/{a["slug"]}/'
    tags = cfg.get("x_tags") or []
    tag_line = " ".join("#" + t for t in tags[:2])
    body = a["leads"][0] if a["leads"] else a["desc"]
    points = a["leads"][1:4]

    out = {}
    # X。1画面で読み切れる長さに収める。結論→URL→タグの順
    x = f'{a["title"]}\n\n{body}\n\n{url}'
    if len(x) + len(tag_line) + 2 <= LIMITS["x"]:
        x += f"\n{tag_line}"
    out["x"] = x[:LIMITS["x"]]

    # Facebook / Threads。3つの要点を並べて、読む前に中身が分かる形にする
    lines = [a["title"], "", body]
    if points:
        lines += [""] + [f"・{p}" for p in points]
    lines += ["", url, tag_line]
    fb = "\n".join(l for l in lines if l is not None)
    out["facebook"] = fb[:LIMITS["facebook"]]
    out["threads"] = fb[:LIMITS["threads"]]
    out["linkedin"] = fb[:LIMITS["linkedin"]]
    # note / はてな向けの転載用（長文）。リンクの無いWeb言及（相関0.66）を増やす入口。
    # 本文の1文結論だけを並べ、出典として元記事と社名を必ず末尾に置く
    note = [a["title"], "", body, ""]
    note += [f"■ {p}" for p in a["leads"][1:6]]
    note += ["", "続きと根拠（数字の出典・表・FAQ）は元記事にまとめています。",
             f"元記事: {url}", f"執筆: {cfg.get('name', '')}（セブンセンシズ株式会社）"]
    out["note"] = "\n".join(note)
    # 訪日客向け: 韓国は Naver ブログ、中国は小紅書で調べる。多言語を指示した社で、
    # 訳（数字の検算を通ったもの）があるときだけ作る。新しく訳さない（Claudeを呼ばない）
    try:
        import i18n
        langs = cfg.get("languages") or []
        for lg, key, tag in (("ko", "naver", "#오사카 #일본여행"), ("zh", "xiaohongshu", "#大阪 #日本旅行")):
            p = i18n.OUT / lg / f"{a['slug']}.json"
            if lg not in langs or not p.is_file():
                continue
            d = json.loads(p.read_text(encoding="utf-8"))
            lines2 = [d["title"], "", d.get("lead", ""), ""]
            lines2 += [f"✔ {s['h2']}\n{s['answer']}" for s in d.get("sections", [])[:4]]
            lines2 += ["", f"https://{cfg.get('domain', '')}/{lg}/{pre}/{a['slug']}/", tag]
            out[key] = "\n".join(x for x in lines2 if x is not None)
    except Exception:
        pass
    return {"id": a["slug"], "site": sid, "title": a["title"], "url": url,
            "made": date.today().isoformat(), "posts": out}


def load():
    if not QUEUE.is_file():
        return []
    return [json.loads(l) for l in QUEUE.read_text(encoding="utf-8").splitlines() if l.strip()]


def save(rows):
    QUEUE.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                     encoding="utf-8")


def add(slug, rows):
    if any(r["id"] == slug for r in rows):
        return None
    a = article(slug)
    if not a:
        return None
    item = compose(a)
    rows.append(item)
    return item


def to_md(rows):
    out = ["# SNS 投稿キュー", "",
           "貼ったら `python scripts/social_post.py --done <id>` で消してください。", ""]
    for r in rows:
        out += [f'## {r["title"]}', f'`{r["id"]}` ／ {r["site"]} ／ 作成 {r["made"]}', ""]
        for k in ("x", "facebook", "threads", "linkedin"):
            out += [f'### {k}', "```", r["posts"][k], "```", ""]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--article", help="記事のslug")
    ap.add_argument("--new", action="store_true", help="キューに無い公開済み記事を追加")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--pending", action="store_true")
    ap.add_argument("--done", help="貼り終えたidを消す")
    ap.add_argument("--md", action="store_true", help="貼り付け用に書き出す")
    a = ap.parse_args()

    rows = load()
    if a.done:
        n = len(rows)
        rows = [r for r in rows if r["id"] != a.done]
        save(rows)
        print(f'  {a.done} を消しました（残り {len(rows)}件）' if n != len(rows) else "  見つかりません")
        return 0

    if a.article:
        it = add(a.article, rows)
        save(rows)
        print(f'  積みました: {it["title"]}' if it else "  対象外です（未公開か、記事がありません）")
        if it:
            print()
            print(it["posts"]["x"])
        return 0

    if a.new:
        have = {r["id"] for r in rows}
        arts = sorted((ROOT / "articles").glob("*.md"), key=lambda p: -p.stat().st_mtime)
        n = 0
        for p in arts:
            if p.stem in have or n >= a.limit:
                continue
            if add(p.stem, rows):
                n += 1
        save(rows)
        print(f"  {n}件を積みました（キュー {len(rows)}件）")

    if a.md:
        OUTMD.parent.mkdir(parents=True, exist_ok=True)
        OUTMD.write_text(to_md(rows), encoding="utf-8")
        print(f"  書き出しました: {OUTMD}")

    print(f"■ SNS 投稿キュー {len(rows)}件")
    for r in rows[:12]:
        print(f'   {r["site"]:<10} {r["title"][:40]}')
    if len(rows) > 12:
        print(f"   …ほか {len(rows) - 12}件")
    print("SOCIAL_OK=" + ("no" if len(rows) > 30 else "yes"))
    if len(rows) > 30:
        print("   貼っていない投稿が溜まっています。作っても貼らなければ何も起きません")
    return 0


if __name__ == "__main__":
    sys.exit(main())
