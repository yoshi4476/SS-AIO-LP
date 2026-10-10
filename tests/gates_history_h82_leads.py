# -*- coding: utf-8 -*-
"""2026-10-10 運用者の指示「文脈を見て売り込みかテストか相談か判別してほしい」「流入経路も表示」「スプレッドに不明と書かれている」。

台帳の15行のうち、売り込み6行（機器の販売・イベント登壇・アポ獲得代行・アフィリエイト広告・協業の提案）と
テスト4行（自社ドメイン・運用者のアドレス・会社名が当社・意味をなさない名前と本文）が、温度 HOT/WARM のまま
「問い合わせ」として数えられ、月次レポートの件数にも入っていた。送信元ページの列は空か URL だけで、どこから来た人か
分からなかった。疎通確認のタブには、AI集客ラボの受付が参照元の無い送信に入れた「不明」が17件残っていた。

ここで確かめること:
  1. 受付（contact.hub.gs）の見分け: テストの決まり → Gemini（文脈）→ 正規表現。Gemini が使えなくても記録・通知は落ちない。
     判定に関係なく担当への通知は必ず出す（件名に印を付けるだけ）。売り込みにだけ自動返信を出さない
  2. 判別の例（悪い例と良い例）: 売り込みの定型文は拾い、自社の事業を紹介してから相談する本物の相談は拾わない
  3. 件数の数え方: 台帳の温度が「営業」「テスト」でない行だけを数える（lead_reconcile.ledger_counts / leads）
  4. 流入の欄: 4サイトのフォームが最初の流入元・入口・送信ページを送り、受付が「流入: …｜入口: …｜送信: …」にする。
     AI の参照元の分類は daily_kpi.AI_DOMAINS が正（受付の写しと一致する）
  5. 台帳の列数（14列）と、温度・流入経路の列の位置
"""
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))
GAS = ROOT / "automation" / "gas"
HARNESS = ROOT / "tests" / "gas_leads_harness.js"
CONTACT = (GAS / "contact.hub.gs").read_text(encoding="utf-8")


def _run(plan):
    node = shutil.which("node")
    if not node:
        return None
    p = subprocess.run([node, str(HARNESS), str(GAS / "hub.gs"), str(GAS / "contact.hub.gs")], input=json.dumps(plan),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if p.returncode:
        raise RuntimeError(f"受付を動かせませんでした: {(p.stderr or p.stdout)[-400:]}")
    return json.loads(p.stdout.strip().splitlines()[-1])


def _js_json(name):
    m = re.search(r"const " + name + r" = (\{.*?\});\n", CONTACT, re.S)
    return json.loads(m.group(1)) if m else None


# 判別の例（作り例。台帳の問い合わせの本文は公開リポジトリに置かない。売り込みは送り主の定型の言い回しの型だけを写す）
SALES_EXAMPLES = [
    "突然のご連絡失礼いたします。弊社では業務用の除菌機器をご案内しております。",
    "貴社サービスが展示イベントに合うと思い、登壇とリード獲得のご案内でご連絡しました。",
    "弊社では完全成果報酬型のアポイント獲得の支援を行っております。",
    "当社の案件をアフィリエイト広告で掲載いただけないか、ご相談させてください。",
    "弊社では業務用の計算機器をご提案しております。協業の機会をいただけないでしょうか。",
]
CONSULT_EXAMPLES = [
    "当社は工務店を営んでいます。ホームページからの問い合わせを増やしたいので、AI検索対策の相談をしたいです。",
    "ものづくり補助金を使えるか知りたいです。来年の設備投資で申請を考えています。",
    "記帳を外に任せたいと考えています。費用と進め方を教えてください。",
    "美容室を開く予定です。地図の検索で見つけてもらう方法を相談したいです。",
    "予約を管理する仕組みを作りたいので、見積もりをお願いします。",
]


def test_lead_kind_rules_and_examples():
    print("\n■ 問い合わせの見分け: 判別の例（悪い例と良い例）と、Gemini に渡す決まり")
    r = _run({"calls": [["isSales_", t] for t in SALES_EXAMPLES + CONSULT_EXAMPLES]
              + [["leadTestRule_", "taro@7senses.co.jp", "ai-lab"], ["leadTestRule_", "a@mail.partner.example.jp", "partner"],
                 ["leadTestRule_", "a@partner.example.jp", "別事業 (partner.example.jp)"],
                 ["leadTestRule_", "a@partner.example.jp", "ai-lab"], ["leadTestRule_", "a@7senses.co.jp.example.com", "ai-lab"],
                 ["leadTestRule_", "a@gmail.com", "ai-lab"]]})
    if r is None:
        print("  WARN  node が無いため受付の動きは確かめられません")
        return
    n = len(SALES_EXAMPLES)
    check("悪い例: 売り込みの定型文（機器・登壇・アポ獲得代行・アフィリエイト・協業）は正規表現でも拾う",
          r["calls"][:n], [True] * n)
    check("良い例: 自社の事業を紹介してから頼む相談・補助金・経理・開業・開発の相談は売り込みにしない",
          r["calls"][n:n + len(CONSULT_EXAMPLES)], [False] * len(CONSULT_EXAMPLES))
    check("テストの決まり: 当社のドメインと、送信先のサイトと同じドメイン（サブドメイン・台帳の表示名からも引く）だけを当て、"
          "別のサイトへの送信・似た別のドメイン・フリーメールは当てない",
          [bool(x) for x in r["calls"][-6:]], [True, True, True, False, False, False])
    check("別事業・お客様のサイトの名前とドメインを受付のコードに書かない（サイト一覧の登録から引く）",
          ("const OWN_MAIL_DOMAINS = ['7senses.co.jp'];" in CONTACT, "siteDomainOf_(site)" in CONTACT), (True, True))
    check("運用者の個人のアドレスは公開リポジトリに書かず、配る時に .env の HUB_OWNER_EMAILS で埋める",
          ("'OWNER_EMAILS_XXXXXXXX'" in CONTACT, "HUB_OWNER_EMAILS" in (ROOT / "scripts" / "gas_deploy.py").read_text(encoding="utf-8"),
           bool(re.search(r"@gmail\.com'", CONTACT))), (True, True, False))
    import gas_deploy as G
    check("配る時に運用者のアドレスの欄を .env の値で埋める",
          "'a@example.com'" in G.fill("const OWNER_EMAILS_FILL = 'OWNER_EMAILS_XXXXXXXX';", {"HUB_OWNER_EMAILS": "a@example.com"}), True)
    p = _run({"calls": [["leadKindPrompt_", "AI集客ラボ (ai.7senses.co.jp)", "contact",
                         {"company": "例", "name": "山田", "email": "yamada@example.co.jp", "tel": "06-0000-0000",
                          "message": "相談です"}]]})["calls"][0]
    check("Gemini に渡す決まり: 3つの分け方・迷ったら相談・JSON で答える",
          all(w in p for w in ("相談:", "売り込み:", "テスト:", "迷ったら「相談」", '"kind"')), True)
    check("Gemini にはメールのドメインと電話の有無だけを渡す（アドレス・番号そのものは渡さない）",
          ("yamada@" in p, "06-0000-0000" in p, "example.co.jp" in p), (False, False, True))


def test_lead_intake_never_drops_and_marks():
    print("\n■ 問い合わせの受付: 先に台帳へ書き、見分けに関係なく担当へ通知する（件名に印を付けるだけ）")
    base = {"referer": "https://corp.7senses.co.jp/contact", "first_ref": "www.google.co.jp", "first_utm": "",
            "first_ad": "", "first_land": "/blog/x/", "first_at": "2026-10-03", "send_page": "/contact"}
    posts = [
        dict(base, site="corporate", type="contact", name="山田", company="例", email="a@example.co.jp", message=SALES_EXAMPLES[4]),
        dict(base, site="corporate", type="contact", name="佐藤", company="例", email="b@example.co.jp", message=CONSULT_EXAMPLES[0]),
        dict(base, site="ai-lab", type="contact", name="原", company="例", email="t@7senses.co.jp", message="試し"),
        # Gemini が 500 → 正規表現。売り込みの定型文なら営業、そうでなければ相談
        dict(base, site="ai-lab", type="contact", name="鈴木", company="例", email="c@example.com",
             message="壊れる " + SALES_EXAMPLES[0]),
        dict(base, site="ai-lab", type="contact", name="田中", company="例", email="d@example.com", message="壊れる 見積もりをお願いします"),
        # Gemini が例外・読めない答え → 正規表現。記録と通知は落ちない
        dict(base, site="subsidy", type="contact", name="高橋", company="例", email="e@example.com", message="投げる 補助金の相談です"),
        dict(base, site="subsidy", type="contact", name="伊藤", company="例", email="f@example.com", message="読めない 補助金の相談です"),
        # 正規表現は売り込みと読むが、文脈では相談（Gemini を優先する）
        dict(base, site="corporate", type="contact", name="渡辺", company="例", email="g@example.com",
             message="突然のご連絡失礼いたします。御社の経理代行をお願いしたく、見積もりをください。"),
        # 別事業のサイト（通知を各サイトが自分で出す silent）。記録と見分けはする
        dict(base, site="partner", type="contact", name="1", company="", email="h@example.com", message="0", silent=True),
        # 疎通確認は台帳・通知に出さず、疎通確認のタブに流入経路の形で残す
        dict(base, site="ai-lab", type="contact", name="疎通確認", email="probe-1@pipeline-check.invalid", message="x"),
    ]
    r = _run({"props": {"GEMINI_API_KEY": "k"}, "posts": posts,
              "gemini": {"業務用の計算機器": {"kind": "売り込み", "reason": "機器の協業の提案"},
                         "壊れる": "fail", "投げる": "throw", "読めない": "garbage",
                         "経理代行をお願いしたく": {"kind": "相談", "reason": "経理代行の見積もり依頼"},
                         "名前: 1": {"kind": "テスト", "reason": "名前が数字だけ"}}})
    if r is None:
        print("  WARN  node が無いため受付の動きは確かめられません")
        return
    check("どの送信も受付は ok を返す（Gemini が落ちても送り主にエラーを出さない）",
          [x.get("ok") for x in r["results"]], [True] * len(posts))
    rows = r["rows"]
    check("疎通確認を除く全件が台帳に残る（見分けの前に書く）", len(rows), len(posts) - 1)
    check("台帳の行は14列のまま（列を増やさない）", sorted({len(x) for x in rows}), [14])
    temps = [x[12] for x in rows]
    check("温度の列: 売り込み→営業・相談→HOT/WARM/COOL・自社ドメイン→テスト・Gemini が使えなければ正規表現",
          [t if t in ("営業", "テスト") else "相談" for t in temps],
          ["営業", "相談", "テスト", "営業", "相談", "相談", "相談", "相談", "テスト"])
    check("詳細の列の末尾に判定と理由（誰が判定したか）を添える",
          [x[9].split("\n")[-1].split("／")[-1] for x in rows],
          ["Gemini", "Gemini", "決まり", "正規表現", "正規表現", "正規表現", "正規表現", "Gemini", "Gemini"])
    check("自社のドメインのアドレスは Gemini を呼ばない（呼んだのは自社ドメイン以外の8件）",
          sum("generativelanguage" in u for u in r["fetches"]), 8)
    staff = [m for m in r["mails"] if m["to"] == "info.ai@7senses.co.jp"]
    check("担当への通知は判定に関係なく必ず出す（silent の別事業のサイト・疎通確認だけ出さない）", len(staff), len(posts) - 2)
    check("件名に【売り込みの可能性】【テスト】の印を付ける",
          (sum("【売り込みの可能性】" in m["subject"] for m in staff), sum("【テスト】" in m["subject"] for m in staff)), (2, 1))
    replies = [m["to"] for m in r["mails"] if m["to"] != "info.ai@7senses.co.jp"]
    check("送り主への自動返信は売り込みにだけ出さない（テスト・相談には出す）",
          (any(t in replies for t in ("a@example.co.jp", "c@example.com")), "t@7senses.co.jp" in replies,
           all(t in replies for t in ("b@example.co.jp", "d@example.com", "e@example.com", "g@example.com"))), (False, True, True))
    check("送信元ページの列は「流入: …｜入口: …｜送信: …」", rows[0][11], "流入: Google検索（初回 10/03）｜入口: /blog/x/｜送信: /contact")
    check("疎通確認は台帳に入れず、疎通確認のタブの送信元に流入経路の形で残す（「不明」と書かない）",
          (len(r["probe"]), r["probe"][0][2] if r["probe"] else ""), (1, "流入: Google検索（初回 10/03）｜入口: /blog/x/｜送信: /contact"))
    check("Gemini の回数は1件につき1回で、月の上限の数に足す", r["props"].get("lead_ai_" + date.today().strftime("%Y-%m")), "8")

    over = _run({"props": {"GEMINI_API_KEY": "k", "lead_ai_" + date.today().strftime("%Y-%m"): "300"},
                 "posts": [dict(base, site="ai-lab", type="contact", name="x", email="z@example.com", message=SALES_EXAMPLES[1])]})
    check("月の上限に達したら Gemini を呼ばず正規表現で見分ける",
          (len(over["fetches"]), over["rows"][0][12], over["rows"][0][9].split("／")[-1]), (0, "営業", "正規表現"))
    nokey = _run({"posts": [dict(base, site="ai-lab", type="contact", name="x", email="z@example.com", message=CONSULT_EXAMPLES[1])]})
    check("鍵が無ければ Gemini を呼ばず、相談は相談のまま記録・通知する",
          (len(nokey["fetches"]), nokey["rows"][0][12] not in ("営業", "テスト"), len(nokey["mails"]) >= 1), (0, True, True))


def test_lead_existing_rows_mark_and_route():
    print("\n■ 既にある行: 運用者の判断で温度を直す（行番号と受信日の両方が合う行だけ）・推定の流入経路を入れる")
    row = lambda day, temp, ref: [day + "T03:00:00Z", "AI集客ラボ (ai.7senses.co.jp)", "無料相談", "会社", "名前", "", "a@example.com",
                                   "", "本文", "詳細", "", ref, temp, "未対応"]
    rows = [row("2026-08-21", "WARM", ""), row("2026-10-05", "HOT", "https://corp.7senses.co.jp/contact"),
            row("2026-10-06", "HOT", "流入: Google検索｜送信: /contact")]
    r = _run({"rows": rows, "posts": [
        {"action": "lead_mark", "secret": "$SECRET", "items": [
            {"row": 2, "day": "2026-08-21", "kind": "営業"}, {"row": 3, "day": "2026-10-04", "kind": "テスト"},
            {"row": 4, "day": "2026-10-06", "kind": "HOT"}]},
        {"action": "lead_mark", "items": [{"row": 2, "day": "2026-08-21", "kind": "営業"}]},
        {"action": "lead_route_fix", "secret": "$SECRET", "items": [
            {"row": 2, "day": "2026-08-21", "route": "推定 流入: ChatGPT｜入口: /｜送信: /contact"},
            {"row": 3, "day": "2026-10-05", "route": "推定 流入: Google検索｜入口: /｜送信: /contact"},
            {"row": 4, "day": "2026-10-06", "route": "推定 流入: X｜送信: /"},
            {"row": 2, "day": "2026-08-21", "route": "流入: X"}]},
    ]})
    if r is None:
        print("  WARN  node が無いため受付の動きは確かめられません")
        return
    mark, nosec, route = r["results"]
    check("温度を直すのは行番号と受信日が合い、kind が営業・テストの行だけ", ([x["row"] for x in mark["marked"]], len(mark["skipped"])), ([2], 2))
    check("合言葉の無い操作は断る", nosec.get("error"), "unauthorized")
    t = r["rows"]
    check("直した行は温度を変え、詳細の末尾に判断の印を足す。名前・本文・メールは変えない",
          (t[0][12], t[0][9].startswith("詳細\n判定: 売り込み（運用者の判断"), t[0][4], t[0][8], t[0][6]),
          ("営業", True, "名前", "本文", "a@example.com"))
    check("推定の流入経路は「推定」で始まり、空・URL だけの列にだけ入れる（受付で受け取った流入経路は上書きしない）",
          ([x["row"] for x in route["fixed"]], t[1][11].startswith("推定 流入: Google検索"), t[2][11]),
          ([2, 3], True, "流入: Google検索｜送信: /contact"))


def test_lead_route_and_ai_domains_match():
    print("\n■ 流入の名前: 受付（contact.hub.gs）と管制塔の Python（lead_reconcile）が同じ分類。AI は daily_kpi.AI_DOMAINS が正")
    import daily_kpi as DK
    import lead_reconcile as LR
    check("受付の AI の参照元の写しが daily_kpi.AI_DOMAINS と同じ", _js_json("LEAD_AI_DOMAINS"), DK.AI_DOMAINS)
    check("受付の AI の名前の写しが daily_kpi.AI_LABELS と同じ", _js_json("LEAD_AI_LABELS"), DK.AI_LABELS)
    m = re.search(r"const LEAD_REF_LABELS = \[(.*?)\n\];", CONTACT, re.S)
    js_ref = re.findall(r"\['([^']+)', '([^']+)'\]", m.group(1) if m else "")
    check("受付の AI 以外の参照元の表が lead_reconcile.REF_LABELS と同じ", js_ref, [tuple(x) for x in LR.REF_LABELS])
    cases = [("www.google.co.jp", "", ""), ("google.com", "", ""), ("chatgpt.com", "", ""), ("", "openai||", ""),
             ("gemini.google.com", "", ""), ("copilot.microsoft.com", "", ""), ("www.bing.com", "", ""),
             ("search.yahoo.co.jp", "", ""), ("t.co", "", ""), ("l.facebook.com", "", ""), ("mail.google.com", "", ""),
             ("", "", ""), ("", "", "gclid"), ("", "newsletter|email|2026-10", ""), ("", "google|cpc|brand", ""),
             ("lp.7senses.co.jp", "", ""), ("ai.7senses.co.jp", "", ""), ("example.com", "", ""), ("x.ai", "", ""),
             ("perplexity.ai", "", ""), ("claude.ai", "", ""), ("news.yahoo.co.jp", "", "")]
    r = _run({"calls": [["leadSource_", a, b, c, "ai.7senses.co.jp"] for a, b, c in cases]})
    if r is None:
        print("  WARN  node が無いため受付の動きは確かめられません")
        return
    sites = {"ai.7senses.co.jp": "AI集客ラボ", "lp.7senses.co.jp": "AI導入補助金サポート", "corp.7senses.co.jp": "コーポレート"}
    py = [LR.source_label(a, b, c, "ai.7senses.co.jp", sites) for a, b, c in cases]
    check("同じ参照元から同じ流入の名前（受付と Python）", r["calls"], py)
    check("流入の名前の実例", dict(zip([a or b or c or "（参照元なし）" for a, b, c in cases[:4]], py[:4])),
          {"www.google.co.jp": "Google検索", "google.com": "Google検索", "chatgpt.com": "ChatGPT", "openai||": "ChatGPT（utm: openai）"})
    check("参照元が無ければ直接、送ったサイトそのものは未記録、自社の別サイトは自社サイト（名前）",
          (py[11], py[16], py[15]), (LR.DIRECT, "未記録（記録を始める前の来訪）", "自社サイト（AI導入補助金サポート）"))
    check("GA4 の参照元からの推定も同じ名前（既存の行の推定に使う）",
          (LR.ga4_source_label("google", "organic"), LR.ga4_source_label("chatgpt.com", "ai-assistant"),
           LR.ga4_source_label("(direct)", "(none)"), LR.ga4_source_label("t.co", "referral")),
          ("Google検索", "ChatGPT", LR.DIRECT, "X"))
    rt = _run({"calls": [["leadRoute_", {"first_ref": "", "first_utm": "", "first_land": "/", "send_page": "/contact/"}, ""],
                         ["leadRoute_", {}, "https://lp.7senses.co.jp/service/dev/?x=1"],
                         ["leadRoute_", {}, ""]]})["calls"]
    check("流入の欄が無い古いページ・転送は「流入: 未記録」。送信ページは場所だけ（? 以降は落とす）",
          rt, [f"流入: {LR.DIRECT}｜入口: /｜送信: /contact/", "流入: 未記録｜送信: /service/dev/", "流入: 未記録"])


def test_lead_counts_exclude_sales_and_tests():
    print("\n■ 問い合わせの件数: 台帳の温度が「営業」「テスト」でない行だけを数え、除いた数を添える")
    import lead_reconcile as LR
    saved = dict(LR._LEDGER)
    try:
        LR._LEDGER["rows"] = [
            {"day": "2026-09-02", "sid": "subsidy", "type": "無料相談", "temp": "HOT", "route": ""},
            {"day": "2026-09-04", "sid": "ai-lab", "type": "無料相談", "temp": "営業", "route": ""},
            {"day": "2026-10-05", "sid": "ai-lab", "type": "無料診断", "temp": "テスト", "route": ""},
            {"day": "2026-10-05", "sid": "ai-lab", "type": "無料診断", "temp": "HOT", "route": ""},
            {"day": "2026-10-06", "sid": "ai-lab", "type": "資料ダウンロード", "temp": "COOL", "route": ""},
            {"day": "2026-10-07", "sid": "ai-lab", "type": "無料相談", "temp": "営業", "route": ""},
        ]
        c = LR.ledger_counts(LR.ledger_rows(), sid="ai-lab", start=date(2026, 10, 1), end=date(2026, 10, 31))
        check("相談・売り込み・テストを分けて数える", (c["consult"], c["sales"], c["test"]), (2, 1, 1))
        check("レポートに出す1行", LR.consult_text(c), "相談 2件（ほかに売り込み 1件・テスト 1件を除いた）")
        r = LR.leads("ai-lab", date(2026, 10, 1), date(2026, 10, 31), ga4_n=9)
        check("台帳に行のある社は台帳の相談の数（GA4 の送信9件は使わない）", (r["n"], r["source"]), (2, "ledger"))
        r = LR.leads("ai-lab", date(2026, 8, 1), date(2026, 8, 31), ga4_n=4)
        check("台帳の始まる前の月は GA4 の送信で数え、見分けていないと書く",
              (r["n"], r["source"], "見分けていません" in r["text"]), (4, "ga4", True))
        r = LR.leads("client-x", date(2026, 10, 1), date(2026, 10, 31), ga4_n=3)
        check("台帳に入らない社は GA4 の送信のまま", (r["n"], r["source"]), (3, "ga4"))
        f = LR.month_fields("ai-lab", date(2026, 10, 1), date(2026, 10, 31), 9)
        check("月次の欄: cv は台帳の相談、cv_ga4 に GA4 の送信を残す", (f["cv"], f["cv_ga4"], f["cv_source"], f["cv_counts"]["sales"]),
              (2, 9, "ledger", 1))
        import monthly_report as M
        html = M.cv_breakdown({"months": [dict(f, cv_parts={"フォーム": 9})]})
        check("月次レポートの内訳: 相談の数・除いた売り込み・テストを出し、GA4 は照合だけと書く",
              all(w in html for w in ("相談 2件（ほかに売り込み 1件・テスト 1件を除いた）", "除いた売り込み", "除いたテスト",
                                      "照合にだけ使います")), True)
    finally:
        LR._LEDGER.clear()
        LR._LEDGER.update(saved)
    src = {n: (ROOT / "scripts" / f"{n}.py").read_text(encoding="utf-8") for n in
           ("monthly_report", "group_report", "daily_kpi", "data_sanity", "report_audit", "report_verify")}
    check("件数を出すところは同じ数え方（lead_reconcile）を使う",
          {n: ("LR.month_fields" in s or "LR.leads" in s or "L.consult_text" in s or "_LR.month_fields" in s) for n, s in src.items()},
          {n: True for n in src})
    dash = (GAS / "dashboard.gs").read_text(encoding="utf-8")
    check("管制塔のダッシュボードも売り込み・テストを除き、除いた数を出す",
          all(w in dash for w in ("kindOf(r) !== '営業' && kindOf(r) !== 'テスト'", "除いた売り込み", "除いたテスト", "問い合わせの流入元")),
          True)


FIRST_HARNESS = r"""
const vm = require('vm');
const code = require('fs').readFileSync(0, 'utf8');
const store = {};
const mk = (path, referrer, search, broken) => ({
  localStorage: broken ? { getItem: () => { throw new Error('denied'); }, setItem: () => { throw new Error('denied'); } }
                       : { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } },
  location: { pathname: path, search: search || '' }, document: { referrer, addEventListener: () => {} },
  URL, URLSearchParams, Date, JSON, Object, String, window: {},
});
const run = (c) => { c.window = c; vm.createContext(c); vm.runInContext(code, c); return c.ssFirst(); };
const a = run(mk('/blog/x/', 'https://www.google.co.jp/', '?utm_source=openai'));
const b = run(mk('/contact/', 'https://lp.7senses.co.jp/blog/x/', ''));
const c = run(mk('/contact/', '', '', true));
console.log(JSON.stringify({ a, b, c }));
"""


def _first_snippet(text):
    """ページの JS から、最初の流入を覚える塊（ss_first を使う IIFE）だけを抜き出す"""
    i = text.find('"ss_first"')
    if i < 0:
        return ""
    s = text.rfind("(function", 0, i)
    e = text.find("})();", i)
    return text[s:e + 5] if s >= 0 and e >= 0 else ""


def test_lead_first_touch_on_every_site():
    print("\n■ 流入の欄: 4サイトのフォームが最初の流入元・入口・送信ページを送る（覚えられなくても送信は止めない）")
    sitejs = (ROOT / "site" / "js" / "site.js").read_text(encoding="utf-8")
    sys.path.insert(0, str(ROOT / "scripts" / "subsidy"))
    import turnstile_block as TB
    pages = (ROOT / "scripts" / "subsidy" / "pages.py").read_text(encoding="utf-8")
    subsidy_js = re.search(r'CHROME_JS = """(.*?)"""', pages, re.S).group(1)
    check("AI集客ラボ: 問い合わせ・資料・診断の送信に流入の欄を足す（site.js）",
          all(w in sitejs for w in ("window.ssFirst", 'name="first_land"', "send_page")), True)
    check("AI集客ラボ: AI紹介チェックの受付も流入の欄を台帳へ渡す",
          "...(x.first || {})" in (ROOT / "functions" / "api" / "ai-check.js").read_text(encoding="utf-8"), True)
    check("AI集客ラボ: 参照元の無い送信に「不明」と入れて管制塔へ送らない",
          '|| "不明"' in (ROOT / "functions" / "api" / "lead.js").read_text(encoding="utf-8")
          or '|| "不明"' in (ROOT / "functions" / "api" / "ai-check.js").read_text(encoding="utf-8"), False)
    check("補助金: 共通の枠が覚え、ロボットよけの送り口が送信に添える",
          ("window.ssFirst" in subsidy_js, "ssFirst()" in TB.BLOCK), (True, True))
    node = shutil.which("node")
    if not node:
        print("  WARN  node が無いため、ページの動きは確かめられません")
        return
    for name, text in (("AI集客ラボ", sitejs), ("補助金", subsidy_js)):
        p = subprocess.run([node, "-e", FIRST_HARNESS], input=_first_snippet(text), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
        if p.returncode:
            raise RuntimeError(f"{name}の流入の塊を動かせませんでした: {(p.stderr or p.stdout)[-300:]}")
        r = json.loads(p.stdout.strip().splitlines()[-1])
        check(f"{name}: 最初のページで参照元・utm・入口を覚え、後のページでも最初の値を送る（送信ページだけ今のページ）",
              (r["a"]["first_ref"], r["a"]["first_utm"], r["b"]["first_ref"], r["b"]["first_land"], r["b"]["send_page"]),
              ("www.google.co.jp", "openai||", "www.google.co.jp", "/blog/x/", "/contact/"))
        check(f"{name}: 保存できない環境でも、そのページの値で送る（送信を止めない）",
              (r["c"]["first_ref"], r["c"]["first_land"], r["c"]["send_page"], bool(re.match(r"^\d{4}-\d{2}-\d{2}$", r["c"]["first_at"]))),
              ("", "/contact/", "/contact/", True))


def test_lead_reconcile_skips_browser_probes():
    print("\n■ 照合: 本物のブラウザから送った疎通確認（GA4 の送信は出るが台帳に入らない）を、取りこぼしと数えない")
    import hub_sheets as H
    import lead_reconcile as LR
    day = (date(2026, 10, 10) - date(1899, 12, 30)).days + 0.5
    label = "AI集客ラボ (ai.7senses.co.jp)"
    fake = {"サイト一覧": [["ai-lab", "AI集客ラボ", "ai.7senses.co.jp"]],
            "疎通確認": [[day, label, "contact", "流入: Google検索（初回 10/10）｜入口: /aio/｜送信: /contact/"],
                        [day, label, "contact", "流入: 未記録"],
                        [day, label, "contact", "https://ai.7senses.co.jp/contact/"],
                        [day, label, "contact", "未記録（自動の疎通確認は参照元を送らない）"],
                        [day, label, "contact", "http://127.0.0.1:8701/"],
                        [day - 30, label, "contact", "流入: ChatGPT｜送信: /contact/"]]}
    saved = H.rows
    H.rows = lambda tab, cols: fake.get(tab, [])
    try:
        got = LR.browser_probes(date(2026, 10, 1))
    finally:
        H.rows = saved
    check("流入の欄つき・本番のページの URL の疎通確認だけ数え、スクリプト・手元（127.0.0.1）の疎通確認と期間の外は数えない",
          {k: dict(v) for k, v in got.items()}, {"ai-lab": {"2026-10-10": 2}})
