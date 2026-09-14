# -*- coding: utf-8 -*-
"""ヒアリングシートを1枚埋めれば、クライアントの運用が立ち上がる

これまでは sites/*.json を手で書き、会社情報と一次情報を別の場所に足し、
KWの起点を考え、CTAを設定する、という作業が散らばっていた。順番も
決まっておらず、抜けたまま記事を作り始めて後から気づくことがあった。

ここでは聞くことを1枚にまとめ、埋まった時点で必要なものが全部そろう。
特に一次情報（その会社にしか出せない数値）は、AI検索に引用されるかを
決める材料なので、空のまま先へ進ませない。

    python scripts/client_intake.py --sheet              # 記入用シートを作る
    python scripts/client_intake.py <記入済み.xlsx>       # 内容を確認する
    python scripts/client_intake.py <記入済み.xlsx> --apply   # 登録まで行う
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "docs" / "client" / "ヒアリングシート.xlsx"
SITES = ROOT / "sites"
sys.path.insert(0, str(ROOT / "scripts"))
from client_add import TYPES  # noqa: E402  形式の定義は1か所に置く

# ── 聞くこと ────────────────────────────────────
# (キー, 見出し, 説明, 記入例, 必須)
# キーの先頭が "#" の行は見出しだけを置く区切り
FIELDS = [
    ("#basic", "1. 会社の基本情報", "記事の著者情報・構造化データ・レポートの宛名に使います。"
     "表記がぶれると別法人と混同されるため、登記どおりに書いてください。", "", False),
    ("company.name", "会社名（正式）", "登記上の表記。株式会社の位置も登記どおりに",
     "セブンセンシズ株式会社", True),
    ("company.name_en", "英語表記", "無ければ空欄で構いません", "SEVEN SENSES Inc.", False),
    ("company.corporate_number", "法人番号", "13桁。国税庁の法人番号公表サイトで確認できます",
     "3120001227825", False),
    ("company.postal", "郵便番号", "ハイフンあり", "537-0003", False),
    ("company.address", "住所", "建物名・部屋番号まで", "大阪府大阪市東成区神路1丁目7-4 ○○ビル901", True),
    ("company.tel", "電話番号", "記事とサイトに掲載する番号", "06-0000-0000", True),
    ("company.hours", "営業時間", "問い合わせを受けられる時間帯",
     "9:00〜20:00（土・日・祝日を除く）", False),
    ("company.founded", "創業年月日", "「○年の実績」と書けるかの判断に使います", "2020年3月10日", False),
    ("company.capital", "資本金", "補助金の要件判定にも使います", "500万円", False),
    ("company.ceo", "代表者名", "記事の著者情報に使います", "山田 太郎", False),
    ("company.email", "問い合わせメール", "レポートの送付先にもなります", "info@example.co.jp", True),

    ("#media", "2. メディアの設計", "どこに、どんな形で記事を出すか。"
     "配信先が別リポジトリの場合は、書き込み権限のあるトークンが別途必要です。", "", False),
    ("id", "サイトID", "英小文字とハイフンのみ。ファイル名に使います", "example-media", True),
    ("name", "メディア名", "記事一覧やレポートに出る名前", "○○の集客ラボ", True),
    ("domain", "公開ドメイン", "https:// は不要", "media.example.co.jp", True),
    ("repo", "配信先リポジトリ", "owner/repo の形式。自社ビルドなら空欄", "example/media-site", False),
    ("branch", "ブランチ", "通常は main", "main", False),
    ("type", "サイトの形式",
     "self-static（当社が構築）/ external-md / external-html / nextjs-json のいずれか",
     "external-html", True),
    ("url_prefix", "記事URLの接頭辞", "記事が /blog/xxx/ に出るなら /blog", "/blog", False),
    ("content_dir", "記事の置き場所", "配信先リポジトリ内のパス", "src/content/blog", False),
    ("images_dir", "画像の置き場所", "同上", "public/images/blog", False),

    ("#offer", "3. 主力商材", "いちばん大切な項目です。ここが曖昧だと、"
     "表示回数は増えても問い合わせにつながらない記事が量産されます。", "", False),
    ("main_offer", "主力商材（1行）", "この記事群で最終的に売りたいもの",
     "経理BPO（記帳代行の受託）", True),
    ("main_category", "主力カテゴリ", "下のカテゴリ一覧のうち、主力商材に直結するもの",
     "keiri-bpo", True),
    ("categories", "カテゴリ一覧",
     "「slug: 表示名」を改行区切りで。slugは英小文字とハイフン",
     "keiri-bpo: 経理BPO\nkeiri-jitsumu: 経理実務\nbackoffice: バックオフィス", True),
    ("category_mix", "カテゴリの配分",
     "「slug: 割合」を改行区切り。合計100。主力を50%前後にすると相談につながりやすくなります",
     "keiri-bpo: 50\nkeiri-jitsumu: 40\nbackoffice: 10", False),

    ("#scope", "4. 対象読者と守備範囲", "「扱わない領域」を書いておくと、"
     "複数サイトを運用したときに記事同士が食い合うのを防げます。", "", False),
    ("theme", "何を扱うメディアか", "1行で", "中小企業の経理実務とバックオフィス効率化", True),
    ("audience", "誰に向けたものか", "1行で。役職や状況まで書けると精度が上がります",
     "経理担当が1〜2名の中小企業の経営者・管理部門責任者", True),
    ("owns", "自社が扱う語", "改行区切り。このメディアの守備範囲",
     "経理BPO\n記帳代行\n月次決算\n請求書処理", True),
    ("avoid", "扱わない領域", "改行区切り。理由も添えてください",
     "補助金の申請手続き（別サイトの担当領域のため）\n人材採用・労務", False),

    ("#kw", "5. キーワードの起点", "業種 × 意図の組み合わせで記事のテーマを作ります。"
     "200通り以上あると、半年ほど書き続けてもテーマが枯れません。", "", False),
    ("kw_seeds.industries", "業種・対象", "改行区切り。20件以上を目安に",
     "製造業\n建設業\n飲食店\nクリニック\n士業事務所", True),
    ("kw_seeds.intents", "検索の意図", "改行区切り。10件以上を目安に",
     "費用\nやり方\n選び方\n比較\n失敗事例\n対象条件", True),

    ("#facts", "6. 一次情報（最重要）",
     "その会社にしか出せない数値です。AI検索が最も引用したがる材料で、"
     "ここが空だと「どこにでもある記事」になり引用されません。"
     "確認できない数値は書かないでください（書いた時点で信頼を失います）。", "", False),
    ("facts.1.claim", "実績・数値 ①", "記事にそのまま書ける一文で",
     "経理BPOで通算120社の月次決算を受託してきました", True),
    ("facts.1.source", "① の出典", "自社実績 / 自社調査 / 顧客アンケート など", "自社実績", True),
    ("facts.1.as_of", "① の時点", "YYYY-MM。古い数値は使われません", "2026-09", True),
    ("facts.2.claim", "実績・数値 ②", "", "導入企業の月次決算が平均6営業日短縮しました", False),
    ("facts.2.source", "② の出典", "", "自社調査（受託42社・2025年実績）", False),
    ("facts.2.as_of", "② の時点", "", "2026-09", False),
    ("facts.3.claim", "実績・数値 ③", "", "", False),
    ("facts.3.source", "③ の出典", "", "", False),
    ("facts.3.as_of", "③ の時点", "", "", False),
    ("facts.note", "事例・体験",
     "数値でなくても、現場で見てきたことがあれば。記事の一人称パートに使います",
     "担当者が1人の会社ほど、退職時に業務が止まるリスクを挙げられます", False),

    ("#cta", "7. リード導線", "記事を読んだ人がどこへ進むか。"
     "全記事に必ず2箇所以上入れます。", "", False),
    ("cta.label", "ボタンの文言", "行動が分かる言葉で。「お問い合わせ」より具体的に",
     "経理の現状分析（無料）", True),
    ("cta.url", "遷移先URL", "問い合わせフォームやLPのURL",
     "https://example.co.jp/contact/", True),
    ("cta_title", "記事下の見出し", "", "経理の負担、どこから減らせるか見てみませんか", False),
    ("cta_desc", "記事下の説明文", "", "現状を伺ったうえで、外に出せる業務を整理してご提案します。", False),
    ("cta.note", "補足", "「ご契約を前提としたご案内ではありません」など安心材料",
     "ご契約を前提としたご案内ではありません", False),

    ("#measure", "8. 計測とレポート", "数字が取れないと改善の判断ができません。"
     "GA4とSearch Consoleへの権限付与をお願いします。", "", False),
    ("ga4_property_id", "GA4プロパティID", "数字のみ。管理画面 > 管理 > プロパティの詳細",
     "123456789", False),
    ("report_to", "レポートの送付先", "複数ある場合はカンマ区切り", "info@example.co.jp", False),
    ("gsc_ready", "Search Consoleの権限付与", "済 / 未 で記入。未の場合は導入時にご案内します",
     "未", False),

    ("#rule", "9. 運用のきまり", "業種による表現規制や、公開前の確認が必要かどうか。", "", False),
    ("monthly_cap", "月の公開本数", "既定は60本（1日2本）。減らす場合は数字を記入", "60", False),
    ("review_before_publish", "公開前の確認",
     "要 / 不要。医療・金融など表現規制のある業種では「要」を推奨します", "不要", False),
    ("ng_words", "使ってはいけない表現",
     "改行区切り。薬機法・景表法などで避ける語があれば",
     "完治\n必ず治る\n日本一", False),
    ("note", "その他の申し送り", "競合、過去の施策、社内の事情など何でも", "", False),
]

SAMPLE_ROW = 4          # 記入欄の開始行（1-2行目は説明、3行目は見出し）


# ============================================================
# シートを作る
# ============================================================
def make_sheet(path=SHEET):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "ヒアリングシート"
    navy = "0B2447"
    thin = Side(style="thin", color="D8DEE7")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws["A1"] = "オウンドメディア運用 ヒアリングシート"
    ws["A1"].font = Font(name="游ゴシック", size=16, bold=True, color=navy)
    ws["A2"] = ("水色の欄にご記入ください。「必須」の行が埋まれば運用を開始できます。"
                "分からない項目は空欄のままで構いません（導入時に一緒に決めます）。")
    ws["A2"].font = Font(name="游ゴシック", size=10, color="5B6B84")
    ws.merge_cells("A1:D1")
    ws.merge_cells("A2:D2")

    head = ["項目", "ご記入欄", "必須", "説明・記入例"]
    for i, h in enumerate(head, 1):
        c = ws.cell(row=3, column=i, value=h)
        c.font = Font(name="游ゴシック", size=10, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", start_color=navy)
        c.alignment = Alignment(vertical="center")
        c.border = border
    ws.row_dimensions[3].height = 22

    r = SAMPLE_ROW
    for key, label, desc, ex, req in FIELDS:
        if key.startswith("#"):
            c = ws.cell(row=r, column=1, value=label)
            c.font = Font(name="游ゴシック", size=11, bold=True, color=navy)
            c.fill = PatternFill("solid", start_color="E9EFF7")
            for col in range(1, 5):
                ws.cell(row=r, column=col).fill = PatternFill("solid", start_color="E9EFF7")
                ws.cell(row=r, column=col).border = border
            d = ws.cell(row=r, column=4, value=desc)
            d.font = Font(name="游ゴシック", size=9, color="5B6B84")
            d.alignment = Alignment(wrap_text=True, vertical="center")
            ws.row_dimensions[r].height = 30
            r += 1
            continue
        ws.cell(row=r, column=1, value=label).font = Font(name="游ゴシック", size=10)
        inp = ws.cell(row=r, column=2)
        inp.fill = PatternFill("solid", start_color="EEF6FD")
        inp.alignment = Alignment(wrap_text=True, vertical="top")
        rq = ws.cell(row=r, column=3, value="必須" if req else "")
        rq.font = Font(name="游ゴシック", size=9, bold=True,
                       color="B42318" if req else "5B6B84")
        rq.alignment = Alignment(horizontal="center", vertical="center")
        note = desc + (f"\n例）{ex}" if ex else "")
        n = ws.cell(row=r, column=4, value=note)
        n.font = Font(name="游ゴシック", size=9, color="5B6B84")
        n.alignment = Alignment(wrap_text=True, vertical="top")
        for col in range(1, 5):
            ws.cell(row=r, column=col).border = border
        ws.row_dimensions[r].height = 34 if "\n" in note else 22
        # キーは右端の隠し列に置く。読み取り時に見出しの表記ゆれで壊れないため
        ws.cell(row=r, column=6, value=key)
        r += 1

    dv = DataValidation(type="list", formula1='"self-static,external-md,external-html,nextjs-json"')
    ws.add_data_validation(dv)
    for row in range(SAMPLE_ROW, r):
        if ws.cell(row=row, column=6).value == "type":
            dv.add(ws.cell(row=row, column=2))
    yn = DataValidation(type="list", formula1='"要,不要"')
    ws.add_data_validation(yn)
    for row in range(SAMPLE_ROW, r):
        if ws.cell(row=row, column=6).value == "review_before_publish":
            yn.add(ws.cell(row=row, column=2))

    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 42
    ws.column_dimensions["C"].width = 6
    ws.column_dimensions["D"].width = 62
    ws.column_dimensions["F"].hidden = True
    ws.freeze_panes = "A4"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


# ============================================================
# シートを読む
# ============================================================
def read_sheet(path):
    from openpyxl import load_workbook
    ws = load_workbook(path, data_only=True).active
    got = {}
    for row in range(SAMPLE_ROW, ws.max_row + 1):
        key = ws.cell(row=row, column=6).value
        if not key or str(key).startswith("#"):
            continue
        v = ws.cell(row=row, column=2).value
        if v is None or str(v).strip() == "":
            continue
        got[str(key)] = str(v).strip()
    return got


def lines(v):
    return [x.strip() for x in re.split(r"[\n\r]+", v or "") if x.strip()]


def pairs(v, num=False):
    """「slug: 表示名」の並びを辞書にする"""
    out = {}
    for ln in lines(v):
        if ":" not in ln and "：" not in ln:
            continue
        k, _, val = ln.replace("：", ":").partition(":")
        val = val.strip()
        out[k.strip()] = int(re.sub(r"[^0-9]", "", val) or 0) if num else val
    return out


def to_config(got):
    """シートの回答を sites/<id>.json の形に組み立てる"""
    cfg = {
        "id": got.get("id", ""),
        "name": got.get("name", ""),
        "domain": got.get("domain", "").replace("https://", "").rstrip("/"),
        "repo": got.get("repo", ""),
        "branch": got.get("branch", "main"),
        "type": got.get("type", "external-html"),
        "url_prefix": got.get("url_prefix", "/blog"),
        "ga4_property_id": got.get("ga4_property_id", ""),
        "kw_plan": f"docs/kw-{got.get('id', 'client')}.md",
        "theme": got.get("theme", ""),
        "audience": got.get("audience", ""),
        "owns": lines(got.get("owns")),
        "avoid": lines(got.get("avoid")),
        "categories": pairs(got.get("categories")),
        "kw_seeds": {"industries": lines(got.get("kw_seeds.industries")),
                     "intents": lines(got.get("kw_seeds.intents"))},
        "main_offer": got.get("main_offer", ""),
        "main_category": got.get("main_category", ""),
        "cta": {"label": got.get("cta.label", ""), "url": got.get("cta.url", ""),
                "note": got.get("cta.note", "")},
    }
    for k in ("content_dir", "images_dir", "cta_title", "cta_desc", "note"):
        if got.get(k):
            cfg[k] = got[k]
    mix = pairs(got.get("category_mix"), num=True)
    if mix:
        cfg["category_mix"] = mix
    # 運用のきまり。既定と違うときだけ持たせる
    rule = {}
    if got.get("monthly_cap") and got["monthly_cap"] != "60":
        rule["monthly_cap"] = int(re.sub(r"[^0-9]", "", got["monthly_cap"]) or 60)
    if got.get("review_before_publish", "").startswith("要"):
        rule["review_before_publish"] = True
    if lines(got.get("ng_words")):
        rule["ng_words"] = lines(got["ng_words"])
    if rule:
        cfg["rules"] = rule
    if got.get("report_to"):
        cfg["report_to"] = [x.strip() for x in got["report_to"].replace("、", ",").split(",")
                            if x.strip()]
    return cfg


def to_company(got):
    out = {k.split(".", 1)[1]: v for k, v in got.items() if k.startswith("company.")}
    if out:
        out["_readme"] = ("この会社の正規表記。記事の著者情報・構造化データ・"
                          "レポートの宛名はすべてここを参照する。表記がぶれると"
                          "検索エンジンが同名の別法人と混同する。")
    return out


def to_facts(got, site_id):
    out = []
    for i in ("1", "2", "3"):
        claim = got.get(f"facts.{i}.claim")
        if not claim:
            continue
        out.append({"id": f"{site_id}-fact{i}", "sites": [site_id],
                    "topic": [], "claim": claim,
                    "source": got.get(f"facts.{i}.source", "自社実績"),
                    "as_of": got.get(f"facts.{i}.as_of", ""),
                    "verifiable": True})
    if got.get("facts.note"):
        out.append({"id": f"{site_id}-note", "sites": [site_id], "topic": [],
                    "claim": got["facts.note"], "source": "現場での観察",
                    "as_of": got.get("facts.1.as_of", ""), "verifiable": False})
    return out


# ============================================================
# 埋まっているかを見る
# ============================================================
def review(got, cfg):
    """記事を作り始める前に気づきたいことだけを見る。
    「あとで直せるもの」は警告、「直さないと回らないもの」は不備にする"""
    ng, warn = [], []

    missing = [label for key, label, _, _, req in FIELDS
               if req and not key.startswith("#") and not got.get(key)]
    for m in missing:
        ng.append(f"「{m}」が空です")

    if cfg.get("id") and not re.fullmatch(r"[a-z][a-z0-9-]*", cfg["id"]):
        ng.append("サイトIDは英小文字とハイフンのみで書いてください")
    if cfg.get("type") not in TYPES:
        ng.append(f"サイトの形式が不正です（{' / '.join(TYPES)}）")
    if cfg.get("type") != "self-static" and not cfg.get("repo"):
        ng.append("配信先リポジトリが空です（自社構築以外は書き込み先が要ります）")

    cats = cfg.get("categories") or {}
    if cfg.get("main_category") and cfg["main_category"] not in cats:
        ng.append(f"主力カテゴリ「{cfg['main_category']}」がカテゴリ一覧にありません")
    mix = cfg.get("category_mix") or {}
    if mix:
        unknown = set(mix) - set(cats)
        if unknown:
            ng.append(f"配分に無いカテゴリがあります: {sorted(unknown)}")
        total = sum(mix.values())
        if total and abs(total - 100) > 2:
            warn.append(f"カテゴリの配分の合計が{total}です（100になるよう調整してください）")
        main = mix.get(cfg.get("main_category"), 0)
        if main and main < 35:
            warn.append(f"主力カテゴリの配分が{main}%です。"
                        "40〜50%を下回ると、表示は増えても相談につながりにくくなります")

    # 既存サイトとの衝突。記事がどちらのものか決まらなくなる
    for p in SITES.glob("*.json"):
        other = json.loads(p.read_text(encoding="utf-8-sig"))
        if other.get("id") == cfg.get("id"):
            ng.append(f"サイトID「{cfg['id']}」は既にあります")
        if other.get("domain") and other["domain"] == cfg.get("domain"):
            ng.append(f"ドメインが {p.stem} と同じです")
        dup = set(cats) & set(other.get("categories", {}))
        if dup:
            ng.append(f"カテゴリ {sorted(dup)} が {p.stem} と重複しています")

    seeds = cfg.get("kw_seeds", {})
    n = len(seeds.get("industries", [])) * len(seeds.get("intents", []))
    if n < 200:
        warn.append(f"キーワードの起点が{n}通りです。"
                    "200通りを下回ると半年ほどでテーマが枯れます")
    if not cfg.get("avoid"):
        warn.append("扱わない領域が空です。他サイトとの食い合い検査が弱くなります")
    if not cfg.get("ga4_property_id"):
        warn.append("GA4プロパティIDが空です。レポートに流入データが出ません")
    if got.get("gsc_ready", "").startswith("未"):
        warn.append("Search Consoleの権限が未付与です。順位と検索語が取れません")

    facts = to_facts(got, cfg.get("id") or "client")
    hard = [f for f in facts if f.get("verifiable")]
    if not hard:
        ng.append("一次情報が1つも書かれていません。"
                  "その会社にしか出せない数値が無いと、AI検索に引用されません")
    elif len(hard) < 2:
        warn.append("一次情報が1つだけです。3つあると記事ごとに使い分けられます")
    for f in hard:
        if not re.fullmatch(r"\d{4}-\d{2}", f.get("as_of") or ""):
            warn.append(f"一次情報の時点が YYYY-MM の形式ではありません: {f['claim'][:24]}…")
    if not to_company(got).get("address"):
        warn.append("住所が空です。構造化データの会社情報が不完全になります")
    return ng, warn


def show(cfg, got, ng, warn):
    print(f"■ {cfg.get('name') or '（名称なし）'}（{cfg.get('id') or '?'}）")
    print(f"    形式    : {cfg.get('type')} … {TYPES.get(cfg.get('type'), '不明')}")
    print(f"    公開先  : {cfg.get('domain', '')}{cfg.get('url_prefix', '')}")
    print(f"    主力商材: {cfg.get('main_offer') or '（未記入）'}")
    cats = cfg.get("categories") or {}
    mix = cfg.get("category_mix") or {}
    if cats:
        s = " / ".join(f"{v}{('・' + str(mix[k]) + '%') if k in mix else ''}"
                       for k, v in cats.items())
        print(f"    カテゴリ: {s}")
    seeds = cfg.get("kw_seeds", {})
    print(f"    KWの起点: 業種{len(seeds.get('industries', []))} × "
          f"意図{len(seeds.get('intents', []))} = "
          f"{len(seeds.get('industries', [])) * len(seeds.get('intents', []))}通り")
    facts = to_facts(got, cfg.get("id") or "client")
    print(f"    一次情報: {len(facts)}件")
    for f in facts[:3]:
        print(f"        ・{f['claim'][:44]}  〔{f['source']} / {f['as_of']}〕")
    print()
    for m in ng:
        print(f"    × {m}")
    for m in warn:
        print(f"    ! {m}")
    if not ng and not warn:
        print("    すべて埋まっています")


# ============================================================
# 反映する
# ============================================================
def apply(got, cfg):
    site_id = cfg["id"]
    made = []

    out = SITES / f"{site_id}.json"
    out.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    made.append(out)

    # 会社情報と一次情報はクライアントごとに分ける。1つのファイルに混ぜると
    # 別のクライアントの実績を引いてしまう事故が起きる
    cdir = ROOT / "data" / "clients" / site_id
    cdir.mkdir(parents=True, exist_ok=True)
    comp = to_company(got)
    if comp:
        p = cdir / "company.json"
        p.write_text(json.dumps(comp, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        made.append(p)
    facts = to_facts(got, site_id)
    if facts:
        p = cdir / "facts.json"
        p.write_text(json.dumps(
            {"_readme": "この会社にしか出せない一次情報。記事はここから最低1つ引く。"
                        "確認できない数値は載せない（載せた瞬間に信頼を失う）。",
             "facts": facts}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        made.append(p)

    plan = ROOT / cfg["kw_plan"]
    if not plan.exists():
        plan.parent.mkdir(parents=True, exist_ok=True)
        seeds = cfg.get("kw_seeds", {})
        plan.write_text(
            f"# {cfg['name']} KW計画\n\n"
            f"- 主力商材: {cfg.get('main_offer', '')}\n"
            f"- 対象読者: {cfg.get('audience', '')}\n"
            f"- 守備範囲: {' / '.join(cfg.get('owns', []))}\n"
            f"- 扱わない: {' / '.join(cfg.get('avoid', [])) or '（未設定）'}\n\n"
            f"## 起点\n業種{len(seeds.get('industries', []))}件 × "
            f"意図{len(seeds.get('intents', []))}件\n\n"
            "（kw_discover.py が自動で補充します）\n", encoding="utf-8")
        made.append(plan)
    return made


def main():
    if "--sheet" in sys.argv:
        p = make_sheet()
        print(f"ヒアリングシートを作成しました: {p.relative_to(ROOT).as_posix()}")
        print("  クライアントにお渡しし、水色の欄をご記入いただいてください。")
        print(f"  記入後: python scripts/client_intake.py {p.name} --apply")
        return 0

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__.strip())
        return 1
    src = Path(args[0])
    if not src.is_file():
        src2 = SHEET.parent / src.name
        if src2.is_file():
            src = src2
        else:
            raise SystemExit(f"見つかりません: {src}")

    got = read_sheet(src)
    cfg = to_config(got)
    ng, warn = review(got, cfg)
    show(cfg, got, ng, warn)

    if ng:
        print(f"\n  {len(ng)}件の不備があるため反映しません。シートを直して再実行してください。")
        return 1
    if "--apply" not in sys.argv:
        print("\n  確認のみ（--apply を付けると登録します）")
        return 0

    made = apply(got, cfg)
    print("\n  作成したファイル")
    for p in made:
        print(f"    {p.relative_to(ROOT).as_posix()}")
    print("\n  次にやること")
    print(f"    1. python scripts/kw_discover.py --site {cfg['id']} --append   … KWを補充する")
    print("    2. GA4とSearch Consoleにサービスアカウントを追加してもらう")
    if cfg.get("type") != "self-static":
        print("    3. python scripts/token_check.py   … 配信先に書き込めるか確認する")
    if (cfg.get("rules") or {}).get("review_before_publish"):
        print("    ※ このクライアントは公開前の確認が必要です。自動公開を切ってください")
    return 0


if __name__ == "__main__":
    sys.exit(main())
