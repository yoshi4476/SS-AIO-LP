# -*- coding: utf-8 -*-
"""クライアント提案資料（PowerPoint版）

sales_deck.py はPDFの読み物。こちらは商談で1枚ずつ送る資料で、
並びを「成約までの流れ」に合わせてある:
  課題 → 原因 → 市場の変化 → 解決策 → 作り方 → 品質の担保
  → 自動改善 → 運用 → 実績 → 料金 → 比較 → 導入 → FAQ

数字はすべて自社サイトでの実測値。顧客に同じ成果を約束する書き方は
しない（優良誤認）。割合には必ず母数と期間を添える。

    python scripts/sales_pptx.py
    python scripts/sales_pptx.py --open
"""
import subprocess
import sys
from datetime import date
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "sales" / "service-proposal.pptx"
# 商談の直前に探し回らずに済むよう、デスクトップにも置く。
# レポートが Desktop/レポート一式 に出ているのと同じ考え方
DESK = Path.home() / "Desktop" / "提案資料"

# 料金・機能一覧・FAQ は sales_deck.py（PDF版）から引き継ぐ。
# 両方に書くと、料金改定のたびに片方だけ古くなる
sys.path.insert(0, str(ROOT / "scripts"))
from sales_deck import (AIO_FEATURES, FAQS, GATES, MARKET, OPS,  # noqa: E402
                        PHASES, PRICE, REPORT_ITEMS, SITE_FEATURES)

# ▼ 自社サイトでの実測値（2026年9月時点）。顧客への約束ではなく、
#   仕組みが実際に動いていることの証拠として示す
FACT = {
    "articles_total": 317, "sites": 3, "per_day": 6, "cap": 60,
    "min_score": 90, "checks": 19, "gates": 4,
    "ctr_weak": "1.04%", "ctr_strong": "2.80%",
    "boiler_before": "41.5%", "boiler_after": "12.1%",
}

NAVY = RGBColor(0x0B, 0x24, 0x47)
BLUE = RGBColor(0x25, 0x63, 0xEB)
TEAL = RGBColor(0x0D, 0x94, 0x88)
GOLD = RGBColor(0xB7, 0x92, 0x2E)
INK = RGBColor(0x1A, 0x22, 0x33)
MUTED = RGBColor(0x5B, 0x6B, 0x84)
LINE = RGBColor(0xE3, 0xEA, 0xF3)
SOFT = RGBColor(0xF5, 0xF8, 0xFC)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
RED = RGBColor(0xB4, 0x23, 0x18)

JP = "游ゴシック"
# A4横（297×210mm）。印刷して配れる判型にする。16:9より縦が長く、
# 1枚に入る情報量が増える。そのぶん余白を広めに取って息苦しくしない
W, H = Inches(11.693), Inches(8.268)
M = Inches(0.72)                      # 左右の余白
CW = W - M * 2                        # 本文の幅
TOP = Inches(0.6)                     # 天の余白
BOT = H - Inches(0.58)                # 地の罫線


# ============================================================
# 下ごしらえ
# ============================================================
def _font(run, size, bold=False, color=INK, name=JP):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = name                 # これは欧文（a:latin）だけを設定する
    # 日本語は東アジア用（a:ea）の指定がないと、別の書体に落ちる
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find(qn("a:ea"))
    if ea is None:
        ea = rPr.makeelement(qn("a:ea"), {})
        rPr.append(ea)
    ea.set("typeface", name)


def text(slide, x, y, w, h, s, size=14, bold=False, color=INK,
         align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, space=0, line=None,
         name=JP):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, part in enumerate(s.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(space)
        if line:
            p.line_spacing = line
        _font(p.add_run(), size, bold, color, name)
        p.runs[0].text = part
    return tb


def box(slide, x, y, w, h, fill=None, line_col=None, line_w=1.0,
        shape=MSO_SHAPE.RECTANGLE):
    sh = slide.shapes.add_shape(shape, x, y, w, h)
    sh.shadow.inherit = False
    if fill:
        sh.fill.solid()
        sh.fill.fore_color.rgb = fill
    else:
        sh.fill.background()
    if line_col:
        sh.line.color.rgb = line_col
        sh.line.width = Pt(line_w)
    else:
        sh.line.fill.background()
    sh.text_frame.word_wrap = True
    return sh


def slide(prs, no=None, title="", lead="", eyebrow=""):
    """本文ページの下地。章番号・見出し・リード文の位置を全ページで揃える"""
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg = s.background.fill
    bg.solid()
    bg.fore_color.rgb = WHITE
    y = TOP
    if eyebrow:
        text(s, M, y - Inches(0.04), CW, Inches(0.2), eyebrow, 9.5, True, TEAL)
        y += Inches(0.24)
    if no:
        text(s, M, y + Inches(0.07), Inches(0.5), Inches(0.28), no, 12.5, True, GOLD)
        tx = M + Inches(0.56)
    else:
        tx = M
    text(s, tx, y, CW - Inches(0.56), Inches(0.4), title, 23, True, NAVY)
    y += Inches(0.5)
    box(s, M, y, Inches(0.5), Pt(2.6), fill=GOLD)
    y += Inches(0.14)
    if lead:
        rows = 1 + lead.count("\n") + len(lead) // 74
        text(s, M, y, CW, Inches(0.28) * rows, lead, 12.5, False, MUTED, line=1.55)
        y += Inches(0.26) * rows
    return s, y + Inches(0.16)


def bullets(s, y, items, size=13, gap=0.42, bullet=True, w=None):
    """・つきの箇条書き。items は文字列、または (太字, 続き) の組"""
    w = w or CW
    for it in items:
        if bullet:
            box(s, M + Inches(0.02), y + Inches(0.09), Pt(5), Pt(5),
                fill=TEAL, shape=MSO_SHAPE.OVAL)
        x = M + Inches(0.2) if bullet else M
        if isinstance(it, tuple):
            tb = s.shapes.add_textbox(x, y - Inches(0.03), w - Inches(0.2), Inches(0.4))
            tf = tb.text_frame
            tf.word_wrap = True
            tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
            p = tf.paragraphs[0]
            p.line_spacing = 1.45
            r1 = p.add_run()
            r1.text = it[0]
            _font(r1, size, True, NAVY)
            r2 = p.add_run()
            r2.text = "　" + it[1]
            _font(r2, size, False, INK)
        else:
            text(s, x, y - Inches(0.03), w - Inches(0.2), Inches(0.4),
                 it, size, False, INK, line=1.45)
        y += Inches(gap)
    return y


def table(s, y, head, rows, widths, size=12, head_h=0.38, row_h=0.44):
    """罫線を引いた表。python-pptx の表は書式が硬いので図形で組む"""
    xs, x = [], M
    for fr in widths:
        xs.append(x)
        x += Emu(int(CW * fr))
    ws = [Emu(int(CW * fr)) for fr in widths]

    box(s, M, y, CW, Inches(head_h), fill=NAVY)
    for i, hcell in enumerate(head):
        text(s, xs[i] + Inches(0.14), y + Inches(0.08), ws[i] - Inches(0.2),
             Inches(0.25), hcell, size - 0.5, True, WHITE)
    y += Inches(head_h)
    for n, row in enumerate(rows):
        hgt = Inches(row_h)
        if n % 2 == 1:
            box(s, M, y, CW, hgt, fill=SOFT)
        box(s, M, y + hgt, CW, Pt(0.75), fill=LINE)
        for i, cell in enumerate(row):
            bold = isinstance(cell, tuple)
            val = cell[0] if bold else cell
            col = cell[1] if bold and len(cell) > 1 else INK
            text(s, xs[i] + Inches(0.14), y + Inches(0.09), ws[i] - Inches(0.24),
                 hgt - Inches(0.1), val, size, bold, col, line=1.3)
        y += hgt
    return y + Inches(0.2)


def cards(s, y, items, per=3, h=1.35, accent=BLUE):
    """見出し＋数字＋説明の小箱を横に並べる"""
    gap = Inches(0.22)
    w = Emu(int((CW - gap * (per - 1)) / per))
    for i, (k, v, note) in enumerate(items):
        col, row = i % per, i // per
        x = M + Emu(int((w + gap) * col))
        yy = y + Emu(int((Inches(h) + Inches(0.2)) * row))
        box(s, x, yy, w, Inches(h), fill=SOFT, line_col=LINE)
        box(s, x, yy, Pt(3), Inches(h), fill=accent)
        text(s, x + Inches(0.24), yy + Inches(0.17), w - Inches(0.4),
             Inches(0.24), k, 11.5, True, MUTED)
        text(s, x + Inches(0.24), yy + Inches(0.42), w - Inches(0.4),
             Inches(0.36), v, 20, True, NAVY)
        text(s, x + Inches(0.24), yy + Inches(0.86), w - Inches(0.4),
             Inches(0.44), note, 11, False, INK, line=1.35)
    rows_n = -(-len(items) // per)
    return y + Emu(int((Inches(h) + Inches(0.2)) * rows_n)) + Inches(0.1)


def foot(s, note=""):
    box(s, M, BOT, CW, Pt(0.75), fill=LINE)
    if note:
        rows = 1 + len(note) // 86
        text(s, M, BOT + Inches(0.1), CW - Inches(2.0), Inches(0.2) * rows,
             note, 8.5, False, MUTED, line=1.4)
    text(s, W - M - Inches(2.0), BOT + Inches(0.1), Inches(2.0), Inches(0.22),
         "セブンセンシズ株式会社", 8.5, False, MUTED, align=PP_ALIGN.RIGHT)


# ============================================================
# スライド
# ============================================================
def cover(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    box(s, 0, 0, W, H, fill=NAVY)
    box(s, 0, H - Inches(0.14), W, Inches(0.14), fill=GOLD)
    logo = ROOT / "site" / "images" / "company" / "logo-white.png"
    if logo.exists():
        s.shapes.add_picture(str(logo), M, Inches(0.72), height=Inches(0.46))
    text(s, M, Inches(2.15), Inches(10.4), Inches(0.4),
         "AI検索に引用される", 20, False, RGBColor(0x9E, 0xC0, 0xE8))
    text(s, M, Inches(2.62), Inches(11.0), Inches(1.6),
         "オウンドメディア\n構築・運用サービス", 46, True, WHITE, line=1.18)
    box(s, M, Inches(4.62), Inches(1.3), Pt(3.5), fill=GOLD)
    text(s, M, Inches(4.92), Inches(9.6), Inches(1.0),
         f"サイト構築から月{PRICE['articles']}本の記事更新、効果測定と改善までを一式で。\n"
         "御社の作業はゼロのまま、検索とAIの両方から見つかる状態をつくります。",
         14.5, False, RGBColor(0xC5, 0xD6, 0xEB), line=1.7)
    for i, b in enumerate(["AI検索（AIO/LLMO）対応", f"月{PRICE['articles']}記事",
                           "レポート・改善込み"]):
        box(s, M + Emu(int(Inches(2.72) * i)), Inches(6.15),
                 Inches(2.5), Inches(0.42), fill=None, line_col=RGBColor(0x3E, 0x5C, 0x82))
        text(s, M + Emu(int(Inches(2.72) * i)), Inches(6.25), Inches(2.5),
             Inches(0.3), b, 11.5, False, RGBColor(0xC5, 0xD6, 0xEB), align=PP_ALIGN.CENTER)
    text(s, W - M - Inches(3.2), Inches(6.25), Inches(3.2), Inches(0.3),
         date.today().strftime("%Y年%m月"), 11.5, False,
         RGBColor(0x7E, 0x9A, 0xBE), align=PP_ALIGN.RIGHT)


def s_summary(prs):
    s, y = slide(prs, "", "はじめに — このご提案の結論",
                 "細かい仕組みの説明に入る前に、御社にとって何が変わるのかを3つにまとめます。")
    y = cards(s, y, [
        ("記事が止まらない", f"月{PRICE['articles']}本",
         "担当者の退職や繁忙期に左右されず、毎日決まった時刻に公開されます"),
        ("品質が落ちない", f"{FACT['min_score']}点未満は公開不可",
         "基準に届かない記事は、システム上サイトに載せられません"),
        ("効かない記事が残らない", "毎週 自動で改善",
         "順位の出ていない記事を機械が特定し、手当てまで自動で行います"),
    ], per=3, h=1.55)
    y += Inches(0.12)
    box(s, M, y, CW, Inches(1.42), fill=SOFT, line_col=LINE)
    box(s, M, y, Pt(3), Inches(1.42), fill=GOLD)
    text(s, M + Inches(0.3), y + Inches(0.22), CW - Inches(0.6), Inches(0.3),
         "記事は「書いて終わり」ではなく、積み上がる資産です", 15, True, NAVY)
    text(s, M + Inches(0.3), y + Inches(0.62), CW - Inches(0.6), Inches(0.7),
         "広告は出稿を止めた瞬間に流入がゼロになります。検索とAI検索から入ってくる記事は、"
         "公開後も残り続けて集客を続けます。本サービスは、その資産を毎月積み上げる仕組みそのものをご提供するものです。",
         13, False, INK, line=1.6)
    foot(s)


def s_problem(prs):
    s, y = slide(prs, "01", "記事を書いても順位が上がらない理由",
                 "多くの企業が記事制作でつまずくのは、書く量ではなく次の3点です。")
    y = bullets(s, y, [
        ("書き手が続かない。",
         "担当者の異動・退職・繁忙期で更新が止まります。3ヶ月空くとサイト全体の評価が下がります。"),
        ("自社の記事同士が食い合う。",
         "似たテーマを重ねると、検索エンジンがどちらを出すか決められず、両方の順位が落ちます。"
         "これは記事が増えるほど起きやすくなります。"),
        ("品質の基準が人によってぶれる。",
         "忙しい週は薄い記事が通り、それがサイト全体の評価を引き下げます。"),
    ], gap=0.86)
    y += Inches(0.16)
    box(s, M, y, CW, Inches(1.5), fill=RGBColor(0xFC, 0xEF, 0xED), line_col=RGBColor(0xF0, 0xC8, 0xC2))
    text(s, M + Inches(0.3), y + Inches(0.2), CW - Inches(0.6), Inches(0.3),
         "食い合いは、目視では防げません", 14.5, True, RED)
    text(s, M + Inches(0.3), y + Inches(0.6), CW - Inches(0.6), Inches(0.8),
         "当社の運用でも、タイトルの類似チェックを通過した記事が、実際には8記事と狙う範囲が重なり、"
         "51の検索語で表示484回・クリック0という結果になったことがあります。"
         "タイトルが違っても、見出しの中身が重なれば食い合います。"
         "本サービスでは、この判定を検索コンソールの実績データに当てて機械的に行います。",
         12.5, False, INK, line=1.6)
    foot(s, "※ 記載の数値は当社運用サイトでの実測値です。")


def s_ai(prs):
    s, y = slide(prs, "02", "検索の入口が変わりつつあります",
                 "Googleの検索結果にAIの回答が表示され、ChatGPTやPerplexityで調べる人が増えています。")
    y = bullets(s, y, [
        ("AIの回答に引用されなければ、存在しないのと同じになります。",
         "利用者はAIの回答を読んで完結し、サイトまで来ないことが増えます。"),
        ("引用の前提は、今までどおり検索での上位表示です。",
         "AIは上位のページを読んで回答を作ります。SEOとAI対応は対立せず、二段構えで設計します。"),
        ("ただし上位でも、構造が整っていなければ引用されません。",
         "AIが抜き出せる形（冒頭の断言・見出しごとの結論・出典つきの数字）になっているかで差がつきます。"),
    ], gap=0.8)
    y += Inches(0.1)
    y = cards(s, y, [
        ("AIが最も引用したがるもの", "一次情報", "自社の実測値・体験・独自の数字"),
        ("AIが抜き出しやすい形", "1文結論", "見出し直下に40〜60字で結論を置く"),
        ("AIが評価する鮮度", "更新日の管理", "「◯年◯月時点」の明記と更新履歴"),
    ], per=3, h=1.3, accent=TEAL)
    foot(s)



TERM_OK2 = RGBColor(0x15, 0x78, 0x3D)
WARN2 = RGBColor(0x9A, 0x67, 0x00)


# ============================================================
# なぜ今か / 何が難しいか / 誰が何をやるか / 何が違うか
# ============================================================

# 全24工程。「AI」は機械が条件で決めるもの、「人」は判断が要るもの。
# ここを曖昧にしたまま「AIで自動化」と言うと、実態は人が徹夜で直すことになる
WORK = [
    ("事業の方向性を決める", "", "人", "どの商材を主力にするか。ここだけは代われません"),
    ("主力商材とカテゴリ配分", "", "人", "初回のヒアリングで一緒に設計します"),
    ("キーワードの候補出し", "AI", "", "競合の獲得語を抽出し、検索数と難易度を取る"),
    ("食い合いの判定", "AI", "", "検索コンソールの実績に当てて機械的に判定"),
    ("語の性質の判定", "AI", "", "「開かないと済まない語」かを採点する"),
    ("一次情報の材料提供", "", "人", "自社の実績数値。年1回の更新で足ります"),
    ("一次情報の収集", "AI", "", "動画字幕から数字・体験・つまずきを抽出"),
    ("競合の構造分析", "AI", "", "検索上位10記事の見出し構造を取得して分類"),
    ("構成の設計", "AI", "", "共通6〜7割＋独自3〜4割で組み立てる"),
    ("構成の事前審査（14項目）", "AI", "", "全項目を満たすまで執筆を開始しない"),
    ("本文の執筆", "AI", "", "5,000字以上。一次情報を2割以上織り込む"),
    ("AI感の排除（7項目）", "AI", "", "曖昧な結論・語尾の単調さなどを機械で検出"),
    ("機械採点（19項目）", "AI", "", "文字数・FAQ・リンク・構造を数える"),
    ("6観点120点の採点", "AI", "", "デザイン/SEO/編集/技術/読者/AI検索"),
    ("修正ループ", "AI", "", "基準に届くまで直して再採点する"),
    ("写真素材の提供", "", "人", "店舗・商品・スタッフの写真のみ"),
    ("図解・アイキャッチの生成", "AI", "", "1記事あたり4〜6枚を自動生成"),
    ("HTML化と構造化データ", "AI", "", "記事情報・FAQ・パンくず・手順を埋め込む"),
    ("公開と配信", "AI", "", "時刻を分けて公開。月の上限も機械で止める"),
    ("検索エンジンへの通知", "AI", "", "Google・Bingへ即時送信"),
    ("内部リンクの追加", "AI", "", "既存記事から新記事へ自動で送る"),
    ("効果測定", "AI", "", "直した日の前後で同じ日数を比較する"),
    ("タイトルの書き換え", "", "人", "対象はAIが特定。文章の判断は人が行う"),
    ("検索意図のずれの修正", "", "人", "同上。主張に関わる判断は自動化しない"),
    ("自動修正の見直し", "AI", "", "積み上がりと言い回しの偏りを検査する"),
    ("月次レポートの作成", "AI", "", "数字と改善指示まで自動で生成"),
    ("翌月の方針判断", "", "人", "レポートを見て決めるのは経営判断"),
]


def s_why_aio(prs):
    s, y = slide(prs, "02", "なぜ今、AIOへの対応が必要なのか",
                 "検索の入口が変わりつつあります。順位を取っても読まれない、"
                 "という状態が現実に起きています。", eyebrow="必要性")
    left = Emu(int(CW * 0.47))
    box(s, M, y, left, Inches(2.35), fill=RGBColor(0xFC, 0xEF, 0xED),
        line_col=RGBColor(0xF0, 0xC8, 0xC2))
    text(s, M + Inches(0.26), y + Inches(0.2), left - Inches(0.5), Inches(0.28),
         "いま起きていること", 12.5, True, RED)
    bullets_in(s, M + Inches(0.26), y + Inches(0.58), left - Inches(0.52), [
        "検索結果の上部にAIの回答が出る",
        "利用者はその回答を読んで完結する",
        "サイトまで来ないまま用事が済む",
        "ChatGPTやPerplexityで直接調べる人が増える",
    ], 11.5, RED)
    right = M + left + Inches(0.3)
    rw = CW - left - Inches(0.3)
    box(s, right, y, rw, Inches(2.35), fill=SOFT, line_col=LINE)
    text(s, right + Inches(0.26), y + Inches(0.2), rw - Inches(0.5), Inches(0.28),
         "そこで起きる分かれ目", 12.5, True, NAVY)
    bullets_in(s, right + Inches(0.26), y + Inches(0.58), rw - Inches(0.52), [
        "AIの回答に引用される = 社名ごと知られる",
        "引用されない = 存在しないのと同じになる",
        "引用の前提は、今までどおりの検索上位表示",
        "上位でも、抽出できない構造なら引用されない",
    ], 11.5, NAVY)
    y += Inches(2.6)
    text(s, M, y, CW, Inches(0.3),
         "だから、SEOとAIO（AI検索対策）は二段構えで設計します", 15, True, NAVY)
    y += Inches(0.46)
    y = cards(s, y, [
        ("第一段", "検索で上位を取る", "AIは上位のページを読んで回答を作ります。"
         "上位表示は今までどおり前提条件です"),
        ("第二段", "抽出できる形にする", "冒頭の断言・見出しごとの結論・"
         "出典つきの数字。AIが切り出せる構造にします"),
        ("結果", "指名検索が増える", "AIの回答に社名ごと載ることで、"
         "クリックされなくても認知が積み上がります"),
    ], per=3, h=1.34, accent=TEAL)
    foot(s, "※ ゼロクリック検索が増えても、引用され続ければ指名検索とご相談は増えます。"
            "「クリック数だけを見ていると気づけない変化」がここで起きています。")


def bullets_in(s, x, y, w, items, size=11.5, col=INK):
    """枠の中に置く小さめの箇条書き"""
    for it in items:
        box(s, x, y + Inches(0.08), Pt(4), Pt(4), fill=col, shape=MSO_SHAPE.OVAL)
        text(s, x + Inches(0.16), y - Inches(0.02), w - Inches(0.16), Inches(0.3),
             it, size, False, INK, line=1.4)
        y += Inches(0.34)
    return y


def s_dilemma(prs):
    s, y = slide(prs, "03", "記事は「量」が要る。しかし量を追うと質が落ちる",
                 "オウンドメディアが続かない理由は、この two つが同時に成り立たないことにあります。",
                 eyebrow="課題")
    half = Emu(int((CW - Inches(0.3)) / 2))
    box(s, M, y, half, Inches(1.72), fill=SOFT, line_col=LINE)
    box(s, M, y, Pt(3), Inches(1.72), fill=BLUE)
    text(s, M + Inches(0.26), y + Inches(0.18), half - Inches(0.5), Inches(0.3),
         "量が要る理由", 13, True, NAVY)
    text(s, M + Inches(0.26), y + Inches(0.58), half - Inches(0.52), Inches(1.0),
         "検索されるテーマは業種ごとに数百あります。1テーマ1記事なので、"
         "カバーするには本数が要ります。月に数本では、"
         "拾える検索語がいつまでも増えません。", 11.5, False, INK, line=1.55)
    x2 = M + half + Inches(0.3)
    box(s, x2, y, half, Inches(1.72), fill=SOFT, line_col=LINE)
    box(s, x2, y, Pt(3), Inches(1.72), fill=RED)
    text(s, x2 + Inches(0.26), y + Inches(0.18), half - Inches(0.5), Inches(0.3),
         "質が落ちる理由", 13, True, NAVY)
    text(s, x2 + Inches(0.26), y + Inches(0.58), half - Inches(0.52), Inches(1.0),
         "本数を増やすほど、1本にかけられる時間が減ります。"
         "忙しい週は薄い記事が通り、似たテーマが重なって"
         "自社の記事同士が食い合います。", 11.5, False, INK, line=1.55)
    y += Inches(1.98)
    text(s, M, y, CW, Inches(0.3), "量を作る3つの方法と、それぞれの限界", 14, True, NAVY)
    y += Inches(0.42)
    y = table(s, y, ["方法", "量", "質", "続くか", "実際に起きること"],
              [["外注ライター", ("○", TERM_OK2), ("△", WARN2), ("△", WARN2),
                "1本ずつ発注・確認が要る。担当が変わると品質が揺れる"],
               ["社内で採用", ("△", WARN2), ("○", TERM_OK2), ("×", RED),
                "採用に数ヶ月。退職すると更新が止まり、評価も下がる"],
               ["AIツールに書かせる", ("◎", TERM_OK2), ("×", RED), ("△", WARN2),
                "量は出るが、食い合いと薄さの判定が誰もできない"]],
              [0.17, 0.06, 0.06, 0.08, 0.63], row_h=0.5)
    box(s, M, y, CW, Inches(0.86), fill=RGBColor(0xEB, 0xF2, 0xFC), line_col=BLUE)
    text(s, M + Inches(0.28), y + Inches(0.16), CW - Inches(0.56), Inches(0.6),
         "本サービスは「量はAIエージェント、質は機械の検査、判断は人」に分けます。"
         "量と質のどちらかを諦める必要がなくなります。", 12.5, True, NAVY, line=1.5)
    foot(s)


def s_roles(prs, part):
    """人とAIの分担。営業でいちばん聞かれるところなので全工程を出す"""
    rows = WORK[:14] if part == 1 else WORK[14:]
    s, y = slide(prs, "09",
                 f"人がやること / AIエージェントがやること（{part}/2）",
                 "全27工程の内訳です。判断が要るものだけを人に残し、"
                 "条件で決まるものは機械に任せます。" if part == 1 else
                 "公開してからの工程です。効果測定と手当ては自動、"
                 "文章の判断は人が行います。", eyebrow="役割分担")
    y = table(s, y, ["工程", "AI", "人", "中身"],
              [[r[0], (r[1], BLUE) if r[1] else "",
                (r[2], GOLD) if r[2] else "", r[3]] for r in rows],
              [0.245, 0.05, 0.05, 0.655], row_h=0.35, size=11)
    if part == 2:
        box(s, M, y, CW, Inches(0.8), fill=SOFT, line_col=LINE)
        text(s, M + Inches(0.28), y + Inches(0.15), CW - Inches(0.56), Inches(0.55),
             "人に残るのは「方向性の決定」「素材の提供」「文章の最終判断」の3つだけです。"
             "合計しても月に1〜2時間程度が目安になります。", 12, True, NAVY, line=1.5)
    foot(s, "※ 「AI」は条件で機械的に決まるもの、「人」は判断が要るものです。"
            "文章の主張に関わる判断を自動化すると、主張のずれた記事が量産されるため分けています。"
            if part == 2 else "")


def s_vs_consult(prs):
    s, y = slide(prs, "22", "一般的なSEO支援と、何が違うのか",
                 "「SEOコンサル」「記事制作代行」「AIライティングツール」と比べます。"
                 "どれも一部は重なりますが、担う範囲が違います。", eyebrow="優位点")
    y = table(s, y, ["", "SEOコンサル", "記事制作代行", "AIツール", "本サービス"],
              [["助言・戦略", "◎", "×", "×", ("○", BLUE)],
               ["記事の執筆", "×", "◎", "○", ("◎", BLUE)],
               ["図解の作成", "×", "△", "×", ("◎", BLUE)],
               ["公開作業", "×", "△", "×", ("◎", BLUE)],
               ["AI検索への対応", "△", "△", "×", ("◎", BLUE)],
               ["食い合いの機械判定", "×", "×", "×", ("◎", BLUE)],
               ["品質の物理ガード", "×", "×", "×", ("◎", BLUE)],
               ["公開後の効果測定", "○", "×", "×", ("◎", BLUE)],
               ["効かない記事の自動改善", "×", "×", "×", ("◎", BLUE)],
               ["自社に残る作業", "多い", "中", "多い", ("ほぼ無し", BLUE)]],
              [0.28, 0.16, 0.16, 0.14, 0.26], row_h=0.36, size=11)
    box(s, M, y, CW, Inches(0.92), fill=RGBColor(0xEB, 0xF2, 0xFC), line_col=BLUE)
    text(s, M + Inches(0.28), y + Inches(0.16), CW - Inches(0.56), Inches(0.65),
         "いちばんの違いは、下の4行です。食い合いの判定・品質の物理ガード・効果測定・"
         "自動改善は、助言でもツールでも代われません。仕組みとして組み込んで初めて回ります。",
         12, True, NAVY, line=1.5)
    foot(s, "※ ◎=標準で含む ○=含むことが多い △=会社による ×=含まないことが多い。"
            "一般的なサービス内容にもとづく比較であり、個別の事業者を指すものではありません。")


def s_overview(prs):
    s, y = slide(prs, "04", "ご提供するものの全体像",
                 "サイトの構築から記事の制作・公開・効果測定・改善まで、一式でお引き受けします。")
    y = table(s, y, ["項目", "担当", "内容"],
              [[("サイトの構築", NAVY), ("当社", BLUE), "オウンドメディア＋サービスLP。AI検索対応を実装済みの状態で納品"],
               [("記事の企画・執筆・図解", NAVY), ("当社", BLUE), f"月{PRICE['articles']}本。1本5,000字以上＋画像4〜6枚。御社の作業はゼロ"],
               [("公開・インデックス登録", NAVY), ("当社", BLUE), "自動で公開し、GoogleとBingへ即時通知"],
               [("効果測定・改善", NAVY), ("当社", BLUE), "毎日の集計、毎週のリライト、毎月のレポート"],
               [("方向性の決定", NAVY), ("御社", TEAL), "どの商材を主力にするか。初回ヒアリングで設計します"],
               [("写真素材のご提供", NAVY), ("御社", TEAL), "店舗・商品・スタッフの写真（記事内の図解は当社が作成）"]],
              [0.22, 0.1, 0.68], row_h=0.52)
    foot(s)


def s_site(prs):
    s, y = slide(prs, "05", "サイト構築で作るもの",
                 "記事を置くだけの箱ではなく、問い合わせにつながる導線まで作り込んだ状態で納品します。")
    for k, v in SITE_FEATURES:
        box(s, M, y, Inches(2.5), Inches(0.52), fill=SOFT, line_col=LINE)
        text(s, M + Inches(0.16), y + Inches(0.14), Inches(2.2), Inches(0.3),
             k, 12, True, NAVY)
        text(s, M + Inches(2.72), y + Inches(0.06), CW - Inches(2.72), Inches(0.48),
             v, 11.5, False, INK, line=1.4)
        y += Inches(0.6)
    foot(s)


def s_aio(prs, part):
    half = AIO_FEATURES[:6] if part == 1 else AIO_FEATURES[6:]
    s, y = slide(prs, "06" if part == 1 else "07", f"AI検索に引用されるための12の実装（{part}/2）",
                 "記事の書き方だけでなく、サイト側の実装でAIに読ませる状態を作ります。"
                 if part == 1 else "記事1本ごとに、以下の形を全て満たした状態で公開します。")
    for i, (k, v) in enumerate(half):
        yy = y + Emu(int(Inches(0.86) * i))
        box(s, M, yy, Inches(0.34), Inches(0.34), fill=TEAL)
        text(s, M, yy + Inches(0.05), Inches(0.34), Inches(0.26),
             str(i + 1 + (0 if part == 1 else 6)), 12, True, WHITE, align=PP_ALIGN.CENTER)
        text(s, M + Inches(0.5), yy - Inches(0.02), CW - Inches(0.5), Inches(0.3),
             k, 13.5, True, NAVY)
        text(s, M + Inches(0.5), yy + Inches(0.28), CW - Inches(0.5), Inches(0.5),
             v, 11.5, False, INK, line=1.4)
    foot(s)



def s_flow(prs):
    s, y = slide(prs, "08", f"記事{PRICE['articles']}本はこう作られます",
                 "1本あたり7つの工程を通ります。各工程の完了を確認してから次へ進み、飛ばせない形にしてあります。")
    for i, (no, k, v) in enumerate(PHASES):
        yy = y + Emu(int(Inches(0.74) * i))
        box(s, M, yy + Inches(0.04), Inches(0.44), Inches(0.44), fill=NAVY)
        text(s, M, yy + Inches(0.13), Inches(0.44), Inches(0.28),
             no, 13, True, WHITE, align=PP_ALIGN.CENTER)
        if i < len(PHASES) - 1:
            box(s, M + Inches(0.21), yy + Inches(0.48), Pt(1.2), Inches(0.26), fill=LINE)
        text(s, M + Inches(0.64), yy, Inches(2.7), Inches(0.3), k, 13.5, True, NAVY)
        text(s, M + Inches(3.4), yy + Inches(0.01), CW - Inches(3.4), Inches(0.64),
             v, 11.5, False, INK, line=1.4)
    foot(s, "※ 工程04の文字数は記事の種類で変わります（手順3,000字〜／比較検討5,000字〜／網羅ガイド8,000字〜）。"
            "全記事を同じ長さに揃えると、それ自体が機械生成の痕跡になるためです。")



def s_sheet(prs):
    """御社にしていただくことの具体。営業でいちばん不安がられるところ"""
    s, y = slide(prs, "10", "ご記入いただくのは、この1枚だけです",
                 "記事づくりに必要な情報を1枚のシートにまとめてあります。"
                 "ご記入は最初の1回のみ。所要時間は30分ほどです。",
                 eyebrow="御社にしていただくこと")
    y = table(s, y, ["ご記入いただくこと", "記事のどこになるか"],
              [[("主力商材とカテゴリの配分", NAVY),
                "記事の結論をどこへ着地させるか。ここが曖昧だと、読まれても相談につながりません"],
               [("ターゲット（人物像・商圏）", NAVY),
                "誰に向けて書くか。1人の顔が浮かぶ粒度まで伺います"],
               [("メインキーワード / サブキーワード", NAVY),
                "掛け合わせて記事の主題を作ります。実例では メイン3語＋サブ4語 から主題候補50件"],
               [("実績の数値（3つまで）", NAVY),
                "AI検索が最も引用したがる一次情報。出典と時点をセットで伺います"],
               [("よく聞かれる質問（5つ以上）", NAVY),
                "記事のFAQにそのまま載ります。お客様の言葉のまま使えるほど強くなります"],
               [("著者名・肩書き・保有資格", NAVY),
                "記事の著者情報。誰が書いたか分からない記事は検索にもAIにも信用されません"],
               [("文体・使いたくない表現", NAVY),
                "全記事の書き方が揃います。既存サイトがあればそちらに合わせます"],
               [("外部との接点（加盟団体・取引先・取材）", NAVY),
                "他サイトからリンクされる起点。買うことはできないので、"
                "すでにある関係から広げます"]],
              [0.3, 0.7], row_h=0.5, size=11.5)
    box(s, M, y, CW, Inches(0.94), fill=SOFT, line_col=LINE)
    text(s, M + Inches(0.28), y + Inches(0.16), CW - Inches(0.56), Inches(0.64),
         "ご記入いただいた内容は、記事を書くたびに読み込まれます。"
         "書かれていないことは書きません。憶測で補うと、事実と違う記事が公開されるためです。",
         12, True, NAVY, line=1.5)
    foot(s, "※ 分からない項目は空欄のままで構いません。導入時のお打ち合わせで一緒に決めます。")


def s_sheet_industry(prs):
    s, y = slide(prs, "11", "業種によって、聞くことを変えています",
                 "同じ質問票では、その業種でしか書けない記事になりません。"
                 "業種ごとに専用の項目をご用意しています。", eyebrow="御社にしていただくこと")
    half = Emu(int((CW - Inches(0.3)) / 2))
    box(s, M, y, half, Inches(2.5), fill=SOFT, line_col=LINE)
    box(s, M, y, Pt(3), Inches(2.5), fill=BLUE)
    text(s, M + Inches(0.26), y + Inches(0.18), half - Inches(0.5), Inches(0.28),
         "共通（全業種）", 13, True, NAVY)
    text(s, M + Inches(0.26), y + Inches(0.52), half - Inches(0.5), Inches(0.24),
         "95項目 / 18セクション", 11, True, BLUE)
    bullets_in(s, M + Inches(0.26), y + Inches(0.88), half - Inches(0.52), [
        "会社情報・著者・文体",
        "主力商材とカテゴリの配分",
        "ターゲットと狙うキーワード",
        "実績の数値・よくある質問",
        "外部との接点（被リンクの起点）",
    ], 11, BLUE)
    x2 = M + half + Inches(0.3)
    box(s, x2, y, half, Inches(2.5), fill=RGBColor(0xEB, 0xF2, 0xFC), line_col=BLUE)
    box(s, x2, y, Pt(3), Inches(2.5), fill=TEAL)
    text(s, x2 + Inches(0.26), y + Inches(0.18), half - Inches(0.5), Inches(0.28),
         "飲食店向け（追加分）", 13, True, NAVY)
    text(s, x2 + Inches(0.26), y + Inches(0.52), half - Inches(0.5), Inches(0.24),
         "124項目 / 23セクション", 11, True, TEAL)
    bullets_in(s, x2 + Inches(0.26), y + Inches(0.88), half - Inches(0.52), [
        "席数・客単価・最寄駅と徒歩分数",
        "看板メニューと価格・食材の産地",
        "予約の受付方法・貸切の可否",
        "グルメサイトと地図サービスの状況",
        "景品表示法で使えない表現",
    ], 11, TEAL)
    y += Inches(2.74)
    box(s, M, y, CW, Inches(1.0), fill=SOFT, line_col=LINE)
    text(s, M + Inches(0.28), y + Inches(0.16), CW - Inches(0.56), Inches(0.7),
         "たとえば飲食店の記事で「明石浦漁港から毎朝直送」「JR大阪駅から徒歩6分」と書けるかどうかで、"
         "記事の説得力はまったく変わります。AI検索も、固有の地名・食材名・産地を手がかりに引用します。"
         "経理代行に席数を伺っても意味がないように、必要な材料は業種ごとに違います。",
         12, False, INK, line=1.55)
    foot(s, "※ 上記以外の業種も、同じ考え方で専用シートをご用意します（クリニック・士業・工務店など）。")


def s_gates(prs):
    s, y = slide(prs, "12", "品質を落とさない四重の検査",
                 "「気をつける」では品質は保てません。基準を割った記事が物理的に公開できない形にしてあります。")
    for i, (k, n, v) in enumerate(GATES):
        yy = y + Emu(int(Inches(1.14) * i))
        col = RED if i == len(GATES) - 1 else BLUE
        box(s, M, yy, CW, Inches(0.96), fill=WHITE, line_col=LINE)
        box(s, M, yy, Pt(3.5), Inches(0.96), fill=col)
        text(s, M + Inches(0.26), yy + Inches(0.15), Inches(3.0), Inches(0.3),
             k, 14, True, NAVY)
        box(s, M + Inches(3.5), yy + Inches(0.13), Inches(2.1), Inches(0.32),
            fill=SOFT, line_col=col)
        text(s, M + Inches(3.5), yy + Inches(0.19), Inches(2.1), Inches(0.24),
             n, 11, True, col, align=PP_ALIGN.CENTER)
        text(s, M + Inches(0.26), yy + Inches(0.54), CW - Inches(0.6), Inches(0.38),
             v, 11.5, False, INK, line=1.4)
    foot(s, f"※ {FACT['min_score']}点は「公開してよい最低ライン」であり、目標ではありません。推奨水準は95点以上です。")


def s_checks(prs):
    s, y = slide(prs, "13", f"機械が数える{FACT['checks']}項目",
                 "数えられるものを人に採点させません。全項目が通るまで、人による採点に進みません。")
    items = ["規定字数以上", "強調が12〜18箇所", "冒頭が断言型・80字以上", "対象読者の明記",
             "鮮度表記（◯年◯月時点）", "用語の定義ブロック", "比較テーブル", "失敗例・注意点の節",
             "見出しが6〜12個", "全見出し直下がリード文", "FAQ 5問以上", "FAQ回答が40〜60字",
             "本文FAQと構造化データが一致", "内部リンク3本以上", "外部の出典2本以上",
             "自社の一次情報がある", "一人称の体験が2箇所以上", "「これにより」がゼロ",
             "「重要です」が3回以下"]
    per = 3
    colw = Emu(int((CW - Inches(0.4)) / per))
    for i, it in enumerate(items):
        c, r = i % per, i // per
        x = M + Emu(int((colw + Inches(0.2)) * c))
        yy = y + Emu(int(Inches(0.46) * r))
        text(s, x, yy, Inches(0.22), Inches(0.28), "✓", 12, True, TEAL)
        text(s, x + Inches(0.26), yy, colw - Inches(0.3), Inches(0.3), it, 12, False, INK)
    y += Emu(int(Inches(0.46) * (-(-len(items) // per)))) + Inches(0.26)
    box(s, M, y, CW, Inches(0.95), fill=SOFT, line_col=LINE)
    text(s, M + Inches(0.28), y + Inches(0.19), CW - Inches(0.56), Inches(0.6),
         "このほかに、公開は止めないが後で直す警告が2項目あります（段落が200字以内・長すぎる文の割合）。"
         "警告つきで公開された記事は、日次の監査で順次直します。", 12, False, INK, line=1.5)
    foot(s)


def s_effect(prs):
    s, y = slide(prs, "14", "効かなかった記事を、毎週自動で直します",
                 "「対策した」と「効果があった」は別物です。直した日の前後で同じ日数を比べ、効いたかどうかを数字で判定します。")
    y = table(s, y, ["数字の状態", "判定", "やること"],
              [["表示20回以上 / クリック0 / 20位以内", ("タイトルの問題", RED),
                "人が直します。検索結果には出せないもの（失敗例・自社の実測）をタイトルに置く"],
               ["表示20回以上 / 21位以下", ("順位が足りない", BLUE),
                "機械が直します。関連記事から内部リンクを送って押し上げる"],
               ["表示が0.7倍未満に減少", ("意図とのずれ", RED),
                "人が直します。直した内容が検索意図とずれていないかを見直す"]],
              [0.3, 0.16, 0.54], row_h=0.64)
    y += Inches(0.06)
    box(s, M, y, CW, Inches(1.3), fill=SOFT, line_col=LINE)
    box(s, M, y, Pt(3), Inches(1.3), fill=GOLD)
    text(s, M + Inches(0.3), y + Inches(0.19), CW - Inches(0.6), Inches(0.3),
         "自動化するもの・しないものを分けています", 14, True, NAVY)
    text(s, M + Inches(0.3), y + Inches(0.57), CW - Inches(0.6), Inches(0.62),
         "自動で当てるのは内部リンクだけです。足しても記事の主張が変わらず、外しても害が小さいからです。"
         "タイトルの書き換えと検索意図の見直しは自動化しません。文章の判断が要り、"
         "機械に任せると主張のずれた記事が量産されます。", 12, False, INK, line=1.5)
    foot(s)


def s_review(prs):
    s, y = slide(prs, "15", "自動修正を、そのままにしません",
                 "自動化でいちばん危ないのは、1本ずつは正しいのに積み上がると記事が壊れることです。"
                 "当てる側は1本しか見ていないため、これを検知できません。")
    box(s, M, y, Inches(3.6), Inches(1.55), fill=RGBColor(0xFC, 0xEF, 0xED),
        line_col=RGBColor(0xF0, 0xC8, 0xC2))
    text(s, M + Inches(0.26), y + Inches(0.18), Inches(3.1), Inches(0.5),
         FACT["boiler_before"], 34, True, RED)
    text(s, M + Inches(0.26), y + Inches(0.8), Inches(3.1), Inches(0.65),
         "当社サイトの内部リンク文970本のうち403本が、まったく同じ一文になっていました",
         11, False, INK, line=1.4)
    text(s, M + Inches(3.95), y + Inches(0.12), CW - Inches(3.95), Inches(1.45),
         "1記事に11本も同じ言い回しが並んだものがありました。1本ずつは基準内でも、"
         "サイト全体で見れば機械生成の痕跡になります。検索エンジンが嫌う状態です。\n"
         f"見直しの工程を入れ、{FACT['boiler_before']} から {FACT['boiler_after']} まで是正しました。",
         13, False, INK, line=1.65)
    y += Inches(1.78)
    y = table(s, y, ["見るもの", "基準", "超えたときの処理"],
              [["1記事のリンクだけの段落", ("4本まで", BLUE),
                "後ろから外す。ただし送り先の被リンクが下限を割るものは残す"],
               ["1記事の同じ言い回し", ("2本まで", BLUE), "別の言い回しに振り直す（リンクは残す）"],
               ["サイト全体の同じ言い回し", ("12%まで", BLUE), "同上。8種類の型に散らす"]],
              [0.3, 0.14, 0.56], row_h=0.5)
    foot(s, "※ 書き込む前に、タグの対応・問い合わせ導線の数・本文の減り幅を修正前後で比較し、"
            "1つでも崩れていればその記事は書き換えません。")


def s_ops(prs):
    s, y = slide(prs, "16", "公開したあとの運用",
                 "公開して終わりではありません。毎日・毎週・毎月の運用が自動で回り続けます。")
    for i, (k, v) in enumerate(OPS):
        yy = y + Emu(int(Inches(0.82) * i))
        box(s, M, yy, Inches(1.5), Inches(0.62), fill=NAVY)
        text(s, M, yy + Inches(0.17), Inches(1.5), Inches(0.3),
             k, 15, True, WHITE, align=PP_ALIGN.CENTER)
        text(s, M + Inches(1.78), yy + Inches(0.1), CW - Inches(1.78), Inches(0.58),
             v, 12.5, False, INK, line=1.45)
    y += Emu(int(Inches(0.82) * len(OPS))) + Inches(0.16)
    box(s, M, y, CW, Inches(1.08), fill=SOFT, line_col=LINE)
    text(s, M + Inches(0.28), y + Inches(0.2), CW - Inches(0.56), Inches(0.7),
         "1日の公開は時間を分けます。同じドメインへ短時間にまとめて投入すると、"
         "機械的な生成とみなされる可能性があるためです。月の上限本数も、"
         "人が気をつけるのではなく配信の入口で機械的に止めています。", 12, False, INK, line=1.5)
    foot(s)


def s_report(prs):
    s, y = slide(prs, "17", "月次レポート（サイト再構成の指示つき）",
                 "数字を並べるだけのレポートではありません。"
                 "「どの記事のどこを、どう変えるか」まで書いて毎月お渡しします。")
    half = -(-len(REPORT_ITEMS) // 2)
    for i, it in enumerate(REPORT_ITEMS):
        c, r = (0, i) if i < half else (1, i - half)
        x = M + Emu(int((CW / 2 + Inches(0.1)) * c))
        yy = y + Emu(int(Inches(0.42) * r))
        strong = it.startswith("<b>")
        label = it.replace("<b>", "").replace("</b>", "")
        text(s, x, yy, Inches(0.2), Inches(0.26), "▸", 11, True,
             GOLD if strong else TEAL)
        text(s, x + Inches(0.24), yy, Emu(int(CW / 2 - Inches(0.36))), Inches(0.32),
             label, 11.5, strong, NAVY if strong else INK, line=1.35)
    foot(s, "※ 金色の項目は、他社のレポートにはあまり含まれない改善指示のパートです。")

def s_proof(prs):
    s, y = slide(prs, "18", "この仕組みは、当社自身が使っています",
                 "提案のために作ったものではありません。当社が自社の3サイトで毎日動かしている仕組みを、そのままご提供します。")
    y = cards(s, y, [
        ("運用中のサイト", f"{FACT['sites']}サイト", "AI集客・経理BPO・補助金支援の3領域"),
        ("公開済みの記事", f"{FACT['articles_total']}本", "すべて品質基準を満たしたもののみ"),
        ("1日の公開数", f"{FACT['per_day']}本", "3サイト×2本を時間を分けて公開"),
    ], per=3, h=1.3)
    y += Inches(0.12)
    text(s, M, y, CW, Inches(0.3), "運用の中で分かったこと", 15, True, NAVY)
    y += Inches(0.44)
    y = bullets(s, y, [
        ("同じ順位でも、検索語によってクリック率が約2.7倍違いました。",
         f"6〜10位という同じ順位帯で、一方のサイトは{FACT['ctr_weak']}、もう一方は"
         f"{FACT['ctr_strong']}（28日間の実測）。差は順位ではなく検索語の性質にありました。"
         "本サービスでは、この性質を機械で判定してから書きます。"),
        ("内部リンクが不足した記事は、そもそも検索結果に出ていませんでした。",
         "90日間で一度も表示されなかった記事は、被リンクが平均3.7〜4.6本。"
         "表示されている記事は5.9〜8.8本でした。基準を引き上げて補充しています。"),
    ], gap=1.05)
    foot(s, "※ いずれも当社運用サイトでの実測値です。成果は業種・競合状況により異なり、"
            "同じ数値をお約束するものではありません。")



# ============================================================
# 実際に動いている記録（すべて実物のログ・出力）
# ============================================================
TERM_BG = RGBColor(0x0E, 0x1B, 0x2B)
TERM_FG = RGBColor(0xD7, 0xE2, 0xEF)
TERM_OK = RGBColor(0x5F, 0xC5, 0x85)
TERM_NG = RGBColor(0xF0, 0x90, 0x84)
TERM_DIM = RGBColor(0x72, 0x88, 0xA3)
TERM_KEY = RGBColor(0xE8, 0xC2, 0x6A)
MONO = "ＭＳ ゴシック"


def term(s, x, y, w, h, lines, size=9.5, title=""):
    """実際の画面出力をそのまま貼る枠。色は行頭の記号で切り替える"""
    box(s, x, y, w, h, fill=TERM_BG)
    ty = y + Inches(0.12)
    if title:
        text(s, x + Inches(0.22), ty, w - Inches(0.44), Inches(0.2),
             title, 8.5, False, TERM_DIM, name=MONO)
        ty += Inches(0.26)
    for ln in lines:
        col = TERM_FG
        if ln.startswith("+"):
            col, ln = TERM_OK, ln[1:]
        elif ln.startswith("-"):
            col, ln = TERM_NG, ln[1:]
        elif ln.startswith("~"):
            col, ln = TERM_DIM, ln[1:]
        elif ln.startswith("*"):
            col, ln = TERM_KEY, ln[1:]
        text(s, x + Inches(0.22), ty, w - Inches(0.4), Inches(0.19),
             ln, size, False, col, name=MONO)
        ty += Inches(size / 48)
    return ty


def s_live_log(prs):
    s, y = slide(prs, "19", "実際に動いている記録 ― 2026年9月14日",
                 "以下は当社の運用サイトで、その日に実際に走った処理の記録です。時刻は日本時間。")
    rows = [("11:38", "自動修復", "skipped", "直すものなし"),
            ("11:17", "記事パイプライン", "success", "補助金サイト 1本公開"),
            ("10:47", "サイトへ配信", "success", "Cloudflareへデプロイ"),
            ("09:04", "自動修復", "skipped", "直すものなし"),
            ("08:45", "記事パイプライン", "success", "コーポレート 1本公開"),
            ("06:26", "週次の最適化", "success", "リライト・内部リンク・見直し"),
            ("05:39", "記事パイプライン", "success", "AI集客ラボ 1本公開"),
            ("02:56", "週刊ダイジェスト配信", "success", "購読者へメール送信")]
    y = table(s, y, ["時刻", "処理", "結果", "内容"],
              [[r[0], r[1], (r[2], TERM_OK if r[2] == "success" else MUTED), r[3]]
               for r in rows],
              [0.09, 0.26, 0.12, 0.53], row_h=0.42)
    box(s, M, y, CW, Inches(0.92), fill=SOFT, line_col=LINE)
    text(s, M + Inches(0.28), y + Inches(0.18), CW - Inches(0.56), Inches(0.6),
         "「自動修復」が skipped になっているのは、直すものが無かったという意味です。"
         "壊れていれば自動で直し、直せなければ通知が飛びます。人がログを見に行く必要はありません。",
         12, False, INK, line=1.5)
    foot(s, "※ GitHub Actions の実行履歴より。人の操作は一切入っていません。")


def s_live_judge(prs):
    s, y = slide(prs, "20", "エージェントが実際に出した判断",
                 "画面の出力をそのまま載せています。どれも人が介在せず、条件だけで判定したものです。")
    colw = Emu(int((CW - Inches(0.3)) / 2))
    term(s, M, y, colw, Inches(2.0),
         ["$ kw_guard.py \"社労士 AI導入補助金\"",
          "",
          "~■ 食い合い審査（補助金サイト）",
          "+   ぶつかる既存記事はありません",
          "*   判定: 着手可",
          "",
          "~■ 開かないと済まない語か",
          "*   [強] 3点（費用/いくら/内訳）"],
         title="① 書く前 ― この語で書いてよいか")
    term(s, M + colw + Inches(0.3), y, colw, Inches(2.0),
         ["$ score_check.py nougyou-shoki-hiyou",
          "",
          "-FAIL | 本文5,000字以上  | 4,784字",
          "+PASS | 冒頭が断言型     | 172字",
          "+PASS | FAQ 5問以上      | 6問",
          "+PASS | 内部リンク3本以上 | 8本",
          "~...",
          "*機械採点: 18/19 → 修正してから再検査"],
         title="② 書いた後 ― 基準を満たしているか")
    y += Inches(2.24)
    term(s, M, y, CW, Inches(1.95),
         ["$ auto_improve.py",
          "",
          "~■ 効果測定から出たやること: 31件",
          "+   内部リンクを足す（自動）        4件",
          "*   タイトルを直す（人が判断）      3件",
          "*   検索意図を見直す（人が判断）   24件",
          "",
          "~   [review] backoffice-gyomu-kaizen       表示が10から1へ減少",
          "~        → 直した内容が検索意図とずれていないか見直す"],
         title="③ 公開の後 ― 効いたか、次に何をするか")
    foot(s, "※ ②は実際に基準を満たさず差し戻された記録です。この記事は加筆して19/19にしてから公開しました。")


def s_live_growth(prs):
    s, y = slide(prs, "21", "止まらずに積み上がっています",
                 "直近11日間に新しく公開された記事です。3サイト合計、すべて品質基準を満たしたもののみ。")
    data = [("09/04", 1), ("09/05", 5), ("09/06", 8), ("09/07", 11), ("09/08", 12),
            ("09/09", 8), ("09/10", 8), ("09/11", 9), ("09/12", 9), ("09/13", 6),
            ("09/14", 5)]
    top = y + Inches(0.28)          # 目盛りの一番上がリード文に寄らないよう下げる
    ch_h = Inches(2.3)
    base = top + ch_h
    peak = max(v for _, v in data)
    bw = Emu(int((CW - Inches(1.0)) / len(data)))
    # 目盛り
    for g in (0, 4, 8, 12):
        gy = base - Emu(int(ch_h * g / peak))
        box(s, M + Inches(0.42), gy, CW - Inches(0.42), Pt(0.75),
            fill=LINE if g else MUTED)
        text(s, M, gy - Inches(0.1), Inches(0.34), Inches(0.2),
             str(g), 9, False, MUTED, align=PP_ALIGN.RIGHT)
    for i, (d, v) in enumerate(data):
        h = Emu(int(ch_h * v / peak))
        x = M + Inches(0.5) + Emu(int(bw * i))
        box(s, x, base - h, bw - Inches(0.16), h, fill=BLUE if v >= 8 else RGBColor(0x8F, 0xB2, 0xDE))
        text(s, x, base - h - Inches(0.24), bw - Inches(0.16), Inches(0.2),
             str(v), 10, True, NAVY, align=PP_ALIGN.CENTER)
        text(s, x, base + Inches(0.08), bw - Inches(0.16), Inches(0.2),
             d, 9.5, False, MUTED, align=PP_ALIGN.CENTER)
    y = base + Inches(0.46)
    y = cards(s, y, [
        ("11日間の公開数", "82本", "1日あたり平均7.5本。3サイトに配分しています"),
        ("差し戻された記事", "0本が未公開のまま", "基準に届かないものは加筆して通してから公開"),
        ("人が書いた記事", "0本", "方向性の決定と最終判断のみ人が行います"),
    ], per=3, h=1.15)
    foot(s, "※ 当社運用サイトのコミット履歴より集計（2026/09/04〜09/14）。"
            "日ごとの本数は、公募や季節の事情でテーマを入れ替えるため上下します。")


def s_price(prs):
    s, y = slide(prs, "23", "料金",
                 f"サイト構築の初期費用と、記事{PRICE['articles']}本＋レポート＋改善作業を含む月額費用です。")
    text(s, M, y, CW, Inches(0.3), "初期費用（サイト構築）", 14, True, NAVY)
    y += Inches(0.46)
    init = [("1サイト目", PRICE["init_1"], "オウンドメディア＋LP　" + PRICE["init_1_note"]),
            ("2サイト目以降", PRICE["init_2"], "同じ設計を使い回すため割安になります")]
    for i, (n, p, u) in enumerate(init):
        w = Emu(int(CW / 2 - Inches(0.12)))
        x = M + Emu(int((CW / 2 + Inches(0.12)) * i))
        box(s, x, y, w, Inches(1.02),
            fill=RGBColor(0xEB, 0xF2, 0xFC) if i == 0 else SOFT,
            line_col=BLUE if i == 0 else LINE)
        text(s, x + Inches(0.26), y + Inches(0.14), w - Inches(0.5), Inches(0.24),
             n, 11.5, True, MUTED)
        text(s, x + Inches(0.26), y + Inches(0.38), w - Inches(0.5), Inches(0.34),
             p, 21, True, NAVY)
        text(s, x + Inches(0.26), y + Inches(0.76), w - Inches(0.5), Inches(0.24),
             u, 10.5, False, INK)
    y += Inches(1.34)
    text(s, M, y, CW, Inches(0.3),
         f"月額費用（記事{PRICE['articles']}本＋レポート＋運用・改善）", 14, True, NAVY)
    y += Inches(0.46)
    run = [("1サイト運用", PRICE["run_1"], f"記事{PRICE['articles']}本／月　レポート・改善込み"),
           ("2サイト運用", PRICE["run_2"], f"2サイト合計{PRICE['articles']}本　横断の重複検査つき"),
           ("3サイト運用", PRICE["run_3"], f"3サイト合計{PRICE['articles']}本　役割分担の設計から")]
    for i, (n, p, u) in enumerate(run):
        w = Emu(int((CW - Inches(0.44)) / 3))
        x = M + Emu(int((w + Inches(0.22)) * i))
        box(s, x, y, w, Inches(1.1),
            fill=RGBColor(0xEB, 0xF2, 0xFC) if i == 0 else SOFT,
            line_col=BLUE if i == 0 else LINE)
        text(s, x + Inches(0.24), y + Inches(0.14), w - Inches(0.48), Inches(0.24),
             n, 11.5, True, MUTED)
        text(s, x + Inches(0.24), y + Inches(0.38), w - Inches(0.48), Inches(0.34),
             p, 21, True, NAVY)
        text(s, x + Inches(0.24), y + Inches(0.76), w - Inches(0.48), Inches(0.3),
             u, 10, False, INK, line=1.3)
    foot(s, f"※ 表示はすべて税別です。複数サイトの場合、記事本数は合計{PRICE['articles']}本を配分します。"
            "写真素材のご支給がない場合、初期費用は上限額となります。")


def s_compare(prs):
    s, y = slide(prs, "24", "他の方法と比べた場合",
                 f"同じ「月{PRICE['articles']}本の記事を作る」を、他の手段で実現した場合と比べます。")
    w_low = MARKET["writer_low"] * PRICE["articles"]
    w_high = MARKET["writer_high"] * PRICE["articles"]
    staff_n = -(-PRICE["articles"] // MARKET["staff_output"])
    y = table(s, y, ["手段", "月あたりの費用", "含まれるもの / 残る課題"],
              [[("本サービス", BLUE), (PRICE["run_1"], BLUE),
                f"記事{PRICE['articles']}本＋図解＋公開＋改善レポートまで込み"],
               ["外注ライター", f"{w_low}万〜{w_high}万円",
                f"1本{MARKET['writer_low']}〜{MARKET['writer_high']}万円×{PRICE['articles']}本。"
                "原稿のみで、公開作業・図解・改善は自社に残ります"],
               ["社内で採用",
                f"{MARKET['staff_cost_low'] * staff_n}万〜{MARKET['staff_cost_high'] * staff_n}万円",
                f"1人が月{MARKET['staff_output']}本として{staff_n}名必要。"
                "採用・育成の期間と、退職時に止まるリスクが残ります"],
               ["SEOコンサル",
                f"{MARKET['consult_low']}万〜{MARKET['consult_high']}万円",
                "助言が中心で、記事の制作は含まれないことが多い。実作業は自社に残ります"]],
              [0.16, 0.19, 0.65], row_h=0.68)
    box(s, M, y, CW, Inches(0.98), fill=SOFT, line_col=LINE)
    text(s, M + Inches(0.28), y + Inches(0.2), CW - Inches(0.56), Inches(0.6),
         "費用よりも「止まらないこと」に差が出ます。外注も採用も、担当が変わればペースが落ちます。"
         "本サービスは仕組みで動くため、公開のペースと品質の基準が人に依存しません。",
         12, False, INK, line=1.5)
    foot(s, "※ 外注・採用・コンサルの金額は一般的な相場の範囲であり、当社が保証するものではありません。")


def s_steps(prs):
    s, y = slide(prs, "25", "導入の流れ",
                 "お申し込みから最初の記事が公開されるまで、おおむね3〜4週間です。")
    steps = [("01", "無料相談・ヒアリング", "60分",
              "御社の強み、狙いたい層、競合状況を伺います。この場で、"
              "どのキーワードが狙えそうかの見立てをお出しします"),
             ("02", "ヒアリングシートのご記入", "30分程度",
              "1枚のシートをお渡しします。ご記入いただくのはこの1回だけで、"
              "主力商材・守備範囲・実績の数値・問い合わせ導線が決まります"),
             ("03", "ご提案・お見積り", "1週間",
              "シートの内容からサイト構成とキーワードの一覧をご提案します。"
              "ご要望を反映してから着手します"),
             ("04", "サイト構築", "2〜3週間",
              "デザイン・実装・AI検索対応の設定まで。写真素材をご支給いただくタイミングです"),
             ("05", "公開・運用開始", "翌日〜",
              f"公開の翌日から記事が増え始めます。1ヶ月目から月{PRICE['articles']}本のペースで積み上がります"),
             ("06", "毎月のレポート", "継続",
              "数字の報告と、翌月の改善指示をお渡しします。ご要望に応じてキーワードの追加も承ります")]
    for i, (no, k, term, v) in enumerate(steps):
        yy = y + Emu(int(Inches(0.86) * i))
        box(s, M, yy, Inches(0.5), Inches(0.5), fill=GOLD)
        text(s, M, yy + Inches(0.13), Inches(0.5), Inches(0.3),
             no, 13, True, WHITE, align=PP_ALIGN.CENTER)
        if i < len(steps) - 1:
            box(s, M + Inches(0.24), yy + Inches(0.54), Pt(1.2), Inches(0.32), fill=LINE)
        text(s, M + Inches(0.72), yy - Inches(0.02), Inches(3.0), Inches(0.3),
             k, 14, True, NAVY)
        box(s, M + Inches(3.8), yy + Inches(0.02), Inches(0.95), Inches(0.28),
            fill=SOFT, line_col=LINE)
        text(s, M + Inches(3.8), yy + Inches(0.06), Inches(0.95), Inches(0.24),
             term, 10.5, True, TEAL, align=PP_ALIGN.CENTER)
        text(s, M + Inches(0.72), yy + Inches(0.34), CW - Inches(0.92), Inches(0.5),
             v, 11.5, False, INK, line=1.4)
    foot(s)


def s_faq(prs, part):
    half = FAQS[:4] if part == 1 else FAQS[4:]
    s, y = slide(prs, "26", f"よくあるご質問（{part}/2）", "")
    for q, a in half:
        box(s, M, y, Inches(0.3), Inches(0.3), fill=NAVY)
        text(s, M, y + Inches(0.04), Inches(0.3), Inches(0.24),
             "Q", 12, True, WHITE, align=PP_ALIGN.CENTER)
        text(s, M + Inches(0.44), y - Inches(0.01), CW - Inches(0.5), Inches(0.3),
             q, 13.5, True, NAVY)
        y += Inches(0.44)
        text(s, M + Inches(0.44), y, CW - Inches(0.62), Inches(0.4),
             a, 11.5, False, INK, line=1.55)
        # 11.5pt・幅11.0inで1行あたり約62文字。行間1.55を掛けて送る
        lines = max(1, -(-len(a) // 62))
        y += Inches(11.5 * 1.55 * lines / 72) + Inches(0.3)
    foot(s)


def s_close(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    box(s, 0, 0, W, H, fill=NAVY)
    box(s, 0, 0, W, Inches(0.12), fill=GOLD)
    logo = ROOT / "site" / "images" / "company" / "logo-white.png"
    if logo.exists():
        s.shapes.add_picture(str(logo), M, Inches(0.85), height=Inches(0.44))
    text(s, M, Inches(2.05), Inches(11.2), Inches(0.95),
         "まずは、御社のキーワードを\n無料でお調べします", 34, True, WHITE, line=1.32)
    box(s, M, Inches(3.8), Inches(1.3), Pt(3.5), fill=GOLD)
    text(s, M, Inches(4.1), Inches(10.6), Inches(0.9),
         "60分のご相談で、どのキーワードなら狙えるか、競合がいま何本の記事を持っているかをお調べしてお伝えします。\n"
         "ご契約を前提としたご案内ではありません。",
         14, False, RGBColor(0xC5, 0xD6, 0xEB), line=1.7)
    for i, (k, v) in enumerate([("お問い合わせ", "corp.7senses.co.jp/contact/"),
                                ("運用中のメディア", "ai.7senses.co.jp")]):
        x = M + Emu(int(Inches(5.6) * i))
        text(s, x, Inches(5.55), Inches(5.2), Inches(0.24), k, 10.5, False,
             RGBColor(0x7E, 0x9A, 0xBE))
        text(s, x, Inches(5.85), Inches(5.2), Inches(0.3), v, 14, True, WHITE)
    text(s, M, Inches(6.65), Inches(11.0), Inches(0.3),
         "セブンセンシズ株式会社", 12, False, RGBColor(0x9E, 0xC0, 0xE8))


def build():
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    # 並びは成約までの流れ。なぜ今か → 何が難しいか → どう解くか →
    # 誰が何をやるか → 本当に動くのか → 何が違うか → いくらか → どう始めるか
    cover(prs)
    s_summary(prs)
    s_problem(prs)
    s_why_aio(prs)
    s_dilemma(prs)
    s_overview(prs)
    s_site(prs)
    s_aio(prs, 1)
    s_aio(prs, 2)
    s_flow(prs)
    s_roles(prs, 1)
    s_roles(prs, 2)
    s_sheet(prs)
    s_sheet_industry(prs)
    s_gates(prs)
    s_checks(prs)
    s_effect(prs)
    s_review(prs)
    s_ops(prs)
    s_report(prs)
    s_proof(prs)
    s_live_log(prs)
    s_live_judge(prs)
    s_live_growth(prs)
    s_vs_consult(prs)
    s_price(prs)
    s_compare(prs)
    s_steps(prs)
    s_faq(prs, 1)
    s_faq(prs, 2)
    s_close(prs)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    return len(prs.slides._sldIdLst)


def to_desktop():
    """デスクトップへ複製する。同名で上書きするので、常に最新の1組だけが残る"""
    import shutil
    DESK.mkdir(parents=True, exist_ok=True)
    put, busy = [], []
    # PDF は sales_deck.py が作る別構成（15ページの読み物）。
    # 「PDF版」と呼ぶと同じ中身だと誤解されるので、名前で用途を分ける
    for src, name in ((OUT, "提案書_商談用スライド.pptx"),
                      (OUT.with_suffix(".pdf"), "提案書_読み物（先方送付用）.pdf"),
                      # 商談の場でそのままお渡しできるよう、提案書と並べて置く。
                      # 業種別があるものは、相手の業種に合うほうを渡す
                      (ROOT / "docs" / "client" / "ヒアリングシート.xlsx",
                       "ヒアリングシート（共通）.xlsx"),
                      (ROOT / "docs" / "client" / "ヒアリングシート_飲食店.xlsx",
                       "ヒアリングシート（飲食店）.xlsx")):
        if not src.is_file():
            continue
        try:
            shutil.copy2(src, DESK / name)
            put.append(name)
        except PermissionError:
            # 開いたまま作り直すことはよくある。ここで全体を止めない
            busy.append(name)
    return put, busy


def main():
    n = build()
    print(f"作成しました: {OUT.relative_to(ROOT)}（{n}枚）")
    if "--no-desktop" not in sys.argv:
        put, busy = to_desktop()
        for name in put:
            print(f"  デスクトップへ: 提案資料/{name}")
        for name in busy:
            print(f"  ! 提案資料/{name} は開かれているため更新できません"
                  f"（閉じてから再実行してください）")
    if "--open" in sys.argv:
        subprocess.run(["cmd", "/c", "start", "", str(OUT)], shell=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
