# -*- coding: utf-8 -*-
"""品質の直しが85点に届かずに止まる原因を潰す（2026-11-18 運用者「85点以上なぜならないかすべて考えて毎回止まらないように精度を上げること」）。

台帳（2026-10-20〜11-18）の実数:
- 公開済みの記事の採点し直しは99件中69件が保留。保留103件のうち27件は直しを1回もせず採点だけで終わった
  （直し1回の見込み14分に対し、実測は9割が2分以内。週次では後の社が「時間が足りない」で採点だけになった）
- 直し346回のうち92回が検算で戻された。31回は「FAQ の答えの数字に本文と同じ条件」の警告、18回は週次の
  「作業場所の外が変わった」（直前の当社調べが15分で時間切れになった3回の週次だけで起きた）。戻された直しも2回の枠を使った
- 2回とも直せたのに80〜84点で止まった保留が35件（運用者の承認で、点が上がり続けているときだけ3回目）
本物の claude は呼ばない。
"""
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))


@contextlib.contextmanager
def patched(*items):
    old = [(o, n, getattr(o, n)) for o, n, _ in items]
    try:
        for o, n, v in items:
            setattr(o, n, v)
        yield
    finally:
        for o, n, v in old:
            setattr(o, n, v)


def quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


def _sc(o, e, d):
    """採点の結果（quality_loop.score の返り値と同じ形）"""
    import rubric as R
    axes = {"originality": o, "extractability": e, "decision": d}
    j = R.judge(axes)
    return {"axes": axes, "quotes": {k: "根拠の文" for k in axes}, "weak": {k: ["弱い点"] for k in axes},
            "total": j["total"], "ok": j["ok"], "why": j["why"], "calls": 1, "double": False}


def _run(scores, improve, mode="rescore", budget=None):
    """一時フォルダの記事1本で process を通す。scores は採点の順（最後の1つは繰り返す）、improve は (slug, sc) → (ok, why)"""
    import gates_history_h128_quality_loop as H
    import quality_loop as QL
    seq = list(scores)
    got = {"improve": 0, "score": 0, "notes": []}

    def score(slug, ask=None):
        got["score"] += 1
        return (seq.pop(0) if len(seq) > 1 else seq[0]), ""

    def imp(slug, sc):
        got["improve"] += 1
        got["notes"].append(sc.get("retry_note", ""))
        return improve(got["improve"])
    with tempfile.TemporaryDirectory() as d:
        e = H.Env(d)
        e.put("zz-aio", H._art("score: 92\n"))
        with patched(*e.patches(QL, ["{}"], improve=imp), (QL, "score", score)):
            res, out = quiet(QL.run, ["zz-aio"], mode, budget or QL.Budget(None))
        rows = [json.loads(x) for x in e.log.read_text(encoding="utf-8").splitlines()] if e.log.exists() else []
    return res, out, got, rows


OK = lambda n: (True, "直しました（テスト）")


def test_rejected_fixes_do_not_use_up_the_two_rounds():
    import quality_loop as QL
    print("\n■ 検算で戻された直し（記事は変わっていない）は2回の枠に数えず、戻された理由を渡してもう一度直させる")
    warn = "警告が増えました（1 → 2）: WARN | ［警告］FAQ の答えの数字に、本文と同じ条件（母数・期間・含むもの）を書く"
    seq = {1: (False, warn)}
    res, out, got, rows = _run([_sc(80, 75, 70)], lambda n: seq.get(n, OK(n)))
    check("1回戻されても、当たった直しが2回になるまで直す（呼んだのは3回）", got["improve"], 3)
    check("戻された理由を次の直しに渡す", warn[:20] in got["notes"][1], True)
    res, out, got, rows = _run([_sc(80, 75, 70)], lambda n: (False, warn))
    check("戻され続けても、直しを呼ぶのは 2回＋もう一度の枠まで", (got["improve"], QL.RETRY_EXTRA), (QL.ROUNDS + QL.RETRY_EXTRA, 2))
    res, out, got, rows = _run([_sc(80, 75, 70)], lambda n: (False, "変更なし（直す必要なしと判断）"))
    check("AI が直す所なしと判断した回は1回と数える（同じ直しを繰り返させない）", got["improve"], 2)
    res, out, got, rows = _run([_sc(80, 75, 70)], lambda n: (False, "claude が動きませんでした（上限）"))
    check("claude が動かない回は、その場で直しをやめて要対応（上がらないとは書かない）",
          (got["improve"], "要対応: 公開済みの zz-aio を直せませんでした" in out, "上がりません" in out), (1, True, False))
    res, out, got, rows = _run([_sc(80, 75, 70)], lambda n: (False, "途中で止まりました（TimeoutExpired）。直す前の中身へ戻しました"))
    check("時間切れで止まった回も、その場で直しをやめる（30分の上限を続けて使わない）", got["improve"], 1)
    res, out, got, rows = _run([_sc(80, 75, 70)], lambda n: (False, "ビルドが通りません（BLOCKED(公開不可): ほかの記事）"))
    check("やり直しても同じ理由（ほかの記事のビルドの止まりなど）は1回と数える", got["improve"], 2)
    res, out, got, rows = _run([_sc(80, 75, 70)], lambda n: seq.get(n, OK(n)))
    imp = [r["round"] for r in rows if r.get("action") == "improve"]
    hold = [r for r in rows if r.get("action") == "hold"]
    check("台帳の直しの番号は呼んだ順（戻された回も1つ）・保留の回数は呼んだ回数",
          (imp, hold[-1]["rounds"] if hold else None), ([1, 2, 3], 3))


def test_third_round_only_while_rising_in_the_80s():
    print("\n■ 2回直して80〜84点で、2回目でも点が上がっていれば3回目を直す（2026-11-18 運用者の承認）")
    res, out, got, rows = _run([_sc(80, 65, 65), _sc(80, 80, 80), _sc(82, 82, 82), _sc(90, 90, 90)], OK)
    check("70→80→82（上がり続けて80〜84）→ 3回目で90", (res, got["improve"]), ({"passed": 1}, 3))
    res, out, got, rows = _run([_sc(80, 65, 65), _sc(82, 82, 82), _sc(80, 80, 80)], OK)
    check("2回目で下がった（82→80。前の版に戻す）なら3回目はしない", (res, got["improve"]), ({"improving": 1}, 2))
    res, out, got, rows = _run([_sc(80, 65, 65), _sc(80, 72, 73), _sc(80, 77, 77)], OK)
    check("上がっていても80点未満（78）なら3回目はしない", (res, got["improve"]), ({"improving": 1}, 2))
    res, out, got, rows = _run([_sc(80, 65, 65), _sc(80, 80, 80), _sc(82, 82, 82), _sc(83, 83, 83)], OK)
    check("3回で止める（4回目はしない）", got["improve"], 3)
    warn = (False, "警告が増えました（1 → 2）")
    res, out, got, rows = _run([_sc(80, 65, 65), _sc(80, 80, 80), _sc(82, 82, 82), _sc(83, 83, 83)],
                               lambda n: warn if n >= 3 else OK(n))
    check("3回目が戻され続けても、呼ぶのは 3回＋もう一度の枠まで（5回）", got["improve"], 5)


def test_published_article_is_not_scored_without_time_to_fix_it():
    import quality_loop as QL
    print("\n■ 公開済みの記事は、直す時間（採点＋直し1回）が無ければ採点も始めない（採点だけで要対応を出さない）")
    left = QL.SCORE_MIN + QL.IMPROVE_MIN - 0.5
    res, out, got, rows = _run([_sc(70, 70, 70)], OK, budget=QL.Budget(left))
    check("採点しない・要対応を出さない", (res, got["score"], "要対応" in out), ({"skipped": 1}, 0, False))
    res, out, got, rows = _run([_sc(70, 70, 70)], OK, budget=QL.Budget(QL.SCORE_MIN + QL.IMPROVE_MIN + 1))
    check("時間があれば採点して直す", (got["score"] >= 1, got["improve"] >= 1), (True, True))
    # 実測は直しが9割2分以内・最大6分、採点し直しが約2分。14分では後の社が採点だけになり、6分では手順の時間切れの余裕を食う
    check("直し1回の見込みは実測の最大（直し6分＋採点し直し2分）", QL.IMPROVE_MIN, 8)


def test_published_article_that_rose_is_reported_as_progress():
    print("\n■ 公開済みの記事で、この回に点が上がったものは要対応にせず経過として出す。上がらなかったときだけ要対応")
    res, out, got, rows = _run([_sc(80, 65, 65), _sc(80, 80, 80), _sc(82, 82, 82)], OK)
    check("70→82 は経過（要対応にしない・点の流れを出す）", ("要対応" in out, "70→82" in out), (False, True))
    res, out, got, rows = _run([_sc(80, 80, 80)], OK)
    check("80→80（上がらない）は要対応", "要対応: 公開済みの" in out, True)
    class Once:
        """採点の前の確かめだけ時間がある（採点が長引き、採点の後には直し1回の時間が残らない回）"""
        n = 0

        def ok(self, need):
            self.n += 1
            return self.n == 1
    res, out, got, rows = _run([_sc(80, 80, 80)], OK, budget=Once())
    check("採点の後に直す時間が残らなかった回は、要対応にせず次の回に直す",
          (got["improve"], "要対応" in out, "直す時間が残っていなかった" in out), (0, False, True))


def test_outside_dirs_never_show_file_names():
    import auto_rewrite as AR
    print("\n■ 変わった場所の表示は2段のフォルダまで・4つ目からは数だけ")
    got = AR.outside_dirs(["data/own_survey/zz-a.json", "data/own_survey/zz-b.json", "data/x.json", "scripts/a.py",
                           "data/cooccur/zz-c.json", ".github/workflows/w.yml"])
    # 5種類（.github/workflows・data・data/cooccur・data/own_survey・scripts）
    check("ファイル名を出さない・4つ目からは数", got, ".github/workflows・data・data/cooccur ほか2")


def test_weekly_rescore_alternates_sites():
    import article_health as AH
    import gates_history_h128_quality_loop as H
    import quality_loop as QL
    import sites as S
    print("\n■ 週次の採点し直しは社を交互に並べる（1つ目の社が時間を使い切り、後の社が採点だけで終わっていた）")
    site = {"za1": "ai-lab", "za2": "ai-lab", "zc1": "corporate", "zc2": "corporate"}
    with tempfile.TemporaryDirectory() as d:
        e = H.Env(d)
        for s in site:
            e.put(s, H._art("score: 92\n").replace("slug: zz-aio", f"slug: {s}"))
        with patched(*e.patches(QL, ["{}"]), (QL, "site_of", lambda s: site[s]), (QL, "rows", lambda path=None: []),
                     (QL, "_audit_scores", lambda: {}), (QL, "_well_read", lambda sid: set()),
                     (QL, "control", lambda s, month=None: False), (QL, "_low_scope", lambda sid: False),
                     (AH, "of", lambda s, sid=None, m=None: "weak"), (AH, "protected", lambda s, kind=None, site=None: False),
                     (S, "load", lambda sid: {})):
            got = QL.rescore_targets(2)
    check("社を交互に", got, ["za1", "zc1", "za2", "zc2"])


def test_own_survey_stops_inside_its_time():
    import own_survey as OS
    import quality_loop as QL
    print("\n■ 当社調べは時間内に自分で止まる（週次で15分の時間切れの後も裏で書き続け、直しの見張りが直しを全部戻した）")
    ran = []
    with patched((OS, "run", lambda slug, force=False: ran.append(slug) or {}), (QL, "site_of", lambda s: "ai-lab"),
                 (QL, "shown", lambda s: s), (sys, "argv", ["own_survey.py", "--budget-min", "0", "za", "zb"])):
        rc, out = quiet(OS.main)
    check("時間が無ければ始めない・残りの本数を出す（「0」を記事の名前と取り違えない）",
          (rc, ran, "OWN_SURVEY_STOPPED=2" in out), (0, [], True))
    ran.clear()
    with patched((OS, "run", lambda slug, force=False: ran.append(slug) or {}), (QL, "site_of", lambda s: "ai-lab"),
                 (QL, "shown", lambda s: s), (sys, "argv", ["own_survey.py", "--budget-min", "30", "za", "zb"])):
        rc, out = quiet(OS.main)
    check("時間があれば全部", ran, ["za", "zb"])
    act = (ROOT / ".github" / "actions" / "own-survey" / "action.yml").read_text(encoding="utf-8")
    check("部品は調べを timeout で包む（手順の時間切れの後に裏で残さない）", 'timeout -k 15 "$((MINUTES * 60))" python -u' in act, True)
    wk = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    blk = wk.split("- name: 当社調べ（採点し直す公開済みの記事", 1)[1].split("\n      - ", 1)[0]
    check("週次の当社調べは手順の時間（15分）の内に止まる", ("timeout-minutes: 15" in blk, "minutes: 11" in blk), (True, True))
    q = wk.split("- name: 公開済みの記事を公開前と同じ基準で採点し直す", 1)[1].split("\n      - ", 1)[0]
    check("採点し直しの前に、残っている当社調べを止める", 0 < q.find("pkill -f scripts/own_survey.py") < q.find("quality_loop.py"), True)


def test_every_survey_step_stops_before_its_step_timeout():
    import re
    print("\n■ 当社調べの部品を使う手順は、どれも調べの上限（minutes。既定11）が手順の時間より4分以上短い"
          "（前後の Codex の準備とログイン情報の書き戻しの分）")
    act = (ROOT / ".github" / "actions" / "own-survey" / "action.yml").read_text(encoding="utf-8")
    default = int(re.search(r"\n  minutes:\n(?:    .*\n)*?    default: \"(\d+)\"", act).group(1))
    bad, seen = [], 0
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = wf.read_text(encoding="utf-8")
        for step in re.split(r"\n      - ", text)[1:]:
            if "uses: ./.github/actions/own-survey" not in step:
                continue
            seen += 1
            to = re.search(r"\n        timeout-minutes: (\d+)", step)
            mins = re.search(r"\n          minutes: (\d+)", step)
            m = int(mins.group(1)) if mins else default
            if not to or m < 1 or m > int(to.group(1)) - 4:
                bad.append(f"{wf.name}: {step.splitlines()[0][:30]}（上限{m}分・手順{to.group(1) if to else 'なし'}分）")
    check("当社調べの手順が見つかる", seen >= 5, True)
    check("どの手順も、時間切れの前に調べが止まる", bad, [])


def test_guard_names_the_folder_that_changed():
    import auto_rewrite as AR
    print("\n■ 直しの見張りが「外が変わった」で戻すとき、変わったフォルダを出す（ファイル名・記事の名前は出さない）")
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        for x in ("articles", "scripts", "data", ".github"):
            (root / x).mkdir()

        def fn():
            (root / "data" / "own_survey").mkdir()
            (root / "data" / "own_survey" / "zz-secret-slug.json").write_text("{}", encoding="utf-8")
        with patched((AR, "ROOT", root)):
            try:
                AR.guarded(fn)
                msg = ""
            except AR.Escaped as e:
                msg = str(e)
        check("フォルダを出し、ファイル名は出さない", ("data/own_survey" in msg, "zz-secret" in msg), (True, False))
        check("変わったファイルは戻してある", (root / "data" / "own_survey" / "zz-secret-slug.json").exists(), False)


def test_fix_prompts_name_the_faq_number_rule():
    import auto_rewrite as AR
    print("\n■ FAQ の数字の条件（戻された直しの31回）を、直す指示と、戻される前の手直しの指示に入れる")
    rule = "FAQ の答えに本文の数字を書くときは"
    check("共通の決まり", rule in AR.PROMPT, True)
    check("品質の直しの決まり", rule in AR.WHAT["quality_loop"], True)
    src = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    blk = src.split('if ng.startswith("警告が増えました") and kind == "quality_loop":', 1)[1].split("guarded(lambda: draft_one(item, fix))", 1)[0]
    check("戻される前の手直し", "FAQ の答えから数字を外す" in blk, True)
    check("品質の直しに古い合格の基準（平均90点）を書かない", "平均90点以上で合格" in AR.WHAT["quality_loop"], False)
