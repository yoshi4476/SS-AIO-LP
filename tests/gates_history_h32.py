# -*- coding: utf-8 -*-
"""お客様の社の新しい記事も、公開直後に検索エンジンへ知らせる門（2026-10-06）。

運用者の方針: どの納品方式でも、最初の接続が済んだ後は人の手なしで全機能が動く。
以前は、記事の枠の公開直後の通知（Indexing API・IndexNow・Bing）が自前ビルドの AI集客ラボの枠だけで動き、
お客様の社の新しい記事は週次の再送まで知らせていなかった。Bing は自社だけ（own_cfgs）で、お客様の
ドメインを当社の Bing アカウントへ足す工程が無かった。ZIP は先方が毎回上げる作業が残り、方針に合わない。

固定すること:
  - お客様の社も記事の枠で通知が呼ばれる（ワークフローの条件・1社分の IndexNow・Indexing API）
  - Search Console のオーナーでない社は Indexing API に送らず「要対応」を出す
  - IndexNow の鍵ファイルと Bing の確認ファイルを、配信と一緒に直下へ置く（先方の確認ファイルは消さない）
  - Bing は AddSite → 確認ファイル → VerifySite → 送信（偽の Bing。本物の API は呼ばない）
  - 同意の無い社は Bing の対象外（API を1回も呼ばない）
  - ZIP は新規で選べない（シート・登録の検査）。過去の互換で TYPES には残す
  - ftp の社でも GA4 の測定IDが sites/<id>.json に入る（ftp の雛形が計測を置く）
"""
import contextlib
import inspect
import io
import json
import tempfile
from pathlib import Path

from test_gates import check, ROOT

GIT_FTP = ("external-md", "external-html", "nextjs-json", "ftp")


def _out(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*a, **k)
    return buf.getvalue()


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


def _clients(sid):
    return sid.startswith("h32-")


CFGS = {
    "h32-a": {"id": "h32-a", "name": "A社", "domain": "h32-a.example", "type": "ftp"},
    "h32-b": {"id": "h32-b", "name": "B社", "domain": "h32-b.example", "type": "external-html", "gsc_owner": True},
}


def _url(cfg):
    return f"https://{cfg['domain']}/blog/x/"


class _Svc:
    """Indexing API の偽物"""

    def __init__(self):
        self.sent = []

    def urlNotifications(self):
        return self

    def publish(self, body):
        self.sent.append(body["url"])
        return self

    def execute(self):
        return {}


def test_client_articles_are_notified_right_after_publish():
    print("\n■ お客様の社の新しい記事も、記事の枠の公開直後に通知する（オーナーでない社は送らず要対応）")
    import sites as S
    import notify_indexing as NX
    import notify_indexnow as NI
    with tempfile.TemporaryDirectory() as d:
        sa = Path(d) / "sa.json"
        sa.write_text('{"client_email": "bot@h32.iam.gserviceaccount.com"}', encoding="utf-8")
        svc = _Svc()
        with _swap(S, is_client=_clients), \
                _swap(NX, SA_PATH=sa, _service=lambda: svc, owner_domains=lambda: {"h32-a.example"},
                      sitemap_of=lambda cfg: [_url(cfg)], todays_urls=lambda cfg, days=1: [_url(cfg)]):
            NX.main(["--site", "h32-a"], CFGS)
            check("Indexing API: オーナーのお客様の社は本日の記事を送る", svc.sent, ["https://h32-a.example/blog/x/"])
            svc.sent.clear()
            out = _out(NX.main, ["--site", "h32-b"], CFGS)
            check("Indexing API: Search Console で実際にオーナーでない社は、設定が済でも送らない", svc.sent, [])
            check("送らない社は、先方にお願いすることを要対応で出す（サービスアカウントのメールつき）",
                  "要対応: B社" in out and "オーナーで追加" in out and "bot@h32.iam.gserviceaccount.com" in out, True)
            check("権限を読めないときは、ヒアリングで聞いた gsc_owner で決める",
                  (NX.gsc_owner_ok(CFGS["h32-a"], None), NX.gsc_owner_ok(CFGS["h32-b"], None)), (False, True))
            check("ドメインのプロパティ（sc-domain）のオーナーはサブドメインにも効く",
                  NX.gsc_owner_ok({"id": "h32-c", "domain": "blog.h32-c.example"}, {"h32-c.example"}), True)
            check("自社は常に送る", NX.gsc_owner_ok({"id": "ai-lab", "domain": "ai.7senses.co.jp"}, set()), True)

            sent = []
            with _swap(NI, find_key=lambda env: "h32key0000000000",
                       key_ok=lambda dom, key: dom != "h32-b.example",
                       notify=lambda urls, key, site: sent.append((site, list(urls))) or 200):
                NI.main(["--site", "h32-a"], CFGS)
                check("IndexNow: --site はその社の本日の記事だけを、その社のドメインで送る",
                      sent, [("https://h32-a.example", ["https://h32-a.example/blog/x/"])])
                sent.clear()
                out = _out(NI.main, ["--site", "h32-b"], CFGS)
                check("IndexNow: 鍵ファイルが出ていないお客様の社は送らず要対応", (sent, "要対応: B社" in out), ([], True))

    import yaml
    y = yaml.safe_load((ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8"))
    steps = y["jobs"]["write"]["steps"]
    names = [s.get("name", "") for s in steps]
    st = next(s for s in steps if s.get("name") == "新しいURLを検索エンジンへ通知")
    run = st.get("run", "")
    check("記事の枠: 通知の工程は自前ビルドの枠だけに限らない", "own == 'True'" in str(st.get("if")), False)
    check("記事の枠: 3つとも、その枠の社を指定して送る",
          all(c in run for c in ('notify_indexnow.py --site "$id"', 'bing_webmaster.py --site "$id"',
                                 'notify_indexing.py --site "$id"')), True)
    check("記事の枠: 配信先のビルドを待つ確認の後に送る（sitemap に載る前に送ると0件になる）",
          names.index("本番に届いたかの確認") < names.index("新しいURLを検索エンジンへ通知"), True)
    check("記事の枠: 要対応は通知の本文へ足す", "findings.txt" in run and "^要対応" in run, True)
    check("Bing の送信記録の復元・保存も全社の枠で動く",
          [("own == 'True'" in str(s.get("if"))) for s in steps if "Bing への送信記録" in s.get("name", "")], [False, False])
    gen = next(s for s in steps if s.get("name", "").startswith("記事生成"))
    check("記事の配信（publish.py）に Bing の鍵を渡す（確認ファイルを配信と一緒に置くため）",
          "BING_WEBMASTER_API_KEY" in (gen.get("env") or {}), True)


def test_key_and_bing_auth_files_ride_along_with_delivery():
    print("\n■ IndexNow の鍵ファイルと Bing の確認ファイルを、配信と一緒に直下へ置く")
    import sites as S
    import notify_indexnow as NI
    import bing_webmaster as BW
    import search_connect as SC
    import publish
    cfg = dict(CFGS["h32-a"], type="nextjs-json", bing_consent=True)
    with tempfile.TemporaryDirectory() as d, _swap(S, is_client=_clients), \
            _swap(NI, find_key=lambda env: "h32key0000000000"), \
            _swap(BW, auth_code=lambda c, key=None, add=True: "H32CODE" if c.get("bing_consent") else "",
                  live_auth=lambda dom: ""):
        dest = Path(d) / "repo"
        (dest / "public").mkdir(parents=True)
        (dest / "public" / "robots.txt").write_text("User-agent: *\n", encoding="utf-8")
        (dest / "public" / "BingSiteAuth.xml").write_text(
            '<?xml version="1.0"?>\n<users>\n\t<user>THEIRS</user>\n</users>\n', encoding="utf-8")
        got = SC.place(cfg, dest)
        check("公開フォルダ（public/）の直下に2つ置く",
              sorted(p.relative_to(dest).as_posix() for p in got), ["public/BingSiteAuth.xml", "public/h32key0000000000.txt"])
        auth = (dest / "public" / "BingSiteAuth.xml").read_text(encoding="utf-8")
        check("先方が自分の Bing アカウントで置いた確認コードを消さずに足す",
              BW.auth_users(auth), ["THEIRS", "H32CODE"])
        check("中身が同じなら書かない（Git の差分を作らない）", SC.place(cfg, dest), [])

        stage = Path(d) / "stage"
        (stage / "blog").mkdir(parents=True)
        (stage / "sitemap.xml").write_text("<urlset/>", encoding="utf-8")
        got = SC.place(dict(CFGS["h32-a"]), stage)
        check("ftp の作業場所はその直下（サーバーの直下へ上がる）。同意の無い社は鍵ファイルだけ",
              [p.relative_to(stage).as_posix() for p in got], ["h32key0000000000.txt"])
        check("WordPress と自社のサイトには置かない（橋渡し・各サイトの仕組みが持つ）",
              (SC.files_for(dict(cfg, type="wordpress")), SC.files_for(dict(cfg, id="ai-lab"))), ({}, {}))

    src = inspect.getsource(publish.main)
    check("publish.py: Git の方式と FTP の方式の両方で、配信の一覧へ足す",
          ("written += search_files(cfg, base)" in src, "written += search_files(cfg, dest)" in src), (True, True))
    with _swap(SC, place=lambda c, d: (_ for _ in ()).throw(OSError("x"))):
        out = _out(lambda: check("置けなくても記事の配信は止めない", publish.search_files(cfg, Path(".")), []))
    check("置けなかったことは警告で出す", "通知用のファイルを置けませんでした" in out, True)


class _Bing:
    """Bing Webmaster API の偽物。AddSite で確認コードを発行し、VerifySite は本番に確認ファイルが出ていれば通す"""

    def __init__(self, served):
        self.sites, self.calls, self.urls, self.served = {}, [], [], served

    def __call__(self, method, name, key, query=None, body=None):
        site = (query or {}).get("siteUrl") or (body or {}).get("siteUrl")
        self.calls.append(name)
        if name == "GetUserSites":
            return {"d": [{"Url": u, "AuthenticationCode": c["code"], "IsVerified": c["v"]} for u, c in self.sites.items()]}
        if name == "AddSite":
            self.sites[site] = {"code": f"C0DE{len(self.sites)}", "v": False}
        if name == "VerifySite":
            c = self.sites[site]
            c["v"] = c["v"] or f"<user>{c['code']}</user>" in self.served.get(site, "")
            return {"d": c["v"]}
        if name == "GetUrlSubmissionQuota":
            return {"d": {"DailyQuota": 50, "MonthlyQuota": 500}}
        if name == "SubmitUrlBatch":
            self.urls += body["urlList"]
        return {"d": None}


def test_bing_adds_client_domain_verifies_then_sends():
    print("\n■ Bing: 同意のある社を当社のアカウントへ足し、確認ファイルが出たら確かめて送る（偽の Bing）")
    import bing_webmaster as BW
    cid = "h32-a"
    cfg = dict(CFGS[cid], bing_consent=True)
    site = "https://h32-a.example/"
    served = {}
    fake = _Bing(served)
    with tempfile.TemporaryDirectory() as d, \
            _swap(BW, _request=fake, api_key=lambda: "dummy-key", STATE=Path(d) / "s.json", BACKFILL=Path(d) / "b.json",
                  client_cfgs=lambda: {cid: cfg}, own_cfgs=lambda: {}, live_auth=lambda dom: served.get(f"https://{dom}/", ""),
                  recent_urls=lambda c, days: [_url(c)],
                  sitemap_entries=lambda dom: [(f"https://{dom}/blog/old/", "2026-09-01")]):
        code = BW.auth_code(cfg)
        check("AddSite で当社のアカウントへ足し、確認コードを取る", (fake.calls, code),
              (["GetUserSites", "AddSite", "GetUserSites"], "C0DE0"))
        ledger = {}
        res = BW.connect({cid: cfg}, "dummy-key", ledger, "2026-10-06")
        check("確認ファイルが本番に出るまでは VerifySite を呼ばず待つ", (res[0]["state"], "VerifySite" in fake.calls),
              ("waiting", False))
        check("まだ確かめていない社には送らない", sorted(BW.send_cfgs("dummy-key")), [])
        out = _out(BW.connect_report, BW.connect({cid: cfg}, "dummy-key", ledger, "2026-10-20"))
        check("7日を過ぎても出なければ要対応（待ち始めた日は送り切りの記録に残る）",
              ("要対応: h32-a.example の Bing の確認ファイル" in out, ledger["connect"][cid]), (True, "2026-10-06"))

        served[site] = BW.site_auth_xml([code])
        res = BW.connect({cid: cfg}, "dummy-key", ledger, "2026-10-21")
        check("確認ファイルが出たら VerifySite で所有権を確かめる", (res[0]["state"], cid in ledger["connect"]),
              ("verified", False))
        check("確かめた社は送信の対象に入る", sorted(BW.send_cfgs("dummy-key")), [cid])
        out = _out(BW.main, ["--site", cid])
        check("記事の枠: 確かめた社の本日の記事を送る", (fake.urls, "BING_OK=yes" in out), ([_url(cfg)], True))
        order = [fake.calls.index(n) for n in ("AddSite", "VerifySite", "SubmitUrlBatch")]
        check("AddSite → VerifySite → 送信 の順", order == sorted(order), True)
        fake.urls.clear()
        _out(BW.main, ["--backfill"])
        check("送り切り（毎日）の対象にも入る", fake.urls, ["https://h32-a.example/blog/old/"])

    fake = _Bing({})
    no = dict(CFGS["h32-b"])
    with tempfile.TemporaryDirectory() as d, \
            _swap(BW, _request=fake, api_key=lambda: "dummy-key", STATE=Path(d) / "s.json",
                  client_cfgs=lambda: {}, own_cfgs=lambda: {}):
        check("同意の無い社は確認コードを取らない", BW.auth_code(no), "")
        out = _out(BW.main, ["--site", "h32-b"])
        check("同意の無い社は対象外（送らない・Bing を1回も呼ばない）",
              ("同意の無い" in out, "BING_OK=unset" in out, fake.calls), (True, True, []))
    import findings as F
    check("findings が接続の点検を回す", any(s == "search_connect.py --check" for _, s, _ in F.CHECKS), True)


def test_intake_asks_consent_and_retires_zip():
    print("\n■ ヒアリングシート: Bing の同意と Search Console のオーナーを聞く・ZIP は新規で選べない")
    import client_add as CA
    import client_intake as CI
    import search_connect as SC
    import sites as S
    import notify_indexing as NX
    keys = {k: (label, desc) for k, label, desc, _, _ in CI.FIELDS}
    check("シートに Bing の同意の欄がある（当社のアカウントで行うことへの同意）",
          "bing_consent" in keys and "同意" in keys["bing_consent"][0] and "当社のアカウント" in keys["bing_consent"][1], True)
    check("シートに Search Console のオーナーの欄がある", "オーナー" in keys.get("gsc_owner", ("", ""))[1], True)
    base = {"id": "h32-x", "name": "X", "domain": "h32-x.example", "type": "ftp", "ga4_measurement_id": "G-ABCD1234"}
    c = CI.to_config(dict(base, bing_consent="可", gsc_owner="済"))
    check("「可」「済」は設定に true で入る", (c["bing_consent"], c["gsc_owner"]), (True, True))
    check("「不可」・空欄は同意なし", (CI.to_config(dict(base, bing_consent="不可"))["bing_consent"],
                                  CI.to_config(base)["bing_consent"], CI.to_config(base)["gsc_owner"]), (False, False, False))
    check("ftp の社でも GA4 の測定IDが sites/<id>.json に入る（ftp の雛形が計測を置く）",
          c.get("ga4_measurement_id"), "G-ABCD1234")
    check("Git の方式は入れない（先方のテンプレートが持つ）",
          "ga4_measurement_id" in CI.to_config(dict(base, type="nextjs-json")), False)

    check("ZIP は過去の互換で TYPES に残し、新規の選択肢からは外す", ("zip" in CA.TYPES, "zip" in CA.NEW_TYPES), (True, False))
    ng, _ = CA.check({"id": "h32-zip", "type": "zip"})
    check("client_add: zip は登録の検査で止まる", any("選べません" in m for m in ng), True)
    ng, _ = CI.review({"type": "zip"}, CI.to_config({"id": "h32-zip", "type": "zip"}))
    check("ヒアリングシート: zip は不備として止まる", any("選べません" in m for m in ng), True)
    from openpyxl import load_workbook
    with tempfile.TemporaryDirectory() as d:
        ws = load_workbook(CI.make_sheet(Path(d) / "s.xlsx")).active
        f = [v.formula1 for v in ws.data_validations.dataValidation if "ftp" in str(v.formula1)]
        check("シートの形式の選択肢に zip が無い（ftp はある）", (len(f), "zip" in str(f)), (1, False))
    check("いま zip の社はいない", sorted(s for s, c in S.load_all().items() if c.get("type") == "zip"), [])

    with _swap(S, is_client=_clients), _swap(NX, SA_PATH=ROOT / "no-such-sa.json"):
        out = _out(SC.check, {"h32-a": CFGS["h32-a"], "h32-z": {"id": "h32-z", "domain": "z.example", "type": "zip",
                                                               "gsc_owner": True}})
    check("接続の点検: オーナーでない社と zip の社を要対応にする",
          ("要対応: A社" in out, "要対応: h32-z は zip" in out, "SEARCH_CONNECT_OK=no" in out), (True, True, True))

    caps = json.loads((ROOT / "data" / "capabilities.json").read_text(encoding="utf-8"))
    check("表: zip の列は新規受付なしと注記し、ok か n/a だけ",
          ("新規受付なし" in caps["methods"]["zip"],
           sorted({f["cells"]["zip"]["status"] for f in caps["features"].values()}) in (["n/a", "ok"], ["n/a"], ["ok"])),
          (True, True))
    check("表: Git・FTP の方式で Indexing API・IndexNow・Bing が ok",
          {(fid, m): caps["features"][fid]["cells"][m]["status"] for fid in ("indexing_api", "indexnow", "bing")
           for m in GIT_FTP if caps["features"][fid]["cells"][m]["status"] != "ok"}, {})
