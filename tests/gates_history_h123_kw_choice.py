# -*- coding: utf-8 -*-
"""2026-10-20 全体点検（担当4: 何を書くかの工程）で反証して確かめた誤りの門。

  E1 kw_gate.next_keyword の手元の候補が、社を問わず AI集客ラボの計画から選ばれ、判定は judge_new < 2（判定1も通る）だった
  E2 site_brief.local_next_kw が新しく書く語の判定を見ず、「管制塔が未接続」と事実と違う表示をしていた
  A2 記事を書く工程が、お客様の社の記事の材料（brief.json）と一次情報（facts.json）の片方だけでも通していた
  E3 rakko の許可（allow）が社をまたいで残った（見積もりが空の社・落ちた社の後）
  E4 ラッコの通信の例外の回を月の記録に書かず、上限の判定が甘くなっていた
  E6 書いた後の門・配信の前が、同じサイトの公開済みの記事と同じ検索（年号違い）を見ず、配信の前は judge だけだった
  E7 claim_kw が台帳の先頭の行（対象外・公開済み）を選び、生きている行があっても止まっていた
  E8 retire_kw が文字のままで照合し、retired=0 のまま「外した」と扱っていた
  E10 kw_plan・kw_discover がお客様の社の社名・社の id をログに出していた
  G10 日次KPI: 全社が取り直し待ちの日を黙って KPI_SENT=0 で終え、一部の社が待ちの日に残りの社だけで全社の合計を書いていた

本物のラッコ・管制塔・GA4・Search Console は使わない。架空の社（client-zz・zz.example）で確かめる
"""
import contextlib
import io
import json
import re
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def _quiet(fn, *a, **k):
    buf = io.StringIO()
    rc = None
    with contextlib.redirect_stdout(buf):
        try:
            rc = fn(*a, **k)
        except SystemExit as e:
            rc = ("exit", e.code)
    return rc, buf.getvalue()


def _plan(d, lines):
    p = Path(d) / "kw.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


# ── E1・E2: 手元の候補はその社の計画から・judge_new == 0 だけ ─────────────────

def test_local_candidates_come_from_the_sites_own_plan():
    import cannibal_check
    import hub_client
    import kw_fit
    import kw_gate as KG
    import kw_status
    import sites as S
    print("\n■ 台帳から返らない日の候補: その社の計画から、新しく書ける語（judge_new == 0）だけ")
    for sid in ("ai-lab", "corporate", "subsidy"):
        rel = (S.load_all().get(sid) or {}).get("kw_plan")
        want = (ROOT / rel) if rel and (ROOT / rel).is_file() else None
        check(f"plan_file({sid}) はその社の kw_plan（AI集客ラボの計画を使い回さない）", kw_status.plan_file(sid), want)
    check("設定の無い社は None", kw_status.plan_file("no-such-site-zz"), None)
    with tempfile.TemporaryDirectory() as d:
        cdir = Path(d) / "clients" / "client-zz"
        cdir.mkdir(parents=True)
        with mock.patch.dict("os.environ", {"SS_PRIVATE_DIR": d}), \
                mock.patch.object(S, "is_client", lambda s: s == "client-zz"), \
                mock.patch.object(S, "resolve", lambda s: s):
            none = kw_status.plan_file("client-zz")
            (cdir / "kw.md").write_text("**狙い**: 歯科 集客\n", encoding="utf-8")
            got = kw_status.plan_file("client-zz")
        check("お客様の社: 非公開の kw.md が無ければ None・あれば非公開の置き場", (none, got == cdir / "kw.md"), (None, True))

        plan = _plan(d, ["**狙い（3本）**: 判定1の語 / 判定2の語 / 書ける語"])
        fit = {"判定1の語": (1, "担当領域語なし"), "判定2の語": (2, "担当の外"), "書ける語": (0, "")}
        seen_sites = []

        def judge_new(k, site):
            seen_sites.append(site)
            return fit[k]
        with mock.patch.object(hub_client, "next_kw", lambda s: None), \
                mock.patch.object(kw_status, "plan_file", lambda s: plan), \
                mock.patch.object(kw_fit, "judge_new", judge_new), \
                mock.patch.object(cannibal_check, "load_articles", lambda: []), \
                mock.patch.object(cannibal_check, "kw_conflicts", lambda k, a: []):
            got = KG.next_keyword("ai-lab")
        check("kw_gate: 判定1の語（担当領域語なし）を飛ばし、judge_new == 0 の語を選ぶ", got, ("書ける語", "ローカルの計画"))
        with mock.patch.object(hub_client, "next_kw", lambda s: None), \
                mock.patch.object(kw_status, "plan_file", lambda s: None):
            got = KG.next_keyword("client-zz")
        check("kw_gate: 計画が読めない社（お客様の社の kw.md が無い）は何も返さない", got, ("", ""))
        with mock.patch.object(KG, "next_keyword", lambda s: ("", "")), \
                mock.patch.object(sys, "argv", ["kw_gate.py", "--before", "--site", "client-zz"]):
            rc, out = _quiet(KG.main)
        check("kw_gate --before: 候補なし → KW_GATE=skip（記事を書かない）", (rc, "KW_GATE=skip" in out), (0, True))

        import site_brief as SB
        with mock.patch.object(kw_status, "plan_file", lambda s: plan), \
                mock.patch.object(kw_fit, "judge_new", judge_new), \
                mock.patch.object(cannibal_check, "load_articles", lambda: []):
            got = [c["keyword"] for c in SB.local_next_kw({"id": "ai-lab"})]
        check("site_brief.local_next_kw: judge_new == 0 の語だけ", got, ["書ける語"])
        with mock.patch.object(kw_status, "plan_file", lambda s: None):
            check("site_brief.local_next_kw: 計画が無ければ空", SB.local_next_kw({"id": "client-zz"}), [])
    src = (ROOT / "scripts" / "site_brief.py").read_text(encoding="utf-8")
    check("site_brief: 「未接続」と決めつけず「台帳から返らなかった」と書く",
          ("管制塔が未接続のためローカルのKW計画を使用" in src, "台帳から次の語が返らなかった" in src), (False, True))
    kd = (ROOT / "scripts" / "kw_discover.py").read_text(encoding="utf-8")
    check("kw_discover: 既知の語はその社の計画（plan_keywords() の使い回しをしない）",
          ("plan_keywords(plan_file(site_id))" in kd, "plan_keywords()}" in kd), (True, False))


# ── A2: 記事を書く工程はお客様の社の brief と facts の両方が要る ───────────────

def test_brief_requires_both_brief_and_facts_for_clients():
    import private_store
    import site_brief as SB
    print("\n■ 執筆の案内: お客様の社は brief.json と facts.json の両方が無ければ止める（公開の id だけを出す）")
    with tempfile.TemporaryDirectory() as d:
        cdir = Path(d) / "clients" / "client-zz"
        cdir.mkdir(parents=True)

        def path(sid, name, **k):
            return cdir / name
        with mock.patch.object(private_store, "client_path", path), \
                mock.patch.object(SB.sites_mod, "is_client", lambda s: s == "client-zz"), \
                mock.patch.object(SB.sites_mod, "public_id", lambda s: "c0000zz00"):
            (cdir / "brief.json").write_text("{}", encoding="utf-8")
            rc1, out1 = _quiet(SB.require_materials, "client-zz")
            (cdir / "facts.json").write_text("[]", encoding="utf-8")
            rc2, out2 = _quiet(SB.require_materials, "client-zz")
            (cdir / "brief.json").unlink()
            rc3, _ = _quiet(SB.require_materials, "client-zz")
            rc4, _ = _quiet(SB.require_materials, "ai-lab")
    check("facts.json が無い → 終了コード3・要対応・PRIVATE_OK=no", (rc1, "要対応:" in out1, "PRIVATE_OK=no" in out1),
          (("exit", 3), True, True))
    check("知らせる文は公開の id（社の id を出さない）", ("c0000zz00" in out1, "client-zz" in out1), (True, False))
    check("両方ある → 通る／brief.json が無い → 止める／自社は見ない", (rc2, rc3, rc4), (None, ("exit", 3), None))
    src = (ROOT / "scripts" / "site_brief.py").read_text(encoding="utf-8")
    check("main が require_or_exit の後に require_materials を呼ぶ",
          0 < src.index('private_store.require_or_exit(cfg["id"], "記事")') < src.index('require_materials(cfg["id"])'), True)


# ── E3・E4: ラッコの許可を社をまたいで残さない・通信の例外も月の記録へ ────────────

def test_rakko_grant_is_revoked_between_sites_and_failures_are_logged():
    import rakko
    import kw_plan as KP
    print("\n■ ラッコ: 許可は社ごとに消す・通信の例外の回も月の記録に（多めに数える）")
    fake = {"site": "client-zz", "limit": 50.0, "used": 0.0, "plimit": {"headline": 20.0}, "pused": __import__("collections").Counter()}
    saved = rakko._GRANT
    try:
        rakko._GRANT = dict(fake)
        rakko.revoke()
        check("revoke() で許可が消える", (rakko._GRANT, rakko.granted()), (None, False))

        rakko._GRANT = dict(fake)
        with mock.patch.object(KP, "estimate_parts", lambda S: {}), mock.patch.object(KP, "DRY", False, create=True):
            r, out = _quiet(KP.budget_ok, {"cfg": {"id": "own-zz"}})
        check("kw_plan.budget_ok: 見積もりが空の社は前の社の許可を消す（allow を呼ばない）",
              (r, rakko.granted(), "RAKKO_GUARD=ok" in out), (True, False, True))

        rakko._GRANT = dict(fake)
        import private_store
        with mock.patch.object(private_store, "require", lambda *a, **k: False):
            _quiet(KP.run, "client-zz", False, False)
        check("kw_plan.run: 社の入口で許可を消す（前の社の許可を持ち越さない）", rakko._GRANT, None)

        def boom(*a, **k):
            rakko._GRANT = dict(fake)
            raise RuntimeError("途中で落ちた")
        import sites as S_
        with mock.patch.object(KP, "run", boom), mock.patch.object(rakko, "sync_shared", lambda *a, **k: None), \
                mock.patch.object(S_, "is_client", lambda s: s == "client-zz"), \
                mock.patch.object(S_, "public_id", lambda s: "c0000zz00" if s == "client-zz" else s), \
                mock.patch.object(sys, "argv", ["kw_plan.py", "--site", "client-zz"]), \
                contextlib.redirect_stderr(io.StringIO()):
            rc, out = _quiet(KP.main)
        check("kw_plan.main: 社の途中の例外でも許可を消す", rakko._GRANT, None)
        check("KW_PLAN_ERROR は公開の id（社の id を出さない）",
              ("KW_PLAN_ERROR=c0000zz00" in out, "client-zz" in out), (True, False))

        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "spend.jsonl"

            def down(*a, **k):
                raise OSError("timed out")
            rakko._GRANT = dict(fake, pused=__import__("collections").Counter())
            with mock.patch.object(rakko, "api_key", lambda: "zz-key"), mock.patch.object(rakko, "SPEND_LOG", log), \
                    mock.patch.object(rakko, "CACHE_DIR", Path(d) / "cache"), mock.patch.object(rakko, "RETRY_WAIT", ()), \
                    mock.patch.object(rakko.urllib.request, "urlopen", down):
                res, _ = _quiet(rakko.call, rakko.HEADLINE, rakko.headline_body("架空の語"))
                rows = rakko.ledger()
                spent = rakko.month_spent(site="client-zz")
            check("通信の例外: 呼び出しは None", res, None)
            check("通信の例外: 月の記録に値段の上限で残す（uncertain つき・社つき）",
                  [(r.get("path"), r.get("credit"), r.get("site"), r.get("uncertain")) for r in rows],
                  [(rakko.HEADLINE, 3.0, "client-zz", True)])
            check("月の消費に数える（上限の判定が甘くならない）", spent, 3.0)
    finally:
        rakko._GRANT = saved
    src = (ROOT / "scripts" / "rakko.py").read_text(encoding="utf-8")
    check("見積もりが空のまま allow を呼ぶ直し方をしていない（budget_ok は空なら allow の前に返す）",
          (ROOT / "scripts" / "kw_plan.py").read_text(encoding="utf-8").count("rakko.allow("), 1)
    check("revoke がある", "def revoke():" in src, True)


# ── E6: 書いた後の門と配信の前も、同じサイトの公開済みの記事と同じ検索を見る ──────────

def test_after_gate_and_publish_check_same_search_published():
    import kw_fit
    import kw_gate as KG
    import sites as S
    print("\n■ 書いた後の門・配信の前: 同じサイトの公開済みの記事と同じ検索（年号違い）なら出さない")
    cfg = {"subsidy": {"categories": {"hojokin": {}}, "kw_same": [["AI導入補助金", "IT導入補助金"]]}}
    arts = [{"slug": "zz-old", "cat": "hojokin", "kw": "it導入補助金 2026 個人事業主"},
            {"slug": "zz-new", "cat": "hojokin", "kw": "ai導入補助金 2027 個人事業主"}]
    with mock.patch.object(S, "load_all", lambda: cfg):
        got = (KG.same_site_published("ai導入補助金 2027 個人事業主", "subsidy", arts, exclude_slug="zz-new"),
               KG.same_site_published("ai導入補助金 飲食店", "subsidy", arts, exclude_slug="zz-new"))
    check("年号・言い換えだけ違う公開済みの記事を見つけ、自分自身は除く", got, (["zz-old"], []))

    def run_after(dup, retire):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "articles").mkdir()
            (Path(d) / "articles" / "zz-new.md").write_text("---\nkeyword: 架空の語\n---\n", encoding="utf-8")
            import hub_client
            with mock.patch.object(KG, "ROOT", Path(d)), \
                    mock.patch.object(KG, "written_keyword", return_value=[("zz-new", "架空の語")]), \
                    mock.patch.object(KG, "judge", return_value=(0, "")), \
                    mock.patch.object(kw_fit, "judge_new", return_value=(0, "")), \
                    mock.patch.object(KG, "same_site_published", side_effect=lambda k, s, arts=None, exclude_slug="": dup), \
                    mock.patch.object(hub_client, "retire_kw", side_effect=retire), \
                    mock.patch.object(sys, "argv", ["kw_gate.py", "--after", "--site", "client-zz"]):
                rc, out = _quiet(KG.main)
            moved = (Path(d) / "articles" / "_conflicted" / "zz-new.md").is_file()
        warn = [ln for ln in out.splitlines() if ln.startswith("要対応:")]
        return rc, moved, "KW_GATE=quarantined" in out, len(warn), any("架空の語" in w or "zz-new" in w for w in warn)

    check("同じ検索の公開済みの記事がある → 隔離（台帳で外せたら要対応なし）",
          run_after(["zz-old"], lambda *a, **k: {"ok": True, "retired": 1}), (0, True, True, 0, False))
    check("同じ検索が無い → 隔離しない（KW_GATE=ok）", run_after([], lambda *a, **k: {"ok": True, "retired": 0})[:3],
          (0, False, False))
    check("台帳で1行も外れない（retired=0）→ 要対応1行（語・slug は書かない）",
          run_after(["zz-old"], lambda *a, **k: {"ok": True, "retired": 0}), (0, True, True, 1, False))

    pf = (ROOT / "scripts" / "publish_flow.py").read_text(encoding="utf-8")
    blk = pf[pf.index("if slug in new_slugs:"):pf.index("def held(out)")]
    check("publish_flow: 新しい記事は judge_new と same_site_published（自分を除く）で止める",
          ("kw_fit.judge_new(kw, cfg[\"id\"])" in blk, "kw_gate.same_site_published(kw, cfg[\"id\"], exclude_slug=slug)" in blk),
          (True, True))
    check("publish_flow: 新しい記事の判定に judge（書き直し用）を使っていない", "kw_fit.judge(kw" in pf, False)


def test_before_gate_reports_when_nothing_was_retired():
    import hub_client
    import kw_fit
    import kw_gate as KG
    print("\n■ 書く前の門: 台帳で1行も外れなかった（retired=0）ら要対応で止める（同じ語を取り直して誤って止まらない）")
    picks = iter([("語A", "管制塔"), ("語B", "管制塔")])

    def run(retire):
        nonlocal picks
        picks = iter([("語A", "管制塔"), ("語B", "管制塔")])
        with mock.patch.object(KG, "next_keyword", lambda s: next(picks)), \
                mock.patch.object(KG, "judge", lambda k, s, exclude_slug="": (2, "食い合い") if k == "語A" else (0, "")), \
                mock.patch.object(KG, "same_site_published", lambda *a, **k: []), \
                mock.patch.object(kw_fit, "judge_new", lambda k, s: (0, "")), \
                mock.patch.object(hub_client, "retire_kw", retire), \
                mock.patch.object(sys, "argv", ["kw_gate.py", "--before", "--site", "client-zz"]):
            return _quiet(KG.main)
    rc, out = run(lambda *a, **k: {"ok": True, "retired": 0})
    check("retired=0 → 終了コード1・KW_GATE=block・要対応", (rc, "KW_GATE=block" in out, "要対応:" in out), (1, True, True))
    rc, out = run(lambda *a, **k: {"ok": True, "retired": 1})
    check("外れた → 次の候補へ進んで通る", (rc, "KW_GATE=ok" in out, "要対応:" in out), (0, True, False))
    check("retired の無い応答（古い管制塔）は外れたものとして扱う", (KG.retired_any({"ok": True}), KG.retired_any(None)),
          (True, False))


# ── E7・E8: 台帳の claim と retire（GAS と hub_sheets で同じ結果） ──────────────

LEDGER = [
    ["client-zz", "歯科 集客 費用", "対象外", "B", "", "", "2026-10-01 00:00:00", "", "", "", ""],
    ["client-zz", "歯科 集客 費用", "未着手", "B", "", "", "2026-10-02 00:00:00", "", "", "", ""],
    ["client-zz", "矯正 費用 相場", "公開済み", "B", "", "", "2026-10-03 00:00:00", "", "", "https://zz.example/a/", ""],
    ["client-zz", "インプラント　費用", "未着手", "B", "", "", "2026-10-04 00:00:00", "", "", "", ""],
    ["client-zz", "入れ歯 費用", "未着手", "B", "", "", "2026-10-05 00:00:00", "", "", "", ""],
]
STEPS = [["claim", "client-zz", "歯科 集客 費用"],          # 先頭の対象外ではなく未着手の行を選ぶ
         ["claim", "client-zz", "矯正 費用 相場"],          # 公開済みだけ → 何もせず ok
         ["retire", "client-zz", ["インプラント 費用"], "架空の理由"],   # 空白の違い → norm で外れる
         ["retire", "client-zz", ["存在しない語"], "架空の理由"]]       # 0行


def _gas():
    src = (ROOT / "automation" / "gas" / "hub.gs").read_text(encoding="utf-8")

    def fn(name):
        m = re.search(rf"function {name}\(.*?\n\}}\n", src, re.S)
        return m.group(0) if m else ""
    tabs = re.search(r"'KW重複の確認': (\[.*?\])", src).group(1)
    harness = """
var BOOK = {'KW台帳': [['h']].concat(%s), 'KW重複の確認': [%s]};
function sheet_(name) {
  var data = BOOK[name];
  return {
    getLastRow: function () { return data.length; },
    appendRow: function (r) { data.push(r.slice()); },
    getRange: function (row, col, nr, nc) {
      return {
        getValues: function () {
          var out = [];
          for (var i = 0; i < (nr || 1); i++) {
            var r = data[row - 1 + i] || [], o = [];
            for (var j = 0; j < (nc || 1); j++) o.push(r[col - 1 + j] === undefined ? '' : r[col - 1 + j]);
            out.push(o);
          }
          return out;
        },
        setValue: function (v) { data[row - 1][col - 1] = (v instanceof Date) ? 'DATE' : v; },
      };
    },
  };
}
function kwRows_() {
  return BOOK['KW台帳'].slice(1).map(function (r) { var o = r.slice(); while (o.length < 11) o.push(''); return o; });
}
""" % (json.dumps(LEDGER, ensure_ascii=False), tabs)
    body = "".join(fn(n) for n in ("normKw_", "kwGroup_", "sameGroup_", "kwTime_", "noteOverlap_", "kwOverlaps_",
                                   "claimKw_", "retireKw_", "cells_"))
    run = """
var STEPS = %s, RES = [];
STEPS.forEach(function (s) {
  RES.push(s[0] === 'claim' ? claimKw_(s[1], s[2], null) : retireKw_(s[1], s[2], s[3], false));
});
console.log(JSON.stringify({res: RES, kw: BOOK['KW台帳'].slice(1)}));
""" % json.dumps(STEPS, ensure_ascii=False)
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d) / "hub_h123.js"
        tmp.write_text(harness + body + run, encoding="utf-8")
        out = subprocess.run(["node", str(tmp)], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=60)
    if out.returncode:
        print(out.stderr[-800:])
    return json.loads(out.stdout.strip() or "{}")


def _py():
    import hub_sheets as HS
    book = [list(r) for r in LEDGER]
    saved = (HS.rows, HS._set, HS._append, HS._overlap_rows)

    def _set(tab, row, col, value):
        book[row - 2][col - 1] = "DATE" if col == 8 and value else value
    try:
        HS.rows = lambda tab, cols: [list(r) + [""] * (cols - len(r)) for r in book]
        HS._set, HS._append, HS._overlap_rows = _set, (lambda tab, v: None), (lambda: [])
        res = [HS.claim_kw(s[1], s[2]) if s[0] == "claim" else HS.retire_kw(s[1], s[2], s[3]) for s in STEPS]
    finally:
        HS.rows, HS._set, HS._append, HS._overlap_rows = saved
    return {"res": res, "kw": book}


def test_claim_prefers_live_rows_and_retire_matches_variants():
    print("\n■ 台帳: claim は未着手・執筆中の行を先に選び、公開済みなら何もしない。retire は表記ゆれを吸収する")
    g, p = _gas(), _py()
    status = lambda kw: [r[2] for r in kw]
    check("hub_sheets: 対象外の行が先にあっても未着手の行を執筆中にする", (p["res"][0].get("ok"), status(p["kw"])[:2]),
          (True, ["対象外", "執筆中"]))
    check("hub_sheets: 公開済みだけの語は ok で何も変えない", (p["res"][1].get("ok"), status(p["kw"])[2]), (True, "公開済み"))
    check("hub_sheets: 空白の違う語も外れる・無い語は retired=0",
          ([r.get("retired") for r in p["res"][2:]], status(p["kw"])[3:]), ([1, 0], ["対象外", "未着手"]))
    check("GAS と hub_sheets の結果が同じ（ok・retired・台帳の状態）",
          ([(r.get("ok"), r.get("retired")) for r in g.get("res", [])], status(g.get("kw", []))),
          ([(r.get("ok"), r.get("retired")) for r in p["res"]], status(p["kw"])))


# ── G10: 日次KPI ────────────────────────────────────────────

def test_daily_kpi_flags_all_waiting_and_keeps_dashboard_whole():
    import daily_kpi as K
    print("\n■ 日次KPI: 全社が取り直し待ちなら要対応・一部の社が待ちの日はダッシュボードを書き換えない")
    mode = {"fail": {"own-zz", "client-zz"}}
    posted = []

    def collect(day, only=None):
        rows = []
        for sid in ("own-zz", "client-zz"):
            if only is not None and sid not in only:
                continue
            r = {"site": sid, "date": day, "note": "n"}
            if sid in mode["fail"]:
                r["_retry"] = ["GA4"]
            else:
                r["sessions"] = 5
            rows.append(r)
        return rows

    with tempfile.TemporaryDirectory() as td:
        sa = Path(td) / "sa.json"
        sa.write_text("{}", encoding="utf-8")
        with mock.patch.object(K, "SA", sa), mock.patch.object(K, "SENT", Path(td) / "kpi_sent.json"), \
                mock.patch.object(K, "collect", collect), \
                mock.patch.object(K.hub_client, "enabled", lambda: True), \
                mock.patch.object(K.hub_client, "_post", lambda b: posted.append(b) or {"ok": True, "rows": len(b["rows"])}), \
                mock.patch.object(sys, "argv", ["daily_kpi.py", "--send", "--once"]):
            _, out1 = _quiet(K.main)
            n1 = len(posted)
            # 別の日（取り直しではない、その日の初めての送信）: 1社だけ取れた（もう1社は待ち）
            K._write_state([(date.today() - timedelta(days=2)).isoformat()], {})
            mode["fail"] = {"client-zz"}
            _, out2 = _quiet(K.main)
    check("全社が待ち → 何も送らず KPI_SENT=0・要対応", (n1, "KPI_SENT=0" in out1, "要対応:" in out1), (0, True, True))
    check("1社だけ待ち → 取れた社の行は送るが、全社の合計（ダッシュボード）は書き換えない印",
          ([r["site"] for r in posted[-1]["rows"]], posted[-1].get("partial"), "要対応:" in out2), (["own-zz"], True, False))
    hub = (ROOT / "automation" / "gas" / "hub.gs").read_text(encoding="utf-8")
    body = hub.split("function kpiLog_", 1)[1].split("\nfunction ", 1)[0]
    check("管制塔: partial の行ではダッシュボードを書かない", "if (!b.partial) writeDashboard_" in body, True)


# ── E10: お客様の社は公開の id だけ ───────────────────────────────

def test_kw_plan_and_discover_show_only_public_ids():
    import kw_plan as KP
    import private_store
    import sites as S
    print("\n■ kw_plan・kw_discover: お客様の社は公開の id だけを出す（社名・社の id を出さない）")
    with mock.patch.object(private_store, "require", lambda *a, **k: True), \
            mock.patch.object(KP.KD, "site_config", lambda s: {"cfg": {"name": "架空の社名", "id": s}, "industries": []}), \
            mock.patch.object(KP, "sheet_terms", lambda s: ([], [])), \
            mock.patch.object(S, "is_client", lambda s: s == "client-zz"), \
            mock.patch.object(S, "public_id", lambda s: "c0000zz00" if s == "client-zz" else s):
        _, out = _quiet(KP.run, "client-zz", False, False)
    check("kw_plan.run の見出しは公開の id", ("■ c0000zz00" in out, "架空の社名" in out, "client-zz" in out), (True, False, False))
    kd = (ROOT / "scripts" / "kw_discover.py").read_text(encoding="utf-8")
    check("kw_discover の見出しはお客様の社なら公開の id",
          'print(f"KW_DISCOVER_SITE={_sm.public_id(_sm.resolve(site_id))}" if quiet' in kd, True)
    kp = (ROOT / "scripts" / "kw_plan.py").read_text(encoding="utf-8")
    check("KW_PLAN_DONE も公開の id", 'KW_PLAN_DONE={_S.public_id(site_id)}' in kp, True)
