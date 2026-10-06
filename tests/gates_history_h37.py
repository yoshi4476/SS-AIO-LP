# -*- coding: utf-8 -*-
"""指示でのサイト改修（site_renovate.py / site_change.py --ask）の門（2026-10-07）。

運用者の依頼: WordPress や FTP の社でも、記事だけでなくサイトの改修まで管制塔から行う。
site_change は「取る・反映・戻す」を持っていたが、作業場所のファイルは人が直す前提だった。直す役を Claude に任せ、
通してよいかは機械が決める。ここでは外部（FTP・WordPress・GitHub・Claude・本番の HTTP）に触れず、
偽の FTP（一時フォルダ）・偽の WordPress（REST の形だけ真似る）・Git の一時リポジトリで確かめる:

  - 良い直しは反映され、台帳（renovate.jsonl）に指示・変えたファイル・確認者が残る
  - 悪い直し（タグの壊れ・リンク切れ・大量削除・許可していない script・インライン script・鍵・Web フォント・
    サイトに無かった電話番号・載せない表現）は検査で止まり、先方には何も届かない
  - 反映後の確認（200・ナビ・フッター・問い合わせの導線）が外れたら自動で戻し、--report が要対応を出す
  - 既定は止まって確認を待つ。renovate_auto の社だけ、その種類（css・text）の小さな直しを自動で反映する
  - 作業場所の外（管制塔）を触ったら捨てる。写真（_preview/）は先方へ送らない
  - 橋渡しのプラグイン 2.0.4 の /ss/v1/design は、許可した項目（link・meta・ld+json・許可したドメインの script src）
    しか通さず、追加CSSに </style> を入れさせない（PHP が無いので、定数と正規表現を取り出して同じ入力を当てる）
"""
import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from urllib.parse import urlsplit

from test_gates import check, ROOT

TOP = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>H37社</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"H37社"}</script>
<link rel="stylesheet" href="/css/style.css"></head>
<body><nav><a href="/">トップ</a> <a href="/about/">会社概要</a> <a href="/guide/">家づくりの流れ</a> <a href="/contact/">お問い合わせ</a></nav>
<main><h1>H37社の家づくり</h1><p>大阪市の工務店です。電話 06-1234-5678</p>
<div class="box"><p>施工の流れを順にご案内します。</p></div></main>
<footer><p>H37社</p></footer></body></html>
"""
ABOUT = TOP.replace("H37社の家づくり", "会社概要")
CONTACT = TOP.replace("H37社の家づくり", "お問い合わせ")
GUIDE = TOP.replace("<p>施工の流れを順にご案内します。</p>",
                    "".join(f"<p>第{i}段階では、打ち合わせの内容を確かめ、図面と見積もりを見直します。</p>" for i in range(60)))
CSS = "body{color:#333;font-family:system-ui,sans-serif}\n.box{padding:12px}\n"
SERVER_FILES = {"index.html": TOP, "about/index.html": ABOUT, "contact/index.html": CONTACT,
                "guide/index.html": GUIDE, "css/style.css": CSS}


def _with(mod, **kw):
    old = {k: getattr(mod, k) for k in kw}
    for k, v in kw.items():
        setattr(mod, k, v)
    return old


def _quiet(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            rc = fn(*a, **kw)
        except SystemExit as e:
            rc = ("exit", str(e))
    return rc, buf.getvalue()


def _png():
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(b, "PNG")
    return b.getvalue()


def _last(log):
    lines = log.read_text(encoding="utf-8").splitlines() if log.is_file() else []
    return json.loads(lines[-1]) if lines else {}


class _Server:
    """偽の FTP サーバー（一時フォルダ）と、その中身を返す偽の本番"""

    def __init__(self, d: Path):
        self.d = d
        for rel, t in SERVER_FILES.items():
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text(t, encoding="utf-8")

    def remote(self):
        srv = self

        class FakeRemote:
            def __init__(self, c):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def walk(self, rel="", skip=()):
                return [(p.relative_to(srv.d).as_posix(), p.stat().st_size) for p in srv.d.rglob("*") if p.is_file()]

            def get(self, rel):
                p = srv.d / rel
                return p.read_bytes() if p.is_file() else None

            def put(self, local, rel):
                (srv.d / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(local, srv.d / rel)

            def delete(self, rel):
                (srv.d / rel).unlink(missing_ok=True)
                return True
        return FakeRemote

    def fetch(self, url):
        path = urlsplit(url).path
        p = self.d / (path.lstrip("/") + ("index.html" if path.endswith("/") else ""))
        return (200, p.read_text(encoding="utf-8")) if p.is_file() else (404, "")

    def text(self, rel):
        return (self.d / rel).read_text(encoding="utf-8")


def _editor(fn):
    """偽の Claude: 作業場所に決まった変更を入れる"""
    def ask(cfg, w, ask):
        fn(Path(w))
        return "直しました"
    return ask


def _sub(rel, old, new):
    def fn(w):
        p = w / rel
        p.write_text(p.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")
    return fn


def test_renovate_ftp_checks_apply_and_rollback():
    import deliver_files as DF
    import site_change as SC
    import site_renovate as R
    print("\n■ 指示での改修（FTP）: 検査で止める・反映する・反映後の確認が外れたら自動で戻す")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "server").mkdir()
        srv = _Server(td / "server")
        log = td / "renovate.jsonl"
        cfg = {"id": "h37-ftp", "name": "H37社", "type": "ftp", "domain": "h37.example",
               "renovate_wait_sec": 0, "renovate_verify_tries": 1}
        old_df = _with(DF, Remote=srv.remote(), credentials=lambda c: {})
        old_sc = _with(SC, WORK=td / "work")
        old_r = _with(R, LOG=log, fetch=srv.fetch, screenshot=lambda urls: {u: _png() for u in urls},
                      tower_status=lambda: set())
        try:
            def go(edit, yes=True, c=cfg, preview=False):
                R.ask_claude = _editor(edit)
                return _quiet(R.run, c, "トップの案内文を直して", yes=yes, preview=preview)

            rc, out = go(_sub("index.html", "施工の流れを順にご案内します。", "施工の流れを3つの段階でご案内します。"))
            rec = _last(log)
            check("良い直し（文言だけ）: 反映され、本番に届く", (rc, "3つの段階" in srv.text("index.html")), (0, True))
            check("台帳: 指示・変えたファイル・確認者（--yes を押した人）・反映後に見たページ",
                  (rec.get("decision"), rec.get("ask"), [f["file"] for f in rec.get("files", [])],
                   rec.get("approver", "").startswith("--yes"), rec.get("checked")),
                  ("applied", "トップの案内文を直して", ["index.html"], True, ["/"]))

            bad = {
                "タグの壊れ": _sub("index.html", "<div class=\"box\">", "<div class=\"box\"><div class=\"new\">"),
                "リンク切れ": _sub("index.html", "</main>", "<p><a href=\"/nope/\">施工事例</a></p></main>"),
                "大量削除": lambda w: (w / "guide" / "index.html").unlink(),
                "許可していない script": _sub("index.html", "</body>", "<script src=\"https://evil.example/x.js\"></script></body>"),
                "インラインの script": _sub("index.html", "</body>", "<script>document.title='x'</script></body>"),
                "on 属性": _sub("index.html", "<h1>", "<h1 onclick=\"go()\">"),
                "鍵": _sub("index.html", "</main>", "<!-- api_key = 'abcd1234efgh5678' --></main>"),
                "日本語Webフォント": _sub("index.html", "</head>",
                                       "<link href=\"https://fonts.googleapis.com/css2?family=Noto+Sans+JP\" rel=\"stylesheet\"></head>"),
                "サイトに無かった電話番号": _sub("index.html", "</main>", "<p>担当直通 090-1111-2222</p></main>"),
                "サーバーの設定": lambda w: (w / ".htaccess").write_text("Deny from all\n", encoding="utf-8"),
                "JSON-LD の壊れ": _sub("index.html", "\"name\":\"H37社\"}", "\"name\":\"H37社\""),
            }
            stopped = {}
            for name, edit in bad.items():
                before = {rel: srv.text(rel) for rel in SERVER_FILES}
                rc, out = go(edit)
                same = all(srv.text(rel) == t for rel, t in before.items()) and not (srv.d / ".htaccess").exists()
                stopped[name] = (rc, _last(log).get("decision"), same)
                R.discard(cfg)
            check("悪い直しは検査で止まり、先方には何も届かない（" + "・".join(bad) + "）",
                  {k: v for k, v in stopped.items() if v != (1, "stopped", True)}, {})
            check("止めた後に --discard で作業場所が取った時点に戻る", R.pending(cfg), [])

            # 反映後の確認: フッターが消えた（タグの開閉は崩れないので検査は通る）→ 自動で戻す
            rc, out = go(_sub("index.html", "<footer><p>H37社</p></footer>", ""))
            rec = _last(log)
            check("反映後の確認が外れたら自動で戻す（フッターが消えた）",
                  (rc, rec.get("decision"), "<footer>" in srv.text("index.html"), "フッター" in str(rec.get("problems"))),
                  (1, "rolled_back", True, True))
            rc, out = _quiet(R.report)
            check("--report: 戻した回を要対応で知らせる（findings の印）",
                  ("要対応: h37-ftp" in out, "RENOVATE_OK=no" in out), (True, True))

            # 既定は止まって確認を待つ（写真は _preview/ に。先方へは送らない）→ --apply で反映
            rc, out = go(_sub("css/style.css", "padding:12px", "padding:16px"), yes=False, preview=True)
            m = SC.mirror(cfg)
            check("既定は止まる（CSS だけでも renovate_auto が無ければ反映しない）",
                  (rc, _last(log).get("decision"), "padding:12px" in srv.text("css/style.css")), (0, "review", True))
            check("写真: 変更前後を並べた画像が _preview/ にでき、作業場所の変更に数えない",
                  (sorted(p.name for p in (m / "_preview").glob("*-compare.png")), R.pending(cfg)),
                  (["top-compare.png"], [("M", "css/style.css")]))
            rc, out = _quiet(R.apply_pending, cfg, preview=False)
            check("--apply で反映し、確認者は --apply",
                  (rc, "padding:16px" in srv.text("css/style.css"), _last(log).get("approver", "").startswith("--apply"),
                   (srv.d / "_preview").exists()), (0, True, True, False))

            auto = {**cfg, "renovate_auto": ["text"]}
            rc, out = go(_sub("about/index.html", "大阪市の工務店です。", "大阪市東成区の工務店です。"), yes=False, c=auto)
            check("renovate_auto の社: 文言だけの直しは確認なしで反映（確認者は自動）",
                  (rc, "東成区" in srv.text("about/index.html"), _last(log).get("approver")), (0, True, "自動（renovate_auto）"))
            rc, out = go(_sub("about/index.html", "</main>", "<section><p>新しい区画</p></section></main>"), yes=False, c=auto)
            check("renovate_auto の社でも、タグが増える直しは止まって確認を待つ",
                  (_last(log).get("decision"), "新しい区画" in srv.text("about/index.html")), ("review", False))
            R.discard(cfg)

            # 作業場所の外を触ったら捨てる
            seq = iter([set(), {"?? scripts/x.py"}])
            R.tower_status = lambda: next(seq)
            rc, out = go(_sub("index.html", "H37社の家づくり", "H37社の家"))
            check("作業場所の外（管制塔）が変わったら止めて捨てる",
                  (rc[0] if isinstance(rc, tuple) else rc, R.pending(cfg), "H37社の家づくり" in srv.text("index.html")),
                  ("exit", [], True))
            R.tower_status = lambda: set()

            # 表現の検査（別の担当の legal_claims。無ければ同じ形の偽物で、つなぎ込みを確かめる）
            fake = None
            if R.legal() is None:
                fake = types.ModuleType("legal_claims")
                fake.find = lambda t: [("rate", s) for s in re.findall(r"[^。>]*採択率[^。<]*。", t)]
                sys.modules["legal_claims"] = fake
            try:
                rc, out = go(_sub("index.html", "</main>", "<p>当社の採択率は90%です。</p></main>"))
                check("表現の検査: 当社の採択率を足す直しは止まる（legal_claims があれば使う）",
                      (rc, _last(log).get("decision"), "載せない表現" in str(_last(log).get("ng"))), (1, "stopped", True))
                R.discard(cfg)
            finally:
                if fake is not None:
                    sys.modules.pop("legal_claims", None)
        finally:
            _with(DF, **old_df)
            _with(SC, **old_sc)
            _with(R, **old_r)


def test_renovate_wordpress_without_ftp():
    import site_change as SC
    import site_renovate as R
    print("\n■ 指示での改修（WordPress・FTP の鍵なし）: 固定ページ・追加CSS・head の追記を REST で変え、外れたら戻す")
    page0 = "<!-- wp:paragraph --><p>会社概要の本文です。</p><!-- /wp:paragraph -->"
    store = {"page": {"id": 1, "title": {"raw": "会社概要"}, "content": {"raw": page0}, "slug": "about", "status": "publish"},
             "design": {"css": "body{color:#333}", "head": [], "footer": []}}
    posts = []

    def fake(cfg, path, data=None, method=None):
        if path.startswith("pages?"):
            return [store["page"]]
        if path.startswith(("menus?", "menu-items?", "navigation?", "templates?", "template-parts?", "widgets?")):
            return []
        if path == "settings" and data is None:
            return {"title": "H37社", "description": ""}
        if path.startswith("themes"):
            return []
        if path == "/ss/v1/design":
            if data is None:
                return json.loads(json.dumps(store["design"]))
            posts.append(data)
            store["design"].update({k: v for k, v in data.items() if k in ("css", "head", "footer")})
            return {"saved": sorted(data)}
        if path.startswith("pages/1") and data is None:
            return store["page"]
        if path == "pages/1":
            store["page"]["content"]["raw"] = data["content"]
            return store["page"]
        return {}

    def fetch(url):
        p = urlsplit(url).path
        body = "<nav></nav><main>{}</main><a href=\"/contact/\">相談</a><footer></footer>"
        if p == "/":
            return 200, body.format("トップ")
        if p == "/about/":
            c = store["page"]["content"]["raw"]
            return (500, "") if "壊れる" in c else (200, body.format(c))
        return 404, ""

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        log = td / "renovate.jsonl"
        cfg = {"id": "h37-wp", "name": "H37社", "type": "wordpress", "domain": "h37wp.example",
               "renovate_wait_sec": 0, "renovate_verify_tries": 1}
        old_sc = _with(SC, WORK=td / "work", _wp=fake, _wp_routes=lambda cfg: set())
        old_r = _with(R, LOG=log, fetch=fetch, screenshot=lambda urls: {}, tower_status=lambda: set())
        try:
            def go(edit, yes=True):
                R.ask_claude = _editor(edit)
                return _quiet(R.run, cfg, "会社概要と色を直して", yes=yes, preview=False)

            m = SC.mirror(cfg)

            def good(w):
                _sub("pages/1.json", "会社概要の本文です。", "会社概要の本文です。創業は大阪です。")(w)
                _sub("design/custom.css", "#333", "#222")(w)
                (w / "design" / "head.json").write_text(json.dumps(
                    [{"t": "meta", "a": {"name": "format-detection", "content": "telephone=no"}},
                     {"t": "ld", "json": {"@context": "https://schema.org", "@type": "Organization", "name": "H37社"}}],
                    ensure_ascii=False), encoding="utf-8")
            rc, out = go(good)
            check("取る: 追加CSS・head・フッターを design/ に取る（橋渡し 2.0.4 の窓口）",
                  sorted(p.name for p in (m / "design").iterdir()), ["custom.css", "footer.json", "head.json"])
            check("良い直し: 固定ページ・追加CSS・head の追記が REST で届く",
                  (rc, "創業は大阪" in store["page"]["content"]["raw"], store["design"]["css"], len(store["design"]["head"])),
                  (0, True, "body{color:#222}", 2))
            check("追加CSS・head・フッターは1回の POST で送る", [sorted(p) for p in posts][-1:], [["css", "footer", "head"]])

            for name, items in {
                "許可していないドメインの script": [{"t": "script", "src": "https://evil.example/x.js"}],
                "http-equiv の meta（転送）": [{"t": "meta", "a": {"http-equiv": "refresh", "content": "0;url=https://evil.example/"}}],
                "任意の HTML": [{"t": "html", "a": {"x": "<img src=x onerror=alert(1)>"}}],
                "Google Fonts の link": [{"t": "link", "a": {"rel": "preconnect", "href": "https://fonts.googleapis.com"}}],
            }.items():
                n = len(posts)
                rc, out = go(lambda w, items=items: (w / "design" / "head.json").write_text(json.dumps(items), encoding="utf-8"))
                check(f"head の追記で止める: {name}", (rc, _last(log).get("decision"), len(posts) == n), (1, "stopped", True))
                R.discard(cfg)
            rc, out = go(_sub("design/custom.css", "}", "}</style><script>alert(1)</script>"))
            check("追加CSSに </style> と <script> を入れさせない", (rc, _last(log).get("decision")), (1, "stopped"))
            R.discard(cfg)

            rc, out = go(_sub("pages/1.json", "創業は大阪です。", "創業は大阪です。壊れる"))
            check("反映後の確認が外れたら（会社概要が500）自動で戻す",
                  (rc, _last(log).get("decision"), "壊れる" in store["page"]["content"]["raw"], "/about/" in str(_last(log).get("problems"))),
                  (1, "rolled_back", False, True))
        finally:
            _with(SC, **old_sc)
            _with(R, **old_r)


def test_renovate_git_rolls_back_with_revert():
    import site_change as SC
    import site_renovate as R
    print("\n■ 指示での改修（Git の社）: 配信先へ push し、反映後の確認が外れたら revert を push する")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        origin = td / "origin.git"
        sh = lambda *a, cwd=None: subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout
        sh("init", "-q", "--bare", "-b", "main", str(origin))
        seed = td / "seed"
        sh("init", "-q", "-b", "main", str(seed))
        for rel, t in SERVER_FILES.items():
            (seed / "public" / rel).parent.mkdir(parents=True, exist_ok=True)
            (seed / "public" / rel).write_text(t, encoding="utf-8")
        sh("-c", "user.name=t", "-c", "user.email=t@t", "add", "-A", cwd=seed)
        sh("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base", cwd=seed)
        sh("push", "-q", str(origin), "main", cwd=seed)
        cfg = {"id": "h37-git", "name": "H37社", "type": "external-html", "domain": "h37git.example", "repo": "h37/none",
               "branch": "main", "renovate_wait_sec": 0, "renovate_verify_tries": 1}
        work = td / "work"
        work.mkdir()
        sh("clone", "-q", str(origin), str(work / cfg["id"]))

        def push(c, committed=False):
            dest = work / c["id"]
            SC.git("add", "-A", cwd=dest)
            if SC.git("status", "--porcelain", cwd=dest).strip():
                SC.git(*SC.BOT, "commit", "-q", "-m", "change", cwd=dest)
            elif not committed:
                return "変更はありません"
            SC.git("push", "-q", "origin", "HEAD:main", cwd=dest)
            return "push しました"

        def fetch(url):
            path = urlsplit(url).path
            rel = "public/" + path.lstrip("/") + ("index.html" if path.endswith("/") else "")
            r = subprocess.run(["git", f"--git-dir={origin}", "show", f"main:{rel}"], capture_output=True)
            return (200, r.stdout.decode("utf-8")) if r.returncode == 0 else (404, "")

        old_sc = _with(SC, WORK=work, git_push=push)
        old_r = _with(R, LOG=td / "renovate.jsonl", fetch=fetch, screenshot=lambda urls: {}, tower_status=lambda: set(),
                      pull=lambda c: "取りました")
        try:
            R.ask_claude = _editor(_sub("public/index.html", "施工の流れを順に", "施工の流れを3段階で"))
            rc, out = _quiet(R.run, cfg, "案内を直して", yes=True, preview=False)
            check("良い直し: 配信先へ push される", (rc, "3段階" in fetch("https://x/")[1]), (0, True))
            check("静的な根（public/）を見つけ、手元で解決できる", R.static_root(cfg, work / cfg["id"]) == work / cfg["id"] / "public", True)
            R.ask_claude = _editor(_sub("public/index.html", "<footer><p>H37社</p></footer>", ""))
            rc, out = _quiet(R.run, cfg, "フッターを消して", yes=True, preview=False)
            log = sh("--git-dir", str(origin), "log", "--oneline", "main")
            check("反映後の確認が外れたら revert を push して戻す（履歴は消さない）",
                  (rc, "<footer>" in fetch("https://x/")[1], len(log.splitlines())), (1, True, 4))
        finally:
            _with(SC, **old_sc)
            _with(R, **old_r)


def _php():
    return (ROOT / "automation" / "wordpress" / "ss-quality-gate.php").read_text(encoding="utf-8")


def _php_list(php, name):
    m = re.search(rf"^const {name} = \[(.*?)\];", php, re.M | re.S)
    return re.findall(r"'([^']*)'", m.group(1)) if m else None


def _php_regex(php, name):
    m = re.search(rf"^const {name} = '(.*?)';$", php, re.M)
    body = m.group(1).replace("\\'", "'").replace("\\\\", "\\")
    d = body[0]
    pat, flags = body[1:].rsplit(d, 1)
    return re.compile(pat, re.I if "i" in flags else 0)


def test_bridge_design_window_is_safe():
    import site_renovate as R
    print("\n■ 橋渡し 2.0.4: 追加CSS・head・フッターの窓口は許可した項目しか通さない")
    php = _php()
    check("版は 2.0.4（見出しと定数）", (re.search(r"^ \* Version: (\S+)", php, re.M).group(1),
                                    re.search(r"^const SSB_VERSION = '(\S+)';", php, re.M).group(1)), ("2.0.4", "2.0.4"))
    route = php.split("register_rest_route(SSB_NS, '/design'", 1)[1].split("register_rest_route(", 1)[0]
    check("窓口: GET・POST とも、書き込みの条件（アプリケーションパスワード）＋外観の編集の権限",
          (route.count("'permission_callback' => 'ssb_can_design'"),
           "return ssb_can_write() && current_user_can('edit_theme_options');" in php), (2, True))
    check("窓口: 1つでも受け付けない項目があれば何も保存しない（保存は検めた後）",
          route.index("if ($bad)") < route.index("wp_update_custom_css_post(") < route.index("update_option('ssb_' . $k"), True)
    check("許可の一覧は管制塔の検査と同じ（項目のキー・link の属性と rel・meta の属性・script のドメイン）",
          [_php_list(php, n) for n in ("SSB_ITEM_KEYS", "SSB_LINK_ATTRS", "SSB_LINK_RELS", "SSB_META_ATTRS", "SSB_SCRIPT_HOSTS")],
          [list(R.ITEM_KEYS), list(R.LINK_ATTRS), list(R.LINK_RELS), list(R.META_ATTRS), list(R.SCRIPT_HOSTS)])
    check("meta に http-equiv（転送）・link に stylesheet を許さない",
          ("http-equiv" in _php_list(php, "SSB_META_ATTRS"), "stylesheet" in _php_list(php, "SSB_LINK_RELS")), (False, False))
    css_bad = _php_regex(php, "SSB_CSS_BAD")
    samples = ["a{}</style><script>x</script>", "a{width:expression(1)}", "a{background:url(javascript:x)}",
               "@import url(https://fonts.googleapis.com/css2?family=Noto+Sans+JP);", "<!-- x -->"]
    check("追加CSS: </style>・<script>・expression・javascript:・Google Fonts を止める（PHP の正規表現そのものを当てる）",
          ([bool(css_bad.search(s)) for s in samples], [bool(R.CSS_BAD.search(s)) for s in samples]), ([True] * 5, [True] * 5))
    check("追加CSS: ふつうの CSS（子セレクタの > を含む）は通す",
          [bool(css_bad.search(s)) for s in ("ul > li { color: #333 }", ".a::after{content:\"→\"}")], [False, False])
    url = re.search(r"preg_match\('(#\^https://.*?#)', \$u\)", php).group(1)
    rx = re.compile(url[1:-1].replace("\\'", "'").replace("\\\\\\\\", "\\\\"))
    check("script src は https の URL だけ（空白・引用符・<>・バックスラッシュ・http・javascript: を通さない）",
          [bool(rx.fullmatch(u)) for u in ("https://www.google.com/recaptcha/api.js", "http://www.google.com/x.js",
                                            "https://x.example/a b", "https://x.example/\"onload=", "javascript:alert(1)",
                                            "https://x.example/\\evil")],
          [True, False, False, False, False, False])
    item = php.split("function ssb_design_item($it)", 1)[1].split("\n}\n", 1)[0]
    check("項目は link・meta・ld・script の4種だけ（style・任意のタグ・インラインの script の形が無い）",
          sorted(set(re.findall(r"\$t === '(\w+)'", item))), ["ld", "link", "meta", "script"])
    out = php.split("function ssb_design_html($items)", 1)[1].split("\n}\n", 1)[0]
    check("出すときは組み立て直す（出す直前に検め直す・esc_url/esc_attr・ld+json は JSON_HEX_TAG）",
          ["$it = ssb_design_item($it);" in out, "esc_url($it['src'])" in out, "esc_attr($v)" in out,
           "JSON_HEX_TAG" in out], [True] * 4)
    check("保存した追記を検めずに出す箇所が無い",
          sorted(set(re.findall(r"echo ([^;]*get_option\('ssb_(?:head|footer)'[^;]*);", php))),
          ["ssb_design_html(get_option('ssb_footer', []))", "ssb_design_html(get_option('ssb_head', []))"])
    check("管制塔の検査: 許可した項目は通し、許可していない項目は止める",
          (R.design_problems([{"t": "meta", "a": {"name": "x", "content": "y"}}, {"t": "ld", "json": {"@type": "Thing"}},
                              {"t": "link", "a": {"rel": "canonical", "href": "/about/"}},
                              {"t": "script", "src": "https://challenges.cloudflare.com/turnstile/v0/api.js", "async": True}]),
           len(R.design_problems([{"t": "script", "src": "https://evil.example/a.js"}, {"t": "style", "a": {}},
                                  {"t": "meta", "a": {"http-equiv": "refresh", "content": "0"}},
                                  {"t": "link", "a": {"rel": "stylesheet", "href": "/x.css"}}, {"t": "ld", "json": "x"},
                                  {"t": "meta", "a": {"name": "x", "content": "y"}, "html": "<b>"}]))), ([], 6))


def test_renovate_is_wired():
    import site_change as SC
    import site_renovate as R
    import inspect
    print("\n■ 入口・台帳・通知・表のつなぎ込み")
    src = inspect.getsource(SC.main)
    check("site_change --ask は site_renovate.run に渡す（取り方・反映の仕方を二重に持たない）",
          ("site_renovate.run(cfg, a.ask" in src, "def push_mirror(" in inspect.getsource(SC), "SC.push_mirror(" in inspect.getsource(R.apply)),
          (True, True, True))
    check("WordPress: ウィジェットを取って戻す（wp/v2/widgets・instance は raw で書き戻す）",
          ("widgets" in [n for n, _, _ in SC.WP_RES], 'data["instance"] = {"raw": inst}' in inspect.getsource(SC.wp_push)), (True, True))
    perm = json.loads(R.perm_settings())["permissions"]
    check("Claude の道具は読み書きと検索だけ（Bash・外部通信なし）、書けるのは作業場所の中だけ・.git は触れない",
          ("Bash" in json.dumps(perm), sorted(perm["allow"]), "Edit(./.git/**)" in perm["deny"]),
          (False, ["Edit(./**)", "Glob", "Grep", "Read", "Write(./**)"], True))
    check("台帳は public のリポジトリに置かない（お客様の指示と変えたファイル）",
          subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "automation/logs/renovate.jsonl"]).returncode, 0)
    check("findings が戻した回を拾う（読むだけの --report）",
          "site_renovate.py --report" in (ROOT / "scripts" / "findings.py").read_text(encoding="utf-8"), True)
    check("既定は自動で反映しない（renovate_auto の無い社）", R.auto_ok({"id": "x"}, [("M", "a.css")], {"css"}), False)
    check("鍵を台帳に残さない", R.redact("api_key = 'abcd1234efgh5678' を入れて"), "（鍵らしき文字列を伏せました） を入れて")
    caps = json.loads((ROOT / "data" / "capabilities.json").read_text(encoding="utf-8"))
    cells = caps["features"]["site_renovate"]["cells"]
    check("表: 指示での改修は FTP・静的な Git の社で ok、WordPress・ビルドする Git の社は partial（理由つき）",
          {m: c["status"] for m, c in cells.items()},
          {"self-static": "n/a", "external-md": "partial", "external-html": "ok", "nextjs-json": "partial",
           "wordpress": "partial", "ftp": "ok", "zip": "n/a"})
    check("表: site_change × wordpress の要るものに 2.0.4 の窓口（追加CSS・head/フッター・ウィジェット）が書いてある",
          all(x in caps["features"]["site_change"]["cells"]["wordpress"]["need"] for x in ("2.0.4", "追加CSS", "ウィジェット")), True)
