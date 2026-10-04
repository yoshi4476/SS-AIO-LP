# -*- coding: utf-8 -*-
"""書き直しの効き・計測の食い違い・一次性が上がらない記事の整理・統合案の並列（2026-10-04）。

どれも見本（実データで見た値・作った値）で「見つけるはずのものを見つけ、隣を拾わない」ことを確かめる。
"""
import json
import subprocess
import tempfile
from datetime import date, timedelta
from pathlib import Path

from test_gates import check, ROOT


def _daily(days_imp):
    """{slug: {日付: 表示}} → effect_ab の日次の形（[表示, クリック, 順位×表示]）"""
    out = {}
    for slug, by_day in days_imp.items():
        out[slug] = {d.isoformat(): [n, 1 if n >= 20 else 0, 10.0 * n] for d, n in by_day.items()}
    return out


def test_rewrite_effect_by_kind():
    """書き直しの種類ごとに、前後28日の表示を対照群（書き直していない記事）の中央値で割り引いて判定する"""
    import effect_ab as E
    log = "\n".join(json.dumps(x, ensure_ascii=False) for x in [
        {"at": "2026-09-28 10:00", "by": "auto_rewrite", "slug": "a", "kind": "aio", "ok": True, "note": "直しました（…）"},
        {"at": "2026-09-28 10:00", "by": "auto_rewrite", "slug": "b", "kind": "stuck", "ok": True, "note": "変更なし（直す必要なしと判断）"},
        {"at": "2026-09-28 10:00", "by": "auto_rewrite", "slug": "c", "kind": "aio", "ok": False, "note": "本文に無かった数字"},
        {"at": "2026-09-28 10:00", "by": "link_boost", "slug": "d", "kind": "link", "ok": True, "note": "直しました"},
        {"at": "2026-09-28 10:00", "by": "auto_merge", "slug": "e", "kind": "merge", "ok": True, "note": "統合しました（x → e）"},
    ]) + "\n"
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "auto_fix.jsonl"
        p.write_text(log, encoding="utf-8")
        got = [(x["slug"], x["kind"]) for x in E.rewrites(p)]
    check("書き直しの記録: 実際に書き換えた分だけ（変更なし・戻した分・内部リンクは数えない）",
          got, [("a", "aio"), ("e", "merge")])

    at = date(2026, 8, 1)
    span = [at + timedelta(days=i) for i in range(-28, 29)]
    flat = {d: 10 for d in span}
    grow = {d: (10 if d < at else 20) for d in span}
    data = {f"ctrl{i}": dict(flat) for i in range(6)}
    acts = []
    for i in range(5):
        data[f"up{i}"] = dict(grow)
        acts.append({"slug": f"up{i}", "at": at.isoformat(), "kind": "aio"})
        data[f"same{i}"] = dict(flat)
        acts.append({"slug": f"same{i}", "at": at.isoformat(), "kind": "desc"})
    for i in range(2):
        data[f"few{i}"] = dict(grow)
        acts.append({"slug": f"few{i}", "at": at.isoformat(), "kind": "question"})
    acts.append({"slug": "new", "at": "2026-09-30", "kind": "title"})
    res = E.rewrite_effects(acts, _daily(data), today=date(2026, 10, 4))
    k = res["kinds"]
    check("表示が対照群の2倍に伸びた種類は「効いた」", (k["aio"]["verdict"], k["aio"]["net_imp"]), ("効いた", 2.0))
    check("対照群と同じ動きの種類は「効かない」", k["desc"]["verdict"], "効かない")
    check("5件に満たない種類は「判定前」", k["question"]["verdict"], "判定前")
    check("28日たっていない書き直しは観測中", (k["title"]["verdict"], k["title"]["pending"]), ("判定前", 1))
    # 書き直した記事どうしは対照群に入れない（入れると差が薄まる）
    item = next(x for x in res["items"] if x["slug"] == "up0")
    check("対照群は書き直していない記事だけ", item["ctrl_n"], 6)

    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週次で書き直しの効きを測る", "effect_ab.py --rewrites" in wf, True)


def test_measurement_mismatch_detectors():
    """GSC・GA4・問い合わせ台帳の食い違い。実データ（2026-10-04・28日）の値で、拾うものと拾わないものを確かめる"""
    import data_sanity as D
    # コーポレートの sessionSourceMedium（GA4 のチャネル「Organic Search」161 の内訳）
    rows = [("google / organic", 79), ("bing / organic", 46), ("yahoo / organic", 18),
            ("openai / organic", 16), ("duckduckgo / organic", 2), ("chatgpt.com / ai-assistant", 27),
            ("(direct) / (none)", 95)]
    check("自然検索の内訳: Google / ほかの検索 / 自然検索に入ったAI", D.organic_split(rows), (79, 66, 16))

    srcs = [("chassu.chat-assistant.persol-group.co.jp", 1), ("openai", 17), ("chatgpt.com", 27),
            ("gemini.google.com", 2), ("perplexity.ai", 1), ("google", 79), ("bing", 46), ("yahoo", 18),
            ("duckduckgo", 2), ("note.com", 2), ("cp.onamae.ne.jp", 3), ("chatwork.com", 4),
            ("shinsaibashi-lab-sample.pages.dev", 1), ("kimitsu-kanko.jp", 1), ("(direct)", 95), ("(not set)", 2)]
    check("AIらしいのに数えていない参照元だけを拾う（chatwork・日本語のドメイン・検索エンジンは拾わない）",
          D.ai_unclassified(srcs), [("chassu.chat-assistant.persol-group.co.jp", 1)])

    ch = [("Organic Search", 161), ("Direct", 95), ("AI Assistant", 28), ("Referral", 5)]
    check("GA4 のチャネル名は単数の「AI Assistant」で数える", D.ai_channel_gap(ch, srcs)[0], 28)
    check("複数形でも拾う（名前の揺れで0にしない）", D.ai_channel_gap([("AI Assistants", 3)], [])[0], 3)
    check("自前の分類（openai を含む）は GA4 のチャネルより多い＝漏れなし",
          D.ai_channel_gap(ch, srcs[1:5]), (28, 47))
    check("GA4 の方が多ければ漏れ", D.ai_channel_gap([("AI Assistant", 5)], [("chatgpt.com", 2)]), (5, 2))

    # 問い合わせ: AI集客ラボ（09-07 は同じ人の再送信を台帳が1行にまとめる・09-18 は調べて決着済み）と
    # コーポレート（09-18 は台帳にだけある）
    check("台帳の再送信まとめ・決着済みの日は食い違いにしない",
          D.lead_mismatch({"2026-09-07": 2, "2026-09-18": 2}, {"2026-09-07": 1}, {"2026-09-18": "確認済み"}), [])
    check("台帳にあるのに GA4 に送信が無い日を拾う",
          D.lead_mismatch({"2026-09-09": 1}, {"2026-09-09": 1, "2026-09-18": 1}), ["2026-09-18"])
    check("GA4 だけにある日は lead_reconcile の担当（ここでは拾わない）",
          D.lead_mismatch({"2026-09-04": 1}, {}), [])


def test_no_plural_ai_channel_name():
    """GA4 の既定チャネル名「AI Assistant」を複数形で比べると0件になる（2026-10-04 に誤報）。書き方で止める"""
    hits = []
    for p in sorted((ROOT / "scripts").rglob("*.py")):
        t = p.read_text(encoding="utf-8", errors="ignore")
        if '"AI Assistants"' in t or "'AI Assistants'" in t:
            hits.append(p.name)
    check("チャネル名を複数形の文字列で比べていない", hits, [])


def test_quality_stuck_articles_go_to_merge():
    """書き直しを2回しても一次性が80点に届かない記事を、統合の候補に出す（補助金の旧記事12本を人手で取り下げた件）"""
    import retire_stale as RS
    audits = {
        "stuck": {"at": "2026-10-01", "audit": {"version": "v3", "axes": {"originality": 55}},
                  "history": [{"version": "v2", "originality": 6}, {"version": "v3", "originality": 50}]},
        "once": {"at": "2026-10-01", "audit": {"version": "v3", "axes": {"originality": 55}}},
        "rose": {"at": "2026-10-01", "audit": {"version": "v3", "axes": {"originality": 82}}},
        "wait": {"at": "2026-09-20", "audit": {"version": "v3", "axes": {"originality": 60}}},
        "oldver": {"at": "2026-10-01", "audit": {"version": "v2", "axes": {"originality": 6}}},
    }
    tries = {"stuck": ["2026-09-10", "2026-09-25"], "once": ["2026-09-25"], "rose": ["2026-09-10", "2026-09-25"],
             "wait": ["2026-09-10", "2026-09-25"], "oldver": ["2026-09-10", "2026-09-25"]}
    legacy = {"ai-hojokin-kyoto-shinsei-daiko": {"axes": {"originality": 47}, "pass": False, "rewritten": True, "attempts": 2},
              "ai-hojokin-osaka-chusho": {"axes": {"originality": 73}, "pass": False, "rewritten": True},
              "ai-hojokin-ok": {"axes": {"originality": 85}, "pass": True, "attempts": 2}}
    got = {x["slug"]: (x["status"], x["src"]) for x in RS.stuck_quality(audits, tries, legacy, "v3", 80)}
    check("2回書き直して届かない記事だけ（1回・上がった・旧基準は出さない。採点前は採点待ち）", got,
          {"stuck": ("候補", "audit"), "wait": ("採点待ち", "audit"), "ai-hojokin-kyoto-shinsei-daiko": ("候補", "legacy")})
    first = next(x for x in RS.stuck_quality(audits, tries, None, "v3", 80) if x["slug"] == "stuck")["first"]
    check("最初の点は同じ基準の採点から取る（旧基準の6点と比べない）", first, 50)

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "auto_fix.jsonl"
        p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in [
            {"at": "2026-09-10 10:00", "by": "auto_rewrite", "slug": "s", "kind": "quality", "ok": True, "note": "直しました（…）"},
            {"at": "2026-09-11 10:00", "by": "auto_rewrite", "slug": "s", "kind": "quality", "ok": False, "note": "警告が増えました"},
            {"at": "2026-09-12 10:00", "by": "auto_rewrite", "slug": "s", "kind": "aio", "ok": True, "note": "直しました（…）"},
        ]) + "\n", encoding="utf-8")
        check("書き直しの回数は quality を実際に当てた分だけ", RS.quality_tries(p), {"s": ["2026-09-10"]})

    ml = (ROOT / "scripts" / "migrate_legacy.py").read_text(encoding="utf-8")
    check("旧記事の書き直しも回数を残す", ('"attempts": tries' in ml, 'AR.note(p.stem, "quality"' in ml), (True, True))
    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週次で一次性が上がらない記事を整理する", "retire_stale.py --quality" in wf, True)


def test_merge_drafts_in_parallel_but_checks_one_by_one():
    """統合案は同時に書かせ、当てるのは1組ずつ。書かせた後で中身が変わった組は案を捨てて書かせ直す"""
    import auto_merge as AM
    import auto_rewrite as AR
    pair = {"site": "ai-lab", "survivor": "s", "loser": "l", "kws": [{"kw": "x"}], "imp": 0,
            "reason": "理由: 書き直しても一次性が上がらない"}
    orig = (AM.is_article, AM.fm, AR.meta, AR.warns, AR.snapshot, AM._claude, AM.url_of)
    calls = []
    with tempfile.TemporaryDirectory() as tmp:
        art = Path(tmp) / "s.md"
        art.write_text("---\ntitle: t\nkeyword: k\n---\n本文", encoding="utf-8")
        saved = AM.ARTICLES
        try:
            AM.is_article = lambda slug: True
            AM.fm = lambda slug: {"text": "loser"}
            AR.meta = lambda slug: ("t", "k", art.read_text(encoding="utf-8"))
            AR.warns = lambda slug: []
            AR.snapshot = lambda: {}
            AM.url_of = lambda site, slug: f"/x/{slug}/"
            AM._claude = lambda prompt, cwd=None: calls.append(prompt) or subprocess.CompletedProcess([], 0, "", "")
            AM.ARTICLES = Path(tmp)
            base = art.read_text(encoding="utf-8")
            AM.run_one(pair, True, draft={"base": base, "loser": "loser", "text": base})
            check("中身が同じなら先に書かせた案を使う（claude を呼び直さない）", len(calls), 0)
            AM.run_one(pair, True, draft={"base": "古い中身", "loser": "loser", "text": "古い統合"})
            check("書かせた後で中身が変わっていたら案を捨てて書かせ直す", len(calls), 1)
            check("呼び出し側の理由をそのまま渡す（食い合いの理由を作らない）",
                  ("一次性が上がらない" in calls[0], "同じ検索語" in calls[0]), (True, False))
        finally:
            AM.ARTICLES = saved
            AM.is_article, AM.fm, AR.meta, AR.warns, AR.snapshot, AM._claude, AM.url_of = orig
    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週次の統合は案を並列で書かせる", "auto_merge.py --write --limit $n --budget-min 30 --parallel" in wf, True)
