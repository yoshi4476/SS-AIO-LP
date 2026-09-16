---
title: AI検索対応とは？公開前に済ませる7つの設定項目
description: AI検索対応とは、robots.txtでAIクローラーを許可し、llms.txtと構造化データでサイトをAIが読み取れる状態に整えることです。公開前に済ませる7つの設定項目を解説します。
slug: ai-kensaku-taiou-settei
keyword: ai検索対応
category: aio
date: 2026-09-16
modified: 2026-09-16
eyecatch: /images/ai-kensaku-taiou-settei/eyecatch.png
depth: standard
score: 93
score_breakdown: {design: 19, seo: 19, editorial: 18, expert: 19, persona: 18, aio: 19}
diagrams:
  - name: point5
    type: list
    title: AI検索対応で整える5つの設定
    items: ["robots.txtでAIクローラーを個別に許可する", "llms.txtでサイト概要と実績を渡す", "構造化データで記事を機械可読にする", "冒頭断言とH2結論で本文を抽出しやすくする", "HTTPS・表示速度・sitemapを整える"]
  - name: ngok
    type: vs
    title: 未設定サイトと設定済みサイトの違い
    items: ["未設定サイト|AIクローラーをまとめてブロックしている|llms.txtが存在しない|FAQPageと本文が一致していない", "設定済みサイト|主要AIクローラーを個別に許可している|llms.txtでサイト概要を渡している|FAQPageと本文が完全一致している"]
  - name: junban
    type: flow
    title: 設定に着手する4ステップ
    items: ["今日: robots.txtを確認", "1週目: llms.txtを設置", "2週目: 構造化データを実装", "月1回: GSCで反映を確認"]
faq:
  - q: AI検索対応とは具体的に何をすることですか？
    a: robots.txtでAIクローラーを許可し、llms.txtと構造化データでサイト情報を機械可読にすることです。
  - q: robots.txtで最低限確認すべきクローラーは何ですか？
    a: Googlebot・GPTBot・OAI-SearchBot・ClaudeBot・PerplexityBotの5つです。
  - q: llms.txtは必ず設置しないといけませんか？
    a: 必須ではありませんが、AIにサイト概要を直接伝えられるため設置が推奨されます。
  - q: 構造化データはどのSchemaを優先すべきですか？
    a: 記事にはBlogPostingとFAQPage、パンくずにはBreadcrumbListを優先します。
  - q: 設定してもすぐにAI検索に反映されますか？
    a: 反映まで数週間かかることが多く、即日での変化は期待しないほうが安全です。
  - q: 対応済みかどうかはどこで確認できますか？
    a: GSCの生成AIパフォーマンスレポートとアクセスログのクローラー種別で確認します。
---

**AI検索対応とは、robots.txtでAIクローラーの巡回を許可したうえで、llms.txtと構造化データでサイトの情報をAIが読み取れる形に整えることです。**この3点が揃って初めて、検索順位が良くても引用の候補にすら入らないという事故を防げます。

<div class="target-reader">この記事は、自社サイトをChatGPT検索・Perplexity・Google AI Overviewなどの生成AI検索に対応させたい店舗・中小企業の集客担当者・経営者向けです。</div>

<p class="freshness">※ 2026年9月時点の情報です。</p>

## AI検索対応とは？サイトに必要な状態を定義する

**AI検索対応とは、AIクローラーへの許可と、AIが読み取れる構造の両方が揃った状態を指します。**

「順位は悪くないのに、AI検索にはまったく出てこない」という相談を受けることがあります。多くの場合、原因は本文の質ではなく、クローラーの許可漏れか、機械が読み取れる構造の不足のどちらかです。基礎知識は、[AI検索とは？AIO対策との違いと5種類の対応ポイント](/aio/aio-taisaku-ai-kensaku/)で解説しています。

<div class="definition-box"><span class="term">AI検索対応</span>とは、ChatGPT検索・Perplexity・Google AI OverviewなどのAIクローラーにサイトへのアクセスを許可し、記事の内容を構造化データ・llms.txt・本文構造を通じて機械が読み取れる形で提供することを指します。</div>

対応の範囲は大きく2つに分かれます。1つはクローラーへの「許可」、もう1つはAIが内容を理解しやすくする「構造」です。順番を間違えて構造だけ整えても、そもそもクローラーが来ていなければ意味がありません。まず許可を確認し、そのあとで構造を整える順序が重要です。

## 設定1: robots.txtで主要AIクローラーを個別に許可する

**robots.txtは、AIクローラーを1つずつ確認し、Googlebotを誤って止めないことが最優先です。**

robots.txtに書く内容自体はシンプルですが、事故が起きやすい設定です。**GPTBot・OAI-SearchBot・ClaudeBot・PerplexityBot**を個別にAllow設定し、まとめてブロックしないようにしてください。

静的サイトはルート直下にファイルを置くだけで済みます。WordPressなどCMS側でrobots.txtを動的生成している場合は、プラグインの設定画面から個別許可を確認する必要があります。

<div class="caution-box"><span class="box-title">注意: Googlebotは絶対にブロックしない</span><br>Google AI OverviewとAIモードは通常のGooglebotのクロール結果を使います。「AI系はまとめて止めておこう」という設定が、Googlebot自体を止める事故につながります。</div>

| クローラー | 対象 | 許可すべき理由 |
|:--|:--|:--|
| Googlebot | Google検索全般・AI Overview | 止めると通常検索にも表示されなくなる |
| GPTBot / OAI-SearchBot | ChatGPT検索 | ChatGPTの回答候補に入る前提になる |
| PerplexityBot | Perplexity | 即時性を重視するPerplexityの情報源になる |
| ClaudeBot | Claude | Claudeが参照する情報源になる |

<a href="https://developers.google.com/search/docs/crawling-indexing/overview-google-crawlers" target="_blank" rel="noopener">Google公式のクローラー一覧</a>を見ながら、WAFやCDN側の自動ブロックでも403や429が返っていないか、アクセスログまで確認してください。robots.txtでは許可していても、WAFが弾いているケースは見落とされがちです。

確認の手順自体は難しくありません。ブラウザで `https://自社ドメイン/robots.txt` を直接開き、目視でAllow・Disallowの記載を確認します。

あわせてサーバーのアクセスログを、User-Agentの文字列（GPTBot・PerplexityBot等）でgrepすると、実際にクローラーが巡回しているかどうかが分かります。

表示はされているのにアクセスログに記録がない場合、WAF側で弾かれている可能性が高いと判断できます。

robots.txtの記載とサーバー側（WAF・CDN）の設定は別のレイヤーです。片方だけ確認して安心しないことが大切です。特にCloudflareなどのCDNを導入しているサイトは、Bot対策機能がAIクローラーまで巻き込んで止めていないか、robots.txtとは別に確認しておく必要があります。

## 設定2: llms.txtでサイト概要と実績をAIに渡す

**llms.txtは、サイトの概要と運営者情報をAIに直接渡すためのテキストファイルです。**

llms.txtはサイトのルート直下にMarkdown形式で設置します。サイト概要、運営者情報、主要コンテンツへのリンクを簡潔にまとめておくと、AIがサイト全体の文脈を把握しやすくなります。

私たちは自社サイトのllms.txtに、運営会社の実績と主要記事一覧を記載しています。当社は自社サイトをAIO対策の実験場にしており、構造化データ・llms.txt・主要AIクローラー20種の許可を実装したうえで、引用状況を日次で計測しています。

llms.txtの運営者情報には、抽象的な自己紹介ではなく確認できる実績を書くことが重要です。当社は2020年3月創業、大阪市東成区を拠点に店舗集客とAI活用を支援しており、MEO運用サービス「G-ran」では通算3,200店舗以上を運用してきました。こうした具体的な数字は、AIが運営者の信頼性を判断する材料にもなります。

この運用を続ける中で分かったことがあります。llms.txt単体で順位や引用が急に変わることはありません。ただ、AIがサイト全体の位置づけを把握する手がかりにはなっていると感じています。個別記事のクロールが遅れているときも、llms.txt経由でサイトの存在自体は把握されているケースが多いためです。

新しい記事を公開したら、llms.txtにも1行追記する運用にしておくと、サイト全体の案内が常に最新の状態を保てます。書き方はシンプルで、`- [記事タイトル](URL): 記事の1行説明` という形式を1記事1行で追加していくだけです。凝った文章にする必要はなく、むしろ簡潔なほうが機械には読み取りやすくなります。

## 設定3: 構造化データ(JSON-LD)で記事を機械可読にする

**構造化データは、記事の要点をAIがそのまま読み取れる形でHTMLに埋め込む仕組みです。**

記事には**BlogPosting・FAQPage・BreadcrumbList**の3種類を最低限設定します。手順を扱う記事にはHowToも追加してください。

<div class="definition-box"><span class="term">JSON-LD</span>とは、HTML内にJSON形式で構造化データを埋め込む記法です。ページの見た目には影響せず、機械だけが読み取れる情報として動作します。</div>

BlogPostingにはauthor(著者名・肩書き)とdateModified(更新日)を必ず含めてください。著者情報が空欄のまま公開されている記事を見かけますが、これはE-E-A-Tの観点でもAI検索の観点でも損をします。

dateModifiedはページ上の表記とSchema内の日付を一致させることも忘れないでください。表記だけ更新してSchemaが古いままだと、鮮度の主張自体が信用されなくなります。

FAQPageを設定する際に最も多い事故は、本文のFAQと構造化データの内容が一致していないことです。<a href="https://developers.google.com/search/docs/appearance/structured-data/faqpage" target="_blank" rel="noopener">Google公式のFAQPageガイドライン</a>でも、ページに実在するコンテンツと一致させることが明記されています。==本文とSchemaの完全一致==は、公開前に必ず確認してください。

## 設定4: 本文構造を冒頭断言・H2結論・FAQで抽出しやすくする

**本文構造は、冒頭の断言・見出し直下の結論・FAQの3点を揃えると抽出されやすくなります。**

構造化データを整えても、本文そのものが抽出しにくい書き方では意味がありません。**冒頭200字**は「◯◯は◯◯です」という断言型で始め、前置きや挨拶は入れません。各H2の直下には40〜60字の1文結論を置き、その1文だけを切り出しても意味が通るようにします。

具体的な書き方は、[AIO対策でAIに引用されるには？5つの実践ポイント](/aio/aio-taisaku-ai-inyou-sareru/)で詳しく解説しています。設定作業と文章構造の調整は別の作業に見えますが、片方だけを整えても引用にはつながりません。

<figure><img src="/images/ai-kensaku-taiou-settei/point5.png" alt="AI検索対応で整える5つの設定: robots.txtでAIクローラーを個別に許可する、llms.txtでサイト概要と実績を渡す、構造化データで記事を機械可読にする、冒頭断言とH2結論で本文を抽出しやすくする、HTTPS・表示速度・sitemapを整える" width="1200" height="675" loading="lazy"><figcaption>AI検索対応で整える5つの設定（当メディア作成）</figcaption></figure>

## 設定5: クロールの土台(HTTPS・表示速度・sitemap)を整える

**クロールの土台は、HTTPS・表示速度・sitemapの3点が整って初めて機能します。**

どれだけrobots.txtや構造化データを整えても、サーバーの応答が遅い、あるいはHTTPS証明書が切れていれば、クローラーは巡回を後回しにします。**HTTPS・表示速度・sitemap**は、他の設定より地味ですが土台として欠かせません。

表示速度はLCP・INP・CLSの3指標(Core Web Vitals)で確認します。sitemap.xmlは新しい記事を公開するたびに更新し、lastmodを実際の更新日に合わせてください。

私たちが自社サイトを運用する中でも、sitemap.xmlの更新を怠ると新規記事のインデックスが遅れる場面を何度も見てきました。<a href="https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap" target="_blank" rel="noopener">Google公式のsitemap作成ガイド</a>にも、更新のたびにsitemapを最新化する重要性が書かれています。技術的な土台は地味な作業ですが、抜けると他の設定の効果が発揮されません。

## 設定後にログとGSCで反映を確認する手順

**設定後は、アクセスログとGSCで実際にクローラーが読みに来ているかを確認します。**

設定して終わりにせず、反映を確認する手順まで運用に組み込んでください。まずアクセスログでGPTBotやPerplexityBotのアクセスが記録されているかを確認します。次にGoogle Search Consoleの生成AIパフォーマンスレポートで、AI Overviewのインプレッションが発生しているかを見ます。

当サイトの実測では、直近28日で291個の検索語からのべ2,171回表示され、7回のクリックがありました（自社サイトのSearch Console実測・2026年9月時点）。この数値も、設定の効果を継続的に確認するための一つの指標として使っています。対応状況を体系的にチェックしたい場合は、[AIO診断のやり方｜無料チェック8項目とツールの使い分け](/aio/aio-shindan-yarikata/)も参考になります。

社内にエンジニアがいない場合、ここまでの設定を自社だけで完結させるのは負担が大きいこともあります。どこまで自社で対応できるかは、[AIO対策は自分でできる？無料で始める5つの手順と3つの限界](/aio/aio-taisaku-jibunde/)で判断基準を整理しています。

<figure><img src="/images/ai-kensaku-taiou-settei/ngok.png" alt="未設定サイトはAIクローラーをまとめてブロックしている・llms.txtが存在しない・FAQPageと本文が一致していない。設定済みサイトは主要AIクローラーを個別に許可している・llms.txtでサイト概要を渡している・FAQPageと本文が完全一致している" width="1200" height="675" loading="lazy"><figcaption>未設定サイトと設定済みサイトの違い（当メディア作成）</figcaption></figure>

## AI検索対応でよくある失敗と注意点

**よくある失敗は、まとめてブロック・設定して放置・本文とSchemaの不一致の3つです。**

1つ目は、AI系クローラーを「念のため」まとめてブロックしてしまうケースです。Googlebotまで巻き込んで止めてしまうと、通常検索の順位まで落ちます。

2つ目は、robots.txtとllms.txtを一度設置したまま放置することです。<a href="https://www.indexnow.org/" target="_blank" rel="noopener">IndexNow</a>は、更新したURLをBing・Copilot系へ即時通知する仕組みです。この通知や、公開のたびのllms.txt追記を運用に組み込まないと、設定した効果が薄れていきます。

3つ目は、FAQPageの本文とSchemaが一致しないまま公開することです。修正のたびにどちらか片方だけを直すと、次第にずれが蓄積します。私たちは記事のFAQを修正するたびに、本文とSchemaの両方を突き合わせて確認する運用にしています。

これら3つの失敗に共通するのは、一度設定して終わりにする運用そのもの。robots.txt・llms.txt・構造化データは、記事を公開するたびに見直す項目としてチェックリスト化しておくと、事故が起きにくくなります。

<div class="caution-box"><span class="box-title">注意: 設定は一度で終わらない</span><br>robots.txtやllms.txtは一度設置すれば終わりではなく、新しいAIクローラーの追加や記事の公開のたびに見直す運用が必要です。</div>

<figure><img src="/images/ai-kensaku-taiou-settei/junban.png" alt="設定に着手する4ステップ: 今日はrobots.txtを確認、1週目はllms.txtを設置、2週目は構造化データを実装、月1回はGSCで反映を確認" width="1200" height="675" loading="lazy"><figcaption>設定に着手する4ステップ（当メディア作成）</figcaption></figure>

## よくある質問

<div class="faq">
<details><summary>AI検索対応とは具体的に何をすることですか？</summary><p class="faq-a">robots.txtでAIクローラーを許可し、llms.txtと構造化データでサイト情報を機械可読にすることです。</p></details>
<details><summary>robots.txtで最低限確認すべきクローラーは何ですか？</summary><p class="faq-a">Googlebot・GPTBot・OAI-SearchBot・ClaudeBot・PerplexityBotの5つです。</p></details>
<details><summary>llms.txtは必ず設置しないといけませんか？</summary><p class="faq-a">必須ではありませんが、AIにサイト概要を直接伝えられるため設置が推奨されます。</p></details>
<details><summary>構造化データはどのSchemaを優先すべきですか？</summary><p class="faq-a">記事にはBlogPostingとFAQPage、パンくずにはBreadcrumbListを優先します。</p></details>
<details><summary>設定してもすぐにAI検索に反映されますか？</summary><p class="faq-a">反映まで数週間かかることが多く、即日での変化は期待しないほうが安全です。</p></details>
<details><summary>対応済みかどうかはどこで確認できますか？</summary><p class="faq-a">GSCの生成AIパフォーマンスレポートとアクセスログのクローラー種別で確認します。</p></details>
</div>

自社サイトがAI検索にどこまで対応できているかは、[AI検索の対応度チェック（無料・30秒）](/diagnosis/aio/)で確かめられます。登録は不要です。

## まとめ: AI検索対応は「許可」と「構造」の両輪

AI検索対応は、単発の設定ではなく、許可と構造という2つの軸を継続的に整える取り組みです。robots.txtとllms.txtでクローラーへの許可を整え、構造化データと本文構造でAIが読み取れる形にする。この2つが揃って初めて、検索順位という土台の上にAI検索対応が成立します。

今日からできるのは、robots.txtで主要AIクローラーの許可状況を確認することです。次にllms.txtの有無を確認し、なければ設置してください。私たちも新しい記事を公開するたびに、この7つの設定項目に立ち返って点検しています。
