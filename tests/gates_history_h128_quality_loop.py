# -*- coding: utf-8 -*-
"""2026-10-20 運用者の決定「公開前に、書いたAIとは別の工程で3観点を採点し、基準未満なら公開を止める」
「書かない選択肢はない。1度や2度で完璧にするように」の門（scripts/quality_loop.py）。

採点と直しの AI（claude）は差し替えて動かす（本物の claude・課金の API は呼ばない）。
- 1回目の採点で届けば、機械が score・score_breakdown・quality_attempts を書いて公開できる
- 届かなければ直して採点し直す。2回直しても届かなければ quality_state: improving のまま公開しない（gate_why・build）
- 次の回は直している記事を新しい記事より先に直す（--pending）
- 引用の無い・本文に無い引用の採点は無効。基準の近くは2回採点して軸ごとに低い方
- 点数は機械だけが書く（書く AI の点数は消す・直しの AI が点数の行を変えたら戻す・合格の記録の無い記事は配らない）
- ワークフローの順番と、鍵を外した中で動くこと。お客様の記事の名前をログに出さないこと
"""
import contextlib
import io
import json
import os
import re
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

BODY = ("この記事は中小企業の担当者向けです。AIO対策は、AIの答えに自社の情報が引用されるように整えることです。\n\n"
        "## 何から始めるか\n\n当社では、最初に検索の実績を見てから直す記事を決めています。\n\n"
        "## 向かない場合\n\n更新する人がいない場合は、外部に任せるほうが続きます。\n")


@contextlib.contextmanager
def patched(*items):
    old = [(o, n, getattr(o, n, None), hasattr(o, n)) for o, n, _ in items]
    try:
        for o, n, v in items:
            setattr(o, n, v)
        yield
    finally:
        for o, n, v, had in old:
            if had:
                setattr(o, n, v)
            else:
                delattr(o, n)


def quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


def _art(extra=""):
    return ("---\ntitle: AIO対策のはじめ方を中小企業向けに解説\nslug: zz-aio\ncategory: aio\nkeyword: aio 対策\n"
            "date: 2026-10-20\ndescription: 説明です。\n" + extra + "---\n" + BODY)


def _answer(o=95, e=95, d=95, quote="当社では、最初に検索の実績を見てから直す記事を決めています。"):
    """採点の AI の応答（JSON）。quote が None なら引用を付けない"""
    def ax(v):
        x = {"score": v, "weaknesses": ["一次情報の数字が無い"]}
        if quote is not None:
            x["quote"] = quote
        return x
    return "前置き\n```json\n" + json.dumps({"originality": ax(o), "extractability": ax(e), "decision": ax(d)},
                                           ensure_ascii=False) + "\n```\n"


class Env:
    """一時フォルダの articles/ と台帳で quality_loop を動かす（本物の記事・台帳は触らない）"""

    def __init__(self, d, site="ai-lab"):
        self.root = Path(d)
        (self.root / "articles").mkdir()
        self.log = self.root / "quality_loop.jsonl"
        self.site = site

    def put(self, slug, text):
        (self.root / "articles" / f"{slug}.md").write_text(text, encoding="utf-8")

    def get(self, slug):
        return (self.root / "articles" / f"{slug}.md").read_text(encoding="utf-8")

    def meta(self, slug):
        import quality_loop as QL
        return QL.meta_of(self.get(slug))

    def patches(self, QL, answers, improve=None):
        calls = {"ask": 0, "improve": 0}
        seq = list(answers)

        def ask(prompt, cwd):
            calls["ask"] += 1
            return seq.pop(0) if len(seq) > 1 else seq[0]

        def imp(slug, sc, blocked):
            calls["improve"] += 1
            if improve:
                return improve(slug, sc)
            return True, "直しました（テスト）"
        self.calls = calls
        return [(QL, "ARTICLES", self.root / "articles"), (QL, "LOG", self.log), (QL, "ASK", ask),
                (QL, "IMPROVE", imp), (QL, "blocked_lines", lambda: set()), (QL, "site_of", lambda s: self.site)]


def test_pass_on_first_score_machine_writes_score():
    import quality_loop as QL
    import rubric as R
    print("\n■ 公開前の採点: 1回目で届けば、機械が点数を書いて公開できる（書く AI の点数は消す）")
    with tempfile.TemporaryDirectory() as d:
        e = Env(d)
        # 書く AI が勝手に書いた点数（95・旧6観点）は残さない
        e.put("zz-aio", _art("score: 95\nscore_breakdown: {aio: 20, design: 20, editorial: 20, expert: 20, persona: 20, seo: 20}\n"))
        with patched(*e.patches(QL, [_answer(95, 94, 96)])):
            res, out = quiet(QL.run, ["zz-aio"], "new", QL.Budget(None))
        m = e.meta("zz-aio")
        check("届いた", res, {"passed": 1})
        check("機械が書いた点数（平均・3観点・回数）", (m.get("score"), m.get("score_breakdown"), m.get("quality_attempts")),
              (95, {"originality": 95, "extractability": 94, "decision": 96}, 1))
        check("改善中の印は外れる", "quality_state" in m, False)
        check("公開の門を通る", R.gate_why(m), "")
        rows = [json.loads(x) for x in e.log.read_text(encoding="utf-8").splitlines()]
        check("台帳に合格の記録", any(r.get("action") == "pass" and r.get("total") == 95 for r in rows), True)
        check("合格の記録を機械の採点と認める", QL.machine_passed("zz-aio", m, e.log), True)
        check("基準の近くでなければ1回だけ採点する", e.calls["ask"], 1)


def test_pass_after_one_improvement():
    import quality_loop as QL
    print("\n■ 届かなければ直して採点し直す。1回の直しで届けば点数を書く")
    with tempfile.TemporaryDirectory() as d:
        e = Env(d)
        e.put("zz-aio", _art())
        with patched(*e.patches(QL, [_answer(60, 85, 80), _answer(95, 95, 95)])):
            res, out = quiet(QL.run, ["zz-aio"], "new", QL.Budget(None))
        m = e.meta("zz-aio")
        check("1回直して届いた", (res, e.calls["improve"]), ({"passed": 1}, 1))
        check("回数は2（採点→直し→採点）", m.get("quality_attempts"), 2)
        rows = [json.loads(x) for x in e.log.read_text(encoding="utf-8").splitlines()]
        check("直した記録が残る", [r["action"] for r in rows], ["score", "improve", "score", "pass"])


def test_still_failing_after_two_rounds_stays_unpublished():
    import quality_loop as QL
    import rubric as R
    import daily_audit as DA
    print("\n■ 2回直しても届かなければ、捨てずに改善中のまま公開しない（gate_why・build が止める）")
    with tempfile.TemporaryDirectory() as d:
        e = Env(d)
        e.put("zz-aio", _art("score: 90\n"))
        with patched(*e.patches(QL, [_answer(60, 85, 80)])):
            res, out = quiet(QL.run, ["zz-aio"], "new", QL.Budget(None))
        m = e.meta("zz-aio")
        check("直しは2回まで", (res, e.calls["improve"]), ({"improving": 1}, 2))
        check("改善中の印・点数なし", (m.get("quality_state"), m.get("score")), ("improving", None))
        check("記事は消さない", (e.root / "articles" / "zz-aio.md").is_file(), True)
        check("要対応で知らせる", "要対応:" in out, True)
        check("公開の門が止める", bool(R.gate_why(m)) and not R.gate_ok(m), True)
        # 点数が書かれていても、改善中の印がある間は止める
        check("点数があっても改善中なら止める", R.gate_ok({"score": 95, "quality_state": "improving"}), False)
        b = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
        i, j = b.find("rubric.improving(meta)"), b.find("未審査（score が数値で記載されていない")
        check("build.py は改善中を BLOCKED と分けて先に止める（救済の AI に点数を書かせない）",
              (0 < i < j, "IMPROVING(品質の改善中)" in b), (True, True))
        # 救済が「足りない」として別の記事を書き足さない（書いた本数には数える・公開済みには数えない）
        a = {"score": "", "quality_state": "improving"}
        check("本数には数え、公開済みには数えない", (DA._is_published(a, need_review=False), DA._is_published(a)),
              (True, False))


def test_pending_first_next_run():
    import quality_loop as QL
    print("\n■ 次の回は、直している記事を新しい記事より先に直す")
    with tempfile.TemporaryDirectory() as d:
        e = Env(d)
        old = (date.today() - timedelta(days=2)).isoformat()
        e.put("zz-old", _art(f"quality_state: improving\nquality_since: {old}\n").replace("date: 2026-10-20", f"date: {old}"))
        e.put("zz-older", _art(f"quality_state: improving\nquality_since: {(date.today() - timedelta(days=3)).isoformat()}\n"))
        e.put("zz-new", _art())
        order = []

        def fake_run(slugs, mode, budget, rounds=2):
            order.append((mode, list(slugs)))
            return {}
        import shutil
        with patched(*e.patches(QL, [_answer()]), (QL, "run", fake_run), (QL, "new_articles", lambda sites=(): ["zz-new"]),
                     (shutil, "which", lambda n: "/x/claude")):
            quiet(QL.main, ["--pending", "--new"])
        check("直している記事（古い順）→ 新しい記事の順", order, [("pending", ["zz-older", "zz-old"]), ("new", ["zz-new"])])
        check("新しい記事には先に印を付ける（途中で止まっても公開されない）", e.meta("zz-new").get("quality_state"), "improving")
        # 前の日に書いて今日届いた記事は、公開する今日の日付になる
        with patched(*e.patches(QL, [_answer()])):
            quiet(QL.run, ["zz-old"], "pending", QL.Budget(None))
        check("届いたら今日の日付で公開", str(e.meta("zz-old").get("date")), date.today().isoformat())
        check("この実行で届いた記事は配信の手順へ渡る", QL.released(os.environ.get("GITHUB_RUN_ID", ""), e.log), ["zz-old"])
    w = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8")
    # 運用者「書かない選択肢はない」（2026-10-20）: 直している記事が残っても、その回の新しい記事は書く
    check("直している記事が残っても新しい記事は書く（hold で止めない）",
          "steps.qpending.outputs.hold" in w or 'echo "hold=yes"' in w, False)
    check("記事の枠は120分・採点と直しは配信の15分を残す",
          ("timeout-minutes: 120" in w, "budget=$(( 105 - used ))" in w), (True, True))


def test_scorer_output_without_quotes_is_rejected():
    import quality_loop as QL
    print("\n■ 引用の無い・本文に無い引用の採点は無効（1回だけ聞き直し、だめなら採点できなかったとして公開しない）")
    art = _art()
    check("引用なし", QL.parse(_answer(quote=None), art)[0], None)
    check("本文に無い引用（作った文）", QL.parse(_answer(quote="当社は3,000社の採択を支援しました。"), art)[0], None)
    check("短すぎる引用", QL.parse(_answer(quote="当社"), art)[0], None)
    check("点が範囲外", QL.parse(_answer(o=120), art)[0], None)
    check("JSON でない", QL.parse("SCORES originality=90", art)[0], None)
    ok, _ = QL.parse(_answer(quote="**当社では、最初に検索の実績を見てから**直す記事を決めています"), art)
    check("強調の記号の違いは同じ引用とみなす", bool(ok), True)
    ok2, _ = QL.parse(_answer(quote="当社では、最初に検索の実績を…直す記事を決めています。"), art)
    check("「…」で省いた引用は、各部分が本文にあればよい", bool(ok2), True)
    with tempfile.TemporaryDirectory() as d:
        e = Env(d)
        e.put("zz-aio", _art())
        with patched(*e.patches(QL, [_answer(quote=None)])):
            res, out = quiet(QL.run, ["zz-aio"], "new", QL.Budget(None))
        check("聞き直しは1回（合わせて2回）", e.calls["ask"], 2)
        check("採点できなかった記事は改善中のまま", (res, e.meta("zz-aio").get("quality_state"), "要対応:" in out),
              ({"error": 1}, "improving", True))
        # 引用が無効でも、聞き直して直れば使う
    with tempfile.TemporaryDirectory() as d:
        e = Env(d)
        e.put("zz-aio", _art())
        with patched(*e.patches(QL, [_answer(quote=None), _answer(96, 96, 96)])):
            res, _ = quiet(QL.run, ["zz-aio"], "new", QL.Budget(None))
        check("聞き直して引用が付けば使う", res, {"passed": 1})


def test_double_scoring_near_threshold_uses_lower():
    import quality_loop as QL
    print("\n■ 基準の近く（平均88〜93・1軸78〜84）は2回採点し、軸ごとに低い方を使う")
    check("近さの判定", (QL.near({"originality": 91, "extractability": 91, "decision": 91}),
                         QL.near({"originality": 96, "extractability": 82, "decision": 97}),
                         QL.near({"originality": 97, "extractability": 96, "decision": 98}),
                         QL.near({"originality": 60, "extractability": 60, "decision": 60})), (True, True, False, False))
    with tempfile.TemporaryDirectory() as d:
        e = Env(d)
        e.put("zz-aio", _art())
        # 1回目は平均91（合格）でも、2回目に一次性が79なら低い方で不合格
        with patched(*e.patches(QL, [_answer(91, 92, 90), _answer(79, 95, 96)]),
                     (QL, "IMPROVE", lambda s, sc, b: (False, "変更なし"))):
            sc, _ = QL.score("zz-aio")
        check("2回採点した", (sc["double"], sc["calls"]), (True, 2))
        check("軸ごとに低い方", sc["axes"], {"originality": 79, "extractability": 92, "decision": 90})
        check("低い方で不合格", sc["ok"], False)


def test_machine_only_writes_scores():
    import quality_loop as QL
    import auto_rewrite as A
    import agent_guard as G
    import hashlib
    print("\n■ 点数は機械だけが書く（書く AI・直す AI が書いた点数を通さない・合格の記録の無い記事は配らない）")
    before = _art("quality_state: improving\nquality_since: 2026-10-20\n")
    check("直す AI が点数を書いたら戻す", bool(A.quality_guard(before, before.replace("quality_state: improving\n", "score: 95\n"))),
          True)
    check("直す AI が改善中の印を消したら戻す", bool(A.quality_guard(before, before.replace("quality_state: improving\n", ""))), True)
    check("本文を足すだけなら通す", A.quality_guard(before, before + "\n## 次の一歩\n\n今日できることを書きます。\n"), "")
    check("本文を大きく削ったら戻す", bool(A.quality_guard(before, before[:len(before) // 2])), True)
    with patched((A, "site_of", lambda s: "ai-lab")):
        import facts as F
        fs = [{"claim": "当サイトの実測では「aio 診断」は平均5.1位でした", "source": "自社サイトのSearch Console実測", "as_of": "2026-10"}]
        with patched((F, "load_for", lambda sid: ({}, fs))):
            prompt, allowed = A.build_prompt({"kind": "quality_loop", "slug": "zz-none", "site": "ai-lab",
                                              "why": "x", "weak": "■ 一次性 60点"})
    check("直しの指示に採点者の指摘と一次情報（出典・時点つき）", ("■ 一次性 60点" in prompt,
                                                   "平均5.1位" in prompt and "2026-10時点" in prompt), (True, True))
    check("一次情報の数字は増えてよい数字に入る", "5.1" in allowed, True)
    check("点数の行は変えさせない（指示）", "点数（score・score_breakdown）と quality_ で始まる" in A.WHAT["quality_loop"], True)
    # 2026-10-20 の実地の試し: 直しが2回とも「3点」「1か月近く」を足して数字の検算で戻された。その後、運用者の決定で
    # 品質ループの直しは数字の検算をしない（「事実でない数字を防ぐ検算なしにして」）。仮の計算例・目安を書けと指示する
    check("仮の計算例・判断の目安を書いてよいと指示する", "仮の計算例" in A.WHAT["quality_loop"], True)
    # 2回目の試し: 一次情報の213字の1文を丸ごと貼り、長文・段落の警告で戻された
    check("長い一次情報の文は数字を変えずに分けると指示する", "数字・出典・時点を変えずに2〜3文に分けて" in A.WHAT["quality_loop"], True)
    sc = {"axes": {"originality": 70, "extractability": 85, "decision": 85}, "quotes": {k: "x" for k in QL.AXIS_KEYS},
          "weak": {k: [] for k in QL.AXIS_KEYS}, "retry_note": "本文に無かった数字が増えました: {'3点': 1}"}
    check("2回目の直しに前に戻された理由を渡す", "前の直しは検算で戻されました" in QL.weak_text(sc), True)
    # 配信の手順: 書く AI が点数を書いた新しい記事（合格の記録なし）は配らず、改善中にして次の回へ回す
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "articles").mkdir()
        (root / "articles" / "zz-new.md").write_text(_art("score: 95\n"), encoding="utf-8")
        called = []

        class _Done:
            returncode, stdout, stderr = 0, "", ""

        def fake_run(cmd, **k):
            called.append(cmd[-1])
            return _Done()
        import score_check as SC
        log = root / "quality_loop.jsonl"
        with patched((G, "_load_state", lambda: {"articles": {}}), (G.subprocess, "run", fake_run),
                     (SC, "run", lambda slug, path=None: [("本文", True, "", False)]), (QL, "LOG", log),
                     (G, "_site_of", lambda s, r=None: "ai-lab")):
            res, out = quiet(G.publish, root, None)
        m = QL.meta_of((root / "articles" / "zz-new.md").read_text(encoding="utf-8"))
        check("配らない（失敗にも数えない）", (called, res["improving"], res["failed"]), ([], 1, 0))
        check("改善中にして書く AI の点数を消す", (m.get("quality_state"), m.get("score")), ("improving", None))
        # 合格の記録があれば配る
        (root / "articles" / "zz-ok.md").write_text(_art("score: 93\nscore_breakdown: {originality: 92, extractability: 93, decision: 94}\nquality_attempts: 1\n"),
                                                     encoding="utf-8")
        log.write_text(json.dumps({"slug": "zz-ok", "state": "passed", "action": "pass", "total": 93}) + "\n", encoding="utf-8")
        st = {"articles": {"zz-new": hashlib.sha1((root / "articles" / "zz-new.md").read_bytes()).hexdigest()}}
        called.clear()
        with patched((G, "_load_state", lambda: st), (G.subprocess, "run", fake_run),
                     (SC, "run", lambda slug, path=None: [("本文", True, "", False)]), (QL, "LOG", log),
                     (G, "_site_of", lambda s, r=None: "ai-lab")):
            res2, _ = quiet(G.publish, root, None)
        check("合格の記録のある記事は配る", called, ["zz-ok"])
    p = (ROOT / "automation" / "multi_site_prompt.txt").read_text(encoding="utf-8")
    check("書く AI の指示に「score: 90 を書く」が残っていない", "score: 90 を機械採点の通過印として書く" in p
          or "score: 90 を書いたら" in p, False)
    check("書く AI の指示が点数を書かないと言う", "score・score_breakdown・quality_ で始まる項目を書かない" in p, True)
    pp = (ROOT / "automation" / "pipeline_prompt.txt").read_text(encoding="utf-8")
    check("救済の指示も score: 90 を書かせない", "score: 90 を書いて" in pp or "score: 90（通過印）を書いたら" in pp, False)


def test_writer_brief_shows_rubric_and_facts_rule():
    import rubric as R
    print("\n■ 書く AI の案内に、採点の基準と「一次情報を2つ以上・文言どおり・出典と時点つき」と上位の調べが出る")
    s = (ROOT / "scripts" / "site_brief.py").read_text(encoding="utf-8")
    check("基準の文は rubric の1か所から", ("rubric.criteria_text()" in s, "kw_serp.brief(" in s), (True, True))
    check("一次情報を2つ以上・出典と時点", "2つ以上。文言・数字を変えず、出典と時点を添えて入れる" in s, True)
    t = R.criteria_text()
    check("基準の文に3軸と目安の点", all(a["name"] in t for a in R.AXES) and "80点" in t, True)
    check("公開後の採点（score_audit）も同じ文を使う", R.criteria_text() in R.prompt_for("x.html"), True)


def test_prescore_check_only_for_named_unscored_article():
    import os
    import rubric as R
    print("\n■ 書く AI の --check（点数の無い記事）は点数以外の門だけを通す。配信は点数が要る")
    m = {"slug": "zz-aio"}
    check("名指しが無ければ点数の無い記事は止める", bool(R.gate_why(m)), True)
    os.environ[R.PRESCORE_ENV] = "zz-aio"
    try:
        check("名指しした点数の無い記事は通す（点数以外の門を見るため）", R.gate_why(m), "")
        check("ほかの記事は止める", bool(R.gate_why({"slug": "zz-other"})), True)
        check("改善中の記事は名指しでも止める", bool(R.gate_why({"slug": "zz-aio", "quality_state": "improving"})), True)
        check("点数のある記事は今までどおり", bool(R.gate_why({"slug": "zz-aio", "score": 80})), True)
    finally:
        os.environ.pop(R.PRESCORE_ENV, None)
    pf = (ROOT / "scripts" / "publish_flow.py").read_text(encoding="utf-8")
    check("publish_flow は --check のときだけ名指しする", "prescore = check and" in pf, True)
    b = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    check("名指しの記事は公開台帳に載せない（新しい記事の門を外さない）", 'm["slug"] != _pre_slug' in b, True)


def _steps(text):
    return [m.group(1).strip() for m in re.finditer(r"^\s+- name: (.+)$", text, re.M)]


def test_workflows_run_the_loop_under_the_lock_in_order():
    print("\n■ ワークフロー: 鍵を外した中で、書いた後・配信の前に動く（記事の枠・救済・週次）")
    w = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8")
    names = _steps(w)

    def at(part):
        return next((i for i, n in enumerate(names) if part in n), -1)
    lock, qp, wr = at("AIの作業場から鍵を外す"), at("前の回から直している記事を先に"), at("記事生成（Phase 1〜7）")
    qn, prot, unl = at("この回に書いた記事を別工程で採点"), at("AIの変更のうち触ってはいけない場所を戻す"), at("AIの作業場に鍵を戻す")
    pub, gate = at("書いた記事を配信する"), at("食い合いゲート（執筆後）")
    check("記事の枠: 鍵を外す → 直している記事 → 執筆 → 採点と直し → 戻す → 鍵 → 配信 → 執筆後の門",
          0 < lock < qp < wr < qn < prot < unl < pub < gate, True)
    for name in ("公開前の品質ループ（前の回から直している記事を先に）", "公開前の品質ループ（この回に書いた記事を別工程で採点し、届くまで直す）"):
        blk = w.split("- name: " + name, 1)[1].split("\n      - ", 1)[0]
        check(f"{name[:24]}…: 鍵の確かめ・時間の上限・配信の鍵なし",
              ("agent_guard.py --verify" in blk, "--budget-min" in blk,
               any(k in blk for k in ("SITE_PUSH_TOKEN", "GCP_SERVICE_ACCOUNT_JSON", "HUB_SECRET", "FTP_CREDENTIALS_JSON"))),
              (True, True, False))
    r = (ROOT / ".github" / "workflows" / "pipeline.yml").read_text(encoding="utf-8")
    rn = _steps(r)
    i1 = next(i for i, n in enumerate(rn) if n.startswith("同日救済"))
    i2 = next(i for i, n in enumerate(rn) if "公開前の品質ループ" in n)
    i3 = next(i for i, n in enumerate(rn) if n == "AIの変更のうち触ってはいけない場所を戻す")
    i4 = next(i for i, n in enumerate(rn) if n.startswith("書いた記事を配信する"))
    check("救済: 書いた後・戻す前・配信の前", i1 < i2 < i3 < i4, True)
    blk = r.split("公開前の品質ループ（別工程の3観点の採点と直し）", 1)[1].split("\n      - ", 1)[0]
    check("救済: 範囲ごとに絞って回す・鍵の確かめ・直している記事が先",
          ("--scope" in blk and "--checkpoint" in blk and "--protect --site" in blk, "--verify" in blk,
           blk.find("--pending") < blk.find("--new")), (True, True, True))
    wk = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    wn = _steps(wk)
    k1 = next(i for i, n in enumerate(wn) if n.startswith("質問形・鮮度などの書き直しの前に作業場から鍵を外す"))
    k2 = next(i for i, n in enumerate(wn) if n.startswith("公開済みの記事を公開前と同じ基準で採点し直す"))
    k3 = next(i for i, n in enumerate(wn) if n.startswith("質問形・鮮度などの書き直しの後に作業場へ鍵を戻す"))
    check("週次: 公開済みの採点し直しは鍵を外した中", k1 < k2 < k3, True)
    blk = wk.split("- name: 公開済みの記事を公開前と同じ基準で採点し直す", 1)[1].split("\n      - ", 1)[0]
    check("週次: 社ごとの本数・時間の上限・全権の合言葉を空に",
          ("--rescore 4" in blk, "--budget-min" in blk, 'HUB_SECRET: ""' in blk), (True, True, True))


def test_published_articles_are_improved_in_place_never_unpublished():
    import quality_loop as QL
    import rubric as R
    print("\n■ 公開済みの記事は、届かなくても公開のまま直す（取り下げない）")
    with tempfile.TemporaryDirectory() as d:
        e = Env(d)
        e.put("zz-pub", _art("score: 95\n"))
        with patched(*e.patches(QL, [_answer(60, 85, 80)])):
            res, out = quiet(QL.run, ["zz-pub"], "rescore", QL.Budget(None))
        m = e.meta("zz-pub")
        check("届かなくても点数と公開はそのまま", (m.get("score"), m.get("quality_state"), R.gate_ok(m)), (95, None, True))
        check("直しは2回まで", e.calls["improve"], 2)
        rows = [json.loads(x) for x in e.log.read_text(encoding="utf-8").splitlines()]
        check("台帳では改善中", rows[-1].get("state"), "improving")
        # 次の週は前に届かなかった記事を先に採点し直す
        e.put("zz-pub2", _art("score: 92\n").replace("date: 2026-10-20", "date: 2026-01-01"))
        with patched(*e.patches(QL, [_answer()]), (QL, "rows", lambda path=None: rows)):
            got = QL.rescore_targets(1)
        check("前に届かなかった記事が先", got, ["zz-pub"])


def test_client_slugs_are_masked_and_rows_go_private():
    import quality_loop as QL
    import client_private as CP
    import sites as S
    print("\n■ お客様の記事の名前はログに出さず、台帳の行は非公開の置き場へ")
    with tempfile.TemporaryDirectory() as d:
        e = Env(d, site="client-zz")
        e.put("zz-client-secret", _art())
        with patched(*e.patches(QL, [_answer(60, 85, 80)]), (S, "is_client", lambda sid: sid == "client-zz")):
            _, out = quiet(QL.run, ["zz-client-secret"], "new", QL.Budget(None))
        check("ログに slug が出ない", "zz-client-secret" in out, False)
        check("伏せた名前で出る", "（お客様の記事）" in out, True)
    check("台帳はお客様の行を非公開の置き場へ分けて書く", "data/quality_loop.jsonl" in CP.SPLIT_JSONL, True)


def test_report_flags_low_share_and_stale():
    import quality_loop as QL
    print("\n■ 週次の知らせ: 2回以内で届く割合が9割を割る・3日を超えて改善中のまま")
    today = date(2026, 10, 20)
    rows = [{"at": "2026-10-10 10:00", "slug": "a", "mode": "new", "action": "score"},
            {"at": "2026-10-10 10:10", "slug": "a", "mode": "new", "action": "pass", "rounds": 1},
            {"at": "2026-10-11 10:00", "slug": "b", "mode": "new", "action": "score"},
            {"at": "2026-10-11 10:30", "slug": "b", "mode": "new", "action": "hold", "rounds": 2}]
    with tempfile.TemporaryDirectory() as d:
        e = Env(d)
        e.put("b", _art("quality_state: improving\nquality_since: 2026-10-11\n"))
        log = Path(d) / "q.jsonl"
        log.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        with patched((QL, "ARTICLES", e.root / "articles"), (QL, "site_of", lambda s: "ai-lab")):
            _, out = quiet(QL.report, today, log)
        check("割合と改善中の日数で要対応", ("1/2本" in out, "9日 改善中" in out, "QUALITY_LOOP_OK=no" in out), (True, True, True))
        log.write_text("", encoding="utf-8")
        (e.root / "articles" / "b.md").unlink()
        with patched((QL, "ARTICLES", e.root / "articles")):
            _, out2 = quiet(QL.report, today, log)
        check("対象が無ければ判定しない（問題なしと言わない）", "QUALITY_LOOP_OK=unknown" in out2, True)
    f = (ROOT / "scripts" / "findings.py").read_text(encoding="utf-8")
    check("週次の findings が読む", '"quality_loop.py --report"' in f, True)


def test_scorer_is_read_only():
    import quality_loop as QL
    print("\n■ 採点の AI は読むだけ（書く道具・コマンド・外への通信を名指しで拒む）")
    s = json.loads(QL.scorer_settings())["permissions"]
    check("読むだけ・断る形", (s["allow"], s["defaultMode"]), (["Read"], "dontAsk"))
    check("書く道具・コマンド・外への通信を拒む", all(x in s["deny"] for x in ("Edit", "Write", "Bash", "WebFetch", "WebSearch")),
          True)
    check("鍵のファイルの Read も拒む", "Read(.env)" in s["deny"], True)
    src = (ROOT / "scripts" / "quality_loop.py").read_text(encoding="utf-8")
    check("引数は Read だけを許す", '"--allowedTools", "Read"' in src, True)
    check("一時フォルダの写しを読ませる", "TemporaryDirectory(prefix=\"quality_score_\"" in src, True)
