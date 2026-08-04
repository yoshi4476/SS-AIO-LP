# -*- coding: utf-8 -*-
"""記事を対象サイトへ配信する（多サイト対応の出口）

使い方:
    python scripts/publish.py --site corporate --slug tenpo-saiyou-teichaku
    python scripts/publish.py --site corporate --slug xxx --push   # 対象リポジトリへpushまで行う

記事Markdownは常に本リポジトリの articles/ に置く（品質ゲート・カニバリ検査を1か所で回すため）。
本スクリプトは、そのMarkdownをサイトごとの形式へ変換して対象リポジトリに書き込む。

サイト種別:
  self-static  … 本リポジトリの静的サイト。build.py が担当するため何もしない
  nextjs-json  … Next.jsサイト。src/content/blog/<slug>.json を書き出す
  external-md  … 別リポジトリの静的サイト。Markdownをそのまま置く

対象リポジトリへの書き込みには SITE_PUSH_TOKEN（repo権限のPAT）が必要。
未設定ならローカルのクローンに書き込むだけで止まる（--push は失敗する）。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import md2html  # noqa: E402
import sites as sites_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / ".publish-work"  # 対象リポジトリのクローン置き場（.gitignore対象）


def run(args, cwd=None, check=True):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore")
    if check and r.returncode != 0:
        raise SystemExit(f"コマンド失敗: {' '.join(args)}\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def try_run(args, cwd=None):
    """成否だけ知りたいとき用（run は標準出力を返すため成否の判定に使えない）"""
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore")
    return r.returncode == 0


def parse_article(path: Path):
    t = path.read_text(encoding="utf-8-sig")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
    if not m:
        raise SystemExit(f"フロントマターがありません: {path}")
    return yaml.safe_load(m.group(1)), m.group(2)


def ensure_clone(cfg, token):
    """対象リポジトリをクローン（既にあれば最新化）して作業パスを返す"""
    WORK.mkdir(exist_ok=True)
    dest = WORK / cfg["id"]
    url = f"https://github.com/{cfg['repo']}.git"
    auth_url = f"https://x-access-token:{token}@github.com/{cfg['repo']}.git" if token else url
    if not (dest / ".git").exists():
        shutil.rmtree(dest, ignore_errors=True)
        run(["git", "clone", "--depth", "1", "--branch", cfg["branch"], auth_url, str(dest)])
    else:
        run(["git", "fetch", "--depth", "1", auth_url, cfg["branch"]], cwd=dest)
        run(["git", "reset", "--hard", "FETCH_HEAD"], cwd=dest)
    return dest


def image_prefix(cfg):
    """配信先での画像の公開パス。images_dir から公開URLを導く。

    例: images_dir="public/images/blog" → 公開パスは "/images/blog"
    Next.jsは public/ 配下をルートとして配信するため、public/ を取り除く。
    """
    d = (cfg.get("images_dir") or "").strip("/")
    for head in ("public/", "static/", "site/"):
        if d.startswith(head):
            d = d[len(head):]
            break
    return "/" + d if d else "/images"


def write_nextjs_json(cfg, dest: Path, meta, body):
    """Next.jsサイト用: 本文HTML込みのJSONを書き出す"""
    html, _ = md2html.convert(body)
    faq = md2html.extract_faq(body)

    # 変換がどこかで止まると、Markdownのまま配信先に届いて段落の無い記事になる。
    # 配信自体は止めない (欠測より読みにくい記事の方がまし) が、必ず気付けるようにする。
    left = md2html.raw_markdown_left(html)
    if left:
        print(f"  [警告] {meta['slug']}: Markdownが変換されずに残っています — {' / '.join(left)}")

    # 記事Markdownは自リポジトリの慣習（/images/<slug>/…）で書かれているため、
    # 配信先の実際の画像置き場に合わせてパスを書き換える。
    # これをしないと配信先で画像が全て404になる。
    prefix = image_prefix(cfg)
    src_path, dst_path = f"/images/{meta['slug']}/", f"{prefix}/{meta['slug']}/"
    if src_path != dst_path:
        html = html.replace(src_path, dst_path)
        if meta.get("eyecatch"):
            meta = {**meta, "eyecatch": str(meta["eyecatch"]).replace(src_path, dst_path)}

    out = {
        "slug": meta["slug"],
        "title": meta["title"],
        "description": meta["description"],
        "date": str(meta["date"]),
        "dateModified": str(meta.get("modified") or meta.get("dateModified") or meta["date"]),
        "category": meta["category"],
        "categoryName": sites_mod.category_name(cfg, meta["category"]),
        "readingMinutes": md2html.reading_minutes(html),
        "faq": faq,
        "html": html,
    }
    if meta.get("eyecatch"):
        out["eyecatch"] = meta["eyecatch"]
    target = dest / cfg["content_dir"] / f"{meta['slug']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Next.jsサイトでも sitemap.xml / llms.txt への追記が要る。呼んでいなかったため、
    # 公開した記事がAIクローラー向けの案内に1本も載っていなかった
    written = [target] + _update_external_index(dest, cfg, meta)

    # 画像も対象リポジトリへ複製（本文が /images/... を参照するため）
    img_src = ROOT / "site" / "images" / meta["slug"]
    if cfg.get("images_dir") and img_src.exists():
        img_dest = dest / cfg["images_dir"] / meta["slug"]
        shutil.rmtree(img_dest, ignore_errors=True)
        shutil.copytree(img_src, img_dest)
        written.append(img_dest)
    return written, len(md2html.plain_text(html))


def write_external_md(cfg, dest: Path, meta, body, src: Path):
    """別リポジトリの静的サイト用: Markdownをそのまま置く"""
    target = dest / cfg["content_dir"] / f"{meta['slug']}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    return [target], len(md2html.plain_text(md2html.convert(body)[0]))


JP_ERA = "%Y年%-m月%-d日"


def _jp_date(iso):
    y, m, d = str(iso).split("-")
    return f"{int(y)}年{int(m)}月{int(d)}日"


def _push_token():
    """配信用PATを取得する。GitHub Actionsは環境変数、手元は .env に置いている。

    環境変数だけを見ていたため、手元から publish.py を直接実行すると必ず
    「未設定」で止まっていた。両方を見て、先に見つかった方を使う。
    """
    v = os.environ.get("SITE_PUSH_TOKEN", "")
    if not v:
        env = ROOT / ".env"
        if env.is_file():
            for line in env.read_text(encoding="utf-8-sig").splitlines():
                if line.startswith("SITE_PUSH_TOKEN="):
                    v = line.split("=", 1)[1]
                    break
    return v.replace("﻿", "").strip().strip('"').strip("'")


def check_contract(cfg, dest: Path, meta):
    """配信先のビルドが壊れない形かを、書き込む前に確かめる。

    相手のビルドスクリプトは、こちらが送る値を辞書のキーとして使うことがある。
    実際に補助金サイトでは、カテゴリ表示名が1文字違うだけで KeyError になり、
    そのサイトの記事31本すべてが公開されなくなった。事前に突き合わせて止める。
    """
    cat_label = cfg["categories"].get(meta["category"], meta["category"])

    # 相手のビルドスクリプトを読み解くのは壊れやすい（実装が変わると検査が効かなくなる）。
    # 既に公開されている記事が実際に使っている表記と突き合わせる方が確実で、
    # 相手の実装が変わっても追従できる。
    blog = dest / "blog"
    if not blog.is_dir():
        return True
    used = {}
    for d in blog.iterdir():
        idx = d / "index.html"
        if not d.is_dir() or not idx.is_file() or d.name == meta["slug"]:
            continue
        m = re.search(r'<span class="cat">(.*?)</span>', idx.read_text(encoding="utf-8", errors="ignore"))
        if m:
            used[m.group(1).strip()] = used.get(m.group(1).strip(), 0) + 1
    # 1本だけ違う表記の記事があっても、それを正解と認めない。
    # 過去に取り違えた記事が1本残っているだけで検査が素通りしてしまうため、
    # 「定着している表記」だけを許可する（全体の1割以上、かつ2本以上）。
    total = sum(used.values())
    established = {k: v for k, v in used.items() if v >= max(2, total * 0.1)}
    if established and cat_label not in established:
        top = sorted(used.items(), key=lambda x: -x[1])
        raise SystemExit(
            f"配信を中止します。カテゴリ表示名『{cat_label}』は配信先で使われていません。\n"
            f"  既存記事が使っている表記: {', '.join(f'{k}({v}本)' for k, v in top)}\n"
            "  表記が違うと相手のビルドが落ち、そのサイトの記事が全て公開されなくなった実績があります。\n"
            f"  対処: sites/{cfg['id']}.json の categories の表示名を上のどれかに合わせること")
    return True


def write_external_html(cfg, dest: Path, meta, body, src: Path):
    """別リポジトリの静的サイト用: 相手のテンプレートに流し込んでHTMLを生成する。

    Markdownを置くだけでは相手側にHTML化の仕組みがなく、記事が公開されないため
    ここで完成したページを作る。テンプレートは相手リポジトリのものを使うので、
    デザイン・構造は向こうの既存記事と揃う。
    """
    check_contract(cfg, dest, meta)

    tpl_path = dest / cfg["template"]
    if not tpl_path.exists():
        raise SystemExit(f"テンプレートが見つかりません: {cfg['template']}（{cfg['repo']}）")
    tpl = tpl_path.read_text(encoding="utf-8")

    html, _ = md2html.convert(body)
    # FAQはテンプレート側が専用セクションを持つので、本文からは先に取り除く
    # （目次を作る前に消さないと、存在しない見出しへのリンクが目次に残る）
    html = re.sub(r"<h2[^>]*>\s*よくある質問\s*</h2>.*?(?=<h2|$)", "", html, flags=re.S)

    # 目次のアンカーを相手の書式（#sec1, #sec2 …）に合わせる
    heads = [re.sub(r"<[^>]+>", "", h).strip()
             for h in re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.S)]

    def _renumber(m, c=[0]):
        c[0] += 1
        return f'<h2 id="sec{c[0]}">'

    html = re.sub(r"<h2[^>]*>", _renumber, html)
    toc = "".join(f'<li><a href="#sec{i}">{h}</a></li>' for i, h in enumerate(heads, 1))

    faqs = meta.get("faq") or []
    faq_html = "\n".join(
        f'    <details>\n      <summary>{f["q"]}</summary>\n'
        f'      <div class="a">{f["a"]}</div>\n    </details>' for f in faqs)
    faq_jsonld = ",\n".join(
        '      { "@type": "Question", "name": %s, "acceptedAnswer": '
        '{ "@type": "Answer", "text": %s } }'
        % (json.dumps(f["q"], ensure_ascii=False), json.dumps(f["a"], ensure_ascii=False))
        for f in faqs)

    related = "\n".join(f'<li><a href="{u}">{t}</a></li>'
                        for t, u in _recent_articles(dest, cfg, meta["slug"], 3))

    plain = md2html.plain_text(html)
    lead = (re.search(r"<p[^>]*>(.*?)</p>", html, re.S) or [None, ""])[1]
    target_txt = (re.search(r'class="target-reader">(.*?)</div>', body, re.S)
                  or [None, cfg.get("audience", "")])[1]
    # テンプレートが「この記事は<b>◯◯</b>向けです」の形で囲むため、
    # 原稿側の「この記事は…向けです。」から中身だけを取り出す（二重表記を避ける）
    target_txt = re.sub(r"<[^>]+>", "", target_txt).strip()
    target_txt = re.sub(r"^この記事は[、,]?\s*", "", target_txt)
    target_txt = re.sub(r"(の方)?向けです[。.]?\s*$", "", target_txt)

    vals = {
        "TITLE": meta["title"],
        "TITLE_SHORT": meta["title"][:28],
        "DESCRIPTION": meta["description"],
        "SLUG": meta["slug"],
        "CATEGORY": cfg["categories"].get(meta["category"], meta["category"]),
        "DATE_ISO": str(meta["date"]),
        "DATE_JP": _jp_date(meta["date"]),
        "DATE_YM": f"{str(meta['date'])[:4]}年{int(str(meta['date'])[5:7])}月",
        "READ_MIN": str(max(3, round(len(plain) / 600))),
        "LEAD_DANGEN": re.sub(r"<[^>]+>", "", lead).strip(),
        "TARGET": target_txt,
        "BODY": html,
        "TOC_ITEMS": toc,
        "FAQ_HTML": faq_html,
        "FAQ_JSONLD": faq_jsonld,
        "RELATED_LINKS": related,
        "CTA_TITLE": cfg.get("cta_title", "補助金が使えるか、無料で確認しませんか"),
        "CTA_DESC": cfg.get("cta_desc",
                            "要件の確認から申請書類の準備まで、はじめての方でも進められるようご案内します。"),
    }
    out = tpl
    for k, v in vals.items():
        out = out.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{([A-Z_]+)\}\}", out)
    if left:
        raise SystemExit(f"テンプレートの未置換タグが残っています: {sorted(set(left))}")

    # 記事の内容に合う写真を在庫から選び、一覧カードとOGPに当てる。
    # 配信先の一覧は在庫写真を順番に使い回しており、中身と絵が合わないため。
    thumb_url = None
    try:
        import pick_photo
        lib = dest / "assets" / "img"
        name, src_img, sc = pick_photo.pick(meta["title"], body, lib)
        if src_img:
            t = dest / "images" / "blog" / meta["slug"] / "thumbnail.webp"
            pick_photo.make_thumbnail(src_img, t)
            thumb_url = f"https://{cfg['domain']}/images/blog/{meta['slug']}/thumbnail.webp"
            out = re.sub(r'(<meta property="og:image" content=")[^"]*(")',
                         rf"\g<1>{thumb_url}\g<2>", out)
            print(f"  写真: {name}（一致度 {sc}）→ images/blog/{meta['slug']}/thumbnail.webp")
    except Exception as e:
        print(f"  写真の選定をスキップ: {e}")

    page = dest / "blog" / meta["slug"] / "index.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(out, encoding="utf-8", newline="\n")

    # 原稿も残す（相手側の重複判定・再生成の材料になる）
    md = dest / cfg["content_dir"] / f"{meta['slug']}.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, md)

    written = [page, md] + _update_external_index(dest, cfg, meta)
    thumb_file = dest / "images" / "blog" / meta["slug"] / "thumbnail.webp"
    if thumb_file.is_file():
        written.append(thumb_file)
    return written, len(plain)


def _recent_articles(dest: Path, cfg, exclude_slug, n):
    """相手サイトの既存記事から関連リンク先を選ぶ（新しい順）"""
    out = []
    blog = dest / "blog"
    if not blog.exists():
        return out
    dirs = sorted((d for d in blog.iterdir() if d.is_dir() and d.name != exclude_slug),
                  key=lambda d: d.stat().st_mtime, reverse=True)
    for d in dirs:
        idx = d / "index.html"
        if not idx.exists():
            continue
        m = re.search(r"<h1[^>]*>(.*?)</h1>", idx.read_text(encoding="utf-8"), re.S)
        if m:
            out.append((re.sub(r"<[^>]+>", "", m.group(1)).strip(), f"/blog/{d.name}/"))
        if len(out) >= n:
            break
    return out


def _public_file(dest: Path, name: str):
    """配信先での公開ファイルの実体を探す。

    リポジトリ直下に置くサイトと public/ 配下に置くサイト（Next.js等）がある。
    直下だけを見ていたため、コーポレートでは llms.txt が一度も更新されず、
    公開した記事がAIクローラー向けの案内に1本も載っていなかった。
    """
    for rel in (name, f"public/{name}", f"static/{name}", f"site/{name}"):
        f = dest / rel
        if f.is_file():
            return f
    return None


def _update_external_index(dest: Path, cfg, meta):
    """相手サイトのsitemap.xmlとllms.txtに新記事を足す（検出されないと公開の意味がない）"""
    touched = []
    url = sites_mod.article_url(cfg, meta)
    sm = _public_file(dest, "sitemap.xml")
    if sm:
        t = sm.read_text(encoding="utf-8")
        if url not in t:
            entry = (f"  <url>\n    <loc>{url}</loc>\n"
                     f"    <lastmod>{meta['date']}</lastmod>\n  </url>\n")
            t = t.replace("</urlset>", entry + "</urlset>")
            sm.write_text(t, encoding="utf-8", newline="\n")
            touched.append(sm)
    lt = _public_file(dest, "llms.txt")
    if lt:
        t = lt.read_text(encoding="utf-8")
        if url not in t:
            lt.write_text(t.rstrip("\n") + f"\n- [{meta['title']}]({url}): {meta['description']}\n",
                          encoding="utf-8", newline="\n")
            touched.append(lt)
    return touched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--push", action="store_true", help="対象リポジトリへcommit+pushする")
    args = ap.parse_args()

    cfg = sites_mod.load(args.site)
    src = ROOT / "articles" / f"{args.slug}.md"
    if not src.exists():
        raise SystemExit(f"記事が見つかりません: {src}")
    meta, body = parse_article(src)

    score = meta.get("score") or 0
    if score < 90:
        raise SystemExit(f"公開基準未達のため配信しません: score={score}（90点以上が必要）")
    if meta["category"] not in cfg.get("categories", {}):
        raise SystemExit(f"カテゴリ '{meta['category']}' は {cfg['id']} に定義されていません"
                         f"（候補: {', '.join(cfg.get('categories', {}))}）")

    if cfg["type"] == "self-static":
        print(f"{cfg['id']} は本リポジトリのサイトです。scripts/build.py で公開してください。")
        return

    token = _push_token()
    dest = ensure_clone(cfg, token)

    if cfg["type"] == "nextjs-json":
        written, chars = write_nextjs_json(cfg, dest, meta, body)
    elif cfg["type"] == "external-md":
        written, chars = write_external_md(cfg, dest, meta, body, src)
    elif cfg["type"] == "external-html":
        written, chars = write_external_html(cfg, dest, meta, body, src)
    else:
        raise SystemExit(f"未対応のサイト種別: {cfg['type']}")

    print(f"配信先: {cfg['name']}（{cfg['repo']} / {cfg['branch']}）")
    for w in written:
        print(f"  書き込み: {w.relative_to(dest)}")
    print(f"  本文: {chars:,}字 / score {score}")
    print(f"  公開URL（予定）: {sites_mod.article_url(cfg, meta)}")

    if not args.push:
        print("\n※ --push を付けると対象リポジトリへcommit+pushします（Cloudflareが自動デプロイ）")
        return

    run(["git", "config", "user.name", "AIO Pipeline Bot"], cwd=dest)
    run(["git", "config", "user.email", "noreply@7senses.co.jp"], cwd=dest)
    run(["git", "add", "-A"], cwd=dest)
    if not run(["git", "status", "--porcelain"], cwd=dest):
        print("変更なし — pushをスキップ")
        return
    run(["git", "commit", "-m",
         f"publish: {meta['title']}（score {score} / {date.today().isoformat()}）"], cwd=dest)
    # PATを最優先で使う（CIにはこれしかない）。手元では期限切れ・失効していることがあり、
    # 実際に失効したPATで押せず記事7本が配信されないまま止まっていた。
    # その場合はgitの資格情報にフォールバックする（手元の開発者は認証済みのため）。
    plain_url = f"https://github.com/{cfg['repo']}.git"
    urls = [f"https://x-access-token:{token}@github.com/{cfg['repo']}.git", plain_url] if token else [plain_url]
    for i, u in enumerate(urls):
        if try_run(["git", "push", u, f"HEAD:{cfg['branch']}"], cwd=dest):
            if i:
                print("※ SITE_PUSH_TOKEN では認証できませんでした。PATの再発行が必要です")
            print("push完了。対象サイトのビルドが自動で走ります。")
            return
    raise SystemExit(
        "pushできません。SITE_PUSH_TOKEN（repo権限のPAT）を再発行して .env と\n"
        "  GitHub Secrets の両方を更新してください。記事は未配信のままです")


if __name__ == "__main__":
    main()
