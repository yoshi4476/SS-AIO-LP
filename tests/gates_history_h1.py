# -*- coding: utf-8 -*-
"""問い合わせ台帳の営業メール・古い「要対応」・食い合い検査の判定不能（2026-10-04）。

3つとも「動いていないもの・古いものを、今の問題として読ませた」誤り。
営業メールに相談と同じ通知と自動返信を出す／10日前の findings.txt を今週の要対応として読ませる／
GSC を読めない日の kw_guard を「既存記事と食い合います」と書く。
"""
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from test_gates import check, ROOT

GS = ROOT / "automation" / "gas" / "contact.hub.gs"


def _sales_patterns():
    """contact.hub.gs の SALES_PATTERNS を Python の正規表現に移す（同じ式で判定するため）。"""
    src = GS.read_text(encoding="utf-8")
    body = src.split("const SALES_PATTERNS = [", 1)[1].split("];", 1)[0]
    return [re.compile(p) for p in re.findall(r"/((?:[^/\\\n]|\\.)+)/", body)]


def test_sales_inquiries_are_kept_but_silent():
    print("\n■ 問い合わせフォームの営業メールは、台帳に残して通知・自動返信・フォローを止める")
    src = GS.read_text(encoding="utf-8")
    check("SALES_PATTERNS がある", "const SALES_PATTERNS" in src, True)
    form = src.split("function form_(body) {", 1)[1].split("\nfunction ", 1)[0]
    i_probe = form.find("@pipeline-check")
    i_sales = form.find("isSales_(")
    i_save = form.find("leadSave_(")
    i_notify = form.find("leadNotify_(")
    check("form_: 疎通確認の後・記録の前に営業を判定する", 0 <= i_probe < i_sales < i_save, True)
    check("form_: 通知より前に営業を判定する", 0 <= i_sales < i_notify, True)
    check("form_: 営業なら温度を「営業」にする", "sales ? '営業'" in form, True)
    # 通知まで止めると、「弊社サービス」「業務提携」を含む本物の相談を見落とす。通知は印つきで出し、自動返信だけ止める
    check("form_: 営業らしい送信も担当には通知し、自動返信だけ止める",
          (bool(re.search(r"const silent = sales \|\|", form)), "if (!sales)" in form and "leadReply_" in form.split("if (!sales)", 1)[1][:200]),
          (False, True))
    check("通知: 営業らしい送信に「要確認」の印を付ける", "営業の可能性・要確認" in src, True)
    follow = src.split("function followUp() {", 1)[1].split("\nfunction ", 1)[0]
    check("followUp: 営業の行に送らない", "temp === '営業'" in follow, True)
    tool = src.split("function toolFollow_(", 1)[1].split("\nfunction ", 1)[0]
    check("toolFollow_: 営業の行に送らない", "'営業'" in tool, True)

    pats = _sales_patterns()
    check("SALES_PATTERNS を読み取れる", len(pats) >= 10, True)
    is_sales = lambda s: any(p.search(s) for p in pats)
    samples = [
        ("突然のご連絡失礼いたします。弊社では現在、AI受託開発の新しい取り組みを進めており…", True),
        ("貴社サービスが当社主催のテーマイベントにマッチすると考え、ご連絡しました。"
         "登壇・リード獲得（リード単価4,000円〜）のご案内です。", True),
        ("新事業進出ものづくり商業サービス補助金の申請についてご相談させてください。", False),
    ]
    for text, want in samples:
        check("営業の判定: " + text[:24], is_sales(text), want)


def test_findings_drops_stale_carry_over():
    print("\n■ findings.txt: 古いファイルの「要対応」を今の問題として持ち越さない")
    import findings as FD
    jst = timezone(timedelta(hours=9))
    now = datetime(2026, 10, 4, 10, 0, tzinfo=jst)
    old = now - timedelta(days=11)
    check("鮮度: 11日前の記録に印を付ける", FD.stale_note(old, now), "（古い記録・2026-09-23 時点）")
    check("鮮度: 2日前の記録には付けない", FD.stale_note(now - timedelta(days=2), now), "")
    check("鮮度: 時刻が分からなければ付けない", FD.stale_note(None, now), "")

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "findings.txt"
        p.write_text("# 生成: 2026-09-23 16:51 JST（この時点で検査を回し直した結果）\n"
                     "要対応: 生成AIの表示回数（手動の取り込み）\n"
                     "   2026-08 ぶんが未取込です: ai-lab\n"
                     "要対応: ラッコキーワードのクレジットが尽きました\n", encoding="utf-8")
        check("生成時刻を先頭の行から読む", FD.written_at(p),
              datetime(2026, 9, 23, 16, 51, tzinfo=jst))
        ts = old.timestamp()
        os.utime(p, (ts, ts))
        prev, note = FD.carry_over(p, set(), now)
        check("11日前のファイルからは持ち越さない", (prev, note), ([], "（古い記録・2026-09-23 時点）"))
        fresh = now - timedelta(hours=3)
        os.utime(p, (fresh.timestamp(),) * 2)
        prev, note = FD.carry_over(p, {"要対応: 生成AIの表示回数（手動の取り込み）"}, now)
        check("同じ回の追記は持ち越す（検査自身の行は除く）",
              (prev, note), (["要対応: ラッコキーワードのクレジットが尽きました"], ""))
    src = (ROOT / "scripts" / "findings.py").read_text(encoding="utf-8")
    check("findings.txt の先頭に生成時刻を書く", '"# 生成: %s JST' in src, True)
    check("findings.py は常に0で終わる", "return 0   # 知らせるのが仕事" in src, True)


def test_kw_guard_unknown_when_gsc_missing():
    print("\n■ kw_guard: GSC の鍵が無い日は「判定不能（3）」を返し、「要差別化（1）」と書かない")
    import auto_rewrite as AR
    import kw_guard as KG
    real = KG.CRED
    try:
        KG.CRED = ROOT / "存在しない鍵-zqx.json"
        lv, reasons = KG.judge("門の試験用の存在しない語 zqx", "ai-lab", use_gsc=True)
        failed = KG.gsc_rows.failed
    finally:
        KG.CRED = real
    check("鍵が無いと判定不能（3）を返す", lv, KG.UNKNOWN)
    check("判定不能の値は3", KG.UNKNOWN, 3)
    check("鍵が無いことを理由に出す", "鍵ファイルがありません" in failed, True)
    check("照合できなかった理由を出す", any(r[0] == "要確認" for r in reasons), True)
    lv0, _ = KG.judge("門の試験用の存在しない語 zqx", "ai-lab", use_gsc=False)
    check("--no-gsc では従来どおり照合なしで判定する", lv0, 0)
    src = (ROOT / "scripts" / "kw_guard.py").read_text(encoding="utf-8")
    check("判定の表示に「判定不能（GSCを読めません）」がある", "判定不能（GSCを読めません）" in src, True)

    m1, m3 = AR.guard_message(1), AR.guard_message(3)
    check("auto_rewrite: 1は食い合い", "既存記事と食い合います" in m1, True)
    check("auto_rewrite: 3は検査が動かなかったと書く",
          ("食い合いの検査が動きませんでした（鍵・通信を確認）" in m3, "既存記事と食い合います" in m3), (True, False))
    merge = (ROOT / "scripts" / "auto_merge.py").read_text(encoding="utf-8")
    check("auto_merge も同じ書き分けを使う", "AR.guard_message(r.returncode)" in merge, True)
    gate = (ROOT / "scripts" / "kw_gate.py").read_text(encoding="utf-8")
    check("kw_gate: 判定不能で語を退避・記事を隔離しない",
          ("level < 2 or level == 3" in gate, "if level == 2:" in gate), (True, True))


def test_inquiry_forms_carry_contact_preferences():
    print("\n■ 問い合わせフォーム: 希望の連絡方法・相談したい時期（任意）を3サイトとも管制塔へ渡す")
    src = GS.read_text(encoding="utf-8")
    form = src.split("function form_(body) {", 1)[1].split("\nfunction ", 1)[0]
    check("form_: 2項目を本文の末尾に添える（列を増やさない）",
          ("d.contact_way" in form, "d.contact_when" in form), (True, True))
    check("form_: 営業の判定より前に添える", form.find("d.contact_way") < form.find("isSales_("), True)
    pages = {
        "ai-lab LP": ROOT / "site" / "lp" / "index.html",
        "ai-lab 問い合わせ": ROOT / "site" / "contact" / "index.html",
        "補助金": ROOT / ".publish-work" / "subsidy" / "index.html",
        "コーポレート": ROOT / ".publish-work" / "corporate" / "src" / "components" / "ContactForm.tsx",
    }
    for name, p in pages.items():
        if not p.is_file():
            continue
        s = p.read_text(encoding="utf-8")
        check(f"{name}: 2項目がある", ("contact_way" in s, "contact_when" in s), (True, True))


def test_sticky_button_ab_is_counted_per_test():
    print("\n■ 診断ボタンの比べ試し: 試験ごとの名前で数え、記事CTAの試験と混ぜない")
    import build as B
    import ab_result as AB
    check("ai_check の固定ボタンに B案が付く", 'data-ab="sticky_ai"' in B.sticky_ab({"category": "aio"}), True)
    check("チェックリストの固定ボタンには付けない（試験しない）", "article_sticky_checklist" in str(B.STICKY_AB), False)
    tpl = (ROOT / "templates" / "article.html").read_text(encoding="utf-8")
    check("記事テンプレートが B案の属性を差し込む", "{{STICKY_AB}}" in tpl, True)
    js = (ROOT / "site" / "js" / "site.js").read_text(encoding="utf-8")
    check("site.js: 試験名入りの表示・押下を送る",
          ("'ab_impression_' + slugId(key) + '_' + v" in js, "'cta_click_' + slugId(abk) + '_' + abv" in js), (True, True))
    names = [t[0] for t in AB.tests()]
    check("ab_result: 記事CTAと固定ボタンを別々に判定する", names[0] == "記事CTA" and len(names) >= 3, True)
    for _k, (key, b) in B.STICKY_AB.items():
        check(f"B案に所要時間・結果の約束を書かない: {key}", any(w in b for w in ("秒", "必ず", "確実")), False)


def test_titles_and_closing_cta_follow_measured_patterns():
    print("\n■ 記事: 飾りの年号を新しい題に入れない／記事末の呼びかけを業種・カテゴリに合わせる")
    import score_check as SC
    import build as B
    for t, want in [("【2026年最新】AIO対策の手順", True), ("補助金2026年最新の締切", True),
                    ("建設業の2024年問題をAIで埋める", False), ("外注費の請求書｜2026年の変更点", False)]:
        check("飾りの年号の判定: " + t, bool(SC.DECOR_YEAR.search(t)), want)
    src = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    check("タイトルの書き直しで飾りの年号を外す", "飾りの年号は外してください" in src, True)
    tpl = (ROOT / "templates" / "article.html").read_text(encoding="utf-8")
    check("記事末の呼びかけはテンプレートに直書きしない", "{{CTA_COPY}}" in tpl and "プロに相談してみませんか" not in tpl, True)
    check("医療の記事は医療向けの呼びかけ", B.cta_copy({"category": "ai-marketing", "hub": "clinic"}) == B.CTA_COPY_IND["medical"]
          or "御院" in B.cta_copy({"category": "ai-marketing", "title": "クリニックの集客", "slug": "clinic-x"}), True)
    for k, v in {**B.CTA_COPY_IND, **B.CTA_COPY_CAT}.items():
        check(f"呼びかけで結果・期間を約束しない: {k}", any(w in v for w in ("必ず", "確実", "保証", "か月で", "上位表示")), False)


def test_subsidy_dist_ships_pages_we_link():
    print("\n■ 補助金サイト: 管制塔が作って sitemap に載せるページを、配信対象（make_dist）にも入れる")
    md = ROOT / ".publish-work" / "subsidy" / "tools" / "make_dist.py"
    if not md.is_file():
        return
    # 2026-10-04: 調査ページを sitemap に載せたが research/ が配信対象に無く、配信前の検査が「404になる」で
    # 約7時間・14回の配信を止めた（取り下げの301も届かなかった）
    # 10-03 の /seido/ も同じ。フォルダ名を1つずつ見ると次の新しいフォルダで再発するので、sitemap の全フォルダを見る
    m = re.search(r"PUBLIC_DIRS\s*=\s*\[(.*?)\]", md.read_text(encoding="utf-8"), re.S)
    dirs = set(re.findall(r'"([^"]+)"', m.group(1))) if m else set()
    sm = ROOT / ".publish-work" / "subsidy" / "sitemap.xml"
    tops = {u.split("/")[3] for u in re.findall(r"<loc>(https?://[^<]+)</loc>", sm.read_text(encoding="utf-8"))
            if len(u.split("/")) > 4} if sm.is_file() else set()
    check("sitemap に載るフォルダはすべて配信対象（make_dist の PUBLIC_DIRS）にある", sorted(tops - dirs), [])


def test_medical_and_shigyou_articles_state_supervision_scope():
    print("\n■ 医療・士業の記事: 医師・士業の監修者はいないので、監修の範囲（集客・Web施策）と公的な決まりの在りかを示す")
    import build as B
    tpl = (ROOT / "templates" / "article.html").read_text(encoding="utf-8")
    check("著者欄が監修の範囲を書く", "監修（集客・Web施策）" in tpl and "{{SCOPE_NOTE}}" in tpl, True)
    med = B.scope_note({"category": "ai-marketing", "hub": "clinic", "slug": "clinic-x", "title": "クリニックの集客"})
    check("医療の記事は厚労省の医療広告規制へリンクする", B.MHLW_AD in B.SCOPE_NOTE["medical"], True)
    for k, t in B.SCOPE_NOTE.items():
        check(f"医師・士業が監修したように書かない: {k}", any(w in t for w in ("医師監修", "医師が監修", "弁護士監修", "税理士監修")), False)
    check("業種の無い記事には付けない", B.scope_note({"category": "seo", "slug": "x", "title": "SEOの基本"}), "")


def test_ai_split_answers_go_back_into_articles():
    print("\n■ AIの答えが割れた問い: 調査の文をそのまま記事に入れ、新しい出典URLは足させない")
    import auto_rewrite as AR
    check("書き直しの種類 aisplit がある", "aisplit" in AR.WHAT, True)
    check("外部URLは Markdown と HTML の両方を数える",
          AR.ext_links('[a](https://x.go.jp/) <a href="https://y.jp/">b</a>'), {"https://x.go.jp/", "https://y.jp/"})
    src = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    check("検算: 調査の文がそのまま入ったか・URLが増えていないか", ("調査の文がそのまま入っていません" in src, "出典のURLが増えました" in src), (True, True))
    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週次で回す", "--kind aisplit" in wf, True)
    for x in AR.aisplit_items(50):
        check(f"渡す文は「当社調べ」の固定の言い回し: {x['slug']}", x["claims"][0].endswith("（当社調べ）"), True)


def test_corporate_aio_page_shows_survey_from_the_same_numbers():
    print("\n■ コーポレートのAIO運用代行: 業種別のAI出典調査の表を、ラボの集計そのものから作る")
    src = (ROOT / "scripts" / "research_publish.py").read_text(encoding="utf-8")
    check("数字は industry_ai_sources.headline から（手で書き写さない）", "IAS.headline(" in src and "def place_aio_data" in src, True)
    tsx = (ROOT / "templates" / "corporate_aio_data.tsx").read_text(encoding="utf-8")
    # 「ポータルが中心」と一律に書いて誤った（2026-10 の集計で29業種中16業種）。言える数をデータから数える
    check("見出しの「何業種中いくつ」をデータから数える", "portalWins" in tsx and "出典の中心" not in tsx, True)
    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週次で最新の数字に揃える", "research_publish.py --push" in wf, True)


def test_research_pages_count_only_engines_that_answered():
    print("\n■ 業種調査のページ: 「何つのAIに聞いたか」は実際に答えたAIの数で書く（固定の「4つ」にしない）")
    import industry_ai_sources as IAS
    check("答えたAIだけを数える", IAS.n_engines({"answered": {"ChatGPT": 0, "Claude": 50, "Gemini": 3}}), 2)
    for f in ("industry_ai_sources.py", "ai_ranking.py"):
        src = (ROOT / "scripts" / f).read_text(encoding="utf-8")
        body = src.split('"""', 2)[2] if src.lstrip().startswith(("# -*-", '"""')) and '"""' in src else src
        check(f"{f}: ページに出す文に「4つのAI」を固定で書いていない", "4つのAI" in body, False)


def test_research_refill_keeps_existing_answers_and_runs_in_ci():
    print("\n■ 業種調査の聞き直し: 既にある答えを消さず、欠けた問いだけ聞き足す。CI で毎日回す")
    run = (ROOT / "scripts" / "research_run.py").read_text(encoding="utf-8")
    # --sub で聞き直すと生の回答を丸ごと書き直し、Gemini の答えが6業種で消えた（2026-10-05）
    check("生の回答がある業種は --refill で聞き足す", '"--refill" if' in run, True)
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    check("生の回答は Git に入れる（CI で続きから聞くため）", any(l.strip() == "data/research/*-raw.json" for l in gi.splitlines()), False)
    import industry_ai_sources as IAS
    raw = {"engines": ["ChatGPT", "Claude"], "answers": {"問": {"group": "g", "ChatGPT": {"urls": ["https://a.jp/"], "error": ""}}}}
    IAS.fill_from_cache(raw)
    check("埋め戻しは、その調査で使ったAIと Gemini だけ（試しの Perplexity を混ぜない）", "Perplexity" in raw["engines"], False)
    wf = (ROOT / ".github" / "workflows" / "research-refill.yml").read_text(encoding="utf-8")
    check("CI: 毎日回し、更新されたログイン情報を Secrets に戻し、公開を起動する",
          ("cron:" in wf, "gh secret set CODEX_AUTH_JSON" in wf, "gh workflow run deploy.yml" in wf), (True, True, True))


def test_ai_visits_are_not_counted_as_organic():
    print("\n■ 月次レポート: ChatGPT 経由（openai / organic）を自然検索から外してAI経由に数える")
    import daily_kpi as D
    import monthly_report as M
    check("openai は ChatGPT", D.ai_label("openai"), "ChatGPT")
    check("パーソルの社内AIチャットはAI経由（2026-10-05 判断）", D.ai_label("chassu.chat-assistant.persol-group.co.jp"), "その他AI")
    check("google は AI ではない", D.ai_label("google"), None)

    class R:
        def __init__(self, ch, src, n):
            self.dimension_values = [type("V", (), {"value": ch}), type("V", (), {"value": src})]
            self.metric_values = [type("V", (), {"value": str(n)})]

    class GA:
        def run_report(self, req):
            return type("Rep", (), {"rows": [R("Organic Search", "google", 128), R("Organic Search", "openai", 10)]})
    got = M.ai_out_of_organic(GA(), "p", "2026-09-01", "2026-09-30", [("Organic Search", 138), ("AI Assistant", 27)])
    check("自然検索から引き、AI経由に足す", dict(got), {"Organic Search": 128, "AI Assistant": 37})
    for wf in ("research-refill.yml", "photo-shelf.yml", "industry-research.yml"):
        s = (ROOT / ".github" / "workflows" / wf).read_text(encoding="utf-8")
        check(f"{wf}: Codex を使う工程は同じ順番待ちで、更新されたログイン情報を戻す",
              ("group: industry-research" in s, "gh secret set CODEX_AUTH_JSON" in s), (True, True))


def _block_tag_issues(text):
    """原稿の段落（空行で区切った塊）ごとに、インラインの開きと閉じの数を比べる。
    記事全体で数えると、段落をまたいで閉じた <span>（数は合うが HTML は壊れる）を見逃す"""
    out = []
    body = re.sub(r"```.*?```", "", text, flags=re.S)
    for i, blk in enumerate(re.split(r"\n\s*\n", body)):
        for tag in ("span", "strong", "a"):
            o, c = len(re.findall(rf"<{tag}\b", blk)), len(re.findall(rf"</{tag}>", blk))
            if o != c:
                out.append(f"段落{i + 1}: <{tag}> 開き{o}・閉じ{c}")
    if re.search(r"</(content|answer|response)>", body):
        out.append("AIの出力の残り（</content> など）")
    return out


def test_articles_have_no_broken_inline_tags():
    print("\n■ 原稿: 段落をまたぐ <span> や AI の出力の残り（</content>）が無い")
    # 2026-10-05: 補助金の3記事の末尾に </content>、1記事は <span> が空行をまたいで閉じていた（本番の巡回で発見）
    check("検出器: 段落をまたいだ span を拾う", bool(_block_tag_issues('<span class="x">文。\n\n</span>次の段落')), True)
    check("検出器: 正しい span は拾わない", _block_tag_issues('<span class="x">文。</span>\n\n次の段落'), [])
    check("検出器: </content> を拾う", bool(_block_tag_issues("本文。\n</content>\n")), True)
    bad = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        issues = _block_tag_issues(p.read_text(encoding="utf-8-sig").split("\n---", 2)[-1])
        if issues:
            bad.append(f"{p.stem}: {issues[0]}")
    check("全記事", bad, [])


def test_intake_requires_client_supervisor():
    print("\n■ ヒアリングシート: 記事の監修者（お客様ご本人）を必須で聞き、同意が無ければ登録しない")
    import client_intake as C
    keys = [f[0] for f in C.fields_for()]
    check("監修者の章がある", all(k in keys for k in ("supervisor.name", "supervisor.qualification", "supervisor.consent", "supervisor.contact")), True)
    ng, _ = C.review({}, {"id": "x", "type": "self-static"})
    # FIELDS だけを見ていて、書き手・監修者の章の必須が効いていなかった（2026-10-05）
    check("必須の判定が書き手・監修者の章まで効く", any("監修者のお名前" in n for n in ng), True)
    got = {"supervisor.name": "佐藤 花子", "supervisor.consent": "未", "supervisor.contact": "sato@example.jp"}
    ng, _ = C.review(got, {"id": "x", "type": "self-static"})
    check("掲載の同意が「可」でなければ止める", any("掲載の同意" in n for n in ng), True)
    sup = C.to_company(dict(got, **{"supervisor.consent": "可"}))["supervisor"]
    check("確認の連絡先は会社情報（表示に使う側）に入れない", ("contact" in sup, sup["display"]), (False, True))


def test_selfheal_never_pushes_workflow_changes():
    print("\n■ 自動修復: ワークフローの変更は外して残りを反映し、変更案は成果物と通知で知らせる")
    wf = (ROOT / ".github" / "workflows" / "selfheal.yml").read_text(encoding="utf-8")
    # CI の鍵ではワークフローを push できず、修復の全体（50ファイル）が拒否されて捨てられた（2026-10-05）
    check("push の前にワークフローの変更を外す（2か所）", wf.count("git checkout -- .github/workflows") >= 2, True)
    check("変更案を成果物に残し、通知に書く", ("workflow-change" in wf, "ワークフローの変更案があります" in wf), (True, True))
    pr = (ROOT / "automation" / "selfheal_prompt.txt").read_text(encoding="utf-8")
    check("AIへの指示でワークフローを直してはいけない側に置く", pr.index(".github/workflows/") > pr.index("直してはいけない"), True)
