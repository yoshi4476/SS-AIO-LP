# -*- coding: utf-8 -*-
"""業種別「AI検索対策チェックリスト」（PDF）を作る。/download/ でメールと引き換えに配る。

    python scripts/checklist_make.py            # 5業種ぶん作る（site/download/checklist-<業種>.pdf）

数字は調査（industry_ai_sources.headline）からだけ取る。チェック項目は、30秒診断（audit.js）で測る項目・
業種別LPの「当社が行うこと」・各業種の広告の決まりから作る。事実として言えないことは書かない。
"""
import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "site" / "download"

# 各項目は（確かめること, 確かめ方, 当てはまらないときの直し方）。受け取った人が自分で手を動かせるように、
# 「〜している」だけでなく、どこを見ればよいか・誰に何を頼めばよいかまで書く（2026-10-04 に詳しくした）
TECH = [
    ("AIのクローラー（GPTBot・ClaudeBot・PerplexityBot など）を robots.txt で拒否していない",
     "ブラウザで「https://自社のドメイン/robots.txt」を開き、これらの名前の下に「Disallow: /」が無いかを見る",
     "制作会社・サーバー管理者に、その行を消すよう頼む（消すだけで、ほかの設定は変わらない）"),
    ("CDN・セキュリティの設定で、AIのクローラーを弾いていない",
     "Cloudflare などを使っている場合、「AIボットをブロック」「ボット対策」の設定を見る。既定で有効になっていることがある",
     "答えに使ってほしいAIのクローラーだけを許可する設定に変える"),
    ("常時SSL（https）になっていて、http で開いても https に移る",
     "アドレスバーに「http://」を付けて開き、自動で「https://」に変わるかを見る",
     "サーバーで SSL 証明書を有効にし、http から https への転送を設定する"),
    ("検索に出さない設定（noindex）が、公開したいページに残っていない",
     "Google Search Console の「ページ」→「インデックスに登録されなかった理由」に「noindex タグによって除外」が無いかを見る",
     "制作時の仮の設定が残っていることが多い。該当ページの noindex を外す"),
    ("サイトマップ（sitemap.xml）を Search Console に送っている",
     "Search Console の「サイトマップ」に、送信済みで「成功」と出ているかを見る",
     "「https://自社のドメイン/sitemap.xml」を登録する（WordPress は多くの場合、自動で作られている）"),
    ("ページごとに、違う題（title）と説明文（description）が付いている",
     "検索で「site:自社のドメイン」と入れ、同じ題・同じ説明文が並んでいないかを見る",
     "ページの中身に合わせて、ページごとに書き分ける（題は30字前後、説明文は80〜120字が目安）"),
    ("見出し（h1）がページに1つあり、そのページの主題を表している",
     "ページを開き、いちばん大きな見出しがそのページの内容を一言で表しているかを見る",
     "ロゴや「ようこそ」ではなく、ページの主題（例: 地域名＋業種＋サービス）を見出しにする"),
    ("会社情報（社名・電話番号・所在地）が、画像ではなく文字で書いてある",
     "電話番号を選んでコピーできるかを試す（画像の中の文字はAIに読まれにくい）",
     "フッターや会社概要に、文字で書いた社名・住所・電話番号を置く"),
    ("構造化データ（会社・パンくず・よくある質問）が正しく入っている",
     "Google の「リッチリザルト テスト」にページのURLを入れ、エラーが無いかを見る",
     "会社（Organization・LocalBusiness）とパンくず（BreadcrumbList）から入れる。FAQ はページにある質問と同じ文にする"),
    ("スマホで表示が遅くない",
     "PageSpeed Insights にトップページのURLを入れ、スマホの「LCP」が2.5秒以内かを見る",
     "大きな画像を縮める・使っていないプラグインを外す・Webフォントを減らす"),
    ("大事なページへ、トップから2回のクリックで行ける",
     "トップから料金・サービス・会社概要・問い合わせまで、何回クリックで届くかを数える",
     "メニューかトップの本文に、大事なページへのリンクを置く"),
]
INDUSTRIES = {
    "dental": {"label": "歯科医院", "research": "dental", "lp": "medical", "word": "歯医者",
               "topics": ["治療ごとの費用の目安と、保険が使えるかどうか", "治療法の選び方（インプラント・入れ歯・ブリッジの違い）",
                          "矯正（マウスピース・ワイヤー）の期間と費用の考え方", "症状ごとの受診の目安（痛み・腫れ・出血など）",
                          "初診の流れ・予約の方法・診療時間・休診日", "子どもの歯科（何歳から・フッ素・シーラント）",
                          "院長・歯科医師の経歴と専門（所属学会・認定医など）", "実際にある設備と、その設備でできること",
                          "通いやすさ（駅からの道・駐車場・バリアフリー）", "治療後の通院とメンテナンスの頻度"],
               "rules": [("医療広告ガイドラインにふれない書き方になっている",
                          "「地域No.1」など他院と比べる表現・効果を保証する表現・患者の体験談（治療の内容や効果についての感想）を載せていないかを見る",
                          "該当する文を消す。自由診療は、費用・期間・主なリスクや副作用を同じページに書く"),
                         ("治療前後の写真を載せる場合、説明を添えている",
                          "写真のそばに、治療内容・費用・期間・リスクの説明があるかを見る",
                          "説明を添えられない写真は外す")]},
    "clinic": {"label": "クリニック", "research": "clinic", "lp": "medical", "word": "クリニック",
               "topics": ["診療科目と、症状ごとの受診の目安", "検査（血液・画像など）の内容と費用", "自費診療の内容と費用・リスク",
                          "予約・待ち時間・オンライン診療の有無", "医師の経歴と専門医の資格", "初診の流れと持ち物（保険証・お薬手帳など）",
                          "健康診断・予防接種の案内（対象・費用・予約方法）", "通いやすさ（駅からの道・駐車場・バリアフリー）",
                          "紹介先・連携している病院", "よくある質問（受診前に聞かれること）"],
               "rules": [("医療広告ガイドラインにふれない書き方になっている",
                          "「最新」「最高」など根拠を示せない最上級の表現・他院との比較・効果の保証・患者の体験談を載せていないかを見る",
                          "該当する文を消す。自費診療は、費用・期間・主なリスクや副作用を同じページに書く"),
                         ("医師の資格は、正式な名称で書いている",
                          "専門医などの資格名が、認定している団体の正式な名称と同じかを見る",
                          "略称や独自の呼び方を、正式な名称に直す")]},
    "fudosan": {"label": "不動産会社", "research": "fudosan", "lp": "fudosan", "word": "不動産会社",
                "topics": ["売却・購入・賃貸それぞれの費用（仲介手数料・諸費用）", "売却の流れと期間（査定から引き渡しまで）",
                           "購入の流れと期間（住宅ローンの事前審査を含む）", "査定の考え方（机上査定と訪問査定の違い）",
                           "対応エリアと、得意な物件・取引", "相続・空き家・住み替えの相談への対応",
                           "賃貸の初期費用と入居までの流れ", "担当者・宅地建物取引士の紹介",
                           "契約で気をつけること（重要事項説明・手付金）", "よくある質問（査定は無料か・しつこい営業はないか など）"],
                "rules": [("掲載物件を最新に保ち、取引できない物件を載せたままにしていない（おとり広告にしない）",
                           "成約済み・取り下げた物件が、自社サイトとポータルに残っていないかを見る",
                           "成約したら、その日のうちに掲載を外す流れを決める"),
                          ("宅建業の免許番号と、取引の形（売主・仲介など）を載せている",
                           "会社概要と物件ページに、免許番号と取引の形が書いてあるかを見る",
                           "会社概要に免許番号を、物件ごとに取引の形を書く。「格安」「最高」など根拠を示せない表現は使わない")]},
    "koumuten": {"label": "工務店・リフォーム会社", "research": "koumuten", "lp": "koumuten", "word": "工務店",
                 "topics": ["費用の考え方（坪単価・総額・諸費用の違い）", "工法と性能（断熱・耐震の等級と、その意味）",
                            "施工事例（地域・費用帯・工期つき）", "家づくり・リフォームの流れと期間", "見積もりの見方と、追加費用が出る場面",
                            "保証とアフターサービス（期間と内容）", "対応エリア", "補助金・減税の使える工事（制度名と時点）",
                            "土地探し・ローンの相談への対応", "よくある質問（工事中の住まい・近所へのあいさつ など）"],
                 "rules": [("施工事例の費用・工期は、実際の数字で書いている",
                            "事例ページに、費用（総額か範囲）・工期・地域が書いてあるかを見る",
                            "実際の数字が出せない事例は、出せる範囲（費用帯など）で書く。作った数字は書かない"),
                           ("建設業の許可番号と、保険・保証の内容を載せている",
                            "会社概要に許可番号が、保証のページに対象と期間が書いてあるかを見る",
                            "会社概要に許可番号を書く。「地域No.1」など根拠を示せない表現は使わない")]},
    "shigyou": {"label": "士業事務所", "research": "shigyou", "lp": "shigyou", "word": "税理士",
                "topics": ["料金の考え方（顧問料・報酬の目安と、何が含まれるか）", "相談テーマごとの解説（相続・設立・労務・許認可など）",
                           "手続きの流れと期間", "相談から依頼までの流れ（初回相談の費用・時間）", "資格者と専門分野",
                           "対応エリアとオンライン対応", "業種ごとの対応実績の分野（数字は事実だけ）", "必要な書類の一覧",
                           "期限のある手続き（申告・届出）のスケジュール", "よくある質問と答え"],
                "rules": [("所属する会の広告に関する規程にそった書き方になっている",
                           "他の事務所との比較・誇大な表現・結果の保証（「必ず通る」など）が無いかを見る",
                           "該当する文を消す。報酬の目安は、何が含まれるかと一緒に書く"),
                          ("資格者の氏名と登録番号を載せている",
                           "事務所概要に、資格者の氏名と登録番号が書いてあるかを見る",
                           "事務所概要に書く")]},
}


import json as _json
# 外部に頼む場合の相場は data/price_ranges.json だけを正とする（当社の料金は書かない・匂わせない）
PRICE = _json.loads((ROOT / "data" / "price_ranges.json").read_text(encoding="utf-8"))
WHO = {"inhouse_tools": "社内にWebの担当者がいて、毎月の見直しの時間が取れる",
       "outsource_partial": "設定やページづくりの一部だけを任せ、運用は社内で続けたい",
       "outsource_full": "調査・ページづくり・掲載情報の整備・毎月の報告まで、まとめて任せたい"}


def page(key):
    import industry_ai_sources as IAS
    c = INDUSTRIES[key]
    hl = IAS.headline(c["research"])
    e = html.escape
    T = hl["T"]
    if hl["verdict"] == "portal":
        first = f'{hl["lp"]}%', f'{T["owner"]}を探す質問で、AIの出典が{T["portal"]}だった割合（{T["owner_site"]}は{hl["lc"]}%）'
    elif hl["verdict"] == "owner":
        first = f'{hl["lc"]}%', f'{T["owner"]}を探す質問で、AIの出典が{T["owner_site"]}だった割合'
    else:
        first = f'{hl["lp"]}%／{hl["lc"]}%', f'{T["owner"]}を探す質問で、出典になった{T["portal"]}と{T["owner_site"]}（ほぼ同じ）'

    def box(items):
        out = []
        for it in items:
            what, how, fix = it if isinstance(it, tuple) else (it, "", "")
            extra = ((f'<span class="how"><b>確かめ方</b> {e(how)}</span>' if how else "")
                     + (f'<span class="fix"><b>直し方</b> {e(fix)}</span>' if fix else ""))
            out.append(f'<li><span class="b"></span><span class="t">{e(what)}{extra}</span></li>')
        return "".join(out)
    w = c["word"]
    seek = [(f"{t}を説明したページがある",
             f"AIに「{w} {t.split('（')[0]}」と聞き、自社のページが出典に出るかを見る",
             "テーマごとに1ページ作り、最初に結論、続けて理由・費用や手順・よくある質問の順に書く") for t in c["topics"]]
    find = [(f"主な{T['portal']}の掲載情報（営業時間・料金・写真・住所）が最新になっている",
             f"自社が載っている{T['portal']}を一覧にし、掲載内容を自社サイトと見比べる",
             "古い情報を直す。月に1回、見直す日を決める"),
            ("Googleビジネスプロフィールの情報（営業時間・カテゴリ・写真）が最新になっている",
             "Googleマップで自社を検索し、営業時間・カテゴリ・写真が今と合っているかを見る",
             "管理画面で直す。休業日や臨時の営業時間も入れる"),
            ("社名・住所・電話番号の書き方が、自社サイトと各サイトで同じになっている",
             "「株式会社」の位置・番地の書き方・電話番号の区切りが、サイトごとに違っていないかを見る",
             "自社サイトの書き方に揃える"),
            (f"{T['portal']}やGoogleの口コミ・質問に、規約の範囲で返信している",
             "直近の口コミに返信が付いているかを見る",
             "お礼と、具体的な対応（改善したこと・問い合わせ先）を返す。個人が分かる情報や、決まりにふれる表現は書かない"),
            (f"「地域名＋{w}」で検索したとき、自社が出ている",
             f"スマホのブラウザで「（自社の地域） {w}」と検索し、地図と検索結果の両方で何番目に出るかを見る",
             "地図に出ないときは Googleビジネスプロフィール、検索結果に出ないときは地域名を含むページを見直す")]
    facts = [("その会社にしか無い事実（実績の数・事例）を、期間と母数をつけて書いている",
              "「多数の実績」のような書き方ではなく、「2025年4月〜2026年3月に◯件」のように書いてあるかを見る",
              "数えられる実績を、期間と一緒に書く。数えられないものは書かない"),
             ("記事やページに、監修者・執筆者の名前と資格を載せている",
              "解説ページの最初か最後に、名前と資格が書いてあるかを見る",
              "書いた人・確かめた人の名前と資格を載せる"),
             ("更新日を載せ、古くなった情報を直している",
              "料金・制度・営業時間のページに更新日があり、半年以上前のままになっていないかを見る",
              "半年に1回、料金・制度のページを見直す日を決める")] + c["rules"]
    measure = [("Google Search Console に登録し、毎月の表示回数とクリック数を見ている",
                "Search Console の「検索パフォーマンス」で、先月と今月を比べる",
                "未登録なら登録する（無料）。数字は月に1回、同じ日に見る"),
               ("AIからの訪問（ChatGPT・Gemini・Perplexity など）を、アクセス解析で分けて見ている",
                "Google アナリティクスの「集客」で、参照元に chatgpt.com・gemini.google.com・perplexity.ai などがあるかを見る",
                "参照元で絞り込んだ表を保存し、毎月見る"),
               ("問い合わせ・予約が、どのページから来たかを分かるようにしている",
                "問い合わせフォームの送信を、アクセス解析で数えているかを見る",
                "送信をイベントとして数え、どのページから来たかを見る")]
    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><title>AI検索対策チェックリスト｜{e(c['label'])}版</title>
<style>
@page{{size:A4;margin:13mm 14mm 13mm}}
body{{font-family:"Hiragino Kaku Gothic ProN","Yu Gothic","Meiryo",sans-serif;color:#10203a;font-size:9.2pt;line-height:1.65;margin:0}}
h1{{font-size:19pt;margin:0;color:#0b2447;letter-spacing:.02em}}
.sub{{color:#5b6b84;font-size:8.6pt;margin:1mm 0 4mm}}
.data{{background:#0b2447;color:#fff;border-radius:3mm;padding:4mm 5mm;display:grid;grid-template-columns:1fr 1fr;gap:5mm;margin-bottom:4mm}}
.data b{{display:block;font-size:20pt;line-height:1.2}}
.data p{{margin:0;font-size:8.4pt;color:rgba(255,255,255,.88)}}
.data .src{{grid-column:1/-1;font-size:7.6pt;color:rgba(255,255,255,.7)}}
.use{{background:#f3f6fb;border-radius:2mm;padding:3mm 4mm;font-size:8.6pt;margin-bottom:2mm}}
h2{{font-size:11.5pt;margin:5mm 0 1.5mm;padding-left:2.5mm;border-left:1.2mm solid #2563eb;color:#0b2447;break-after:avoid}}
.why{{margin:0 0 2mm;color:#5b6b84;font-size:8.6pt}}
ul{{list-style:none;margin:0;padding:0;display:grid;gap:2mm}}
li{{display:flex;gap:2.4mm;align-items:flex-start;break-inside:avoid}}
.b{{flex:none;width:3.6mm;height:3.6mm;border:.35mm solid #2563eb;border-radius:.6mm;margin-top:.9mm}}
.t{{display:block}}
.how,.fix{{display:block;font-size:8pt;color:#4a5a73;line-height:1.55;margin-top:.4mm}}
.how b,.fix b{{color:#2563eb;font-weight:700;margin-right:1mm}}
.fix b{{color:#0b7a4b}}
ol.order{{margin:0;padding-left:5mm;font-size:8.8pt}}
.tag{{float:right;font-size:7.4pt;font-weight:500;color:#5b6b84;background:#eef3fb;border-radius:1mm;padding:.4mm 1.6mm;margin-top:.6mm}}
.page{{break-before:page}}
.pit li{{display:block;padding-left:4mm;text-indent:-4mm;font-size:8.8pt}}
table.mk{{width:100%;border-collapse:collapse;font-size:8.6pt;margin:1mm 0 2mm}}
table.mk th,table.mk td{{border:.25mm solid #d9e2ef;padding:1.6mm 2.2mm;text-align:left;vertical-align:top}}
table.mk thead th{{background:#eef3fb}}
.steps{{display:grid;grid-template-columns:repeat(4,1fr);gap:2.5mm;margin:1mm 0 2mm}}
.steps div{{border:.3mm solid #d9e2ef;border-radius:2mm;padding:2.5mm;font-size:8.2pt;line-height:1.55}}
.steps b{{display:block;color:#2563eb;font-size:8.8pt;margin-bottom:.8mm}}
.ask{{background:#0b2447;color:#fff;border-radius:3mm;padding:4.5mm 5mm;margin-top:4mm}}
.ask h3{{margin:0 0 1.5mm;font-size:12pt}}
.ask p{{margin:.8mm 0;font-size:8.8pt;color:rgba(255,255,255,.92)}}
.ask .big{{font-size:10.5pt;font-weight:700;color:#fff;margin-top:2mm}}
.foot{{margin-top:6mm;border-top:.3mm solid #e3eaf3;padding-top:3mm;font-size:8.4pt;color:#5b6b84}}
.foot b{{color:#0b2447}}
</style></head><body>
<h1>AI検索対策チェックリスト｜{e(c['label'])}版</h1>
<p class="sub">セブンセンシズ株式会社（AI集客ラボ）・{hl['date'][:4]}年{int(hl['date'][5:7])}月版 ／ 当てはまるものに印をつけてください</p>
<div class="data"><div><b>{e(first[0])}</b><p>{e(first[1])}</p></div>
<div><b>{hl['oa']}%</b><p>{e(T['other_short'])}を調べる質問で、回答が{e(T['owner_site'])}を1つ以上出典にしていた割合</p></div>
<p class="src">出典: セブンセンシズ株式会社の調査（{hl['questions']}問を {hl['engines_text']} に質問・{hl['date']}）{hl['url']}</p></div>
<div class="use"><b>使い方</b>　各項目の「確かめ方」で今の状態を見て、当てはまれば□に印をつけます。当てはまらない項目は「直し方」を、
上から順に進めてください。1〜2は数日で直せる設定の項目、3〜4はページづくりの項目です。全部で{len(TECH) + len(find) + len(seek) + len(facts) + len(measure)}項目あります。</div>
<h2>1. AIと検索に読まれる状態か（{len(TECH)}項目）<span class="tag">確かめる: 自分で ／ 直す: 制作会社・サーバーの作業</span></h2><p class="why">ここが欠けると、内容が良くてもAIの答えに使われません。まず最初に確かめてください。</p><ul>{box(TECH)}</ul>
<h2>2.「探される」場面（{e(T['owner'])}を探す人・{len(find)}項目）<span class="tag">自分でできる ／ 続けるのが難しい</span></h2><p class="why">探す質問では、AIは{e(T['portal'])}も出典にします。掲載情報の古さは、そのまま答えに出ます。</p><ul>{box(find)}</ul>
<h2>3.「調べられる」場面（自社の解説ページ・{len(seek)}項目）<span class="tag">文章・構成・決まりの知識が要る</span></h2><p class="why">費用・手続きなどを調べる質問では、AIは{e(T['owner_site'])}を出典にしていました。次のテーマに答えるページがあるかを確かめてください。</p><ul>{box(seek)}</ul>
<h2>4. 事実と書き方（{len(facts)}項目）<span class="tag">業種の決まりの確認が要る</span></h2><p class="why">AIが根拠に選ぶのは、そこにしか無い事実です。業種の決まりにふれる書き方は、AIの答えにも載りません。</p><ul>{box(facts)}</ul>
<h2>5. 効果を測る（{len(measure)}項目）<span class="tag">最初の設定が要る</span></h2><p class="why">直したかどうかではなく、表示・訪問・問い合わせが増えたかで判断します。</p><ul>{box(measure)}</ul>
<h2>6. どこから手を付けるか</h2>
<ol class="order"><li>1の設定の項目（クローラー・noindex・SSL）を先に直す。ここが欠けていると、ほかの項目の効果が出ません。</li>
<li>2の掲載情報と Googleビジネスプロフィールを最新にする。</li>
<li>3のテーマのうち、問い合わせにつながる「費用」「流れ」から1ページずつ作る。</li>
<li>4の決まりにふれる表現を消し、事実を期間と母数つきで足す。</li>
<li>5の数字を月に1回見て、増えたページの書き方を、ほかのページにも広げる。</li></ol>
<div class="page"></div>
<h2>7. よくあるつまずき</h2><p class="why">項目そのものより、続け方でつまずくことが多くあります。</p>
<ul class="pit">
<li>・設定を直しても、AIの答えや検索の順位に表れるまでには数か月単位の時間がかかり、途中で手が止まる。</li>
<li>・解説ページを増やしたが、地域名や業種名だけを入れ替えた同じ形のページになり、かえって評価を下げる。</li>
<li>・{e(c['label'])}の決まりにふれる表現が残ったまま、ページを広げてしまう。</li>
<li>・{e(T['portal'])}や Googleビジネスプロフィールの情報が、気づかないうちに古くなる。</li>
<li>・数字を見ていないので、どのページが問い合わせにつながったのか分からず、次に何をすればよいか決められない。</li>
<li>・担当者が本業と兼ねていて、月に1回の見直しが続かない。</li>
</ul>
<h2>8. 自社で進めるか、任せるか</h2>
<table class="mk"><thead><tr><th>やり方</th><th>向いている場合</th><th>費用の目安（{e(PRICE['label'])}）</th></tr></thead><tbody>
{"".join(f"<tr><th>{e(r['label'])}</th><td>{e(WHO[r['id']])}</td><td>{e(r['range'])}</td></tr>" for r in PRICE['ranges'])}
</tbody></table>
<p class="why">自社で進める場合も、担当者の時間がかかります。1〜2の設定だけを自社で直し、3〜5を任せる分け方もできます。
当社の料金は、無料相談で御社の状況（今の印の数・ページの数・地域）をうかがってからご案内します。</p>
<h2>9. 当社に任せた場合の進め方</h2>
<div class="steps">
<div><b>1. 無料相談</b>このチェックリストの結果をもとに、どこから直すと効果が大きいかを一緒に決めます。</div>
<div><b>2. 調査</b>御社と同じ地域の{e(T['owner'])}が、ChatGPT・Gemini などのAIにどう紹介されているかを調べます。</div>
<div><b>3. 改善</b>設定の修正、{e(c['label'])}の決まりにふれない解説ページづくり、掲載情報の整備を進めます。</div>
<div><b>4. 毎月の報告</b>検索の表示・AIからの訪問・問い合わせの数を毎月お届けし、次の打ち手を決めます。</div>
</div>
<div class="ask"><h3>このチェックリストで、印がつかなかった項目はいくつありましたか</h3>
<p>印がつかなかった項目が5つ以上あれば、AIの答えに選ばれるための土台が欠けています。どれから直すかで、効果が出るまでの時間が変わります。</p>
<p>無料相談では、次の3つをお伝えします。</p>
<p>・印がつかなかった項目のうち、効果が大きい順の3つと、その直し方<br>
・同じ地域の{e(T['owner'])}が、AIにどう紹介されているか<br>
・必要な作業と期間の目安、お見積り（ご依頼いただくかは、そのあとでお決めください）</p>
<p class="big">ご相談: https://ai.7senses.co.jp/lp/{c['lp']}/ ／ TEL 06-4305-7547（平日9:00〜20:00）</p></div>
<div class="foot"><b>確かめる（無料）</b><br>
・AIにどう紹介されているか無料チェック: https://ai.7senses.co.jp/tools/ai-check/<br>
・サイトが読まれているかの30秒診断: https://ai.7senses.co.jp/lp/{c['lp']}/<br>
<b>相談する</b>: {e(T['lp_name'])} https://ai.7senses.co.jp/lp/{c['lp']}/ ／ TEL 06-4305-7547（平日9:00〜20:00）<br>
セブンセンシズ株式会社 〒537-0003 大阪府大阪市東成区神路1丁目7-4 コンフォートビル901・902</div>
</body></html>"""


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        for key in INDUSTRIES:
            pg.set_content(page(key), wait_until="load")
            out = OUT / f"checklist-{key}.pdf"
            pg.pdf(path=str(out), format="A4", print_background=True)
            print(f"  {out.name}（{out.stat().st_size // 1024}KB）")
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
