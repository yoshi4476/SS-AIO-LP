# -*- coding: utf-8 -*-
"""2026-11-13 運用者の決定。記事の数字は門で確かめていたが、手で書いた固定ページ（トップ・よくある質問・サービス・会社概要）は
対象外で、補助金LPのよくある質問に公募要領に無い「売上が法人3,300万円・個人事業主3,900万円以上」「決算2期」が残っていた
（2026-11-12 に手で直した）。scripts/fixed_facts.py が月初に本番の固定ページを取り、制度の台帳（program-status.md）・
終わった制度（RETIRED_PROGRAMS）・会社の実績の台帳（first_party_facts.json ほか）と照らす。
ネットワークには出ない（HTML の文字列を直接渡す）。"""
import io
import sys
from contextlib import redirect_stdout
from unittest import mock

from test_gates import check, ROOT, pipeline_doc

sys.path.insert(0, str(ROOT / "scripts"))

PROGRAMS = [
    ("デジタル化・AI導入補助金2026 インボイス枠",
     "デジタル化・AI導入補助金2026 インボイス枠 補助額は約350万円まで（機能が1つなら約50万円まで）。補助率は3/4以内（小規模事業者4/5）、50万円超は2/3以内"),
    ("デジタル化・AI導入補助金2026 通常枠", "デジタル化・AI導入補助金2026 通常枠 補助額5万〜150万円未満／150万〜450万円、補助率1/2"),
    ("事業再構築補助金", "事業再構築補助金 新規公募は第13回で終了"),
]
FACTS = ["2020年から2026年10月までの支援はAIO・SEO・MEOを合わせて累計3,200件以上で、MEOの運用は2,000件以上です",
         "2023年4月から2026年9月までに経理代行を担当した会社は48社で、うち31社は継続中です"]


def _ledger():
    import fixed_facts as F
    return F.Ledger(PROGRAMS, FACTS, ["事業再構築補助金"])


def _kinds(html, ledger=None):
    import fixed_facts as F
    return sorted((it["kind"], it["value"]) for it in F.check_html(html, ledger or _ledger(), "https://zz.example/"))


def _bad(html, ledger=None):
    import fixed_facts as F
    return [k for k in _kinds(html, ledger) if k[0] in F.BAD]


SUB = "<p>補助金の申請を支援します。補助金の相談は無料です。補助金の要件を確かめます。</p>"


def test_bad_examples_are_found():
    print("\n■ 固定ページの数字: 台帳と食い違う上限額・終わった制度・台帳に無い要件を拾う")
    check("インボイス枠の文の上限額が、インボイス枠の行に無い（通常枠の450万円）",
          _bad("<p>AI導入補助金のインボイス枠は補助上限450万円です。</p>"), [("mismatch", "450万円")])
    check("数字と「万円」が別の span、見出しが別の要素（最初の画面の数字の帯）でも照らす",
          _bad("<dl><dt>補助上限（インボイス枠）</dt><dd><span>500</span><span>万円</span></dd></dl>"),
          [("mismatch", "500万円")])
    check("補助率も照らす", _bad("<p>インボイス枠の補助率は最大9/10です。</p>"), [("mismatch", "9/10")])
    check("終わった制度を、終わったと書かずに載せている",
          _bad("<p>事業再構築補助金で設備投資を支援します。</p>"), [("retired", "事業再構築補助金")])
    faq = ("<h3>よくある質問</h3><p>Q. 対象になる会社は？</p>"
           "<p>A. AI導入補助金は、売上が法人3,300万円・個人事業主3,900万円以上で、決算を2期終えた事業者が対象です。</p>")
    check("2026-11-12 のよくある質問（売上の下限・決算2期）を台帳に無い要件として拾う",
          _bad(faq), [("requirement", "2期"), ("requirement", "3,300万円"), ("requirement", "3,900万円")])
    check("表のセル（主語の「売上要件」が隣のセル）でも拾う",
          _bad(SUB + "<table><tr><th>① 売上要件</th><td>法人 3,300万円以上</td></tr></table>"),
          [("requirement", "3,300万円")])
    check("過去の採択の期間（台帳に無い）を拾う",
          _bad(SUB + "<p>直近4年以内にIT導入補助金の採択・交付を受けた事業者は対象外です。</p>"),
          [("requirement", "4年")])


def test_good_examples_are_not_found():
    print("\n■ 固定ページの数字: 台帳どおりの数字・日付・言い回しは拾わない")
    check("インボイス枠の上限350万円（台帳どおり）",
          _kinds("<dl><dt>補助上限（インボイス枠）</dt><dd><span>350</span><span>万円</span></dd></dl>"), [])
    check("通常枠の最大450万円・補助率1/2（台帳どおり）",
          _kinds("<p>AI導入補助金の通常枠は最大450万円、補助率は1/2です。</p>"), [])
    check("会社の実績（累計3,200件・48社のうち31社）は実績の台帳どおり",
          _kinds("<p>累計3,200件の支援。経理代行は48社（うち31社が継続中）。MEOの運用は2,000件以上。</p>"), [])
    check("終わったと書いた制度名は拾わない",
          _kinds("<p>事業再構築補助金は新規公募が終了しました。後継の制度をご案内します。</p>"), [])
    check("日付・年度・電話番号・設問の番号は数字の主張に数えない",
          _kinds("<p>2026年11月12日更新。令和8年度。電話 06-1234-5678。Q1 / 8</p>"), [])
    check("料金の行（月額）と「1円も出ません」は扱わない",
          _kinds("<p>月額5万円のプランです。順番を間違えると1円も出ません。</p>"), [])
    check("モデルケースの導入費は上限額の主張ではない（食い違いにしない。台帳に無い数字として並べるだけ）",
          _bad("<p>導入費550万円の例では、AI導入補助金のインボイス枠で補助金350万円が交付された場合の自己負担は200万円です。</p>"),
          [])
    check("台帳に無い数字は「台帳に無い数字」（誤りと断定しない）",
          _kinds("<p>運用サービスの契約継続率は94%です。</p>"), [("unsourced", "94%")])


def test_real_ledger_catches_the_2026_11_12_faq():
    import fixed_facts as F
    print("\n■ 本物の台帳（program-status.md・RETIRED_PROGRAMS）で照らす")
    real = F.Ledger(F.program_rows(), [], F.retired_programs())
    check("program-status.md の表を読めている", len(real.programs) >= 10, True)
    check("直した誤りを書いた括弧（「…3,300万円…と書いていたので直した」）の数は台帳の数に入れない",
          ("円", 33_000_000) in real.all_prog, False)
    check("RETIRED_PROGRAMS の制度を終わった制度として読む", "事業再構築補助金" in real.retired, True)
    check("2026-11-12 に直したよくある質問の文を、本物の台帳でも拾う",
          _bad("<p>A. AI導入補助金は、売上が法人3,300万円・個人事業主3,900万円以上で、決算を2期終えた"
               "事業者が対象です。</p>", real),
          [("requirement", "2期"), ("requirement", "3,300万円"), ("requirement", "3,900万円")])
    check("コーポレートの最初の画面の「補助上限（インボイス枠）350万円」は本物の台帳どおり",
          _bad("<dl><dt>補助上限（インボイス枠）</dt><dd><span>350</span><span>万円</span></dd></dl>", real), [])


def _run(get, targets=None):
    import fixed_facts as F
    out = io.StringIO()
    with mock.patch.object(F, "targets", return_value=(targets or [("zz", {"domain": "zz.example", "fixed_pages": ["/"]})], [])), \
            mock.patch.object(F, "ledger_for", return_value=_ledger()), mock.patch.object(F, "fetch", get), \
            mock.patch.object(F, "WAIT", 0), mock.patch.object(sys, "argv", ["fixed_facts.py"]), redirect_stdout(out):
        rc = F.main()
    return rc, out.getvalue()


def test_exit_codes_follow_8_7():
    print("\n■ 終了コードと印は 8.7 の決まりどおり（見つかっても0、取れなかったときだけ1で unknown）")
    rc, out = _run(lambda url: ("<p>AI導入補助金のインボイス枠は補助上限450万円です。</p>", ""))
    check("見つかった: 0 で FIXED_FACTS_OK=no と要対応の明細", (rc, "FIXED_FACTS_OK=no" in out, "要対応: 固定ページの" in out),
          (0, True, True))
    rc, out = _run(lambda url: ("<p>累計3,200件の支援。インボイス枠の補助上限は350万円です。</p>", ""))
    check("無かった: 0 で FIXED_FACTS_OK=yes、要対応の行は無い", (rc, "FIXED_FACTS_OK=yes" in out, "要対応" in out),
          (0, True, False))
    rc, out = _run(lambda url: ("<p>継続率94%</p>", ""))
    check("台帳に無い数字だけなら FIXED_FACTS_OK=yes（情報として並べる）", (rc, "FIXED_FACTS_OK=yes" in out, "情報:" in out),
          (0, True, True))
    rc, out = _run(lambda url: (None, "HTTP 503"))
    check("取得できなかった: 1 で FIXED_FACTS_OK=unknown（問題なしにしない）",
          (rc, "FIXED_FACTS_OK=unknown" in out, "取得できませんでした" in out), (1, True, True))


def test_client_details_stay_out_of_ci_log():
    import fixed_facts as F
    print("\n■ お客様の社は CI のログに件数だけを出す")
    items = F.check_html("<p>AI導入補助金のインボイス枠は補助上限450万円です。株式会社ZZの実績は年商12億円。</p>",
                         _ledger(), "https://zz.example/")
    hidden = "\n".join(F.report("client-zz", items, [], 1, hide=True))
    check("伏せた出力に URL・本文が無く、件数の要対応がある",
          ("zz.example" in hidden, "株式会社ZZ" in hidden, "要対応: client-zz の固定ページに 台帳と食い違う数字 1件" in hidden),
          (False, False, True))
    src = (ROOT / "scripts" / "fixed_facts.py").read_text(encoding="utf-8")
    check("CI（GITHUB_ACTIONS）でお客様の社を伏せ、非公開のデータが無い社は private_store.require で知らせる",
          ('hide=client and ci' in src, "private_store.require(" in src), (True, True))


def test_wired_monthly_and_documented():
    import json
    print("\n■ 月初の工程に入っていて、文書に書いてある")
    wf = (ROOT / ".github" / "workflows" / "monthly-report.yml").read_text(encoding="utf-8")
    step = wf.split("scripts/fixed_facts.py", 1)[0].rsplit("- name:", 1)[-1] if "scripts/fixed_facts.py" in wf else ""
    check("monthly-report.yml の月初（mid == 'false'）に1ステップある", "steps.day.outputs.mid == 'false'" in step, True)
    check("要対応の行を通知（findings.txt）へ積む", "automation/logs/findings.txt" in wf.split("scripts/fixed_facts.py", 1)[-1][:900],
          True)
    for sid in ("ai-lab", "corporate", "subsidy"):
        cfg = json.loads((ROOT / "sites" / f"{sid}.json").read_text(encoding="utf-8"))
        check(f"{sid} の固定ページの一覧（fixed_pages）が少数で、トップを含む",
              ("/" in cfg.get("fixed_pages", []), 1 <= len(cfg.get("fixed_pages", [])) <= 8), (True, True))
    check("docs/pipeline に点検の説明がある", "fixed_facts.py" in pipeline_doc(), True)
