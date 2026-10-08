# -*- coding: utf-8 -*-
"""2026-10-08 ラッコキーワードの上限（運用者の指示「1サイトの上限を決めて、ちゃんとして」）から。

- ラッコは自動課金（オートチャージ）なので、尽きて止まることが無い。月の目安（1,000）は「超えても止めない」で、
  1回の上限（400）は1サイトの月の上限より大きく、意味が無かった
- 利用記録（data/rakko_spend.jsonl）に社が無く、社ごとの使用量が分からなかった
- 手元とCIで別々の記録を数えると、上限が2倍に効く
- 週次の kw_discover がキーさえあれば毎週ラッコを呼ぶ作りだった
- 見積もりが --deep（1起点22.5）を数えておらず、実際より小さく出ることがあった

決めた上限: 1サイト月150（sites/<id>.json の rakko_monthly_cap で上書き）・全体月600・1回150。超えるなら呼ばない。
1サイトの150は目的ごとの枠（見出し・共起語 70／実際の質問 30／一括検索数 30／季節の推移・予備 20。rakko_budget で上書き）。
"""
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import urllib.parse
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


@contextlib.contextmanager
def patched(obj, **kw):
    saved = {k: getattr(obj, k) for k in kw}
    try:
        for k, v in kw.items():
            setattr(obj, k, v)
        yield obj
    finally:
        for k, v in saved.items():
            setattr(obj, k, v)


@contextlib.contextmanager
def ci_env(on):
    old = os.environ.get("GITHUB_ACTIONS")
    if on:
        os.environ["GITHUB_ACTIONS"] = "true"
    else:
        os.environ.pop("GITHUB_ACTIONS", None)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("GITHUB_ACTIONS", None)
        else:
            os.environ["GITHUB_ACTIONS"] = old


def _quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


# 公式の資料（https://api.rakkokeyword.com/docs v1.21.0）の単価。偽の通信はこの値段で課金したことにする
OFFICIAL = {"/v1/suggest-keywords": 1.5, "/v1/related-keywords": 1.5, "/v1/question-search": 1.5,
            "/v1/other-keywords": 22.5}


class FakeRakko:
    """ラッコの代わり。呼ばれた回数と、公式の単価での消費を返す（本物は1回も呼ばない）"""

    def __init__(self):
        self.calls = []
        self.registered = []

    def __call__(self, req, timeout=0):
        url = req.full_url
        if not url.startswith("https://api.rakkokeyword.com"):
            raise AssertionError("ラッコ以外への通信: " + url)
        path = urllib.parse.urlparse(url).path
        body = json.loads(req.data.decode()) if req.data else {}
        self.calls.append(path)
        if path.endswith("/status"):
            out = {"result": True, "meta": {"consumedCredit": 0}, "data": {"isCompleted": True}}
        elif path.endswith("/results"):
            out = {"result": True, "meta": {"consumedCredit": 0},
                   "data": {"items": [{"keyword": k, "metrics": {"searchVolume": 100}} for k in self.registered]}}
        elif path == "/v1/search-volume":
            self.registered = body.get("keywords") or []
            out = {"result": True, "meta": {"consumedCredit": max(15.0, round(0.03 * len(self.registered), 2))},
                   "data": {"requestId": "r1"}}
        elif path == "/v1/account/info":
            out = {"result": True, "meta": {"consumedCredit": 0}, "data": {"credit": {"balance": 1000}}}
        else:
            kw = body.get("keyword", "")
            out = {"result": True, "meta": {"consumedCredit": OFFICIAL.get(path, 99.0)},
                   "data": {"keywords": [{"keyword": f"{kw} 費用 相場 {i}", "metrics": {}} for i in range(3)],
                            "items": []}}
        return io.BytesIO(json.dumps(out, ensure_ascii=False).encode())


@contextlib.contextmanager
def sandbox(rows=(), hub=None, ci=False):
    """本物の台帳・控え・管制塔・ラッコに触らずに rakko を動かす"""
    import hub_client
    import rakko
    td = Path(tempfile.mkdtemp())
    log = td / "spend.jsonl"
    log.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    net = FakeRakko()
    with ci_env(ci), \
            patched(rakko, SPEND_LOG=log, CACHE_DIR=td / "cache", api_key=lambda: "k", RETRY_WAIT=(0, 0, 0),
                    _GRANT=None, CONSUMED=0.0, BUDGET=None, _OUT_OF_CREDIT=False), \
            patched(rakko.urllib.request, urlopen=net), \
            patched(hub_client, enabled=lambda: hub is not None, _post=hub or (lambda b: None)):
        rakko._SAID.clear()
        yield rakko, net, log


def _row(at, credit, site=None, path="/v1/suggest-keywords"):
    r = {"at": at, "path": path, "credit": credit}
    if site is not None:
        r["site"] = site
    return r


class FakeHub:
    """管制塔の rakko_usage / rakko_log（automation/gas/contact.hub.gs と同じ数え方）"""

    def __init__(self):
        self.rows = []

    def __call__(self, body):
        a = body.get("action")
        if a == "rakko_log":
            self.rows.append((body.get("site") or "", body.get("env") or "", float(body.get("credit") or 0),
                              str(body.get("note") or ""), body.get("purpose") or "reserve"))
            return {"ok": True, "rakko": True}
        if a == "rakko_usage":
            out = {"ok": True, "rakko": True, "total": 0, "sites": {}, "purposes": {}, "envs": {}, "blocked": {}}
            for site, env, credit, note, purpose in self.rows:
                out["total"] += credit
                if site:
                    out["sites"][site] = out["sites"].get(site, 0) + credit
                    out["purposes"].setdefault(site, {})
                    out["purposes"][site][purpose] = out["purposes"][site].get(purpose, 0) + credit
                k = f"{site}|{purpose}"
                out["envs"].setdefault(env, {})
                out["envs"][env][k] = out["envs"][env].get(k, 0) + credit
                if note.startswith("止めた"):
                    out["blocked"][site] = out["blocked"].get(site, 0) + 1
            return out
        # 配る前の古い管制塔は action を知らず、フォームとして扱って ok:false を返す
        return {"ok": False, "error": "メールアドレスの形式をご確認ください。"}


def test_rakko_caps_stop_before_calling():
    print("\n■ ラッコ: 1サイト月150・全体月600・1回150。超えるなら呼ばない（自動課金なので警告では止まらない）")
    import rakko
    check("上限の値（1サイト・全体・1回）", (getattr(rakko, "SITE_CAP", None), getattr(rakko, "TOTAL_CAP", None),
                                         getattr(rakko, "RUN_CAP", None)), (150, 600, 150))
    import kw_plan
    check("kw_plan の1回の上限は1サイトの月の上限を超えない", kw_plan.CREDIT_CAP <= getattr(rakko, "SITE_CAP", 0), True)
    month = rakko.datetime.now(rakko.JST).strftime("%Y-%m") if hasattr(rakko, "JST") else "2026-10"
    at = f"{month}-01T10:00:00+09:00"

    # 社の上限: その社の今月 140 ＋ 見積もり 15 > 150 → 呼ばない
    with sandbox([_row(at, 140, "conflux", "/v1/headline")]) as (rk, net, log):
        ok, out = _quiet(rk.allow, "conflux", 15)
        check("社の今月＋見積もりが社の上限を超えるなら許可しない", ok, False)
        check("止めた印は RAKKO_GUARD=site_cap", "RAKKO_GUARD=site_cap" in out, True)
        _quiet(rk.suggest, "クリニック 集客")
        _quiet(rk.call, "/v1/search-volume", {"keywords": ["a"]})
        check("許可が無ければラッコに1回も問い合わせない", net.calls, [])
        check("止めたことを記録する（findings が数える）",
              [r.get("blocked") for r in map(json.loads, log.read_text(encoding="utf-8").splitlines()) if r.get("blocked")],
              ["site_cap"])
        lines, over = rk.month_report(month)
        check("止めた回は要対応（RAKKO_MONTH=over）", over, True)
        check("社ごとの今月の消費と上限を出す", any("conflux: 140.0 / 上限 150" in ln and "止めた 1回" in ln for ln in lines), True)

    # 全体の上限: 社の記録なし（過去の行）590 ＋ 見積もり 15 > 600 → 呼ばない。過去の行は社に割り振らない
    with sandbox([_row(at, 590)]) as (rk, net, log):
        ok, out = _quiet(rk.allow, "ai-lab", 15)
        check("全体の今月＋見積もりが全体の上限を超えるなら許可しない", (ok, "RAKKO_GUARD=total_cap" in out), (False, True))
        check("社の無い過去の行は全体にだけ数える（社に割り振らない）",
              (rk.month_spent(month, "ai-lab"), rk.month_spent(month)), (0, 590))

    with sandbox() as (rk, net, log):
        ok, out = _quiet(rk.allow, "", 3)
        check("社を指定しない課金の呼び出しはしない", ok, False)
        ok, out = _quiet(rk.allow, "ai-lab", 15, dry=True)
        check("dry-run は判定を見せるだけで許可を出さない", (ok, rk.granted()), (True, False))

    # 見積もりが外れても、枠（社の残り）を超える呼び出しはしない
    with sandbox([_row(at, 140, "subsidy", "/v1/headline")]) as (rk, net, log):
        ok, _ = _quiet(rk.allow, "subsidy", 9, purpose="qa")
        got = [_quiet(rk.call, "/v1/question-search", {"keyword": f"q{i}"})[0] is not None for i in range(9)]
        check("社の残り10の枠で、1.5の呼び出しは6回まで", (ok, sum(got), len(net.calls)), (True, 6, 6))
        rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
        check("使った分は社・環境・目的つきで記録する",
              sorted({(r.get("site"), r.get("env"), r.get("purpose")) for r in rows if r.get("credit") and "env" in r}),
              [("subsidy", "local", "qa")])
        check("その社の今月は上限を超えていない", rk.month_spent(month, "subsidy") <= 150, True)

    # 社ごとに上限を変えられる（rakko_monthly_cap）。1回の上限は社の上限を上げても150
    import sites
    cfgs = {"conflux": {"id": "conflux", "rakko_monthly_cap": 30, "rakko_budget": {"headline": 70}},
            "big": {"id": "big", "rakko_monthly_cap": 400}}
    with sandbox() as (rk, net, log), patched(sites, load_all=lambda: cfgs):
        check("社ごとの上限（rakko_monthly_cap）と、書いていない社の既定", (rk.site_cap("conflux"), rk.site_cap("ai-lab")), (30, 150))
        ok, out = _quiet(rk.allow, "conflux", {"headline": 31.5})
        check("社ごとの上限を超えるなら許可しない", (ok, "RAKKO_GUARD=site_cap" in out), (False, True))
        ok, out = _quiet(rk.allow, "big", {"headline": 160})
        check("見積もりが1回の上限を超えるなら許可しない", (ok, "RAKKO_GUARD=run_cap" in out), (False, True))

    # 値段の分からない経路は呼ばない（見積もりも上限も効かなくなる）
    with sandbox() as (rk, net, log):
        _quiet(rk.allow, "ai-lab", 15)
        _quiet(rk.call, "/v1/ranking-keywords", {"keyword": "x"})
        check("単価の資料が無い経路は、許可があっても呼ばない", net.calls, [])


def test_rakko_purpose_budgets():
    print("\n■ ラッコ: 1サイト月150を目的ごとの枠に分ける（見出し・共起語70／質問30／一括検索数30／季節・予備20）")
    import rakko
    check("既定の枠（合計は1サイトの上限）", (getattr(rakko, "BUDGET_SPLIT", None),
                                         sum((getattr(rakko, "BUDGET_SPLIT", None) or {}).values())),
          ({"headline": 70, "qa": 30, "volume": 30, "reserve": 20}, 150))
    check("目的ごとの単価は公式の資料のとおり（見出し3・共起語3・質問1.5・LSI/PAA 22.5）",
          tuple(rakko.price(p) if hasattr(rakko, "price") else None
                for p in ("/v1/headline", "/v1/co-occurrence", "/v1/question-search", "/v1/other-keywords")),
          (3.0, 3.0, 1.5, 22.5))
    with sandbox() as (rk, net, log):
        ok, out = _quiet(rk.allow, "ai-lab", {"reserve": 180, "volume": 30})
        check("枠を超える目的だけ外し、他の目的は続ける", (ok, rk.granted(), "RAKKO_BUCKET=skip:reserve" in out,
                                                 "RAKKO_GUARD=bucket" in out), (False, True, True, True))
        check("目的ごとの許可（一括検索数は可・予備は不可）", (rk.granted("volume"), rk.granted("reserve")), (True, False))
        _quiet(rk.suggest, "aio")
        got = [_quiet(rk.call, "/v1/search-volume", {"keywords": [f"k{i}"]})[0] is not None for i in range(3)]
        _quiet(rk.call, "/v1/headline", {"keyword": "aio"})
        check("外した目的・計画に無い目的では呼ばず、枠のある目的は枠まで（15×2=30）",
              (got, net.calls), ([True, True, False], ["/v1/search-volume", "/v1/search-volume"]))
        lines, _ = rk.month_report()
        check("目的ごとの使用量を出す", any("ai-lab: 30.0" in ln and "一括検索数 30/30" in ln for ln in lines), True)
    import sites
    with sandbox() as (rk, net, log), patched(sites, load_all=lambda: {"x": {"id": "x", "rakko_budget": {"reserve": 50, "qa": 10}}}):
        check("枠は sites/<id>.json の rakko_budget で上書きできる", rk.budget_split("x"),
              {"headline": 70, "qa": 10, "volume": 30, "reserve": 50})
        ok, out = _quiet(rk.allow, "x", {"reserve": 45})
        check("上書きした枠の中なら許可する", ok, True)
    with sandbox() as (rk, net, log), patched(sites, load_all=lambda: {"x": {"id": "x", "rakko_monthly_cap": 300}}):
        check("社の上限だけ変えた社は、枠が同じ比で伸びる", rk.budget_split("x"),
              {"headline": 140, "qa": 60, "volume": 60, "reserve": 40})


def test_rakko_counts_local_and_ci_in_one_total():
    print("\n■ ラッコ: 手元とCIの消費を管制塔の台帳で合わせ、どこで動かしても同じ合計で判断する")
    import rakko
    month = rakko.datetime.now(rakko.JST).strftime("%Y-%m") if hasattr(rakko, "JST") else "2026-10"
    at = f"{month}-02T10:00:00+09:00"
    hub = FakeHub()
    # 手元で conflux に 100 使った（見出し・共起語）
    with sandbox([_row(at, 100, "conflux", "/v1/headline")], hub=hub) as (rk, net, log):
        _quiet(rk.sync_shared)
        _quiet(rk.sync_shared)
        check("手元の記録を管制塔へ写す（2回写しても二重にならない）", hub.rows and sum(r[2] for r in hub.rows), 100)
    # CI の記録には conflux は無いが、管制塔の台帳で手元の 100 が見える → 100＋60 > 150 で止まる
    with sandbox([], hub=hub, ci=True) as (rk, net, log):
        check("CI から手元の目的ごとの消費が見える", rk.usage("conflux", month, rk.shared_usage(month))["purposes"]["headline"], 100)
        ok, out = _quiet(rk.allow, "conflux", {"qa": 30, "volume": 30})
        check("CI でも手元の消費を合わせて社の上限を判断する", (ok, "RAKKO_GUARD=site_cap" in out), (False, True))
        ok, out = _quiet(rk.allow, "conflux", {"qa": 30, "reserve": 15})
        check("合わせても上限内なら許可する", ok, True)
    # CI で使った分も写り、手元から見える
    with sandbox([_row(at, 30, "ai-lab", "/v1/search-volume")], hub=hub, ci=True) as (rk, net, log):
        _quiet(rk.sync_shared)
    with sandbox([_row(at, 100, "conflux", "/v1/headline")], hub=hub) as (rk, net, log):
        u = rk.usage("ai-lab", month, rk.shared_usage(month))
        check("手元から CI の消費が見える（全体の合計も同じ）", (u["site"], u["total"], u["purposes"]["volume"]), (30, 130, 30))
    # 管制塔に届かないとき: CI は呼ばない（手元の消費が見えない）。手元は自分の記録で判断する
    with sandbox([], hub=None, ci=True) as (rk, net, log):
        ok, out = _quiet(rk.allow, "ai-lab", 15)
        check("CI で管制塔の台帳が読めなければ呼ばない", (ok, "RAKKO_GUARD=shared" in out), (False, True))
    with sandbox([], hub=None, ci=False) as (rk, net, log):
        ok, out = _quiet(rk.allow, "ai-lab", 15)
        check("手元は自分の記録で判断し、管制塔に届かないことを書く", (ok, "この環境の記録だけ" in out), (True, True))
    # 配る前の管制塔（action を知らずフォームとして ok:false）を台帳と取り違えない
    with sandbox([], hub=lambda b: {"ok": True}) as (rk, net, log):
        check("印（rakko: true）の無い応答は台帳として読まない", rk.shared_usage(month), None)
    gas = (ROOT / "automation" / "gas" / "contact.hub.gs").read_text(encoding="utf-8")
    hubgs = (ROOT / "automation" / "gas" / "hub.gs").read_text(encoding="utf-8")
    check("管制塔: ラッコ利用の台帳（rakko_usage / rakko_log・目的つき）",
          ("function rakkoUsage_" in gas and "function rakkoLog_" in gas and "rakko: true" in gas and "out.purposes" in gas,
           "case 'rakko_usage'" in hubgs and "case 'rakko_log'" in hubgs), (True, True))


def test_weekly_refill_never_calls_rakko():
    print("\n■ ラッコ: 週次の kw_discover は呼ばない（控えにある応答だけを使う）")
    import rakko
    src = (ROOT / "scripts" / "kw_discover.py").read_text(encoding="utf-8")
    check("kw_discover は上限の許可（rakko.allow）を取らない", "allow(" in src, False)
    check("kw_discover は月の目安を見て続ける作りではない", "MONTHLY_BUDGET" in src, False)
    with sandbox() as (rk, net, log):
        # 控えにある応答は課金なしで返る
        body = rk.suggest_body("aio") if hasattr(rk, "suggest_body") else {
            "keyword": "aio", "modes": ["google", "youtube"], "increaseKeyword": True,
            "sortBy": "searchVolume", "orderBy": "desc", "limit": 100}
        rk._cache_put("/v1/suggest-keywords", body, "POST", {"result": True, "data": {"keywords": [{"keyword": "aio 費用"}]}})
        got, _ = _quiet(rk.suggest, "aio")
        _quiet(rk.related, "aio")
        check("許可が無いときは控えだけを返し、ラッコには問い合わせない", ([r.get("keyword") for r in got], net.calls),
              (["aio 費用"], []))
    import yaml
    wk = yaml.safe_load((ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8"))
    runs = " ".join(str(s.get("run") or "") for j in wk["jobs"].values() for s in j.get("steps", []))
    check("週次のワークフローは kw_plan（課金する工程）を動かさない", "kw_plan.py" in runs, False)
    mo = (ROOT / ".github" / "workflows" / "monthly-report.yml").read_text(encoding="utf-8")
    check("月次: 上限で止めた回を要対応にする（社・全体・1回・目的の枠）",
          all(w in mo for w in ("site_cap", "total_cap", "run_cap", "bucket")), True)


def test_every_rakko_call_goes_through_one_door():
    print("\n■ ラッコ: 通信の口は rakko.call の1か所だけ。課金する工程は上限の許可を先に取る")
    door, direct = [], []
    for p in sorted((ROOT / "scripts").rglob("*.py")):
        s = p.read_text(encoding="utf-8", errors="replace")
        rel = p.relative_to(ROOT).as_posix()
        if "rakkokeyword.com" in s and rel != "scripts/rakko.py":
            direct.append(rel)
        if re.search(r"\brakko\.(call|suggest|related|questions|account)\(", s):
            door.append(rel)
    check("ラッコの URL を持つのは rakko.py だけ", direct, [])
    check("ラッコを呼ぶ工程は kw_plan（月次・新しいお客様）と kw_discover（控えだけ）", door,
          ["scripts/kw_discover.py", "scripts/kw_plan.py"])
    rk_src = (ROOT / "scripts" / "rakko.py").read_text(encoding="utf-8")
    check("rakko.py の中でも通信は call() の1か所", len(re.findall(r"urlopen\(", rk_src)), 1)
    import ast
    tree = ast.parse(rk_src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "call")
    check("その1か所は call() の中", "urlopen(" in ast.get_source_segment(rk_src, fn), True)
    kp = (ROOT / "scripts" / "kw_plan.py").read_text(encoding="utf-8")
    run_src = kp[kp.index("def run("):kp.index("def main(")]
    check("kw_plan は集める前に上限の許可を取る", 0 < run_src.find("budget_ok(S)") < run_src.find("gather("), True)
    check("kw_plan の許可は rakko.allow", "rakko.allow(" in kp, True)


def test_rakko_estimate_is_not_below_actual():
    print("\n■ ラッコ: 見積もり（RAKKO_EST）は実際以上（小さく出ると上限が効かない）")
    import kw_discover as KD
    import kw_plan as KP
    import rakko
    check("単価は公式の資料のとおり（サジェスト・関連語・LSI/PAA）",
          tuple(rakko.price(p) if hasattr(rakko, "price") else None for p in OFFICIAL), tuple(OFFICIAL.values()))
    if hasattr(rakko, "price"):
        check("一括調査は1語0.03・1回最低15（500語で15）",
              (rakko.price("/v1/search-volume", {"keywords": ["a"] * 500}),
               rakko.price("/v1/search-volume", {"keywords": ["a"] * 1000})), (15.0, 30.0))
    # 2026-10-08 の CONFLUX: 問い合わせ120回（1.5）＋一括1回（15）＝実際 195
    with patched(KP, paid_queries=lambda S: [("/v1/suggest-keywords", {"keyword": str(i)}) for i in range(120)]):
        check("CONFLUX の実例（実際195）より見積もりが小さくない", KP.estimate({"industries": []}) >= 195, True)
        check("見積もりを目的ごとに分ける（サジェスト＝予備・一括＝一括検索数）",
              KP.estimate_parts({"industries": []}), {"reserve": 180.0, "volume": 30.0})
    with patched(KP, paid_queries=lambda S: [], DEEP=True):
        check("--deep の LSI/PAA（1起点22.5）を見積もりに数える",
              KP.estimate({"industries": ["a", "b"]}) >= 2 * 22.5, True)
    # 計画を偽のラッコで実際に組み、使った量が見積もりを超えないこと（--deep あり・なし。目的ごとにも）
    S = {"cfg": {"id": "_gate_", "kw_seeds": {"core": ["集客", "seo"]}}, "gsc": "", "industries": ["aio", "クリニック"],
         "own_terms": ("aio",), "intents": [], "ng_terms": ()}
    import sites
    for deep in (False, True):
        with sandbox() as (rk, net, log), \
                patched(sites, load_all=lambda: {"_gate_": {"id": "_gate_", "rakko_budget": {"qa": 60}}}), \
                patched(KD, gsc_queries=lambda *a, **k: [], gsc_rising=lambda *a, **k: [], suggest=lambda *a, **k: []), \
                patched(KP, DEEP=deep, DRY=False, VOL_CACHE=Path(tempfile.mkdtemp()) / "vol.json"), \
                patched(KP.time, sleep=lambda s: None):
            parts = KP.estimate_parts(S)
            ok, _ = _quiet(rk.allow, "_gate_", parts)
            cands, _ = _quiet(KP.gather, "_gate_", S, deep)
            _quiet(KP.fill_volume, cands)
            used = {p: rk.month_spent(None, "_gate_", p) for p in parts}
            check(f"使った量 ≤ 見積もり（deep={deep}）", (ok, rk.spent() <= sum(parts.values()), rk.spent() > 0),
                  (True, True, True))
            check(f"目的ごとにも 使った量 ≤ 見積もり（deep={deep}）", [p for p in parts if used[p] > parts[p]], [])
