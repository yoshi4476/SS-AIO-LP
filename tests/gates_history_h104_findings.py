# -*- coding: utf-8 -*-
"""2026-10-12 11:30 の週次点検（findings）で新しく出たものの点検。

  1. 最初の接続の点検（onboard_check）が、検索から外した記事（noindex）を「本番で開けるのに sitemap に無い」と
     3サイトで9本知らせた。noindex の記事は sitemap・llms.txt から外す決まり（scripts/noindex.py）なので誤報
  2. 動画の説明欄の点検（history_checks_b）も、noindex にした記事の動画を「sitemap に無い」と知らせた（ページは200）
  3. 配信先の llms.txt から、新しい記事の行が消えていた（Next.js の社で10月7日〜12日の12本）。記事の行を末尾の
     「## まとめのページ」の区画の後ろに足し、区画の書き直し（aggregate_pages.update_indexes）が続く「- 」行ごと
     置き換えていた
  4. 内部リンクの見直し（auto_review）が、原稿の無い記事（配信先にだけある・統合で消えた）への送り先を被リンク0本と
     みなして下限で守り、上限+1本が毎週直らなかった
  5. history_checks_d が CI で GitHub の鍵を受け取る口（この検査だけが使う名前）を持つ

本物の HTTP・GitHub は使わない。架空の社（client-zz・zz.example）で確かめる
"""
import contextlib
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

DOM = "zz.example"
O = f"https://{DOM}"
CFG = {"id": "client-zz", "name": "ZZ社", "domain": DOM, "type": "external-html"}


@contextlib.contextmanager
def _swap(mod, **kw):
    old = {k: getattr(mod, k) for k in kw}
    for k, v in kw.items():
        setattr(mod, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(mod, k, v)


def _fetch(site):
    def fetch(url, follow=True, head=False):
        path = url[len(O):] if url.startswith(O) else None
        if path is None or path not in site:
            return (404, {}, "", url) if path is not None else (None, {}, "", url)
        st, body = site[path]
        return st, {}, "" if head else body, url
    return fetch


def _onboard(sitemap_slugs):
    """記事3本（ふつうの a1・a2 と、検索から外した hid）。sitemap に載せる記事を変えて sitemap の判定を見る"""
    import onboard_check as OC
    import sites as S
    import wp_bridge
    metas = [{"slug": s, "title": s, "date": "2026-09-01", "category": "zz", **({"noindex": True} if s == "hid" else {})}
             for s in ("a1", "a2", "hid")]
    sm = "<urlset>" + "".join(f"<url><loc>{O}/blog/{s}/</loc></url>" for s in sitemap_slugs) + "</urlset>"
    page = "<html><head><title>t</title></head><body>本文</body></html>"
    site = {"/": (200, page), "/robots.txt": (200, "User-agent: *\nAllow: /\n"), "/sitemap.xml": (200, sm),
            "/llms.txt": (200, "".join(f"- [{s}]({O}/blog/{s}/)\n" for s in sitemap_slugs)),
            "/blog/a1/": (200, page), "/blog/a2/": (200, page),
            "/blog/hid/": (200, page.replace("<title>", '<meta name="robots" content="noindex,follow"><title>'))}
    with _swap(wp_bridge, _site_articles=lambda cfg: [(m, "本文", Path(f"{m['slug']}.md")) for m in metas]), \
            _swap(S, article_url=lambda cfg, m: f"{O}/blog/{m['slug']}/"), \
            _swap(OC, fetch=_fetch(site), expected_pages=lambda c, live: [], delivered_paths=lambda c: set(),
                  videos=lambda c: {}, translations=lambda c: {}, merges=lambda c: [], indexnow_key=lambda: ""):
        arts = OC.articles(CFG, OC.Ctx(CFG))
        res = OC.run_site(CFG, today=date(2026, 10, 12))
    st = next((c for c in res["checks"] if c["id"] == "sitemap"), {})
    return [a["slug"] for a in arts], st.get("status"), st.get("detail", "")


def test_onboard_sitemap_does_not_count_noindex_articles():
    print("\n■ 最初の接続の点検: 検索から外した記事を sitemap の抜けと数えない")
    slugs, status, detail = _onboard(["a1", "a2"])
    check("記事の一覧に検索から外した記事（noindex）を入れない", slugs, ["a1", "a2"])
    check("良い例: ふつうの記事が全部載り、noindex の記事だけが無い sitemap は ok", status, "ok")
    _, status, detail = _onboard(["a1"])
    check("悪い例: 本番で開けるふつうの記事が sitemap に無ければ、これまでどおり ng（抜けはその記事だけ）",
          (status, "a2" in detail, "hid" in detail), ("ng", True, False))


def test_video_desc_check_skips_sitemap_for_noindex():
    import history_checks_b as HB
    import noindex
    url = f"{O}/blog/zz-live/"
    with _swap(noindex, is_hidden=lambda s: s == "zz-hidden"):
        got = (HB.missing_from_sitemap("zz-hidden", f"{O}/blog/zz-hidden/", set()),
               HB.missing_from_sitemap("zz-live", url, set()),
               HB.missing_from_sitemap("zz-live", url, {url}),
               HB.missing_from_sitemap("zz-live", url, {url.rstrip("/")}),
               HB.missing_from_sitemap("zz-live", url, None))
    check("動画の説明欄: noindex の記事は sitemap に無くてよい／ふつうの記事が無ければ拾う／末尾スラッシュ違い・"
          "sitemap が取れない回は拾わない", got, (False, True, False, False, False))


def test_llms_article_lines_survive_aggregate_block():
    import aggregate_pages as AP
    import publish as P
    print("\n■ llms.txt: 記事の行を「まとめのページ」の区画に飲み込ませない")
    check("区画の行の見分け（compare・topics・industry・en はまとめ、/blog/ は記事）",
          [AP.is_page_line(f"- [x]({O}{p}): d") for p in ("/compare/", "/topics/t1/", "/industry/zz/faq/", "/en/blog/a/",
                                                           "/blog/a/", "/aio/a/")],
          [True, True, True, True, False, False])
    head = f"# ZZ\n\n## 記事\n- [a1]({O}/blog/a1/): d1\n\n"
    block = f"{AP.LLMS_HEAD}\n- [比較表]({O}/compare/): 比較\n- [古いテーマ]({O}/topics/old/): 古い\n"
    cfg = {"id": "client-zz", "domain": DOM, "url_prefix": "/blog", "images_dir": "images"}
    pages = [{"title": "比較表", "url": f"{O}/compare/", "description": "比較"}]
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d)
        lt = dest / "llms.txt"
        lt.write_text(head + block, encoding="utf-8", newline="\n")
        P._update_external_index(dest, cfg, {"slug": "a2", "date": "2026-10-12", "title": "a2", "description": "d2"})
        after_pub = lt.read_text(encoding="utf-8")
        AP.update_indexes(dest, cfg, pages)
        t = lt.read_text(encoding="utf-8")
        line = f"- [a2]({O}/blog/a2/): d2"
        check("新しい記事の行は区画の前に入る（後ろに足すと区画の書き直しで消える）",
              after_pub.index(line) < after_pub.index(AP.LLMS_HEAD), True)
        check("区画を書き直しても記事の行が残り、区画は今のページだけ・1つだけ",
              (line in t, f"{O}/topics/old/" in t, t.count(AP.LLMS_HEAD), t.index(line) < t.index(AP.LLMS_HEAD)),
              (True, False, 1, True))
        # 前の作りで区画の後ろに足された行（悪い例）も、消さずに区画の前へ戻す
        lt.write_text(head + block + line + "\n", encoding="utf-8", newline="\n")
        AP.update_indexes(dest, cfg, pages)
        t = lt.read_text(encoding="utf-8")
        check("区画に紛れた記事の行は消さずに区画の前へ戻す（まとめのページの古い行は消す）",
              (t.count(line), t.index(line) < t.index(AP.LLMS_HEAD), f"{O}/topics/old/" in t), (1, True, False))
        # 区画が無い llms.txt は、これまでどおり末尾に足す
        lt.write_text(head, encoding="utf-8", newline="\n")
        P._update_external_index(dest, cfg, {"slug": "a3", "date": "2026-10-12", "title": "a3", "description": "d3"})
        check("区画の無い llms.txt は末尾に足す", lt.read_text(encoding="utf-8").rstrip("\n").endswith(f"- [a3]({O}/blog/a3/): d3"),
              True)


def _review_article(dir_, targets):
    filler = "中小企業の基準は業種ごとに資本金と従業員数で決まります。申請の前に自社の数字を確かめてください。" * 10
    parts = ["---\ntitle: t\n---\n", "## 見出し1\n", filler, ""]
    words = ("あわせて", "続けて", "関連して", "次に", "ほかに")
    for i, s in enumerate(targets):
        parts += [f"{words[i % 5]}[記事{i}](/blog/{s}/)もご覧ください。", ""]
    parts += ["## 見出し2\n", filler, "", "## 見出し3\n", filler, ""]
    p = Path(dir_) / "zz-review.md"
    p.write_bytes("\n".join(parts).encode("utf-8"))
    return p


def test_review_drops_links_to_articles_without_a_manuscript():
    import auto_review as A
    have = sorted(p.stem for p in (ROOT / "articles").glob("*.md") if not p.name.startswith("_"))[:4]
    if len(have) < 4:
        check("内部リンクの見直し: 試す材料（原稿4本）がある", len(have), 4)
        return
    gone = "zz-no-such-article-x"
    check("原稿の無い記事への送り先だけを見分ける（業種ハブなど記事でないページは守る）",
          (A.uncounted_article(f"あわせて[x](/blog/{gone}/)もご覧ください。"),
           A.uncounted_article(f"あわせて[x](/blog/{have[0]}/)もご覧ください。"),
           A.uncounted_article("あわせて[x](/industry/zz-gyoshu/)もご覧ください。")), (True, False, False))
    inb = {s: 3 for s in have}          # どれも被リンク3本（1本外すと下限3を割る）
    with tempfile.TemporaryDirectory() as d:
        p = _review_article(d, have + [gone])
        item = A.findings([p])[0]
        r, dropped, ng = A.fix(p, item, write=True, inb=dict(inb), floors={})
        body = p.read_text(encoding="utf-8")
        check("悪い例: 上限+1本で、原稿の無い記事への段落を外す（下限で守らない）",
              (dropped, ng, f"/blog/{gone}/" in body, all(f"/blog/{s}/" in body for s in have)), (1, "", False, True))
        p = _review_article(d, have + [have[0]])
        item = A.findings([p])[0]
        r, dropped, ng = A.fix(p, item, write=False, inb=dict(inb), floors={})
        check("良い例: 送り先がどれも原稿のある記事で下限を割るなら、これまでどおり外さない", (dropped, ng), (0, ""))


def test_histd_takes_its_own_github_key():
    import history_checks_d as HD
    seen = []

    def run(cmd, **k):
        env = k.get("env") or {}
        seen.append((cmd[1], env.get("GH_TOKEN")))
        if cmd[1] == "secret":
            return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")
        ok = env.get("GH_TOKEN") == "repo-key"
        return subprocess.CompletedProcess(cmd, 0 if ok else 1, stdout='{"items": []}' if ok else "", stderr="" if ok else "no")

    import os
    import sites as S
    keep = {k: os.environ.get(k) for k in ("HISTD_GH_TOKEN", "HISTD_REPO_TOKEN", "SITE_PUSH_TOKEN")}
    try:
        os.environ.update({"HISTD_GH_TOKEN": "secret-key", "HISTD_REPO_TOKEN": "bad-key", "SITE_PUSH_TOKEN": "repo-key"})
        with _swap(HD.shutil, which=lambda n: "/usr/bin/gh"), _swap(HD.subprocess, run=run), \
                _swap(HD, workflow_secrets=lambda: set()), \
                _swap(S, load_all=lambda: {"client-zz": {"type": "external-md", "repo": "zz/zz-site"}}):
            HD.GH_SKIPPED.clear()
            found = []
            HD.check_secrets(found)
            HD.check_delivery_fonts(found)
    finally:
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    check("history_checks_d: Secrets の一覧はこの検査だけの鍵（HISTD_GH_TOKEN）で読む",
          [t for c, t in seen if c == "secret"], ["secret-key"])
    check("history_checks_d: 配信先の検索は配信先を読める鍵を順に試し、通った鍵で続ける（動けた回は unknown にしない）",
          ([t for c, t in seen if c == "api"], HD.GH_SKIPPED), (["bad-key", "repo-key"], []))
    with _swap(os, environ={k: v for k, v in os.environ.items()
                            if k not in ("HISTD_GH_TOKEN", "HISTD_REPO_TOKEN", "SITE_PUSH_TOKEN")}):
        check("history_checks_d: 鍵が無ければ gh の手元の認証のまま（env を渡さない）", HD._gh_env("HISTD_GH_TOKEN"), None)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
