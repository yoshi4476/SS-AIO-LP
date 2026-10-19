# -*- coding: utf-8 -*-
"""2026-10-20 全体点検（担当5: 数字・レポート・知らせ・事実の門）で直したものの門。

1. 月次レポート: 平均順位が悪くなった月にも「改善したことが主因」、CV が減った月にも「揃って伸長」と書いていた。
   CV が10件未満でも前月比の割合を出していた（2件→3件で +50%）
2. お客様のレポートに当社の「外部での言及」の数を載せていた
3. 指名検索: 全社に当社の語（セブンセンシズ・AI集客ラボ）を当て、お客様の社名の検索を数えていなかった。
   取れなかった回に BRAND_OK の印を出さず「問題なし」と読まれ、日次の監査も全社失敗を OK と出していた
4. お客様の社の名前・語・URL・slug を CI のログに出していた（growth_guard・daily_audit・outcome_watch・report_digest）
5. 合算の照合（report_audit）と3倍計画（growth_plan）にお客様の数字を足していた
6. findings: 結果のファイルが無い週に要対応の語の無い文を送ろうとして送られず、「動かせず」を情報に下げ、
   明細の記録を300で切って毎週「新しい明細」にしていた
7. 一次情報: お客様の社の一次情報を公開リポジトリの first_party_facts.json に登録できた
8. 表示の門（legal_claims）: 漢数字・パーセント・「累計」「社超」・割合の言い換え・キャッシュバック・「代わりに作ります」を
   見逃し、還元の該当があると表示名の対応表に無く KeyError で落ちていた
9. 多言語の数字の照合: 展開前の「10」・月を落とした形を許し、「10万円→10 yen」「9月→October」が通っていた。
   範囲の上下・上限と下限の入れ替えも見ていなかった
10. 動画の台本: 漢数字を数として拾わず、ショートの決まり8（当社の実績の数字は使わない）は指示だけだった
11. seo_audit が手元の Windows で cp932 に無い字を出して落ちていた／llms.txt の監修者の行が裸の URL だった
お客様の語は架空（client-zz・zz.example）で書く。本物の通信・課金・送信はしない。
"""
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

CL, PUB, NAME, DOM = "client-zz", "c0000zz00", "株式会社ズィーズィー工務店", "zz.example"
CFG = {"id": CL, "name": NAME, "domain": DOM, "client": True, "categories": {"zz-blog": "ブログ"}, "public_id": PUB}


def _is_client(s):
    return s in (CL, PUB)


def _pub(s):
    return PUB if s == CL else s


def _out(fn, *a, **k):
    buf = io.StringIO()
    with redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


def _analyze(prev, cur):
    import monthly_report as M
    base = {"label": "2026-08"}
    d = {"months": [dict(base, **prev), dict({"label": "2026-09"}, **cur)], "content": {"published": 10}}
    return M.analyze(d)


# ── 1. 月次レポートの向き ───────────────────────────────

def test_monthly_summary_reads_rank_and_small_cv_correctly():
    print("\n■ 月次の要約: 順位は小さいほど良い・揃っての伸びは3つとも上向きのとき・CV10件未満は件数だけ")
    worse = _analyze({"clicks": 100, "impressions": 5000, "sessions": 300, "cv": 5, "pos": 10.0},
                     {"clicks": 150, "impressions": 6000, "sessions": 400, "cv": 3, "pos": 14.0})
    g = " ".join(worse["grown"])
    check("順位が10→14位に悪化した月に「改善」と書かない", ("改善しています" in g, "主因" in g), (False, False))
    check("CV が減った月に「揃って伸長」と書かない", "揃って伸長" in worse["summary"], False)
    check("CV が10件未満なら割合を出さず件数（前月の件数）", ("CV3件（前月5件）" in worse["summary"],
                                                   "CV3件（-" in worse["summary"] or "CV3件（+" in worse["summary"]),
          (True, False))
    check("CV が減った月を「横ばい」と書かない", "横ばい" in " ".join(worse["headline"]), False)
    good = _analyze({"clicks": 100, "impressions": 5000, "sessions": 300, "cv": 20, "pos": 14.0},
                    {"clicks": 150, "impressions": 6000, "sessions": 400, "cv": 30, "pos": 10.0})
    check("3つとも上向き・順位が上がった月は「揃って伸長」「改善」", ("揃って伸長" in good["summary"],
                                                  "改善しています" in " ".join(good["grown"])), (True, True))
    check("CV が10件以上なら前月比の割合を出す", "CV30件（+" in good["summary"], True)


# ── 2・3. お客様のレポートの言及・指名検索 ─────────────────────

def test_client_report_has_no_operator_mentions_and_own_brand_words():
    import monthly_report as M
    import brand_search as B
    import sites as S
    import private_store as PS
    print("\n■ お客様のレポートに当社の言及を載せない・指名検索はお客様の社名で数える")
    with mock.patch.object(M, "SITE_ID", CL), mock.patch.object(S, "is_client", _is_client):
        check("お客様の社の外部での言及は「未登録」（当社の台帳の数を出さない）", M._ai_mentions(), None)
    with mock.patch.object(M, "SITE_ID", "ai-lab"), mock.patch.object(S, "is_client", lambda s: False):
        check("自社は言及の台帳を数える（件数の組）", isinstance(M._ai_mentions(), tuple), True)

    with mock.patch.object(S, "is_client", _is_client), \
            mock.patch.object(PS, "read_json", lambda sid, f, d=None: {"name": NAME} if sid == CL else d):
        pat = B.pattern_for(CL)
        check("お客様の社名（法人の種類を外した部分）で数える",
              (bool(pat.search("ズィーズィー工務店 評判")), bool(pat.search("セブンセンシズ"))), (True, False))
        check("自社は当社の語", B.pattern_for("ai-lab") is B.BRAND, True)
    with mock.patch.object(S, "is_client", _is_client), mock.patch.object(PS, "read_json", lambda *a, **k: {}):
        check("社名が無いお客様の社は数えない（None）", B.pattern_for(CL), None)

    asked = []

    def fake_collect(days=28, only=None):
        asked.append(only)
        return {}
    with mock.patch.object(M, "SITE_ID", PUB), mock.patch.object(S, "resolve", lambda s: CL if s == PUB else s), \
            mock.patch.object(B, "collect", fake_collect):
        got = M._ai_brand()
    check("公開の id で呼ばれても社の id で引き、取れなければカードを出さない", (asked, got), ([{CL}], None))


def _fake_gsc(fail=()):
    import gsc_detail as G

    def q(sc, dom, a, b, dims, n, raise_errors=False):
        if dom in fail:
            raise RuntimeError("down https://" + dom)
        return [{"keys": ["ズィーズィー工務店 口コミ"], "impressions": 10, "clicks": 1, "position": 2.0},
                {"keys": ["セブンセンシズ 評判"], "impressions": 7, "clicks": 1, "position": 1.0}]
    return mock.patch.object(G, "client", lambda: object()), mock.patch.object(G, "q", q)


def test_brand_search_unknown_when_not_fetched():
    import brand_search as B
    import daily_audit as D
    import sites as S
    import private_store as PS
    print("\n■ 指名検索: 取れなかった回は BRAND_OK=unknown・日次の監査は SKIPPED に入れる")
    sites = {"ai-lab": {"name": "AI集客ラボ", "domain": "ai.example"}, CL: CFG}
    p1, p2 = _fake_gsc()
    with p1, p2, mock.patch.object(S, "load_all", lambda: sites), mock.patch.object(S, "is_client", _is_client), \
            mock.patch.object(S, "public_id", _pub), \
            mock.patch.object(PS, "read_json", lambda sid, f, d=None: {"name": NAME} if sid == CL else d):
        got = B.collect(28)
    check("お客様の社は社名の語だけ・自社は当社の語だけを数える",
          (got[CL]["cur"]["imp"], got["ai-lab"]["cur"]["imp"]), (10, 7))
    check("お客様の社の名前はログ用に公開の id", got[CL]["name"], PUB)
    with mock.patch.object(B, "collect", mock.Mock(side_effect=RuntimeError("no key"))), \
            mock.patch.object(sys, "argv", ["brand_search.py"]):
        _, out = _out(B.main)
    check("GSC に接続できない回は BRAND_OK=unknown", ("BRAND_OK=unknown" in out, "BRAND_OK=yes" in out), (True, False))
    with mock.patch.object(B, "collect", lambda *a, **k: {}), mock.patch.object(sys, "argv", ["brand_search.py"]):
        _, out = _out(B.main)
    check("結果が空の回も BRAND_OK=unknown", "BRAND_OK=unknown" in out, True)
    p1, p2 = _fake_gsc(fail=(DOM,))
    with p1, p2, mock.patch.object(S, "load_all", lambda: sites), mock.patch.object(S, "is_client", _is_client), \
            mock.patch.object(S, "public_id", _pub), mock.patch.object(sys, "argv", ["brand_search.py"]), \
            mock.patch.object(PS, "read_json", lambda sid, f, d=None: {"name": NAME} if sid == CL else d):
        _, out = _out(B.main)
    check("一部の社が取れず減っていない回は yes にしない（unknown）", ("BRAND_OK=unknown" in out, DOM in out), (True, False))

    D.SKIPPED.clear()
    p1, p2 = _fake_gsc(fail=("ai.example", DOM))
    with p1, p2, mock.patch.object(S, "load_all", lambda: sites), mock.patch.object(S, "is_client", _is_client), \
            mock.patch.object(S, "public_id", _pub), \
            mock.patch.object(PS, "read_json", lambda sid, f, d=None: {"name": NAME} if sid == CL else d):
        _out(D.check_brand, [])
    check("日次の監査: 全社が取れなかった回は SKIPPED に「指名検索」", "指名検索" in D.SKIPPED, True)
    D.SKIPPED.clear()


# ── 4. ログにお客様の名前・語・URL を出さない ─────────────────────

def test_logs_show_only_public_id_for_clients():
    import growth_guard as GG
    import gsc_detail as G
    import measure
    import sites as S
    import daily_audit as D
    import outcome_watch as OW
    print("\n■ growth_guard・daily_audit・outcome_watch はお客様の社を公開の id と件数だけで出す")
    calls = {"n": 0}

    def totals(dom, a, b):
        calls["n"] += 1
        return (1000, 50) if calls["n"] % 2 == 0 else (100, 5)    # 今期100・前期1000（落ちた）

    def q(sc, dom, a, b, dims, n, raise_errors=False):
        if calls["n"] <= 2:
            return []
        return [{"keys": ["zz秘密の語", f"https://{DOM}/zz-secret-slug/"], "impressions": 500, "clicks": 3, "position": 4.0}]
    with mock.patch.object(G, "client", lambda: object()), mock.patch.object(G, "q", q), \
            mock.patch.object(measure, "gsc_totals", totals), mock.patch.object(S, "load_all", lambda: {CL: CFG}), \
            mock.patch.object(S, "is_client", _is_client), mock.patch.object(S, "public_id", _pub), \
            mock.patch.object(sys, "argv", ["growth_guard.py"]):
        alerts, out = _out(GG.main)
    check("growth_guard: 落ちたことは知らせる", "GROWTH_DROP=yes" in out, True)
    check("growth_guard: 社名・語・URL・ドメインを出さず公開の id を出す",
          [w for w in (NAME, "zz秘密の語", "zz-secret-slug", DOM) if w in out] + [PUB in out], [True])

    with mock.patch.object(S, "is_client", _is_client), mock.patch.object(S, "public_id", _pub):
        check("daily_audit: お客様の社は公開の id・記事は伏せる（範囲の数えのために公開の id は残す）",
              (D.site_shown(CL), D.slug_shown("zz-secret-slug", CL), D.slug_shown("own-slug", "ai-lab")),
              (PUB, f"{PUB} の（お客様の記事）", "own-slug"))
        with mock.patch.object(D.growth_guard if hasattr(D, "growth_guard") else GG, "main", lambda: [(CL, -0.5, 3, 2, [f"https://{DOM}/zz-secret-slug/"])]):
            todo = []
            _out(D.check_growth, todo)
        check("daily_audit: 表示が落ちた TODO に URL を出さない", (DOM in " ".join(todo), PUB in " ".join(todo)), (False, True))

    art = {"slug": "zz-secret-slug", "date": "2026-10-19", "category": "zz-blog"}
    with mock.patch.object(D, "articles_by_site", lambda: {CL: [art]}), mock.patch.object(D, "counted_day", lambda a: "2026-10-19"), \
            mock.patch.object(D, "_is_published", lambda a, need_review=True: True), \
            mock.patch.object(OW, "expected_articles", lambda sid, arts, day: 1), \
            mock.patch.object(S, "load_all", lambda: {CL: CFG}), mock.patch.object(S, "is_client", _is_client), \
            mock.patch.object(S, "public_id", _pub), \
            mock.patch.object(S, "article_url", lambda cfg, m: f"https://{DOM}/zz-blog/{m['slug']}/"), \
            mock.patch("urllib.request.urlopen", mock.Mock(side_effect=OSError(f"https://{DOM}/ down"))):
        bad = []
        from datetime import date
        _, out = _out(OW.check_articles, date(2026, 10, 19), bad)
    txt = out + " ".join(bad)
    check("outcome_watch: 開けない記事は知らせるが、社名・ドメイン・slug を出さない",
          (len(bad), [w for w in (NAME, DOM, "zz-secret-slug") if w in txt], PUB in txt), (1, [], True))


def test_report_digest_log_hides_client_rows():
    import report_digest as RD
    import sites as S
    print("\n■ report_digest: ログの本文はお客様の社の行を伏せる（メールの本文はそのまま）")
    rows = [{"site": CL, "name": NAME, "ok": True}, {"site": "ai-lab", "name": "AI集客ラボ", "ok": True}]
    lines = ["2026-09 の月次レポート（2社）", f"・{NAME}:", "    - 計測の権限 → 付与する", "・AI集客ラボ（ai-lab-2026-09.pdf）",
             f"消費 {CL}: 10.0 / 上限 150"]
    with mock.patch.object(S, "is_client", _is_client), mock.patch.object(S, "public_id", _pub), \
            mock.patch.object(S, "load_all", lambda: {CL: CFG, "ai-lab": {}}):
        log = RD.log_body(lines, rows)
    check("お客様の社名・社の id・その社の明細を出さず、自社の行は残す",
          ([w for w in (NAME, CL, "計測の権限") if w in log], "AI集客ラボ" in log, "伏せ" in log or "出しません" in log),
          ([], True, True))


# ── 5. 合算・3倍計画は自社だけ ─────────────────────────────

def test_group_totals_use_own_sites_only():
    import growth_plan as GP
    import group_report as GR
    import inspect
    import report_audit as RA
    print("\n■ 合算の照合と3倍計画は自社のグループ（own_cfgs）だけを足す")
    seen = []

    def fetch(cfg, labels):
        seen.append(cfg["id"])
        return {"months": [{"clicks": 1}]}
    with mock.patch.object(GR, "own_cfgs", lambda: {"ai-lab": {"id": "ai-lab"}}), mock.patch.object(GR, "fetch_site", fetch):
        GP.measure("2026-09")
    check("growth_plan.measure はお客様の社を取りに行かない", seen, ["ai-lab"])
    src = inspect.getsource(RA.audit_group)
    check("report_audit の合算は own_cfgs（お客様の社を取り直さない・表示しない）",
          ("own_cfgs()" in src, "S.load_all()" in src), (True, False))


# ── 6. findings の知らせ方 ────────────────────────────────

def test_findings_never_silences_broken_or_missing_checks():
    import findings as F
    import notify_slack as N
    print("\n■ findings: 結果が無い週も要対応で送る・動かない検査は情報に下げない・明細の記録を切らない")
    with tempfile.TemporaryDirectory() as d:
        missing = F.body_text(Path(d) / "findings.txt")
        empty = Path(d) / "e.txt"
        empty.write_text("# 生成: 2026-10-20 09:00 JST（x）\n", encoding="utf-8")
        check("findings.txt が無い・空の回は「要対応: 検査の結果を取得できませんでした」で、定時でも送られる",
              (missing.startswith(F.MISSING), F.body_text(empty).startswith(F.MISSING),
               N.worth_sending("🔧 週次最適化: success\n" + missing, True)), (True, True, True))
    lab = "指名検索の推移"
    _, _, _, rec = F.notice(lab, ["BRAND_OK=unknown"], {}, "2026-10-12", state="動かせず")
    act, why, _, _ = F.notice(lab, ["BRAND_OK=unknown"], {lab: rec}, "2026-10-19", state="動かせず")
    check("「動かせず」は先週と同じでも要対応のまま", act, True)
    many = [f"要対応: 明細 {chr(0x4e00 + i)}{chr(0x4e00 + i * 7 % 900)}" for i in range(450)]
    _, _, _, rec = F.notice("x", many, {}, "2026-10-12")
    act, why, _, _ = F.notice("x", many, {"x": rec}, "2026-10-19")
    check("明細が300行を超えても、先週と同じなら「新しい明細」にしない", (act, "新しい明細" in why), (False, False))


# ── 7. 一次情報 ────────────────────────────────────────

def test_add_fact_refuses_client_sites():
    import add_fact as AF
    import sites as S
    print("\n■ add_fact: お客様の社の一次情報は公開の first_party_facts.json に入れない")
    f = {"id": "zz-fact", "sites": [CL], "topic": ["施工"], "claim": "2025年に12棟を施工しました", "source": "自社",
         "as_of": "2026-09"}
    with mock.patch.object(S, "is_client", _is_client), mock.patch.object(S, "public_id", _pub), \
            mock.patch.object(S, "load_all", lambda: {CL: CFG, "corporate": {}}):
        bad = AF.problems(f, set())
        ok = AF.problems(dict(f, sites=["corporate"]), set())
    check("お客様の社は止め、非公開の facts.json へ案内する（社の名前は公開の id）",
          (any("非公開の facts.json" in x for x in bad), any(NAME in x or CL in x for x in bad)), (True, False))
    check("自社の社は止めない", ok, [])


# ── 8. 表示の門 ─────────────────────────────────────────

MUST = ["当社の採択率は九割です。", "当社の採択率は90パーセントです。", "当社は200社の導入を支援しました。",
        "当社は200社超の企業を支援しています。", "当社は累計200社の申請に関わりました。", "当社はのべ五十社の導入を支援しました。",
        "当社が支援した企業の9割が採択されました。", "当社は42社中38社が採択されました。",
        "採択後にキャッシュバックします。", "申請書類を代わりに作ります。"]
MUST_NOT = ["全国で1万社超が申請しました。", "当社は2023年1月から2026年8月までに、経理BPOを10社以上へ導入しています。",
            "行政書士は申請書類を代わりに作ります。", "採択後のキャッシュバックは規程上で禁止されています。",
            "1,000社のうち400社が採択されました（中小企業庁）。", "着手金の不採択時返金の有無も会社によって異なります。",
            "IT導入補助金の採択率はおよそ九割と言われますが、事業者は根拠を確認してください。"]


def test_legal_claims_catches_reworded_claims():
    import legal_claims as LC
    print("\n■ 表示の門: 漢数字・パーセント・累計・社超・割合の言い換え・キャッシュバック・代わりに作るを拾う")
    check("見つけるべき言い方を拾う", [s for s in MUST if not LC.find(s)], [])
    check("一般の説明・公的な数字・注意喚起は拾わない", [s for s in MUST_NOT if LC.find(s)], [])
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.md"
        p.write_text("補助金の一部をキャッシュバックします。\n", encoding="utf-8")
        with mock.patch.object(sys, "argv", ["legal_claims.py", str(p)]):
            try:
                _, out = _out(LC.main)
                err = ""
            except KeyError as e:
                out, err = "", repr(e)
    check("還元の該当があっても落ちずに LEGAL_OK=no を出す（表示名の対応表に rebate）", (err, "LEGAL_OK=no" in out), ("", True))


# ── 9. 多言語の数字 ────────────────────────────────────

def _d(title="", lead=""):
    return {"title": title, "lead": lead, "description": "", "sections": [], "faq": []}


def test_i18n_compares_magnitude_percent_month_and_bounds():
    import i18n as I
    print("\n■ 多言語: 桁・割合・月をそろえて比べ、範囲の上下・上限と下限の入れ替えを捨てる")
    src = _d("AI導入補助金は10万円", "2026年9月時点で6つの手順")
    bad = [(src, _d("Subsidy: 10 yen", "As of September 2026, 6 steps")),
           (src, _d("Subsidy: 100,000 yen", "As of October 2026, 6 steps")),
           (_d("上限は450万円"), _d("The maximum is 45 million yen")),
           (_d("上限は450万円"), _d("상한은 450억 엔입니다")),
           (_d("採択者の3割が"), _d("3% of adopted applicants")),
           (_d("", "3〜5社に相談"), _d("", "Consult 5 to 3 companies")),
           (_d("", "補助の上限は100万円です"), _d("", "The subsidy is at least 1,000,000 yen")),
           (_d("", "従業員10人以上の会社"), _d("", "Companies with up to 10 employees"))]
    good = [(src, _d("Subsidy: 100,000 yen", "As of September 2026, 6 steps")),
            (_d("上限は450万円"), _d("The maximum is 4.5 million yen")),
            (_d("上限は450万円"), _d("상한은 450만 엔입니다")),
            (_d("上限は450万円"), _d("上限为450万日元")),
            (_d("採択者の3割が"), _d("30% of adopted applicants")),
            (_d("", "費用は3〜5万円"), _d("", "It costs 30,000 to 50,000 yen")),
            (_d("", "補助の上限は100万円です"), _d("", "The subsidy is up to 1,000,000 yen")),
            (_d("", "1億5000万円"), _d("", "150 million yen")),
            (_d("", "6つの手順"), _d("", "You may need 6 steps"))]
    check("意味の変わった訳を捨てる", [b["title"] + b["lead"] for a, b in bad if I._digits_ok(a, b)[0]], [])
    check("正しい訳は通す", [b["title"] + b["lead"] for a, b in good if not I._digits_ok(a, b)[0]], [])


# ── 10. 動画の台本 ──────────────────────────────────────

def test_video_scripts_read_kanji_numbers_and_rule8():
    import duo_video as DV
    import duo_short as DS
    print("\n■ 動画の台本: 漢数字を数に読む・ショートは当社の実績の数字を使わない")
    check("漢数字を数にそろえる（三割・四百五十万円・五十社・二〇二六年）",
          [DV._nums(s) for s in ("三割", "四百五十万円", "五十社", "二〇二六年")], [["3"], ["450"], ["50"], ["2026"]])
    check("数でない漢数字は拾わない（十分・一緒・一人で・一つずつ）",
          [DV._nums(s) for s in ("十分に", "一緒に", "一人で", "一つずつ")], [[], [], [], []])
    art = {"text": "延床32坪で断熱等級6。AI集客ラボ。", "category": "aio"}
    sc = {"lines": [{"who": "N", "text": "当社の実績では32坪です。"}, {"who": "N", "text": "延床32坪です。"}]}
    with mock.patch.object(DV, "brand", lambda a: {"name": "AI集客ラボ", "search": "AI集客ラボ"}):
        ng = DS.own_ng(sc, art)
    check("当社が主語の文の数字は記事にあっても止め、記事の事実の文は止めない", [x.split(":")[0] for x in ng], ["0"])
    _, out = _out(DS.selftest)
    check("ショートの自己診断が通る（決まり8・漢数字を含む）", "SHORT_SELFTEST=ok" in out, True)


# ── 11. 出力の落ち・llms.txt ─────────────────────────────

def test_seo_audit_survives_cp932_and_llms_link_form():
    import inspect
    import seo_audit as SA
    print("\n■ seo_audit は手元の cp932 でも落ちない・llms.txt の監修者は Markdown のリンク")
    check("seo_audit.main の頭で標準出力を置き換え可能にする", 'reconfigure(errors="replace")' in inspect.getsource(SA.main), True)
    t = (ROOT / "site" / "llms.txt").read_text(encoding="utf-8")
    check("llms.txt に「監修者プロフィール: URL」の裸の URL が無い",
          ("監修者プロフィール: http" in t, "[監修者プロフィール](https://" in t), (False, True))
