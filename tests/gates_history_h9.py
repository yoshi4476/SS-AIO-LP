# -*- coding: utf-8 -*-
"""受託のお客様の経路を架空の歯科医院で通しで試して見つけた不具合の門（2026-10-05）。

お客様の記事の監修者はお客様ご本人（運用者の決定）。当社の名前・実績・自社サイトへのリンクが
お客様の記事に出ないこと、監修の表示と構造化データ（reviewedBy）がお客様の監修者になること、
配信方式ごとの取りこぼし（/blog 固定・ZIP が届かない・戻しが押されない・変化なしで落ちる）を固定する。
FTP・Git・WordPress・Google の本物には触れない（一時フォルダと関数・ソースだけを見る）。
"""
import inspect
import json
import tempfile
from pathlib import Path

from test_gates import check, ROOT


def test_intake_checks_every_required_row_and_keeps_contacts_private():
    import client_intake as ci
    print("\n■ ヒアリングシート: 必須の全行・連絡先を public に出さない")
    keys = {k for k, *_ in ci.fields_for() if not k.startswith("#")}
    got = {k: "x" for k in keys}
    got.update({"id": "h9-sample", "type": "external-html", "repo": "o/r", "url_prefix": "/blog",
                "categories": "h9-a: A\nh9-b: B", "category_mix": "h9-a: 60\nh9-b: 40", "main_category": "h9-a",
                "facts.1.as_of": "2026-09", "supervisor.consent": "可", "supervisor.contact": "doc@example.test",
                "channels.contact": "山田 / yamada@example.test", "languages": "", "facts.1.denominator": "",
                "facts.2.denominator": "", "facts.3.denominator": ""})
    cfg = ci.to_config(got)
    ng, _ = ci.review(dict(got), cfg)
    check("埋まったシートは不備なし", [m for m in ng if "既に" not in m], [])
    for k, label in (("author.name", "著者名"), ("supervisor.name", "監修者のお名前"), ("kw.main", "メインキーワード")):
        g2 = dict(got)
        g2.pop(k)
        check(f"必須の「{label}」が空なら止める（FIELDS 以外の章も見る）",
              any(label in m for m in ci.review(g2, ci.to_config(g2))[0]), True)
    brief = json.dumps(ci.to_brief(got), ensure_ascii=False)
    check("brief.json（public）に監修者・SNS担当のメールが出ない", "@example.test" in brief, False)
    check("sites/<id>.json（public）に SNS 担当の連絡先を置かない", "contact" in cfg["channels"], False)
    priv = ci.to_private(got)
    check("連絡先は private.json へ", (priv.get("supervisor_contact"), "yamada" in priv.get("channels_contact", "")),
          ("doc@example.test", True))


def _client_tree(td, display=True):
    r = Path(td)
    c = r / "data" / "clients" / "h9-dental"
    c.mkdir(parents=True)
    (c / "company.json").write_text(json.dumps({
        "name": "医療法人 試験会", "tel": "00-0000-0000", "address": "架空県1-2-3",
        "supervisor": {"name": "試験 太郎", "title": "院長", "qualification": ["歯科医師"], "scope": "診療内容",
                       "career": ["架空大学 卒業"], "same_as": ["https://gakkai.example.test/1"],
                       "profile_url": "https://example-dental.test/doctor/", "display": display}},
        ensure_ascii=False), encoding="utf-8")
    (c / "brief.json").write_text(json.dumps({"author": {"name": "試験 花子", "title": "広報"}}, ensure_ascii=False),
                                  encoding="utf-8")
    return r


def test_client_article_credits_the_clients_supervisor():
    import publish as P
    import sites as S
    print("\n■ お客様の記事の監修者・著者・発行元（当社の名前を出さない）")
    cfg = {"id": "h9-dental", "domain": "example-dental.test", "name": "試験コラム", "url_prefix": "/column"}
    tpl = ('<html><head><script type="application/ld+json">{"@context":"https://schema.org","@type":"BlogPosting",'
           '"headline":"t","publisher":{"@type":"Organization","name":"試験コラム"}}</script></head>'
           '<body><h1>題</h1><p>本文</p></body></html>')
    meta = {"title": "題", "slug": "x"}
    old_p, old_s = P.ROOT, S.ROOT
    try:
        with tempfile.TemporaryDirectory() as td:
            P.ROOT = S.ROOT = _client_tree(td)
            c = P.client_credit(cfg)
            page = P.apply_credit(tpl, c, "https://example-dental.test/column/x/", meta)
            lds = [json.loads(b) for b in __import__("re").findall(r'<script type="application/ld\+json">(.*?)</script>', page)]
            bp = [d for d in lds if d.get("@type") == "BlogPosting"]
            check("BlogPosting は1つのまま（雛形のものに足す）", len(bp), 1)
            check("reviewedBy はお客様の監修者（資格つき）",
                  (bp[0]["reviewedBy"]["name"], bp[0]["reviewedBy"]["hasCredential"][0]["name"],
                   bp[0]["reviewedBy"]["sameAs"]), ("試験 太郎", "歯科医師", ["https://gakkai.example.test/1"]))
            check("author はお客様の書き手、publisher はお客様の会社",
                  (bp[0]["author"]["name"], bp[0]["publisher"]["name"]), ("試験 花子", "医療法人 試験会"))
            check("h1 の直後に「監修: 名前（資格）」と範囲を表示",
                  "監修: " in page and "試験 太郎（歯科医師）" in page and "監修の範囲: 診療内容" in page, True)
            check("当社の名前が出ない", [m for m in S.OPERATOR_MARKS if m in page], [])
        with tempfile.TemporaryDirectory() as td:
            P.ROOT = S.ROOT = _client_tree(td, display=False)
            c = P.client_credit(cfg)
            page = P.apply_credit(tpl, c, "https://example-dental.test/column/x/", meta)
            check("掲載の同意が無い監修者は表示も reviewedBy も出さない",
                  ("監修:" in page, "reviewedBy" in page), (False, False))
        with tempfile.TemporaryDirectory() as td:
            P.ROOT = S.ROOT = Path(td)
            check("自社サイトは対象外（None）", P.client_credit(cfg), None)
    finally:
        P.ROOT, S.ROOT = old_p, old_s
    src = inspect.getsource(P)
    check("nextjs-json・WordPress も同じ監修の表示を入れる",
          [src.count("client_credit(cfg)") >= 3, "credit_ld(credit" in inspect.getsource(P.write_wordpress),
           "credit_jsonld(credit" in inspect.getsource(P.write_nextjs_json)], [True, True, True])
    check("Person（原口）を付けるのは自社だけ", "if ap.get(\"same_as\") and not credit" in inspect.getsource(P.write_external_html), True)


def test_client_article_gate_blocks_operator_names_and_ng_words():
    import publish as P
    import sites as S
    print("\n■ お客様の記事の配信前の門（当社の名前・自社サイトへのリンク・使えない表現・公開前の確認）")
    hit = S.operator_leaks("MEO運用サービス「G-ran」で3,200店舗。[解説](/aio/aio-taisaku-souba/) と [院内](/column/a/)")
    check("当社のサービス名と自社カテゴリへのリンクを拾う（お客様のパスは拾わない）",
          ("G-ran" in hit, any("/aio/aio-taisaku-souba/" in h for h in hit), any("/column/" in h for h in hit)),
          (True, True, False))
    check("当社の正式名・代表名・ドメインも拾う",
          [bool(S.operator_leaks(t)) for t in ("セブンセンシズ株式会社", "監修: 原口 優", "https://ai.7senses.co.jp/x/")],
          [True, True, True])
    src = inspect.getsource(P.main)
    check("配信の入口で止める（お客様のサイトだけ）",
          ["is_client(cfg[\"id\"])" in src, "operator_leaks(" in src, "ng_words" in src,
           "review_before_publish" in src], [True, True, True, True])
    import editorial_review as ER
    check("公開前の確認の記録は、お客様の記事ならお客様の監修者の名前で残す", "reviewer_for(s)" in inspect.getsource(ER.main), True)


def test_delivery_paths_follow_the_url_prefix():
    import publish as P
    import deliver_files as DF
    import retract as RT
    import publish_rerender as PR
    print("\n■ 記事ページの置き場は URL の接頭辞と同じ（/blog 固定にしない）")
    check("external-html: /column の社は column/ に置く", P.page_dir({"url_prefix": "/column"}), "column")
    check("接頭辞が無ければ blog", P.page_dir({}), "blog")
    check("FTP・ZIP の作業場所は blog/ に書いてから移す", P.page_dir(DF.stage_cfg({"id": "a", "url_prefix": "/column"})), "blog")
    check("書き出し・関連記事・配信済みの判定・取り下げ・描き直しが同じ置き場を見る",
          ["page_dir(cfg)" in inspect.getsource(f) for f in
           (P.write_external_html, P._recent_articles, P._delivered, P.check_contract, RT.apply, PR.main)],
          [True] * 6)
    check("下の CTA にお客様の問い合わせ先のボタンがある",
          "{{CTA_URL}}" in (ROOT / "templates" / "external_article.html").read_text(encoding="utf-8"), True)
    check("お客様の社に補助金の CTA 文言を出さない", "if not credit" in inspect.getsource(P.write_external_html), True)


def test_zip_ftp_and_site_change_actually_reach_the_client():
    import deliver_files as DF
    import site_change as SC
    import publish_rerender as PR
    print("\n■ ZIP・FTP・サイト変更が先方に届く")
    check("ZIP は先方へメールし、CI で届かなければ配信済みにしない",
          ["hand_over(cfg, out)" in inspect.getsource(DF.deliver), "GITHUB_ACTIONS" in inspect.getsource(DF.deliver),
           "hand_over(cfg, out)" in inspect.getsource(DF.deliver_batch), "hand_over(cfg, out)" in inspect.getsource(DF.retract)],
          [True] * 4)
    check("ZIP の宛先はシートの会社メール（email）も見る", 'c.get("email")' in inspect.getsource(SC._mail_zip), True)
    check("FTP の社は sitemap・llms.txt を上げ先のサーバーから読む", "Remote(credentials(cfg))" in inspect.getsource(DF.stage), True)
    src = inspect.getsource(SC.main)
    check("Git の社の --rollback は revert を押す（差分が無くても）",
          ["git_push(cfg, committed=True)" in src, "committed" in inspect.getsource(SC.git_push)], [True, True])
    check("描き直しで変化が無ければ commit しない（落ちない）", "変更が無いので押しません" in inspect.getsource(PR.main), True)


def test_client_is_kept_apart_from_own_sites():
    import sites as S
    import kw_guard as KG
    import monthly_report as MR
    import group_report as GR
    import article_videos as AV
    import social_post as SP
    import daily_audit as DA
    print("\n■ お客様と自社3サイトを混ぜない")
    with tempfile.TemporaryDirectory() as td:
        old = S.ROOT
        try:
            S.ROOT = Path(td)
            (Path(td) / "data" / "clients" / "h9-x").mkdir(parents=True)
            check("お客様の食い合いの相手はその社だけ", S.group_of("h9-x"), ["h9-x"])
            check("is_client", (S.is_client("h9-x"), S.is_client("ai-lab")), (True, False))
        finally:
            S.ROOT = old
    check("食い合い検査の GSC 照合は group_of の範囲だけ", "group_of(site_id)" in inspect.getsource(KG.gsc_rows), True)
    check("お客様の月次: 宛名・Search Console 未接続で落ちない・当社の数字を載せない",
          ["addressee()" in inspect.getsource(MR), "gsc_missing" in inspect.getsource(MR.fetch_real),
           "group_of(SITE_ID)" in inspect.getsource(MR.group_totals), "G-ran" not in
           inspect.getsource(MR.improvements_html).split("if f.get(\"client\"):")[1]], [True] * 4)
    check("グループ月次は自社3サイトだけ", "own_cfgs()" in inspect.getsource(GR.main), True)
    check("動画は未接続のお客様を本数で切る前に外す", "token_path(sid)" in inspect.getsource(AV.candidates), True)
    check("note の転載文はお客様の社名で出す", "data\" / \"clients\" / sid" in inspect.getsource(SP.compose), True)
    check("月の上限はシートで減らした数（rules.monthly_cap）を使う", "site_cap(sid) - n" in inspect.getsource(DA.cap_left), True)
