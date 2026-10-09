# -*- coding: utf-8 -*-
"""CONFLUX（conflux-partners.jp）と管制塔を結合して確かめた食い違い（2026-10-08・運用者の決定）。

  1. CONFLUX の記事は本文に当社名（セブンセンシズ株式会社）が出てよい（例「ラクシフトAIは、セブンセンシズ株式会社が
     提供しています」）。お客様の記事に当社名を入れない検査（sites.operator_leaks）が CONFLUX でも止めていたため、
     監修待ちの business-system-development-cost は承認しても BLOCKED で配信できなかった。
     許すのは sites/<id>.json の operator_ok に書いた語だけ。ほかのお客様の社と、代表者名・AI集客ラボ・当社のドメインは止める
  2. 自動化の記事の監修は両方の名前（YW（CONFLUX PARTNERS）とセブンセンシズ株式会社）で表示する
     （先方の src/components/page/JournalArticle.tsx）。監修の記録（editorial_review）の名義が「YW」だけで食い違っていた
  3. 先方の scripts/build-journal.mjs は更新日を modified、狙う語を keyword で読む（docs/journal-pipeline.md）。
     管制塔は updated・tags で書いていた
  4. 定義の枠: 先方は <div class="box-note" data-label="定義"> で札を「定義」にする。管制塔は札「ポイント」のまま
     題「定義」を足していた（1つの枠に「ポイント」と「定義」が並ぶ）
  5. 先方は layout（Measure）で計測する。記事の本文に計測のスクリプトが入れば書き込む前に止める
  6. 先方は /journal/<slug>/ を /journal/<slug> へ 308 で転送する（本番で確認）。管制塔は記事の URL を末尾スラッシュ
     付きで組み、通知・配信の記録・レポートが転送先でない URL を指していた
"""
import inspect
import re
import sys

from test_gates import check, ROOT, client_ready

sys.path.insert(0, str(ROOT / "scripts"))
SLUG = "business-system-development-cost"
SAYS = "ラクシフトAIは、セブンセンシズ株式会社が提供しています。"


class _Reached(Exception):
    """配信が作業コピーの取得（書き込みの直前）まで進んだ印"""


def _receiver_reads(fm):
    """先方の fromPipeline が front matter から読むもの（2026-10-08 の main の版の写し）"""
    tags = fm.get("tags") or []
    return {"updatedAt": str(fm.get("modified") or fm.get("updated") or fm.get("lastmod") or fm.get("date")),
            "keyword": fm.get("keyword") or (tags[0] if tags else None) or fm.get("title")}


def test_conflux_may_name_the_operator_only_where_allowed():
    # CONFLUX の設定・材料は非公開の置き場（2026-10-10 守秘義務）。取れない回は飛ばす（自社の門は回る）
    if not client_ready("conflux"):
        return
    print("\n■ CONFLUX の記事は当社名（セブンセンシズ株式会社）を出してよい。ほかの社と、ほかの当社の表記は今までどおり止める")
    import aggregate_pages as AP
    import sites as S
    cf = S.load("conflux")
    check("CONFLUX: 本文の「セブンセンシズ株式会社」は通す（sites/conflux.json の operator_ok）",
          S.operator_leaks(SAYS, cf), [])
    check("ほかのお客様の社（operator_ok が無い）と、設定を渡さない呼び出しは今までどおり止める",
          [S.operator_leaks(SAYS, {"id": "h55-other"}), S.operator_leaks(SAYS)], [["セブンセンシズ"], ["セブンセンシズ"]])
    check("CONFLUX でも、許した語の外は止める（代表者名・社名の略・AI集客ラボ・当社のドメイン）",
          [bool(S.operator_leaks(t, cf)) for t in ("監修: 原口 優", "セブンセンシズの記事", "AI集客ラボ",
                                                     "https://ai.7senses.co.jp/x/")], [True, True, True, True])
    check("許す語に代表者名を入れない（先方の記事に人の名前を出さない決まり）",
          [w for w in cf.get("operator_ok") or [] if "原口" in w], [])
    # 配信の入口（publish.main）は test_held_conflux_article_reaches_delivery_once_approved が動かして確かめる
    check("まとめのページ（aggregate_pages）も、その社の設定を渡して検査する",
          'S.operator_leaks(p["html"] + json.dumps(p["jsonld"], ensure_ascii=False), cfg)' in inspect.getsource(AP.collect),
          True)


def test_held_conflux_article_reaches_delivery_once_approved():
    # CONFLUX の設定・材料は非公開の置き場（2026-10-10 守秘義務）。取れない回は飛ばす（自社の門は回る）
    if not client_ready("conflux"):
        return
    print("\n■ 監修待ちの CONFLUX の記事は、承認の記録が付けば当社名の検査で止まらず、配信（作業コピーの取得）まで進む")
    import editorial_review as ER
    import publish as P
    import scaled_guard as SG
    if not (ROOT / "articles" / f"{SLUG}.md").is_file():
        print(f"  --  {SLUG} が無いため確かめません")
        return

    def stop(*a, **k):
        raise _Reached()
    saved = (ER.reviewed, ER.load, SG.check, P.ensure_clone, sys.argv)
    try:
        ER.reviewed = lambda slug, recs=None: True
        ER.load = lambda: {SLUG: {"slug": SLUG, "by": "h55"}}
        SG.check = lambda *a, **k: []
        P.ensure_clone = stop
        sys.argv = ["publish.py", "--site", "conflux", "--slug", SLUG]
        try:
            P.main()
            got = "作業コピーを取らずに終わった"
        except _Reached:
            got = "作業コピーの取得まで進んだ"
        except SystemExit as e:
            got = str(e.code)[:160]
    finally:
        ER.reviewed, ER.load, SG.check, P.ensure_clone, sys.argv = saved
    check(f"{SLUG}: 承認後に BLOCKED・HELD で止まらない", got, "作業コピーの取得まで進んだ")


def test_journal_front_matter_and_parts_match_the_receiver():
    # CONFLUX の設定・材料は非公開の置き場（2026-10-10 守秘義務）。取れない回は飛ばす（自社の門は回る）
    if not client_ready("conflux"):
        return
    print("\n■ CONFLUX へ渡す形: 更新日 modified・狙う語 keyword・定義の札・本文に計測のスクリプトを入れない")
    import publish as P
    import sites as S
    from gates_history_h50 import _from_pipeline
    cf = S.load("conflux")
    ok_fm = {"slug": "x", "title": "x", "description": "x", "category": "development", "date": "2026-10-08", "author": "YW"}
    ok_md = "## a\n\n本文\n\n## b\n\n本文\n\n## c\n\n本文\n"
    check("検出器: 本文に計測のスクリプトがあれば止める（構造化データの script は止めない）",
          [P.journal_problems(ok_fm, ok_md, {}),
           any("スクリプト" in p for p in P.journal_problems(ok_fm, ok_md + '\n<script>gtag("event","x")</script>\n', {})),
           any("スクリプト" in p for p in P.journal_problems(ok_fm, ok_md + '\n<script type="application/ld+json">{}</script>\n', {}))],
          [[], True, False])
    check("記事の URL は先方の正規の形（末尾スラッシュ無し。付けると 308 の転送が挟まる）",
          S.article_url(cf, {"slug": SLUG, "category": "development"}), f"https://conflux-partners.jp/journal/{SLUG}")
    if not (ROOT / "articles" / f"{SLUG}.md").is_file():
        print(f"  --  {SLUG} が無いため、ここから先は確かめません（形は gates_history_h50 の試験の記事でも見ている）")
        return
    meta, body = P.parse_article(ROOT / "articles" / f"{SLUG}.md")
    fm, md = P.journal_md(cf, meta, P._md_insert_entries(body, cf), P.md_dialect(cf))
    check("更新日は modified・狙う語は keyword（先方の docs/journal-pipeline.md の書き方）。updated・tags は書かない",
          [str(fm.get("modified")), fm.get("keyword"), "updated" in fm, "tags" in fm],
          [str(meta.get("modified") or meta["date"]), meta["keyword"], False, False])
    check("先方がその front matter から更新日と狙う語を読める",
          _receiver_reads(fm), {"updatedAt": str(meta.get("modified") or meta["date"]), "keyword": meta["keyword"]})
    check("定義の枠は box-note の札を「定義」にする（data-label）。札と同じ題を中に重ねない",
          ['<div class="box-note" data-label="定義">\n<p><strong>人月とは</strong>' in md, '<p class="box-title">定義</p>' in md],
          [True, False])
    check("本文に計測などのスクリプトが無い（先方は layout の Measure で計測する）",
          re.findall(r"<script\b(?![^>]*application/ld\+json)[^>]*>", md), [])
    got = _from_pipeline(md)
    check("冒頭: 先方が結論（em-marker）・情報の時点・対象読者を拾い、その行を本文から外す",
          [bool(got["answer"]), got["asOf"], got["audience"].endswith("向けです"), "本記事は" in got["md"]],
          [True, "2026年10月時点の情報です", True, False])
    check("先方の変換の条件を満たす（止める語・部品・** が残らない）", P.journal_problems(fm, md, P.md_dialect(cf)), [])


def test_conflux_review_record_names_both_supervisors():
    # CONFLUX の設定・材料は非公開の置き場（2026-10-10 守秘義務）。取れない回は飛ばす（自社の門は回る）
    if not client_ready("conflux"):
        return
    print("\n■ 監修の記録の名義: CONFLUX の自動化の記事は、先方の表示と同じ「YW（CONFLUX PARTNERS）・セブンセンシズ株式会社」")
    import editorial_review as ER
    import sites as S
    cf = S.load("conflux")
    check("sites/conflux.json の review_by（先方の JournalArticle.tsx の表示と同じ並び）",
          cf.get("review_by"), ["YW（CONFLUX PARTNERS）", "セブンセンシズ株式会社"])
    if not (ROOT / "articles" / f"{SLUG}.md").is_file():
        print(f"  --  {SLUG} が無いため記録の名義は確かめません")
        return
    # review_by の無いお客様は今までどおり company.json の監修者（gates_history_h10 の「試験 太郎」）
    by = ER.reviewer_for(SLUG)
    check("承認の記録の名義は両方の名前（代表者の実名は入れない）",
          [by, "原口" in by], ["YW（CONFLUX PARTNERS）・セブンセンシズ株式会社", False])
