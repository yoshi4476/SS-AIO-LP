# -*- coding: utf-8 -*-
"""調査が引用・言及されやすくなる仕組みの門（2026-10-05）。

AI検索での見え方は被リンクより言及で決まる（YouTube 0.71・リンク無しの言及 0.66 ＞ 被リンク 0.22。CLAUDE.md 0.3節）。
調査ページのすべてに「この調査を引用する方へ」（そのまま貼れる出典・引用の条件・コピーのボタン）を置き、
業種別の調査とランキングには貼れる図を出す。図の数字は headline()・集計のまま（計算し直さない）。
Dataset は1ページに1つで、usageInfo（引用の条件）と creator を持つ。
毎月のお知らせの下書きは、集計に無い数字・一律の言い方があれば作らない。配信・送信はしない。
本物の配信先・SNS・メールには触れない（関数とソースだけを見る）。
"""
import importlib.util
import json
import re

from test_gates import check, ROOT


def _industries():
    import industry_ai_sources as IAS
    out = []
    for p in sorted((ROOT / "data" / "research").glob("*-summary.json")):
        ind = p.name[:-len("-summary.json")]
        if ind in IAS.QUESTIONS and IAS.headline(ind):
            out.append(ind)
    return out


def _subsidy_research():
    spec = importlib.util.spec_from_file_location("subsidy_research_h12", ROOT / "scripts" / "subsidy" / "research.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _cite_line(body):
    m = re.search(r'id="cite-line">([^<]*)<', body)
    return m.group(1) if m else ""


def test_every_research_page_has_a_citation_box_with_company_and_url():
    import ai_ranking as AR
    import industry_ai_sources as IAS
    import research_cite as RC
    print("\n■ 調査ページ: 引用する方への枠（社名・URL・条件・コピー）")
    inds = _industries()
    check("業種別の調査が1つ以上ある", bool(inds), True)
    for ind in inds:
        hl = IAS.headline(ind)
        _, _, body, _, _ = IAS.render(ind)
        line = _cite_line(body)
        check(f"{ind}: 出典の1行に社名とページのURL", ("セブンセンシズ株式会社" in line, hl["url"] in line), (True, True))
        check(f"{ind}: 引用の条件とコピーのボタン", (RC.TERMS in body, 'class="cite-copy"' in body), (True, True))
    if AR.months():
        _, _, rbody = AR.body()
        line = _cite_line(rbody)
        check("ランキング: 出典の1行に社名とURL", ("セブンセンシズ株式会社" in line, AR.PAGE_URL in line), (True, True))
    RS = _subsidy_research()
    d = {"url": "/research/x/", "domain": "https://example.test", "period": "2026-10-01", "engines": ["Gemini"],
         "rows": [], "split": 0, "answers": 0, "sources": {}, "public_pct": 0, "readout_html": "",
         "cite": {"line": RC.cite_line(RC.org_label("テスト"), "題", "2026-10-01", "https://example.test/research/x/")}}
    body = RS.html_body(d)
    check("AIに聞いた調査（3サイト共通）: 枠がある", ('id="cite"' in body, "セブンセンシズ株式会社" in _cite_line(body)), (True, True))
    tsx = (ROOT / "templates" / "corporate_research_page.tsx").read_text(encoding="utf-8")
    pub = (ROOT / "scripts" / "research_publish.py").read_text(encoding="utf-8")
    check("コーポレート: ページが cite を描き、配信が cite と CiteCopy を置く",
          ("d.cite.line" in tsx, '"cite")}' in pub, "corporate_cite_copy.tsx" in pub), (True, True, True))


def test_chart_numbers_are_the_headline_numbers():
    import ai_ranking as AR
    import industry_ai_sources as IAS
    import research_cite as RC
    print("\n■ 貼れる図: 数字は headline・集計のまま")
    for ind in _industries():
        hl = IAS.headline(ind)
        spec = RC.industry_spec(hl)
        check(f"{ind}: 図の数字 = headline の lp・lc・oa", RC.spec_values(spec), [hl["lp"], hl["lc"], hl["oa"]])
        txt = [t for _, rows in spec["groups"] for *_, t in rows]
        check(f"{ind}: 図の表示 = headline の値に%", txt, [f"{hl['lp']}%", f"{hl['lc']}%", f"{hl['oa']}%"])
    if AR.months():
        cur = AR.load(AR.months()[-1])
        check("ランキング: 図の数字 = 各業種の1位の n",
              RC.spec_values(AR.chart_spec(cur)), [d["top"][0][2] for d in cur["industries"].values() if d.get("top")])
    page = "a" + RC.box_html("出典", "", ("/x.png", "<figure></figure>", "alt", 10, 10)) + "b"
    check("図を描けなかったら図の区間だけ外す", ("cite-embed" in RC.strip_fig(page), 'id="cite-line"' in RC.strip_fig(page)), (False, True))


def test_one_dataset_with_usage_info_and_creator():
    import industry_ai_sources as IAS
    print("\n■ 構造化データ: Dataset は1つ・usageInfo と creator を持つ")
    for ind in _industries():
        _, _, body, ld, _ = IAS.render(ind)
        check(f"{ind}: Dataset は ld の1つだけ", (ld["@type"], "Dataset" in body), ("Dataset", False))
        check(f"{ind}: usageInfo は引用の枠・creator は社名",
              (ld.get("usageInfo"), ld.get("creator", {}).get("name")), (ld["url"] + "#cite", "セブンセンシズ株式会社"))
        built = ROOT / "site" / "research" / f"{ind}-ai-sources" / "index.html"
        if built.is_file():
            n = len(re.findall(r'"@type":\s*"Dataset"', built.read_text(encoding="utf-8")))
            check(f"{ind}: 公開ページの Dataset は1つ", n, 1)
    RS = _subsidy_research()
    ld = RS.dataset_ld({"title": "t", "description": "d", "domain": "https://example.test", "url": "/research/x/",
                        "period": "2026-10-01"})
    check("AIに聞いた調査: usageInfo と creator", (ld["usageInfo"], ld["creator"]["name"]),
          ("https://example.test/research/x/#cite", "セブンセンシズ株式会社"))


def test_monthly_announcement_draft_uses_only_tallied_numbers():
    import research_announce as RA
    print("\n■ 毎月のお知らせの下書き: 集計の数字だけ・配信しない")
    cur, prev = RA.latest()
    if cur:
        title, md, posts, wh = RA.compose(cur, prev)
        check("下書きは検査を通る", RA.problems(md + "\n" + "\n".join(posts.values()), cur, prev, wh), [])
        check("集計に無い数字を止める", any("98765" in x for x in RA.problems("98765問", cur, prev, wh)), True)
        check("一律の言い方を止める", bool(RA.problems("どの業種でもポータルが中心", cur, prev, wh)), True)
        check("社名・問い合わせ先・図がある",
              ("セブンセンシズ株式会社" in md, "/contact/" in md, "chart.png" in md, "## 要点" in md), (True, True, True, True))
        check("SNS の短文は字数の内", len(posts["x"]) <= 250, True)
    src = (ROOT / "scripts" / "research_announce.py").read_text(encoding="utf-8")
    check("送らない（メール・投稿の道具を呼ばない）",
          any(w in src for w in ("notify_slack", "resend", "requests.post", "urlopen")), False)
    wf = (ROOT / ".github" / "workflows" / "research.yml").read_text(encoding="utf-8")
    check("月次のランキング更新で下書きを作る", "research_announce.py --write" in wf and "docs/announcements" in wf, True)
