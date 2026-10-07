# -*- coding: utf-8 -*-
"""問い合わせの数え方と計測の不具合（2026-10-07 のリード導線の点検で判明）。

  1. ページを移って送るフォーム（AI集客ラボの /contact/・/lp/・/download/）では、site.js の form_submit と
     GA4 の拡張計測（フォームの操作）の form_submit が1回ずつ出る。/contact/ の 9/4・9/7・10/7 はどれも
     form_submit 2・lead_capture 1 で、問い合わせの数え方（その日の最大）は1回を2件と数えていた。
     数えるのは lead_capture / generate_lead だけにする（ファネルの「送信した」も同じ）
  2. 補助金は lead_hub: false で突き合わせから外れていた（本番の送り先は管制塔）。台帳にサイト名が
     「（不明）」で残った行は「メールにだけ届いた」とは言わず、サイト名を直すよう知らせる
  3. コーポレートの入口は ?s=backoffice（選択肢に無い）・?s=keiri-shindan（送信時に名前が付かない）で、
     /contact/ は /contact へ 308 で転送されていた。行き先を変えても日次の --write が2本目を足さない
  4. 補助金の記事138本の著者欄の「AI診断」の入口は、押されても計測されていなかった

ネットワーク・GA4・台帳には触れない（全部スタブ）。
"""
import collections
import contextlib
import io
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


@contextlib.contextmanager
def _patched(*triples):
    saved = [(o, n, getattr(o, n)) for o, n, _ in triples]
    try:
        for o, n, v in triples:
            setattr(o, n, v)
        yield
    finally:
        for o, n, v in saved:
            setattr(o, n, v)


def _out(fn, *a, argv=None):
    buf, old = io.StringIO(), sys.argv
    if argv is not None:
        sys.argv = argv
    try:
        with contextlib.redirect_stdout(buf):
            rv = fn(*a)
    finally:
        sys.argv = old
    return rv, buf.getvalue()


def _boom(*a, **k):
    raise RuntimeError("GA4 に届かない（スタブ）")


def test_one_inquiry_is_counted_once():
    import lead_reconcile as LR
    # AI集客ラボ /contact/ の実例（9/4・9/7・10/7 は同じ形）: form_submit は site.js と拡張計測が1回ずつ
    contact = [("20260904", "form_submit", "/contact/", 2), ("20260904", "lead_capture", "/contact/", 1),
               ("20260904", "lead_form", "/contact/", 1)]
    check("問い合わせ1回（form_submit 2・lead_capture 1）は1件", LR.count_rows(contact), {"2026-09-04": 1})
    corp = [("20261005", "form_submit", "/contact", 1), ("20261005", "generate_lead", "/contact", 1),
            ("20261005", "lead_capture", "/contact", 1)]
    check("コーポレートの1回（generate_lead と lead_capture が両方出る）も1件", LR.count_rows(corp),
          {"2026-10-05": 1})
    check("form_submit は問い合わせのページでも数えない", LR.is_lead("form_submit", "/contact/"), False)
    check("数えるのは lead_capture と generate_lead", sorted(LR.EVENTS), ["generate_lead", "lead_capture"])
    rc, out = _out(LR.selftest)
    check("lead_reconcile の自己テストが新しい数え方で通る", (rc, "LEAD_SELFTEST=ok" in out), (0, True))

    import funnel as FN
    names = dict(FN.STEPS)["送信した"]
    check("ファネルの「送信した」の代わりの数え方にも form_submit を入れない", "form_submit" in names, False)
    # 10/7 の形: site.js の form_submit（種類つき）と拡張計測の form_submit（種類なし）と lead_capture（種類つき）
    rows = [("20261007", "form_start", "お問い合わせ", "", "/contact/", 1),
            ("20261007", "form_submit", "お問い合わせ", "", "/contact/", 1),
            ("20261007", "form_submit", "(not set)", "", "/contact/", 1),
            ("20261007", "lead_capture", "お問い合わせ", "", "/contact/", 1)]
    m = FN.summarize_forms(rows)["202610"]
    check("フォームの項目別: 送信の合計も種類別も1件", (m["sent_total"], m["types"]["お問い合わせ"]["sent"]), (1, 1))

    # 送信の数が取れないときの代わり: lead_capture と generate_lead は足さずに多い方（form_submit は見ない）
    ev = {"page_view": 100, "cta_click": 10, "form_start": 5, "form_submit": 4, "lead_capture": 2, "generate_lead": 2}
    with _patched((FN, "events", lambda prop, days: ev), (LR, "ga4_by_day", _boom),
                  (FN, "lead_routes", lambda prop, days: {}), (FN, "print_inline", lambda conf: None)):
        _, out = _out(FN.main, argv=["funnel.py"])
    sent = re.findall(r"送信した\s+(\d+)", out)
    check("ファネル: 送信の数が取れない日の代わりも2倍にしない", bool(sent) and set(sent) == {"2"}, True)
    with _patched((FN, "events", lambda prop, days: ev), (LR, "ga4_by_day", lambda *a: {"2026-10-07": 1}),
                  (FN, "lead_routes", lambda prop, days: {}), (FN, "print_inline", lambda conf: None)):
        _, out = _out(FN.main, argv=["funnel.py"])
    sent = re.findall(r"送信した\s+(\d+)", out)
    check("ファネル: 送信した は lead_reconcile の数え方の件数", bool(sent) and set(sent) == {"1"}, True)


def test_subsidy_is_reconciled_and_unknown_rows_are_named():
    import lead_reconcile as LR
    import sites as S
    sub = S.load("subsidy")
    check("補助金も問い合わせの突き合わせに入る（lead_hub を false にしない）", sub.get("lead_hub") is not False, True)
    prop = str(sub.get("ga4_property_id"))

    def ledger(rows):
        d = collections.defaultdict(collections.Counter)
        for sid, day in rows:
            d[sid][day] += 1
        return lambda start: d

    ga = lambda p, s, e: {"2026-10-01": 1} if str(p) == prop else {}
    with _patched((LR, "ledger_by_site", ledger([("?", "2026-10-01")])), (LR, "ga4_by_day", ga),
                  (LR, "ACKED", {})):
        rc, out = _out(LR.main, argv=["lead_reconcile.py"])
    line = next((x for x in out.splitlines() if "要対応" in x and sub["name"] in x), "")
    check("補助金の送信が突き合わされる", bool(line), True)
    check("台帳にサイト名不明の行がある日は、その行を直すよう知らせる（メールを探させない）",
          ("サイト名を判定できない行が1行" in line, "メールにだけ届いた" in line), (True, False))
    check("食い違いがあれば LEADS_OK=no（終了コードは0）", ("LEADS_OK=no" in out, rc), (True, 0))
    with _patched((LR, "ledger_by_site", ledger([])), (LR, "ga4_by_day", ga), (LR, "ACKED", {})):
        _, out = _out(LR.main, argv=["lead_reconcile.py"])
    line = next((x for x in out.splitlines() if "要対応" in x and sub["name"] in x), "")
    check("不明の行も無ければ、従来どおりメールの受信箱を確かめるよう知らせる", "メールにだけ届いた" in line, True)
    with _patched((LR, "ledger_by_site", ledger([("subsidy", "2026-10-01")])), (LR, "ga4_by_day", ga),
                  (LR, "ACKED", {})):
        _, out = _out(LR.main, argv=["lead_reconcile.py"])
    check("台帳に補助金の行があれば食い違いにしない", ("LEADS_OK=yes" in out, sub["name"] in out), (True, True))


# コーポレートのフォームの「ご相談内容」で、送信時に名前が付く値（services.ts の slug と ContactForm.tsx の EXTRA）。
# 配信先の作業コピーがあればそこから読む（無い CI では 2026-10-07 時点の値）
CORP_CHOICES = {"keiri-bpo", "ai-subsidy", "meo", "aio", "ai-consulting", "web-production",
                "system-development", "rakushift", "aio-agent", "all", "other"}


def _corp_choices():
    src = ROOT / ".publish-work" / "corporate" / "src"
    svc, form = src / "lib" / "services.ts", src / "components" / "ContactForm.tsx"
    if not (svc.is_file() and form.is_file()):
        return CORP_CHOICES
    slugs = set(re.findall(r'^    slug: "([^"]+)"', svc.read_text(encoding="utf-8"), re.M))
    extra = re.search(r"const EXTRA[^=]*=\s*\{(.*?)\};", form.read_text(encoding="utf-8"), re.S)
    keys = set(re.findall(r'^\s*"?([a-z0-9-]+)"?\s*:', extra.group(1), re.M)) if extra else set()
    return (slugs | keys) or CORP_CHOICES


def test_corporate_entry_links_open_a_named_choice_without_redirect():
    import tool_links as TL
    choices = _corp_choices()
    corp = {k: v[0] for k, v in TL.OFFER.items() if "corp.7senses.co.jp" in v[0]}
    check("コーポレートの入口がある", sorted(corp), ["backoffice", "keiri-bpo", "keiri-jitsumu"])
    bad = {}
    for k, url in corp.items():
        u = urlparse(url)
        s = parse_qs(u.query).get("s", [""])[0]
        if u.path.endswith("/") or s not in choices:
            bad[k] = url
    check("入口は /contact（転送なし）で、?s= はフォームの選択肢のうち名前が付く値だけ", bad, {})

    old = "https://corp.7senses.co.jp/contact/?s=keiri-shindan"
    art = ("---\ntitle: テスト\ncategory: keiri-bpo\n---\n\n## 失敗しやすい点\n\n本文です。\n\n"
           "整理は、[経理の現状分析（無料）](" + old + ")からご相談いただけます。\n\n"
           '<div class="cta-box"><a class="cta-button" href="' + old + '">経理の現状分析（無料）</a></div>\n\n'
           "## まとめ\n\n本文です。\n")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "articles").mkdir()
        (root / "sites").mkdir()
        p = root / "articles" / "h52-test.md"
        p.write_bytes(art.encode("utf-8"))
        fresh = root / "articles" / "h52-fresh.md"
        fresh.write_bytes(art.replace("整理は、[経理の現状分析（無料）](" + old + ")からご相談いただけます。\n\n", "")
                          .replace('<div class="cta-box"><a class="cta-button" href="' + old
                                   + '">経理の現状分析（無料）</a></div>\n\n', "").encode("utf-8"))
        with _patched((TL, "ROOT", root)):
            _out(TL.main, True)
            check("以前の行き先が入った記事に、日次の --write が2本目を足さない", p.read_bytes().decode("utf-8"), art)
            check("入口の無い記事には今の行き先で1本入る",
                  fresh.read_text(encoding="utf-8").count("corp.7senses.co.jp/contact"), 1)
            relink = getattr(TL, "relink", None)
            if relink:
                _out(relink, True)
            got = p.read_bytes().decode("utf-8")
            check("--relink で以前の行き先を今の行き先へ（本文のリンクも cta-box の href も）",
                  (old in got, got.count(TL.OFFER["keiri-bpo"][0])), (False, 2))
            check("--relink は行き先だけを変える", got.replace(TL.OFFER["keiri-bpo"][0], old), art)
            if relink:
                _out(relink, True)
            check("--relink は何度当てても同じ", p.read_bytes().decode("utf-8"), got)


def test_subsidy_aicheck_entry_sends_cta_click():
    import subsidy_cta as C
    page = ('<html><body><div class="author"><div class="sv-links"><a href="/about/">プロフィール詳細</a>'
            + C.SUPERVISOR_END + "\n    </div></body></html>")
    out = C.apply(page)
    track = re.search(r'data-cta="subsidy_aicheck_blog"[^>]*>[^<]*</a>(<script>.*?</script>)</aside>', out, re.S)
    js = track.group(1) if track else ""
    check("著者欄の入口に、押されたら cta_click を送る計測が付く", '"cta_click"' in js, True)
    check("送る項目は記事ページの計測と同じ（cta_id は data-cta・link_url・page_path）",
          all(k in js for k in ('cta_id:a.getAttribute("data-cta")', 'link_url:a.getAttribute("href")',
                                "page_path:location.pathname")), True)
    v1 = getattr(C, "AICHECK_V1", "")
    old = page.replace(C.SUPERVISOR_END, C.SUPERVISOR_END + "\n      " + v1) if v1 else ""
    up = C.apply(old) if old else ""
    check("配信済みの記事（計測の無い版）は差し替わり、入口は1つのまま",
          (bool(v1) and v1 not in up, up.count('data-cta="subsidy_aicheck_blog"'), up.count('"cta_click"')), (True, 1, 1))
    check("何度当てても同じ", (C.apply(out) == out, C.apply(up) == up if up else False), (True, True))
