# -*- coding: utf-8 -*-
"""競合比較のループの門（2026-10-05）。

測る（compete --measure）→ 負けている理由を出す（--gaps）→ 埋める（auto_rewrite --kind compete）→
効いたかで残すか戻す（effect_ab --rewrites・rewrite_rollback）→ 見せる（月次レポート・週次の要対応）。
固定すること: 出典の種類分け（ポータル・公的機関・百科事典・まとめを同業と混ぜない）／母数10未満は割合にしない／
競合の文を写さない・出典URLを増やさない／月の上限を超えたらAIを呼ばない／compete も効果判定と戻しの対象。
本物のAI・競合のサイト・Search Console には触れない（偽のエンジン・一時フォルダ・手元の記録だけ）。
"""
import hashlib
import io
import json
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from test_gates import check, ROOT


def _rec(n_answered, n_ours, comps=(("rival-a.example", 3),)):
    items = []
    for i in range(n_answered):
        doms = {d: 1 for d, n in comps if i < n}
        doms["ja.wikipedia.org"] = 1
        items.append({"kw": f"語{i}", "pos": 5.0 if i % 2 else 25.0, "imp": 10, "url": "", "slug": "",
                      "ai": {"Claude": {"answered": True, "ours": i < n_ours, "domains": list(doms), "urls": []}},
                      "ai_answered": True, "ai_ours": i < n_ours, "ai_domains": doms})
    return items


def test_sources_are_typed_and_peers_are_not_mixed():
    import compete as C
    print("\n■ 競合比較: 出典の種類分け")
    mine, op = {"mine.example"}, {"ai.7senses.co.jp"}
    got = {d: C.kind_of(d, mine, op) for d in
           ("nta.go.jp", "city.osaka.lg.jp", "ja.wikipedia.org", "kotobank.jp", "epark.jp", "suumo.jp",
            "youtube.com", "prtimes.jp", "mine.example", "blog.mine.example", "ai.7senses.co.jp", "rival-dental.example")}
    check("公的機関・百科事典・ポータル・動画・メディアを同業と分ける", got, {
        "nta.go.jp": "public", "city.osaka.lg.jp": "public", "ja.wikipedia.org": "wiki", "kotobank.jp": "wiki",
        "epark.jp": "portal", "suumo.jp": "portal", "youtube.com": "video", "prtimes.jp": "media",
        "mine.example": "self", "blog.mine.example": "self", "ai.7senses.co.jp": "operator",
        "rival-dental.example": "peer"})
    check("Gemini の転送URLはどのサイトか分からないので数えない",
          C.domain_of("https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc"), "")
    s = C.summarize(_rec(12, 2, (("rival-a.example", 5), ("once.example", 1))), mine, op)
    check("競合は同業だけ・2語以上で出たドメインだけ（百科事典・1語だけの相手は入れない）",
          [c["domain"] for c in s["competitors"]], ["rival-a.example"])
    check("同業以外は種類ごとに別に残す", s["other_types"].get("wiki"), ["ja.wikipedia.org"])
    import sites as S
    if S.own_ids():
        sid = S.own_ids()[0]
        m, o = C.site_domains(sid, S.load(sid))
        check("自社3サイトのシェアは自分のドメインだけで数え、兄弟サイトは競合にしない（operator 扱い）",
              (len(m), S.load(sid)["domain"].replace("www.", "") in m, bool(o) == (len(S.own_ids()) > 1)), (1, True, True))


def test_small_samples_are_not_shown_as_rates():
    import compete as C
    print("\n■ 競合比較: 母数10未満は割合にしない")
    check("9語では割合を出さない／10語なら出す", (C.share(3, 9), C.share(3, 10)), (None, 0.3))
    check("表示は件数と理由", "割合にしません" in C.fmt_share(3, 9) and "%" not in C.fmt_share(3, 9), True)
    s = C.summarize(_rec(9, 3), set(), set())
    check("AIのシェア・競合のシェアとも None（9語）", (s["ai"]["share"], s["competitors"][0]["ai_share"]), (None, None))
    with tempfile.TemporaryDirectory() as td:
        old = C.OUT
        try:
            C.OUT = Path(td)
            (C.OUT / "x").mkdir()
            rec = {"site": "x", "ym": "2026-10", "measured": "2026-10-05", "mode": "live", "gsc_window": "2026-09-04〜2026-10-02",
                   "engines": ["Claude"], "items": _rec(9, 3), "summary": s}
            (C.OUT / "x" / "2026-10.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
            p1, p2 = C.report_html("x", client=True)
            check("レポートの節: 9語は割合でなく件数・母数と期間を添える",
                  ["33%" not in p1, "3/9語" in p1, "2026-09-04〜2026-10-02" in p1, "母数" in p1], [True] * 4)
            check("お客様の名義では「御社にご用意いただきたいもの」", "御社にご用意いただきたいもの" in p2, True)
        finally:
            C.OUT = old


def test_competitor_text_is_not_copied():
    import auto_rewrite as A
    import compete as C
    print("\n■ 競合比較: 写さない・出典URLを増やさない")
    html = ("<html><body><h2>第1章 医院の口コミが減る本当の理由とは</h2><p>" + "本文" * 3000 + "</p>"
            "<table><tr><td>1</td></tr></table><script>var x=1</script></body></html>")
    f = C.page_features(html)
    check("競合ページは見出し（40字まで）と数えた特徴だけを残す（本文を持たない）",
          (sorted(f), all(len(h) <= 40 for h in f["heads"]), f["heads"][0]),
          (["chars", "heads", "modified", "primary", "questions", "tables"], True, "医院の口コミが減る本当の理由とは"))
    gap = {"their_pages": [{"heads": ["医院の口コミが減る本当の理由とは"]}]}
    b = "---\ntitle: 口コミ返信の書き方\n---\n## はじめに\n本文です。\n"
    ok_add = b + "## 低い評価が続くときの見直し方\n患者さんの声を週ごとに読み返します。\n"
    check("自分の言葉で節を足す直しは通す", A.compete_guard(b, ok_add, "t", "t", gap), "")
    check("競合の見出しを写したら止める",
          A.compete_guard(b, b + "## 医院の口コミが減る本当の理由とは\n説明。\n", "t", "t", gap).startswith("競合の見出し"), True)
    check("出典URLを足したら止める",
          A.compete_guard(b, b + "[資料](https://example.com/x)\n", "t", "t", gap).startswith("出典のURL"), True)
    check("題を変えたら止める", A.compete_guard(b, ok_add, "t", "t2", gap).startswith("タイトル"), True)
    check("本文を削ったら止める", A.compete_guard(b, b[:20], "t", "t", gap).startswith("本文が減り"), True)
    mine = {"heads": ["はじめに"], "tables": 0, "modified": "2026-01-01", "primary": "", "chars": 3000, "body": "はじめに"}
    theirs = [{"questions": [], "tables": 0, "modified": "", "primary": "アンケート", "chars": 3000}]
    d, act, wish = C.decide("口コミ 返信", mine, theirs, [])
    check("差が一次データだけで登録が無ければ書き直さず要望にする", (act, "アンケート" in wish), ("needs_data", True))
    check("登録済みの一次データがあれば書き直しに回す", C.decide("口コミ 返信", mine, theirs, ["口コミ返信は42件"])[1], "rewrite")


def test_ai_budget_stops_before_calling():
    import ai_cite_check as AC
    import compete as C
    import sites as S
    print("\n■ 競合比較: 月の上限を超えたらAIを呼ばずに知らせる")
    calls = []

    def fake(q):
        calls.append(q)
        return ["https://rival-a.example/p"]
    sid = next((s for s in S.load_all() if (ROOT / "data" / "ranks" / f"{s}.json").is_file()), "")
    if not sid:
        check("順位の記録があるサイト（試しに使う）", False, True)
        return
    cfg = dict(S.load(sid))
    cfg["compete"] = {"ai_cap": 3}
    with tempfile.TemporaryDirectory() as td:
        old = (C.OUT, C.USAGE, AC.CACHE_DIR, C.ledger_words)
        try:
            C.OUT, C.USAGE, AC.CACHE_DIR = Path(td) / "c", Path(td) / "c" / "_usage.json", Path(td) / "cache"
            C.ledger_words = lambda sid: []          # 管制塔へ通信しない
            out = io.StringIO()
            with redirect_stdout(out):
                C.measure_site(sid, cfg, dry=True, eng={"Fake": fake})
            check("dry-run は聞かない・何も書かない", (calls, (C.OUT / sid).exists()), ([], False))
            with redirect_stdout(out):
                rec = C.measure_site(sid, cfg, eng={"Fake": fake}, usage={})
            check("上限（3回）を超える見込みなら1回も聞かない", calls, [])
            check("記録には上限で止めたことを残し、要対応を出す",
                  (rec["status"], "要対応:" in out.getvalue(), json.loads(C.USAGE.read_text()) if C.USAGE.exists() else {}),
                  ("over_cap", True, {}))
            cfg["compete"] = {"ai_cap": 1000}
            with redirect_stdout(io.StringIO()):
                rec = C.measure_site(sid, cfg, eng={"Fake": fake}, usage={})
            check("上限内なら聞き、使った回数を月ごとに残す",
                  (rec["status"], len(calls) == rec["summary"]["kw_n"],
                   json.loads(C.USAGE.read_text()).get(rec["ym"], {}).get(sid)), ("ok", True, rec["summary"]["kw_n"]))
        finally:
            C.OUT, C.USAGE, AC.CACHE_DIR, C.ledger_words = old
    mon = (ROOT / ".github" / "workflows" / "monthly-report.yml").read_text(encoding="utf-8")
    check("月次CI: 課金の前に dry-run を記録し、レポートより先に測る",
          [mon.find("compete.py --measure --dry-run") < mon.find("compete.py --measure 2>&1") < mon.find("monthly_report.py --site")
           and mon.find("compete.py --measure --dry-run") > 0, "compete.py --gaps" in mon], [True, True])


def test_compete_rewrites_are_judged_and_rolled_back():
    import auto_rewrite as A
    import effect_ab as EA
    import rewrite_rollback as RB
    print("\n■ 競合比較: compete の書き直しも効果判定と戻しの対象")
    with tempfile.TemporaryDirectory() as td:
        r = Path(td)
        (r / "articles").mkdir()
        art = r / "articles" / "h14-a.md"
        art.write_bytes(b"before\n")
        oldA, oldRB, oldLOG = A.ROOT, RB.ROOT, RB.LOG
        try:
            A.ROOT = RB.ROOT = r
            kept = A.keep_before("h14-a", b"before\n", b"after\n")
            art.write_bytes(b"after\n")
            log = r / "auto_fix.jsonl"
            line = {"at": "2026-08-01 10:00", "by": "auto_rewrite", "slug": "h14-a", "kind": "compete", "ok": True,
                    "note": "直しました（a… → a…）", "before_title": "t", **kept}
            log.write_text(json.dumps(line, ensure_ascii=False) + "\n", encoding="utf-8")
            check("effect_ab --rewrites が compete の書き直しを数える（種類別・対照群比）",
                  [x["kind"] for x in EA.rewrites(log)], ["compete"])
            RB.LOG = log
            check("rewrite_rollback が compete を戻す候補に入れる", [d["kind"] for d in RB.entries()], ["compete"])
            check("直した後だれも触っていなければ、直す前の原稿へ戻す",
                  (RB.restore("h14-a", line), art.read_bytes()), (True, b"before\n"))
            art.write_bytes(b"after-and-edited\n")
            with redirect_stdout(io.StringIO()) as o:
                ok = RB.restore("h14-a", line)
            check("後から別の直しが入っていたら戻さず要対応", (ok, "要対応:" in o.getvalue(), art.read_bytes()),
                  (False, True, b"after-and-edited\n"))
            check("台帳に残す after_sha は直した後の中身", kept["after_sha"], hashlib.sha1(b"after\n").hexdigest())
        finally:
            A.ROOT, RB.ROOT, RB.LOG = oldA, oldRB, oldLOG


def test_compete_loop_is_wired():
    import compete as C
    import findings as F
    import inspect
    import monthly_report as MR
    print("\n■ 競合比較: 週次・月次・レポートにつながっている")
    check("週次の要対応に「AIのシェアが下がった語」", any(s.startswith("compete.py --check") for _, s, _ in F.CHECKS), True)
    wk = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週次CI: compete の書き直し（週2本・予算つき）と戻しの要対応",
          ["--kind compete --limit $n" in wk, "rewrite_rollback.py --write 2>&1) || true" in wk], [True, True])
    check("月次レポートに競合比較の節（お客様名義でも出す）",
          ["compete_pages" in inspect.getsource(MR.render), "is_client(SITE_ID)" in inspect.getsource(MR.render)], [True, True])
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    check("お客様の競合比較は public に置かない（自社3サイトだけコミット）",
          ["data/compete/*" in gi, "!data/compete/ai-lab/" in gi], [True, True])
    with tempfile.TemporaryDirectory() as td:
        old = C.OUT
        try:
            C.OUT = Path(td)
            import sites as S
            sid = next(iter(S.load_all()))
            (C.OUT / sid).mkdir()
            (C.OUT / sid / "2026-10.json").write_text(json.dumps(
                {"ym": "2026-10", "diff": {"from": "2026-09", "lost": ["語A"]}, "items": []}, ensure_ascii=False), encoding="utf-8")
            (C.OUT / sid / "gaps.json").write_text(json.dumps(
                {"items": [{"kw": "語B", "action": "needs_data", "wish": "対応件数（期間と母数つき）"}]}, ensure_ascii=False),
                encoding="utf-8")
            with redirect_stdout(io.StringIO()) as o:
                C.check([sid])
            v = o.getvalue()
            check("--check: 外れた語と一次データの要望を要対応で出す（印で判定）",
                  ["AIのシェアが下がった語 1語" in v, "  - 語A" in v, "一次データがあれば勝てる語" in v, "COMPETE_OK=no" in v],
                  [True] * 4)
        finally:
            C.OUT = old
