# -*- coding: utf-8 -*-
"""運用者の決定3つの門（2026-10-05）。

1. KW台帳の重複は「社の組」で分ける。同じ組（自社3サイト・同じお客様）の中は今までどおり弾き、
   組の違う社と重なった語は登録したうえで「KW重複の確認」に残して運用者に知らせる。
   管制塔（GAS）と直接接続（hub_sheets）が同じ結果になることを、同じ台帳で両方に当てて確かめる。
2. お客様の月次レポートは report_issuer で名義を選ぶ（client なら当社名・URL・ロゴを出さない）。
3. 公開前の確認を「要」にしたお客様の記事は、記録が付くまで HELD。社ごとの一覧（原稿のURL・題・待った日数・
   承認の手順）を通知に載せ、承認したら配信まで進む（配信は --push なしの dry で確かめる）。
本物のシート・配信先・メールには触れない（偽の台帳・一時フォルダだけを使う）。
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from test_gates import check, ROOT

CTX = {"groups": {"ai-lab": "own", "corporate": "own", "subsidy": "own", "cl-a": "cl-a", "cl-b": "cl-b"},
       "regions": {"ai-lab": "大阪", "corporate": "大阪", "subsidy": "大阪", "cl-a": "京都府", "cl-b": "兵庫県"}}


def _ledger():
    def r(site, kw, st, d):
        return [site, kw, st, "B", "", "", d, "", "", "", ""]
    return [r("ai-lab", "歯科 集客", "未着手", "2026-09-01 10:00:00"),
            r("cl-a", "インプラント 費用 大阪", "公開済み", "2026-09-02 10:00:00"),
            r("corporate", "補助金 申請", "未着手", "2026-09-03 10:00:00"),
            r("subsidy", "補助金申請", "未着手", "2026-09-04 10:00:00"),
            r("cl-a", "矯正 費用", "未着手", "2026-09-05 10:00:00")]


# 両方に同じ順で当てる操作。ctx が None の呼び出しは古い記事工場（全社を1つの組として弾く）
STEPS = [
    ("add", "corporate", ["歯科 集客", "新しい語"], CTX),
    ("add", "cl-b", ["歯科集客", {"keyword": "インプラント 費用 大阪", "priority": "A"}], CTX),
    ("add", "cl-b", ["インプラント費用大阪"], CTX),
    ("claim", "cl-a", "インプラント 費用 大阪", CTX),
    ("claim", "subsidy", "補助金申請", CTX),
    ("add", "cl-b", ["矯正 費用"], None),
    ("claim", "cl-a", "矯正 費用", CTX),
    ("add", "cl-b", ["矯正 費用"], CTX),
]


def _summary(res):
    """比べる形に揃える（日時は書き手ごとに違うので落とす）"""
    out = {"ok": res.get("ok"), "added": res.get("added")}
    for k in ("skipped_dup", "skipped_other_site", "overlaps", "conflicts"):
        v = res.get(k)
        if v:
            out[k] = sorted(json.dumps({x: y for x, y in i.items() if x in ("keyword", "site")}, ensure_ascii=False)
                            for i in v)
    return out


def _run_gas():
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
        setValue: function (v) { data[row - 1][col - 1] = v; },
      };
    },
  };
}
function kwRows_() {
  return BOOK['KW台帳'].slice(1).map(function (r) { var o = r.slice(); while (o.length < 11) o.push(''); return o; });
}
""" % (json.dumps(_ledger(), ensure_ascii=False), tabs)
    body = "".join(fn(n) for n in ("normKw_", "kwGroup_", "sameGroup_", "kwTime_", "noteOverlap_", "kwOverlaps_",
                                   "kwConflict_", "addKw_", "claimKw_"))
    run = """
var STEPS = %s, RES = [];
STEPS.forEach(function (s) {
  RES.push(s[0] === 'add' ? addKw_(s[1], s[2], s[3]) : claimKw_(s[1], s[2], s[3]));
});
var cf = kwConflict_('cl-a', '歯科 集客', null, null, %s);
var cfOld = kwConflict_('corporate', '歯科 集客');
console.log(JSON.stringify({res: RES, kw: BOOK['KW台帳'].slice(1), ov: kwOverlaps_().rows,
                            cf: [cf.level, cf.other_group.length, cfOld.level]}));
""" % (json.dumps(STEPS, ensure_ascii=False), json.dumps(CTX, ensure_ascii=False))
    tmp = ROOT / "tests" / "_hub_h10_tmp.js"
    tmp.write_text(harness + body + run, encoding="utf-8")
    try:
        out = subprocess.run(["node", str(tmp)], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=60)
    finally:
        tmp.unlink(missing_ok=True)
    if out.returncode:
        print(out.stderr[-800:])
    return json.loads(out.stdout.strip() or "{}")


def _run_py():
    import hub_sheets as HS
    book = {"KW台帳": [list(r) for r in _ledger()], HS.OVERLAP_TAB: []}
    saved = (HS.rows, HS._set, HS._append, HS._overlap_rows)

    def rows(tab, cols):
        return [list(r) + [""] * (cols - len(r)) for r in book[tab]]

    def _set(tab, row, col, value):
        book[tab][row - 2][col - 1] = value

    def _append(tab, values):
        book[tab].append(list(values))

    try:
        HS.rows, HS._set, HS._append = rows, _set, _append
        HS._overlap_rows = lambda: rows(HS.OVERLAP_TAB, HS.OVERLAP_COLS)
        res = [HS.add_kw(s[1], s[2], s[3]) if s[0] == "add" else HS.claim_kw(s[1], s[2], s[3]) for s in STEPS]
        ov = HS.kw_overlaps()["rows"]
    finally:
        HS.rows, HS._set, HS._append, HS._overlap_rows = saved
    return {"res": res, "kw": book["KW台帳"], "ov": ov}


def test_kw_ledger_blocks_within_group_and_reports_across_groups():
    print("\n■ KW台帳: 同じ組は弾き、組の違う社は登録して「KW重複の確認」へ（GAS と hub_sheets が同じ結果）")
    g, p = _run_gas(), _run_py()
    gs, ps = [_summary(r) for r in g.get("res", [])], [_summary(r) for r in p["res"]]
    check("GAS と hub_sheets の結果が同じ（各操作）", gs, ps)
    check("自社の別サイトが持つ語は弾く（今までどおり）", ps[0].get("skipped_other_site"),
          ['{"keyword": "歯科 集客", "site": "ai-lab"}'])
    check("組の違う社と重なった語は登録する", ps[1]["added"], 2)
    check("同じお客様の中の重複は弾く", (ps[2]["added"], len(ps[2].get("skipped_dup") or [])), (0, 1))
    check("着手（claim）も組の違う社の語では止めない", ps[3]["ok"], True)
    check("着手（claim）は自社の組の中の重複で止める", (ps[4]["ok"], len(ps[4].get("conflicts") or [])), (False, 1))
    check("組を送らない古い呼び出しは、全社を1つの組として弾く", ps[5].get("skipped_other_site"),
          ['{"keyword": "矯正 費用", "site": "cl-a"}'])

    def ov(rows):
        return sorted((r["keyword"], r["site_a"], r["region_a"], r["site_b"], r["region_b"], r["status"]) for r in rows)

    check("記録の行が同じ（語・社A・地域A・社B・地域B・状態）", ov(g.get("ov", [])), ov(p["ov"]))
    check("知らせる中身: 先に登録した社が社A・地域つき・未確認", ov(p["ov"]), sorted([
        ("歯科集客", "ai-lab", "大阪", "cl-b", "兵庫県", "未確認"),
        ("インプラント 費用 大阪", "cl-a", "京都府", "cl-b", "兵庫県", "未確認"),
        ("矯正 費用", "cl-a", "京都府", "cl-b", "兵庫県", "未確認")]))
    check("同じ語・同じ2社は1行だけ（claim で二重に積まない）", len(p["ov"]), 3)
    check("台帳の行が同じ（社・語・状態）", [r[:3] for r in g.get("kw", [])], [r[:3] for r in p["kw"]])
    check("kw_conflict: 組の違う社は止めず other_group で返す。ctx 無しは従来どおり", g.get("cf"), [0, 2, 1])

    import hub_client as HC
    import findings as F
    import sites as S
    check("hub_client が組と地域を送る（add_kw・claim_kw）",
          ['"ctx": kw_context()' in __import__("inspect").getsource(f) for f in (HC.add_kw, HC.claim_kw)], [True, True])
    check("地域: kw_seeds.regions、無ければ会社の住所の都道府県", (S.region_of("ai-lab") != "",
                                                    S.PREF.search("〒600-0000 京都府京都市").group(1),
                                                    S.PREF.search("神奈川県横浜市").group(1)), (True, "京都府", "神奈川県"))
    check("週次の findings が未確認の重複を要対応として拾う",
          any(s == "hub_client.py overlaps" for _, s, _ in F.CHECKS), True)
    gs_src = (ROOT / "automation" / "gas" / "hub.gs").read_text(encoding="utf-8")
    check("KW台帳の列は変えない（11列のまま）・新しいタブは TABS にある",
          ("'記事URL', '備考'],\n  '記事作成ログ'" in gs_src, "'KW重複の確認': ['日時', '語', '社A', '地域A', '社B', '地域B', '状態'" in gs_src),
          (True, True))


def test_overlap_report_marks_and_exit_codes():
    import hub_client as HC
    print("\n■ KW重複の確認の通知（見つかっても終了コード0・印で知らせる）")
    import contextlib
    import io
    saved = (HC.enabled, HC.kw_overlaps)
    try:
        HC.enabled = lambda: True
        HC.kw_overlaps = lambda: [{"keyword": "歯科集客", "site_a": "ai-lab", "region_a": "大阪", "site_b": "cl-b",
                                   "region_b": "兵庫県", "status": "未確認"},
                                  {"keyword": "x", "site_a": "cl-a", "site_b": "cl-b", "status": "両方使う"}]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = HC.overlaps_report()
        out = buf.getvalue()
        check("未確認だけを要対応に・終了コード0", (rc, "KW_OVERLAP_OK=no" in out, out.count("  - ")), (0, True, 1))
        check("語・両社・地域・先に登録した側が載る", all(w in out for w in ("歯科集客", "ai-lab", "大阪", "cl-b", "兵庫県", "先に登録")), True)
        HC.kw_overlaps = lambda: None
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            HC.overlaps_report()
        check("古い管制塔（未配布）は unknown（問題なしと言わない）", "KW_OVERLAP_OK=unknown" in buf.getvalue(), True)
    finally:
        HC.enabled, HC.kw_overlaps = saved


def _client_tree(td, rules=None, issuer=None):
    import sites as S
    td = Path(td)
    (td / "sites").mkdir()
    for p in S.SITES_DIR.glob("*.json"):
        shutil.copy(p, td / "sites" / p.name)
    cfg = {"id": "h10-dent", "name": "試験デンタルコラム", "domain": "dent.example.test", "type": "ftp", "theme": "t",
           "url_prefix": "/column", "categories": {"h10-col": "コラム"}}
    if rules:
        cfg["rules"] = rules
    if issuer:
        cfg["report_issuer"] = issuer
    (td / "sites" / "h10-dent.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    (td / "data" / "clients" / "h10-dent").mkdir(parents=True)
    (td / "data" / "clients" / "h10-dent" / "company.json").write_text(json.dumps(
        {"name": "医療法人 試験会", "address": "京都府京都市下京区1-1", "tel": "075-000-0000",
         "supervisor": {"name": "試験 太郎"}}, ensure_ascii=False), encoding="utf-8")
    return td


def test_client_diagnosis_drops_operator_findings():
    import site_diagnosis as SD
    import sites as S
    print("\n■ お客様の診断に、全社共通の要対応（当社の社名）を出さない")
    old = (SD.FINDINGS, S.ROOT, S.SITES_DIR)
    try:
        with tempfile.TemporaryDirectory() as td:
            SD.FINDINGS = Path(td) / "findings.txt"
            SD.FINDINGS.write_text("要対応: セブンセンシズ コーポレートサイト — 1/2 本でした\n要対応: 共通の話\n",
                                   encoding="utf-8")
            check("自社: 全部出る", len(SD.findings("ai-lab")), 2)
            S.ROOT = _client_tree(td, issuer="client")
            S.SITES_DIR = S.ROOT / "sites"
            check("お客様: 当社の社名を含む行は出ない", SD.findings("h10-dent"), ["要対応: 共通の話"])
    finally:
        SD.FINDINGS, S.ROOT, S.SITES_DIR = old


def test_monthly_report_issuer_is_selectable():
    import client_intake as ci
    import monthly_report as MR
    import sites as S
    print("\n■ お客様の月次レポートの名義（report_issuer）")
    check("シートの欄 → report_issuer", [ci.to_config({"report_issuer": v}).get("report_issuer")
                                        for v in ("お客様名だけ", "当社名を出す", "")], ["client", "operator", "operator"])
    check("シートに欄がある", any(f[0] == "report_issuer" for f in ci.fields_for()), True)
    old = (S.ROOT, S.SITES_DIR, MR.SITE_ID)
    try:
        for mode in ("client", "operator"):
            with tempfile.TemporaryDirectory() as td:
                S.ROOT = _client_tree(td, issuer=mode)
                S.SITES_DIR = S.ROOT / "sites"
                MR.SITE_ID = "h10-dent"
                d = MR.fetch_demo()
                page = MR.render(d, MR.analyze(d))
                cover = page.split("発行: ")[1][:40]
                back = page[page.rfind('class="sheet back-cover"'):]
                if mode == "client":
                    check("client: 表紙の発行はお客様の社名", cover.startswith("<b>医療法人 試験会</b>"), True)
                    check("client: 当社の名前・URL・ロゴが出ない",
                          ([m for m in S.OPERATOR_MARKS if m in page], '<img class="cv-logo"' in page), ([], False))
                    check("client: 巻末はお客様の住所とサイト", ("京都府京都市下京区1-1" in back, "https://dent.example.test" in back),
                          (True, True))
                else:
                    check("operator（既定）: 今の形（発行: セブンセンシズ・巻末の当社URL）",
                          (cover.startswith("<b>セブンセンシズ株式会社</b>"), "https://ai.7senses.co.jp" in back), (True, True))
        S.ROOT, S.SITES_DIR = old[0], old[1]
        MR.SITE_ID = "ai-lab"
        check("自社サイトは report_issuer に関係なく当社名義", MR.issuer()["operator"], True)
    finally:
        S.ROOT, S.SITES_DIR, MR.SITE_ID = old
    import inspect
    check("当社名が残ったお客様名義のレポートは PDF を作らない", "issuer_leaks(html)" in inspect.getsource(MR._main), True)
    import report_digest as RD
    check("まとめ送信でお客様名義のPDFに印を付ける", "issuer_label(r['site'])" in inspect.getsource(RD.main), True)


def test_client_review_holds_lists_and_releases():
    import deliver_files as DF
    import editorial_review as ER
    import publish as P
    import scaled_guard as SG
    import sites as S
    print("\n■ 公開前の確認を「要」にしたお客様: HELD → 社ごとの通知 → 承認で配信へ（dry）")
    old = (S.ROOT, S.SITES_DIR, ER.ROOT, ER.LEDGER, P.ROOT, DF.ROOT, DF.WORK, SG.check, sys.argv)
    try:
        with tempfile.TemporaryDirectory() as td:
            root = _client_tree(td, rules={"review_before_publish": True})
            written = (datetime.now(timezone(timedelta(hours=9))).date() - timedelta(days=3)).isoformat()
            (root / "articles").mkdir()
            body = "\n\n".join(f"## 見出し{i}\n\n" + "歯科の予約を増やすには、診療の内容と料金を先に示します。" * 8
                               for i in range(6))
            (root / "articles" / "h10-yoyaku.md").write_text(
                "---\ntitle: 歯科の予約を増やす5つの方法\ndescription: " + "歯科医院の予約を増やす方法を説明します。" * 4 +
                f"\nslug: h10-yoyaku\nkeyword: 歯科 予約 増やす\ncategory: h10-col\ndate: {written}\n"
                "score: 95\nscore_breakdown: {originality: 95, extractability: 95, decision: 95}\n---\n\n" + body + "\n",
                encoding="utf-8")
            S.ROOT, S.SITES_DIR = root, root / "sites"
            ER.ROOT, ER.LEDGER = root, root / "data" / "editorial_reviews.jsonl"
            P.ROOT, DF.WORK = root, root / ".publish-work"   # 雛形は本物の templates/ を読む（書き込みは一時フォルダだけ）
            SG.check = lambda *a, **k: []
            ER._SITE.clear()
            check("記録が無い間は HELD（reviewed=False・待ちの一覧に入る）",
                  (ER.reviewed("h10-yoyaku"), ER.pending()), (False, ["h10-yoyaku"]))
            lines = ER.notify_lines()
            text = "\n".join(lines)
            check("通知: 社ごとの要対応1行（社名・本数・待った日数）",
                  lines[0], "要対応: 公開前の確認待ち — 試験デンタルコラム（h10-dent）1本（最長3日待ち）")
            check("通知: 記事の題・原稿のURL・公開予定のURL",
                  ("「歯科の予約を増やす5つの方法」" in text, "articles/h10-yoyaku.md" in text,
                   "https://dent.example.test/column/h10-yoyaku/" in text), (True, True, True))
            check("通知: 承認の手順（Actions の「監修の記録」と --approve）",
                  ("approve-review.yml" in text and "--approve <slug>" in text), True)
            check("監修者への自動メールは作らない（送信の処理が無い）",
                  any(w in __import__("inspect").getsource(ER) for w in ("resend", "urlopen", "smtplib")), False)
            sys.argv = ["publish.py", "--site", "h10-dent", "--slug", "h10-yoyaku"]
            try:
                P.main()
                held = ""
            except SystemExit as e:
                held = str(e.code)
            check("承認前の配信は HELD で止まる", held.startswith("HELD(監修待ち): h10-yoyaku"), True)
            ER.record(["h10-yoyaku"], by=ER.reviewer_for("h10-yoyaku"))
            check("承認後は待ちから消える", (ER.reviewed("h10-yoyaku"), ER.pending(), ER.notify_lines()), (True, [], []))
            check("記録の監修者はお客様の監修者", ER.load()["h10-yoyaku"]["by"], "試験 太郎")
            try:
                P.main()
                after = "配信まで進んだ"
            except SystemExit as e:
                after = str(e.code)
            check("承認後は配信まで進む（--push なしの dry）", after, "配信まで進んだ")
    finally:
        (S.ROOT, S.SITES_DIR, ER.ROOT, ER.LEDGER, P.ROOT, DF.ROOT, DF.WORK, SG.check, sys.argv) = old
        ER._SITE.clear()
    wf = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8")
    check("日次の記事CIが、その枠の社の確認待ちを通知本文へ足す",
          'editorial_review.py --notify --site "${{ steps.site.outputs.id }}"' in wf, True)
