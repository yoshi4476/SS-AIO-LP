# -*- coding: utf-8 -*-
"""Git を使わない配信先（レンタルサーバーの FTP・ZIP 納品）の門（2026-10-04）。

配信方式を足すときに漏れやすいのは、書き出しより周り（形式の一覧・CI に渡す鍵・公開の照合）。
1か所でも抜けると「登録はできるが CI で配信されない」「毎日同じ ZIP を作り直す」になる。
"""
import re
import tempfile
from pathlib import Path

from test_gates import check, ROOT


def test_file_delivery_types_are_wired():
    import client_add
    import deliver_files as DF
    for t in DF.TYPES:
        check(f"配信方式 {t} が形式の一覧にある", t in client_add.TYPES, True)
        check(f"配信方式 {t} をヒアリングシートで選べる",
              t in (ROOT / "scripts" / "client_intake.py").read_text(encoding="utf-8").split("DataValidation(type=\"list\", formula1='\"wordpress")[1].split("'")[0], True)

    # 原稿（.md）と作業用の雛形は相手のサーバーに上げない。記事は接頭辞の場所へ移す
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        page = base / "blog" / "x" / "index.html"
        page.parent.mkdir(parents=True)
        page.write_text('<a href="/blog/y/">y</a>', encoding="utf-8")
        (base / "_src").mkdir()
        (base / "_src" / "x.md").write_text("a", encoding="utf-8")
        (base / "_template.html").write_text("t", encoding="utf-8")
        got = DF.files_of([page, base / "_src" / "x.md", base / "_template.html"], base, "/column")
        check("FTP/ZIP は原稿と雛形を上げない", [r for _, r in got], ["column/x/index.html"])
        check("FTP/ZIP は記事内の関連リンクも接頭辞に合わせる", 'href="/column/y/"' in page.read_text(encoding="utf-8"), True)

    # 汎用の雛形は write_external_html が埋める名前と、作業場所で埋める3つだけを使う
    tpl = (ROOT / "templates" / "external_article.html").read_text(encoding="utf-8")
    pub = (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
    vals = set(re.findall(r'^\s+"([A-Z_]+)": ', pub.split("vals = {", 1)[1].split("\n    }", 1)[0], re.M))
    left = set(re.findall(r"\{\{([A-Z_]+)\}\}", tpl)) - vals - {"SITE_NAME", "ORIGIN", "PREFIX"}
    check("汎用の雛形に埋まらない差し込みが無い", sorted(left), [])

    # 配信する工程（SITE_PUSH_TOKEN を渡す工程）には、FTP・WordPress の接続情報も渡す
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        s = wf.read_text(encoding="utf-8")
        n = s.count("SITE_PUSH_TOKEN: ${{ secrets.SITE_PUSH_TOKEN }}")
        check(f"{wf.name}: 配信の工程に FTP の接続情報を渡している",
              s.count("FTP_CREDENTIALS_JSON: ${{ secrets.FTP_CREDENTIALS_JSON }}") >= n, True)
        check(f"{wf.name}: 配信の工程に WordPress の接続情報を渡している",
              s.count("WP_CREDENTIALS_JSON: ${{ secrets.WP_CREDENTIALS_JSON }}") >= n, True)

    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    check("FTP の接続情報と ZIP 納品物はコミットしない", "ftp-credentials.json" in gi and "deliveries/" in gi, True)
    check("ZIP 納品は未配信の照合から外す（毎日作り直さない）",
          'c.get("type") == "zip"' in (ROOT / "scripts" / "publish_gap.py").read_text(encoding="utf-8"), True)


def test_site_changes_reach_file_delivery():
    """記事の配信だけでなく、サイト改修（取り下げと301・全記事の描き直し・メニュー・訳のページ）も
    FTP・ZIP・WordPress の社に届く。Git の作業コピー前提の道具は、ここで落ちていた（2026-10-04）"""
    src = lambda n: (ROOT / "scripts" / n).read_text(encoding="utf-8")
    check("取り下げ（統合の301）が FTP・ZIP の社を扱う", "deliver_files.retract" in src("retract.py"), True)
    check("取り下げが WordPress の社を扱う（下書きに戻す）", '"status": "draft"' in src("retract.py"), True)
    check("全記事の描き直しが FTP・ZIP の社を扱う", "DF.deliver_batch" in src("publish_rerender.py"), True)
    check("多言語メニューが FTP・ZIP の社に届く", '("ftp", "zip")' in src("menu_page.py"), True)
    check("訳のページを書いたものとして返す（FTP・ZIP は返したものだけ届ける）",
          'written += [dest / lg / pre / meta["slug"] for lg in extra["langs"]]' in src("publish.py"), True)
