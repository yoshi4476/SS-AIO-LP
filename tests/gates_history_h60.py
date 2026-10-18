# -*- coding: utf-8 -*-
"""計測と「お客様のデータを public に置かない」の残り（2026-10-08 の点検と直しの後に残った細かい所）。

  1. 入口の押下を cta_click・diagnosis_click・contact_intent の合計で数え、診断・相談の押下を2回数えていた
     （コーポレートは 10/8 から診断の入口で cta_click と diagnosis_click を両方送る）。月次レポートは
     cta で始まる出来事を全部足し、cta_click と cta_〈ボタンID〉の2つを数えて2倍に出ていた（AI集客ラボ・補助金）
  2. コーポレートが送る cta_kind が GA4 に未登録。お客様の社はカスタム定義が1つも無かった
  3. 拡張計測の「フォームの操作」と自前の form_start・form_submit が重なる。止めた日を残し、数字に添える
  4. コーポレートの記事の相談ボタン（262か所）が /contact/ → /contact の転送（308）を挟み、
     コーポレートの計測（pathname === "/contact"）にも数えられていなかった
  5. 中ほどの導線が、補助金の記事にも AI集客ラボの青で出ていた
  6. 設定の lead_hub を変えただけで全記事の描き直しが走る
  7. お客様の行・ファイル（介入の台帳・学び・量産の兆候・本数の効き・狙う語の記録・積んだ語・AIの答え）が
     public に載りうる

ネットワーク・GA4・台帳には触れない（全部スタブ）。
"""
import contextlib
import io
import json
import re
import sys
import tempfile
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


# ── 1. 入口の押下は cta_click だけで数える ─────────────────────────────

def test_entry_clicks_are_counted_once():
    import funnel as F
    steps = dict(F.STEPS)
    check("ファネル: CTAを押した は cta_click だけ（diagnosis_click・contact_intent は同時に飛ぶので足さない）",
          steps.get("CTAを押した"), ("cta_click",))
    cc = getattr(F, "cta_counts", None)
    check("ファネル: 日ごとに数え方を決める関数がある（funnel.cta_counts）", callable(cc), True)
    if not callable(cc):
        return
    by_day = {
        # コーポレートの 10/7 まで: cta_click が無い。診断（diagnosis_click）と相談への遷移（contact_intent）で数える
        "20261006": {"diagnosis_click": 3, "contact_intent": 2},
        # 10/8 から: cta_click と diagnosis_click・contact_intent が同時に飛ぶ。cta_click だけ
        "20261008": {"cta_click": 4, "diagnosis_click": 1, "contact_intent": 1},
        # AI集客ラボの cta_id 登録前: cta_click と cta_〈ボタンID〉が1回ずつ。A/B の cta_click_a は数えない
        "20260920": {"cta_click": 3, "cta_top_mv_lp": 2, "cta_x": 1, "cta_click_a": 1},
    }
    ids = {"20261008": [("article_body_contact-keiri-bpo", "contact", 2), ("top_hero_lab-ai-check", "diagnosis", 1),
                        ("svc-aio_industries_lab-checklist", "doc", 1)],
           "20260920": [("(not set)", "", 3)]}
    got = cc(by_day, ids)
    check("ファネル: 押下は日ごとに cta_click（無い日だけ旧い2つ）で、問い合わせ方向は cta_kind・cta_id・ボタンIDの名前で",
          (got["total"], got["to_contact"], got["legacy_days"], got["name_days"]),
          (12, 6, ["20261006"], ["20260920"]))
    cb = F.contact_bound
    cases = {("nav_consult", ""): True, ("article_mid_diagnosis", ""): False, ("lp_fudosan_scan", ""): False,
             ("ai_check_lp_fudosan", ""): True, ("article_article-cta_contact-system-development", ""): True,
             ("service_main_package", ""): False, ("form_submit", ""): False, ("tel", ""): True,
             ("AI導入補助金の無料相談", ""): True, ("補助金が使えるか、3分で無料診断する", ""): False,
             ("x", "contact"): True, ("top_hero_contact", "doc"): False}
    check("問い合わせ方向: 最後に出てくる行き先の語で決める（cta_kind があればそれ）",
          {k: cb(*k) for k in cases}, cases)

    def fake_days(prop, start, end):
        return {"20261008": {"page_view": 50, "cta_click": 4, "diagnosis_click": 1, "contact_intent": 1,
                             "form_start": 2, "lead_capture": 1, "generate_lead": 1}}
    st = F.stages("1", date(2026, 10, 8), date(2026, 10, 8), by_day=fake_days("1", None, None), sent=1)
    check("ファネル: 段の数（押下は cta_click だけ・送信は lead_reconcile の数え方）",
          [n for _, n in st], [50, 4, 2, 1])
    import site_diagnosis as SD
    import lead_reconcile as LR
    with patched(F, day_events=fake_days), patched(LR, ga4_by_day=lambda p, s, e: {"2026-10-08": 1}):
        got = SD.funnel_counts("1", 28)
    check("サイトの現在地（レポート）も同じ数え方（以前は3つの合計と lead_capture＋generate_lead の合計）",
          [n for _, n in got], [50, 4, 2, 1])


def test_monthly_report_counts_like_the_funnel():
    import monthly_report as M
    bc = getattr(M, "behavior_counts", None)
    check("月次: 行動の内訳を数える関数がある（monthly_report.behavior_counts）", callable(bc), True)
    if not callable(bc):
        return
    by_day = {"20260920": {"cta_click": 3, "cta_top_mv_lp": 2, "cta_x": 1, "form_start": 2, "form_submit": 4},
              "20260921": {"session_start": 9}}
    b = bc(by_day, {"20260920": [("(not set)", "", 3)]}, leads=1)
    check("月次: ボタン押下は cta_click だけ（以前は cta で始まる出来事を全部足して6）・問い合わせ方向はボタンIDで",
          (b["cta"], b["cta_to_form"], b["form_start"], b["sessions"]), (3, 2, 2, 9))
    check("月次: 送信完了は問い合わせの数え方（lead_capture / generate_lead）。form_submit は拡張計測と重なる",
          b["form_submit"], 1)
    src = (ROOT / "scripts" / "monthly_report.py").read_text(encoding="utf-8")
    check("月次: cta で始まる出来事を足す数え方が残っていない", 'k.startswith("cta")' in src, False)
    check("月次: 送信完了は lead_reconcile で数える", "LR.ga4_by_day(" in src and "behavior_counts(" in src, True)
    import funnel as F
    notes = F.change_notes("ai-lab", date(2026, 10, 1), date(2026, 10, 31))
    check("月次: 10/8 に入口リンクも数えるようにした月は、前後で比べられないと添える",
          any("2026-10-08" in n and "比べられません" in n for n in notes), True)
    check("月次: 変更の無い期間は何も添えない", F.change_notes("ai-lab", date(2026, 11, 1), date(2026, 11, 30)), [])
    check("月次: コーポレートは cta_click を送り始めた日を添える（それより前は旧い2つの出来事で数えた）",
          any("2026-10-08" in n for n in F.change_notes("corporate", date(2026, 10, 1), date(2026, 10, 31))), True)
    check("月次: 数え方を変えた月（2026-10）のレポートに、以前のレポートとの違いを書く",
          bool(M.method_note("2026-10")) and not M.method_note("2026-11"), True)


def test_inline_compare_warns_when_counting_changed():
    import funnel as F
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "inline_tool.json"
        p.write_text(json.dumps({"sites": {"ai-lab": {"since": "2026-10-05"}}}), encoding="utf-8")
        with patched(F, inline_compare=lambda site, prop, since: ([("記事の訪問", 1, 1)], 9), INLINE_FILE=p):
            _, out = _quiet(F.print_inline, {"ai-lab": {"name": "AI集客ラボ", "ga4_property_id": "1"}})
    check("記事の入力欄の前後比較: 比べる期間に入口の数え方の変更（10/8）があれば、押下は比べられないと書く",
          "比べられません" in out and "2026-10-08" in out, True)


# ── 2・3. GA4 の定義と、拡張計測のフォームの操作 ───────────────────────

def test_ga4_custom_dims_and_form_interactions():
    import ga4_dims as G
    check("GA4: cta_kind（入口の種類）を登録する", "cta_kind" in [n for n, _ in G.DIMS], True)
    check("GA4: 表示名に記号を使わない（全角の括弧でお客様の社の page_path が 400 で登録できなかった）",
          [label for _, label in G.DIMS if not re.fullmatch(r"[\w ]+", label)], [])
    ver = getattr(G, "verified", None)
    check("拡張計測: 自前の計測が出ているかを決める関数がある（ga4_dims.verified）", callable(ver), True)
    if not callable(ver):
        return
    check("拡張計測: 種類つきの form_start と、離脱・種類つきの送信・問い合わせのどれかが出ていれば止めてよい",
          [ver(c)[0] for c in ({"typed_start": 1, "abandon": 1}, {"typed_start": 1, "typed_submit": 1},
                               {"typed_start": 1, "leads": 1}, {"typed_start": 0, "abandon": 3, "leads": 2},
                               {"typed_start": 2}, None)],
          [True, True, True, False, False, False])

    class Sess:
        def __init__(self):
            self.patched = []

        def get(self, url, params=None):
            class R:
                ok = True
                status_code = 200

                def __init__(self, d):
                    self._d = d

                def json(self):
                    return self._d
            if url.endswith("/dataStreams"):
                return R({"dataStreams": [{"name": "properties/1/dataStreams/9", "type": "WEB_DATA_STREAM"}]})
            return R({"name": "properties/1/dataStreams/9/enhancedMeasurementSettings", "streamEnabled": True,
                      "formInteractionsEnabled": True, "scrollsEnabled": True})

        def patch(self, url, params=None, json=None):
            self.patched.append((url, params, json))

            class R:
                ok = True
                status_code = 200

                def json(self):
                    return {"formInteractionsEnabled": False}
            return R()
    with tempfile.TemporaryDirectory() as td:
        rec = Path(td) / "ga4_settings.json"
        with patched(G, SETTINGS=rec):
            s1 = Sess()
            r1, _ = _quiet(G.forms_off, s1, "x-site", "1", True, counts=lambda p: {"typed_start": 1, "abandon": 1},
                           today="2026-10-08")
            s2 = Sess()
            r2, _ = _quiet(G.forms_off, s2, "y-site", "2", True, counts=lambda p: {"typed_start": 0, "leads": 4},
                           today="2026-10-08")
            saved = json.loads(rec.read_text(encoding="utf-8"))
    check("拡張計測: 確かめられた社だけ formInteractionsEnabled を false にする（updateMask つき）",
          ([(u.endswith("enhancedMeasurementSettings"), p, j) for u, p, j in s1.patched], s2.patched),
          ([(True, {"updateMask": "formInteractionsEnabled"}, {"formInteractionsEnabled": False})], []))
    entry = (saved.get("form_interactions_off") or {}).get("x-site") or {}
    check("拡張計測: 止めた日と変える前の値を data/ga4_settings.json に残す（確かめられない社は書かない）",
          (entry.get("at"), entry.get("before", {}).get("formInteractionsEnabled"), "y-site" in saved.get("form_interactions_off", {})),
          ("2026-10-08", True, False))
    check("拡張計測: 結果を返す（変えた・確かめられない）", (r1.get("changed"), r2.get("changed")), (True, False))
    import funnel as F
    with tempfile.TemporaryDirectory() as td:
        rec = Path(td) / "ga4_settings.json"
        rec.write_text(json.dumps({"form_interactions_off": {"ai-lab": {"at": "2026-10-08"}}}), encoding="utf-8")
        with patched(F, FORM_AUTO_FILE=rec):
            n_mid = F.form_note("ai-lab", date(2026, 10, 1), date(2026, 10, 31))
            n_after = F.form_note("ai-lab", date(2026, 11, 1), date(2026, 11, 30))
            n_on = F.form_note("subsidy", date(2026, 11, 1), date(2026, 11, 30))
    check("拡張計測: 止めた日をまたぐ期間・止めていない社には、入力開始が重なることを添える。止めた後は何も添えない",
          ("2026-10-08" in (n_mid or ""), n_after, "有効" in (n_on or "")), (True, None, True))


def test_form_interactions_are_off_only_where_own_tracking_was_seen():
    p = ROOT / "data" / "ga4_settings.json"
    d = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    off = d.get("form_interactions_off") or {}
    check("拡張計測のフォームの操作を止めた社は、変える前の値と止めた日・確かめた出来事を残している",
          all(v.get("at") and isinstance(v.get("before"), dict) and v.get("seen") for v in off.values()) and bool(off), True)


# ── 4. コーポレートの相談ボタンは転送の無い URL ──────────────────────

def test_corporate_cta_has_no_redirect():
    import sites as S
    import tool_links as TL
    import cta_fill as C
    url = (S.load("corporate").get("cta") or {}).get("url", "")
    check("コーポレートの相談ボタンの行き先は記事の入口と同じ /contact?s=keiri-bpo（/contact/ は 308 を挟む）",
          url, TL.CORP_CONTACT)
    stale = getattr(C, "stale_links", None)
    check("CTA の行き先がサイト設定と食い違う記事を数える関数がある（cta_fill.stale_links）", callable(stale), True)
    if not callable(stale):
        return
    left = stale()
    check("記事の相談ボタンに、設定と同じ場所を指す古い形（末尾の / 違い）が残っていない", left[:3], [])
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "articles").mkdir()
        body = ("---\ntitle: t\ncategory: keiri-bpo\nscore: 95\n---\n\n## 見出し\n\n本文\n\n"
                '<div class="cta-box"><p>相談</p><a class="cta-button" href="https://corp.7senses.co.jp/contact/">相談</a></div>\n\n'
                '<div style="text-align:center"><a href="https://corp.7senses.co.jp/contact/" class="cta-button">相談</a></div>\n\n'
                "[経理の現状分析（無料）](https://corp.7senses.co.jp/contact/?s=keiri-shindan)\n")
        (root / "articles" / "x.md").write_text(body, encoding="utf-8")
        with patched(C, ROOT=root):
            n1 = sum(n for _, n in C.stale_links())
            _quiet(C.relink, True)
            out = (root / "articles" / "x.md").read_text(encoding="utf-8")
            n2 = sum(n for _, n in C.stale_links())
    check("--relink: 相談ボタンの href だけを今の行き先へ（本文の別の入口・クエリ付きの URL は触らない）",
          (n1, n2, out.count(TL.CORP_CONTACT), "contact/?s=keiri-shindan" in out), (2, 0, 2, True))


# ── 5. 中ほどの導線はサイトの色 ─────────────────────────────────

def test_mid_cta_uses_the_site_colors():
    import publish as P
    import sites as S
    sub = P.mid_cta_block(S.load("subsidy"))
    lab = P.mid_cta_block(S.load("ai-lab"))
    check("補助金の中ほどの導線に AI集客ラボの青（#1b4fa0）を書かない", "#1b4fa0" in sub, False)
    check("補助金の中ほどの導線は主ボタンと同じ金（sites/subsidy.json の cta_colors）",
          "#d9b36a" in sub and "#171104" in sub, True)
    check("色の設定の無い社は、これまでどおりの色", "#1b4fa0" in lab, True)
    cfg = {"id": "zz", "diagram_colors": {"accent": "#C2410C", "soft": "#F7E4D9", "line": "#D5D6D0", "muted": "#4B4F57"},
           "cta": {"label": "相談", "url": "https://zz.test/contact"}}
    zz = P.mid_cta_block(cfg)
    check("cta_colors の無い社は図の色（diagram_colors）で描く", ("#C2410C" in zz, "#F7E4D9" in zz), (True, True))
    bad = P.mid_cta_block({**cfg, "cta_colors": {"button": "red;background:url(x)"}})
    check("色でない値は使わない（style に入れる値を検める）", "url(x)" in bad, False)
    m = re.search(r'<div class="cta-mid"[^>]*>\s*<p[^>]*>(.*?)</p>\s*<a class="cta-button" href="([^"]+)"'
                  r'(?: data-cta="([^"]*)")?[^>]*>(.*?)</a>\s*(?:<p[^>]*>(.*?)</p>)?\s*</div>', sub, re.S)
    check("塊の形は変えない（external-md の社の .cta-inline への読み替えが同じ形で読む）", bool(m), True)


# ── 6. 描き直しの指紋 ─────────────────────────────────────────

def test_lead_hub_does_not_trigger_rerender():
    import rerender_watch as R
    cfg = {"id": "zz", "type": "external-html", "cta": {"url": "/c"}, "lead_hub": True}
    check("lead_hub は描き方に関係しない（変えても描き直さない）",
          R.inputs(cfg) == R.inputs({**cfg, "lead_hub": False}), True)
    check("色の設定（cta_colors）は描き方に関係する", R.inputs(cfg) == R.inputs({**cfg, "cta_colors": {"button": "#000"}}),
          False)


# ── 7. お客様の行・ファイルは public に置かない ────────────────────────

def _client_markers():
    import sites as S
    out = []
    for sid, c in S.load_all().items():
        if S.is_client(sid):
            out += [sid, str(c.get("domain") or "")]
    return [m for m in out if m]


def test_public_logs_have_no_client_rows():
    import client_private as CP
    rows = [json.loads(x) for x in (ROOT / "automation" / "logs" / "auto_fix.jsonl").read_text(encoding="utf-8").splitlines()
            if x.strip()]
    bad = [r.get("slug") for r in rows if CP.is_private(CP.owner_of_slug(r.get("slug") or ""))]
    check("介入の台帳（automation/logs/auto_fix.jsonl）に、お客様の記事の行が無い", bad, [])
    marks = _client_markers()
    les = [json.loads(x) for x in (ROOT / "data" / "lessons.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    bad = [r.get("id") for r in les if any(CP.is_private(s) for s in r.get("sites") or [])
           or any(m.lower() in json.dumps(r, ensure_ascii=False).lower() for m in marks)]
    check("学びの台帳（data/lessons.jsonl）に、お客様の行・お客様の名前の入った行が無い", bad, [])
    for rel in ("data/pace_state.json", "data/yield_state.json", "data/key_queries.json", "data/kw_plan_added.json"):
        p = ROOT / rel
        d = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
        check(f"{rel} にお客様の社のキーが無い", sorted(k for k in d if CP.is_private(k)), [])


def test_split_logs_route_and_merge():
    import client_private as CP
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "articles").mkdir()
        (base / "articles" / "cx-a.md").write_text("---\ncategory: cxcat\n---\n", encoding="utf-8")
        (base / "articles" / "own-a.md").write_text("---\ncategory: owncat\n---\n", encoding="utf-8")
        owner = {"cxcat": "cx", "owncat": "own"}
        import sites as S
        with patched(CP, ROOT=base, clients=lambda: ["cx"], is_private=lambda s: s == "cx"), \
                patched(S, find_category_owner=lambda c: owner.get(c)):
            log = base / "automation" / "logs" / "auto_fix.jsonl"
            CP.append_jsonl(log, {"slug": "cx-a", "by": "t", "note": "15.0位・表示340回"})
            CP.append_jsonl(log, {"slug": "own-a", "by": "t"})
            CP.append_jsonl(log, {"slug": "(3記事)", "by": "t"})
            pub = log.read_text(encoding="utf-8")
            priv = CP.private_path("cx", "automation/logs/auto_fix.jsonl").is_file()
            merged = [json.loads(x)["slug"] for x in CP.read_lines(log)]
            other = base / "elsewhere.jsonl"
            CP.append_jsonl(other, {"slug": "cx-a"})
            other_has = "cx-a" in other.read_text(encoding="utf-8")
    check("台帳: お客様の記事の行は置き場へ、自社・集計の行は public へ（読むときは両方）。"
          "決まった台帳でないファイル（門の一時ファイル）はそのまま書く",
          ("cx-a" in pub, priv, sorted(merged), other_has), (False, True, ["(3記事)", "cx-a", "own-a"], True))


def test_writers_and_readers_use_the_split_log():
    """介入の台帳を書く・読むスクリプトが、お客様の行を置き場へ書き、読むときに合わせる"""
    writers = ["auto_improve", "auto_review", "auto_rewrite", "auto_merge", "cta_fill", "desc_fill", "exit_fix",
               "fact_cite", "i18n", "link_boost", "rewrite_rollback"]
    readers = ["auto_review", "auto_rewrite", "retire_stale", "rewrite_rollback", "effect_ab", "focus_report"]
    bad = []
    for n in writers:
        s = (ROOT / "scripts" / f"{n}.py").read_text(encoding="utf-8")
        if "append_jsonl(" not in s:
            bad.append(f"{n}: 書く")
    for n in readers:
        s = (ROOT / "scripts" / f"{n}.py").read_text(encoding="utf-8")
        if "read_lines(" not in s:
            bad.append(f"{n}: 読む")
    check("介入の台帳の読み書きは client_private を通す（お客様の行を public に書かない）", bad, [])
    import auto_rewrite as AR
    import client_private as CP
    import sites as S
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "articles").mkdir()
        (base / "articles" / "cx-a.md").write_text("---\ncategory: cxcat\n---\n", encoding="utf-8")
        log = base / "automation" / "logs" / "auto_fix.jsonl"
        with patched(CP, ROOT=base, clients=lambda: ["cx"], is_private=lambda s: s == "cx"), \
                patched(S, find_category_owner=lambda c: "cx" if c == "cxcat" else None), patched(AR, LOG=log):
            AR.note("cx-a", "title", True, "直しました（a → b）")
            CP.append_jsonl(log, {"at": date.today().isoformat() + " 10:00", "by": "auto_rewrite", "slug": "cx-a",
                                  "kind": "title", "ok": True, "before_title": "前の題", "after_title": "後の題"})
            pub = log.read_text(encoding="utf-8") if log.is_file() else ""
            recent = AR.recently_touched(7)
            locked = AR.title_locked("cx-a")
    check("書き直しの台帳: お客様の記事の行は public に書かず、「最近直した」「題の判定期間」はお客様の行も見る"
          "（見ないと同じ記事を毎週直し、28日の判定の途中で題を変える）",
          ("cx-a" in pub, "cx-a" in recent, bool(locked)), (False, True, True))


def test_lessons_keep_client_rows_private():
    import client_private as CP
    import lessons as L
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        src = base / "data" / "lessons.jsonl"
        with patched(CP, ROOT=base, clients=lambda: ["cx"], is_private=lambda s: s == "cx",
                     markers=lambda: {"cx": ["cx", "cx.test", "CXパートナーズ"]}), patched(L, SRC=src):
            L.add("failure", "kw", "お客様専用の決まり", "表示340回", sites=["cx"])
            L.add("failure", "kw", "全体の決まり", "CXパートナーズ（cx.test）の補充語が外れた", sites=[])
            pub = src.read_text(encoding="utf-8")
            rows = L.load()
            priv = CP.private_path("cx", "data/lessons.jsonl").is_file()
    check("学び: お客様の社の行は置き場へ。全体の行は残し、お客様の名前・ドメインを伏せる",
          ("お客様専用" in pub, "CXパートナーズ" in pub, "cx.test" in pub, priv,
           sorted(r["rule"] for r in rows)),
          (False, False, False, True, ["お客様専用の決まり", "全体の決まり"]))


def test_site_keyed_records_keep_client_keys_private():
    import client_private as CP
    import pace
    import content_yield as CY
    import key_queries as KQ
    import kw_plan as KP
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "data").mkdir()
        with patched(CP, ROOT=base, clients=lambda: ["cx"], is_private=lambda s: s == "cx"), \
                patched(KQ, REG=base / "data" / "key_queries.json"), patched(KP, ADDED=base / "data" / "kw_plan_added.json"):
            KQ.save({"ai-lab": {"queries": []}, "cx": {"queries": [{"q": "お客様の語"}]}})
            KP.remember_added("cx", ["お客様の語"])
            KP.remember_added("ai-lab", ["自社の語"])
            pub_kq = (base / "data" / "key_queries.json").read_text(encoding="utf-8")
            got = KQ.load()
            pub_kp = (base / "data" / "kw_plan_added.json").read_text(encoding="utf-8")
            kp_ok = ("お客様の語" not in pub_kp, "自社の語" in pub_kp,
                     KP.norm("お客様の語") in KP.added_before("cx"))
    check("狙う語の記録: お客様の社の語は置き場へ（読むときは合わせる）",
          ("お客様の語" in pub_kq, sorted(got)), (False, ["ai-lab", "cx"]))
    check("積んだ語の記録（kw_plan_added）: お客様の社の語は置き場へ（読むときは合わせる）", kp_ok, (True, True, True))
    for mod, attr in ((pace, "STATE"), (CY, "STATE")):
        s = (ROOT / "scripts" / f"{mod.__name__}.py").read_text(encoding="utf-8")
        check(f"{mod.__name__}: 社ごとの記録はお客様の分を置き場へ（client_private の save_dict / load_dict）",
              "CP.save_dict(" in s and "CP.load_dict(" in s, True)


def test_ai_answers_for_clients_are_private():
    import ai_cite_check as AC
    import client_private as CP
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        with patched(CP, ROOT=base, clients=lambda: ["cx"], is_private=lambda s: s == "cx"), \
                patched(AC, CACHE_DIR=base / "data" / "ai_cache"):
            calls = []
            fn = AC._cached("Gemini", lambda q: calls.append(q) or ["https://a.test/"], site="cx")
            fn("お客様の語")
            pub = list((base / "data" / "ai_cache").rglob("*.json")) if (base / "data" / "ai_cache").is_dir() else []
            priv = list((base / "data" / "clients" / "cx" / "private" / "data" / "ai_cache").rglob("*.json"))
            fn("お客様の語")
            own = AC._cached("Gemini", lambda q: calls.append(q) or [], site="ai-lab")
            own("自社の語")
            pub2 = list((base / "data" / "ai_cache").rglob("*.json"))
    check("AIの答え: お客様の社の質問は置き場へ（2回目はそこから読む）・自社は今までどおり",
          (len(pub), len(priv), calls, len(pub2)), (0, 1, ["お客様の語", "自社の語"], 1))
    src = {n: (ROOT / "scripts" / f"{n}.py").read_text(encoding="utf-8")
           for n in ("ai_kw_research", "compete", "cooccur", "ai_followup")}
    check("AIに聞く工程は、どの社の質問かを渡す（engines_available(site=…)）",
          sorted(n for n, s in src.items() if "engines_available(site=" not in s), [])


# ── 8. 持ち越しの保存で、並行のジョブの更新を消さない ─────────────────────

def test_saving_does_not_drop_other_jobs_updates():
    """月次（直列のグループの外）と週次・記事の枠が同じ写しから始めて別々に残すと、後から残した方が先の方の更新を消した。
    残す直前に一番新しい写しを重ね、このジョブで変えたファイルだけを戻す（.jsonl は両方の行を残す）"""
    import os
    import client_private as CP
    for name in ("mark_before", "mark_after", "stash", "unstash"):
        if not callable(getattr(CP, name, None)):
            check("持ち越し: 残す前に最新の写しへ重ねる関数がある（client_private." + name + "）", False, True)
            return
    with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as tmp:
        base = Path(td)
        priv = base / "data" / "clients" / "cx" / "private"
        old = os.environ.get("RUNNER_TEMP")
        os.environ["RUNNER_TEMP"] = tmp

        def put(files):
            for rel, text in files.items():
                (priv / rel).parent.mkdir(parents=True, exist_ok=True)
                (priv / rel).write_text(text, encoding="utf-8")
        try:
            with patched(CP, ROOT=base):
                CP.mark_before()                                   # 1回目に戻す前（置き場は空）
                put({"targets.json": "S0", "log.jsonl": "x\n"})       # 戻した写し S0
                CP.mark_after()
                put({"mine-early.json": "A"})                      # 2回目に戻す前に、このジョブが書いた
                CP.mark_before()
                put({"ai_kw.json": "K"})                            # 2回目に戻した写し（ai-kw）
                CP.mark_after()
                put({"log.jsonl": "x\na1\n", "new.json": "N"})       # このジョブの直し
                n = CP.stash()
                put({"targets.json": "S1", "log.jsonl": "x\nb1\n"})  # その間に別のジョブ（月次）が残した最新の写し
                CP.unstash()
                got = {p.name: p.read_text(encoding="utf-8") for p in priv.rglob("*") if p.is_file()}
        finally:
            if old is None:
                os.environ.pop("RUNNER_TEMP", None)
            else:
                os.environ["RUNNER_TEMP"] = old
    check("持ち越し: このジョブで変えたファイルだけを最新の写しに重ねる（別のジョブの目標を消さず、台帳は両方の行）",
          (n, got.get("targets.json"), got.get("log.jsonl"), got.get("new.json"), got.get("mine-early.json"),
           got.get("ai_kw.json")),
          (3, "S1", "x\nb1\na1\n", "N", "A", "K"))
    check("学びの台帳（id のある行）は同じ id ならこのジョブの行を残す",
          CP.merge_jsonl('{"id": "L1", "hits": 1}\n{"id": "L2"}\n', '{"id": "L1", "hits": 2}\n'),
          '{"id": "L1", "hits": 2}\n{"id": "L2"}\n')


def _wf(name):
    import yaml
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


def test_client_private_is_merged_and_saved_by_writers():
    import yaml
    act = yaml.safe_load((ROOT / ".github" / "actions" / "client-private" / "action.yml").read_text(encoding="utf-8"))
    st = act["runs"]["steps"]
    run = [str(s.get("run", "")) + str(s.get("uses", "")) for s in st]

    def at(text):
        return next((i for i, r in enumerate(run) if text in r), None)
    order = [at("--mark-before"), at("cache/restore"), at("--mark-after"), at("--stash"),
             next((i for i, s in enumerate(st) if "cache/restore" in str(s.get("uses")) and "save" in str(s.get("if"))), None),
             at("--unstash"), at("cache/save")]
    check("持ち越し（action）: 戻す前後に中身を覚え、残す前に退避→最新の写しを戻す→このジョブの分を重ねる→残す",
          None not in order and order == sorted(order), True)
    merge = [s for s in st if "cache/restore" in str(s.get("uses")) and "save" in str(s.get("if"))]
    check("持ち越し（action）: 最新の写しへ重ねるのは private の系統だけ（並行ジョブの ai-kw・index は今までどおり）",
          bool(merge) and all("inputs.family == 'private'" in str(s.get("if")) for s in merge), True)
    pm = _wf("pipeline-multi.yml")["jobs"]
    sel = pm["select"]["steps"]
    i_r = next((i for i, s in enumerate(sel) if s.get("uses") == "./.github/actions/client-private"), None)
    i_s = next((i for i, s in enumerate(sel) if "対象サイトの判定" in str(s.get("name"))), None)
    check("記事の枠: 1日の本数（pace の判定）を読む前に、お客様の置き場を戻す",
          i_r is not None and i_s is not None and i_r < i_s, True)
    wr = pm["write"]["steps"]
    saves = [i for i, s in enumerate(wr) if s.get("uses") == "./.github/actions/client-private"
             and (s.get("with") or {}).get("mode") == "save"]
    last_write = max(i for i, s in enumerate(wr) if "link_boost.py" in str(s.get("run", "")))
    check("記事の枠: お客様の記事に当てた直しの台帳・学びを、書いた後に（落ちても）残す",
          bool(saves) and saves[-1] > last_write and str(wr[saves[-1]].get("if", "")).startswith("always()"), True)
