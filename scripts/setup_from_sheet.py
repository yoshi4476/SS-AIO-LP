# -*- coding: utf-8 -*-
"""ヒアリングシート（Excel）から、サイト一式を作る

これまでは回答を見ながら設定JSONを手で書き、サイトのHTMLも手で用意していた。
転記の間違いに気づけず、記事を作り始めてから作り直しになることがあった。

記入済みのExcelを渡せば、次を一度に作る。
  ・sites/<id>.json          サイト設定
  ・docs/kw-<id>.md          KW計画の置き場
  ・site-<id>/               サイトの骨格（トップ・会社概要・問い合わせ・
                             プライバシー・カテゴリ一覧）
  ・setup-memo-<id>.md       次にやることの控え

使い方:
    python scripts/setup_from_sheet.py <記入済みExcel>            # 確認だけ
    python scripts/setup_from_sheet.py <記入済みExcel> --write    # 実際に作る
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def cells(ws):
    """「#」列の記号をキーに、記入欄（3列目）を拾う"""
    out = {}
    for row in ws.iter_rows(values_only=True):
        if not row or not row[0]:
            continue
        key = str(row[0]).strip()
        if re.fullmatch(r"[A-K]\d{1,2}", key):
            out[key] = str(row[2]).strip() if len(row) > 2 and row[2] else ""
    return out


def split(text):
    """「A、B / C」のような書き方をまとめて配列にする"""
    if not text:
        return []
    parts = re.split(r"[、,／/\n・]+", text)
    return [p.strip() for p in parts if p.strip()]


def slugify(text, fallback="site"):
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t or fallback


def category_rows(ws):
    """カテゴリは表で書かれている。「カテゴリ名（表示用）」の見出しの下を拾う"""
    out, hit = [], False
    for row in ws.iter_rows(values_only=True):
        if not row:
            continue
        head = str(row[0] or "")
        if "カテゴリ名" in head:
            hit = True
            continue
        if hit:
            if not row[0]:
                if out:
                    break          # 空行が来たら表の終わり
                continue
            if re.fullmatch(r"[A-K]\d{1,2}", str(row[0]).strip()):
                break              # 次の面に入った
            name = str(row[0]).strip()
            slug = str(row[1]).strip() if len(row) > 1 and row[1] else ""
            out.append((name, slug))
    return out


def read(path):
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    a, cats = {}, []
    for ws in wb.worksheets:
        a.update(cells(ws))
        cats += category_rows(ws)
    a["_categories"] = cats
    return a


def to_config(a):
    domain = a.get("A4", "").replace("https://", "").replace("http://", "").strip("/ ")
    # ドメインの先頭だと「media」「www」など、どのクライアントでも同じ名前になる。
    # 意味のある部分を選ぶ。
    parts = [p for p in domain.split(".")
             if p not in ("www", "media", "blog", "lp", "corp", "co", "jp", "com", "net")]
    site_id = slugify(parts[0] if parts else a.get("A3", ""))
    prefix = a.get("A5", "/blog/").strip()
    prefix = "/" + prefix.strip("/").split("/")[0] if prefix.strip("/") else "/blog"

    kind = a.get("A6", "")
    if "Next" in kind:
        site_type = "nextjs-json"
    elif "Markdown" in kind:
        site_type = "external-md"
    elif kind:
        site_type = "external-html"
    else:
        site_type = "self-static"

    cats = {}
    for i, (name, slug) in enumerate(a.get("_categories", []), 1):
        cats[slug or slugify(name, "cat" + str(i))] = name
    if not cats:
        for i, name in enumerate(split(a.get("D1", "")) or ["お役立ち"], 1):
            cats[slugify(name, "cat" + str(i))] = name

    return {
        "id": site_id,
        "name": a.get("A3", "") or "（メディア名）",
        "domain": domain or "example.com",
        "repo": "", "branch": "main",
        "type": site_type,
        "content_dir": "content", "url_prefix": prefix,
        "ga4_property_id": a.get("H1", ""),
        "kw_plan": "docs/kw-" + site_id + ".md",
        "theme": a.get("B1", ""),
        "audience": a.get("B2", ""),
        "owns": split(a.get("C1", "")),
        "avoid": split(a.get("C2", "")),
        "categories": cats,
        "kw_seeds": {"industries": split(a.get("E1", "")),
                     "intents": split(a.get("E2", ""))},
        "cta_title": a.get("G1", "") or "無料でご相談ください",
        "cta_desc": a.get("G4", ""),
        "cta": {"label": a.get("G3", "") or "無料相談する",
                "url": a.get("G2", ""), "note": a.get("G4", "")},
        "x_tags": [],
        # 会社情報。サイトの雛形とE-E-A-Tの記述に使う
        "company": {
            "name": a.get("K14", "") or a.get("A1", ""),
            "corporate_number": a.get("A2", ""),
            "address": a.get("K15", ""),
            "representative": a.get("K16", ""),
            "founded": a.get("K17", ""),
            "business": a.get("K18", ""),
            "license": a.get("K19", ""),
            "email": a.get("H4", ""),
        },
        "facts": [x for x in (a.get("F1", ""), a.get("F2", ""),
                              a.get("F3", ""), a.get("F4", "")) if x],
    }


def check(cfg):
    ng, warn = [], []
    if not cfg["domain"] or cfg["domain"] == "example.com":
        ng.append("A4 公開ドメインが空です")
    if not cfg["theme"]:
        ng.append("B1 何のメディアかが空です")
    if not cfg["audience"]:
        ng.append("B2 誰に向けたものかが空です")
    if not cfg["owns"]:
        ng.append("C1 扱うテーマの語が空です")
    if not cfg["facts"]:
        ng.append("F 一次情報が空です。ここが無いと引用されない記事になります")
    if not cfg["avoid"]:
        warn.append("C2 扱わない領域が空です。他サイトとの territory 検査が効きません")
    n = len(cfg["kw_seeds"]["industries"]) * len(cfg["kw_seeds"]["intents"])
    if n < 100:
        warn.append("E1×E2 が" + str(n) + "通りしかありません（200通り以上あるとKWが枯れにくい）")
    if not cfg["ga4_property_id"]:
        warn.append("H1 GA4のプロパティIDが空です。流入を測れません")
    if not cfg["company"]["name"]:
        warn.append("運営会社名が空です。E-E-A-Tの評価に影響します")
    return ng, warn


def page(title, body, cfg, depth=0):
    """サイトの骨格。凝った見た目は後から差し替える前提で、構造だけ整える"""
    c = cfg["company"]
    root = "../" * depth
    nav = "\n".join(
        '      <a href="/' + s + '/">' + n + "</a>"
        for s, n in cfg["categories"].items())
    return (
        "<!DOCTYPE html>\n<html lang=\"ja\">\n<head>\n"
        "<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>" + title + "｜" + cfg["name"] + "</title>\n"
        "<meta name=\"description\" content=\"" + cfg["theme"][:110] + "\">\n"
        "<link rel=\"canonical\" href=\"https://" + cfg["domain"] + "/\">\n"
        "<link rel=\"stylesheet\" href=\"/" + root + "css/style.css\">\n"
        "</head>\n<body>\n"
        "<header class=\"site-header\">\n  <div class=\"inner\">\n"
        "    <a class=\"brand\" href=\"/\">" + cfg["name"] + "</a>\n"
        "    <nav class=\"global-nav\">\n" + nav + "\n"
        "      <a href=\"/about/\">運営者情報</a>\n"
        "      <a href=\"/contact/\" class=\"nav-cta\">お問い合わせ</a>\n"
        "    </nav>\n  </div>\n</header>\n"
        "<main class=\"article\">\n" + body + "\n</main>\n"
        "<footer class=\"site-footer\">\n  <div class=\"inner\">\n"
        "    <p class=\"addr\">運営: " + c["name"] + "<br>" + c["address"] + "</p>\n"
        "    <nav>\n"
        "      <a href=\"/about/\">運営者情報</a>\n"
        "      <a href=\"/contact/\">お問い合わせ</a>\n"
        "      <a href=\"/privacy/\">プライバシーポリシー</a>\n"
        "    </nav>\n"
        "    <div class=\"copyright\">© " + c["name"] + "</div>\n"
        "  </div>\n</footer>\n</body>\n</html>\n")


def build_site(cfg, out):
    c = cfg["company"]
    top = (
        "  <header class=\"article-header\">\n"
        "    <h1>" + cfg["name"] + "</h1>\n"
        "    <p class=\"lead\">" + cfg["theme"] + "</p>\n"
        "  </header>\n"
        "  <p>" + cfg["audience"] + "に向けて発信しています。</p>\n"
        "  <section class=\"cta\">\n"
        "    <p class=\"cta-copy\">" + cfg["cta_title"] + "</p>\n"
        "    <a class=\"btn btn-primary\" href=\""
        + (cfg["cta"]["url"] or "/contact/") + "\">" + cfg["cta"]["label"] + "</a>\n"
        "  </section>")

    about = (
        "  <header class=\"article-header\"><h1>運営者情報</h1></header>\n"
        "  <h2>運営会社</h2>\n"
        "  <div class=\"table-wrap\"><table><tbody>\n"
        "    <tr><th>会社名</th><td>" + c["name"] + "</td></tr>\n"
        "    <tr><th>法人番号</th><td>" + c["corporate_number"] + "</td></tr>\n"
        "    <tr><th>代表者</th><td>" + c["representative"] + "</td></tr>\n"
        "    <tr><th>設立</th><td>" + c["founded"] + "</td></tr>\n"
        "    <tr><th>所在地</th><td>" + c["address"] + "</td></tr>\n"
        "    <tr><th>事業内容</th><td>" + c["business"] + "</td></tr>\n"
        "    <tr><th>許認可・資格</th><td>" + c["license"] + "</td></tr>\n"
        "  </tbody></table></div>\n"
        "  <h2>編集方針</h2>\n"
        "  <p>実務で得た一次情報をもとに記事を制作しています。事実と意見を分け、"
        "出典を明記します。情報の時点を示し、古くなった内容は定期的に更新します。</p>")

    contact = (
        "  <header class=\"article-header\"><h1>お問い合わせ</h1></header>\n"
        "  <p>" + (cfg["cta_desc"] or "お気軽にご相談ください。") + "</p>\n"
        "  <p>メール: " + c["email"] + "</p>\n"
        "  <!-- フォームは管制塔GASのURLを action に設定して差し替える -->")

    privacy = (
        "  <header class=\"article-header\"><h1>プライバシーポリシー</h1></header>\n"
        "  <p>" + c["name"] + "（以下「当社」）は、個人情報の保護に関する法律および"
        "関連法令を遵守し、以下のとおり個人情報を適切に取り扱います。</p>\n"
        "  <h2>1. 取得する情報</h2>\n"
        "  <p>お問い合わせフォームを通じて、氏名・会社名・メールアドレス・電話番号・"
        "ご相談内容を取得します。</p>\n"
        "  <h2>2. 利用目的</h2>\n"
        "  <p>お問い合わせへの回答、サービスのご案内に利用します。</p>\n"
        "  <h2>3. 第三者提供</h2>\n"
        "  <p>法令に基づく場合を除き、本人の同意なく第三者へ提供しません。</p>\n"
        "  <h2>4. 開示・訂正・削除</h2>\n"
        "  <p>ご本人からのお申し出があった場合、速やかに対応します。</p>\n"
        "  <p>連絡先: " + c["email"] + "</p>")

    pages = {
        "index.html": page(cfg["name"], top, cfg),
        "about/index.html": page("運営者情報", about, cfg, 1),
        "contact/index.html": page("お問い合わせ", contact, cfg, 1),
        "privacy/index.html": page("プライバシーポリシー", privacy, cfg, 1),
    }
    for slug, name in cfg["categories"].items():
        body = ("  <header class=\"article-header\">\n"
                "    <h1>" + name + "</h1>\n"
                "    <p class=\"lead\">" + name + "に関する記事の一覧です。</p>\n"
                "  </header>\n"
                "  <!-- 記事一覧は build.py が生成します -->")
        pages[slug + "/index.html"] = page(name, body, cfg, 1)

    for rel, html in pages.items():
        f = out / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(html, encoding="utf-8", newline="")

    css = ROOT / "site" / "css" / "style.css"
    if css.is_file():
        (out / "css").mkdir(exist_ok=True)
        (out / "css" / "style.css").write_text(
            css.read_text(encoding="utf-8"), encoding="utf-8", newline="")
    return len(pages)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit("使い方: python scripts/setup_from_sheet.py <記入済みExcel> [--write]")
    cfg = to_config(read(Path(args[0])))
    ng, warn = check(cfg)

    print("■ " + cfg["name"] + "（" + cfg["id"] + "）")
    print("    ドメイン: " + cfg["domain"] + cfg["url_prefix"] + "/")
    print("    種別: " + cfg["type"])
    print("    カテゴリ: " + " / ".join(cfg["categories"].values()))
    ind = len(cfg["kw_seeds"]["industries"])
    itn = len(cfg["kw_seeds"]["intents"])
    print("    KWの起点: 業種" + str(ind) + " × 意図" + str(itn)
          + " = " + str(ind * itn) + "通り")
    print("    一次情報: " + str(len(cfg["facts"])) + "件")
    for m in ng:
        print("    × " + m)
    for m in warn:
        print("    ! " + m)
    if ng:
        raise SystemExit("\n  記入漏れがあるため作成しません。埋めてから再実行してください")
    if "--write" not in sys.argv:
        print("\n  確認のみ（--write を付けると作成します）")
        return

    (ROOT / "sites").mkdir(exist_ok=True)
    (ROOT / "sites" / (cfg["id"] + ".json")).write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    plan = ROOT / cfg["kw_plan"]
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text("# " + cfg["name"] + " KW計画\n\n対象: " + cfg["audience"]
                    + "\n\n（kw_discover.py が自動補充します）\n", encoding="utf-8")
    out = ROOT / ("site-" + cfg["id"])
    n_page = build_site(cfg, out)

    memo = ROOT / ("setup-memo-" + cfg["id"] + ".md")
    memo.write_text(
        "# " + cfg["name"] + " セットアップの控え\n\n"
        "## 作られたもの\n"
        "- sites/" + cfg["id"] + ".json\n"
        "- " + cfg["kw_plan"] + "\n"
        "- site-" + cfg["id"] + "/（" + str(n_page) + "ページ）\n\n"
        "## 次にやること\n"
        "1. サイトを公開先へ設置し、repo を sites/" + cfg["id"] + ".json に書く\n"
        "2. GA4とSearch Consoleにサービスアカウントを追加（Search Consoleはオーナー）\n"
        "3. python scripts/kw_discover.py --site " + cfg["id"] + " --deep --append\n"
        "4. python scripts/kw_status.py で未着手が60件以上あるか確認\n"
        "5. python scripts/publish_flow.py " + cfg["id"] + " <slug> で1本目\n\n"
        "## 一次情報（記事に必ず入れる）\n"
        + "\n".join("- " + x for x in cfg["facts"]) + "\n", encoding="utf-8")

    print("\n  作成: sites/" + cfg["id"] + ".json")
    print("  作成: " + cfg["kw_plan"])
    print("  作成: site-" + cfg["id"] + "/（" + str(n_page) + "ページ）")
    print("  作成: " + memo.name)


if __name__ == "__main__":
    main()
