# -*- coding: utf-8 -*-
"""クライアント提案資料（AIO特化オウンドメディア構築・運用サービス）

使い方:
    python scripts/sales_deck.py          # HTML+PDFを生成
    python scripts/sales_deck.py --open   # 生成後にPDFを開く

内容を変えたいときはこのファイルの定数を編集して再実行する。
料金・実績値を1か所にまとめてあるので、改定時の修正漏れが起きない。
"""
import base64
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "sales"

# ▼ 料金 ─────────────────────────────────
PRICE = {
    "init_1": "20万〜30万円", "init_1_note": "画像を生成する場合は30万円",
    "init_2": "10万〜15万円",
    "run_1": "月額17万円〜", "run_2": "月額27万円", "run_3": "月額34万円",
    "articles": 60,
}
# 相場は「一般的な外注単価の範囲」。断定を避けて幅で示す
MARKET = {
    "writer_low": 3, "writer_high": 5,        # 1記事あたりの外注単価（万円）
    "staff_cost_low": 25, "staff_cost_high": 40,  # ライター1名の月額人件費（万円）
    "staff_output": 10,                        # ライター1名が月に書ける本数の目安
    "consult_low": 10, "consult_high": 30,     # SEOコンサル月額（万円）
}
# ────────────────────────────────────────

NAVY, BLUE, TEAL, GOLD, MUTED, LINE = "#0b2447", "#2563eb", "#0d9488", "#b7922e", "#5b6b84", "#e3eaf3"


def logo_tag(white=True):
    p = ROOT / "site" / "images" / "company" / ("logo-white.png" if white else "logo.png")
    if not p.exists():
        return ""
    b64 = base64.b64encode(p.read_bytes()).decode()
    return f'<img class="lg" src="data:image/png;base64,{b64}">'


def li(items):
    return "".join(f"<li>{x}</li>" for x in items)


def rows(data):
    return "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in data)


# ============================================================
# 各ページの中身
# ============================================================
SITE_FEATURES = [
    ("ページ構成", "トップ / カテゴリ一覧 / 記事詳細 / サービスLP / 会社情報 / お問い合わせ / "
                "プライバシーポリシー / 特定商取引法表記 / 用語集 / はじめての方へ / 編集ポリシー"),
    ("記事ページの機能", "目次の自動生成・パンくず・著者と監修者の表示・関連記事・前後の記事ナビ・"
                    "SNSシェア・URLコピー・音声読み上げ・メール購読フォーム"),
    ("問い合わせ導線", "記事内CTA 2箇所以上・追従サイドバー・記事下CTA・LPへの誘導・無料診断への導線"),
    ("フォーム", "送信内容をスプレッドシート台帳へ自動記録＋メール通知。自動返信も設定可能。"
             "迷惑投稿対策（ハニーポット・合言葉検証）を実装"),
    ("表示速度", "Cloudflareの世界規模CDNから配信。静的生成のため表示が速く、"
             "アクセスが増えてもサーバー費用が上がらない構成"),
    ("スマートフォン対応", "全ページがスマホ・タブレット・PCに最適化。読み込みの軽さと"
                    "指で操作しやすい導線を優先した設計"),
    ("アクセシビリティ", "キーボード操作・スクリーンリーダー対応。動きを減らす設定にも追従し、"
                  "誰にとっても読める状態を担保"),
]

AIO_FEATURES = [
    ("構造化データ4種", "記事情報・FAQ・パンくず・手順（HowTo）をGoogleが読める形式で埋め込み。"
                  "検索結果でのリッチ表示とAIの理解精度を高める"),
    ("llms.txt の設置", "AIクローラー向けにサイトの案内図を設置。何のサイトで誰が書いているかを"
                   "機械が読める形で明示する（AI検索時代の新しい標準）"),
    ("AIクローラーの許可", "GPTBot・OAI-SearchBot・ClaudeBot・PerplexityBot・Google-Extended・Bingbot の"
                    "6種を明示的に許可。ここをブロックしていると、順位が高くてもAIに引用されない"),
    ("冒頭200字の断言型回答", "「◯◯は◯◯です」で始める。AIが最も抜き出しやすい形で結論を置く"),
    ("見出しごとの1文結論", "各見出しの直下に40〜60字の結論。その1文だけ切り出しても意味が通るため"
                    "AIの回答にそのまま採用されやすい"),
    ("FAQ5問以上＋完全一致", "本文のFAQと構造化データを完全に一致させる。不一致はスパム判定のリスクがある"),
    ("出典付きの数値ファクト", "1記事に3箇所以上。AIは数値付きの断定文を優先的に引用する"),
    ("情報の鮮度表記", "「◯年◯月時点」の明記と更新日の管理。AI検索は鮮度を強く評価する"),
    ("比較テーブル", "表だけを切り出しても意味が完結する作り。AIが引用しやすい"),
    ("失敗例・注意点", "「これはNG」の形で最低1箇所。網羅性の評価につながる"),
    ("対象読者の明記", "「この記事は◯◯向けです」を冒頭に。誰に向けた情報かをAIに伝える"),
    ("画像に頼らない", "図解の重要情報は必ず本文にも文章で書く。AIは画像を引用できないため"),
]

PHASES = [
    ("01", "キーワード選定", "台帳から次のテーマを取得し、既存記事との重複を機械検査。"
                      "他サイトを運用中の場合は、サイトをまたいだ重複も検査して共倒れを防ぐ"),
    ("02", "一次情報の収集", "SNS・動画・公的統計から、その記事にしかない事実と数字を集める。"
                      "AI検索が最も引用したがるのが一次情報"),
    ("03", "構成の設計と事前審査", "検索上位の構造を分析し、共通6〜7割＋独自3〜4割で構成を設計。"
                          "執筆前に14項目を自己審査し、全項目を満たすまで書き始めない"),
    ("04", "執筆", "5,000字以上。AI感を排除する7項目（曖昧な結論・語尾の単調さ等）を全チェック。"
              "一人称の体験・観察を必ず2箇所以上入れる"),
    ("05", "品質採点", "機械採点18項目を全て通したうえで、6つの観点から120点満点で採点。"
                 "基準に届かなければ自動で修正して再採点する"),
    ("06", "画像生成と公開", "アイキャッチ1枚＋本文図解3〜5枚を生成。HTML化し、"
                     "サイトマップ・AI向け案内図を更新して公開"),
    ("07", "インデックス登録と内部リンク", "GoogleとBingへ即時通知。既存記事から新記事への"
                              "内部リンクを自動で追加し、サイト全体の評価を底上げする"),
]

GATES = [
    ("構成の事前審査", "14項目", "書き始める前に構成を審査。タイトル字数・見出し設計・"
                          "結論の草案・出典候補・内部リンク先まで確認する"),
    ("機械採点", "18項目", "文字数・強調の数・FAQ数・リンク数・見出し構造・"
                     "AI感のNGワードなど、数えられるものを機械が判定"),
    ("6観点の採点", "120点満点", "デザイン／SEO／編集／技術正確性／読者目線／AI検索対応の6観点。"
                          "各観点20点で、1観点でも16点未満なら合計に関わらず不合格"),
    ("公開時の物理ガード", "90点未満は公開不可", "基準に届かない記事は、システム上サイトに載せられない。"
                                    "「とりあえず出す」が構造的に起きない"),
]

OPS = [
    ("毎日", "記事の生成・採点・公開・検索エンジンへの通知・KPIの集計"),
    ("毎週", "既存記事のリライト、重複記事の検出と統合、内部リンクの最適化、"
          "古くなった情報の更新"),
    ("毎月", "17ページの月次レポートを自動発行。次month の改善指示まで含む"),
    ("随時", "問い合わせの台帳記録と通知、メール購読者への週刊配信"),
]

REPORT_ITEMS = [
    "今月を3行でまとめた要約",
    "主要4指標の評価（良好／標準／要改善の判定と、その判定基準）",
    "6ヶ月トレンドのグラフ（セッション・クリック・表示回数・順位）",
    "検索キーワード別の実績と、伸ばすべきキーワードの特定",
    "記事別の成績一覧（どの記事が効いていて、どれがテコ入れ対象か）",
    "流入構造の分析（自然検索・直接・SNSの比率、スマホ比率、日別推移）",
    "AI検索からの流入分析（ChatGPT・Perplexity・Gemini別の内訳）",
    "投資対効果（同じ流入を広告で買った場合の金額換算）",
    "LPのどこで離脱しているかの分析（セクション別の到達率）",
    "<b>サイト全体監査 — 記事ごとに「どこを・どう変えるか」の具体的な修正指示</b>",
    "<b>サイト構造・導線の変更指示（カテゴリ設計・CTA配置・見出しの改善）</b>",
    "前月に立てた目標に対する達成率",
    "来月のKPI目標と、週単位の実行スケジュール",
    "リスクと前提条件（数字を正しく読むための注記）",
]

FAQS = [
    ("記事の品質は大丈夫ですか。AIが書いた記事だと分かりませんか？",
     "AI特有の言い回しを排除する7項目を全記事でチェックし、一人称の体験・観察を必ず入れています。"
     "さらに6観点120点満点の採点で基準に届かない記事は公開されません。"
     "実際の記事は貴社サイトでご確認いただけますので、まずは既存メディアの記事をご覧ください。"),
    ("効果が出るまでどれくらいかかりますか？",
     "検索での順位は、記事公開から評価が安定するまで3〜6ヶ月かかるのが一般的です。"
     "ただし記事は資産として積み上がるため、6ヶ月目以降は同じ費用でも成果が伸び続けます。"
     "初月から見えるのは、インデックス登録状況と表示回数の増加です。"),
    ("記事のテーマはこちらで決められますか？",
     "はい。初回のヒアリングで御社の強みと狙いたい層を伺い、キーワードの一覧をご提案します。"
     "台帳はスプレッドシートで共有するため、いつでもご確認・ご要望の追加が可能です。"),
    ("公開前に内容を確認できますか？",
     "可能です。ご希望に応じて、公開前の確認フローを挟む運用に変更できます。"
     "医療・金融など表現規制のある業種では、この運用を推奨しています。"),
    ("既存のサイトがありますが、作り直しになりますか？",
     "既存サイトを活かしたまま、記事部分だけを追加することも可能です。"
     "ただしAI検索への対応度は既存サイトの作りに左右されるため、"
     "初回の診断でどちらが良いかをご提案します。"),
    ("解約はいつでもできますか？",
     "可能です。解約後も公開済みの記事とサイトはそのまま御社の資産として残ります。"
     "データの引き渡しにも対応します。"),
    ("写真はこちらで用意する必要がありますか？",
     f"店舗写真・商品写真・スタッフ写真はご支給いただく前提です（初期費用 {PRICE['init_1']}）。"
     "AIでの画像生成をご希望の場合は初期費用30万円となります。"
     "なお記事内の図解は、いずれの場合も当社が全て作成します。"),
]


def build_html():
    today = date.today()
    w_low = MARKET["writer_low"] * PRICE["articles"]          # 外注ライター合計（万円）
    w_high = MARKET["writer_high"] * PRICE["articles"]
    staff_n = -(-PRICE["articles"] // MARKET["staff_output"])  # 内製に必要な人数（切り上げ）
    s_low = MARKET["staff_cost_low"] * staff_n
    s_high = MARKET["staff_cost_high"] * staff_n

    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><style>
@page {{ size: A4; margin: 0; }}
* {{ box-sizing: border-box; margin: 0; }}
body {{ font-family: "Yu Gothic","Meiryo",sans-serif; color:#10203a; font-size:10pt; line-height:1.85; }}
.sheet {{ width:210mm; min-height:296mm; padding:16mm 15mm 18mm; page-break-after:always; position:relative; }}
.sheet:last-child {{ page-break-after:auto; }}
.cover {{ background:linear-gradient(150deg,#071a38,{NAVY} 45%,#14345c); color:#fff;
  display:flex; flex-direction:column; padding:24mm 20mm; }}
/* 縦並びのflex内では既定で横に引き伸ばされるため、align-selfで実寸比率を保つ */
.lg {{ height:36px;width:auto;align-self:flex-start;flex:0 0 auto; }}
.back .lg {{ align-self:center; }}
.cv-g {{ width:64px;height:4px;background:{GOLD};margin:12mm 0 7mm; }}
.kick {{ letter-spacing:.32em;font-size:9pt;color:#93b4e8; }}
.ttl {{ font-size:27pt;font-weight:900;line-height:1.45;margin-top:5mm; }}
.sub {{ font-size:12pt;color:#cfe0f7;margin-top:6mm;line-height:2; }}
.badges {{ display:flex;gap:7px;margin-top:9mm;flex-wrap:wrap; }}
.badge {{ border:1px solid rgba(255,255,255,.4);border-radius:999px;padding:3px 14px;font-size:8.6pt;color:#dbe7fa; }}
.meta {{ margin-top:auto;font-size:9.5pt;color:#bcd0ee;line-height:2.1;
  border-top:1px solid rgba(255,255,255,.25);padding-top:6mm; }}
.sec {{ display:flex;align-items:center;gap:10px;margin:0 0 13px; }}
.sec .no {{ background:{NAVY};color:#fff;font-weight:bold;font-size:10pt;padding:3px 12px;border-radius:4px;letter-spacing:.06em; }}
.sec h2 {{ font-size:15pt; }}
.sec .gold {{ flex:1;height:2px;background:linear-gradient(90deg,{GOLD},transparent); }}
h3 {{ font-size:11.5pt;margin:17px 0 7px;color:{NAVY}; }}
p.lead {{ font-size:10.5pt;line-height:2;margin-bottom:10px; }}
.dim {{ color:{MUTED}; }}
.small {{ font-size:8.6pt;color:{MUTED};line-height:1.9; }}
table {{ border-collapse:collapse;width:100%;font-size:9.2pt;margin-top:8px; }}
th,td {{ border:1px solid #dbe3ee;padding:7px 9px;text-align:left;vertical-align:top; }}
th {{ background:{NAVY};color:#fff;font-weight:600; }}
td.num {{ text-align:right;font-variant-numeric:tabular-nums; }}
tr:nth-child(even) td {{ background:#f7fafd; }}
ul {{ padding-left:19px; }} li {{ margin:5px 0; }}
.callout {{ border-left:4px solid {GOLD};background:#fbf8ef;padding:11px 15px;
  border-radius:0 8px 8px 0;margin:12px 0;font-size:9.6pt; }}
.warn {{ border-left:4px solid #2563eb;background:#eff6ff;padding:11px 15px;
  border-radius:0 8px 8px 0;margin:12px 0;font-size:9.6pt; }}
.cards {{ display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:12px 0; }}
.card {{ border:1px solid {LINE};border-top:3px solid {BLUE};border-radius:10px;padding:12px 13px; }}
.card .k {{ font-size:8.6pt;color:{MUTED}; }}
.card .v {{ font-size:17pt;font-weight:900;color:{NAVY};line-height:1.35; }}
.card .s {{ font-size:8.6pt;color:{MUTED}; }}
.flow {{ counter-reset:f;list-style:none;padding:0;margin:10px 0 0; }}
.flow li {{ counter-increment:f;position:relative;padding:8px 0 8px 44px;
  border-bottom:1px dotted {LINE};font-size:9.4pt;line-height:1.85; }}
.flow li:last-child {{ border-bottom:0; }}
.flow li::before {{ content:counter(f,decimal-leading-zero);position:absolute;left:0;top:9px;
  width:30px;height:30px;border-radius:9px;background:{NAVY};color:#fff;
  font-size:8.6pt;font-weight:bold;text-align:center;line-height:30px; }}
.flow b {{ display:block;font-size:10.2pt;color:{NAVY}; }}
.price {{ display:grid;grid-template-columns:repeat(3,1fr);gap:11px;margin:12px 0; }}
.pbox {{ border:2px solid {LINE};border-radius:14px;padding:14px 15px;text-align:center; }}
.pbox.hot {{ border-color:{GOLD};background:#fdfaf1; }}
.pbox .n {{ font-size:9pt;color:{MUTED};letter-spacing:.08em; }}
.pbox .p {{ font-size:20pt;font-weight:900;color:{NAVY};margin:4px 0; }}
.pbox .u {{ font-size:8.6pt;color:{MUTED}; }}
.vs {{ display:grid;grid-template-columns:1fr 1fr;gap:11px; }}
.vs > div {{ border:1px solid {LINE};border-radius:10px;padding:12px 14px; }}
.vs h4 {{ font-size:10pt;margin-bottom:6px; }}
.mark {{ background:linear-gradient(transparent 58%, #ffe873 58%); font-weight:bold; }}
.back {{ background:{NAVY};color:#fff;display:flex;flex-direction:column;justify-content:center;
  align-items:center;text-align:center;gap:4mm; }}
.back .s {{ font-size:9.6pt;color:#9db8e0;line-height:2.2; }}
</style></head><body>

<!-- 表紙 -->
<div class="sheet cover">
  {logo_tag()}
  <div class="cv-g"></div>
  <div class="kick">AI OPTIMIZATION × OWNED MEDIA</div>
  <div class="ttl">AIに引用される<br>オウンドメディアを、<br>まるごと運用します。</div>
  <div class="sub">サイト構築から月{PRICE["articles"]}本の記事更新、<br>
  改善指示つきの月次レポートまで一気通貫。</div>
  <div class="badges">
    <span class="badge">AI検索（AIO/LLMO）対応</span><span class="badge">月{PRICE["articles"]}記事</span>
    <span class="badge">品質90点未満は公開しない</span><span class="badge">月次レポート17ページ</span>
  </div>
  <div class="meta">
    セブンセンシズ株式会社｜〒537-0003 大阪府大阪市東成区神路1丁目7-4 コンフォートビル901・902<br>
    TEL 06-4305-7547（9:00〜20:00 / 土日祝休）｜info.ai@7senses.co.jp<br>
    {today.year}年{today.month}月版
  </div>
</div>

<!-- 01 結論 -->
<div class="sheet">
<div class="sec"><span class="no">01</span><h2>このサービスで何が変わるか</h2><div class="gold"></div></div>
<ul class="flow">
  <li><b>検索とAIの両方から見つかる状態をつくります</b>
  Googleの検索結果だけでなく、ChatGPTやAI Overviewの「回答の中」で自社が引用される状態を狙います。
  この2つは対策が異なり、両方を設計できる会社はまだ多くありません。</li>
  <li><b>月{PRICE["articles"]}本の記事が、止まらずに増え続けます</b>
  企画・執筆・図解・公開・検索エンジンへの通知までを自動化しています。
  担当者の退職や繁忙期に左右されず、毎日同じ品質で積み上がります。</li>
  <li><b>「次に何をすべきか」が毎月届きます</b>
  数字の報告だけで終わらせません。記事ごとに「どこをどう直すか」、
  サイト構造のどこを変えるかまで、実行できる粒度で指示します。</li>
</ul>
<div class="callout"><b>広告との決定的な違い:</b> 広告は出稿を止めた瞬間に流入がゼロになります。
記事は<span class="mark">公開後も検索とAIの両方から流入を生み続ける資産</span>です。
本サービスは、その資産を毎月{PRICE["articles"]}本ずつ積み上げていく仕組みそのものをご提供します。</div>
<h3>こういう課題をお持ちの企業に向いています</h3>
<ul>
  <li>広告費を止めると問い合わせが止まる。広告に依存しない集客の柱がほしい</li>
  <li>記事を作りたいが、社内に書ける人がいない・続かない</li>
  <li>外注ライターに頼んだが、品質にばらつきがあり成果につながらなかった</li>
  <li>ChatGPTなどのAI検索が広がる中で、自社が取り残されている感覚がある</li>
  <li>レポートは届くが数字の羅列で、結局何をすればいいのか分からない</li>
</ul>
</div>

<!-- 02 なぜ今か -->
<div class="sheet">
<div class="sec"><span class="no">02</span><h2>なぜ今、AI検索への対応が必要か</h2><div class="gold"></div></div>
<p class="lead">検索の入口が変わりつつあります。従来は「検索して、リンクをクリックして、サイトを見る」でしたが、
いまは<b>AIが答えを直接返し、利用者はクリックせずに済ませる</b>場面が増えています。</p>
<h3>起きている変化</h3>
<table>
<tr><th style="width:26%">従来の検索</th><th>AI検索の時代</th></tr>
<tr><td>検索結果の10本のリンクから選ぶ</td><td>AIが要約した回答が最初に表示され、リンクは参考扱いになる</td></tr>
<tr><td>1位を取ればクリックが集まる</td><td>1位でも、AIの回答に<b>引用されなければ</b>読まれないことがある</td></tr>
<tr><td>Googleだけを見ていればよかった</td><td>ChatGPT・Perplexity・Gemini・Copilotなど、複数の入口ができた</td></tr>
<tr><td>キーワードを詰め込む対策</td><td>AIが<b>抜き出しやすい構造</b>と、<b>引用したくなる独自の事実</b>が評価される</td></tr>
</table>
<div class="warn"><b>ここが重要です。</b> AI検索への対応は、従来のSEOと対立するものではありません。
<span class="mark">Googleで上位を取ることがAIに引用される前提条件</span>であり、
その上で「AIが抜き出しやすい構造」を足す、という二段構えになります。
本サービスは、この二段構えを最初から設計に組み込んでいます。</div>
<h3>先に始めた企業が有利な理由</h3>
<p>AI検索は「よく引用されるサイト」を繰り返し引用する傾向があります。
記事の蓄積とドメインの評価には時間がかかるため、<b>今から始めた企業と1年後に始めた企業では、
追いつくのに1年以上の差がつきます</b>。広告のように「お金を積めば今日から表示される」ものではない、
というのがこの領域の性質です。</p>
</div>

<!-- 03 全体像 -->
<div class="sheet">
<div class="sec"><span class="no">03</span><h2>ご提供するものの全体像</h2><div class="gold"></div></div>
<div class="cards">
  <div class="card"><div class="k">初期</div><div class="v">サイト構築</div>
  <div class="s">オウンドメディア＋LP。AI検索対応を最初から組み込んだ設計</div></div>
  <div class="card"><div class="k">毎月</div><div class="v">{PRICE["articles"]}記事</div>
  <div class="s">企画から公開・通知まで。図解つき5,000字以上</div></div>
  <div class="card"><div class="k">毎月</div><div class="v">改善レポート</div>
  <div class="s">17ページ。記事ごとの修正指示とサイト再構成の提案まで</div></div>
</div>
<h3>作業の分担</h3>
<table>
<tr><th style="width:30%">工程</th><th style="width:22%">担当</th><th>内容</th></tr>
<tr><td>ヒアリング・戦略設計</td><td>当社＋御社</td><td>強み・狙う層・キーワードの方向性をすり合わせ</td></tr>
<tr><td>サイト構築</td><td><b>当社</b></td><td>デザイン・実装・各種設定・計測環境の構築まで</td></tr>
<tr><td>写真の用意</td><td><b>御社</b>（または当社）</td><td>店舗・商品・スタッフ写真をご支給。生成する場合は初期費用30万円</td></tr>
<tr><td>キーワード選定</td><td><b>当社</b></td><td>台帳で共有。ご要望の追加はいつでも可能</td></tr>
<tr><td>記事の企画・執筆・図解</td><td><b>当社</b></td><td>月{PRICE["articles"]}本。御社の作業はゼロ</td></tr>
<tr><td>公開・検索エンジン通知</td><td><b>当社</b></td><td>自動。公開と同時にGoogle・Bingへ通知</td></tr>
<tr><td>効果測定・改善提案</td><td><b>当社</b></td><td>月次レポートで報告し、翌月の改善を実行</td></tr>
<tr><td>内容の最終確認</td><td>御社（任意）</td><td>ご希望に応じて公開前の確認フローを追加可能</td></tr>
</table>
<div class="callout"><b>御社にお願いすること:</b> 初回のヒアリング（1〜2時間）と、写真のご支給だけです。
運用が始まってからの定例会議や原稿確認は<span class="mark">任意</span>で、
「レポートを読むだけ」の運用も可能です。</div>
</div>

<!-- 04 サイト構築の中身 -->
<div class="sheet">
<div class="sec"><span class="no">04</span><h2>サイト構築で作るもの</h2><div class="gold"></div></div>
<p class="lead">「記事が置ける箱」を作るのではありません。
<b>読者が迷わず問い合わせにたどり着き、かつAIが理解しやすい構造</b>を最初から組み込みます。</p>
<table>
<tr><th style="width:24%">項目</th><th>内容</th></tr>
{rows(SITE_FEATURES)}
</table>
<div class="warn"><b>技術的な補足:</b> サイトは静的生成という方式で作ります。
ページをあらかじめ完成品として用意しておく方式のため、<b>表示が速く、攻撃に強く、
アクセスが増えてもサーバー費用が上がりません</b>。
WordPressのような管理画面はありませんが、記事の更新はすべて当社が行うため運用上の支障はありません。</div>
</div>

<!-- 05 AIO対応 -->
<div class="sheet">
<div class="sec"><span class="no">05</span><h2>AI検索に引用されるための12の実装</h2><div class="gold"></div></div>
<p class="lead">「AI対応」と一言で言っても、具体的に何をするのかが分かりにくい領域です。
当社が全記事・全サイトに標準で実装している内容を、すべて公開します。</p>
<table>
<tr><th style="width:26%">実装項目</th><th>内容と狙い</th></tr>
{rows(AIO_FEATURES)}
</table>
<p class="small">※ これらは全記事に自動で適用されます。記事ごとに実装漏れがないかを機械が検査し、
不足があれば公開されない仕組みになっています。</p>
</div>

<!-- 06 記事の作り方 -->
<div class="sheet">
<div class="sec"><span class="no">06</span><h2>記事{PRICE["articles"]}本はこう作られます</h2><div class="gold"></div></div>
<p class="lead">1本の記事が公開されるまでに、7つの工程を通ります。すべて自動で動きますが、
中身は人間の編集者が行う手順をそのまま設計に落とし込んだものです。</p>
<ul class="flow">
{"".join(f'<li><b>{t}</b>{d}</li>' for _, t, d in PHASES)}
</ul>
<h3>1記事に含まれるもの</h3>
<table>
<tr><td style="width:22%"><b>本文</b></td><td>5,000字以上（一般的なSEO記事の1.5〜2倍）</td>
<td style="width:22%"><b>画像</b></td><td>アイキャッチ1枚＋図解3〜5枚</td></tr>
<tr><td><b>FAQ</b></td><td>5問以上。構造化データと完全一致</td>
<td><b>リンク</b></td><td>内部リンク3本以上＋出典の外部リンク</td></tr>
<tr><td><b>根拠</b></td><td>出典付きの数値ファクト3箇所以上</td>
<td><b>導線</b></td><td>目次・CTA2箇所以上・関連記事・前後ナビ</td></tr>
</table>
</div>

<!-- 07 品質保証 -->
<div class="sheet">
<div class="sec"><span class="no">07</span><h2>品質を落とさない四重の検査</h2><div class="gold"></div></div>
<p class="lead">記事を大量に作るとき、最大のリスクは品質のばらつきです。
本サービスでは<b>4段階の検査を通過しない記事は、システム上サイトに載せられません</b>。
「今月は本数が足りないから、少し品質を落として出す」ということが構造的に起きない設計です。</p>
<table>
<tr><th style="width:22%">検査</th><th style="width:16%">項目数</th><th>内容</th></tr>
{rows(GATES)}
</table>
<h3>6観点の採点とは</h3>
<table>
<tr><th style="width:22%">観点</th><th>何を見るか</th></tr>
<tr><td>デザイン</td><td>見出し構成・図解の配置・強調の量・読みやすい段落の長さ</td></tr>
<tr><td>SEO</td><td>タイトルとメタ情報・文字数・内部リンク・独自の事実の数</td></tr>
<tr><td>編集</td><td>AI感の排除・文体の統一・体験談の有無・文末の単調さ</td></tr>
<tr><td>技術正確性</td><td>ツール情報の正確さ・手順の再現性・限界や注意点の明示</td></tr>
<tr><td>読者目線</td><td>悩みに答えているか・専門用語の説明・次の行動が明確か</td></tr>
<tr><td>AI検索対応</td><td>冒頭の断言回答・1文結論・FAQ整合・出典付き数値・鮮度表記</td></tr>
</table>
<div class="callout"><b>採点の厳しさについて:</b> 合計点が基準を超えていても、
<span class="mark">1つの観点でも著しく低ければ不合格</span>にしています。
「デザインは満点だが内容が薄い」記事を、合計点で通してしまわないための仕組みです。</div>
</div>

<!-- 08 運用 -->
<div class="sheet">
<div class="sec"><span class="no">08</span><h2>公開したあとの運用</h2><div class="gold"></div></div>
<p class="lead">記事は書いて終わりではありません。公開後の手入れで成果が大きく変わります。
以下はすべて月額費用に含まれており、追加料金はかかりません。</p>
<table>
<tr><th style="width:14%">頻度</th><th>実施内容</th></tr>
{rows(OPS)}
</table>
<h3>特に効果が大きい3つの運用</h3>
<ul>
  <li><b>リライト（記事の手直し）</b> — 検索順位11〜30位の記事は、少し手を入れるだけで1ページ目に入ることがあります。
  この層を毎週見つけて優先的に改善します。新記事を1本書くより成果が出やすい作業です。</li>
  <li><b>重複記事の検出</b> — 似たテーマの記事が増えると、自社の記事同士で検索順位を奪い合います。
  文章の類似度を機械で測定し、重複が起きる前に検出します。複数サイトを運用される場合は、
  サイトをまたいだ重複も検査します。</li>
  <li><b>情報の鮮度更新</b> — AI検索は情報の新しさを強く評価します。
  古くなった数値・料金・事例を定期的に見つけて更新し、更新日を明示します。</li>
</ul>
</div>

<!-- 09 レポート -->
<div class="sheet">
<div class="sec"><span class="no">09</span><h2>月次レポート（サイト再構成の指示つき）</h2><div class="gold"></div></div>
<p class="lead">毎月1日に17ページのレポートをお送りします。
一般的な「アクセス数の報告書」とは異なり、<b>次に何をどう直すかまで書かれている</b>のが特徴です。
このレポートに基づくサイトの手直しも、月額費用に含まれます。</p>
<h3>レポートに載る内容（全項目）</h3>
<ul>{li(REPORT_ITEMS)}</ul>
<div class="callout"><b>「サイト再構成」まで含みます:</b> レポートで指摘した改善点のうち、
記事の修正・内部リンクの追加・CTAの配置変更・カテゴリ構成の見直しといった作業は、
<span class="mark">翌月の運用の中で当社が実施します</span>。
「指摘はするが直すのは別料金」ということはありません。</div>
</div>

<!-- 10 料金 -->
<div class="sheet">
<div class="sec"><span class="no">10</span><h2>料金</h2><div class="gold"></div></div>
<h3>初期費用（サイト構築）</h3>
<div class="price">
  <div class="pbox hot"><div class="n">1サイト目</div><div class="p">{PRICE["init_1"]}</div>
  <div class="u">オウンドメディア＋LP<br>{PRICE["init_1_note"]}</div></div>
  <div class="pbox"><div class="n">2サイト目以降</div><div class="p">{PRICE["init_2"]}</div>
  <div class="u">設計を流用するため<br>約半額でご提供できます</div></div>
  <div class="pbox"><div class="n">写真</div><div class="p">ご支給</div>
  <div class="u">AI生成をご希望の場合は<br>初期費用30万円</div></div>
</div>
<h3>月額費用（記事{PRICE["articles"]}本＋レポート＋運用）</h3>
<div class="price">
  <div class="pbox hot"><div class="n">1サイト運用</div><div class="p">{PRICE["run_1"]}</div>
  <div class="u">記事{PRICE["articles"]}本／月<br>レポート・改善作業込み</div></div>
  <div class="pbox"><div class="n">2サイト運用</div><div class="p">{PRICE["run_2"]}</div>
  <div class="u">2サイト合計で{PRICE["articles"]}本<br>サイト横断の重複検査つき</div></div>
  <div class="pbox"><div class="n">3サイト運用</div><div class="p">{PRICE["run_3"]}</div>
  <div class="u">3サイト合計で{PRICE["articles"]}本<br>役割分担の設計から対応</div></div>
</div>
<h3>月額に含まれるもの</h3>
<table>
<tr><th style="width:34%">項目</th><th>内容</th></tr>
<tr><td>記事の企画・執筆・図解</td><td>月{PRICE["articles"]}本。1本5,000字以上＋画像4〜6枚</td></tr>
<tr><td>公開作業・検索エンジン通知</td><td>Google・Bingへの即時通知を含む</td></tr>
<tr><td>週次の改善作業</td><td>リライト・重複検出・内部リンク最適化・鮮度更新</td></tr>
<tr><td>月次レポート</td><td>17ページ。改善指示つき</td></tr>
<tr><td>レポートに基づくサイト再構成</td><td>記事修正・導線改善・カテゴリ見直し</td></tr>
<tr><td>サーバー・配信費用</td><td>当社負担（Cloudflare）</td></tr>
<tr><td>問い合わせ管理の仕組み</td><td>台帳の自動記録・メール通知</td></tr>
</table>
<p class="small">※ 表示価格はすべて税別です。ドメイン取得費用、有料の外部ツール利用料、
写真の撮影費用は別途となります。<br>
※ 複数サイトの場合、記事本数は合計{PRICE["articles"]}本を配分する形になります。
本数を増やすご要望には別途お見積りで対応します。</p>
</div>

<!-- 11 費用対効果 -->
<div class="sheet">
<div class="sec"><span class="no">11</span><h2>他の方法と比べた場合</h2><div class="gold"></div></div>
<p class="lead">同じ「月{PRICE["articles"]}本の記事を作る」を他の方法で実現した場合と比較します。</p>
<table>
<tr><th style="width:22%">方法</th><th style="width:24%">月額の目安</th><th>実現できるか</th></tr>
<tr><td><b>本サービス</b></td><td><b>{PRICE["run_1"]}</b></td>
<td>記事{PRICE["articles"]}本＋図解＋公開＋改善レポートまで込み</td></tr>
<tr><td>外注ライターに依頼</td><td>約{w_low}万〜{w_high}万円<br>
<span class="small">1本{MARKET["writer_low"]}〜{MARKET["writer_high"]}万円 × {PRICE["articles"]}本</span></td>
<td>執筆のみ。企画・図解・公開・改善は別途必要</td></tr>
<tr><td>社内で内製</td><td>約{s_low}万〜{s_high}万円<br>
<span class="small">1名月{MARKET["staff_output"]}本として{staff_n}名分の人件費</span></td>
<td>採用・教育・退職リスクを自社で抱える。品質のばらつきも生じやすい</td></tr>
<tr><td>SEOコンサルのみ契約</td><td>約{MARKET["consult_low"]}万〜{MARKET["consult_high"]}万円</td>
<td>助言のみ。記事の制作と実行は自社で行う必要がある</td></tr>
</table>
<div class="callout"><b>本サービスが安く提供できる理由:</b> 企画から公開までの工程を自社で仕組み化しており、
人手でしかできない部分（戦略設計・品質基準の設計・改善判断）に集中しているためです。
<span class="mark">品質を下げて安くしているのではなく、作り方が違います</span>。
その証拠として、品質検査の全項目を本資料で公開しています。</div>
<h3>もう一つの見方 — 広告費との比較</h3>
<p>記事による流入を広告で買った場合の金額は、月次レポートで毎回ご報告します。
検索クリック1回あたりの広告単価は、この領域では300〜1,000円が一般的です。
記事が積み上がるほどこの金額は増え続けますが、<b>広告と違って支払いは増えません</b>。</p>
<p class="small">※ 上記の他社比較は一般的な相場をもとにした目安であり、実際の金額は依頼先により異なります。</p>
</div>

<!-- 12 導入の流れ -->
<div class="sheet">
<div class="sec"><span class="no">12</span><h2>導入の流れ</h2><div class="gold"></div></div>
<ul class="flow">
  <li><b>無料相談（1時間程度）</b>
  現状の課題、既存サイトの有無、狙いたい顧客層を伺います。この段階での費用は発生しません。</li>
  <li><b>無料の現状分析レポート</b>
  既存サイトがある場合は、AI検索への対応度を診断してお渡しします。
  何が足りていないかを具体的にご説明します。</li>
  <li><b>ご提案とお見積り</b>
  サイト構成案、狙うキーワードの一覧、想定スケジュールをご提示します。</li>
  <li><b>ご契約・キックオフ</b>
  写真のご支給と、記事のテーマ方針をすり合わせます。</li>
  <li><b>サイト構築（2〜4週間）</b>
  デザイン確認を挟みながら構築します。計測環境の設定まで当社が行います。</li>
  <li><b>公開・記事更新の開始</b>
  公開翌日から記事が増え始めます。1ヶ月目から{PRICE["articles"]}本のペースで積み上がります。</li>
  <li><b>毎月1日にレポートをお届け</b>
  数字の報告と、翌月の改善内容をご説明します。</li>
</ul>
<div class="warn"><b>成果が見え始める時期の目安:</b> 検索での順位は、公開から3〜6ヶ月で安定してきます。
1〜2ヶ月目は「インデックス登録が進み、表示回数が増える」段階です。
この時期の数字の動きもレポートでご説明しますので、
<span class="mark">何が起きているか分からない期間</span>が生じないようにしています。</div>
</div>

<!-- 13 FAQ -->
<div class="sheet">
<div class="sec"><span class="no">13</span><h2>よくあるご質問</h2><div class="gold"></div></div>
<table>
<tr><th style="width:32%">ご質問</th><th>回答</th></tr>
{rows(FAQS)}
</table>
</div>

<!-- 裏表紙 -->
<div class="sheet back">
  {logo_tag()}
  <div style="font-size:14pt;font-weight:bold;">セブンセンシズ株式会社</div>
  <div class="s">〒537-0003 大阪府大阪市東成区神路1丁目7-4 コンフォートビル901・902<br>
  TEL 06-4305-7547（9:00〜20:00 / 土日祝休）<br>
  info.ai@7senses.co.jp<br><br>
  コーポレートサイト www.7senses.co.jp<br>
  運営メディア「AI集客ラボ」 ai.7senses.co.jp<br><br>
  まずは無料相談から。現状分析レポートを無料でお渡しします。</div>
</div>
</body></html>"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    html_path = OUT / "service-proposal.html"
    pdf_path = OUT / "service-proposal.pdf"
    html_path.write_text(build_html(), encoding="utf-8")
    print(f"HTML: {html_path}")

    try:
        from playwright.sync_api import sync_playwright

        import pdf_util
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.goto(html_path.resolve().as_uri(), wait_until="networkidle")
            pdf_util.compact_pages(pg)
            pdf_util.check_overflow(pg, "提案書")
            pg.pdf(path=str(pdf_path), format="A4", print_background=True,
                   display_header_footer=True, header_template="<div></div>",
                   footer_template='<div style="width:100%;font-size:7px;color:#8ba0bd;'
                                   'padding:0 12mm;display:flex;justify-content:space-between;">'
                                   '<span>AIO特化オウンドメディア構築・運用サービス ｜ セブンセンシズ株式会社</span>'
                                   '<span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>',
                   margin={"top": "0", "bottom": "10mm", "left": "0", "right": "0"})
            b.close()
        print(f"PDF : {pdf_path}")
        if "--open" in sys.argv:
            subprocess.run(["cmd", "/c", "start", "", str(pdf_path)], check=False)
    except Exception as e:
        print(f"PDF生成をスキップ: {e}")


if __name__ == "__main__":
    main()
