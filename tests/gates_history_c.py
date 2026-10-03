# -*- coding: utf-8 -*-
"""過去の誤り（分析・レポート・検出器・書き換えの検算）を、機械が止める門にしたもの。

どの門も「壊れた例を確かに捕まえる」と「正しい例を捕まえない」の両方を確かめてから、
今のコード・データに当てる（CLAUDE.md 0.1: 検出器は見つかるはずの例で試す）。
ネットワーク・課金APIは使わない。取得は全部スタブに差し替える。
"""
import contextlib
import hashlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def _ledger_hashes():
    """門が読むだけのはずの台帳。読み込みの時点（どの門も走る前）に指紋を取る"""
    files = [ROOT / "data" / "lessons.jsonl", ROOT / "automation" / "logs" / "auto_fix.jsonl"]
    files += sorted((ROOT / "data").glob("*.jsonl"))
    return {p.relative_to(ROOT).as_posix(): hashlib.sha1(p.read_bytes()).hexdigest()
            for p in dict.fromkeys(files) if p.is_file()}


_START = _ledger_hashes()


@contextlib.contextmanager
def _patched(*triples):
    """(対象, 属性名, 差し替える値) を一時的に差し替え、必ず戻す"""
    saved = [(o, n, getattr(o, n)) for o, n, _ in triples]
    try:
        for o, n, v in triples:
            setattr(o, n, v)
        yield
    finally:
        for o, n, v in saved:
            setattr(o, n, v)


def _run(fn, *a, argv=None, **k):
    """標準出力を拾って (戻り値, 出力) を返す。SystemExit も戻り値として扱う"""
    buf, old = io.StringIO(), sys.argv
    if argv is not None:
        sys.argv = argv
    try:
        with contextlib.redirect_stdout(buf):
            try:
                rv = fn(*a, **k)
            except SystemExit as e:
                rv = e.code
    finally:
        sys.argv = old
    return rv, buf.getvalue()


def _boom(*a, **k):
    raise RuntimeError("HttpError 503（門の試験で注入した取得失敗）")


def _warn(label, rows):
    if rows:
        print(f"  WARN  {label}（{len(rows)}件）: " + " / ".join(str(r) for r in rows[:4]))


# ── 0. 取れなかった検査が「問題なし・0」と出さない ─────────────
def test_hist_failed_checks_never_report_clean():
    """GSC・GA4・台帳が取れなかったとき、*_OK=yes・0件・食い違いなし・-100% を出さない。

    2026-08-21〜10-03 に同じ形の誤りを6回出した（取得失敗を0として「表示ゼロ」「食い合いなし」
    「-100%」、照合が動かないのを「食い違いなし」、403 を「消えた」、被リンク未計測を0固定）。
    """
    print("\n■ 取れなかった検査を「問題なし」と出さない（履歴c-0）")
    import gsc_detail
    import measure
    import growth_guard as GG

    with _patched((gsc_detail, "client", lambda: object()), (gsc_detail, "q", _boom),
                  (measure, "gsc_totals", _boom)):
        _, out = _run(GG.main, argv=["growth_guard.py"])
    check("growth_guard: GSCが落ちた週に「下落なし」と出さない", "GROWTH_DROP=no" in out, False)
    check("growth_guard: GSCが落ちた週に -100% と出さない", "-100%" in out, False)
    check("growth_guard: 確かめられなかったと印を出す", "GROWTH_DROP=unknown" in out, True)
    with _patched((gsc_detail, "client", lambda: object()), (gsc_detail, "q", lambda *a, **k: []),
                  (measure, "gsc_totals", lambda *a, **k: (100, 10))):
        _, out = _run(GG.main, argv=["growth_guard.py"])
    check("growth_guard: 取れて変化が無い週は「下落なし」", "GROWTH_DROP=no" in out, True)

    import collections
    import lead_reconcile as LR
    import sites as S
    eligible = [s for s, c in S.load_all().items() if c.get("ga4_property_id") and c.get("lead_hub") is not False]
    if eligible:
        empty = lambda start: collections.defaultdict(collections.Counter)
        with _patched((LR, "ledger_by_site", empty), (LR, "ga4_by_day", _boom)):
            rc, out = _run(LR.main, argv=["lead_reconcile.py"])
        check("lead_reconcile: GA4が読めない日に「食い違いなし」と出さない", "LEADS_OK=yes" in out, False)
        check("lead_reconcile: 照合できなかったら終了コード1（検査が動かなかった）", rc, 1)
        with _patched((LR, "ledger_by_site", empty), (LR, "ga4_by_day", lambda *a: {})):
            rc, out = _run(LR.main, argv=["lead_reconcile.py"])
        check("lead_reconcile: 読めて送信が無い日は LEADS_OK=yes", ("LEADS_OK=yes" in out, rc), (True, 0))

    import data_sanity as DS
    with _patched((DS, "ga", _boom)):
        _, out = _run(DS.main, argv=["data_sanity.py"])
    check("data_sanity: GA4が落ちたら SANITY_OK=yes と出さない", "SANITY_OK=yes" in out, False)

    class _V:
        def __init__(self, v):
            self.value = v

    class _Row:
        def __init__(self, dims, met):
            self.dimension_values = [_V(d) for d in dims]
            self.metric_values = [_V(str(met))]

    def fake_ga(prop, dims, mets, days=28, filt=None):
        if dims == ["eventName"]:
            return [_Row(["page_view"], 100)]
        if dims == ["sessionSourceMedium", "country"]:
            return [_Row(["google / organic", "Japan"], 50)]
        return [_Row(["google / organic"], 50)]
    with _patched((DS, "ga", fake_ga), (gsc_detail, "client", lambda: object()),
                  (gsc_detail, "q", _boom), (measure, "gsc_totals", _boom)):
        _, out = _run(DS.main, argv=["data_sanity.py"])
    check("data_sanity: GSCだけ落ちても「崩れなし」と出さない",
          ("SANITY_OK=yes" in out, "確かめられず" in out), (False, True))

    import gcreds
    import kw_guard as KG
    kw = "門の試験用の存在しない語 zqx"
    with _patched((gcreds, "load", _boom)):
        lv, reasons = KG.judge(kw, "ai-lab", use_gsc=True)
    check("kw_guard: GSCが落ちた日に「着手可」（0）を返さない", lv >= 1, True)
    check("kw_guard: 照合できなかった理由を出す", any(r[0] == "要確認" for r in reasons), True)
    lv0, _ = KG.judge(kw, "ai-lab", use_gsc=False)
    check("kw_guard: --no-gsc を明示したときは照合なしで判定する", lv0, 0)

    import findings as FD
    check("findings: *_OK=unknown を「問題なし」に数えない", FD.judge("CWV_OK=unknown（…）", 0), "動かせず")
    check("findings: *_OK=yes は問題なし", FD.judge("SANITY_OK=yes", 0), "問題なし")

    import mentions as MN
    d = {"items": [{"url": "https://a.example/403", "where": "a"}, {"url": "https://b.example/404", "where": "b"},
                   {"url": "https://c.example/ok", "where": "c"}]}
    resp = {"https://a.example/403": (403, ""), "https://b.example/404": (404, ""),
            "https://c.example/ok": (200, "<p>セブンセンシズ株式会社</p>")}
    with _patched((MN, "fetch", lambda u: resp[u])):
        (alive, gone, unknown), _ = _run(MN.check, d)
    check("mentions: 403 を「消えた」と数えない（確かめられない）",
          ([i["url"][8:9] for i in alive], [i["url"][8:9] for i in gone], [i["url"][8:9] for i in unknown]),
          (["c"], ["b"], ["a"]))

    import aio_score as AS
    arts = [({"title": "x"}, "本文")]
    check("aio_score: 被リンク未計測を0件と書かない",
          any("未計測" in x for x in AS.trust_score(arts, None)[1]), True)
    check("aio_score: 実測0件は0件と書く", any("0件" in x for x in AS.trust_score(arts, 0)[1]), True)

    import daily_audit as DA
    import hub_client as HC
    with _patched((HC, "enabled", lambda: True), (HC, "all_kw", _boom)):
        _, out = _run(DA.check_supply, [])
    check("daily_audit: 台帳が読めない日に「在庫0件」と出さない",
          ("判定できません" in out, bool(re.search(r"未着手\s+0件", out))), (True, False))

    # 台帳の非 strict 読み。失敗を空で返すため、件数・書き込みの判断に使うと「0本」「未記録」に化ける
    pat = re.compile(r"\ball_kw\(\s*\)")
    check("検出器: 非 strict の all_kw() を見つける", bool(pat.search("rows = hub_client.all_kw()")), True)
    check("検出器: strict=True は見逃す側に入れない", bool(pat.search("HC.all_kw(strict=True)")), False)
    must_strict = ("publish_flow.py", "report_actions.py", "daily_audit.py", "cannibal_check.py", "kw_plan.py")
    for name in must_strict:
        src = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        check(f"{name}: 書き込み・件数の判断に使う台帳は strict で読む", bool(pat.search(src)), False)
    display = {"hub_client.py", "hub_sheets.py", "weekly_report.py", "season.py", "kw_reorder.py"}
    loose = [p.name for p in sorted((ROOT / "scripts").glob("*.py"))
             if p.name not in display and p.name not in must_strict
             and pat.search(p.read_text(encoding="utf-8", errors="ignore"))]
    _warn("台帳を非 strict で読み、失敗が0件に化けうる（表示の扱いを確かめて strict にする）", loose)


# ── 4. 書き換えの検算が、正しい書き換えを差し戻さない ─────────────
def test_hist_rewrite_check_passes_legit_rewrites():
    """2026-09-23〜28 に5種類、正しい書き換えを差し戻して記事が永久に直せなくなった"""
    print("\n■ 書き換えの検算: 通すべき書き換えを通す（履歴c-4）")
    import auto_rewrite as AR
    check("通すべき書き換え（桁区切り・同じ事実の2回目・個数・英語表記・AI-OCR・助詞違い）を全部通す",
          AR.false_alarms(), [])
    base = "title: 時給1,500円の経理代行\n本文。3つの手順。\n"
    check("無かった数字は止める", AR.new_fact_numbers(base, base + "前年比12.7%増です。\n"), {"12.7%": 1})
    check("無かった桁区切りの数字は止める", bool(AR.new_fact_numbers(base, base + "相場は2,800円。\n")), True)
    check("見出しに語が無ければ止める", AR.heads_cover_terms(["集客の基本"], ["tool"]), False)
    check("狙う語を扱わない題は止める", AR.title_covers_kw("美容室の集客方法", "中小企業助成金"), False)
    src = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    sel = src[src.index("def selftest("):]
    check("selftest が通すべき書き換えも試す（落ちたら書き換えを飛ばす）", "false_alarms()" in sel[:1500], True)
    chk = src[src.index("def check("):src.index("def site_of(")]
    check("check() が検算の部品（数字・見出し）を使う",
          "new_fact_numbers(" in chk and "heads_cover_terms(" in chk, True)


# ── 12. GA4 のイベント名・管制塔へ送る種別 ─────────────────
EVENT_OK = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")


def _event_names(js):
    """(リテラルの名前, 連結の (接頭辞, 式)) を返す"""
    lit = re.findall(r"""\b(?:ga|gtag\(\s*['"]event['"]\s*,)\s*\(?\s*['"]([^'"]+)['"]\s*[,)]""", js)
    cat = re.findall(r"""\bga\(\s*['"]([^'"]+)['"]\s*\+\s*([A-Za-z_$][\w$]*(?:\()?)""", js)
    return lit, cat


def _unsafe_concat(js):
    """記号を英数字と _ に揃えずに名前へ連結している箇所"""
    _, cat = _event_names(js)
    bad = []
    for prefix, expr in cat:
        if not EVENT_OK.match(prefix):
            bad.append(prefix + expr)
        elif expr == "slugId(":
            continue
        elif re.search(rf"\b(?:var\s+)?{re.escape(expr)}\s*=\s*slugId\(", js):
            continue
        elif expr in ("v", "abv") and "v = Math.random() < 0.5 ? 'a' : 'b'" in js:
            continue                     # A/B の印は site.js が 'a' / 'b' だけを入れる
        elif expr == "route" and re.search(r"route = [^;]*\? 'dl' : 'form'", js):
            continue
        else:
            bad.append(prefix + expr)
    return bad


def test_hist_ga4_event_names_and_lead_payload():
    """2026-09-25: ハイフン入りの区画名で section_view が記録されず、
    フォームが site/type を送らず管制塔で弾かれ台帳に入らなかった"""
    print("\n■ GA4 のイベント名と、管制塔へ送る種別（履歴c-12）")
    bad_js = "ga('form-start', {}); var raw = el.id; ga('section_view_' + raw, {});"
    lit, _ = _event_names(bad_js)
    check("検出器: ハイフン入りの名前を見つける", [n for n in lit if not EVENT_OK.match(n)], ["form-start"])
    check("検出器: 揃えずに連結した名前を見つける", _unsafe_concat(bad_js), ["section_view_raw"])
    good_js = "var id = slugId(x); ga('section_view_' + id, {}); ga('cta_' + slugId(y), {}); ga('form_submit', {});"
    check("検出器: 揃えた名前は通す", ([n for n in _event_names(good_js)[0] if not EVENT_OK.match(n)],
                                     _unsafe_concat(good_js)), ([], []))

    bad_lit, bad_cat = [], []
    files = sorted((ROOT / "site" / "js").glob("*.js")) + sorted((ROOT / "templates").glob("*.html"))
    for p in files:
        t = p.read_text(encoding="utf-8", errors="ignore")
        lit, _ = _event_names(t)
        bad_lit += [f"{p.name}:{n}" for n in lit if not EVENT_OK.match(n)]
        bad_cat += [f"{p.name}:{x}" for x in _unsafe_concat(t)]
    check("GA4: 送るイベント名は英数字と _ だけ", bad_lit, [])
    check("GA4: 連結した名前は slugId などで揃えてある", bad_cat, [])

    # 管制塔へ送る受付は site と type を必ず持つ（無いと contact 扱いで本文必須になり弾かれる）
    def payload_missing(t):
        out = []
        for m in re.finditer(r"JSON\.stringify\(\{[^)]*?GAS_SHARED_SECRET[^)]*?\bdata:\s*([A-Za-z_]\w*|\{[^}]*\})",
                             t, re.S):
            d = m.group(1)
            if d.startswith("{"):
                body = d
            else:
                dm = re.search(rf"const {d} = \{{([^;]*)\}};", t, re.S)
                body = dm.group(1) if dm else ""
            if not (re.search(r"\bsite\s*:", body) and re.search(r"\btype\b", body)):
                out.append(d[:20])
        return out
    check("検出器: site/type の無い送信を見つける",
          (payload_missing('JSON.stringify({ secret: env.GAS_SHARED_SECRET || "", data: { ...data } })'),
           payload_missing('JSON.stringify({ secret: env.GAS_SHARED_SECRET, data: { ...d, site: "x", type } })')),
          (["{ ...data }"], []))
    miss = [f"{p.name}:{x}" for p in sorted((ROOT / "functions" / "api").glob("*.js"))
            for x in payload_missing(p.read_text(encoding="utf-8"))]
    check("管制塔へ送る受付が site と type を付けている", miss, [])
    # /api/lead へ送るフォームは種別（form_type）を持つ。type はここから決まる
    nofields = []
    for p in (ROOT / "site").rglob("*.html"):
        t = p.read_text(encoding="utf-8", errors="ignore")
        if "/api/lead" not in t:
            continue
        for m in re.finditer(r'<form\b[^>]*action="/api/lead"[^>]*>(.*?)</form>', t, re.S):
            if 'name="form_type"' not in m.group(1):
                nofields.append(p.relative_to(ROOT).as_posix())
    check("問い合わせフォームが form_type を送る", nofields, [])


# ── 14. 判定期間中にタイトルを変え直さない ─────────────────
def test_hist_title_not_changed_within_rollback_window():
    """09-25 に auto_rewrite が変えた seikyusho-shougou-jidoka の題を 09-27 に変え直し、
    rewrite_rollback の判定（28日）ができなくなった"""
    print("\n■ 判定期間中のタイトル変更（履歴c-14）")
    import auto_rewrite as AR
    from datetime import date
    rows = [
        {"at": "2026-09-25 10:00", "slug": "a", "kind": "title", "ok": True,
         "before_title": "旧", "after_title": "新", "note": "直しました"},
        {"at": "2026-09-25 10:00", "slug": "b", "kind": "aio", "ok": True,
         "before_title": "同じ", "after_title": "同じ", "note": "直しました"},
        {"at": "2026-09-25 10:00", "slug": "c", "kind": "title", "ok": False,
         "before_title": "旧", "after_title": "新", "note": "差し戻し"},
        {"at": "2026-08-01 10:00", "slug": "d", "kind": "title", "ok": True,
         "before_title": "旧", "after_title": "新", "note": "直しました"},
    ]
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "log.jsonl"
        f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        today = date(2026, 9, 27)
        got = {s: AR.title_locked(s, today, f) for s in "abcd"}
    check("題を変えて28日以内は変え直させない", got["a"], "2026-09-25")
    check("題が変わっていない直しは縛らない", got["b"], "")
    check("差し戻した直しは縛らない", got["c"], "")
    check("28日を過ぎたら変えてよい", got["d"], "")
    src = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    run = src[src.index("def run_one("):src.index("def selftest(")]
    check("auto_rewrite: 書き換えの前後で判定期間を確かめる", run.count("title_locked(") >= 2, True)
    # 今の台帳で、28日以内に同じ記事の題を2回変えた組
    ch = sorted(AR.title_changes())
    pairs = []
    for i, (s, at) in enumerate(ch):
        for s2, at2 in ch[i + 1:]:
            if s2 == s and at2 != at and (date.fromisoformat(at2) - date.fromisoformat(at)).days < AR.TITLE_LOCK_DAYS:
                pairs.append(f"{s}:{at}→{at2}")
    _warn("判定期間中に題を2回変えた記録", pairs)


# ── 15. 検出器の癖で「無い」と誤報しない ─────────────────
def test_hist_detectors_do_not_misread_markup():
    """2026-09-19〜20: async の位置・CTAのクラス名・原稿と生成HTML・タグの消し方で「無い」と誤報した"""
    print("\n■ 検出器: 書き方の違いで「無い」と読まない（履歴c-15）")
    import speed_fix as SF
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "a.html").write_text('<script async src="https://www.googletagmanager.com/gtag/js?id=G-X"></script>',
                                     encoding="utf-8")
        (base / "b.html").write_text('<script src="https://www.googletagmanager.com/gtag/js?id=G-X" async></script>',
                                     encoding="utf-8")
        (base / "c.html").write_text("<script>window.addEventListener('load',function(){var s=document.createElement"
                                     "('script');s.async=true;s.src='https://www.googletagmanager.com/gtag/js?id=G-X';"
                                     "document.head.appendChild(s);});</script>", encoding="utf-8")
        got = sorted(p.name for p, _ in SF.leftovers(base))
    check("speed_fix: 属性の順に関係なく先読みの計測タグを見つけ、遅らせた読み込みは通す",
          got, ["a.html", "b.html"])

    # CTA は cta-button で数える。数える側が知らないクラスで導線を書くと「CTAゼロ」と誤報する
    lead = r"/lp/|/contact|/diagnosis/|/tools/|/site-audit/"

    def unknown_cta_classes(text):
        out = set()
        for m in re.finditer(r'<a\b([^>]*)>', text):
            a = m.group(1)
            if re.search(rf'href="[^"]*(?:{lead})', a):
                c = re.search(r'class="([^"]+)"', a)
                if c and "cta-button" not in c.group(1).split():
                    out.add(c.group(1))
        return out
    check("検出器: 数えられない名前のCTAを見つける",
          unknown_cta_classes('<a class="cta-mid" href="/lp/">診断</a>'), {"cta-mid"})
    check("検出器: cta-button は数えられる側", unknown_cta_classes('<a class="cta-button" href="/lp/">x</a>'), set())
    seen = set()
    for p in (ROOT / "articles").glob("*.md"):
        seen |= unknown_cta_classes(p.read_text(encoding="utf-8", errors="ignore"))
    check("原稿の導線はすべて CTA の数え方（cta-button）に入る", sorted(seen), [])

    # 導線の有無は生成HTMLで見る（原稿に無くてもテンプレートが入れる。191本と誤報した）
    lead_re = re.compile(r"/diagnosis/|/tools/|/site-audit/|#diagnosis|/contact|/lp/")
    md_missing, html_missing, n = 0, [], 0
    for p in sorted((ROOT / "articles").glob("*.md")):
        t = p.read_text(encoding="utf-8-sig", errors="ignore")
        fm = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
        if not fm:
            continue
        cat = (re.search(r"^category:\s*(\S+)", fm.group(1), re.M) or [0, ""])[1]
        slug = (re.search(r"^slug:\s*(\S+)", fm.group(1), re.M) or [0, p.stem])[1].strip('"')
        h = ROOT / "site" / cat / slug / "index.html"
        if not h.is_file():
            continue
        n += 1
        md_missing += not lead_re.search(t)
        if not lead_re.search(h.read_text(encoding="utf-8", errors="ignore")):
            html_missing.append(slug)
    print(f"  --  公開ページ {n}本: 原稿で導線なしに見える {md_missing}本 / 生成HTMLで導線なし {len(html_missing)}本")
    check("生成HTMLで導線の無い記事", html_missing[:5], [])

    # 見出しの文字はタグを「除いて」取る。空白に置き換えると文がばらばらに見える
    def h1_extractors_replacing_with_space(src):
        bad = []
        lines = src.splitlines()
        for i, ln in enumerate(lines):
            if re.search(r"<h1\[\^>\]\*>\(\.\*\?\)</h1>", ln):
                near = "\n".join(lines[i:i + 3])
                if re.search(r"""re\.sub\(r?["']<\[\^>\]\+>["'],\s*["'] ["']""", near):
                    bad.append(i + 1)
        return bad
    bad_src = 'm = re.search(r"<h1[^>]*>(.*?)</h1>", h)\nt = re.sub(r"<[^>]+>", " ", m.group(1))\n'
    good_src = 'm = re.search(r"<h1[^>]*>(.*?)</h1>", h)\nt = re.sub(r"<[^>]+>", "", m.group(1))\n'
    check("検出器: タグを空白に置き換える見出し抽出を見つける",
          (h1_extractors_replacing_with_space(bad_src), h1_extractors_replacing_with_space(good_src)), ([2 - 1], []))
    offenders = [f"{p.name}:{n}" for p in sorted((ROOT / "scripts").glob("*.py"))
                 for n in h1_extractors_replacing_with_space(p.read_text(encoding="utf-8", errors="ignore"))]
    check("見出し（H1）の文字をタグの除去で取っている", offenders, [])


# ── 16. 外部リンク検査の誤判定 ───────────────────────
def test_hist_external_link_judgement():
    """2026-09-29: Googleヘルプの機械向け404・LinkedIn の999・短縮URL・twitter→x・preconnect で
    生きている18本をリンク切れと報告した"""
    print("\n■ 外部リンク検査（履歴c-16）")
    import urllib.error
    import seo_audit as SA

    class _Resp:
        def __init__(self, status, final):
            self.status, self._final = status, final

        def geturl(self):
            return self._final

    def fake_urlopen(req, timeout=20):
        u = req.full_url
        ua = req.get_header("User-agent") or ""
        browser = "Chrome/" in ua
        table = {
            "https://support.google.com/x": (200, None) if browser else (404, None),
            "https://www.linkedin.com/in/x": (999, None),
            "https://dead.example.com/gone": (404, None),
            "https://twitter.com/x": (200, "https://x.com/x"),
            "https://maps.app.goo.gl/abc": (200, "https://www.google.com/maps/place/x"),
            "https://old.example.org/": (200, "https://fx-casino.example.net/"),
        }
        code, final = table[u]
        if code >= 400:
            raise urllib.error.HTTPError(u, code, "x", {}, None)
        return _Resp(code, final or u)

    pages = {"/p/": {"ext": {"https://support.google.com/x", "https://www.linkedin.com/in/x",
                             "https://dead.example.com/gone", "https://twitter.com/x",
                             "https://maps.app.goo.gl/abc", "https://old.example.org/"}}}
    with _patched((SA.urllib.request, "urlopen", fake_urlopen)):
        rows = SA.external(pages)
    flagged = sorted(r[3].split()[-1] if r[1] == "外部リンク切れ" else r[3].split(" → ")[0] for r in rows)
    check("外部リンク: 本当に切れたもの・乗っ取られた転送だけを挙げる",
          flagged, ["https://dead.example.com/gone", "https://old.example.org/"])
    facts = SA.page_facts('<html><head><link rel="preconnect" href="https://fonts.googleapis.com">'
                          '<title>t</title></head><body><a href="https://example.com/a">a</a></body></html>')
    check("外部リンク: preconnect は数えない", sorted(facts["ext"]), ["https://example.com/a"])


# ── 17. 社名・指名検索の検出器 ───────────────────────
def test_hist_brand_detectors():
    """表記ゆれの検出式が正規表記に一致して4,989件を誤検出した（brand_spelling）。
    指名検索の除外が大文字だけを見て小文字が残った（2026-08-26）"""
    print("\n■ 社名・指名検索の検出器（履歴c-17）")
    import brand_spelling as BS
    canon_text = "。".join(BS.CANON) + "。株式会社ではなくセブンセンシズ株式会社です。"
    check("brand_spelling: 正規表記だけの文に「ゆれ」を見つけない", BS.scan(canon_text), {})
    check("brand_spelling: 正規表記は直しで変わらない", BS.fix(canon_text), canon_text)
    for bad in ("セブン・センシズ", "セブンセンシズ（株）", "ＡＩ集客ラボ", "AI 集客ラボ"):
        check(f"brand_spelling: ゆれ「{bad}」を見つける", bool(BS.scan(f"本文{bad}です")), True)
        fixed = BS.fix(f"本文{bad}です")
        check(f"brand_spelling: 「{bad}」の直しは2回当てても同じ", BS.fix(fixed), fixed)

    import brand_search as BR
    import kw_discover as KD
    import report_verify as RV
    for q in ("セブンセンシズ 評判", "7SENSES", "原口優", "G-RAN 料金", "g-ran"):
        check(f"kw_discover: 指名検索「{q}」を大文字小文字に関係なく除く", KD.is_brand_query(q), True)
    check("kw_discover: 一般語は指名にしない", KD.is_brand_query("経理代行 費用"), False)
    core = ("セブンセンシズ", "7Senses", "AI集客ラボ", "ai集客ラボ")
    for q in core:
        check(f"brand_search: 「{q}」を指名と数える", bool(BR.BRAND.search(q)), True)
        check(f"report_verify: 「{q}」を指名と数える", any(n.lower() in q.lower() for n in RV.NAMED), True)
    gaps = [q for q in ("AI集客ラボ", "G-ran", "Seven Senses")
            if bool(BR.BRAND.search(q)) != KD.is_brand_query(q)
            or bool(BR.BRAND.search(q)) != any(n.lower() in q.lower() for n in RV.NAMED)]
    _warn("指名検索の判定が検出器ごとに食い違う語（brand_search / kw_discover / report_verify）", gaps)


# ── 24. 月次レポートの表示 ──────────────────────────
def test_hist_report_display():
    """「指名検索 +-12%」「約0円」・カテゴリがスラッグのまま・順位タイルが常に赤（2026-08〜09）"""
    print("\n■ 月次レポートの表示（履歴c-24）")
    plus = re.compile(r"""f(["'])[^"'\n]*\+\{[^}]*(?:pct|mom|rate|diff|/|-)[^}]*:[^}]*\.\d*f\}%""")
    check("検出器: 符号を手で付けた割合を見つける",
          (bool(plus.search('rate = f"+{(ti - pi) / pi * 100:.0f}%"')), bool(plus.search('rate = f"{d:+.0f}%"'))),
          (True, False))
    names = ("monthly_report.py", "group_report.py", "weekly_report.py", "report_digest.py", "data_report.py",
             "site_diagnosis.py", "structure_plan.py", "report_heat.py", "report_context.py")
    off = [f"{n}:{i + 1}" for n in names if (ROOT / "scripts" / n).is_file()
           for i, ln in enumerate((ROOT / "scripts" / n).read_text(encoding="utf-8").splitlines())
           if plus.search(ln)]
    check("レポートの前月比は書式の符号（:+）で出す（+- を出さない）", off, [])

    import monthly_report as M
    import sites as S
    names_map = M.cat_names()
    raw = [f"{sid}:{slug}" for sid, c in S.load_all().items() for slug in (c.get("categories") or {})
           if names_map.get(slug, slug) == slug]
    check("月次レポート: どの社のカテゴリも表示名で出す", raw, [])
    src = (ROOT / "scripts" / "monthly_report.py").read_text(encoding="utf-8")
    check("月次レポート: カテゴリの表示名を手書きの対応表で持たない", src.count("cat_jp = cat_names()"), 2)
    check("月次レポート: 順位タイルの色を符号でなく数字で決める", 'if key == "pos":' in src, True)
    check("月次レポート: AIクローラー到達を実測で出す（固定の 3/3 にしない）",
          '<div class="v">3/3</div>' in src, False)

    # 生成済みの最新版（系列ごとに最新の月）に壊れた表示が残っていないか
    latest = {}
    for p in sorted((ROOT / "reports").glob("*/report.html"), key=lambda x: x.parent.name):
        latest[re.sub(r"\d{4}-\d{2}", "", p.parent.name)] = p      # 系列ごとに最後（最新の月）が残る
    slugs = [s for c in S.load_all().values() for s in (c.get("categories") or {}) if "-" in s or s == "hojokin"]
    bad_sign, bad_cat = [], []
    for p in latest.values():
        vis = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", p.read_text(encoding="utf-8", errors="ignore"), flags=re.S)
        vis = re.sub(r"<[^>]+>", " ", vis)
        if "+-" in vis or "約0円" in vis:
            bad_sign.append(p.parent.name)
        hit = [s for s in slugs if re.search(rf"(?<![\w/.-]){re.escape(s)}(?![\w/.-])", vis)]
        if hit:
            bad_cat.append(f"{p.parent.name}:{','.join(hit)}")
    check("最新のレポートに「+-」「約0円」が無い", bad_sign, [])
    _warn("最新のレポートにカテゴリのスラッグが残る（作り直すと表示名になる）", bad_cat)


# ── 25. レポートの本数・期間 ─────────────────────────
def test_hist_report_counts_and_period():
    """「新規公開0本」・当月分の混入・取り下げを含めて「コーポレート12本」（実5本）・GSC終了日が今日"""
    print("\n■ レポートの本数と期間（履歴c-25）")
    import monthly_report as M
    check("month_end: 月末で締める", (M.month_end("2026-08"), M.month_end("2026-12"), M.month_end("2024-02")),
          ("2026-08-31", "2026-12-31", "2024-02-29"))
    today_pat = re.compile(r"""(?:["']endDate["']\s*:\s*|end_date\s*=\s*)(?:str\()?date\.today\(\)|end_date\s*=\s*["']today["']""")
    check("検出器: 終了日を今日にする書き方を見つける",
          (bool(today_pat.search('"endDate": str(date.today())')),
           bool(today_pat.search('"endDate": month_end(cur)'))), (True, False))
    off = [f"{n}:{i + 1}" for n in ("monthly_report.py", "group_report.py", "report_verify.py", "report_audit.py")
           for i, ln in enumerate((ROOT / "scripts" / n).read_text(encoding="utf-8").splitlines())
           if today_pat.search(ln)]
    check("レポートのGSC・GA4の終了日を「今日」にしない", off, [])

    import group_report as GR
    import external_index as EI
    import sites as S
    others = [s for s in S.load_all() if s != S.primary()]
    if others:
        sid = others[0]
        ledger = [{"site": sid, "status": "公開済み", "keyword": f"k{i}"} for i in range(12)]
        live = {"sites": {sid: [{"slug": f"s{i}"} for i in range(5)]}}
        with _patched((GR.hub_client, "all_kw", lambda *a, **k: ledger), (EI, "load", lambda *a, **k: live)):
            got, _ = _run(GR.article_stats)
        check("グループ: 公開本数は台帳の記録でなく公開中のページで数える（取り下げを含めない）",
              got["counts"].get(sid), 5)


# ── 26. 照合は、そのレポートの社のデータで行う ──────────────
def test_hist_report_sources_follow_site():
    """2026-09-25: corporate/subsidy の月次を AI集客ラボの数字で照合し、毎回照合NGで届かなかった"""
    print("\n■ 照合の取得先がその社のものか（履歴c-26）")
    import monthly_report as M
    import report_audit as RA
    import report_verify as RV
    import sites as S
    calls = []

    def fake_gsc(site, start, end, dims=None, limit=1):
        calls.append(("gsc", site, end))
        return {"rows": [{"impressions": 0, "clicks": 0, "position": 0}]} if not dims else {"rows": []}

    def fake_ga(prop, start, end):
        calls.append(("ga", str(prop), end))
        return {}
    wrong = []
    for sid, cfg in S.load_all().items():
        calls.clear()
        with _patched((M, "SITE_ID", sid), (RV, "_gsc", fake_gsc), (RV, "_ga_events", fake_ga),
                      (RA, "pdf_text", lambda p: ("", 1))):
            _run(RA.audit, "x.pdf", "2026-08")
            _run(RV.check, "2026-08")
        gsc = {c[1] for c in calls if c[0] == "gsc"}
        ga = {c[1] for c in calls if c[0] == "ga"}
        want_ga = {str(cfg["ga4_property_id"])} if cfg.get("ga4_property_id") else set()
        if gsc != {f"https://{cfg['domain']}/"} or ga != want_ga:
            wrong.append(f"{sid}: GSC {sorted(gsc)} / GA4 {sorted(ga)}")
        if {c[2] for c in calls} != {"2026-08-31"}:
            wrong.append(f"{sid}: 終了日 {sorted({c[2] for c in calls})}")
    check("照合・検算がその社の GSC・GA4・月末で取り直す", wrong, [])
    # 壊れた例: 全社を AI集客ラボのドメインで照合していたら、上の検査が捕まえるか
    lab = S.load(S.primary())["domain"]
    others = [c["domain"] for s, c in S.load_all().items() if s != S.primary()]
    check("検出器の前提: 他社のドメインは AI集客ラボと別", all(d != lab for d in others), True)
    for n in ("report_audit.py", "report_verify.py"):
        src = (ROOT / "scripts" / n).read_text(encoding="utf-8")
        check(f"{n}: 手で動かすときも --site で社を選べる", 'add_argument("--site")' in src, True)


# ── 27. 同じレポートを二重に送らない ─────────────────────
def test_hist_no_double_send():
    """09-14 に週次の送り直しで月次まで二重、10-01 に照合で止まった月の再送でグループ版を二重に送った"""
    print("\n■ レポートの二重送付（履歴c-27）")
    wf = (ROOT / ".github" / "workflows").glob("*.yml")
    texts = {p.name: p.read_text(encoding="utf-8") for p in wf}
    mon, heal = texts.get("monthly-report.yml", ""), texts.get("selfheal.yml", "")

    def missing_steps(heal_src, mon_src):
        names = set(re.findall(r'\.name == "([^"]+)"', heal_src))
        have = set(re.findall(r"^\s*- name:\s*(.+?)\s*$", mon_src, re.M))
        return sorted(names - have)
    check("検出器: 名前の変わった工程を見つける",
          missing_steps('select(.name == "旧い名前")', "      - name: 新しい名前\n"), ["旧い名前"])
    check("自動修復が見る工程名が月次のワークフローに実在する（変わると送り済みを見落として二重に送る）",
          missing_steps(heal, mon), [])
    def group_resend_unguarded(step):
        g = step.find("group_report.py --email")
        return g >= 0 and not (0 <= step.find("gsent") < g)
    check("検出器: 送り済みを確かめずにグループ版を出し直す形を見つける",
          (group_resend_unguarded("run: |\n  python scripts/group_report.py --email\n"),
           group_resend_unguarded('gsent=$(gh api x)\nif [ "$gsent" -gt 0 ]; then :; else\n'
                                  "  python scripts/group_report.py --email\nfi\n")), (True, False))
    i = heal.find("落ちたのが月次レポートなら発行し直す")
    step = heal[i:heal.find("- name:", i + 10)] if i >= 0 else ""
    check("自動修復: グループ版は元の run で送り済みなら出し直さない", group_resend_unguarded(step), False)
    grp = re.search(r"- name: グループ月次レポート生成・メール送付\s*\n\s*if: ([^\n]+)", mon)
    check("月次: 各社分だけの再送ではグループ版を送らない", bool(grp and "!inputs.resend_sites" in grp.group(1)), True)
    sr = (ROOT / "scripts" / "send_reports.py").read_text(encoding="utf-8")
    check("send_reports: 片方だけ送り直せる（--only）", '"--only"' in sr, True)


# ── 28. 門は台帳を書き換えない（最後に走る） ─────────────────
def test_hist_zz_gates_do_not_touch_ledgers():
    """2026-09-25: 門の検査が学びの台帳の hits を毎回+1して保存し、週次CIが水増しをコミットした"""
    print("\n■ 門は台帳を書き換えない（履歴c-28）")
    import lessons as L
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "lessons.jsonl"
        f.write_text(L.SRC.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        h0 = f.read_bytes()
        with _patched((L, "SRC", f)):
            L.brief("ai-lab", count=False)
            same = f.read_bytes() == h0
            L.brief("ai-lab", count=True)
            bumped = f.read_bytes() != h0
    check("lessons.brief(count=False) は台帳を書かない", same, True)
    check("検出器の前提: count=True は書く（上の検査が効いている）", bumped, True)
    call = re.compile(r"\b(?:L|LS|lessons)\.brief\((?![^)]*count=False)")
    check("検出器: count=False の無い呼び出しを見つける",
          (bool(call.search('L.brief("ai-lab")')), bool(call.search('L.brief("ai-lab", count=False)'))), (True, False))
    calls = [f"{p.name}:{n}" for p in sorted((ROOT / "tests").glob("*.py")) + [ROOT / "scripts" / "gate_selftest.py"]
             for n, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
             if call.search(ln) and p.name != "gates_history_c.py"]
    check("門から学びを読むときは count=False", calls, [])
    now = _ledger_hashes()
    changed = sorted(k for k in set(_START) | set(now) if _START.get(k) != now.get(k))
    # 門だけが書きうる台帳は止める。それ以外は手元で並行して動く工程（動画の聞き直し等）も書くため知らせるだけ
    strict = {"data/lessons.jsonl", "automation/logs/auto_fix.jsonl", "data/rakko_spend.jsonl"}
    check("ここまでの門の実行で学び・自動修正・ラッコ消費の台帳が変わっていない",
          [c for c in changed if c in strict], [])
    _warn("門の実行中に変わった台帳（並行して動いた工程か、門が書いたかを確かめる）",
          [c for c in changed if c not in strict])
