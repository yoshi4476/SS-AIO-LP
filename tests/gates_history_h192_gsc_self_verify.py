# -*- coding: utf-8 -*-
"""お客様の社の Search Console の所有権を、サービスアカウントが自分で確かめる（2026-11-18）。

新しく受けた社は、先方がサービスアカウントをオーナーに足すまで Search Console を読めず、
食い合いの検査は照合を落とし、Indexing API でも知らせられなかった。運用者の指示は「自動でして」。
配信先の直下へはファイルを置ける（IndexNow の鍵・Bing の確認ファイル）ので、Google の確認ファイルも
配信と一緒に置き、本番に出たら Site Verification API で確かめる（偽の Google。本物の API は呼ばない）
"""
import contextlib
import io
import tempfile
from pathlib import Path

from test_gates import check

NAME = "google0123456789abcdef.html"
CFG = {"id": "h192-a", "name": "A社", "domain": "h192-a.example", "type": "nextjs-json"}


@contextlib.contextmanager
def _swap(mod, **kw):
    old = {k: getattr(mod, k) for k in kw}
    for k, v in kw.items():
        setattr(mod, k, v)
    try:
        yield mod
    finally:
        for k, v in old.items():
            setattr(mod, k, v)


class _Call:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class _Google:
    """Site Verification API と Search Console の偽物"""

    def __init__(self, disabled=False):
        self.calls, self.disabled = [], disabled

    def webResource(self):
        return self

    def sites(self):
        return self

    def getToken(self, body):
        def run():
            self.calls.append(("getToken", body["site"]["identifier"], body["verificationMethod"]))
            if self.disabled:
                raise RuntimeError("Site Verification API has not been used in project 1 before or it is disabled")
            return {"method": "FILE", "token": NAME}
        return _Call(run)

    def insert(self, verificationMethod, body):
        return _Call(lambda: self.calls.append(("insert", body["site"]["identifier"], verificationMethod)) or {})

    def add(self, siteUrl):
        return _Call(lambda: self.calls.append(("add", siteUrl)) or {})


def _out(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


def test_service_account_verifies_itself_after_the_file_goes_live():
    print("\n■ 確認ファイルが本番に出たら、サービスアカウントが自分で所有権を確かめ、Search Console に足す")
    import gsc_verify as GV
    g = _Google()
    r = GV.connect(CFG, sv=g, sc=g, fetch=lambda dom, name: "")
    check("まだ出ていない: 待つ（確かめる API を呼ばない）", (r["state"], [c[0] for c in g.calls]), ("waiting", ["getToken"]))
    check("待ちは要対応にしない（配信の直後）", GV.todo(CFG, r, "bot@x").startswith("確認中:"), True)
    check("週次の点検でまだ出ていなければ要対応", GV.todo(CFG, r, "bot@x", weekly=True).startswith("要対応:"), True)

    g = _Google()
    r = GV.connect(CFG, sv=g, sc=g, fetch=lambda dom, name: GV.file_body(name) + "\n")
    check("出ている: 確認ファイルで確かめ、URL のプロパティを足す", (r["state"], g.calls),
          ("verified", [("getToken", "https://h192-a.example/", "FILE"),
                        ("insert", "https://h192-a.example/", "FILE"), ("add", "https://h192-a.example/")]))

    g = _Google()
    r = GV.connect(CFG, sv=g, sc=g, fetch=lambda dom, name: "google-site-verification: google-other.html")
    check("別の中身のファイル: 確かめに行かない", (r["state"], len(g.calls)), ("waiting", 1))

    g = _Google(disabled=True)
    r = GV.connect(CFG, sv=g, sc=g, fetch=lambda dom, name: "")
    msg = GV.todo(CFG, r, "bot@x")
    check("API が無効: 有効にする場所を名指しした要対応", (r["state"], GV.ENABLE_URL in msg, msg.startswith("要対応:")),
          ("disabled", True, True))

    g = _Google()
    r = GV.connect(dict(CFG, type="wordpress"), sv=g, sc=g, fetch=lambda dom, name: "")
    check("WordPress: 直下に置けないので先方にお願いする（API を呼ばない）",
          (r["state"], g.calls, "オーナーで追加" in GV.todo(CFG, r, "bot@x")), ("manual", [], True))


def test_file_rides_along_with_delivery_and_notify_uses_it():
    print("\n■ 確認ファイルは配信と一緒に置き、公開直後の通知の工程で確かめる")
    import gsc_verify as GV
    import notify_indexing as NX
    import search_connect as SC
    import sites as S
    import notify_indexnow as NI
    with tempfile.TemporaryDirectory() as d, \
            _swap(S, is_client=lambda sid: sid.startswith("h192-")), \
            _swap(NI, find_key=lambda env: "h192key000000000"), \
            _swap(GV, token=lambda domain, sv=None: NAME):
        dest = Path(d) / "repo"
        (dest / "public").mkdir(parents=True)
        (dest / "public" / "robots.txt").write_text("User-agent: *\n", encoding="utf-8")
        got = SC.place(CFG, dest)
        check("公開フォルダの直下に Google の確認ファイルを置く",
              sorted(p.name for p in got), sorted([NAME, "h192key000000000.txt"]))
        check("中身は Google の決まった形", (dest / "public" / NAME).read_text(encoding="utf-8"), GV.file_body(NAME))
        check("自社と WordPress には置かない",
              (SC.files_for(dict(CFG, id="ai-lab")), NAME in SC.files_for(dict(CFG, type="wordpress"))), ({}, False))

        sa = Path(d) / "sa.json"
        sa.write_text('{"client_email": "bot@h192.iam.gserviceaccount.com"}', encoding="utf-8")
        sent = []

        class _Svc:
            def urlNotifications(self):
                return self

            def publish(self, body):
                sent.append(body["url"])
                return self

            def execute(self):
                return {}

        url = "https://h192-a.example/blog/x/"
        state = {"r": "verified"}
        with _swap(NX, SA_PATH=sa, _service=lambda: _Svc(), owner_domains=lambda: set(),
                   sitemap_of=lambda cfg: [url], todays_urls=lambda cfg, days=1: [url]), \
                _swap(GV, connect=lambda cfg: {"site": cfg["id"], "domain": cfg["domain"], "state": state["r"],
                                               "msg": "https://h192-a.example/" + NAME}):
            _r, out = _out(NX.main, ["--site", "h192-a"], {"h192-a": CFG})
            check("確かめられた回は、その場で Indexing API に送る（要対応を出さない）",
                  (sent, "要対応" in out), ([url], False))
            sent.clear()
            state["r"] = "waiting"
            _r, out = _out(NX.main, ["--site", "h192-a"], {"h192-a": CFG})
            check("待ちの回は送らず、確認中を出す（先方へのお願いを出さない）",
                  (sent, "確認中:" in out, "要対応" in out), ([], True, False))
            state["r"] = "waiting"
            with _swap(NX, owner_domains=lambda: set()):
                _r, out = _out(SC.check, {"h192-a": CFG})
            check("週次の点検: まだ出ていなければ要対応（確認ファイルを名指し）",
                  ("要対応: A社 の Search Console の確認ファイル" in out, "SEARCH_CONNECT_OK=no" in out), (True, True))
