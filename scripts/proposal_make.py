# -*- coding: utf-8 -*-
"""営業用の提案書（PDF）を作る。実測の数字は台帳から読むので、古くならない。

**なぜ作り直すか**: 2026年9月に一次情報で確かめた結果、前の版の主張のいくつかが
裏づけを失った。llms.txt は Google が「読まない」と明言し、構造化データも
AI検索には必須でないとされた。一方で、外部での言及や YouTube での言及が
被リンクより強く相関することが分かった。**提案書が実態とずれたままだと、
商談で聞かれたときに答えられない。**

    python scripts/proposal_make.py            # HTMLとPDFを作る
    python scripts/proposal_make.py --html     # HTMLだけ（早い）
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT_DIR = Path(r"C:\Users\user\Desktop\AIO系")
HTML = ROOT / "automation" / "proposal.html"

# 配色は以前の提案書に合わせる（紺＋金・白地）。
# 金は「強調」、濃紺は「当社が担当する範囲」、クリームは「補足」。
# 装飾で色を増やさず、役割のある色だけを置く
NAVY, GOLD, INK, MUTED, LINE, BG = "#1B2A4A", "#B0873E", "#243347", "#6B7A8D", "#E4E8EE", "#FAFBFD"
GOLD_L, CREAM, PANEL = "#EFE4CE", "#FBF7EE", "#17253F"
ACCENT, STOP, STOPBG, PAPER = GOLD, "#A15C2B", "#FDF4EC", "#FFFFFF"


def facts():
    """提案書に載せる数字を、台帳から読む。手で書かない（古くなるため）"""
    f = {"date": date.today().strftime("%Y.%m")}
    f["datasets"] = len([p for p in (ROOT / "site" / "data").glob("*") if p.is_dir()])
    f["articles"] = len(list((ROOT / "articles").glob("*.md")))
    try:
        d = json.loads((ROOT / "data" / "first_party_facts.json").read_text(encoding="utf-8"))
        f["facts"] = len(json.dumps(d))
    except Exception:
        f["facts"] = 0
    return f


PAGES = []


def page(kind, num, eyebrow, title, lead, body):
    PAGES.append({"kind": kind, "num": num, "eyebrow": eyebrow,
                  "title": title, "lead": lead, "body": body})


def tbl(head, rows, widths=None):
    w = widths or []
    th = "".join(f'<th{f" style=width:{x}" if x else ""}>{c}</th>'
                 for c, x in zip(head, w + [""] * len(head)))
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>"


def cards(items):
    return '<div class="cards">' + "".join(
        f'<div class="card"><div class="ic">{"◆"}</div>'
        f'<div class="cn">{n}</div><div class="ct">{t}</div>'
        f'<div class="cb">{b}</div></div>' for n, t, b in items) + "</div>"


def bars(rows, unit=""):
    mx = max(v for _, v, _ in rows) or 1
    out = ['<div class="bars">']
    for label, v, note in rows:
        on = "on" if note == "★" else ""
        out.append(
            f'<div class="bar {on}"><div class="bl">{label}</div>'
            f'<div class="bt"><i style="width:{v / mx * 100:.0f}%"></i></div>'
            f'<div class="bv">{v}{unit}</div></div>')
    return "".join(out) + "</div>"


def flow(steps, note="", on=-1):
    """横に並ぶ工程図。矢印は「この順でしか進まない」ことを示す。

    on に番号を渡すと、その段だけ濃紺で塗る。いまどこの話かが一目で分かる
    （以前の提案書と同じ作法）。
    """
    items = []
    for i, (t, b) in enumerate(steps):
        if i:
            items.append('<div class="fa">&rarr;</div>')
        cls = "fs on" if i == on else "fs"
        items.append(f'<div class="{cls}"><div class="ft"><i>{i + 1}</i>{t}</div>'
                     f'<div class="fb">{b}</div></div>')
    out = '<div class="flow">' + "".join(items) + "</div>"
    return out + (f'<p class="note">{note}</p>' if note else "")


def build_pages(f):
    PAGES.clear()

    page("cover", "", "SEVEN SENSES INC. ｜ PROPOSAL " + f["date"],
         "AIに引用される<br>オウンドメディアを、<br>まるごと運用します。",
         "サイト構築から月60本の記事更新、解説動画とSNSの投稿文、"
         "改善指示つきの月次レポートまで ｜ 一気通貫でお任せいただけます。", "")

    page("toc", "", "CONTENTS", "目次",
         "戦略設計から実装、品質保証、改善、そして発信まで。AI検索時代の"
         "オウンドメディア運用を、16の章でご説明いたします。",
         '<div class="toc">' + "".join(
             f'<div class="ti"><span class="tn">{n:02d}</span>{t}</div>'
             for n, t in enumerate([
                 "このサービスで、何が変わるか", "なぜ今、AI検索への対応が必要か",
                 "AI検索で本当に効くもの（実測）", "ご提供するものの全体像",
                 "作業の分担", "オウンドメディア × LP という設計思想",
                 "4つの手法を、同じ土俵で比べる", "サイト構築で作るもの",
                 "AIに引用されるための工夫", "そこにしか無い数字をつくる",
                 "記事60本のつくり方", "品質を落とさない四重の検査",
                 "判断そのものを、実測で確かめる", "動画とSNSへの自動展開",
                 "毎日の見張りと、月次レポート", "料金と、4つのお約束"], 1)) + "</div>")

    page("std", "01", "SERVICE OVERVIEW", "このサービスで、何が変わるか",
         "本サービスが実現するのは、次の3つの状態です。広告のような「出稿を止めれば"
         "終わり」の施策ではなく、御社の資産として積み上がり続ける集客の柱をつくります。",
         cards([
             ("01", "検索とAIの両方から<br>見つかる状態をつくる",
              "Googleの検索結果だけでなく、ChatGPT・Perplexity・Gemini の回答の中でも"
              "御社が参照される状態を目指します。"),
             ("02", "見つかった後、<br>問い合わせまで運ぶ",
              "記事で知ってもらうだけでは終わりません。専用LPへの一本道を最初から設計し、"
              "相談につながる導線をつくります。"),
             ("03", "止めても消えない<br>資産として積み上がる",
              "広告は出稿を止めれば流入も止まります。記事と一次データは残り、"
              "翌月以降も働き続けます。")]) +
         '<h3 class="mini">毎月、この流れで回り続けます</h3>' +
         flow([("戦略設計", "狙う業種と扱わない領域を決める"),
               ("サイト構築", "初期のみ"),
               ("記事50〜60本", "毎月。検査を通ったものだけ公開"),
               ("動画とSNS", "同じ内容から自動生成"),
               ("改善レポート", "翌月の運用にそのまま反映")], on=2))

    page("std", "02", "MARKET SHIFT", "なぜ今、AI検索への対応が必要か",
         "検索の入口が変わりつつあります。従来は「検索して、リンクをクリックして、"
         "サイトを見る」でしたが、いまはAIが答えを直接返し、利用者がクリックせずに"
         "済ませる場面が増えています。",
         tbl(["", "従来の検索", "AI検索の時代"], [
             ["利用者の動き", "検索結果の10本のリンクから選んで開く",
              "AIの回答を読んで、必要なときだけ開く"],
             ["企業がやること", "検索結果で上位に入る",
              "<b>AIの回答の中で参照される</b>"],
             ["効いてくるもの", "被リンク・キーワード",
              "<b>そこにしか無い数字・外部での言及</b>"],
             ["表示のされ方", "10本のリンク", "1つの答えと、数本の出典"]],
             ["16%", "40%", "44%"]) +
         '<p class="note">Google AI Overview の表示率は13.7%ですが、'
         '<b>質問形のクエリでは64.7%</b>に跳ね上がります'
         '（Washington University・55,393クエリ・2026年3〜4月）。'
         'また AI Overview が引用したドメインの約30%は、同じ検索の1ページ目に'
         '出ていませんでした。<b>順位とは別の選ばれ方がある</b>ということです。</p>')

    page("std", "03", "WHAT ACTUALLY WORKS", "AI検索で本当に効くもの（実測）",
         "「AI対策」として語られる手法の多くは、一次情報にあたると裏づけがありませんでした。"
         "当社は通説ではなく、公開された実測と自社のデータだけを根拠にします。",
         bars([("YouTubeでの言及", 71, "★"), ("リンクの無いWeb言及", 66, "★"),
               ("ブランド名のアンカー", 53, ""), ("指名検索の量", 39, ""),
               ("Domain Rating", 33, ""), ("被リンクの本数", 22, "")], "") +
         '<p class="note">AI Overview での可視性との相関（Ahrefs・75,000ブランド・'
         'Spearman・2025年12月公表）。数値は相関係数を100倍したもの。'
         '<b>被リンクより「言及」が3倍強く相関します。</b>AIがブランドに触れても'
         'リンクを張るのは28%だけなので、リンクの有無で数えると実態を取り逃がします。'
         'なお著者自身が「相関は因果ではない」と明記しており、当社もそのように扱います。</p>' +
         tbl(["よく言われること", "Googleの公式見解（2026年5月）"], [
             ["llms.txt がAI検索に効く", "<b>無視する。</b>害も益も無い"],
             ["構造化データがAI引用に必須", "<b>必須ではない。</b>専用スキーマも存在しない"],
             ["内容を細かく刻むと理解されやすい", "不要。複数の話題があるページも理解できる"],
             ["GEO/AEO の技法", "「Googleの仕組みに照らして効かない」"],
             ["", "<b>効くのは、独自の視点・一般論に留まらない内容・クロールできること</b>"]],
             ["44%", "56%"]) if False else "")

    page("std", "03", "WHAT ACTUALLY WORKS", "通説と、Googleの公式見解",
         "「AI対策」として広く語られている手法のうち、Googleが公式に否定しているものを"
         "並べます。当社はこれらを成果の根拠に数えません。",
         tbl(["よく言われること", "Googleの公式見解（2026年5月のAI最適化ガイド）"], [
             ["llms.txt がAI検索に効く", "<b>無視する。</b>害も益も無い"],
             ["構造化データがAI引用に必須", "<b>必須ではない。</b>AI検索向けの専用スキーマも存在しない"],
             ["内容を細かく刻むと理解されやすい", "不要。複数の話題があるページも理解できる"],
             ["AI向けの特別な書き方がある", "不要。同義語も文意も理解する"],
             ["GEO/AEO の技法", "「Googleの仕組みに照らして効かない」"]],
             ["40%", "60%"]) +
         '<p class="note stop"><b>Googleが効くと明記しているのは3つだけです。</b>'
         '独自の視点（一次体験）／一般論に留まらない内容／クロールできること。'
         'リッチリザルト目的の構造化データは引き続き有効なので、当社は出力を変えていません。'
         '<b>変えたのは「成果の根拠に数えるかどうか」です。</b></p>')

    page("std", "04", "DELIVERABLES", "ご提供するものの全体像",
         "サービスは4つ。「初期のサイト構築」「毎月60本の記事更新」「解説動画とSNSの投稿文」"
         "「毎月の改善レポート」。すべてお任せいただける一気通貫の運用体制です。",
         cards([
             ("初期", "サイト構築",
              "オウンドメディア＋LP。AIが理解しやすい構造と、問い合わせまでの導線を"
              "最初から組み込みます。"),
             ("毎月", "記事60本",
              "キーワード選定から公開・内部リンクの手入れまで自動。"
              "基準に届かない記事はそもそも生成されません。"),
             ("毎月", "動画とSNS",
              "記事と一次データから解説動画を自動生成し、YouTubeへ。"
              "X・Facebook・Threads・LinkedIn の投稿文もお渡しします。"),
             ("毎月", "改善レポート",
              "17ページ。実測にもとづく改善点と、その直し方まで。"
              "「何をやらないか」も根拠つきでお示しします。")]))

    page("std", "05", "WORK DIVISION", "作業の分担 ｜ 御社の手間は最小限に",
         "御社にお願いすることは、初回のヒアリング（1〜2時間）と写真のご支給、"
         "そして機械では埋められない数点だけです。運用開始後の定例会議や原稿確認は任意で、"
         "「レポートを読むだけ」の運用も可能です。",
         tbl(["工程", "担当", "内容"], [
             ["ヒアリング・戦略設計", "当社＋御社", "強み・狙う業種・扱わない領域を1〜2時間で"],
             ["サイト構築・記事制作", "<b>当社</b>", "設計から公開まで。ご確認は任意"],
             ["一次データの抽出", "御社→当社", "<b>記録を行のままお渡しいただければ集計は当社で</b>"],
             ["公的登録・認定の申請", "御社", "登録支援事業者・認定支援機関など。無料のものが多い"],
             ["YouTubeチャンネルの許可", "御社", "1度だけ「投稿を許可」を押していただきます"],
             ["SNSへの掲載", "御社", "当社が作った投稿文を貼るだけ"],
             ["計測・改善・レポート", "<b>当社</b>", "毎週の自動検査と、毎月のレポート"]],
             ["26%", "14%", "60%"]))

    page("std", "06", "OWNED MEDIA × LP", "オウンドメディア × LP という設計思想",
         "SEO対策とAIO対策は当然実装した上で、本サービスが標準で組み込むのが"
         "「オウンドメディア＋LP」の二本立て設計。記事で“見つかる”だけでなく、"
         "専用LPで“問い合わせまで運ぶ”一本道を最初から設計します。",
         cards([
             ("A", "記事が入口をつくる",
              "検索とAIの回答から人が来ます。1記事が1つの疑問に完結して答える形にし、"
              "AIが抜き出しやすい構造で書きます。"),
             ("B", "LPが判断を助ける",
              "記事を読んだ人が次に知りたいのは「誰に頼むか」です。実績・料金・"
              "流れをLPに集約し、迷わせません。"),
             ("C", "指名検索に変わる",
              "AIの回答で名前を知った人が、社名で検索し直します。"
              "<b>自社の実測では28日で+194%</b>（78→229表示）。")]))

    page("std", "07", "COMPARISON", "4つの手法を、同じ土俵で比べる",
         "「AI検索で見つかる」までの手法は複数ありますが、見つかった後に成約まで"
         "運べるかで差がつきます。4つの主要な組み合わせを比較しました。",
         tbl(["", "集客", "成約", "資産化", "持続性", "費用の性質"], [
             ["<b>本サービス</b><br>オウンドメディア＋LP＋動画",
              "◎", "◎", "◎", "◎", "月額。止めても記事は残る"],
             ["リスティング広告", "◎", "○", "×", "×", "出稿を止めた日に流入ゼロ"],
             ["SNS運用のみ", "○", "△", "△", "△", "投稿を止めると届かなくなる"],
             ["記事外注（1本ずつ発注）", "○", "△", "○", "△", "1本ごとに費用。検査は発注側"]],
             ["30%", "10%", "10%", "12%", "12%", "26%"]))

    page("std", "08", "SITE BUILD", "サイト構築で作るもの",
         "「記事が置ける箱」を作るのではありません。読者が迷わず問い合わせにたどり着き、"
         "かつAIが理解しやすい構造を最初から組み込みます。",
         tbl(["区分", "作るもの"], [
             ["ページ構成", "トップ／カテゴリ一覧／記事詳細／サービスLP／会社情報／お問い合わせ／"
              "プライバシーポリシー／特定商取引法表記／<b>一次データの公開ページ</b>／"
              "<b>業種別のまとめページ</b>"],
             ["構造", "手法（AIO・SEO・MEO）と業種の2軸。読者が探す単位に合わせます"],
             ["表示速度", "日本語Webフォントを使わず端末のフォントで描画。"
              "<b>実測で総合62→96、LCP 7.3秒→2.1秒、転送1.8MB→0.38MB</b>"],
             ["計測", "GA4・Search Console・AI参照元・生成AIレポートの取り込みまで"],
             ["通知", "問い合わせは即時メール。異常は自動で検知して知らせます"]],
             ["18%", "82%"]))

    page("std", "09", "CRAFTS FOR AI CITATION", "AIに引用されるための工夫",
         "「AI対応」と一言で言っても、具体的に何をするのかが分かりにくい領域です。"
         "当社が全記事に標準で実装している内容を、すべて公開します。"
         "不足があれば、その記事は公開されません。",
         tbl(["実装すること", "なぜ効くか"], [
             ["冒頭200字の断言型回答", "AIが最初に読む場所。「◯◯は◯◯です」で始める"],
             ["見出し直下の1文結論（40〜60字）", "その1文だけ切り出しても意味が通るため、回答にそのまま使われる"],
             ["<b>質問形の見出し</b>", "<b>AIの回答は質問形のクエリで表示率が13.7%→64.7%に上がる</b>"],
             ["定義ブロック・比較表・FAQ", "抜き出しやすい形。表は単体で意味が完結するように書く"],
             ["出典付きの数値（3箇所以上）", "AIは数値付きの断定文を優先して引用する"],
             ["鮮度の明示とdateModified", "古い情報は選ばれにくい。「◯年◯月時点」を必ず書く"],
             ["対象読者の限定と失敗例", "誰向けかが分かる記事のほうが、AIも人も判断しやすい"],
             ["AIクローラーの許可と<b>毎日の到達確認</b>",
              "<b>robots.txtに許可と書いてもCDNが手前で落とすことがある。実際のUAで毎日確認</b>"]],
             ["36%", "64%"]))

    page("std", "10", "FIRST-PARTY DATA", "そこにしか無い数字をつくる",
         "AIが回答の根拠に選ぶのは「そこにしか無い数字」です。公開情報の言い換えは"
         "引用されません。御社の記録を、引用される形に変えるのが本サービスの中核です。",
         cards([
             ("01", "行のままお預かりします",
              "集計済みの数字ではなく、記録の行をそのまま。平均だけだと"
              "一部の大きい値に引っ張られていないか確かめられません。"),
             ("02", "集計は当社で行います",
              "中央値・分布・外れ値の影響まで出したうえで、どの数字を公開するかを"
              "ご相談します。"),
             ("03", "引用される形にします",
              "表・棒グラフ・CSV・Dataset構造化データ・引用用の一文まで自動生成し、"
              "記事からも参照されます。")]) +
         '<p class="note"><b>公開の条件は3つ。</b>母数10件以上（10件未満の割合は1件動くと'
         '10ポイント動き、個社の特定にもつながります）。集計期間が明記できること'
         '（割合には母数と期間の両方が必要／景品表示法）。個社名・店名・住所を含まないこと。'
         '<b>記憶や概算の数字は使いません。</b>記録から取れない数字は公開しません。'
         f'（自社での公開実績: {f["datasets"]}本）</p>')

    page("std", "11", "ARTICLE PROCESS", "記事60本のつくり方",
         "1本の記事が公開されるまでに7つの工程を通ります。人間の編集者が行う手順を"
         "そのまま設計に落とし込んだ、丁寧なつくり方です。",
         tbl(["#", "工程", "内容"], [
             ["1", "キーワード選定",
              "台帳から次のテーマを取得し、既存記事との重複を機械で検査。"
              "<b>「開かないと済まない語」かどうかも判定します</b>"],
             ["2", "一次情報の収集", "YouTubeの字幕から、引用できる一文だけを抜き出します"],
             ["3", "構成の設計", "上位記事の見出しを分析し、共通6〜7割＋独自3〜4割で組みます"],
             ["4", "構成の事前審査", "14項目。1項目でも欠けたまま執筆を始めません"],
             ["5", "執筆", "一次情報を2割以上組み込み、AI感を排除"],
             ["6", "品質検査", "機械検査＋別工程の採点。基準に届かない記事は生成されません"],
             ["7", "公開と通知", "画像生成・構造化データ・サイトマップ・検索エンジンへの即時通知"]],
             ["6%", "22%", "72%"]))

    page("std", "12", "QUALITY CONTROL", "品質を落とさない四重の検査",
         "記事を大量に作るときの最大のリスクは品質のばらつきです。4段階の検査を通過"
         "しない記事はサイトに載らず、「今月は本数が足りないから品質を落として出す」"
         "ということが構造的に起きません。",
         tbl(["段階", "何を見るか", "落ちたらどうなるか"], [
             ["構成の事前審査", "14項目。狙う語の重複・見出しの設計・一次情報の有無",
              "執筆を始めない"],
             ["機械検査", "文字数・メタ字数・内部リンク404・図表の取りこぼし・生成HTMLの崩れ",
              "<b>ファイルごと生成されない</b>"],
             ["別工程の採点", "<b>書いた工程とは別の工程が、本文だけを読んで採点。"
              "一次性・抽出性・決定支援の3軸（各10点、各7点以上・合計24点以上）</b>",
              "弱い記事として改善対象に"],
             ["公開後の見直し", "内部リンクの積み上がり・同じ言い回しの偏り・段落の長さ",
              "毎週自動で直す"]],
             ["20%", "50%", "30%"]) +
         '<p class="note">採点する工程には点数を見せません。'
         '<b>前の工程の判断を引き継がないようにするため</b>です。</p>')

    page("std", "13", "VALIDATE THE RULES", "判断そのものを、実測で確かめる",
         "多くの運用会社は「品質スコアを上げます」「内部リンクを増やします」と言います。"
         "当社はその判断が本当に成果を分けているかを毎週検証し、"
         "<b>効かないと分かったものは止めます</b>。",
         tbl(["よく言われる施策", "自社データでの実測", "当社の扱い"], [
             ["品質スコアを上げる", "<b>逆になっている。</b>91〜93点が96点以上より4.1位<b>上</b>",
              "公開の門には使うが、記事を選ぶ基準にはしない"],
             ["内部リンクを増やす", "本数の順序と成果の順序が一致しない", "下限を割る記事だけ補う"],
             ["記事を長くする", "5,500字未満が最良（17.6位）", "下限は満たす。伸ばすこと自体を目的にしない"],
             ["llms.txt を整える", "Googleが公式に「読まない」と明言", "設置は残すが成果に数えない"],
             ["<b>開く理由のある語を狙う</b>", "<b>成果を分けている</b>",
              "<b>キーワード選定の重みを上げました</b>"]],
             ["24%", "40%", "36%"]) +
         '<p class="note">努力の総量は変わりません。<b>効かないことに使えば、効くことに使えません。</b>'
         'この検証結果は毎月のレポートにそのまま載ります。</p>')

    page("std", "14", "VIDEO & SOCIAL", "動画とSNSへの自動展開",
         "記事は書いて終わりではありません。同じ内容から解説動画とSNSの投稿文を"
         "自動で作り、御社の名義で発信します。追加費用はかかりません。",
         cards([
             ("01", "解説動画を自動生成",
              "記事と一次データから、ナレーション・スライド・字幕つきの動画を作ります"
              "（90秒〜3分）。声は男女から選べます。"),
             ("02", "YouTubeへ自動投稿",
              "御社のチャンネルへ。概要欄には記事URLと、母数・期間・集計方法まで入ります。"
              "最初は限定公開で、ご確認いただいてから公開します。"),
             ("03", "SNSの投稿文をお渡し",
              "X・Facebook・Threads・LinkedIn の4媒体ぶん。"
              "貼るだけの形でお届けします。")]) +
         flow([("記事・一次データ", "既に公開しているもの"),
               ("台本", "本文に書かれていることだけを抜き出す"),
               ("ナレーション", "読み上げ用に日付・略語・URLを直す"),
               ("スライドと字幕", "読み上げの実測に合わせて切り替え"),
               ("YouTube", "概要欄に記事URLと母数・期間")]) +
         '<p class="note"><b>なぜYouTubeを最初に置くか。</b>AI検索での可視性と最も強く'
         '相関するのがYouTubeでの言及だからです（AI Overviews 0.712・ChatGPT 0.737）。'
         'Web言及0.656、被リンク0.218より上でした。<br>'
         '<b>なぜSNSは自動投稿にしないか。</b>Xは2026年2月に新規の無料枠が廃止され、'
         'リンク付き投稿が1件0.20ドルかかります。FacebookとThreadsは無料ですが、'
         '他社ページへの投稿にはMetaの審査が必要です。投稿文をお渡しする形なら、'
         '権限も審査も課金も要りません。効果が出ると分かってから自動化に切り替えます。</p>')

    page("std", "15", "WATCH & REPORT", "毎日の見張りと、月次レポート",
         "記事の質をいくら上げても、AIのクローラーが入れなければ引用されません。"
         "人が忘れることを、機械が毎日覚えています。",
         tbl(["いつ", "見るもの", "見つけたらどうするか"], [
             ["毎日", "<b>AIクローラーが本番に入れるか</b>",
              "<b>実際のUAで叩いて確認。塞がっていればメールで知らせ、直し方も本文に載せます</b>"],
             ["毎日", "公開できなかった記事", "自動で救済し、それでも駄目なら知らせます"],
             ["毎週", "宣言した主要クエリの順位", "上がらない語を4つの原因に分けて、対応する工程へ"],
             ["毎週", "指名検索・外部での言及", "減っていれば知らせます"],
             ["毎週", "判断の当たり具合", "効かない判断が見つかれば、基準を作り直します"],
             ["毎月", "17ページのレポート",
              "<b>改善点と、その直し方。やらないことも根拠つきで</b>"]],
             ["10%", "34%", "56%"]) +
         '<p class="note">Cloudflare は2026年9月15日から、AIのクローラーを既定で'
         'ブロックする方針に変えました。この既定は「学習用」と「回答用」を区別しないため、'
         '気づかないうちにChatGPTやPerplexityの回答から消えることがあります。</p>')

    page("std", "16", "PRICING & COMMITMENT", "料金と、4つのお約束",
         "初期費用はサイト構築のみ。月額費用に記事60本・動画・SNS投稿文・レポート・"
         "改善作業のすべてが含まれます。（表示価格はすべて税別）",
         tbl(["区分", "内容", "価格"], [
             ["初期費用", "1サイト目（オウンドメディア＋LP）", "20万〜30万円"],
             ["初期費用", "2サイト目以降（設計を流用）", "10万〜15万円"],
             ["月額", "記事60本・動画・SNS投稿文・レポート・改善作業", "別途お見積り"],
             ["追加費用", "<b>ありません</b>（公開後の手入れ・改善・レポートは月額に含む）", "―"]],
             ["16%", "60%", "24%"]) +
         cards([
             ("01", "品質を数で妥協しない",
              "本数が足りなくても、基準に届かない記事は生成されません。"),
             ("02", "作った数字は公開しない",
              "記録から取れない数字は使いません。割合には母数と期間を必ず添えます。"),
             ("03", "効かないことはやめる",
              "実測で成果を分けていない施策は、根拠を示して止めます。"),
             ("04", "解約後も資産は残る",
              "公開済みの記事は御社のサイトに残り、原稿データもお渡しします。")]))


def html(f):
    build_pages(f)
    css = f"""
*{{box-sizing:border-box;margin:0;padding:0}}
@page{{size:297mm 210mm;margin:0}}
body{{font-family:"Yu Gothic","Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif;
 color:{INK};-webkit-print-color-adjust:exact;print-color-adjust:exact;
 font-feature-settings:"palt" 1}}
.p{{width:297mm;height:210mm;padding:15mm 17mm 13mm;position:relative;
 page-break-after:always;overflow:hidden;background:{PAPER}}}
.p:last-child{{page-break-after:auto}}
.eyebrow{{font-size:7.4pt;letter-spacing:.42em;color:{GOLD};font-weight:700;
 text-transform:uppercase;white-space:nowrap}}
.eyebrow s{{text-decoration:none;color:{GOLD_L};margin:0 2mm;letter-spacing:0}}
h1{{font-size:23pt;line-height:1.4;color:{NAVY};letter-spacing:.005em;
 margin:3.4mm 0 3mm;font-weight:800;text-wrap:balance}}
h1 em{{color:{GOLD};font-style:normal}}
.lead{{font-size:9.2pt;line-height:1.9;color:{MUTED};max-width:208mm;margin-bottom:7mm}}
.num{{position:absolute;bottom:9.4mm;right:17mm;font-size:7.4pt;color:#A8B3C1;
 letter-spacing:.06em;font-variant-numeric:tabular-nums}}
.num b{{color:{GOLD};font-weight:800}}

table{{width:100%;border-collapse:separate;border-spacing:0;font-size:8.5pt;
 line-height:1.7;font-variant-numeric:tabular-nums;
 border:1px solid {LINE};border-radius:6px;overflow:hidden}}
th{{background:{NAVY};color:#fff;text-align:left;padding:3mm 3.6mm;
 font-weight:700;font-size:8pt;letter-spacing:.03em}}
td{{border-top:1px solid {LINE};padding:3mm 3.6mm;vertical-align:top}}
tbody tr:nth-child(even) td{{background:{BG}}}
td b{{color:{NAVY}}}

.cards{{display:flex;gap:5mm}}
.card{{flex:1;background:#fff;border:1px solid {LINE};border-radius:8px;
 padding:6mm 5.4mm 6.4mm;position:relative;box-shadow:0 1px 3px rgba(27,42,74,.05)}}
.cn{{font-size:22pt;font-weight:800;color:{GOLD_L};line-height:1;margin-bottom:2mm;
 font-variant-numeric:tabular-nums}}
.ct{{font-size:11.5pt;font-weight:800;color:{NAVY};line-height:1.45;margin-bottom:3mm}}
.cb{{font-size:8.3pt;line-height:1.85;color:{MUTED}}}
.card .ic{{position:absolute;top:5.4mm;right:5.4mm;width:11mm;height:11mm;
 border-radius:50%;background:{GOLD_L};display:flex;align-items:center;
 justify-content:center;color:{GOLD};font-size:12pt;font-weight:800}}

.panel{{background:{PANEL};border-radius:8px;padding:6.4mm 6mm;color:#fff}}
.panel h3{{font-size:11.5pt;font-weight:800;margin-bottom:4.4mm;color:#fff}}
.panel h3 em{{color:{GOLD};font-style:normal}}
.panel li{{list-style:none;font-size:8.8pt;line-height:1.6;padding:2.2mm 0 2.2mm 8mm;
 position:relative;color:#DCE4F0}}
.panel li::before{{content:"";position:absolute;left:0;top:2.6mm;width:4.6mm;height:4.6mm;
 border-radius:50%;background:{GOLD}}}

.note{{margin-top:5mm;font-size:8pt;line-height:1.85;color:{MUTED};
 background:{CREAM};padding:4.4mm 5.4mm;border-radius:6px}}
.note b{{color:{GOLD}}}
.note.stop{{background:{STOPBG}}}
.note.stop b{{color:{STOP}}}

.bars{{margin:1mm 0}}
.bar{{display:flex;align-items:center;gap:4mm;margin-bottom:3.4mm}}
.bl{{width:50mm;font-size:8.8pt;color:{MUTED};text-align:right}}
.bt{{flex:1;height:6.6mm;background:#EFF2F7;border-radius:3px;overflow:hidden}}
.bt i{{display:block;height:100%;background:#C7CFDC;border-radius:3px}}
.bar.on .bl{{color:{NAVY};font-weight:800}}
.bar.on .bt i{{background:{GOLD}}}
.bv{{width:12mm;font-size:9.2pt;color:{MUTED};font-weight:800;
 font-variant-numeric:tabular-nums;text-align:right}}
.bar.on .bv{{color:{NAVY}}}

.mini{{font-size:9.6pt;font-weight:800;color:{NAVY};margin:7mm 0 3.4mm}}
.flow{{display:flex;align-items:stretch;gap:2.4mm;margin-top:1mm}}
.fs{{flex:1;background:#fff;border:1px solid {LINE};border-radius:7px;padding:4.6mm 4mm;
 box-shadow:0 1px 3px rgba(27,42,74,.05)}}
.fs.on{{background:{PANEL};border-color:{PANEL}}}
.fs.on .ft{{color:#fff}} .fs.on .fb{{color:#C6D2E4}}
.ft{{font-size:9.4pt;font-weight:800;color:{NAVY};line-height:1.45;margin-bottom:2.4mm}}
.ft i{{color:{GOLD};font-style:normal;margin-right:1.6mm}}
.fb{{font-size:7.9pt;line-height:1.8;color:{MUTED}}}
.fa{{align-self:center;color:{GOLD_L};font-size:16pt;font-weight:700}}
.split{{display:flex;gap:5mm;align-items:stretch}}
.split>*{{flex:1;min-width:0}}

.cover{{background:{NAVY};color:#fff;padding:0;display:grid;
 grid-template-columns:1.3fr 1fr}}
.cv-l{{padding:24mm 0 16mm 17mm;display:flex;flex-direction:column;justify-content:center}}
.cover .eyebrow{{color:{GOLD}}}
.cover h1{{color:#fff;font-size:32pt;line-height:1.42;margin:5mm 0 7mm;font-weight:800}}
.cover h1 em{{color:{GOLD};font-style:normal}}
.cover .lead{{color:#B6C3D6;font-size:9.6pt;max-width:150mm;line-height:1.95;margin:0}}
.brand{{position:absolute;bottom:13mm;left:17mm;font-size:7pt;
 letter-spacing:.34em;color:{GOLD}}}
.cv-r{{background:{PANEL};padding:26mm 17mm 20mm 12mm;display:flex;
 flex-direction:column;justify-content:center}}
.cv-t{{font-size:7pt;letter-spacing:.34em;color:{GOLD};font-weight:700;margin-bottom:6mm}}
.cvb{{display:flex;align-items:center;gap:3.4mm;margin-bottom:3.6mm}}
.cvl{{width:34mm;font-size:8pt;color:#93A3BA;text-align:right;line-height:1.3}}
.cvt{{flex:1;height:5.4mm;background:#223353;border-radius:3px;overflow:hidden}}
.cvt i{{display:block;height:100%;background:#3D4E6E;border-radius:3px}}
.cvb.on .cvl{{color:#fff;font-weight:800}}
.cvb.on .cvt i{{background:{GOLD}}}
.cvv{{width:9mm;font-size:8.4pt;color:#93A3BA;font-weight:800;text-align:right;
 font-variant-numeric:tabular-nums}}
.cvb.on .cvv{{color:{GOLD}}}
.cv-n{{margin-top:7mm;font-size:7.2pt;line-height:1.85;color:#8FA0B8;
 border-top:1px solid #2A3A58;padding-top:5mm}}

.toc{{display:grid;grid-template-columns:1fr 1fr;gap:3.4mm 12mm}}
.ti{{font-size:9.2pt;color:{NAVY};border-bottom:1px solid {LINE};padding-bottom:2.6mm;
 display:flex;gap:4mm}}
.tn{{color:{GOLD};font-weight:800;font-variant-numeric:tabular-nums}}
.foot{{position:absolute;bottom:9.4mm;left:17mm;font-size:7.4pt;color:#A8B3C1}}
"""
    body = []
    total = len(PAGES)
    for i, pg in enumerate(PAGES, 1):
        if pg["kind"] == "cover":
            rows = [("YouTubeでの言及", 71, 1), ("リンクの無いWeb言及", 66, 1),
                    ("ブランド名のアンカー", 53, 0), ("指名検索の量", 39, 0),
                    ("Domain Rating", 33, 0), ("被リンクの本数", 22, 0)]
            gr = "".join(
                f'<div class="cvb {"on" if on else ""}"><div class="cvl">{l}</div>'
                f'<div class="cvt"><i style="width:{v / 71 * 100:.0f}%"></i></div>'
                f'<div class="cvv">{v}</div></div>' for l, v, on in rows)
            body.append(
                f'<div class="p cover"><div class="cv-l">'
                f'<div class="eyebrow">{pg["eyebrow"]}</div>'
                f'<h1>{pg["title"]}</h1>'
                f'<div class="lead">{pg["lead"]}</div>'
                f'<div class="brand">SEVEN SENSES INC.</div></div>'
                f'<div class="cv-r"><div class="cv-t">WHAT ACTUALLY WORKS</div>{gr}'
                f'<div class="cv-n">AI検索での可視性との相関（Ahrefs・75,000ブランド）。'
                f'被リンクより「言及」が3倍強く相関します。<br>'
                f'当社は通説ではなく、実測だけを根拠にします。</div></div></div>')
            continue
        n = f'<div class="num">{i:02d} / {total}</div>'
        g = f'<div class="ghost">{pg["num"]}</div>' if pg["num"] else ""
        body.append(
            f'<div class="p">{g}{n}<div class="eyebrow">{pg["eyebrow"]}</div>'
            f'<h1>{pg["title"]}</h1>'
            f'<div class="lead">{pg["lead"]}</div>{pg["body"]}'
            f'<div class="foot">AIO特化オウンドメディア構築・運用サービス ｜ '
            f'セブンセンシズ株式会社</div></div>')
    return f"<!doctype html><html lang=ja><meta charset=utf-8><style>{css}</style>" \
           f"<body>{''.join(body)}</body></html>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", action="store_true", help="HTMLだけ作る")
    a = ap.parse_args()

    f = facts()
    HTML.parent.mkdir(parents=True, exist_ok=True)
    HTML.write_text(html(f), encoding="utf-8")
    print(f"  HTML: {HTML}（{len(PAGES)}ページ）")
    if a.html:
        return 0

    from playwright.sync_api import sync_playwright
    out = OUT_DIR / "AIO提案書_詳細版.pdf"
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(HTML.as_uri())
        pg.wait_for_timeout(500)
        # 1ページに収まらない章は、商談中にめくる位置がずれる。作る側で気づけるようにする
        over = pg.evaluate("""() => [...document.querySelectorAll('.p')].map((e,i)=>
            ({i:i+1, h:e.scrollHeight, t:(e.querySelector('h1')||{}).textContent||''}))
            .filter(x => x.h > 794)""")
        pg.pdf(path=str(out), width="297mm", height="210mm", print_background=True,
               margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        b.close()
    for x in over:
        print(f'  ページ溢れ: {x["i"]}ページ「{x["t"]}」 {x["h"]}px')
    print(f"  PDF: {out}（{out.stat().st_size / 1024 / 1024:.1f}MB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
