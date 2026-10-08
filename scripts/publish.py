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
  external-md  … 別リポジトリの静的サイト。Markdownを置く（画像・写真・構造化データ・動画・入口も揃える）
  wordpress    … WordPress。REST APIで投稿する（公開可否は先方のmu-pluginが判定）

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
import deliver_files  # noqa: E402
import render_check  # noqa: E402
import site_files  # noqa: E402
import sites as sites_mod  # noqa: E402
import table_charts  # noqa: E402
import noindex  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / ".publish-work"  # 対象リポジトリのクローン置き場（.gitignore対象）


def source_hash(md_path: Path):
    """配信した原稿そのものの指紋。届いたかどうかの判定に使う"""
    import hashlib
    return hashlib.sha1(md_path.read_bytes()).hexdigest()[:12]


def manifest_path(cfg, dest: Path):
    """公開サイトから読める場所に置く。認証なしで照合できるようにするため。

    Next.jsは public/ の中身がそのままURLになる。静的サイトは直下。
    """
    pub = "public" if (cfg.get("images_dir") or "").startswith("public/") else ""
    return dest / pub / "article-manifest.json" if pub else dest / "article-manifest.json"


def stamp_manifest(cfg, dest: Path, meta, src: Path):
    """配信した原稿の指紋を残す。

    ページが在るか・タイトルが合うかだけでは、本文だけ直したときに
    「配信済み」に見える。実際、リード導線を全記事に足したのに
    1本も届いていないことに、後から実物を見るまで気づけなかった。
    """
    p = manifest_path(cfg, dest)
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except ValueError:
        data = {}
    data[meta["slug"]] = source_hash(src)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=0, sort_keys=True),
                 encoding="utf-8")
    return p


def mask(s):
    """ログに出す前にトークンらしき文字列を伏せる"""
    return re.sub(r"(github_pat_|ghp_|ghs_|gho_)[A-Za-z0-9_]+", r"\1***", str(s))


def git_auth(token):
    """トークンをコマンドラインに出さずに git へ渡す。

    URLに埋めると、プロセス一覧を見るだけでPATが読める。特権は要らない。
    実際、稼働中の配信からPATの全体が読み出せた。
    ユーザー名だけURLに残し、パスワードは GIT_ASKPASS から渡す。
    """
    if not token:
        return None
    WORK.mkdir(exist_ok=True)
    if os.name == "nt":
        ask = WORK / "_askpass.bat"
        ask.write_text("@echo off\r\necho %GIT_TOKEN%\r\n", encoding="ascii")
    else:
        ask = WORK / "_askpass.sh"
        ask.write_text('#!/bin/sh\nprintf "%s" "$GIT_TOKEN"\n', encoding="ascii")
        ask.chmod(0o700)
    env = dict(os.environ)
    env["GIT_TOKEN"] = token
    env["GIT_ASKPASS"] = str(ask)
    return env


def run(args, cwd=None, check=True, env=None):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore", env=env)
    if check and r.returncode != 0:
        raise SystemExit(mask(f"コマンド失敗: {' '.join(args)}\n{r.stdout}\n{r.stderr}"))
    return r.stdout.strip()


def try_run(args, cwd=None, env=None):
    """成否だけ知りたいとき用（run は標準出力を返すため成否の判定に使えない）"""
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore", env=env)
    return r.returncode == 0


def gate_ok(meta):
    """公開の基準（score 90以上かつ観点の足切り）。判定は rubric.gate_ok を唯一の正とする。

    配信側が score だけを見ていたため、build.py が止める「1観点だけ壊滅した記事」が
    別リポジトリの社にはそのまま配信されていた
    """
    import rubric
    f = getattr(rubric, "gate_ok", None)
    if f:
        return bool(f(meta))
    sc = meta.get("score")
    return isinstance(sc, (int, float)) and not isinstance(sc, bool) and sc >= 90


def read_meta(path: Path):
    """フロントマターだけを読む（壊れていれば None）"""
    try:
        return parse_article(path)[0] or None
    except (SystemExit, yaml.YAMLError):
        return None


def parse_article(path: Path):
    t = path.read_text(encoding="utf-8-sig")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
    if not m:
        raise SystemExit(f"フロントマターがありません: {path}")
    # 検索から外した記事（noindex）へのリンクも配信の入口で外す（文は残す。build.py と同じ関数）。
    # main() だけで外すと、描き直し（publish_rerender・republish_images・wp_bridge）が素の原稿で書き戻す
    return yaml.safe_load(m.group(1)), noindex.unlink(strip_private_links(m.group(2)))[0]


def strip_private_links(body):
    """一次データを非公開にしている間は、AI集客ラボの /data/ へのリンクを文字に戻す。
    AI集客ラボのビルドは外しているが、配信先の記事には残り、404へ送っていた（2026-09-29: コーポレート4本）。
    main() だけで外していたため、描き直し（publish_rerender・republish_images）が素の原稿で書き戻し、
    2026-10-06 の描き直しでコーポレート8本に 404 へのリンクが戻った。配信の入口（parse_article）で外す"""
    try:
        import data_intake
    except ImportError:
        return body
    if data_intake.PUBLIC:
        return body
    body = re.sub(r"\[([^\]]+)\]\(https://ai\.7senses\.co\.jp/data/(?!reco\.json)[^)]*\)", r"\1", body)
    return re.sub(r'<a\s[^>]*href="https://ai\.7senses\.co\.jp/data/(?!reco\.json)[^"]*"[^>]*>(.*?)</a>',
                  r"\1", body, flags=re.S)


def ensure_clone(cfg, token):
    """対象リポジトリをクローン（既にあれば最新化）して作業パスを返す"""
    WORK.mkdir(exist_ok=True)
    dest = WORK / cfg["id"]
    url = f"https://github.com/{cfg['repo']}.git"
    auth_url = f"https://x-access-token@github.com/{cfg['repo']}.git" if token else url
    env = git_auth(token)
    if not (dest / ".git").exists():
        shutil.rmtree(dest, ignore_errors=True)
        run(["git", "clone", "--depth", "1", "--branch", cfg["branch"], auth_url,
             str(dest)], env=env)
    else:
        # 前の配信が途中で落ちて rebase / merge が残っていると、reset --hard では消えず、
        # この後の rebase・push が全部失敗する。先に中断して作業状態を片付ける
        g = dest / ".git"
        if (g / "rebase-merge").exists() or (g / "rebase-apply").exists():
            try_run(["git", "rebase", "--abort"], cwd=dest)
            shutil.rmtree(g / "rebase-merge", ignore_errors=True)
            shutil.rmtree(g / "rebase-apply", ignore_errors=True)
            print("  配信先に途中の rebase が残っていたので中断しました")
        if (g / "MERGE_HEAD").exists():
            try_run(["git", "merge", "--abort"], cwd=dest)
        # 手元で配信先を直接直していると、この reset で黙って消える（2026-10-03: 補助金サイトの
        # トップ・運営者情報・記事の雛形の修正を、コミット前に配信し直して失った）。手元では止めて知らせる
        if not os.environ.get("GITHUB_ACTIONS"):
            dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=dest,
                                   capture_output=True, text=True, encoding="utf-8").stdout.strip()
            if dirty:
                raise SystemExit(f"配信先 {dest} にコミットしていない変更があります。先にコミットするか、"
                                 f"要らなければ git -C \"{dest}\" checkout -- . で戻してから配信してください:\n{dirty[:600]}")
        run(["git", "fetch", "--depth", "1", auth_url, cfg["branch"]], cwd=dest, env=env)
        run(["git", "reset", "--hard", "FETCH_HEAD"], cwd=dest)
    return dest


def ensure_images(meta):
    """フロントマターが指す画像が手元に無ければ、その場で作る（Pillow・外部APIなし）。

    実測で、eyecatch を指しているのに site/images/<slug>/ が空の記事が11本あり、
    配信先の一覧で画像が 404 になっていた。配信の直前に必ず実体を揃える。
    """
    slug = meta.get("slug", "")
    img_src = ROOT / "site" / "images" / slug
    if not meta.get("eyecatch") or (img_src / "eyecatch.png").is_file():
        return
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_images.py"), slug],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if (img_src / "eyecatch.png").is_file():
        print(f"  画像が無かったので作りました: site/images/{slug}/")
    else:
        print(f"  [警告] 画像を作れませんでした（{(r.stderr or r.stdout)[-80:].strip()}）。配信先で 404 になります")


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


def client_credit(cfg, url=""):
    """お客様の記事の監修者・著者・発行元（data/clients/<id>/ の company.json と brief.json から）。

    監修者はお客様ご本人（2026-10-05 運用者の決定）。運用会社の代表を監修者・著者として
    付けると事実と違う記事になる。掲載の同意（display）が無い方は表示も構造化データも出さない。
    クライアントでなければ None（自社サイトは各サイトの雛形が持つ）
    """
    import html as H
    cdir = ROOT / "data" / "clients" / cfg["id"]
    if not cdir.is_dir():
        return None

    def read(name):
        try:
            return json.loads((cdir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    comp, brief = read("company.json"), read("brief.json")
    origin = f"https://{cfg['domain']}/"
    org = {"@type": "Organization", "name": comp.get("name") or cfg.get("name", ""), "url": origin}
    if comp.get("tel"):
        org["telephone"] = comp["tel"]
    if comp.get("address"):
        org["address"] = {"@type": "PostalAddress", "streetAddress": comp["address"],
                          **({"postalCode": comp["postal"]} if comp.get("postal") else {})}
    a = brief.get("author") or {}
    author = ({"@type": "Person", "name": a["name"], **({"jobTitle": a["title"]} if a.get("title") else {}),
               "worksFor": {"@type": "Organization", "name": org["name"]}} if a.get("name") else dict(org))
    sup = comp.get("supervisor") or {}
    out = {"publisher": org, "author": author, "reviewer": None, "byline": "", "supervisor": None}
    if not (sup.get("name") and sup.get("display")):
        return out
    quals = sup.get("qualification") or []
    # ヒアリングシートの「なし（実務の経歴で監修。資格は表示しない）」は資格ではない。資格として出すと
    # 「監修: YW（なし（…））」と表示され、構造化データにも資格として載る（CONFLUX・2026-10-08）
    quals = [q for q in ([quals] if isinstance(quals, str) else quals)
             if q and not re.match(r"\s*(なし|無し|ない|-|－|ー)(\s|（|\(|$)", str(q))]
    rv = {"@type": "Person", "name": sup["name"]}
    if sup.get("title"):
        rv["jobTitle"] = sup["title"]
    if quals:
        rv["hasCredential"] = [{"@type": "EducationalOccupationalCredential", "name": q} for q in quals]
    career = sup.get("career") or []
    if career:
        rv["description"] = " / ".join(career if isinstance(career, list) else [career])
    same = sup.get("same_as") or []
    if same:
        rv["sameAs"] = same if isinstance(same, list) else [same]
    if sup.get("profile_url"):
        rv["url"] = sup["profile_url"]
    rv["worksFor"] = {"@type": "Organization", "name": org["name"]}
    out["reviewer"] = rv
    name = H.escape(sup["name"]) + (f"（{H.escape('・'.join(quals))}）" if quals else "")
    if sup.get("profile_url"):
        name = f'<a href="{H.escape(sup["profile_url"])}">{name}</a>'
    out["byline"] = ('<p class="supervisor" style="font-size:.88rem;color:#4b5563;margin:8px 0 16px">'
                     f"監修: {name}"
                     + (f"／{H.escape(sup['title'])}" if sup.get("title") else "")
                     + (f"<br>監修の範囲: {H.escape(sup['scope'])}" if sup.get("scope") else "")
                     + "</p>")
    out["supervisor"] = {k: sup[k] for k in ("name", "title", "qualification", "scope", "profile_url")
                         if sup.get(k)}
    return out


def credit_ld(credit, url, meta):
    """記事に足す構造化データ（BlogPosting に author・publisher・reviewedBy を付けたもの）"""
    ld = {"@context": "https://schema.org", "@type": "BlogPosting", "@id": url + "#article",
          "headline": meta["title"], "mainEntityOfPage": url,
          "author": credit["author"], "publisher": credit["publisher"]}
    if credit.get("reviewer"):
        ld["reviewedBy"] = credit["reviewer"]
    return ld


def credit_jsonld(credit, url, meta, cfg=None, html=None, image="", video=True):
    """お客様の記事の構造化データ。cfg を渡すと BlogPosting に日付・画像・about/mentions を足し、FAQPage も出す"""
    if cfg is not None:
        return ld_scripts(cfg, meta, url, html or "", image, credit, video)
    return '<script type="application/ld+json">' + json.dumps(credit_ld(credit, url, meta), ensure_ascii=False) + "</script>"


def apply_credit(page, credit, url, meta):
    """描き上がったページへ、お客様の監修者・著者・発行元を当てる。
    雛形（汎用・先方の template.html）が何を持っているかに依らず、h1 の直後に監修の表示、
    head に構造化データを置く。雛形にもともとある BlogPosting の publisher は発行元に揃える"""
    if not credit:
        return page
    if credit["byline"]:
        page = re.sub(r"(</h1>)", lambda m: m.group(1) + "\n" + credit["byline"], page, count=1)
    # 雛形の BlogPosting に足す（別の BlogPosting を並べると、同じ記事が2つの実体に見える）
    for m in re.finditer(r'(<script type="application/ld\+json">)(.*?)(</script>)', page, re.S):
        try:
            ld = json.loads(m.group(2))
        except ValueError:
            continue
        if not (isinstance(ld, dict) and ld.get("@type") == "BlogPosting"):
            continue
        ld["author"], ld["publisher"] = credit["author"], credit["publisher"]
        if credit.get("reviewer"):
            ld["reviewedBy"] = credit["reviewer"]
        new = m.group(1) + json.dumps(ld, ensure_ascii=False) + m.group(3)
        return page[:m.start()] + new + page[m.end():]
    tag = credit_jsonld(credit, url, meta)
    return page.replace("</head>", tag + "\n</head>", 1) if "</head>" in page else page + tag


def apply_html_parts(html, cfg):
    """原稿の部品（definition-box など）を、配信先の CSS が持つ部品の名前へ読み替える（sites/<id>.json の html_parts）。

    部品の見た目は AI集客ラボの CSS にしかなく、そのまま渡すとコーポレートでは全記事の定義・注意・要約が素の段落になっていた
    （2026-10-08 の点検: 132/132本）。コーポレートの記事の CSS（article.css）は def-box・note-box・summary-box を持ち、
    箱の題は先頭の strong で描く（.summary-box > strong）。部品の題（lst-title・box-title）も strong にする"""
    parts = {k: v for k, v in (cfg.get("html_parts") or {}).items() if not k.startswith("_") and v}
    if not parts:
        return html

    def box(m):
        # 題の後の <br> は残す（注意の箱の strong は行の中の要素なので、改行が無いと本文とつながる）
        inner = re.sub(r'^\s*<(p|span) class="(?:lst-title|box-title)">(.*?)</\1>',
                       r"<strong>\2</strong>", m.group(2), count=1, flags=re.S)
        return f'<div class="{parts[m.group(1)]}">{inner}</div>'
    return re.sub(r'<div class="(' + "|".join(map(re.escape, parts)) + r')">(.*?)</div>', box, html, flags=re.S)


def template_intro(html, tpl, cfg, meta):
    """雛形が冒頭に別に出すもの（{{LEAD_DANGEN}} の結論・{{TARGET}} の対象読者・{{DATE_YM}} の時点）を本文から外し、
    (本文, 結論の文字, 対象読者) を返す。雛形に無いものは本文に残す（先方の雛形 template.html が持たない社がある）。

    両方に出すと冒頭で同じ文が2回並ぶ（補助金サイト 129本）。対象読者の箱に2文目があると
    「この記事は<b>…方に向けて書いています。</b>向けです」と文が壊れた（47本）。対象読者は最初の「向けです」の前だけを使い、
    箱の2文目以降（「…方に向けて書いています。」「公募の日程は◯日時点の…」）は本文に残す"""
    cut = html.find("<h2")
    intro, rest = (html[:cut], html[cut:]) if cut >= 0 else (html, "")
    lead = ""
    m = re.search(r"<p>(.*?)</p>", intro, re.S)
    if m:
        lead = _plain(m.group(1))
        if "{{LEAD_DANGEN}}" in tpl:
            intro = intro[:m.start()] + intro[m.end():]
    target = ""
    m = re.search(r'<div class="target-reader">(.*?)</div>', intro, re.S)
    if m:
        head, sep, tail = m.group(1).partition("向けです")
        if sep:
            target = re.sub(r"(の方)?$", "", re.sub(r"^この記事は[、,]?\s*", "", _plain(head)))
            if "{{TARGET}}" in tpl:
                tail = re.sub(r"^[。.]\s*", "", tail.strip())
                intro = (intro[:m.start()] + (f'<div class="target-reader">{tail}</div>' if _plain(tail) else "")
                         + intro[m.end():])
    if not target:
        target = re.sub(r"(の方)?向けです[。.]?$", "", re.sub(r"^この記事は[、,]?\s*", "",
                                                         str(cfg.get("audience") or "").strip()))
    m = re.search(r'<p class="freshness">(.*?)</p>', intro, re.S)
    if m and "{{DATE_YM}}" in tpl:
        head, sep, tail = m.group(1).partition("時点の情報です")
        if sep:
            tail = re.sub(r"^[。.]\s*", "", tail.strip())
            intro = intro[:m.start()] + (f'<p class="freshness">※ {tail}</p>' if _plain(tail) else "") + intro[m.end():]
    return intro + rest, lead or str(meta.get("description") or ""), target


def write_nextjs_json(cfg, dest: Path, meta, body):
    """Next.jsサイト用: 本文HTML込みのJSONを書き出す"""
    html, _ = md2html.convert(body)
    html = apply_html_parts(html, cfg)
    faq = md2html.extract_faq(body)
    # 変換されずに残ったMarkdownの検査は main() に移した。
    # ここに置くと nextjs-json だけが見られ、他の配信方式が素通りする

    # 記事Markdownは自リポジトリの慣習（/images/<slug>/…）で書かれているため、
    # 配信先の実際の画像置き場に合わせてパスを書き換える。
    # これをしないと配信先で画像が全て404になる。
    prefix = image_prefix(cfg)
    src_path, dst_path = f"/images/{meta['slug']}/", f"{prefix}/{meta['slug']}/"
    if src_path != dst_path:
        html = html.replace(src_path, dst_path)
        if meta.get("eyecatch"):
            meta = {**meta, "eyecatch": str(meta["eyecatch"]).replace(src_path, dst_path)}
    html += aggregate_links(cfg, dest, meta)
    # お客様の記事: 配信先のアプリが監修の欄を持たなくても出るよう、本文の頭と末尾に入れる
    # 読了時間・文字数は本文だけで数える（構造化データの文字を数えない）
    text_html = html
    url = sites_mod.article_url(cfg, meta)
    credit = client_credit(cfg)
    # 記事の動画（VideoObject つき）は本文の頭に置く。配信先の CSP が YouTube を許さなければ置かない
    vb = video_block(meta, dest)
    if vb:
        html = vb + html
    if credit:
        # お客様の Next.js には、当社が記事の雛形を持たない。入口・中ほどの導線・構造化データ
        # （BlogPosting に日付・画像・about/mentions・著者、FAQPage）を本文に入れて、アプリの実装に依らず出す。
        # コーポレート（自社）はアプリ側が出す（InlineToolBox・事業への帯・BlogPosting/FAQPage/about）ので入れない
        img = f"https://{cfg['domain']}{meta['eyecatch']}" if meta.get("eyecatch") else ""
        html = (credit["byline"] + "\n" if credit["byline"] else "") + \
            insert_mid_cta(insert_inline_entry(html, cfg), cfg) + "\n" + \
            credit_jsonld(credit, url, meta, cfg=cfg, html=text_html, image=img, video=not vb)
    # 表の数字を同じ数字の横棒グラフにして表の直後に添える（読了時間・扱う実体は表だけの本文で数える）。
    # 先方のアプリは本文を dangerouslySetInnerHTML でそのまま描く（消毒しない）ので、インラインの SVG のまま渡す
    html = table_charts.add_to_html(html, cfg)

    out = {
        "slug": meta["slug"],
        "title": meta["title"],
        "description": meta["description"],
        "date": str(meta["date"]),
        "dateModified": str(meta.get("modified") or meta.get("dateModified") or meta["date"]),
        "category": meta["category"],
        "categoryName": sites_mod.category_name(cfg, meta["category"]),
        "readingMinutes": md2html.reading_minutes(text_html),
        "faq": faq,
        "html": html,
    }
    if noindex.on(meta):
        # 検索から外した記事: 先方の記事ページが head を noindex にし、一覧・関連・サイトマップから外す
        out = noindex.nextjs_fields(out)
    if credit:
        out["author"] = credit["author"]
        if credit["supervisor"]:
            out["supervisor"] = credit["supervisor"]
    if meta.get("eyecatch"):
        out["eyecatch"] = meta["eyecatch"]
    # 記事が扱う実体（構造化データの about / mentions）。アプリが head に出すための材料
    import entities
    out["about"], out["mentions"] = entities.about_and_mentions(
        f"{meta['title']} {meta.get('keyword', '')}", md2html.plain_text(text_html))
    try:
        import video_embed
        rec = video_embed.info(meta["slug"])
        if rec:
            # inHtml が偽なら本文に入っていない（CSP で止めた）。アプリが自前で出すときの材料
            out["video"] = {"youtube": rec["youtube"], "embedUrl": f"https://www.youtube-nocookie.com/embed/{rec['youtube']}",
                            "uploadDate": video_embed.upload_date(rec), "seconds": int(rec.get("sec") or 0), "inHtml": bool(vb)}
    except Exception:
        pass
    # 一覧・記事の頭に出す写真（写真の棚から内容に合う1枚）。共有画像の eyecatch は文字のカードのまま
    try:
        import photo_shelf
        _, url = photo_shelf.pick(meta["title"], str(meta.get("keyword") or ""), meta["slug"])
        photo = photo_shelf.copy_to(dest / "public", url) if url else ""
        if photo:
            out["photo"] = photo
    except Exception as e:
        print(f"  写真の棚をスキップ: {e}")
    # 多言語の要約（指示のある社だけ）。Next.js 側はこの translations を読んで /en/… を出す
    # （表示の実装は配信先のアプリ側。無ければ JSON に載っているだけで害は無い）
    langs = [l for l in (cfg.get("languages") or []) if l in ("en", "zh", "ko")]
    if langs:
        try:
            import i18n
            tr = {}
            for lg in langs:
                p = i18n.OUT / lg / f"{meta['slug']}.json"
                if p.is_file():
                    d = json.loads(p.read_text(encoding="utf-8"))
                    tr[lg] = {k: d[k] for k in ("title", "description", "lead", "sections", "faq") if k in d}
            if tr:
                out["translations"] = tr
        except Exception:
            pass
    # 日本語の記事と訳のページの組（hreflang）。記事ページの generateMetadata が配った部品（ssAlternates）で head に出す
    alts = article_alternates(cfg, dest, meta)
    if alts:
        out["alternates"] = alts
    # 画像を先に複製する（本文が /images/... を参照するため）。JSONはその後に書く。
    # アイキャッチはWebP（PNGの1/3）も作り、表示はそちらを使う。OG画像はPNGのまま
    img_written = []
    ensure_images(meta)
    img_src = ROOT / "site" / "images" / meta["slug"]
    if cfg.get("images_dir") and img_src.exists():
        img_dest = dest / cfg["images_dir"] / meta["slug"]
        shutil.rmtree(img_dest, ignore_errors=True)
        shutil.copytree(img_src, img_dest)
        img_written.append(img_dest)
        if to_webp(img_dest / "eyecatch.png") and meta.get("eyecatch"):
            out["eyecatchWebp"] = str(meta["eyecatch"]).rsplit(".", 1)[0] + ".webp"
    target = dest / cfg["content_dir"] / f"{meta['slug']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Next.jsサイトでも sitemap.xml / llms.txt への追記が要る。呼んでいなかったため、
    # 公開した記事がAIクローラー向けの案内に1本も載っていなかった
    # 画像・動画のサイトマップ行は、ページを書き出さないので本文とアイキャッチから拾う
    page = html + (f'<meta property="og:image" content="https://{cfg["domain"]}{out["eyecatch"]}">'
                   if out.get("eyecatch") else "")
    written = [target] + _update_external_index(dest, cfg, meta, page=page) + img_written
    if langs:
        written += nextjs_alternates_part(cfg, dest, warn=bool(alts))
    # 検索から外した記事（noindex）を先方のアプリが扱えるようにする（記事の読み込みと記事ページに数行。2回目からは何も書かない）。
    # お客様のアプリは先方のファイルなので書き換えず、外した記事を配信したときだけ要対応で知らせる
    client = sites_mod.is_client(cfg["id"])
    nj, why = noindex.nextjs_app(dest, write=not client)
    if client and nj:
        why = "記事の読み込み（lib/blog.ts）と記事ページに、JSON の noindex を robots と一覧の除外に使う数行を足してください"
    elif nj:
        written += nj
    if why and noindex.on(meta):
        print(f"要対応: {cfg['id']} の記事 {meta['slug']} は検索から外す記事ですが、先方のアプリが noindex を読めません（{why}）")
    return written, len(md2html.plain_text(text_html))


def to_webp(png: Path, quality=80):
    """PNGの隣にWebPを作る（無ければ何もしない）。モバイルの転送量を減らすため"""
    if not png.is_file():
        return None
    try:
        from PIL import Image
        out = png.with_suffix(".webp")
        with Image.open(png) as im:
            im.convert("RGB").save(out, "WEBP", quality=quality, method=6)
        return out
    except Exception as e:
        print(f"  WebP変換をスキップ: {png.name}（{str(e)[:40]}）")
        return None


def public_root(cfg, dest: Path):
    """配信先で URL の / に当たるフォルダ（images_dir の public/・static/・site/ を見る）"""
    d = (cfg.get("images_dir") or "").strip("/")
    for head in ("public", "static", "site"):
        if d.startswith(head + "/"):
            return dest / head
    return dest


def _md_insert_entries(body, cfg):
    """Markdown の原稿に、その場の入口と中ほどの導線を置く（HTML の insert_inline_entry・insert_mid_cta と同じ位置）。
    塊は1行の HTML で、前後に空行を置く（Markdown の HTML ブロックとして本文から切り離す）"""
    lines = body.split("\n")
    fence = False
    heads = []
    for i, ln in enumerate(lines):
        if ln.startswith("```"):
            fence = not fence
        elif not fence and re.match(r"## (?!#)", ln):
            heads.append(i)
    ins = {}
    ent = cfg.get("cta_inline") or {}
    if ent.get("url") and "cta-inline" not in body and heads \
            and not re.search(r"よくある質問|まとめ", lines[heads[0]]):
        i = heads[0] + 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i < len(lines) and not re.match(r"\s*(<|[|#>]|[-*+]\s|\d+\.\s)", lines[i]):
            while i < len(lines) and lines[i].strip():
                i += 1
            ins[i] = inline_entry_block(ent)
    if len(heads) >= 5 and "cta-mid" not in body:
        ins[heads[len(heads) // 2]] = mid_cta_block(cfg)
    for i in sorted(ins, reverse=True):
        lines[i:i] = ["", ins[i], ""]
    return "\n".join(lines)


# ============================================================
# 先方の変換が読む Markdown の方言（sites/<id>.json の md_dialect。いまは CONFLUX の journal）
# ============================================================
# CONFLUX は届いた Markdown を先方の scripts/build-journal.mjs（fromPipeline）で読み替え、marked で HTML にする。
# 当社の原稿のまま置くと、次のことが起きる（2026-10-08 の点検で再現）:
#   - score があり author の無い記事を「自動化の記事」と見なさず、日付の欄が無いまま読んで組み立てごと落ちる（RangeError）
#   - marked（CommonMark）は「**…。**本文」の ** を閉じと見なさず、記号のまま出す（1本で7組）
#   - 定義・注意・要約・対象読者・時点・相談の箱に先方の CSS が無く素の段落になる。相談の箱は当社の青で浮く
#   - よくある質問の <div class="faq"> の殻が残り、中身の無い見出しが先方の質問欄と並んで目次に2回出る
#   - 結論の枠に説明文（description）が入る（先方は最初の em-marker を結論として読む）
# 先方の部品（globals.css の .prose-yw の box-note・box-warn・cta-inline・table-wrap）と、
# fromPipeline が読む書き方（「本記事は◯時点の情報です。この記事は、◯向けです。」の1行・## この記事の要点・em-marker）へ直す
_PROTECT = re.compile(r"```.*?```|`[^`\n]+`|<script\b.*?</script>", re.S)
_HOLD = re.compile(r"@@HOLD(\d+)@@")
# 先方が描けない当社の部品（変換の後に残っていれば配信しない）
OUR_PARTS = ("definition-box", "caution-box", "lead-summary", "target-reader", "freshness", "cta-box", "cta-mid",
             "cta-button", "faq", "txt-red", "txt-blue", "big", "lst-title", "term")


def md_dialect(cfg):
    """先方の変換が読む方言の設定（sites/<id>.json の md_dialect）。無ければ {}（当社の原稿の形のまま置く）"""
    d = cfg.get("md_dialect")
    return d if isinstance(d, dict) and d.get("name") == "journal" else {}


def md_inline_to_html(md, em="em"):
    """**強調** と *強調* を HTML のタグにする（当社の変換 Python-Markdown と同じ範囲）。コード・script の中は触らない。
    CommonMark（marked など）は句読点の直後の ** を閉じと見なさず、「**…。**本文」が記号のまま表示される。
    em は *強調* のタグ（当社のサイトでは青の太字。斜体を持たない和文の配信先には strong を渡す）"""
    keep = []

    def hold(m):
        keep.append(m.group(0))
        return f"@@HOLD{len(keep) - 1}@@"
    t = _PROTECT.sub(hold, md)
    t = re.sub(r"\*\*(?!\s)([^\n]+?)(?<!\s)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*(?![\s*])([^*\n]+?)(?<![\s*])\*(?!\*)", rf"<{em}>\1</{em}>", t)
    return _HOLD.sub(lambda m: keep[int(m.group(1))], t)


def _plain(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).replace("==", "").strip()


def _md_block(html):
    """HTML の塊を1つの塊として置く（中の空行を詰め、前後に空行）。CommonMark は空行で HTML の塊を終え、
    残りを Markdown として読むため、塊の中に空行があると閉じタグが本文に出る"""
    return "\n\n" + re.sub(r"\n\s*\n", "\n", html.strip()) + "\n\n"


def _journal_box(cls, title, inner, label=""):
    """先方の枠（box-note・box-warn）。label は枠の札の文字（先方の CSS が data-label を札に描く。無ければ
    box-note は「ポイント」、box-warn は「注意」）。札と同じ文を題（box-title）として中に重ねない"""
    inner = re.sub(r"^\s*(?:<br\s*/?>\s*)+", "", inner.strip())
    if not re.match(r"<(p|ul|ol|table|div)\b", inner):
        inner = f"<p>{inner}</p>"
    head = f'<p class="box-title">{title}</p>\n' if title and title != label else ""
    attr = f' data-label="{label}"' if label else ""
    return _md_block(f'<div class="{cls}"{attr}>\n{head}{inner}\n</div>')


def _journal_cta(href, label, text, tag=""):
    """相談の導線を先方の部品（.cta-inline: 黒地に用紙色の文字）にする。先方の手書きの記事と同じ書き方"""
    label = re.sub(r"\s*[→＞>]+\s*$", "", _plain(label))
    data = f' data-cta="{tag}"' if tag else ""
    return _md_block(f'<a class="cta-inline" href="{href}"{data}><strong>{label} →</strong>'
                     f"<span>{_plain(text)}</span></a>")


def _lead_answer(block):
    """冒頭の段落から結論の1文を取り出す。(結論の Markdown, 残りの Markdown)。取れなければ ("", block)"""
    bold = re.match(r"\s*\*\*(.+?)\*\*", block, re.S)
    if bold and bold.group(1).rstrip().endswith(("。", "！", "？")):
        return bold.group(1), block[bold.end():].strip()
    sent = re.match(r"\s*(.+?[。！？])", block, re.S)
    if sent and sent.group(1).count("**") % 2 == 0:
        return sent.group(1), block[sent.end():].strip()
    return "", block


def _journal_intro(body, cfg, meta):
    """最初の見出し（H2）より前を先方の形にする。

    先方は「本記事は◯時点の情報です。この記事は、◯向けです。」の行から時点と対象読者を取って行ごと外し、
    最初の em-marker を結論の枠に出す。結論はこの行に置く（本文の1段落目に残すと、結論の枠と本文の頭に同じ文が2回並ぶ）。
    「この記事でわかること」は ## この記事の要点 の箇条書きで渡す。最初の見出しの直前に置く
    （先方は次の ## までを節として外すので、後ろに本文があると一緒に消える）。
    対象読者・時点の箱にある2文目以降（「…方に向けて書いています。」「公募の日程は◯日時点の…」）は本文に残す"""
    m = re.search(r"^## ", body, re.M)
    if not m:
        return body
    intro, rest = body[:m.start()], body[m.start():]

    def take(rx):
        nonlocal intro
        got = re.search(rx, intro, re.S)
        if got:
            intro = intro[:got.start()] + intro[got.end():]
        return got.group(1) if got else None
    target = take(r'<div class="target-reader">(.*?)</div>')
    fresh = take(r'<p class="freshness">(.*?)</p>')
    summary = take(r'<div class="lead-summary">(.*?)</div>')
    notes, aud, asof = [], "", ""
    if target is not None:
        head, sep, tail = target.partition("向けです")
        if sep:
            aud = re.sub(r"^この記事は[、,]?\s*", "", _plain(head))
            tail = re.sub(r"^[。.]\s*", "", tail.strip())
            if _plain(tail):
                notes.append(tail)
        else:
            notes.append(target.strip())
    aud = aud or re.sub(r"(の方)?向けです[。.]?$", "", str(cfg.get("audience") or "").strip())
    if fresh is not None:
        head, sep, tail = fresh.partition("時点の情報です")
        if sep:
            asof = re.sub(r"^[※*\s]+", "", _plain(head)) + "時点の情報です"
            tail = re.sub(r"^[。.]\s*", "", tail.strip())
            if _plain(tail):
                notes.append("※ " + tail)
        else:
            notes.append(fresh.strip())
    mod = str(meta.get("modified") or meta.get("date") or "")
    if not asof and re.match(r"\d{4}-\d{2}", mod):
        asof = f"{mod[:4]}年{int(mod[5:7])}月時点の情報です"
    blocks = [b for b in re.split(r"\n\s*\n", intro.strip("\n")) if b.strip()]
    answer, out = "", []
    for b in blocks:
        # 生の HTML の塊（動画・図・注意の箱）は結論にしない。文字の装飾で始まる段落は結論の候補
        if answer or not (asof and aud) or re.match(r"\s*<(?!strong\b|em\b|b\b|a\b|span\b)[a-z]", b):
            out.append(b)
            continue
        ans, left = _lead_answer(b)
        # 結論の枠は文字だけを描く（リンクの記法は文字に戻す）
        answer = _plain(md_inline_to_html(re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", ans)))
        if left or not answer:
            out.append(left if answer else b)
    head = []
    if asof and aud:
        head.append(f"本記事は{asof}。この記事は、{aud}向けです。"
                    + (f'<span class="em-marker">{answer}</span>' if answer else ""))
    learn = ""
    items = [li.strip() for li in re.findall(r"<li>(.*?)</li>", summary or "", re.S) if _plain(li)]
    if items:
        learn = "## この記事の要点\n\n" + "\n".join(f"- {li}" for li in items) + "\n\n"
    return "\n\n".join(head + out + notes) + "\n\n" + learn + rest


def journal_md(cfg, meta, body, dialect):
    """当社の原稿（入口・導線を置いた後）を、先方の変換が読む (フロントマター, 本文) にする"""
    # 自社サイト内のリンクは / から（先方の変換は https のリンクを全部「新しいタブ」で開くようにする）
    body = re.sub(r"(\]\(|href=\")https?://(?:www\.)?" + re.escape(cfg["domain"]) + r"(?=/)", r"\1", body)
    # 文字の装飾（入れ子は内側から）。赤・青は太字、大きな文字は先方のマーカー
    for _ in range(5):
        new = re.sub(r'<span class="(txt-red|txt-blue|big)">((?:(?!<span\b).)*?)</span>',
                     lambda m: (f'<strong class="marker">{m.group(2)}</strong>' if m.group(1) == "big"
                                else f"<strong>{m.group(2)}</strong>"), body, flags=re.S)
        if new == body:
            break
        body = new
    body = _journal_intro(body, cfg, meta)
    # 定義は先方の box-note の札を「定義」にする（先方の globals.css が data-label を札に描く。2026-10-08 先方の指定）
    body = re.sub(r'<div class="definition-box">(.*?)</div>',
                  lambda m: _journal_box("box-note", "", re.sub(r'<span class="term">(.*?)</span>', r"<strong>\1</strong>",
                                                               m.group(1), flags=re.S), label="定義"), body, flags=re.S)

    def warn(m):
        inner, title = m.group(1).strip(), ""
        t = re.match(r'<(span|p) class="box-title">(.*?)</\1>', inner, re.S)
        if t:
            # 先方の枠は「注意」の札を付けるので、題の頭の「注意:」は外す
            title, inner = re.sub(r"^\s*注意点?\s*[:：]\s*", "", t.group(2)).strip(), inner[t.end():]
        return _journal_box("box-warn", title, inner)
    body = re.sub(r'<div class="caution-box">(.*?)</div>', warn, body, flags=re.S)
    body = re.sub(r'<div class="cta-box">\s*<p>(.*?)</p>\s*<a class="cta-button" href="([^"]+)"[^>]*>(.*?)</a>\s*</div>',
                  lambda m: _journal_cta(m.group(2), m.group(3), m.group(1)), body, flags=re.S)
    body = re.sub(r'<div class="cta-mid"[^>]*>\s*<p[^>]*>(.*?)</p>\s*<a class="cta-button" href="([^"]+)"'
                  r'(?: data-cta="([^"]*)")?[^>]*>(.*?)</a>\s*(?:<p[^>]*>(.*?)</p>)?\s*</div>',
                  lambda m: _journal_cta(m.group(2), m.group(4), m.group(1) + (m.group(5) or ""), m.group(3) or ""),
                  body, flags=re.S)
    # よくある質問: 先方は <details> を抜き出して質問欄にし、空になった見出しを外す。殻の div が残ると見出しも残る
    body = re.sub(r'<div class="faq">\s*(.*?)\s*</div>', lambda m: "\n" + m.group(1) + "\n", body, flags=re.S)
    # 表は先方の横スクロールの枠（.table-wrap）に入れる（先方の手書きの記事と同じ形）
    lines, out, fence, i = body.split("\n"), [], False, 0
    while i < len(lines):
        if lines[i].startswith("```"):
            fence = not fence
        if not fence and lines[i].lstrip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            out += ["", '<div class="table-wrap">', ""] + lines[i:j] + ["", "</div>", ""]
            i = j
            continue
        out.append(lines[i])
        i += 1
    body = re.sub(r"\n{3,}", "\n\n", md_inline_to_html("\n".join(out), em="strong")).strip("\n") + "\n"
    fm = {k: meta[k] for k in ("slug", "title", "description", "category", "date") if meta.get(k) not in (None, "")}
    # 更新日は modified、狙う語は keyword（先方の docs/journal-pipeline.md の書き方。先方は updated・tags も読むが、
    # 書き方の説明と食い違うと、先方が読む欄を絞ったときに更新日と狙う語が黙って公開日と題に変わる）
    fm["modified"] = meta.get("modified") or meta.get("date")
    try:
        brief = json.loads((ROOT / "data" / "clients" / cfg["id"] / "brief.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        brief = {}
    fm["author"] = dialect.get("author") or (brief.get("author") or {}).get("name") or ""
    if meta.get("keyword"):
        fm["keyword"] = str(meta["keyword"])
    return fm, body


def journal_problems(fm, body, dialect):
    """先方の変換が組み立てを止める条件（build-journal.mjs）と、先方が描けない形を、書き込む前に見る。
    先方は1本でも止まるとサイト全体の組み立てが失敗し、どの記事も更新されなくなる"""
    out = []
    if "score" in fm or not fm.get("date"):
        out.append("自動化の記事と見なされない（score がある・date が無い）")
    out += [f"{k} がありません" for k in ("slug", "title", "description", "category", "author") if not fm.get(k)]
    text = json.dumps(fm, ensure_ascii=False, default=str) + body
    out += [f"先方が止める語「{w}」が入っています" for w in dialect.get("forbidden") or [] if w and w in text]
    heads = [h for h in re.findall(r"^##\s*(.+)$", body, re.M)
             if not re.match(r"\s*(目次|この記事の要点|よくある質問|出典|参考)", h)]
    if len(heads) < 3:
        out.append(f"見出し（H2）が3つ未満（{len(heads)}）")
    # 先方は layout（Measure）で計測する。本文の計測は二重に数え、ページ内の移動では動かない
    if re.search(r"<script\b(?![^>]*application/ld\+json)", body):
        out.append("本文に計測などのスクリプトがあります（先方は layout で計測する）")
    bare = _PROTECT.sub("", body)
    if "**" in bare:
        out.append("** が残っています（先方の変換では記号のまま出ます）")
    left = sorted({c for c in re.findall(r'class="([^"]+)"', bare) if c in OUR_PARTS})
    if left:
        out.append("先方に無い部品が残っています: " + "・".join(left))
    return out


def write_external_md(cfg, dest: Path, meta, body, src: Path):
    """別リポジトリの静的サイト用: Markdown を置き、記事1本分の届け物を揃える。

    原稿を置くだけでは、本文の図解とアイキャッチが404になり（画像を複製していなかった）、
    構造化データ・動画・入口・写真・サイトマップの画像の行が1つも届かなかった。
    本文には既に生の HTML（図解の figure・注意の枠）があり、先方の変換は生の HTML を通す前提なので、
    構造化データ・動画・入口は本文に HTML で置く（先方の雛形に手を入れずに出る）。
    head にしか置けないもの（robots の meta・OGP の画像）はフロントマターに載せる:
      image（OGP の絶対URL）・photo（一覧・記事の頭の写真）・robots・video（YouTube の URL）

    sites/<id>.json に md_dialect がある社は、先方の変換が読む形（journal_md）で置く。先方のページが記事・FAQ の
    構造化データ・アイキャッチ・写真を自分で出すので、それらは置かない（重ねると同じ記事が2つの実体に見える）"""
    slug = meta["slug"]
    url = sites_mod.article_url(cfg, meta)
    origin = f"https://{cfg['domain']}"
    root = public_root(cfg, dest)
    images_dir = cfg.get("images_dir") or "images"
    prefix = image_prefix({**cfg, "images_dir": images_dir})
    journal = md_dialect(cfg)
    fm = dict(meta)
    src_path, dst_path = f"/images/{slug}/", f"{prefix}/{slug}/"
    if src_path != dst_path:
        body = body.replace(src_path, dst_path)
        if fm.get("eyecatch"):
            fm["eyecatch"] = str(fm["eyecatch"]).replace(src_path, dst_path)
    chars = len(md2html.plain_text(md2html.convert(body)[0]))
    vb = video_block(meta, dest)
    # 表の数字の横棒グラフは、前後を空行で挟んだ1行の HTML の塊として表の直後に置く（先方の marked は生の HTML を
    # そのまま通す。消毒しない。中の * や = は文字参照にしてあるので、journal_md の読み替えにも拾われない）
    body = table_charts.add_to_markdown(body, cfg)
    if journal:
        body = _md_insert_entries((vb + "\n" + body.lstrip("\n")) if vb else body, cfg)
        html = md2html.convert(body)[0]
        fm, body = journal_md(cfg, meta, body, journal)
        bad = journal_problems(fm, body, journal)
        if bad:
            raise SystemExit(f"BLOCKED(公開不可): {slug} は {cfg.get('name', cfg['id'])} の先方の変換で組み立てが止まるか、"
                             "崩れる形です: " + " / ".join(bad))
    written = []
    ensure_images(meta)
    img_src = ROOT / "site" / "images" / slug
    if img_src.is_dir():
        img_dest = dest / images_dir / slug
        shutil.rmtree(img_dest, ignore_errors=True)
        # アイキャッチには運用会社の名前が入る。先方の雛形が使わない方言では図解だけを届ける
        shutil.copytree(img_src, img_dest, ignore=shutil.ignore_patterns("eyecatch.*") if journal else None)
        written.append(img_dest)
    image = f"{origin}{fm['eyecatch']}" if fm.get("eyecatch") else ""
    if not journal:
        try:
            import photo_shelf
            _, purl = photo_shelf.pick(meta["title"], str(meta.get("keyword") or ""), slug)
            photo = photo_shelf.copy_to(root, purl) if purl else ""
            if photo:
                fm["photo"] = photo
                jpg = photo_shelf.path_of(purl)
                if jpg.is_file():
                    shutil.copy2(jpg, root / "images" / "shelf" / jpg.name)
                    image = f"{origin}/images/shelf/{jpg.name}"
                written += [root / "images" / "shelf"]
        except Exception as e:
            print(f"  写真の棚をスキップ: {e}")
        if image:
            fm["image"] = image
        import search_preview
        fm["robots"] = ", ".join(search_preview.DIRECTIVES)
        if vb:
            fm["video"] = re.search(r'"contentUrl": "([^"]+)"', vb).group(1)
            body = vb + "\n" + body.lstrip("\n")
        body = _md_insert_entries(body, cfg)
        html = md2html.convert(body)[0]
        credit = client_credit(cfg, url)
        body = body.rstrip("\n") + "\n\n" + ld_scripts(cfg, meta, url, html, image, credit, video=not vb)
        # 訳のページとの組（hreflang の値 → URL）。head に出すのは先方の雛形（訳のページの Markdown と同じ alternates の形）
        alts = article_alternates(cfg, dest, meta)
        if alts:
            fm["alternates"] = alts
    if noindex.on(meta):
        # 検索から外した記事: head の robots は先方の雛形がフロントマターから出す（見え方の指定 max-* は付けない）
        fm = noindex.md_front(fm)
        if journal and not any("noindex" in f.read_text(encoding="utf-8", errors="ignore")
                               for f in (dest / "scripts").glob("*.mjs")):
            print(f"要対応: {cfg['id']} の記事 {slug} は検索から外す記事ですが、先方の組み立て（scripts/*.mjs）が "
                  "フロントマターの noindex・robots を読みません。先方の記事ページに robots を出す1行を足してください")
    target = dest / cfg["content_dir"] / f"{slug}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, width=1000)
                      + "---\n" + body, encoding="utf-8", newline="\n")
    page = html + "".join(f'<meta property="og:image" content="{u}">'
                          for u in dict.fromkeys([image, f"{origin}{fm.get('eyecatch') or ''}"]) if u and u != origin)
    written = [target] + _update_external_index(dest, cfg, meta, page=page) + written
    return written, chars


JP_ERA = "%Y年%-m月%-d日"


def insert_mid_cta(html, cfg):
    """本文の中盤に問い合わせへの導線を1つ差し込む。

    記事末のCTAだけだと、読み終えた読者しか見られない。補助金サイトの
    実測では、ボタン押下12回のうち問い合わせへ向かうものが1回だった。
    診断や記事一覧など途中で終わる導線に流れており、問い合わせへの
    入口そのものが足りていない。

    置く場所はH2の切れ目。段落の途中に入れると読みを断ち切る。
    """
    heads = [m.start() for m in re.finditer(r"<h2[ >]", html)]
    if len(heads) < 5:
        return html
    pos = heads[len(heads) // 2]
    return html[:pos] + mid_cta_block(cfg) + "\n" + html[pos:]


# 中ほどの導線の色。サイト設定の cta_colors（主ボタンの色）→ diagram_colors（図の色）→ AI集客ラボの色の順に使う。
# 色を直書きしていたため、補助金の記事の中ほどだけ AI集客ラボの青で、主ボタン（金）と揃っていなかった（2026-10-08）
CTA_COLORS = {"button": "#1b4fa0", "button_ink": "#fff", "soft": "#f4f7fc", "line": "#dbe4f0", "muted": "#5b6980"}
_HEX = r"#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})"
_CSS_COLOR = re.compile(rf"{_HEX}|linear-gradient\(\d{{1,3}}deg(?:,{_HEX}(?: \d{{1,3}}%)?){{2,4}}\)")


def cta_colors(cfg):
    c = dict(CTA_COLORS)
    dia = cfg.get("diagram_colors") or {}
    for k, src in (("button", "accent"), ("soft", "soft"), ("line", "line"), ("muted", "muted")):
        if isinstance(dia.get(src), str) and _CSS_COLOR.fullmatch(dia[src]):
            c[k] = dia[src]
    for k, v in (cfg.get("cta_colors") or {}).items():
        # style 属性へそのまま入れるので、色と線形のグラデーション以外は使わない
        if k in c and isinstance(v, str) and _CSS_COLOR.fullmatch(v):
            c[k] = v
    return c


def mid_cta_block(cfg):
    """中ほどの導線の塊（HTML 1行）。Markdown の原稿へもそのまま置ける形にする（external-md）"""
    # 記事の中ほどは、読み手がまだ「相談する」段階にない。実測で補助金サイトは
    # 記事到達147に対しCTA押下4（2.7%）、診断を前面に出すAI集客ラボは9.4%だった。
    # サイト設定に cta_mid があれば、中ほどだけ軽い入口（診断など）に差し替える
    mid = cfg.get("cta_mid") or {}
    label = mid.get("label") or (cfg.get("cta") or {}).get("label", "無料で相談する")
    url = mid.get("url") or (cfg.get("cta") or {}).get("url", "/#contact")
    note = mid.get("note") or "要件の確認だけでもご利用いただけます"
    tag = "article_mid_diagnosis" if "diagnosis" in url else "article_mid_contact"
    c = cta_colors(cfg)
    return (
        f'<div class="cta-mid" style="background:{c["soft"]};border:1px solid {c["line"]};'
        'border-radius:12px;padding:20px;margin:28px 0;text-align:center">'
        '<p style="margin:0 0 12px;font-weight:700">'
        'ここまでの内容が自社に当てはまるか、確認しませんか。</p>'
        f'<a class="cta-button" href="{url}" data-cta="{tag}" '
        'style="display:inline-block;padding:12px 26px;border-radius:8px;'
        f'background:{c["button"]};color:{c["button_ink"]};text-decoration:none;font-weight:700">{label}</a>'
        f'<p style="margin:10px 0 0;font-size:.82rem;color:{c["muted"]}">'
        f'{note}</p></div>')


def insert_inline_entry(html, cfg):
    """最初の見出しの直下の1文結論の後に、その場の入口を1つ置く（サイト設定に cta_inline がある社だけ）。

    AI集客ラボの inline_tool と同じ考え。記事のボタンは別ページへの誘導だけで、9/5〜10/2 の3サイト合計で
    記事の訪問261に対し押下3だった。配信先のテンプレートは相手のものなので、見た目は style で持ち、
    計測（見えた・押した）も相手の site.js に頼らずこの塊の中で送る
    """
    ent = cfg.get("cta_inline") or {}
    if not ent.get("url") or "cta-inline" in html:
        return html
    heads = list(re.finditer(r"<h2[^>]*>(.*?)</h2>", html, re.S))
    if not heads or re.search(r"よくある質問|まとめ", re.sub(r"<[^>]+>", "", heads[0].group(1))):
        return html
    end = heads[1].start() if len(heads) > 1 else len(html)
    m = re.match(r"\s*<p[ >].*?</p>", html[heads[0].end():end], re.S)
    if not m:
        return html
    pos = heads[0].end() + m.end()
    return html[:pos] + "\n" + inline_entry_block(ent) + html[pos:]


def inline_entry_block(ent):
    """その場の入口の塊（HTML 1行）。Markdown の原稿へもそのまま置ける形にする（external-md）"""
    tool = ent.get("tool", "diagnosis")
    note = f'<p style="margin:8px 0 0;font-size:.8rem;color:#5b6980">{ent["note"]}</p>' if ent.get("note") else ""
    return (
        f'<aside class="cta-inline" data-tool="{tool}" style="margin:24px 0 28px;padding:18px 20px;'
        'border:1px solid #dbe4f0;border-left:4px solid #1b4fa0;border-radius:12px;background:#f4f7fc">'
        f'<p style="margin:0 0 12px;font-weight:700;color:#132445;line-height:1.6">{ent["head"]}</p>'
        f'<a class="cta-button" href="{ent["url"]}" data-cta="article_inline_{tool}" '
        'style="display:inline-block;padding:11px 24px;border-radius:8px;background:#1b4fa0;color:#fff;'
        f'text-decoration:none;font-weight:700">{ent.get("label", "質問に答える")}</a>{note}'
        '<script>(function(){var b=document.currentScript.parentNode,p={page_path:location.pathname,tool:b.getAttribute("data-tool")};'
        'function g(n){if(typeof gtag==="function")gtag("event",n,p);}'
        'if("IntersectionObserver" in window){var o=new IntersectionObserver(function(e){if(e[0].isIntersecting){g("inline_tool_view");o.disconnect();}},{threshold:.6});o.observe(b);}'
        'b.querySelector("a").addEventListener("click",function(){g("inline_tool_submit");});})();</script>'
        '</aside>')


# 入口の塊が自分で送る計測。先方のページに ss-measure（同じ名前で送る）を置くときは外す（二重に数えない）
INLINE_SELF_MEASURE = re.compile(r"<script>\(function\(\)\{var b=document\.currentScript.*?</script>", re.S)


def measure_script(cfg):
    """GA4 の計測（WordPress の橋渡しプラグインと同じ出来事・同じ名前・同じ引数）。測定IDが無い社は空。

    中身は automation/wordpress/ss-quality-gate.php の SSB_MEASURE_JS を唯一の正として読む。
    写しを持つと、片方だけ直したときに方式ごとで数え方がずれ、月次の比較が成り立たなくなる"""
    import wp_bridge
    gid = wp_bridge.ga4_id(cfg)
    if not gid:
        return ""
    php = (Path(__file__).resolve().parent.parent / "automation" / "wordpress" / "ss-quality-gate.php")
    m = re.search(r"const SSB_MEASURE_JS = <<<'JS'\n(.*?)\nJS;", php.read_text(encoding="utf-8"), re.S)
    if not m:
        raise SystemExit("計測の本体（ss-quality-gate.php の SSB_MEASURE_JS）が見つかりません")
    return f'<script id="ss-measure">window.SSB_GA4={json.dumps(gid)};\n{m.group(1)}</script>\n'


def add_measure(page, cfg):
    """管制塔の雛形で描いたページ（FTP・ZIP）に計測を置く。雛形に既にあれば何もしない"""
    tag = measure_script(cfg)
    if not tag or 'id="ss-measure"' in page or "</body>" not in page:
        return page
    page = INLINE_SELF_MEASURE.sub("", page)
    return page.replace("</body>", tag + "</body>", 1)


def youtube_blocked(dest: Path):
    """配信先の CSP（Cloudflare Pages の _headers）が YouTube の埋め込みを許さないか。
    許さないのに埋めると、記事の頭に空の枠が出る（コーポレートは frame-src が Google マップだけ）"""
    for rel in ("_headers", "public/_headers", "static/_headers"):
        f = dest / rel
        if not f.is_file():
            continue
        m = re.search(r"Content-Security-Policy:\s*(.+)", f.read_text(encoding="utf-8", errors="ignore"))
        if not m:
            continue
        pol = {p.strip().split(" ", 1)[0]: p.strip() for p in m.group(1).split(";") if p.strip()}
        rule = pol.get("frame-src") or pol.get("child-src") or pol.get("default-src") or ""
        return "youtube-nocookie.com" not in rule and "*" not in rule.split()
    return False


def video_block(meta, dest: Path):
    """記事の動画の埋め込み（VideoObject つき）。台帳に無い・配信先の CSP が許さないときは空"""
    try:
        import video_embed
        b = video_embed.block(meta)
    except Exception as e:
        print(f"  [警告] 動画の埋め込みを飛ばしました（{str(e)[:40]}）")
        return ""
    if b and youtube_blocked(dest):
        print(f"要対応: {meta['slug']} の動画を埋め込めません。配信先の CSP（_headers）の frame-src に "
              "https://www.youtube-nocookie.com、img-src に https://i.ytimg.com を足してください（site_change）")
        return ""
    return b


def ld_scripts(cfg, meta, url, html, image="", credit=None, video=True):
    """記事の構造化データ（BlogPosting＋FAQPage）の script タグ。中身は WordPress と同じ _wp_jsonld。
    本文に動画の塊（VideoObject つき）を置いた記事は video=False（同じ動画を2つの実体にしない）"""
    ld, extra = _wp_jsonld(cfg, meta, credit_ld(credit, url, meta) if credit else None, url, html, image)
    if not video:
        ld.pop("video", None)
    return "".join('<script type="application/ld+json">' + json.dumps(d, ensure_ascii=False) + "</script>\n"
                   for d in [ld] + extra)


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


def page_dir(cfg):
    """external-html の記事ページを置くフォルダ。URL の接頭辞と同じ場所に置く。
    "blog" 固定だったため、/column の社では記事が /blog/ に置かれ、sitemap・canonical の /column/ が404になった。
    FTP・ZIP の作業場所は blog/ に書いてから接頭辞の場所へ移す（deliver_files.stage_cfg が page_dir を渡す）"""
    return cfg.get("page_dir") or (cfg.get("url_prefix") or "/blog").strip("/") or "blog"


def _route_exists(dest: Path, seg):
    """配信先の作業コピーに、/<seg> で開ける場所があるか（静的ファイル・Next.js の app の経路・転送の規則）"""
    for base in ("", "public", "static", "site", "src/app", "app"):
        if (dest / base / seg).exists():
            return True
    # Next.js の動的な階層の下（src/app/[locale]/journal など）
    for app in (dest / "src" / "app", dest / "app"):
        if app.is_dir() and any(p.is_dir() for p in app.glob(f"[[]*[]]/{seg}")):
            return True
    for rel in ("_redirects", "public/_redirects", "static/_redirects"):
        f = dest / rel
        if f.is_file() and re.search(rf"^/{re.escape(seg)}(/|\s)", f.read_text(encoding="utf-8", errors="ignore"), re.M):
            return True
    return False


def foreign_links(cfg, body, dest=None):
    """原稿の / で始まるリンクのうち、その社に無い場所へ向かうもの。

    AI集客ラボの相談先 /lp/ がコーポレート・補助金の記事の相談ボタンに入り、404 だった（2026-10-08: 2本4か所）。
    Git の社は配信先の作業コピーに在るかで見る。作業コピーの無い方式（FTP・ZIP・WordPress）は、
    AI集客ラボにしか無い入口（/lp/ とカテゴリ）だけを見る"""
    if cfg.get("type") == "self-static":
        return []
    pre = (cfg.get("url_prefix") or "").strip("/").split("/")[0]
    lab = set()
    for sid, c in sites_mod.load_all().items():
        if c.get("type") == "self-static" and sid != cfg.get("id"):
            lab |= {"lp", *(c.get("categories") or {})}
    bad = []
    for path in re.findall(r"""(?:\]\(|href=["'])(/[^)"'\s#?]*)""", body):
        seg = path.strip("/").split("/")[0]
        if path.startswith("//") or seg in ("", "images", pre):
            continue
        if (not _route_exists(dest, seg)) if dest is not None else (seg in lab):
            bad.append(path)
    return sorted(set(bad))


def stop_foreign_links(cfg, meta, body, dest=None):
    bad = foreign_links(cfg, body, dest)
    if bad:
        raise SystemExit(f"BLOCKED(公開不可): {meta['slug']} に {cfg.get('name', cfg['id'])} に無い場所へのリンクがあります: "
                         f"{' / '.join(bad)}（相談先は sites/{cfg['id']}.json の cta.url: {(cfg.get('cta') or {}).get('url', '—')}）")


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
    blog = dest / page_dir(cfg)
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


_I18N_SHELL = """<!DOCTYPE html>
<html lang="{lang_attr}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}｜{site}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{url}">
{hreflang}
<style>
body{{margin:0;background:#fdfcf9;color:#212b3d;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Hiragino Sans","Noto Sans CJK JP",sans-serif;line-height:1.8}}
main{{max-width:760px;margin:0 auto;padding:40px 20px 80px}}
h1{{font-size:1.6rem;line-height:1.4;color:#1d3461}} h2{{font-size:1.15rem;color:#1d3461;margin-top:2em}}
.latest-block{{margin:1.2em 0}} .hub-lead{{font-size:1.02rem}} .hub-note{{font-size:.9rem;color:#5b6472}}
details{{margin:.6em 0;padding:.8em 1em;background:#fff;border:1px solid #e7e2d4;border-radius:10px}}
summary{{font-weight:700;cursor:pointer}} a{{color:#1b4fa0}}
.cat-head h2{{margin:0}}
</style>
</head>
<body><main>
{content}
<p class="hub-note"><a href="https://{domain}/">{site}</a></p>
</main></body>
</html>
"""


def _i18n_pages(cfg, meta, dest: Path):
    """指示のある言語の要約ページを配信先に置き、日本語ページ用の hreflang を返す。
    訳（data/i18n/<lang>/<slug>.json）が無い言語は何もしない"""
    langs = [l for l in (cfg.get("languages") or []) if l in ("en", "zh", "ko")]
    if not langs:
        return None
    try:
        import i18n
    except Exception:
        return None
    attr = {"en": "en", "zh": "zh-Hans", "ko": "ko"}
    pre = (cfg.get("url_prefix") or "/blog").strip("/")
    ja = f"https://{cfg['domain']}/{pre}/{meta['slug']}/"
    have = {}
    for lg in langs:
        p = i18n.OUT / lg / f"{meta['slug']}.json"
        if p.is_file():
            try:
                have[lg] = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    if not have:
        return None
    url_of = lambda lg: f"https://{cfg['domain']}/{lg}/{pre}/{meta['slug']}/"
    tags = [f'<link rel="alternate" hreflang="ja" href="{ja}">', f'<link rel="alternate" hreflang="x-default" href="{ja}">']
    tags += [f'<link rel="alternate" hreflang="{attr[lg]}" href="{url_of(lg)}">' for lg in have]
    import html as _hm
    for lg, d in have.items():
        page = dest / lg / pre / meta["slug"] / "index.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(_I18N_SHELL.format(
            lang_attr=attr[lg], title=_hm.escape(d["title"]), site=_hm.escape(cfg.get("name", "")),
            desc=_hm.escape(d.get("description", "")), url=url_of(lg), hreflang="\n".join(tags),
            content=i18n.page_html(d, ja, lg), domain=cfg["domain"]), encoding="utf-8", newline="\n")
    # 配信物の生成（tools/make_dist.py）が言語のフォルダを配信対象に入れていなければ足す。
    # 入れないと、置いたページが公開されない（補助金サイトの業種ハブで同じことが起きた）
    md = dest / "tools" / "make_dist.py"
    if md.is_file():
        t = md.read_text(encoding="utf-8")
        m = re.search(r"PUBLIC_DIRS\s*=\s*\[([^\]]*)\]", t)
        if m:
            add = [lg for lg in have if f'"{lg}"' not in m.group(1)]
            if add:
                t = t[:m.end(1)] + "".join(f', "{lg}"' for lg in add) + t[m.end(1):]
                md.write_text(t, encoding="utf-8", newline="\n")
    # sitemap にも載せる
    sm = _public_file(dest, "sitemap.xml")
    if sm:
        t = sm.read_text(encoding="utf-8")
        add = "".join(f"  <url>\n    <loc>{url_of(lg)}</loc>\n    <lastmod>{meta['date']}</lastmod>\n  </url>\n"
                      for lg in have if url_of(lg) not in t)
        if add:
            sm.write_text(t.replace("</urlset>", add + "</urlset>"), encoding="utf-8", newline="\n")
    return {"hreflang": "\n".join(tags), "langs": list(have)}


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
    html = apply_html_parts(html, cfg)
    # FAQはテンプレート側が専用セクションを持つので、本文からは先に取り除く
    # （目次を作る前に消さないと、存在しない見出しへのリンクが目次に残る）
    html = re.sub(r"<h2[^>]*>\s*よくある質問\s*</h2>.*?(?=<h2|$)", "", html, flags=re.S)
    # 雛形が冒頭に出す結論・対象読者・時点は本文から外す（動画を頭に足す前に。動画の説明を結論と取り違えない）
    html, lead, target_txt = template_intro(html, tpl, cfg, meta)
    # YouTube に上がった記事動画があれば先頭に埋め込む（build.py と同じ関数。CSP が許さない配信先は飛ばす）
    html = video_block(meta, dest) + html
    html += aggregate_links(cfg, dest, meta)
    credit = client_credit(cfg)
    # 著者の実在（Person + sameAs）。配信先のテンプレートは著者名しか出さないので、
    # 台帳から束ねた sameAs を本文側の JSON-LD で足す（AI集客ラボの記事と同じ人物だと機械に分かる）
    try:
        ap = json.loads((ROOT / "data" / "author_profile.json").read_text(encoding="utf-8"))
        # クライアントの記事の著者は先方の人。運用会社の代表を著者として付けると事実と違う
        if ap.get("same_as") and not credit:
            person = {"@context": "https://schema.org", "@type": "Person", "name": "原口 優",
                      "@id": "https://ai.7senses.co.jp/author/haraguchi/#person",
                      "url": "https://ai.7senses.co.jp/author/haraguchi/", "jobTitle": "セブンセンシズ株式会社 代表取締役",
                      "sameAs": ap["same_as"]}
            html += '\n<script type="application/ld+json">' + json.dumps(person, ensure_ascii=False) + "</script>\n"
    except Exception:
        pass

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

    # 冒頭の結論は雛形の枠に出る。本文から外しても、読む量と扱う実体には数える
    plain = md2html.plain_text(html) + lead

    # 記事が扱う実体（IT導入補助金など）を公式の場所へ結ぶ（AI検索が同じ実体として束ねる）
    import entities
    _about, _mentions = entities.about_and_mentions(f"{meta['title']} {meta.get('keyword', '')}", plain)
    about_json, mentions_json = json.dumps(_about, ensure_ascii=False), json.dumps(_mentions, ensure_ascii=False)
    mod = str(meta.get("modified") or meta["date"])
    vals = {
        "TITLE": meta["title"],
        "TITLE_SHORT": meta["title"][:28],
        "DESCRIPTION": meta["description"],
        "SLUG": meta["slug"],
        "CATEGORY": cfg["categories"].get(meta["category"], meta["category"]),
        "DATE_ISO": str(meta["date"]),
        "DATE_MOD_ISO": mod,
        "DATE_JP": _jp_date(meta["date"]),
        # 「◯年◯月時点」は情報を確かめた時点。書き直した記事で公開月のままだと古く見える
        "DATE_YM": f"{mod[:4]}年{int(mod[5:7])}月",
        "READ_MIN": str(max(3, round(len(plain) / 600))),
        "LEAD_DANGEN": lead,
        "TARGET": target_txt,
        "BODY": insert_mid_cta(insert_inline_entry(html, cfg), cfg),
        "TOC_ITEMS": toc,
        "FAQ_HTML": faq_html,
        "FAQ_JSONLD": faq_jsonld,
        "ABOUT_JSONLD": about_json,
        "MENTIONS_JSONLD": mentions_json,
        "RELATED_LINKS": related,
        # 既定の文言は補助金サイトのもの。お客様の社に補助金の案内が出ないよう、社の設定が無ければ汎用の文にする
        "CTA_TITLE": cfg.get("cta_title") or ("補助金が使えるか、無料で確認しませんか" if not credit
                                              else "まずはお気軽にご相談ください"),
        "CTA_DESC": cfg.get("cta_desc") or (
            "要件の確認から申請書類の準備まで、はじめての方でも進められるようご案内します。" if not credit else ""),
        "CTA_URL": (cfg.get("cta") or {}).get("url") or f"https://{cfg['domain']}/",
        "CTA_LABEL": (cfg.get("cta") or {}).get("label") or "お問い合わせ",
    }
    # 表の数字の横棒グラフ（表の直後・1記事2つまで）。読了時間・扱う実体は上で表だけの本文から数えてある
    vals["BODY"] = table_charts.add_to_html(vals["BODY"], cfg)
    out = tpl
    for k, v in vals.items():
        out = out.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{([A-Z_]+)\}\}", out)
    if left:
        raise SystemExit(f"テンプレートの未置換タグが残っています: {sorted(set(left))}")
    # 配信先のテンプレートが古く dateModified に公開日を入れている場合も、更新日に揃える
    # （書き直しても dateModified が公開日のままだと、鮮度の信号が届かない）
    out = re.sub(r'("dateModified":\s*")[^"]*(")', lambda m_: m_.group(1) + mod + m_.group(2), out)

    # 記事の内容に合う写真を在庫から選び、一覧カードとOGPに当てる。
    # 配信先の一覧は在庫写真を順番に使い回しており、中身と絵が合わないため。
    thumb_url = None
    try:
        import pick_photo
        import photo_shelf
        # まず3サイト共通の写真の棚から（業種・作業ごとに複数枚）。棚が空のときだけ配信先の在庫写真に戻る
        name, url = photo_shelf.pick(meta["title"], str(meta.get("keyword") or ""), meta["slug"])
        src_img = photo_shelf.DIR / f"{Path(url).stem}.webp" if url else None
        sc = "棚"
        if not (src_img and src_img.is_file()):
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

    # 多言語の要約（指示のある社だけ）: 日本語ページの head に hreflang を足し、訳のページを置く
    extra = None if noindex.on(meta) else _i18n_pages(cfg, meta, dest)
    if extra:
        out = out.replace("</head>", extra["hreflang"] + "\n</head>", 1)

    out = apply_credit(out, credit, sites_mod.article_url(cfg, meta), meta)
    # 先方の雛形が robots を持たない・index,follow だけでも、見え方の指定を1つの meta にまとめて足す
    import search_preview
    out = search_preview.robots_tag(out)
    if noindex.on(meta):
        # 検索から外した記事: ページは置き（URL を 404 にしない）、head を noindex,follow にする。
        # 一覧・業種・sitemap・llms.txt（subsidy/pages.py）と関連記事（_recent_articles）はこの印で外す
        out = noindex.set_robots(out)
    # FTP・ZIP の社は管制塔の雛形で描くので、計測（GA4・CTA・フォーム・入口・A/B）もここで置く。
    # Git の社（external-html）は先方の雛形が計測を持つ（補助金サイトは site.js）
    if cfg.get("type") in deliver_files.TYPES:
        out = add_measure(out, cfg)
    page = dest / page_dir(cfg) / meta["slug"] / "index.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(out, encoding="utf-8", newline="\n")

    # 原稿も残す（相手側の重複判定・再生成の材料になる）
    md = dest / cfg["content_dir"] / f"{meta['slug']}.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, md)

    written = [page, md] + _update_external_index(dest, cfg, meta)
    # 訳のページも書いたものとして返す（FTP・ZIP は返したものだけを届けるため、漏れると訳が公開されない）
    if extra:
        pre = (cfg.get("url_prefix") or "/blog").strip("/")
        written += [dest / lg / pre / meta["slug"] for lg in extra["langs"]]
    # 補助金サイトは記事の冒頭と一覧の見出し下に写真を置く（subsidy_photos。何度呼んでも同じ）。
    # サムネイルを作った後に呼ぶ（記事の冒頭はそのサムネイルを出す）
    if (dest / "assets" / "img" / "hero-owner.webp").is_file():
        # 一覧・制度別・業種別のページ、記事途中の案内、写真は管制塔で作って届ける。
        # 以前は補助金サイトの CI（tools/）が作っていたが、2つの仕組みが同じページを書き換えて
        # 食い違ったため、管制塔に一本化した（2026-10-03）
        env = dict(os.environ, SUBSIDY_ROOT=str(dest), PYTHONIOENCODING="utf-8")
        for script in ("subsidy/pages.py", "subsidy_cta.py"):
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / script)], env=env,
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode:
                print(f"  {script} が失敗: {(r.stderr or r.stdout)[-200:]}")
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "subsidy_photos.py"), str(dest)], env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode:
            print(f"  写真の配置が失敗: {(r.stderr or r.stdout)[-200:]}")

    # アイキャッチと本文図解も配信先へ複製する。
    # 本文は /images/<slug>/… を参照しているのに複製していなかったため、
    # 配信済みの記事で図解が全て404になっていた（サムネイルだけが届いていた）。
    img_src = ROOT / "site" / "images" / meta["slug"]
    ensure_images(meta)
    if cfg.get("images_dir") and img_src.is_dir():
        img_dest = dest / cfg["images_dir"] / meta["slug"]
        shutil.rmtree(img_dest, ignore_errors=True)
        shutil.copytree(img_src, img_dest)
        written.append(img_dest)

    thumb_file = dest / "images" / "blog" / meta["slug"] / "thumbnail.webp"
    if thumb_file.is_file():
        written.append(thumb_file)
    return written, len(plain)


def _recent_articles(dest: Path, cfg, exclude_slug, n):
    """相手サイトの既存記事から関連リンク先を選ぶ（新しい順）"""
    out = []
    blog = dest / page_dir(cfg)
    if not blog.exists():
        return out
    # 並びは記事の公開日で決める。作業コピーの mtime はクローンし直すたびに揃って
    # しまい、「新しい順」のつもりが実質ディレクトリ名の順になっていた
    pages = []
    for d in blog.iterdir():
        idx = d / "index.html"
        if not d.is_dir() or d.name == exclude_slug or not idx.is_file():
            continue
        c = idx.read_text(encoding="utf-8")
        m = re.search(r"<h1[^>]*>(.*?)</h1>", c, re.S)
        # 検索から外した記事（noindex）は関連記事に出さない（自社の導線から外す）
        if not m or noindex.page_hidden(c) or noindex.is_hidden(d.name):
            continue
        pub = (re.search(r'"datePublished":\s*"([^"]+)"', c) or [None, ""])[1]
        pages.append((pub, d.name, re.sub(r"<[^>]+>", "", m.group(1)).strip()))
    pages.sort(key=lambda x: (x[0], x[1]), reverse=True)
    pre = (cfg.get("url_prefix") or "/blog").rstrip("/")
    return [(title, f"{pre}/{name}/") for _, name, title in pages[:n]]


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


def _media_xml(dest: Path, cfg, meta, url, page=None):
    """記事の画像（アイキャッチ・図解）と埋め込んだ動画のサイトマップ行。書き出したページから拾う。
    ページを書き出さない方式（external-md・nextjs-json）は、変換した本文を page で渡す。
    図解はこの時点でまだ配信先へ複製していないので、複製元（site/images/<slug>/）にあれば実在とみなす"""
    import search_preview as SP
    from urllib.parse import urlparse
    if page is None:
        f = dest / page_dir(cfg) / meta["slug"] / "index.html"
        if not f.is_file():
            return ""
        page = f.read_text(encoding="utf-8")

    def exists(p):
        rel = p.lstrip("/")
        return any(c.is_file() for c in (dest / rel, dest / "public" / rel, ROOT / "site" / rel))
    o = urlparse(url)
    return SP.media_lines(page, meta["slug"], f"{o.scheme}://{o.netloc}", exists)


def _update_external_index(dest: Path, cfg, meta, page=None):
    """相手サイトのsitemap.xmlとllms.txtに新記事を足す（検出されないと公開の意味がない）"""
    touched = []
    url = sites_mod.article_url(cfg, meta)
    sm = _public_file(dest, "sitemap.xml")
    lt = _public_file(dest, "llms.txt")
    # 検索から外した記事（noindex）の行は、どの記事を配信するときにも外す（noindex のページを sitemap に載せると矛盾する）。
    # 外した記事そのものは、足さずにここで終える
    hid = set(noindex.slugs()) | ({meta["slug"]} if noindex.on(meta) else set())
    for f, prune in ((sm, noindex.prune_sitemap), (lt, noindex.prune_llms)):
        if f and hid:
            t = f.read_text(encoding="utf-8")
            new = prune(t, hid)
            if new != t:
                f.write_text(new, encoding="utf-8", newline="\n")
                touched.append(f)
    if noindex.on(meta):
        return touched
    if sm:
        t = sm.read_text(encoding="utf-8")
        if url not in t:
            entry = (f"  <url>\n    <loc>{url}</loc>\n"
                     f"    <lastmod>{meta['date']}</lastmod>\n" + _media_xml(dest, cfg, meta, url, page) + "  </url>\n")
            import search_preview
            t = search_preview.ensure_ns(t.replace("</urlset>", entry + "</urlset>"))
            sm.write_text(t, encoding="utf-8", newline="\n")
            touched.append(sm)
    if lt:
        t = lt.read_text(encoding="utf-8")
        line = f"- [{meta['title']}]({url}): {meta['description']}"
        # 既にある行は置き換える。足すだけだと、タイトルや説明を直しても
        # AIクローラー向けの案内には古い題名が残り続ける
        pat = re.compile(r"^- \[[^\n]*?\]\(" + re.escape(url) + r"\)[^\n]*$", re.M)
        if pat.search(t):
            new = pat.sub(lambda _m: line, t, count=1)
        else:
            new = t.rstrip("\n") + f"\n{line}\n"
        if new != t:
            lt.write_text(new, encoding="utf-8", newline="\n")
            touched.append(lt)
    # 業種の定義は配信先へ写さない。一覧づくり（scripts/subsidy_pages.py）が本リポジトリの定義を直接読む。
    # 写しを持つと、古い写しで建設業などのページが更新されなくなった（2026-10-03）
    return touched


# ============================================================
# まとめのページ（比較表・テーマ・エリア・今の時期の特集・多言語の要約）
# 中身は aggregate_pages.collect（build.py と同じモジュールの関数）。ここは方式ごとに置くだけ
# ============================================================
def _live_slugs(cfg, dest: Path, extra=()):
    """配信先に既にある記事と、いま書いた記事。まとめのページには公開済みの記事しか載せない（404へ送らない）"""
    if cfg["type"] == "nextjs-json":
        have = {p.stem for p in (dest / cfg["content_dir"]).glob("*.json")}
    elif cfg["type"] == "external-md":
        have = {p.stem for p in (dest / cfg["content_dir"]).glob("*.md")}
    else:
        have = {p.parent.name for p in (dest / page_dir(cfg)).glob("*/index.html")}
    # 検索から外した記事（noindex）は、まとめのページ（比較表・テーマ・用語集・エリア・訳）の材料にしない
    return noindex.live(have | set(extra))


def aggregate_links(cfg, dest: Path, meta):
    """記事の末尾に置く、その記事を含むまとめのページ（テーマ・比較表・エリア・季節）への案内"""
    try:
        import aggregate_pages as AP
        return AP.links_html(AP.cached(cfg, _live_slugs(cfg, dest, {meta["slug"]})), meta["slug"])
    except Exception as e:
        print(f"  [警告] まとめのページへの案内を飛ばしました（{str(e)[:60]}）")
        return ""


def article_alternates(cfg, dest: Path, meta):
    """日本語の記事と訳のページの組（hreflang の値 → URL。ja・x-default・訳のある言語）。訳が無ければ None。
    訳のページを作るのと同じ aggregate_pages.collect の組をそのまま使う（記事の側と訳の側で URL が食い違わない）"""
    if not [l for l in (cfg.get("languages") or []) if l in ("en", "zh", "ko")]:
        return None
    try:
        import aggregate_pages as AP
        tail = f"/{meta['slug']}/"
        return next((dict(p["alternates"]) for p in AP.cached(cfg, _live_slugs(cfg, dest, {meta["slug"]}))
                     if p["kind"] == "i18n" and p["path"].endswith(tail) and p.get("alternates")), None)
    except Exception as e:
        print(f"  [警告] 訳のページとの組（hreflang）を飛ばしました（{str(e)[:60]}）")
        return None


NEXTJS_ALT_PART = "nextjs_alternates.ts"


def nextjs_alternates_part(cfg, dest: Path, warn=True):
    """nextjs-json: 記事 JSON の alternates を generateMetadata の alternates.languages にする部品（lib/ssAlternates.ts）を置く。
    先方の記事ページがこの部品を使っていなければ要対応で知らせる（最初の接続で記事ページに1行足す）。書いたファイルを返す"""
    src = dest / "src" if (dest / "src" / "app").is_dir() else dest
    part = src / "lib" / "ssAlternates.ts"
    body = (ROOT / "templates" / NEXTJS_ALT_PART).read_text(encoding="utf-8")
    written = []
    if not part.is_file() or part.read_text(encoding="utf-8") != body:
        if part.is_file() and "ss-aggregate" not in part.read_text(encoding="utf-8", errors="ignore")[:300]:
            print(f"要対応: {cfg['id']} の {part.relative_to(dest).as_posix()} は先方のファイルなので、hreflang の部品を置きません")
            return []
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_text(body, encoding="utf-8", newline="\n")
        written.append(part)
    app = src / "app"
    used = app.is_dir() and any("ssAlternates(" in f.read_text(encoding="utf-8", errors="ignore")
                                for f in app.rglob("page.tsx") if "ss-aggregate" not in f.read_text(encoding="utf-8", errors="ignore")[:300])
    if warn and not used:
        print(f"要対応: {cfg['id']} の記事ページが訳のページとの組（hreflang）を出していません。記事ページの generateMetadata で "
              "alternates: ssAlternates(post, canonical) を返してください（部品は lib/ssAlternates.ts に置きました）")
    return written


def write_aggregate_html(cfg, dest: Path, live, gone_extra=()):
    """external-html・ftp・zip: まとめのページをその社の雛形で書き、sitemap.xml・llms.txt に載せる。
    先方が自分で作った同じパスのページは上書きしない。(書いたもの, 置いたパス, 消したパス) を返す"""
    import aggregate_pages as AP
    pages = AP.cached(cfg, live)
    tpl = (dest / cfg["template"]).read_text(encoding="utf-8")
    written, keep = [], set()
    for p in pages:
        f = dest / p["path"].strip("/") / "index.html"
        # 訳のページは記事の配信（_i18n_pages）が先に置いたもの。それ以外で印の無いページは先方のもの
        if f.is_file() and p["kind"] != "i18n" and not AP.is_ours(f):
            print(f"要対応: {cfg['id']} の {p['path']} は先方のページなので、まとめのページを置きません")
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(AP.html_doc(tpl, cfg, p), encoding="utf-8", newline="\n")
        written.append(f)
        keep.add(p["path"])
    gone = AP.sweep_html(dest, keep) + [g for g in gone_extra if g not in keep]
    written += AP.update_indexes(dest, cfg, [p for p in pages if p["path"] in keep], gone)
    AP.ensure_public_dirs(dest, [p.strip("/").split("/")[0] for p in sorted(keep)])
    return written, keep, gone


def write_aggregate_nextjs(cfg, dest: Path, live):
    """nextjs-json: 中身を <content_dir の親>/aggregate/pages.json に書き、それを描くページ（templates/nextjs_aggregate_*.tsx）を
    入口ごとに置く。先方が同じ入口（src/app/compare など）を持っていれば触らない"""
    import aggregate_pages as AP
    pages = AP.cached(cfg, live)
    src = dest / "src" if (dest / "src" / "app").is_dir() else dest
    app = src / "app"
    if not app.is_dir():
        print(f"要対応: {cfg['id']} に app ディレクトリが無いため、まとめのページを置けません（App Router の Next.js だけ扱う）")
        return []
    comp = src / "components" / "SsAggregatePage.tsx"
    data_p = dest / Path(cfg["content_dir"]).parent / "aggregate" / "pages.json"

    def ours(f):
        return f.is_file() and AP.MARK in f.read_text(encoding="utf-8", errors="ignore")[:300]

    def imp(frm, to):
        rel = os.path.relpath(to, frm.parent).replace(os.sep, "/")
        return rel if rel.startswith(".") else "./" + rel

    def tpl(name):
        return (ROOT / "templates" / name).read_text(encoding="utf-8")

    tops = {}
    for p in pages:
        tops.setdefault(p["path"].strip("/").split("/")[0], []).append(p)
    old = {}
    if data_p.is_file():
        try:
            old = json.loads(data_p.read_text(encoding="utf-8")).get("pages") or {}
        except ValueError:
            old = {}
    keep, written = {}, []
    for top, ps in sorted(tops.items()):
        idx, slug = app / top / "page.tsx", app / top / "[...slug]" / "page.tsx"
        if (app / top).exists() and not (ours(idx) or ours(slug)):
            print(f"要対応: {cfg['id']} に先方のページ /{top} があるため、まとめのページを置きません")
            continue
        subs = [p for p in ps if p["path"].strip("/") != top]
        for f, want, name in ((idx, len(subs) < len(ps), "nextjs_aggregate_index.tsx"),
                              (slug, bool(subs), "nextjs_aggregate_slug.tsx")):
            if want:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(tpl(name).replace("__KEY__", top).replace("__COMPONENT__", imp(f, comp.with_suffix(""))),
                             encoding="utf-8", newline="\n")
                written.append(f)
            elif ours(f):
                f.unlink()
        for p in ps:
            keep[p["path"].strip("/")] = {k: p[k] for k in ("title", "description", "html", "jsonld", "lang", "url")}
            if p.get("alternates"):
                keep[p["path"].strip("/")]["alternates"] = p["alternates"]
    # 作らなくなった入口のページを消す（管制塔が置いたものだけ）
    live_tops = {k.split("/")[0] for k in keep}
    for d in sorted(app.iterdir()):
        if d.is_dir() and d.name not in live_tops and (ours(d / "page.tsx") or ours(d / "[...slug]" / "page.tsx")):
            shutil.rmtree(d, ignore_errors=True)
    data_p.parent.mkdir(parents=True, exist_ok=True)
    data_p.write_text(json.dumps({"pages": keep}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    og = 'images: [{ url: "/ogp.png" }]' if (dest / "public" / "ogp.png").is_file() else ""
    comp.parent.mkdir(parents=True, exist_ok=True)
    comp.write_text(tpl("nextjs_aggregate_page.tsx").replace("__DATA__", imp(comp, data_p)).replace("__OG__", og)
                    .replace("__CSS__", json.dumps(AP.CSS, ensure_ascii=False)), encoding="utf-8", newline="\n")
    written += [data_p, comp]
    gone = ["/" + k + "/" for k in old if k not in keep]
    written += AP.update_indexes(dest, cfg, [p for p in pages if p["path"].strip("/") in keep], gone)
    return written


def write_aggregate_md(cfg, dest: Path, live):
    """external-md: まとめのページを permalink つきの Markdown（本文は HTML）で pages_dir に置く。
    HTML にするのは先方のビルド（記事と同じ）。置き場は sites/<id>.json の pages_dir（既定は content_dir の隣の pages/）"""
    import aggregate_pages as AP
    from urllib.parse import urlsplit
    pages = AP.cached(cfg, live)
    root = dest / (cfg.get("pages_dir") or (Path(cfg["content_dir"]).parent / "pages").as_posix())
    written, keep = [], set()
    for p in pages:
        f = root / p["path"].strip("/") / "index.md"
        if f.is_file() and "ss_managed: true" not in f.read_text(encoding="utf-8", errors="ignore")[:800]:
            print(f"要対応: {cfg['id']} の {p['path']} は先方のページなので、まとめのページを置きません")
            continue
        link = urlsplit(p["url"]).path
        front = {"title": p["title"], "description": p["description"], "permalink": link, "url": link,
                 "lang": p["lang"], "layout": "page", "ss_managed": True}
        if p.get("alternates"):
            front["alternates"] = p["alternates"]
        lds = "".join('\n<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")
                      + "</script>" for ld in p["jsonld"])
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("---\n" + yaml.safe_dump(front, allow_unicode=True, sort_keys=False) + "---\n\n"
                     + p["html"] + lds + "\n", encoding="utf-8", newline="\n")
        written.append(f)
        keep.add(p["path"])
    gone = []
    for f in sorted(root.rglob("index.md")) if root.is_dir() else []:
        path = "/" + f.parent.relative_to(root).as_posix() + "/"
        if path not in keep and "ss_managed: true" in f.read_text(encoding="utf-8", errors="ignore")[:800]:
            f.unlink()
            gone.append(path)
    written += AP.update_indexes(dest, cfg, [p for p in pages if p["path"] in keep], gone)
    return written


def aggregate_for_git(cfg, dest: Path, extra=()):
    """Git の配信先（external-html・nextjs-json・external-md）: 記事を書いたついでに、まとめのページを作り直す。
    変わらなければ git の差分も出ない。失敗しても記事の配信は止めない（要対応として知らせる）"""
    try:
        live = _live_slugs(cfg, dest, extra)
        if cfg["type"] == "external-html":
            return write_aggregate_html(cfg, dest, live)[0]
        if cfg["type"] == "nextjs-json":
            return write_aggregate_nextjs(cfg, dest, live)
        if cfg["type"] == "external-md":
            return write_aggregate_md(cfg, dest, live)
    except Exception as e:
        print(f"要対応: {cfg['id']} のまとめのページを作れませんでした（{type(e).__name__}: {str(e)[:80]}）")
    return []


def aggregate_for_files(cfg, base: Path, extra=(), force=False):
    """ftp・zip: 作業場所にまとめのページを書く（1日1回まで。WordPress の sync_if_stale と同じ間隔）。
    (書いたもの, 置いたパス) を返す。今日もう届けていれば ([], None)"""
    import aggregate_pages as AP
    st = AP.load_state(cfg["id"])
    if not force and st.get("at") == date.today().isoformat():
        return [], None
    try:
        scfg = deliver_files.stage_cfg(cfg)
        w, keep, _ = write_aggregate_html(scfg, base, _live_slugs(scfg, base, extra),
                                          gone_extra=sorted(set(st.get("paths") or [])))
        return w, keep
    except Exception as e:
        print(f"要対応: {cfg['id']} のまとめのページを作れませんでした（{type(e).__name__}: {str(e)[:80]}）")
        return [], None


def aggregate_files_done(cfg, keep):
    """届けた後: FTP の社は、前に置いて今回作らなかったまとめのページをサーバーから消し、置いたパスを控える。
    ZIP の社は先方が上げるので消せない（控えだけ残す）"""
    import aggregate_pages as AP
    if keep is None:
        return
    old = set(AP.load_state(cfg["id"]).get("paths") or [])
    if cfg["type"] == "ftp" and old - keep:
        with deliver_files.Remote(deliver_files.credentials(cfg)) as r:
            for path in sorted(old - keep):
                n = r.rmtree(path.strip("/"))
                if n:
                    print(f"  まとめのページを消しました: {path}（{n}ファイル）")
    AP.save_state(cfg["id"], keep)



# ============================================================
# WordPress（REST API で投稿する）
# ============================================================
def _wp_auth(cfg):
    """接続情報を返す。合言葉は .env に置き、ログには出さない

    WP_USER_<SITE_ID> / WP_APP_PASSWORD_<SITE_ID> を見る。
    アプリケーションパスワードは WordPress の
    ユーザー > プロフィール > アプリケーションパスワード で発行する。
    """
    import base64
    sid = cfg["id"].upper().replace("-", "_")
    user = os.environ.get(f"WP_USER_{sid}", "")
    pw = os.environ.get(f"WP_APP_PASSWORD_{sid}", "")
    if not (user and pw):
        env = ROOT / ".env"
        if env.is_file():
            for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith(f"WP_USER_{sid}="):
                    user = line.split("=", 1)[1].strip().strip('"')
                elif line.startswith(f"WP_APP_PASSWORD_{sid}="):
                    pw = line.split("=", 1)[1].strip().strip('"')
    if not (user and pw):
        # CI では社ごとの名前を workflow に並べられないため、全社分を1つの Secret で渡す
        # （WP_CREDENTIALS_JSON = {"<site id>": {"user": "...", "password": "..."}}）
        try:
            c = json.loads(os.environ.get("WP_CREDENTIALS_JSON") or "{}").get(cfg["id"]) or {}
            user, pw = c.get("user", ""), c.get("password", "")
        except ValueError:
            pass
    if not (user and pw):
        raise SystemExit(
            f"WordPressの接続情報がありません。.env に次の2行を足してください:\n"
            f"  WP_USER_{sid}=<ユーザー名>\n"
            f"  WP_APP_PASSWORD_{sid}=<アプリケーションパスワード>")
    token = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "User-Agent": "SS-AIO-Pipeline"}


def _wp_api(cfg):
    base = cfg.get("wp_api") or f"https://{cfg['domain']}/wp-json/wp/v2"
    return base.rstrip("/")


def _wp_root(cfg):
    """REST の根（…/wp-json）。橋渡しのプラグインの ss/v1 はここから引く"""
    api = _wp_api(cfg)
    return api[:-len("/wp/v2")] if api.endswith("/wp/v2") else api.rsplit("/wp/v2", 1)[0]


def _wp_call(cfg, path, data=None, method=None, headers=None, raw=None):
    """path が / で始まれば REST の根から（例: /ss/v1/urls）、それ以外は wp/v2 から引く"""
    import urllib.error
    import urllib.request
    url = f"{_wp_root(cfg) if path.startswith('/') else _wp_api(cfg)}/{path.lstrip('/')}"
    h = dict(_wp_auth(cfg))
    if headers:
        h.update(headers)
    body = raw if raw is not None else (
        json.dumps(data, ensure_ascii=False).encode("utf-8") if data else None)
    req = urllib.request.Request(url, data=body, headers=h,
                                 method=method or ("POST" if body else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        raise SystemExit(f"WordPressの応答が {e.code} でした（{path}）\n  {detail}")
    except urllib.error.URLError as e:
        raise SystemExit(f"WordPressに接続できません（{url}）: {e.reason}")


def _wp_term(cfg, slug, name, taxonomy="categories"):
    """カテゴリを slug で探し、無ければ作ってIDを返す"""
    found = _wp_call(cfg, f"{taxonomy}?slug={slug}&per_page=1")
    if isinstance(found, list) and found:
        return found[0]["id"]
    made = _wp_call(cfg, taxonomy, {"slug": slug, "name": name})
    return made["id"]


def _wp_media(cfg, path: Path, alt="", slug=""):
    """アイキャッチを上げてIDを返す。同じ記事のものが既にあれば使い回す"""
    return _wp_media_info(cfg, path, alt, slug).get("id", 0)


WP_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
                  ".gif": "image/gif"}


def _wp_media_info(cfg, path: Path, alt="", slug=""):
    """画像を上げて {id, url} を返す。同じ記事のものが既にあれば使い回す

    記事の画像はどれも eyecatch.png という同じ名前で作られる。
    そのまま上げると、検索で別の記事の画像を拾ってしまう。
    記事のスラッグを付けて、記事ごとに別のファイル名にする。
    """
    if not path.is_file() or path.suffix.lower() not in WP_MEDIA_TYPES:
        return {}
    name = f"{slug}-{path.name}" if slug else path.name
    # WordPress は添付の slug を小文字・英数とハイフンにする（ドットや _ は - に変わる）
    want = re.sub(r"[^a-z0-9-]+", "-", Path(name).stem.lower()).strip("-")
    found = _wp_call(cfg, f"media?search={want}&per_page=5")
    if isinstance(found, list):
        for m in found:
            if m.get("slug") == want:
                return {"id": m["id"], "url": m.get("source_url", "")}
    res = _wp_call(cfg, "media", raw=path.read_bytes(), method="POST",
                   headers={"Content-Type": WP_MEDIA_TYPES[path.suffix.lower()],
                            "Content-Disposition": f'attachment; filename="{name}"'})
    if alt and res.get("id"):
        _wp_call(cfg, f"media/{res['id']}", {"alt_text": alt}, method="POST")
    return {"id": res.get("id", 0), "url": res.get("source_url", "")}


def _wp_body_images(cfg, html, slug):
    """本文の画像（/images/… を指すもの）を WordPress のメディアに上げ、src をその URL に置き換える。
    アイキャッチしか上げていなかったため、WordPress の記事では図解が全部404になっていた"""
    done = {}
    for src in dict.fromkeys(re.findall(r'<img[^>]+src="(/images/[^"]+)"', html)):
        p = ROOT / "site" / src.lstrip("/")
        info = _wp_media_info(cfg, p, slug=slug if f"/images/{slug}/" in src else "")
        if info.get("url"):
            done[src] = info["url"]
        else:
            print(f"  [警告] 本文の画像を上げられませんでした: {src}")
    for a, b in done.items():
        html = html.replace(f'src="{a}"', f'src="{b}"')
    return html, len(done)


def _wp_photo(cfg, meta):
    """写真の棚から選んだ1枚を WordPress のメディアに上げて {id, url}。棚は記事をまたいで同じ写真を使うので、
    記事のスラッグでなく ss-shelf- を付けた名前で1回だけ上げて使い回す（先方の画像と名前がぶつからない）"""
    try:
        import photo_shelf
        _, url = photo_shelf.pick(meta["title"], str(meta.get("keyword") or ""), meta["slug"])
        return _wp_media_info(cfg, photo_shelf.path_of(url), meta.get("title", ""), "ss-shelf") if url else {}
    except Exception as e:
        print(f"  写真の棚をスキップ: {str(e)[:60]}")
        return {}


def _wp_jsonld(cfg, meta, base, url, html, image=""):
    """WordPress の記事の構造化データ。(BlogPosting, そのほかの実体の配列)。

    base はお客様の記事の BlogPosting（credit_ld。著者・発行元・監修者つき）。
    BlogPosting は投稿メタ _ss_jsonld、FAQPage は _ss_jsonld_extra に入れ、先方の mu-plugin が wp_head で出す。
    自社の WordPress（お客様でない）では base が無く、以前は構造化データが空だった"""
    if base:
        ld = dict(base)
    else:
        org = {"@type": "Organization", "name": cfg.get("name", ""), "url": f"https://{cfg['domain']}/"}
        ld = {"@context": "https://schema.org", "@type": "BlogPosting", "@id": url + "#article",
              "headline": meta["title"], "mainEntityOfPage": url, "author": dict(org), "publisher": org}
        # 著者の実在（Person + sameAs）。運用会社の自社サイトだけ（お客様の記事の著者は先方の人）
        try:
            ap = json.loads((ROOT / "data" / "author_profile.json").read_text(encoding="utf-8"))
            if ap.get("same_as"):
                ld["author"] = {"@type": "Person", "name": "原口 優",
                                "@id": "https://ai.7senses.co.jp/author/haraguchi/#person",
                                "url": "https://ai.7senses.co.jp/author/haraguchi/",
                                "jobTitle": "セブンセンシズ株式会社 代表取締役", "sameAs": ap["same_as"]}
        except (OSError, ValueError):
            pass
    ld["description"] = meta.get("description", "")
    if meta.get("date"):
        ld.update({"datePublished": str(meta["date"]), "dateModified": str(meta.get("modified") or meta["date"])})
    if image:
        ld["image"] = image
    try:
        import entities
        about, mentions = entities.about_and_mentions(f"{meta['title']} {meta.get('keyword', '')}",
                                                      md2html.plain_text(html))
        if about:
            ld["about"] = about
        if mentions:
            ld["mentions"] = mentions
    except Exception:
        pass
    try:
        import video_embed
        rec = video_embed.info(meta.get("slug", ""))
        if rec:
            m = re.search(r'<script type="application/ld\+json">(.*?)</script>', video_embed.block(meta), re.S)
            if m:
                v = json.loads(m.group(1))
                v.pop("@context", None)
                ld["video"] = v
    except Exception:
        pass
    extra = []
    faqs = [f for f in (meta.get("faq") or []) if f.get("q") and f.get("a")]
    if faqs:
        extra.append({"@context": "https://schema.org", "@type": "FAQPage",
                      "mainEntity": [{"@type": "Question", "name": str(f["q"]),
                                      "acceptedAnswer": {"@type": "Answer", "text": str(f["a"])}} for f in faqs]})
    return ld, extra


def wp_alternates(cfg, rows, meta, url):
    """WordPress: 日本語の記事と訳のページ（固定ページ /en/<slug>/ など）の組。訳の無い記事・多言語の指示の無い社は {}。
    訳のページを作る wp_bridge.sync_aggregate と同じ組（aggregate_pages.collect）を使う"""
    if not [l for l in (cfg.get("languages") or []) if l in ("en", "zh", "ko")]:
        return {}
    try:
        import wp_bridge
        got = wp_bridge._aggregate(cfg, list(rows) + [{"slug": meta["slug"], "url": url, "type": "post"}], kinds=("i18n",))
        return next((dict(p["alternates"]) for p in got
                     if p["path"].endswith(f"/{meta['slug']}/") and p.get("alternates")), {})
    except Exception as e:
        print(f"  [警告] 訳のページとの組（hreflang）を飛ばしました（{str(e)[:60]}）")
        return {}


def wp_media(html, thumb_url, ld):
    """WordPress の記事の画像・動画（サイトマップの材料）。画像は上げた後の URL（アイキャッチと本文）、
    動画は構造化データの VideoObject から。必須（サムネイル・題・説明・再生の場所）のそろう動画だけ"""
    import search_preview as SP
    imgs = [u for u in dict.fromkeys([thumb_url] + re.findall(r'<img[^>]+src="(https?://[^"]+)"', html)) if u]
    vids = []
    v = (ld or {}).get("video")
    for x in (v if isinstance(v, list) else [v] if isinstance(v, dict) else []):
        thumb = x.get("thumbnailUrl")
        thumb = thumb[0] if isinstance(thumb, list) and thumb else thumb
        if thumb and x.get("name") and x.get("description") and x.get("embedUrl"):
            vids.append({"thumbnail_loc": thumb, "title": x["name"],
                         "description": str(x["description"])[:SP.MAX_VIDEO_DESC], "player_loc": x["embedUrl"],
                         "duration": SP._seconds(x.get("duration"))})
    return {"images": imgs[:SP.MAX_IMAGES], "videos": vids}


def write_wordpress(cfg, meta, body, src: Path, push=False):
    """記事をWordPressへ送る。

    公開してよいかの最終判断は、WordPress側の mu-plugin が行う。
    こちらが publish で送っても、スコアが基準に届かなければ下書きへ戻る。
    二重に見るのは、配信側だけの検査では管理画面からの投稿を止められないため。
    """
    import md2html
    import wp_bridge
    html, _ = md2html.convert(body)
    # 公開URLの一覧（パーマリンク）。本文の内部リンクを実際のURLへ直すのと、構造化データの URL に使う
    rows = wp_bridge.url_rows(cfg, fallback=False)
    html = wp_bridge.rewrite_links(html, rows)
    # 入口・導線は他の配信方式と同じ関数で入れる。入口の塊の計測スクリプトは外す:
    # 投稿者に unfiltered_html が無いと消され、計測は先方の mu-plugin（wp_footer）が同じ名前で送る
    html = insert_mid_cta(insert_inline_entry(html, cfg), cfg)
    html = re.sub(r"<script>\(function\(\)\{var b=document\.currentScript.*?</script>", "", html, flags=re.S)
    # 記事の動画は URL を1行で置く（WordPress が埋め込みに変える）。iframe は投稿者の権限によっては消される
    try:
        import video_embed
        rec = video_embed.info(meta["slug"])
        if rec:
            html = f'\n<p>https://www.youtube.com/watch?v={rec["youtube"]}</p>\n' + html
    except Exception as e:
        print(f"  [警告] 動画の埋め込みを飛ばしました（{str(e)[:40]}）")
    # 同じ業種のまとめ（管制塔が作る固定ページ）があれば、記事の末尾から案内する
    try:
        import industry_hub as IH
        ind = IH.detect(meta.get("title", ""), meta.get("keyword", ""))
        hub = next((r["url"] for r in rows if r.get("managed")
                    and r["url"].rstrip("/").endswith(f"/{wp_bridge.HUB_PARENT[0]}/{ind}")), "") if ind else ""
        if hub:
            name = next(i["name"] for i in IH.load()[0] if i["slug"] == ind)
            html += f'\n<p class="ss-industry"><a href="{hub}" data-cta="article_industry_hub">{name}の記事をまとめて見る</a></p>\n'
    except Exception:
        pass
    # テーマ・比較表・エリア・季節のまとめ（管制塔が作る固定ページ）のうち、この記事を含み、先方に既にあるものへ案内する
    try:
        html += wp_bridge.aggregate_links(cfg, rows, meta["slug"])
    except Exception as e:
        print(f"  [警告] まとめのページへの案内を飛ばしました（{str(e)[:60]}）")
    ensure_images(meta)
    html, n_img = _wp_body_images(cfg, html, meta["slug"])
    # 監修の表示はテーマに欄が無くても出るよう本文に入れる。構造化データは本文に入れない:
    # 投稿ユーザーに unfiltered_html が無いと <script> が除去される。投稿メタ _ss_jsonld に入れ、
    # 先方の mu-plugin（ss-quality-gate.php）が wp_head で出す
    chars = len(re.sub(r"<[^>]+>|\s", "", html))
    credit = client_credit(cfg)
    if credit and credit["byline"]:
        html = credit["byline"] + "\n" + html
    score = int(meta.get("score") or 0)

    cat_slug = meta["category"]
    cat_id = _wp_term(cfg, cat_slug, cfg["categories"].get(cat_slug, cat_slug))

    # アイキャッチ画像は写真の棚から内容に合う1枚（FTP・Next.js と同じ選び方）。棚が空なら文字のアイキャッチ
    info = _wp_photo(cfg, meta)
    eye = meta.get("eyecatch") or ""
    if not info.get("id") and eye:
        info = _wp_media_info(cfg, ROOT / "site" / eye.lstrip("/"), meta.get("title", ""), meta["slug"])
    thumb, thumb_url = info.get("id", 0), info.get("url", "")

    url = wp_bridge.url_map(cfg, rows).get(meta["slug"]) or sites_mod.article_url(cfg, meta)
    ld, extra = _wp_jsonld(cfg, meta, credit_ld(credit, url, meta) if credit else None, url, html, thumb_url)
    jsonld = json.dumps(ld, ensure_ascii=False)
    alts = wp_alternates(cfg, rows, meta, url)

    # --push が付くまでは下書きで入れる。他の形式が「書き込むがpushしない」
    # のと揃える。ここを publish 固定にすると、確認のつもりの実行で公開される
    payload = {
        "slug": meta["slug"], "title": meta["title"], "content": html,
        "excerpt": meta.get("description", ""),
        "status": "publish" if push else "draft",
        "categories": [cat_id],
        "meta": {"_ss_quality_score": score, "_ss_written_by": "agent", "_ss_jsonld": jsonld,
                 "_ss_jsonld_extra": json.dumps(extra, ensure_ascii=False) if extra else "",
                 # 訳のページとの組。head の hreflang は先方の mu-plugin が出す（訳のページが公開されているものだけ）
                 "_ss_alternates": json.dumps(alts, ensure_ascii=False) if alts else "",
                 # 原稿の指紋（publish_gap が /ss/v1/urls で本文の更新が届いたかを照合する）と、画像・動画のサイトマップの
                 # 材料（mu-plugin 2.0.3 が /ss-media-sitemap.xml に出す）。古い mu-plugin は黙って捨てる
                 "_ss_source_hash": source_hash(src) if Path(src).is_file() else "",
                 "_ss_media": json.dumps(wp_media(html, thumb_url, ld), ensure_ascii=False)},
    }
    if thumb:
        payload["featured_media"] = thumb

    exist = _wp_call(cfg, f"posts?slug={meta['slug']}&status=publish,draft,pending&per_page=1")
    if isinstance(exist, list) and exist:
        res = _wp_call(cfg, f"posts/{exist[0]['id']}", payload, method="POST")
        how = "更新"
    else:
        res = _wp_call(cfg, "posts", payload, method="POST")
        how = "新規"

    # 先方のゲートは、メタが保存されたあとに公開を下書きへ戻す。
    # 投稿時の応答は、その前の状態を返すことがある。取り直して確かめる
    pid = res.get("id")
    if pid:
        after = _wp_call(cfg, f"posts/{pid}?context=edit&_fields=status,link,meta")
        if isinstance(after, dict) and after.get("status"):
            res = {**res, **after}
    status = res.get("status", "?")
    link = res.get("link", "")
    # 初めての記事は、投稿するまでパーマリンクが分からない。分かったら構造化データの URL を直す
    if pid and status == "publish" and link and link != url:
        ld2, _ = _wp_jsonld(cfg, meta, credit_ld(credit, link, meta) if credit else None, link, html, thumb_url)
        _wp_call(cfg, f"posts/{pid}", {"meta": {"_ss_jsonld": json.dumps(ld2, ensure_ascii=False)}}, method="POST")
    print(f"配信先: {cfg['name']}（WordPress / {cfg['domain']}）")
    print(f"  {how}: 投稿ID {res.get('id')} / カテゴリ {cat_slug}"
          + (f" / アイキャッチ {thumb}" if thumb else "") + (f" / 本文の画像 {n_img}枚" if n_img else ""))
    print(f"  本文: {chars:,}字 / score {score}")
    m = res.get("meta")
    if jsonld and isinstance(m, dict) and not m.get("_ss_jsonld"):
        # 古い mu-plugin は _ss_jsonld を登録していないので、WordPress が黙って捨てる
        print(f"要対応: {cfg['id']} の構造化データが保存されませんでした。先方の mu-plugin を "
              "automation/wordpress/ss-quality-gate.php の最新に差し替えてください")

    if status == "publish":
        print(f"  公開しました: {link}")
        # llms.txt・IndexNow の鍵・計測の設定を揃える（静的サイトの _update_external_index に当たる）
        try:
            for note in wp_bridge.sync_if_stale(cfg, rows):
                print(note)
            wp_bridge.push_settings(cfg)
        except SystemExit as e:
            print(f"要対応: {cfg['id']} の橋渡し（llms.txt・計測の設定）に届きません。先方の mu-plugin を "
                  f"最新に差し替えてください（{str(e)[:80]}）")
    elif not push:
        print(f"  下書きとして入れました（投稿ID {res.get('id')}）")
        print("  ※ --push を付けると公開します")
        return True
    else:
        why = ""
        m = res.get("meta") or {}
        if isinstance(m, dict):
            why = m.get("_ss_gate_last_reason") or ""
        print(f"  × 公開されませんでした（状態: {status}）")
        print(f"    {why or 'WordPress側の品質ゲートが公開を止めています'}")
        print("    基準を満たしてから再実行してください")
        return False
    return True


def search_files(cfg, dest: Path):
    """検索エンジンへの通知に要るファイル（IndexNow の鍵・Bing の確認ファイル）を、配信と一緒に直下へ置く。
    お客様の社で、公開直後の通知が鍵ファイルの無いドメインとして拒否されないため（search_connect.place）。
    置けなくても記事の配信は止めない（翌日の通知の工程が要対応で知らせる）"""
    try:
        import search_connect
        return search_connect.place(cfg, dest)
    except Exception as e:
        print(f"  [警告] 通知用のファイルを置けませんでした（{type(e).__name__}）")
        return []


def _delivered(cfg, meta):
    """この記事が配信先に既にあるか。(在るか, 作業コピー) を返す。

    書き出し先は各 writer と同じ場所を見る（ずれると、配信済みを新記事と取り違える）。
    作業コピーを作った場合は返して、配信でそのまま使う（取り直さない）
    """
    slug = meta["slug"]
    if cfg["type"] == "self-static":
        return (ROOT / "site" / meta["category"] / slug / "index.html").is_file(), None
    if cfg["type"] == "wordpress":
        found = _wp_call(cfg, f"posts?slug={slug}&status=publish&per_page=1&_fields=id")
        return bool(isinstance(found, list) and found), None
    if cfg["type"] in deliver_files.TYPES:
        return slug in deliver_files.load_index(cfg), None
    dest = ensure_clone(cfg, _push_token())
    where = {"nextjs-json": dest / cfg["content_dir"] / f"{slug}.json",
             "external-md": dest / cfg["content_dir"] / f"{slug}.md",
             "external-html": dest / page_dir(cfg) / slug / "index.html"}.get(cfg["type"])
    return bool(where and where.is_file()), dest


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
    # git の衝突マーカーが残った原稿は配信しない。「=======」が見出しとして描かれ、
    # 「<<<<<<< Updated upstream」が H1 として公開されていた（2026-09-29: 17本）
    if re.search(r"^(<<<<<<< |>>>>>>> |=======\s*$)", body, re.M):
        raise SystemExit(f"{args.slug}: git の衝突マーカーが原稿に残っています。解いてから配信してください")
    # 当社の採択率・支援社数（根拠の母数・期間が無い）と、当社が申請書類を作成・代行すると読める文は
    # 配信しない（景品表示法・行政書士法。定型文として約75本に広がっていた 2026-10-07）
    import legal_claims
    _legal = legal_claims.find(src.read_text(encoding="utf-8"))
    if _legal:
        raise SystemExit(f"{args.slug}: 当社の採択率・支援社数、または申請書類の作成・代行と読める文があります"
                         f"（{_legal[0][0]}: {_legal[0][1][:60]}）。python scripts/legal_claims.py で確かめて直してください")
    score = meta.get("score") or 0
    if not gate_ok(meta):
        raise SystemExit(f"公開基準未達のため配信しません: score={score}"
                         f" / 観点 {meta.get('score_breakdown') or '—'}"
                         "（90点以上かつ各観点の足切りを通ることが必要）")
    # 量産の指紋は、配信先にまだ無い記事だけに当てる。配信済みの直しの再配信まで止めると、
    # 既にある同型の組を書き分ける修正すら出せなくなる。date だけで判定すると、
    # 配信済みの記事が後から書かれた記事との重なりで再配信を止められ続ける。
    # 監修の判定より先に見る（品質NGの記事を HELD にすると、書き直しに回らない）
    import scaled_guard
    bad = scaled_guard.check(args.slug)
    dest = None
    if bad:
        delivered, dest = _delivered(cfg, meta)
        if not delivered:
            raise SystemExit("BLOCKED(公開不可): " + " / ".join(bad))
    # 配信先のテンプレートは監修者を固定で表示する。記録の無い記事を出すと表示が実態と食い違う
    import editorial_review
    if not editorial_review.reviewed(args.slug):
        raise SystemExit(f"HELD(監修待ち): {args.slug} は監修の記録がありません"
                         f"（確認したら GitHub の Actions →「監修の記録」に {args.slug} を入れて実行。"
                         "配信と台帳への記録まで行います）")
    if meta["category"] not in cfg.get("categories", {}):
        raise SystemExit(f"カテゴリ '{meta['category']}' は {cfg['id']} に定義されていません"
                         f"（候補: {', '.join(cfg.get('categories', {}))}）")
    if sites_mod.is_client(cfg["id"]):
        # お客様の記事に運用会社の名前・実績・自社サイトへのリンクを出さない（監修者はお客様ご本人）。
        # その社の operator_ok に書いた語だけは通す（CONFLUX の「セブンセンシズ株式会社」。2026-10-08 運用者の決定）
        leak = sites_mod.operator_leaks(f"{meta.get('title', '')}\n{meta.get('description', '')}\n"
                                        f"{json.dumps(meta.get('faq') or [], ensure_ascii=False)}\n{body}", cfg)
        # ヒアリングシートの「使ってはいけない表現」（医療広告・景表法など）。シートで聞いて設定に
        # 書いていたのに、どこも読んでいなかった
        leak += [f"使えない表現「{w}」" for w in ((cfg.get("rules") or {}).get("ng_words") or [])
                 if w and w in f"{meta.get('title', '')}{meta.get('description', '')}{body}"]
        if leak:
            raise SystemExit(f"BLOCKED(公開不可): {args.slug} にお客様の記事に出せないものがあります: "
                             + " / ".join(dict.fromkeys(leak)))
        # 公開前の確認を「要」にした社（医療など）は、確認の記録が付くまで配信しない
        if (cfg.get("rules") or {}).get("review_before_publish") and args.slug not in editorial_review.load():
            raise SystemExit(f"HELD(監修待ち): {args.slug} は {cfg['name']} の公開前の確認がまだです"
                             f"（確認が済んだら python scripts/editorial_review.py --approve {args.slug}）")

    # 描画の崩れは、ここで一度だけ見る。各writerの中に書くと、配信方式が
    # 増えたときに必ず漏れる（実際 external-html と wordpress には検査が無く、
    # 表がパイプ記号のまま5本配信されていた）。全方式がこの行を必ず通る。
    for name, sample, fix in render_check.problems(md2html.convert(body)[0]):
        print(f"  [警告] {meta['slug']}: {name}"
              + (f" 「{sample}」" if sample else "") + f" → {fix}")

    if cfg["type"] == "self-static":
        print(f"{cfg['id']} は本リポジトリのサイトです。scripts/build.py で公開してください。")
        return

    # その社に無い場所へのリンク（AI集客ラボの /lp/ など）は配信しない。Git の社は作業コピーを取った後に見る
    if cfg["type"] == "wordpress" or cfg["type"] in deliver_files.TYPES:
        stop_foreign_links(cfg, meta, body)

    if cfg["type"] == "wordpress":
        ok = write_wordpress(cfg, meta, body, src, push=args.push)
        raise SystemExit(0 if ok else 1)

    # Git を使わない配信先（レンタルサーバーの FTP・ZIP 納品）も、書き出しは external-html と同じ
    if cfg["type"] in deliver_files.TYPES:
        base = deliver_files.stage(cfg)
        placed = site_files.ensure(cfg, base, base / "blog")
        written, chars = write_external_html(deliver_files.stage_cfg(cfg), base, meta, body, src)
        written += [p for p in placed if p not in written]
        written.append(stamp_manifest(cfg, base, meta, src))
        written += search_files(cfg, base)
        agg, keep = aggregate_for_files(cfg, base, {meta["slug"]})
        written += agg
        print(f"配信先: {cfg['name']}（{cfg['type']}）/ 本文: {chars:,}字 / score {score}")
        print(f"  公開URL（予定）: {sites_mod.article_url(cfg, meta)}")
        if deliver_files.deliver(cfg, meta, written, base, args.push):
            aggregate_files_done(cfg, keep)
        return

    token = _push_token()
    dest = dest or ensure_clone(cfg, token)
    stop_foreign_links(cfg, meta, body, dest)
    # 直下の llms.txt・robots.txt（と静的サイトの sitemap.xml）が無ければ作り、AI クローラーを塞いでいれば直す。
    # 書き出しより先に置く（記事の行は書き出しが既にあるファイルへ足すため）
    placed = site_files.ensure(cfg, dest, dest / page_dir(cfg))

    if cfg["type"] == "nextjs-json":
        written, chars = write_nextjs_json(cfg, dest, meta, body)
    elif cfg["type"] == "external-md":
        written, chars = write_external_md(cfg, dest, meta, body, src)
    elif cfg["type"] == "external-html":
        written, chars = write_external_html(cfg, dest, meta, body, src)
    else:
        raise SystemExit(f"未対応のサイト種別: {cfg['type']}")
    written += aggregate_for_git(cfg, dest, {meta["slug"]})

    written.append(stamp_manifest(cfg, dest, meta, src))
    written += search_files(cfg, dest) + [p for p in placed if p not in written]

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
    urls = [f"https://x-access-token@github.com/{cfg['repo']}.git", plain_url] if token else [plain_url]
    env = git_auth(token)
    for attempt in range(2):
        for i, u in enumerate(urls):
            # トークン付きのURLにだけ askpass を渡す。素のURLは手元の資格情報に任せる
            if try_run(["git", "push", u, f"HEAD:{cfg['branch']}"], cwd=dest,
                       env=(env if i == 0 else None)):
                if i:
                    print("※ SITE_PUSH_TOKEN では認証できませんでした。PATの再発行が必要です")
                print("push完了。対象サイトのビルドが自動で走ります。")
                return
        if attempt == 0:
            # 押せない理由は権限だけではない。配信先が先に進んでいると弾かれる。
            # それを「トークンの問題」と伝えると、無関係な再発行に時間を使わせる。
            # 実際、配信先が1コミット進んでいるだけで4本ごとに止まっていた。
            print("  押せませんでした。配信先の変更を取り込んで、もう一度試します")
            if not (try_run(["git", "fetch", "origin"], cwd=dest, env=env)
                    and try_run(["git", "rebase", f"origin/{cfg['branch']}"], cwd=dest)):
                # 取り込みに失敗したら必ず中断して元に戻す。途中のまま残すと、次の配信の
                # rebase が「already a rebase-merge directory」で全部落ちた（2026-09-28〜29: 1本おきに失敗）
                try_run(["git", "rebase", "--abort"], cwd=dest)
                break
    raise SystemExit(
        "pushできません。次の順に確かめてください。\n"
        "  1. python scripts/token_check.py で TOKEN_OK=yes か\n"
        "     （権限不足なら Contents: Read and write を付ける）\n"
        "  2. 配信先に手を入れていないか（衝突していると取り込めません）\n"
        "  記事は未配信のままです")


if __name__ == "__main__":
    main()
