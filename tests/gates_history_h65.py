# -*- coding: utf-8 -*-
"""2026-10-08 運用者の指摘「Search Console と GA4 を見ると、全く関係ないキーワードが選ばれている」から。

実測（GSC 2026-09-08〜10-05・28日、page 次元を末尾スラッシュで合算）:
  - コーポレート: 銀行の通帳・ゆうちょの送金と振込を扱う記事（狙う語「記帳 やり方 ゆうちょ」ほか）が
    サイト全体の表示の約4割（4,097回のうち 1,576回）。「記帳」は帳簿づけ（経理）と通帳の記帳（銀行）が同じ字で、
    担当領域語の部分一致だけで通っていた（kw_discover の GSC 実証とサジェスト、kw_plan の「記帳」起点）
  - AI集客ラボ: 「歯科医院 閉院 費用」「整骨院 費用 保険」「クリニック 電話予約 やり方」など、患者・開業・建築の記事。
    kw_discover が「業種名＋汎用語（費用・やり方・事例・選び方）」を担当領域とみなしていた（GENERIC_TERMS）。
    ai_kw_research も業種名だけで担当領域とみなし、「保険代理店 選び方」を台帳に積んでいた
  - 補助金: 「建設業 電子申請 閲覧」「個人事業主 開業届 電子申請」「社会保険 電子申請義務化」など補助金でない電子申請。
    「申請」が担当領域語で、補助金の文脈が無くても通っていた
  - 台帳に「-一覧 -ランキング -求人」の検索演算子入りの語、特定の医療機関名（不妊治療の助成金を調べる患者の検索）が残っていた

直し: 担当領域の判定を1つ（kw_fit）にし、積む（hub_client.add_kw・kw_discover・ai_kw_research・kw_plan）・
選ぶ（hub_client.next_kw）・書く前（kw_guard）・書いた後（kw_gate --after・publish_flow）の入口が全部これを通る。
同じ字で別の意味の語は sites/<id>.json の kw_needs（文脈の語）、担当の外の文脈は kw_off に書く（データで直せる）。
"""
import inspect
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

# 実際に台帳に積まれた・記事になった・検索で出ていた語（悪い例）と、主力の語（良い例）
BAD = {
    "corporate": ["記帳 やり方 ゆうちょ", "送金 振込 違い ゆうちょ", "通帳 記帳できない 原因", "記帳 やり方 銀行",
                  "通帳に記帳", "記帳通帳", "モンハン ライズ 手 記帳", "ライフウェーブ バックオフィス ログイン",
                  "経理事務の仕事内容", "経費精算コンカー", "計理 経理 違い", "おすすめ 日記帳", "aio対策 代行"],
    "ai-lab": ["歯科医院 閉院 費用", "整骨院 費用 保険", "クリニック 電話予約 やり方", "保険代理店 選び方",
               "歯科医院 移転 費用", "クリニック 建築 事例", "工務店 meo対策", "it導入補助金 申請 やり方"],
    "subsidy": ["建設業 電子申請 閲覧", "個人事業主 開業届 電子申請", "e-gov 電子申請 個人事業主",
                "社会保険 電子申請義務化 中小企業", "杉ウィメンズ クリニック 助成金", "加藤 レディース クリニック 助成金",
                "病気で働けない 補助金 個人事業主", "it・ソフトウェア 補助金申請代行 株式会社 -一覧 -ランキング -求人",
                "meo対策 大阪"],
}
GOOD = {
    "corporate": ["記帳代行 費用", "経理代行 相場", "記帳 代行 相場 法人", "経理 アウトソーシング 費用",
                  "請求書 仕訳", "経費精算 bpo", "月次決算 早期化 方法"],
    "ai-lab": ["歯科医院 aio対策 費用", "クリニック seo", "不動産 llmo", "工務店 ai検索 集客", "リフォーム 集客 方法",
               "llmo 店舗集客"],
    "subsidy": ["ai導入補助金 申請 やり方", "it導入補助金 電子申請", "補助金 電子申請 義務化", "ものづくり補助金 美容室",
                "持続化補助金 2026", "ai導入補助金 交付決定 いつ", "農業 補助 金 申請 方法"],
}


def test_kw_fit_sorts_real_unrelated_words():
    import kw_fit
    print("\n■ kw_fit: 実際に積まれた・記事になった関係ない語を止め、主力の語は通す")
    for site, kws in BAD.items():
        got = [k for k in kws if kw_fit.judge(k, site)[0] < 2]
        check(f"{site}: 関係ない語は判定2（記事にしない）", got, [])
    for site, kws in GOOD.items():
        got = [(k, kw_fit.judge(k, site)) for k in kws if kw_fit.judge(k, site)[0] != 0]
        check(f"{site}: 主力の語は判定0（そのまま書く）", got, [])
    # 担当領域語の無い語は止めない（人や計画が選んだ語）。自動で拾う工程だけが積まない
    check("担当領域語の無い語は判定1（業種＋汎用語）", kw_fit.judge("飲食店 平日 来店", "ai-lab")[0], 1)
    check("設定の無い社は止めない", kw_fit.judge("記帳 やり方 ゆうちょ", "no-such-site"), (0, ""))
    # 理由が読める（台帳の掃除の一覧・隔離の知らせに出す）
    lv, why = kw_fit.judge("記帳 やり方 ゆうちょ", "corporate")
    check("理由に何で止めたかが出る", bool(why) and lv == 2, True)


def test_discovery_sources_require_territory_words():
    import kw_discover as KD
    import ai_kw_research as AK
    import sites as S
    print("\n■ 自動で拾う工程: 業種名＋汎用語・業種名だけ・同じ字で別の意味の語を積まない")
    lab, corp, sub = KD.site_config("ai-lab"), KD.site_config("corporate"), KD.site_config("subsidy")
    check("kw_discover: 業種名＋汎用語を担当領域とみなさない（クリニック 電話予約 やり方）", KD.fits("クリニック 電話予約 やり方", lab), False)
    check("kw_discover: 通帳の記帳を拾わない（GSC 実証で出ていた語）", KD.fits("ゆうちょ 記帳", corp), False)
    check("kw_discover: 補助金でない電子申請を拾わない", KD.fits("建設業 電子申請 閲覧", sub), False)
    check("kw_discover: 主力の語は拾う", (KD.fits("クリニック aio対策 費用", lab), KD.fits("記帳代行 相場", corp),
                                    KD.fits("it導入補助金 電子申請", sub)), (True, True, True))
    check("kw_discover: 受け入れの判定に汎用語（domain_terms）を使わない", 'S["domain_terms"]' in inspect.getsource(KD.main), False)
    # kw_fit の「別のサイトの担当」は同じ組（自社3サイト）だけを見る。お客様の社（CONFLUX）の「外注」で
    # 「経理 外注 費用」を落とさない（kw_discover の除外語の取り違えは別の直しで止める）
    import kw_fit
    check("kw_fit: お客様の社の担当領域語で自社の買い手の語を止めない",
          (kw_fit.judge("経理 外注 費用", "corporate")[0], kw_fit.judge("ai 導入 補助金 個人事業主", "subsidy")[0]), (0, 0))
    cfg = S.load("ai-lab")
    check("ai_kw_research: 業種名だけの語を担当領域とみなさない（保険代理店 選び方）", AK.in_territory("保険代理店 選び方", cfg), False)
    check("ai_kw_research: 主力の語は通す", AK.in_territory("クリニック aio 対策 とは", cfg), True)


def test_kw_plan_drops_homonyms_with_real_site_config():
    import kw_discover as KD
    import kw_plan as KP
    print("\n■ kw_plan: 実際のサイト設定で、同じ字で別の意味の語を計画に入れない")
    S = KD.site_config("corporate")

    def ok(kw):
        return KP.relevant({"kw": kw, "vol": 1000, "imp": 0}, S, [], [], [], [])
    check("通帳の記帳は落とす", ok("通帳 記帳できない 原因") != "", True)
    check("ゆうちょの記帳は落とす", ok("記帳 やり方 ゆうちょ") != "", True)
    check("記帳代行は通す", ok("記帳代行 費用 相場"), "")


def test_ledger_door_and_selection_use_kw_fit():
    import hub_client as HC
    import kw_reach as R
    print("\n■ 台帳の入口（add_kw）と次に書く語（next_kw）が kw_fit を通る")
    saved = {k: getattr(HC, k) for k in ("enabled", "_post", "_get", "all_kw", "_ai_targets")}
    saved_held = R.held_queries
    sent = []
    try:
        HC.enabled = lambda: True
        HC._post = lambda body: (sent.append(body), {"ok": True, "added": len(body["keywords"])})[1]
        r = HC.add_kw("corporate", ["記帳 やり方 ゆうちょ", "記帳代行 費用",
                                    {"keyword": "通帳 記帳できない 原因", "priority": "A"}])
        posted = [k["keyword"] if isinstance(k, dict) else k for b in sent for k in b["keywords"]]
        check("add_kw: 関係ない語は台帳へ送らない", posted, ["記帳代行 費用"])
        check("add_kw: 送らなかった語と理由を返す", len((r or {}).get("skipped_unfit", [])), 2)
        sent.clear()
        r = HC.add_kw("corporate", ["通帳に記帳"])
        check("add_kw: 全部が関係ない語なら台帳を呼ばない", (sent, (r or {}).get("added")), ([], 0))

        row = lambda k: {"site": "corporate", "status": "未着手", "keyword": k, "priority": "A"}
        led = [row(k) for k in ("記帳 やり方 ゆうちょ", "通帳に記帳", "記帳代行 費用 相場")]
        HC._get = lambda p: {"ok": True, "keyword": "記帳 やり方 ゆうちょ", "category": "", "aim": ""}
        HC.all_kw = lambda strict=False: led
        HC._ai_targets = lambda site: set()
        R.held_queries = lambda site: []
        got = HC.next_kw("corporate")
        check("next_kw: 台帳の先頭が関係ない語なら、関係ない語を飛ばして主力の語を書く",
              (got or {}).get("keyword"), "記帳代行 費用 相場")
        led[:] = [row(k) for k in ("記帳 やり方 ゆうちょ", "通帳に記帳")]
        check("next_kw: 未着手が関係ない語だけなら書かない", HC.next_kw("corporate"), None)
    finally:
        for k, v in saved.items():
            setattr(HC, k, v)
        R.held_queries = saved_held


def test_guards_before_and_after_writing_use_kw_fit():
    import kw_gate
    import kw_guard
    import publish_flow
    print("\n■ 書く前（kw_guard）と書いた後（kw_gate --after・publish_flow）も kw_fit を通る")
    lv, reasons = kw_guard.judge("記帳 やり方 ゆうちょ", "corporate", use_gsc=False)
    check("kw_guard: 関係ない語は着手禁止（2）", lv, 2)
    check("kw_guard: 理由に担当領域の外と出る", any("担当領域の外" in h for _t, h, _d in reasons), True)
    lv2, reasons2 = kw_guard.judge("記帳 やり方 ゆうちょ", "corporate", use_gsc=False, exclude_slug="yucho-kicho-yarikata")
    check("kw_guard: 公開済み記事の書き直し・統合（--exclude-slug）は担当領域で止めない（扱いは運用者が決める）",
          any("担当領域の外" in h for _t, h, _d in reasons2), False)
    check("kw_gate --after: 書いた記事の狙う語を kw_fit で見る", "kw_fit" in inspect.getsource(kw_gate.main), True)
    check("kw_gate --before: 担当領域の外の語は食い合いと書かずに退避する", "担当領域の外" in inspect.getsource(kw_gate.main), True)
    check("publish_flow: 配信の前に、この回に書いた記事の狙う語を kw_fit で見る", "kw_fit" in inspect.getsource(publish_flow), True)


def test_ledger_cleanup_lists_before_writing():
    import kw_fit
    print("\n■ 台帳の掃除: 未着手・執筆中の関係ない語を一覧にする（書き換えは --retire を付けたときだけ）")
    rows = [{"site": "corporate", "status": "未着手", "keyword": "記帳 やり方 ゆうちょ"},
            {"site": "corporate", "status": "執筆中", "keyword": "通帳に記帳"},
            {"site": "corporate", "status": "公開済み", "keyword": "記帳 やり方 銀行"},
            {"site": "corporate", "status": "未着手", "keyword": "記帳代行 費用"},
            {"site": "ai-lab", "status": "未着手", "keyword": "保険代理店 選び方"}]
    got = [(r["site"], r["keyword"]) for r, _lv, _why in kw_fit.ledger_unfit(rows)]
    check("未着手・執筆中の関係ない語だけを挙げる（公開済み・主力の語は挙げない）", got,
          [("corporate", "記帳 やり方 ゆうちょ"), ("corporate", "通帳に記帳"), ("ai-lab", "保険代理店 選び方")])
    src = inspect.getsource(kw_fit.main)
    check("一覧は既定で読むだけ（retire_kw は --retire のときだけ呼ぶ）", "if a.retire" in src and src.count("retire_kw") == 1, True)


def test_rewrites_do_not_lean_into_unrelated_queries():
    import datetime as dt
    import tempfile
    from pathlib import Path
    import auto_rewrite as AR
    print("\n■ 流入語に寄せる直し（early・desc）が、担当領域の外の語に寄せない")
    # 2026-09-27 の書き直しが、関係ない流入語「送金 振込 違い ゆうちょ」を FAQ と冒頭に足し、さらにその語へ寄せた
    row = {"kw": "送金 振込 違い ゆうちょ", "url": "https://corp.7senses.co.jp/blog/yucho-kicho-yarikata",
           "pos": 6.7, "imp": 62, "clicks": 1}
    with tempfile.TemporaryDirectory() as d:
        log = Path(d) / "none.jsonl"
        log.write_text("", encoding="utf-8")
        got = AR.early_items(limit=5, today=dt.date(2026, 10, 8), rows_of=lambda s: [row] if s == "corporate" else [],
                             log=str(log))
    check("early: 担当領域の外の細い語を題・見出し・FAQへ入れる候補にしない",
          [i["slug"] for i in got if i["slug"] == "yucho-kicho-yarikata"], [])
    check("desc: 担当領域の外の流入語を説明文に入れない", "kw_fit" in inspect.getsource(AR.desc_items), True)
