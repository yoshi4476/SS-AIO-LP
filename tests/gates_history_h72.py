# -*- coding: utf-8 -*-
"""2026-10-09 運用者の決定「補助金サイト（subsidy）は新しい記事を1日1本に減らし、浮いた1枠で主力（AI導入補助金）の
既存記事を書き直して上位へ押し上げる」から。

背景: 補助金の主力の語は書き終えて、新しく積めた主力の語は4本だけ（2026-10-09 のラッコの調べ・122クレジット）。
台帳の未着手は108本中104本が周辺の制度の語で、1日2本のままだと周辺の記事ばかり増え、主力の割合が下がる。

固定すること（本物の claude・ラッコ・配信は呼ばない）:
- 社ごとの1日の本数の上限（sites/<id>.json の daily_articles）が、日次の枠（pace.quota）・救済と本数の点検
  （daily_audit）・結果の見張り（outcome_watch）・在庫の1か月分（kw_plan.month_need）に効く。1本の日に「1/2本」と言わない
- 運用者の設定は量産の兆候と分ける（pace の一覧・週次の findings で「要対応」にしない）
- spare_slot=rewrite_main の社は、設定で浮いた枠だけ書き直しに回す。量産の兆候・手動の対策・月の上限で止めた枠は書き直さない
- 書き直しは主力の語の記事だけ（--main-only）。順は「4〜20位で上位の見出しがある」→「11〜30位」→「競合との差」。
  候補が無い日は何もしない（新しい記事にも戻さない）
- 浮いた枠の書き直しも、既存の検算・台帳・28日後の効果判定（effect_ab・rewrite_rollback）を通る
"""
import contextlib
import io
import json
import re
import subprocess
import sys
import tempfile
import types
from datetime import date
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


def _quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


@contextlib.contextmanager
def fake_pace(sites, state=None, manual=None):
    """pace の読む3つ（sites/<id>.json・兆候の記録・手動の対策）を一時の場所へ差し替える"""
    import pace
    today = date.today().isoformat()
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "sites").mkdir()
        for sid, cfg in sites.items():
            (base / "sites" / f"{sid}.json").write_text(json.dumps(dict(cfg, id=sid), ensure_ascii=False), encoding="utf-8")
        st = {sid: {"quota": q, "date": today, "signals": []} for sid, q in (state or {}).items()}
        (base / "state.json").write_text(json.dumps(st), encoding="utf-8")
        (base / "manual.json").write_text(json.dumps(manual or {}), encoding="utf-8")
        with patched(pace, SITES=base / "sites", STATE=base / "state.json", MANUAL=base / "manual.json"):
            yield pace


SITES = {"x": {"daily_articles": 1, "spare_slot": "rewrite_main"},     # 補助金と同じ設定
         "y": {},                                                       # 設定なし（既定の2本）
         "z": {"daily_articles": 0, "spare_slot": "rewrite_main"},     # 新しい記事を止め、2枠とも書き直し
         "w": {"daily_articles": 1},                                    # 1日1本だが書き直しはしない（CONFLUX と同じ）
         "bad": {"daily_articles": 7}}                                  # 範囲外は0〜2に収める


def test_daily_articles_caps_the_days_quota():
    import pace
    check("pace: 運用者の1日の本数（sites/<id>.json の daily_articles）を読む関数がある",
          callable(getattr(pace, "setting", None)) and callable(getattr(pace, "slot", None)), True)
    if not callable(getattr(pace, "setting", None)):
        return
    with fake_pace(SITES, state={"x": 2, "y": 2, "z": 2, "w": 2, "bad": 2}):
        check("日次の枠の本数: 設定1本の社は1本・設定なしは2本・0本の社は0本・範囲外は2本まで",
              [pace.quota(s) for s in ("x", "y", "z", "w", "bad")], [1, 2, 0, 1, 2])
    with fake_pace(SITES, state={"x": 1, "y": 1}):
        check("量産の兆候で1本に落ちた週は、設定と兆候の小さい方", [pace.quota("x"), pace.quota("y")], [1, 1])
    with fake_pace(SITES, state={"x": 2}, manual={"x": {"quota": 0, "reason": "手動による対策"}}):
        check("手動による対策（0本）は設定より優先して0本", pace.quota("x"), 0)
    cfg = json.loads((ROOT / "sites" / "subsidy.json").read_text(encoding="utf-8"))
    check("補助金: 1日1本・浮いた枠は主力の書き直し（理由の注記つき）",
          (cfg.get("daily_articles"), cfg.get("spare_slot"), "2026-10-09" in str(cfg.get("_daily_articles_note", ""))),
          (1, "rewrite_main", True))
    # CI の select は pip の前に呼ぶ。標準ライブラリだけで動くこと（site-packages を読まない -S で確かめる）
    r = subprocess.run([sys.executable, "-S", "scripts/pace.py", "--quota", "subsidy"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    check("pace.py --quota は標準ライブラリだけで動き、補助金は1本以下", (r.returncode, r.stdout.strip() in ("0", "1")), (0, True))
    r = subprocess.run([sys.executable, "-S", "scripts/pace.py", "--slot", "subsidy", "1"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    check("pace.py --slot も標準ライブラリだけで動き、補助金の2本目は新しい記事にしない",
          (r.returncode, bool(re.search(r"^SLOT=(rewrite|skip)$", r.stdout, re.M))), (0, True))


def test_daily_audit_and_month_need_count_by_setting():
    import daily_audit as D
    import kw_plan as KP
    import outcome_watch as OW
    import site_order
    import sites as S
    today = date.today().isoformat()
    arts = {"x": [{"slug": "a1", "date": today, "score": "95", "title": "a1", "category": "c", "makeup_for": ""}]}
    with fake_pace(SITES, state={"x": 2}):
        check("在庫の1か月分（kw_plan.month_need）: 1日1本の社は30本", KP.month_need("x"), 30)
        with patched(site_order, order=lambda: ["a", "b", "x", "c"]):
            check("救済が待つ枠の時刻: 1日1本の社は新しい記事の枠（その日の1本目・12:07）だけ", D.publish_hours("x"), (12,))
        todo = []
        with patched(D, articles_by_site=lambda: arts, today_iso=lambda: today, _due_now=lambda sid, hour=None: 2):
            _, out = _quiet(D.check_volume, todo)
        check("本数の点検: 1本書いた日は「1/1本」で、不足（救済の TODO）にしない",
              ("本日 1/1本" in out, "1/2本" in out, todo), (True, False, []))
        check("結果の見張り: 書くはずの本数は1本", OW.expected_articles("x", arts["x"], date.today()), 1)
        bad = []
        fake = types.SimpleNamespace(status=200)
        with patched(D, articles_by_site=lambda: arts), patched(S, load_all=lambda: {"x": {"name": "X"}},
                                                                article_url=lambda cfg, meta: "https://x.example/a1/"), \
                patched(OW.urllib.request, urlopen=lambda *a, **k: fake):
            _, out = _quiet(OW.check_articles, date.today(), bad)
        check("結果の見張り: 1本の日に「1/2本でした」と知らせない", ("1/1本" in out, bad), (True, []))


def test_operator_setting_is_not_reported_as_a_signal():
    import pace
    rl = getattr(pace, "report_line", None)
    check("pace: 一覧の1行と「要対応」かを返す関数がある（report_line）", callable(rl), True)
    if not callable(rl):
        return
    calm = {"quota": 2, "signals": [], "new": 10, "how": "URL検査", "not_indexed_rate": 0.0, "duplicates": 0,
            "pairs": 0, "imp": [100, 120]}
    with fake_pace(SITES):
        line, flagged = rl("x", "補助金", calm)
        check("運用者の設定で1本の社: 「要対応」にせず「1日1本（運用者の設定）」と出す",
              (line.lstrip().startswith("要対応"), "1日1本（運用者の設定）" in line, flagged), (False, True, False))
        line2, flagged2 = rl("y", "Y", dict(calm, quota=1, signals=["サイト全体の表示が急落"]))
        check("量産の兆候で落とした社は今までどおり「要対応」", (line2.lstrip().startswith("要対応"), flagged2), (True, True))
    src = (ROOT / "scripts" / "findings.py").read_text(encoding="utf-8")
    check("週次の findings は pace の「要対応:」「兆候:」の行だけを拾う（設定の行は拾われない）",
          'pace.py' in src and "要対応:|兆候:" in src, True)
    manual = json.loads((ROOT / "data" / "pace_manual.json").read_text(encoding="utf-8"))
    conflux = json.loads((ROOT / "sites" / "conflux.json").read_text(encoding="utf-8"))
    check("CONFLUX の毎日1本（オーナーの指示）は手動による対策ではなく運用者の設定で持つ",
          ("conflux" in manual, conflux.get("daily_articles")), (False, 1))


def test_spare_slot_goes_to_rewrite_only_when_the_setting_frees_it():
    import pace
    if not callable(getattr(pace, "slot", None)):
        check("pace.slot がある", False, True)
        return
    with fake_pace(SITES, state={"x": 2, "y": 2, "z": 2, "w": 2}):
        check("設定で浮いた枠: 1本目は新しい記事・2本目は書き直し",
              [pace.slot("x", 0)[0], pace.slot("x", 1)[0]], ["write", "rewrite"])
        check("0本の社は2枠とも書き直し・設定なしは2枠とも新しい記事・書き直しを指定しない社は書かない",
              [pace.slot("z", 0)[0], pace.slot("z", 1)[0], pace.slot("y", 1)[0], pace.slot("w", 1)[0]],
              ["rewrite", "rewrite", "write", "skip"])
        argv = sys.argv
        try:
            sys.argv = ["pace.py", "--slot", "x", "1"]
            _, out = _quiet(pace.main)
        finally:
            sys.argv = argv
        check("pace.py --slot は SLOT= と理由を出す（select が読む）",
              ("SLOT=rewrite" in out, "SLOT_WHY=" in out), (True, True))
    with fake_pace(SITES, state={"x": 1}):
        check("量産の兆候で1本に落ちた週: 2本目は書き直しにも回さない", pace.slot("x", 1)[0], "skip")
    with fake_pace(SITES, state={"x": 2}, manual={"x": {"quota": 0, "reason": "手動による対策"}}):
        check("手動による対策: どの枠も書き直さない", [pace.slot("x", 0)[0], pace.slot("x", 1)[0]], ["skip", "skip"])

    import yaml
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8"))
    sel = wf["jobs"]["select"]
    run = next(str(s.get("run", "")) for s in sel["steps"] if "対象サイトの判定" in str(s.get("name")))
    i_cap, i_slot = run.find("--cap-reached"), run.find("pace.py --slot")
    check("select: 月の上限で止めた枠は書き直しに回さない（上限の判定が先・書き直しは pace.py --slot が決める）",
          (i_cap >= 0, i_slot > i_cap, "mode=" in run), (True, True, True))
    check("select: 書き直しの枠かを write へ渡す（outputs.mode）", "mode" in (sel.get("outputs") or {}), True)
    steps = wf["jobs"]["write"]["steps"]
    gen = next((s for s in steps if "claude -p" in str(s.get("run", ""))), {})
    check("write: 書き直しの枠では新しい記事を書かない（記事生成の工程を通らない）",
          "mode != 'rewrite'" in str(gen.get("if", "")), True)
    for name in ("食い合いゲート（執筆前）", "一次情報の収集", "食い合いゲート（執筆後）"):
        s = next((s for s in steps if name in str(s.get("name"))), {})
        check(f"write: 書き直しの枠では「{name}」を通らない", "mode != 'rewrite'" in str(s.get("if", "")), True)
    rw = [s for s in steps if "mode == 'rewrite'" in str(s.get("if", ""))]
    body = "\n".join(str(s.get("run", "")) for s in rw)
    check("write: 書き直しの枠は検算の自己診断を先に通す", "auto_rewrite.py --selftest" in body, True)
    m = re.search(r"auto_rewrite\.py --write(?:[^\n]*\\\n)*[^\n]*", body)
    cmd = m.group(0) if m else ""
    check("write: 書き直しは主力の記事を1本だけ・直近に直した記事を外し・印 spare-slot を付ける",
          all(x in cmd for x in ("--kind spare", "--main-only", "--limit 1", "--skip-recent", "--tag spare-slot", "--sites")),
          True)
    check("write: 書き直した記事を週次と同じ道具（publish_changed）で配信先へ届ける",
          "publish_changed.py --site" in body and "--push" in body, True)
    others = [p.name for p in (ROOT / ".github" / "workflows").glob("*.yml")
              if p.name != "pipeline-multi.yml" and "spare-slot" in p.read_text(encoding="utf-8")]
    check("浮いた枠のために新しい workflow を作らない（記事の枠のジョブを使う）", others, [])


def _write_art(base, slug, kw, title, cat="hojokin"):
    (base / "articles").mkdir(exist_ok=True)
    (base / "articles" / f"{slug}.md").write_text(
        f"---\ntitle: {title}\nkeyword: {kw}\ncategory: {cat}\nscore: 95\ndate: 2026-08-01\n---\n\n本文。\n",
        encoding="utf-8")


def test_main_only_keeps_main_articles():
    import auto_rewrite as AR
    check("auto_rewrite: 主力の語の記事だけに絞る関数がある（--main-only）", callable(getattr(AR, "only_main", None)), True)
    if not callable(getattr(AR, "only_main", None)):
        return
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        _write_art(base, "a", "AI導入補助金 申請 方法", "AI導入補助金の申請方法")
        _write_art(base, "b", "ものづくり補助金 運送業", "ものづくり補助金は運送業も使える？AI導入補助金との違い")
        _write_art(base, "c", "it導入補助金 おすすめ", "IT導入補助金のおすすめの選び方")
        with patched(AR, ROOT=base):
            items = [{"kind": "stuck", "slug": s, "site": "subsidy", "why": ""} for s in ("a", "b", "c")]
            got = [x["slug"] for x in AR.only_main(items)]
    check("--main-only: 補助金は主力（AI導入補助金）の語の記事だけ（題に名前が出るだけの周辺の記事は入れない）", got, ["a"])


def test_spare_candidates_order_and_empty_day():
    import auto_rewrite as AR
    import kw_plan as KP
    import kw_serp
    import rank_rescue
    if not callable(getattr(AR, "spare_items", None)):
        check("auto_rewrite.spare_items がある", False, True)
        return
    arts = {"p": "AI導入補助金 対象", "q": "AI導入補助金 締切", "u": "AI導入補助金 費用", "v": "AI導入補助金 期間",
            "w": "AI導入補助金 種類"}
    head = {"at": date.today().isoformat(), "headline": {"pages": [{"pos": 1, "ours": False, "heads": [["h2", "対象になるツール"]]}]}}
    serp = {kw: dict(head, kw=kw) for kw in arts.values() if kw != "AI導入補助金 締切"}     # q だけ調べが無い
    # ページ単位の順位: p は 6位・表示40（入る）、v は 25位（帯の外）、w は表示8回（偶然と区別できない）、u は 4.0位・表示90（入る・先頭）
    pages = {"p": (6.0, 40), "q": (12.0, 30), "u": (4.0, 90), "v": (25.0, 50), "w": (9.0, 8)}
    stuck = [{"kind": "stuck", "slug": "r", "site": "subsidy", "terms": ["締切"], "why": "15.0位"},
             {"kind": "stuck", "slug": "p", "site": "subsidy", "terms": ["対象"], "why": "18.0位"}]
    comp = [{"kind": "compete", "slug": "s", "site": "subsidy", "imp": 9, "gap": {}, "why": "競合"}]
    with patched(KP, site_articles=lambda sid: arts if sid == "subsidy" else {}), \
            patched(kw_serp, get=lambda sid, kw, stale_days=60: serp.get(kw) if sid == "subsidy" else None), \
            patched(AR, page_positions=lambda sid: pages), \
            patched(rank_rescue, items=lambda limit=0: stuck), patched(AR, compete_items=lambda limit=2, log=None: comp):
        got = [(x["kind"], x["slug"]) for x in AR.spare_items()]
    check("浮いた枠の順: 4〜20位（ページ単位）で上位の見出しがある記事 → 11〜30位 → 競合との差（同じ記事は1回）",
          got, [("serp", "u"), ("serp", "p"), ("stuck", "r"), ("compete", "s")])
    src = __import__("inspect").getsource(AR.page_positions)
    check("4〜20位はページ単位の GSC（rank_up.fetch・page 次元）で数える（query×page の data/ranks は語の少ないページが欠ける）",
          "rank_up.fetch(" in src, True)

    calls = []
    with tempfile.TemporaryDirectory() as td:
        log = Path(td) / "auto_fix.jsonl"
        argv = sys.argv
        try:
            sys.argv = ["auto_rewrite.py", "--write", "--kind", "spare", "--main-only", "--sites", "subsidy",
                        "--limit", "1", "--skip-recent", "28", "--tag", "spare-slot"]
            with patched(AR, LOG=log, spare_items=lambda: [], run_one=lambda *a, **k: calls.append(a) or (True, "")):
                rc, out = _quiet(AR.main)
            check("候補が無い日: 何もしない（書き直しも新しい記事もしない）・実行ログに残す",
                  (rc, calls, "SPARE_SLOT=none" in out, log.exists()), (0, [], True, False))
            cands = [{"kind": "serp", "slug": "p", "site": "subsidy", "why": "6.0位"},
                     {"kind": "stuck", "slug": "r", "site": "subsidy", "why": "15.0位"}]
            log.write_text(json.dumps({"at": date.today().isoformat() + " 09:00", "by": "auto_rewrite", "slug": "p",
                                       "kind": "stuck", "ok": True, "note": "直しました（…）"}, ensure_ascii=False) + "\n",
                           encoding="utf-8")
            with patched(AR, LOG=log, spare_items=lambda: cands, only_main=lambda items: items,
                         run_one=lambda x, w, edited=None: calls.append(x["slug"]) or (True, "直しました（a… → b…）"),
                         hub_rewrite_log=lambda *a, **k: None):
                rc, out = _quiet(AR.main)
            last = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
            check("候補がある日: 直近に直した記事を外して1本だけ・台帳に印 spare-slot",
                  (calls, last.get("slug"), last.get("tag"), "SPARE_SLOT=rewrote" in out), (["r"], "r", "spare-slot", True))
        finally:
            sys.argv = argv
            AR.TAG = ""


def test_spare_rewrites_are_guarded_judged_and_rolled_back():
    import auto_rewrite as AR
    import effect_ab as EA
    import rewrite_rollback as RB
    check("auto_rewrite: 上位の見出しとの差を埋める直し（serp）の指示と検算がある",
          ("serp" in AR.WHAT, callable(getattr(AR, "serp_guard", None))), (True, True))
    if not callable(getattr(AR, "serp_guard", None)):
        return
    before = "---\ntitle: AI導入補助金の対象ツール\n---\n## 対象になる経費\n本文。\n"
    heads = ["対象にならないツールの見分け方とその理由"]
    good = before + "## 対象外になりやすいソフトは？\n申請の前に確かめます。\n"
    check("serp: 節を1つ足すだけの直しは通す", AR.serp_guard(before, good, "AI導入補助金の対象ツール", "AI導入補助金の対象ツール", heads), "")
    bad = [("題を変える", before, good, "別の題"),
           ("上位の見出しを写す", before, before + "## 対象にならないツールの見分け方とその理由\n本文。\n", None),
           ("本文を削る", before + "長い本文。" * 50, before + "## 足した節\n本文。\n", None),
           ("節を足さない", before, before.replace("本文。", "本文を言い換えた。"), None)]
    got = [n for n, b, a, t in bad if not AR.serp_guard(b, a, "AI導入補助金の対象ツール", t or "AI導入補助金の対象ツール", heads)]
    check("serp: 題の変更・上位の見出しの写し・本文の削り・節を足さない直しは止める", got, [])
    saved = AR.TAG
    try:
        AR.TAG = "spare-slot"
        k1 = [AR.keep_original(k) for k in ("serp", "stuck", "compete")]
        AR.TAG = ""
        k2 = [AR.keep_original(k) for k in ("serp", "stuck", "title")]
    finally:
        AR.TAG = saved
    check("浮いた枠の直しは直す前の原稿を残す（28日後に効かなければ戻せる）", (k1, k2), ([True] * 3, [True, False, False]))

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        log = base / "auto_fix.jsonl"
        rows = [{"at": "2026-09-01 09:00", "by": "auto_rewrite", "slug": "p", "kind": "serp", "ok": True,
                 "note": "直しました（…）", "before_path": "data/rewrite_before/p@2026-09-01.md", "after_sha": "x",
                 "tag": "spare-slot"},
                {"at": "2026-09-02 09:00", "by": "auto_rewrite", "slug": "r", "kind": "stuck", "ok": True,
                 "note": "直しました（…）", "before_path": "data/rewrite_before/r@2026-09-02.md", "after_sha": "x",
                 "tag": "spare-slot"},
                {"at": "2026-09-03 09:00", "by": "auto_rewrite", "slug": "t", "kind": "stuck", "ok": True,
                 "note": "直しました（…）"}]
        log.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        with patched(RB, LOG=log):
            got = [d["slug"] for d in RB.entries()]
        kinds = [x["kind"] for x in EA.rewrites(log)]
        restored = []
        with patched(RB, restore_file=lambda slug, d: restored.append(slug) or True,
                     restore_early=lambda slug, d: False):
            RB.restore("p", rows[0])
            RB.restore("r", rows[1])
    check("28日後の判定（rewrite_rollback）: 浮いた枠の直しは原稿ごと戻せる（週次の stuck は今までどおり対象外）",
          (got, restored), (["p", "r"], ["p", "r"]))
    check("効きの判定（effect_ab --rewrites）: 浮いた枠の直しは週次の直しと分けて数える",
          (kinds[0] != "serp" and kinds[0].startswith("serp"), kinds[1] != "stuck", kinds[2]), (True, True, "stuck"))
