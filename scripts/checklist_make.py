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
# TECH と同じ並び。（なぜ大事か, (優先度, 担当, 時間の目安)）。受け取った人が「やらないと何が起きるか」と
# 「自分でやれるか」を項目ごとに判断できるようにする。根拠を示せない数字は書かない
TECH_WHY = [
    ("拒否されていると、AIはページを読めず、答えの出典に選べません。内容をどれだけ良くしても効きません。", ("最優先", "自分で確認・制作会社", "5分")),
    ("管理画面に出ない所で弾かれていることがあり、気づかないまま「引用されない状態」が続きます。", ("最優先", "制作会社", "10分")),
    ("https でないページは、ブラウザに「保護されていない」と出て、問い合わせの前に離れられます。", ("高", "制作会社", "10分")),
    ("残っていると、そのページは検索にもAIの答えにも出ません。サイトを作り直した後に残りやすい設定です。", ("最優先", "自分で確認", "10分")),
    ("新しいページや直したページを、検索エンジンに早く見つけてもらえます。", ("高", "自分で", "15分")),
    ("検索結果とAIが、そのページが何の話かを最初に判断する所です。同じ題が並ぶと、どれを見せるか決められません。", ("高", "自分で・制作会社", "30分〜")),
    ("見出しが主題を言っていないと、AIがページの要点を取り違えます。", ("中", "制作会社", "30分")),
    ("画像の中の電話番号は、AIにも検索エンジンにも読まれにくく、問い合わせ先として紹介されません。", ("高", "制作会社", "15分")),
    ("必須ではありませんが、会社名・住所・質問と答えを、機械が取り違えにくくなります。", ("中", "制作会社", "半日")),
    ("表示が遅いと、スマホで探している人が読む前に離れます。", ("中", "制作会社", "半日〜")),
    ("奥にあるページは、検索エンジンにもAIにも「大事なページ」だと伝わりにくくなります。", ("中", "制作会社", "30分")),
]
# 業種の決まりの2項目（rules）に共通の理由
RULE_WHY = [("決まりにふれる表現は、指導の対象になるうえ、AIの答えにも載りにくくなります。", ("最優先", "自分で確認", "1時間")),
            ("登録・許可の番号は、比べている人が信頼できる相手かを確かめる材料です。", ("高", "自分で", "15分"))]
GLOSSARY = [
    ("robots.txt", "サイトの入口に置く、「どのロボットに読ませるか」を決めるファイル。"),
    ("クローラー", "ページを読みに来るロボット。GPTBot（ChatGPT）・ClaudeBot・Googlebot など。"),
    ("noindex", "「このページを検索に出さない」という設定。公開したいページに付いていると、検索にもAIにも出ません。"),
    ("サイトマップ", "サイトにあるページの一覧のファイル。検索エンジンに新しいページを知らせます。"),
    ("title・description", "検索結果に出る題と説明文。ページごとに中身に合わせて書きます。"),
    ("構造化データ", "会社名・住所・よくある質問などを、機械が読みやすい形で書いたもの。"),
    ("LCP", "ページのいちばん大きな部分が表示されるまでの時間。2.5秒以内が目安（Google の基準）。"),
    ("Search Console", "Google の無料の道具。どの言葉で何回表示され、何回クリックされたかが分かります。"),
    ("Googleビジネスプロフィール", "Googleマップに出る会社・店の情報。営業時間・写真・口コミを管理します。"),
    ("出典", "AIが答えの根拠として示すページ。ここに自社のページが入ることが、AI検索対策の目標です。"),
]
QUICK = [("robots.txt を開いて見る", "「https://自社のドメイン/robots.txt」をブラウザで開き、「Disallow: /」の行が無いかを見る（1-1）"),
         ("Googleビジネスプロフィールを直す", "Googleマップで自社を検索し、営業時間・写真が今と合っているかを見る（2-2）"),
         ("Search Console に登録する", "無料。登録した日から数字が溜まるので、早いほど比べられる期間が長くなります（5-1）")]
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
    """章ごとに頁を分けた、読みやすい版（表紙・目次・グラフ・章の帯・自己採点の表・進める順番の図・提案）。
    数字は当社の調査（industry_ai_sources.headline）だけ。金額は載せない（問い合わせた方にだけ伝える）"""
    import industry_ai_sources as IAS
    c = INDUSTRIES[key]
    hl = IAS.headline(c["research"])
    e = html.escape
    T = hl["T"]
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
    def attach(rows, whys):
        return [r + w for r, w in zip(rows, whys)] + list(rows[len(whys):])
    find = attach(find, [
        (f"探す質問でAIが出典にするのは{T['portal']}が多く、古い情報がそのまま答えに使われます。", ("最優先", "自分で", "30分")),
        ("地図検索とAIの両方が参照します。営業時間の誤りは、来店・来院の取りこぼしに直結します。", ("最優先", "自分で", "15分")),
        ("書き方がサイトごとに違うと、同じ会社だと判断されにくくなります。", ("高", "自分で", "30分")),
        ("返信は、探している人が比べるときの判断材料になります。", ("中", "自分で", "毎週10分")),
        ("今の位置を知らないと、直した後に効果があったかを比べられません。", ("高", "自分で", "5分"))])
    seek = [r + ("このテーマの質問に答えるページが無いと、AIは他のサイトを出典にします。" if i == 0 else "",
                 ("高" if i < 2 else "中", "自社で書く・制作会社", "1ページ半日"))
            for i, r in enumerate(seek)]
    facts = attach(facts, [
        ("「多数の実績」は確かめようがありません。AIは数字と期間のある事実を根拠に選びます。", ("高", "自分で", "1時間")),
        ("誰が書いたか分からないページは、医療・法律・お金の分野で特に信頼されにくくなります。", ("高", "自分で", "30分")),
        ("古い料金・制度のまま答えに使われると、問い合わせ後の食い違いにつながります。", ("中", "自分で", "半年に1回"))] + RULE_WHY)
    measure = attach(measure, [
        ("数字が無いと、どの直しが効いたかが分からず、次の手を決められません。", ("高", "自分で", "15分")),
        ("分けて見ないと、AIからの訪問の変化に気づけません。", ("中", "自分で", "15分")),
        ("どのページが問い合わせを生んだかが分かると、増やすべきページが決まります。", ("高", "制作会社", "1時間"))])
    ex = {
        1: ("ページの題（title）", f"ホーム｜{c['label']}名", f"（地域名）の{c['label']}｜（主なサービス）の費用と流れ｜（社名）"),
        2: ("社名・住所の書き方", "サイトAでは「㈱〇〇」、ポータルでは「株式会社〇〇 本店」", "すべてのサイトで、自社サイトと同じ「株式会社〇〇」に揃える"),
        3: ("解説ページの組み立て", "あいさつ → 会社の紹介 → 最後に少しだけ本題", "最初に結論 → 理由 → 費用・手順 → よくある質問 → 相談の案内"),
        4: ("実績の書き方", "多数の実績があります", "2025年4月〜2026年3月に（数）件をお手伝いしました（数えられる事実だけ）"),
    }
    chapters = [
        ("AIと検索に読まれる状態か", "ここが欠けると、内容が良くてもAIの答えに使われません。最初に確かめてください。",
         "確かめる: 自分で ／ 直す: 制作会社・サーバー", [r + w for r, w in zip(TECH, TECH_WHY)]),
        (f"「探される」場面（{T['owner']}を探す人）", f"探す質問では、AIは{T['portal']}も出典にします。掲載情報の古さは、そのまま答えに出ます。",
         "自分でできる ／ 続けるのが難しい", find),
        ("「調べられる」場面（自社の解説ページ）", f"費用・手続きなどを調べる質問では、AIは{T['owner_site']}を出典にしていました。",
         "文章・構成・決まりの知識が要る", seek),
        ("事実と書き方", "AIが根拠に選ぶのは、そこにしか無い事実です。業種の決まりにふれる書き方は、AIの答えにも載りません。",
         "業種の決まりの確認が要る", facts),
        ("効果を測る", "直したかどうかではなく、表示・訪問・問い合わせが増えたかで判断します。", "最初の設定が要る", measure),
    ]
    total = sum(len(ch[3]) for ch in chapters)

    PRI = {"最優先": "p1", "高": "p2", "中": "p3"}

    def items(n, rows):
        out = []
        for i, r in enumerate(rows, 1):
            what, how, fix = r[:3]
            why = r[3] if len(r) > 3 else ""
            pri, who, mins = r[4] if len(r) > 4 else ("", "", "")
            tags = (f'<span class="tg {PRI.get(pri, "p3")}">{e(pri)}</span><span class="tg tw2">{e(who)}</span>'
                    f'<span class="tg tt">目安 {e(mins)}</span>') if pri else ""
            out.append(f'<tr><td class="cb"><span class="b"></span></td><td class="no">{n}-{i}</td>'
                       f'<td><p class="w">{e(what)}</p><p class="tags">{tags}</p>'
                       + (f'<p class="why"><b>なぜ大事か</b>{e(why)}</p>' if why else "")
                       + f'<div class="hf"><p><b class="h">確かめ方</b>{e(how)}</p>'
                       f'<p><b class="f">直し方</b>{e(fix)}</p></div></td></tr>')
        return "".join(out)

    def example(n):
        if n not in ex:
            return ""
        k, ng, ok = ex[n]
        return (f'<div class="ex"><p class="exh">見本: {e(k)}</p><div class="exg"><p class="ng"><b>NG</b>{e(ng)}</p>'
                f'<p class="ok"><b>OK</b>{e(ok)}</p></div></div>')

    def bar(label, pct, color):
        return (f'<div class="bar"><span class="bl">{e(label)}</span><span class="bt"><span class="bf" style="width:{pct}%;background:{color}"></span></span>'
                f'<span class="bv">{pct}%</span></div>')

    lp, lc, oa = float(hl["lp"]), float(hl["lc"]), float(hl["oa"])
    chart = (f'<div class="chart"><p class="ct">{e(T["owner"])}を探す質問で、AIが出典にしたサイト</p>'
             + bar(T["portal"], lp, "#94a3b8") + bar(T["owner_site"], lc, "#2563eb")
             + f'<p class="ct" style="margin-top:3mm">{e(T["other_short"])}を調べる質問で、{e(T["owner_site"])}を出典にした回答</p>'
             + bar("1つ以上を出典にした回答", oa, "#0b7a4b")
             + f'<p class="src">出典: セブンセンシズ株式会社の調査（{hl["questions"]}問を {e(hl["engines_text"])} に質問・{hl["date"]}）{hl["url"]}</p></div>')
    toc = '<tr><td class="tn">0</td><td>はじめに（今日すぐできる3つ・印の見方・用語ミニ辞典）</td><td class="tc">—</td><td class="tw">3分</td></tr>'
    toc += "".join(f'<tr><td class="tn">{i}</td><td>{e(ch[0])}</td><td class="tc">{len(ch[3])}項目</td><td class="tw">{e(ch[2])}</td></tr>'
                  for i, ch in enumerate(chapters, 1))
    toc += ('<tr><td class="tn">6</td><td>自己採点と、どこから手を付けるか</td><td class="tc">—</td><td class="tw">5分</td></tr>'
            '<tr><td class="tn">7</td><td>よくあるつまずき・自社で進めるか任せるか</td><td class="tc">—</td><td class="tw"></td></tr>')
    # 章ごとに頁を改めると、短い章の頁の下半分が空く。1章だけ新しい頁から始め、あとは続けて流す
    body_ch = "".join(
        f'<section class="ch{" first" if i == 1 else ""}"><div class="band"><span class="num">{i}</span><div><h2>{e(ch[0])}</h2>'
        f'<p>{e(ch[1])}</p></div><span class="meta">{len(ch[3])}項目<br>{e(ch[2])}</span></div>'
        f'{example(i)}<table class="it">{items(i, ch[3])}</table></section>'
        for i, ch in enumerate(chapters, 1))
    score = "".join(f'<tr><td>{i}. {e(ch[0])}</td><td class="tc">{len(ch[3])}</td><td class="fill"></td>'
                    f'<td class="tc">{(len(ch[3]) + 1) // 2}未満なら優先</td></tr>' for i, ch in enumerate(chapters, 1))
    hi, mid = round(total * 0.8), round(total * 0.5)
    verdict = (f'<table class="verdict"><tr><th>印の合計</th><th>今の段階</th><th>次にやること</th></tr>'
               f'<tr><td class="tc">{hi}以上</td><td><b class="v1">土台は整っている</b></td><td>解説ページを増やし、毎月の数字で効いたページを伸ばす</td></tr>'
               f'<tr><td class="tc">{mid}〜{hi - 1}</td><td><b class="v2">一部が欠けている</b></td><td>印の少ない章から。特に1章の欠けを先に埋める</td></tr>'
               f'<tr><td class="tc">{mid - 1}以下</td><td><b class="v3">土台から整える段階</b></td><td>1章の設定と2章の掲載情報を先に。解説ページはその後</td></tr></table>')
    quick = "".join(f'<div><b>{e(a)}</b>{e(b)}</div>' for a, b in QUICK)
    gloss = "".join(f'<tr><th>{e(a)}</th><td>{e(b)}</td></tr>' for a, b in GLOSSARY)
    intro = (f'<section class="intro"><div class="band"><span class="num">0</span><div><h2>はじめに</h2>'
             f'<p>今日すぐできる3つと、印の見方・言葉の意味をまとめました。</p></div><span class="meta">所要 3分</span></div>'
             f'<h3 class="sec">今日すぐできる3つ（どれも無料・30分以内）</h3><div class="quick">{quick}</div>'
             '<h3 class="sec">項目の印の見方</h3><div class="legend">'
             '<p><span class="tg p1">最優先</span>欠けていると、ほかの直しの効果が出ない項目</p>'
             '<p><span class="tg p2">高</span>問い合わせ・信頼に直接かかわる項目</p>'
             '<p><span class="tg p3">中</span>土台が整った後に進める項目</p>'
             '<p><span class="tg tw2">自分で ／ 制作会社</span>誰が手を動かすか</p>'
             '<p><span class="tg tt">目安</span>作業にかかる時間の目安</p></div>'
             f'<h3 class="sec">用語ミニ辞典</h3><table class="gloss">{gloss}</table></section>')
    pits = ["設定を直しても、AIの答えや検索の順位に表れるまでには数か月単位の時間がかかり、途中で手が止まる",
            "解説ページを増やしたが、地域名や業種名だけを入れ替えた同じ形のページになり、かえって評価を下げる",
            f"{c['label']}の決まりにふれる表現が残ったまま、ページを広げてしまう",
            f"{T['portal']}や Googleビジネスプロフィールの情報が、気づかないうちに古くなる",
            "数字を見ていないので、どのページが問い合わせにつながったのか分からず、次の手を決められない",
            "担当者が本業と兼ねていて、月に1回の見直しが続かない"]
    who = "".join(f"<tr><th>{e(r['label'])}</th><td>{e(WHO[r['id']])}</td></tr>" for r in PRICE["ranges"])
    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><title>AI検索対策チェックリスト｜{e(c['label'])}版</title>
<style>
@page{{size:A4;margin:12mm 13mm 13mm}}
*{{box-sizing:border-box}}
body{{font-family:"Hiragino Kaku Gothic ProN","Yu Gothic","Meiryo",sans-serif;color:#122036;font-size:9.6pt;line-height:1.7;margin:0}}
p{{margin:0}}
.cover h1{{font-size:24pt;line-height:1.3;margin:0;color:#0b2447;letter-spacing:.01em}}
.cover .kick{{display:inline-block;background:#2563eb;color:#fff;font-size:8.4pt;font-weight:700;border-radius:1mm;padding:.6mm 2.4mm;margin-bottom:3mm}}
.cover .sub{{color:#5b6b84;font-size:8.6pt;margin:2mm 0 5mm}}
.learn{{display:grid;grid-template-columns:repeat(3,1fr);gap:3mm;margin-bottom:5mm}}
.learn div{{border-top:1mm solid #2563eb;background:#f4f7fc;padding:3mm;font-size:8.6pt;line-height:1.55}}
.learn b{{display:block;color:#0b2447;font-size:9.4pt;margin-bottom:1mm}}
.chart{{background:#0b2447;color:#fff;border-radius:3mm;padding:4.5mm 5mm;margin-bottom:5mm}}
.ct{{font-size:8.8pt;font-weight:700;margin-bottom:1.5mm}}
.bar{{display:grid;grid-template-columns:42mm 1fr 14mm;align-items:center;gap:2mm;margin:1.2mm 0;font-size:8.2pt}}
.bt{{height:4.2mm;background:rgba(255,255,255,.14);border-radius:1mm;overflow:hidden;display:block}}
.bf{{display:block;height:100%}}
.bv{{text-align:right;font-weight:700;font-size:9.4pt}}
.src{{font-size:7.2pt;color:rgba(255,255,255,.7);margin-top:2.5mm}}
h3.sec{{font-size:11pt;color:#0b2447;margin:0 0 2mm;padding-bottom:1mm;border-bottom:.3mm solid #d9e2ef}}
table{{width:100%;border-collapse:collapse}}
.toc td{{border-bottom:.25mm solid #e3eaf3;padding:1.8mm 1.5mm;font-size:9pt}}
.toc .tn{{width:8mm;color:#2563eb;font-weight:800;font-size:11pt}}
.tc{{width:20mm;text-align:center;white-space:nowrap}}
.tw{{width:62mm;color:#5b6b84;font-size:8pt}}
.use{{background:#f4f7fc;border-radius:2mm;padding:3mm 4mm;font-size:8.6pt;margin-top:4mm}}
.ch{{margin-top:7mm}} .ch.first,.intro,.last{{break-before:page;margin-top:0}}
.band{{break-after:avoid}} .ex{{break-inside:avoid;break-after:avoid}}
.band{{display:grid;grid-template-columns:13mm 1fr 44mm;gap:3mm;align-items:center;background:#0b2447;color:#fff;border-radius:3mm;padding:3.5mm 4mm;margin-bottom:3mm}}
.band .num{{font-size:22pt;font-weight:800;color:#93c5fd;text-align:center}}
.band h2{{font-size:13pt;margin:0 0 .8mm}}
.band p{{font-size:8.4pt;color:rgba(255,255,255,.88)}}
.band .meta{{font-size:7.8pt;color:#cfe0ff;text-align:right;line-height:1.5}}
.it td{{border-bottom:.25mm solid #e3eaf3;padding:2.2mm 1.2mm;vertical-align:top}}
.it tr{{break-inside:avoid}}
.cb{{width:6mm}}
.b{{display:block;width:3.8mm;height:3.8mm;border:.4mm solid #2563eb;border-radius:.7mm;margin-top:.6mm}}
.no{{width:9mm;color:#2563eb;font-weight:800;font-size:8.4pt;padding-top:2.6mm!important}}
.w{{font-weight:700;color:#0b2447;font-size:10pt;margin-bottom:.8mm}}
.tags{{margin:0 0 1.2mm}}
.tg{{display:inline-block;font-size:7.4pt;font-weight:700;border-radius:4mm;padding:.2mm 2.2mm;margin-right:1.2mm;line-height:1.6}}
.p1{{background:#fde2e1;color:#a4161a}} .p2{{background:#fff1d6;color:#8a4b00}} .p3{{background:#e8edf5;color:#3d4b63}}
.tw2{{background:#e6f0ff;color:#1d4ed8}} .tt{{background:#eef7f1;color:#0b6b41}}
.why{{font-size:8.8pt;color:#1f2d45;margin:0 0 1.4mm;line-height:1.6}}
.why b{{color:#a4161a;margin-right:1.5mm;font-size:8pt}}
.hf{{display:grid;grid-template-columns:1fr 1fr;gap:3mm}}
.hf p{{font-size:8.5pt;color:#24324a;line-height:1.6;background:#f3f6fb;border-radius:1.2mm;padding:1.8mm 2.2mm}}
.hf b{{display:block;font-size:7.8pt;margin-bottom:.4mm}}
.h{{color:#2563eb}} .f{{color:#0b7a4b}}
.score td,.score th{{border:.25mm solid #d9e2ef;padding:2.2mm;font-size:8.8pt}}
.score th{{background:#eef3fb;text-align:left}}
.fill{{width:24mm;background:#fffdf3}}
.flow{{display:grid;grid-template-columns:repeat(5,1fr);gap:0;margin:2mm 0 5mm}}
.flow div{{position:relative;background:#eef3fb;padding:3mm 2.5mm 3mm 4mm;font-size:8pt;line-height:1.5;clip-path:polygon(0 0,92% 0,100% 50%,92% 100%,0 100%,8% 50%)}}
.flow div:first-child{{clip-path:polygon(0 0,92% 0,100% 50%,92% 100%,0 100%)}}
.flow b{{display:block;color:#2563eb;font-size:8.6pt}}
.pit{{display:grid;grid-template-columns:1fr 1fr;gap:2mm;margin-bottom:4mm}}
.pit div{{border-left:1mm solid #f59e0b;background:#fffbeb;padding:2mm 2.5mm;font-size:8.3pt;line-height:1.55}}
.who th,.who td{{border:.25mm solid #d9e2ef;padding:2mm;font-size:8.6pt;text-align:left;vertical-align:top}}
.who th{{width:42mm;background:#eef3fb}}
.note{{font-size:8.4pt;color:#3d4b63;margin:2mm 0 4mm}}
.steps{{display:grid;grid-template-columns:repeat(4,1fr);gap:2.5mm;margin:2mm 0 4mm}}
.steps div{{border:.3mm solid #d9e2ef;border-radius:2mm;padding:2.5mm;font-size:8.2pt;line-height:1.55}}
.steps b{{display:block;color:#2563eb;font-size:9pt;margin-bottom:.8mm}}
.ask{{background:#0b2447;color:#fff;border-radius:3mm;padding:5mm}}
.ask h3{{margin:0 0 2mm;font-size:12.5pt}}
.ask p{{margin:1mm 0;font-size:8.8pt;color:rgba(255,255,255,.92)}}
.ask ul{{margin:1.5mm 0;padding-left:5mm;font-size:8.8pt}}
.ask .big{{font-size:10.5pt;font-weight:700;color:#fff;margin-top:2.5mm}}
.foot{{margin-top:5mm;border-top:.3mm solid #e3eaf3;padding-top:3mm;font-size:8pt;color:#5b6b84}}
.foot b{{color:#0b2447}}
.ex{{border:.3mm solid #d9e2ef;border-radius:2mm;padding:2.5mm 3mm;margin:0 0 3mm}}
.exh{{font-weight:700;color:#0b2447;font-size:9pt;margin-bottom:1.5mm}}
.exg{{display:grid;grid-template-columns:1fr 1fr;gap:2.5mm}}
.exg p{{font-size:8.6pt;border-radius:1.2mm;padding:1.8mm 2.2mm;line-height:1.55}}
.exg b{{display:inline-block;color:#fff;font-size:7.6pt;border-radius:.8mm;padding:0 1.6mm;margin-right:1.6mm}}
.ng{{background:#fdf0ef}} .ng b{{background:#c2410c}} .ok{{background:#edf7f0}} .ok b{{background:#0b7a4b}}
.quick{{display:grid;grid-template-columns:repeat(3,1fr);gap:3mm;margin:0 0 5mm}}
.quick div{{border-top:1mm solid #0b7a4b;background:#f2f9f4;padding:3mm;font-size:8.8pt;line-height:1.6}}
.quick b{{display:block;color:#0b2447;font-size:9.8pt;margin-bottom:1mm}}
.legend{{display:grid;grid-template-columns:1fr 1fr;gap:1.5mm 5mm;margin:0 0 5mm;font-size:8.8pt}}
.legend .tg{{margin-right:2mm}}
.gloss th,.gloss td{{border-bottom:.25mm solid #e3eaf3;padding:1.8mm 2mm;font-size:8.8pt;text-align:left;vertical-align:top}}
.gloss th{{width:44mm;color:#0b2447;white-space:nowrap}}
.verdict{{margin:4mm 0 2mm}} .verdict th,.verdict td{{border:.25mm solid #d9e2ef;padding:2mm;font-size:8.8pt;text-align:left}}
.verdict th{{background:#eef3fb}}
.v1{{color:#0b7a4b}} .v2{{color:#8a4b00}} .v3{{color:#a4161a}}
</style></head><body>
<section class="cover">
<span class="kick">{e(c['label'])}版 ／ {hl['date'][:4]}年{int(hl['date'][5:7])}月版</span>
<h1>AI検索対策チェックリスト<br>AIの答えに選ばれる{e(T['owner_site'])}にするための{total}項目</h1>
<p class="sub">セブンセンシズ株式会社（AI集客ラボ）。当てはまるものに印をつけてください。各項目に「確かめ方」と「直し方」を付けています。</p>
<div class="learn"><div><b>今の状態が分かる</b>{total}項目に印をつけるだけで、AIと検索に読まれる土台がどこまで整っているかが分かります。</div>
<div><b>何から直すか分かる</b>章ごとの印の数から、先に手を付ける章が決まります（6章の自己採点の表）。</div>
<div><b>自社でやるか決められる</b>自社でできる項目と、専門の作業が要る項目を分けて示しています。</div></div>
{chart}
<h3 class="sec">目次</h3><table class="toc">{toc}</table>
<div class="use"><b>使い方</b>　1章から順に「確かめ方」で今の状態を見て、当てはまれば□に印をつけます。
当てはまらない項目は「直し方」を参考に進めてください。印の数は6章の表に書き込みます。</div>
</section>
{intro}
{body_ch}
<section class="ch last"><div class="band"><span class="num">6</span><div><h2>自己採点と、どこから手を付けるか</h2>
<p>章ごとの印の数を書き込み、少ない章から手を付けます。</p></div><span class="meta">所要 5分</span></div>
<table class="score"><thead><tr><th>章</th><th class="tc">項目数</th><th class="tc">印の数</th><th class="tc">目安</th></tr></thead><tbody>{score}
<tr><th>合計</th><th class="tc">{total}</th><td class="fill"></td><td></td></tr></tbody></table>
<h3 class="sec" style="margin-top:5mm">合計から分かる今の段階</h3>{verdict}
<h3 class="sec" style="margin-top:5mm">進める順番</h3>
<div class="flow"><div><b>1. 設定</b>クローラー・noindex・SSL</div><div><b>2. 掲載情報</b>ポータル・地図を最新に</div>
<div><b>3. 解説ページ</b>「費用」「流れ」から</div><div><b>4. 事実と決まり</b>期間と母数をつける</div><div><b>5. 測る</b>月に1回、同じ日に</div></div>
<p class="note">1の設定が欠けていると、2〜5の効果が出ません。3の解説ページは、問い合わせにつながる「費用」「流れ」のテーマから1ページずつ作ります。</p>
<h3 class="sec">よくあるつまずき</h3>
<div class="pit">{"".join(f"<div>{e(x)}</div>" for x in pits)}</div>
</section>
<section class="ch last"><div class="band"><span class="num">7</span><div><h2>自社で進めるか、任せるか</h2>
<p>1〜2の設定だけを自社で直し、3〜5を任せる分け方もできます。</p></div><span class="meta">判断の材料</span></div>
<table class="who">{who}</table>
<p class="note">自社で進める場合も、担当者の時間がかかります。費用の目安と当社の料金は、お問い合わせいただいた方に、御社の状況（今の印の数・ページの数・地域）をうかがってからお伝えします。</p>
<h3 class="sec">当社に任せた場合の進め方</h3>
<div class="steps">
<div><b>1. 無料相談</b>このチェックリストの結果をもとに、どこから直すと効果が大きいかを一緒に決めます。</div>
<div><b>2. 調査</b>同じ地域の{e(T['owner'])}が、ChatGPT・Gemini などのAIにどう紹介されているかを調べます。</div>
<div><b>3. 改善</b>設定の修正、{e(c['label'])}の決まりにふれない解説ページづくり、掲載情報の整備を進めます。</div>
<div><b>4. 毎月の報告</b>検索の表示・AIからの訪問・問い合わせの数を毎月お届けし、次の打ち手を決めます。</div></div>
<div class="ask"><h3>印がつかなかった項目は、いくつありましたか</h3>
<p>印がつかなかった項目が5つ以上あれば、AIの答えに選ばれるための土台が欠けています。どれから直すかで、効果が出るまでの時間が変わります。</p>
<p>無料相談では、次の3つをお伝えします。</p>
<ul><li>印がつかなかった項目のうち、効果が大きい順の3つと、その直し方</li>
<li>同じ地域の{e(T['owner'])}が、AIにどう紹介されているか</li>
<li>必要な作業と期間の目安、費用とお見積り（ご依頼いただくかは、そのあとでお決めください）</li></ul>
<p class="big">ご相談: https://ai.7senses.co.jp/lp/{c['lp']}/ ／ TEL 06-4305-7547（平日9:00〜20:00）</p></div>
<div class="foot"><b>確かめる（無料）</b>　AIにどう紹介されているか: https://ai.7senses.co.jp/tools/ai-check/ ／ サイトの30秒診断: https://ai.7senses.co.jp/lp/{c['lp']}/<br>
セブンセンシズ株式会社 〒537-0003 大阪府大阪市東成区神路1丁目7-4 コンフォートビル901・902</div>
</section>
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
