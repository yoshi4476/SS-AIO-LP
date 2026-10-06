<?php
/**
 * Plugin Name: 品質ゲートと橋渡し（管制塔との接続）
 * Description: 採点を通っていない記事が公開されるのを、保存のたびに止める。あわせて、管制塔が人の手なしで回すための窓口（転送・llms.txt・IndexNow の鍵・計測・公開URLの一覧・訳のページとの hreflang・表示速度・画像と動画のサイトマップ・配信の指紋・自己更新）を持つ。
 * Version: 2.0.3
 *
 * ■ 先方が最初に1回だけすること
 *   1. このファイルを wp-content/mu-plugins/ に置く
 *   2. 投稿に使うユーザー（編集者以上）でアプリケーションパスワードを発行し、運用会社へ渡す
 *   これ以降、記事・転送・llms.txt・計測の設定・このファイルの更新まで、管制塔が REST で行う。
 *
 * ■ 置き場所
 *   wp-content/mu-plugins/ss-quality-gate.php
 *   （plugins/ ではなく mu-plugins/。管理画面に停止ボタンが出ないため、
 *     「忙しかったので一旦切った」が起きない）
 *
 * ■ 何をするか
 *   公開（publish）へ進もうとする保存をすべて捕まえ、品質スコアが
 *   基準に届いていなければ下書きへ戻す。管理画面からの投稿も、
 *   REST API からの投稿も、同じ関所を通る。
 *
 * ■ なぜ必要か
 *   静的サイトでは、基準に届かない記事はファイルごと生成されないため、
 *   Web上に存在できない。WordPress はデータベースに入ってしまうので、
 *   公開ステータスへの遷移をここで止める必要がある。
 *
 * ■ 外せてしまう条件（正直に）
 *   サーバーのファイルを触れる人が、このファイルを削除すれば外れる。
 *   ただし管理画面からは無効化できないため、事故では起きない。
 */

if (!defined('ABSPATH')) {
    exit;
}

const SSQG_META_SCORE = '_ss_quality_score';   // 100点換算のスコア
const SSQG_META_BY    = '_ss_written_by';      // 'agent' か 'human'
const SSQG_MIN_SCORE  = 90;                    // これ未満は公開させない
const SSQG_META_JSONLD = '_ss_jsonld';         // 記事の構造化データ（JSON の文字列）

// 人が管理画面で書いた記事に求める最低限。採点の仕組みを通らないぶん、
// 数えられるものだけを見る。0 にすると人の投稿を素通しできる
const SSQG_HUMAN_MIN_CHARS = 3000;
const SSQG_HUMAN_MIN_H2    = 4;

// 自己更新で、届いたファイルの中にこの行があることを確かめる（版の書き換えだけの差し替えを通さない）
const SSB_VERSION = '2.0.3';
const SSB_META_JSONLD_EXTRA = '_ss_jsonld_extra';   // FAQPage など BlogPosting 以外の実体（JSON の配列）
const SSB_META_ALTERNATES = '_ss_alternates';       // 訳のページとの組（{"en": URL, …} の JSON。同じサイトの URL だけ出す）
const SSB_META_MANAGED = '_ss_managed';             // 管制塔が作った固定ページの印
const SSB_META_HASH = '_ss_source_hash';            // 配信した原稿の指紋（/ss/v1/urls で返す。本文の更新が届いたかを管制塔が照合する）
const SSB_META_MEDIA = '_ss_media';                 // 記事の画像・動画（{"images": [URL], "videos": [{…}]} の JSON。/ss-media-sitemap.xml に出す）
// 更新元と公開鍵は wp-config.php で上書きできる（鍵を替えるときのため）。ここに置くのは公開鍵だけ
if (!defined('SSB_UPDATE_URL')) {
    define('SSB_UPDATE_URL', 'https://ai.7senses.co.jp/wp/ss-bridge.json');
}
if (!defined('SSB_PUBKEY')) {
    define('SSB_PUBKEY', 'hlNuMbLzh43H3cU8vTuF+ADK/mV4+0LG8Oi4pMwhaqY=');   // Ed25519 の公開鍵（base64）。python scripts/wp_bridge.py --keygen が書く
}


/**
 * 記事の実文字数（タグと空白を除く）
 */
function ssqg_body_chars($content)
{
    $text = wp_strip_all_tags((string) $content);
    $text = preg_replace('/\s+/u', '', $text);
    return mb_strlen($text, 'UTF-8');
}

function ssqg_h2_count($content)
{
    return preg_match_all('/<h2[\s>]/i', (string) $content);
}

/**
 * 公開してよいか。だめな理由の配列を返す（空なら公開可）
 */
/**
 * 判定に使うメタ。REST の保存中は、リクエストに入ってきた値を先に見る。
 *
 * REST は本文を保存して save_post を走らせ、そのあとでメタを保存する。保存済みのメタだけを見ていたため、
 * 採点つきで送った新規の記事が「品質スコアがありません」で必ず下書きに戻っていた（2026-10-06 手元の WordPress で確認）
 */
function ssqg_meta($post_id, $key)
{
    $p = $GLOBALS['ssqg_pending'] ?? null;
    if (is_array($p) && array_key_exists($key, $p)) {
        return $p[$key];
    }
    return $post_id ? get_post_meta($post_id, $key, true) : '';
}

add_filter('rest_pre_insert_post', function ($prepared, $request) {
    $m = $request->get_param('meta');
    $GLOBALS['ssqg_pending'] = is_array($m)
        ? array_intersect_key($m, [SSQG_META_SCORE => 1, SSQG_META_BY => 1]) : [];
    return $prepared;
}, 10, 2);

function ssqg_reasons($post_id, $content)
{
    $by = ssqg_meta($post_id, SSQG_META_BY);

    // パイプラインが入れた記事: 採点の結果だけを見る
    if ($by !== 'human') {
        $score = (int) ssqg_meta($post_id, SSQG_META_SCORE);
        if ($score <= 0) {
            return ['品質スコアがありません（採点を通っていない記事です）'];
        }
        if ($score < SSQG_MIN_SCORE) {
            return [sprintf('品質スコアが %d 点です（%d 点以上が必要）',
                            $score, SSQG_MIN_SCORE)];
        }
        return [];
    }

    // 人が書いた記事: 数えられるものだけを見る
    $bad = [];
    $chars = ssqg_body_chars($content);
    if ($chars < SSQG_HUMAN_MIN_CHARS) {
        $bad[] = sprintf('本文が %s 字です（%s 字以上が必要）',
                         number_format($chars), number_format(SSQG_HUMAN_MIN_CHARS));
    }
    $h2 = ssqg_h2_count($content);
    if ($h2 < SSQG_HUMAN_MIN_H2) {
        $bad[] = sprintf('見出し（H2）が %d 個です（%d 個以上が必要）',
                         $h2, SSQG_HUMAN_MIN_H2);
    }
    return $bad;
}


/**
 * ① 更新時の関所。すでにメタがある記事は、ここで止められる。
 *
 * wp_insert_post_data は管理画面・REST API・WP-CLI・予約投稿のどれもが
 * 必ず通る。ただし新規投稿では $postarr['ID'] がまだ 0 で、メタも
 * 保存前のため判定できない。新規は下の②で受け止める。
 * REST の新規は、リクエストのメタで公開の前に判定する（公開→下書きの往復で、
 * 他のプラグインの「公開したら SNS へ流す」が走らないように）
 */
add_filter('wp_insert_post_data', function ($data, $postarr) {
    if ($data['post_status'] !== 'publish' && $data['post_status'] !== 'future') {
        return $data;
    }
    if (($data['post_type'] ?? 'post') !== 'post') {
        return $data;   // 固定ページ・カスタム投稿は対象外
    }
    $post_id = (int) ($postarr['ID'] ?? 0);
    if (!$post_id && empty($GLOBALS['ssqg_pending'])) {
        return $data;   // 新規。メタがまだ無いので②で見る
    }
    $reasons = ssqg_reasons($post_id, $data['post_content'] ?? '');
    if (empty($reasons)) {
        return $data;
    }
    $data['post_status'] = 'draft';
    if ($post_id) {
        update_post_meta($post_id, '_ss_gate_blocked', implode(' / ', $reasons));
    }
    return $data;
}, 999, 2);   // 優先度を大きくして、他のプラグインの書き換えより後に効かせる


/**
 * ② メタが保存されたあとの関所。ここが本体。
 *
 * 新規投稿では、本文とメタが別々に保存される。メタが入る前に判定すると
 * 「スコアが無い」と誤判定して、正しく採点した記事まで下書きに落ちる。
 * 保存が終わってから見直し、だめなら下書きへ戻す。
 */
function ssqg_recheck($post_id, $post = null)
{
    if (wp_is_post_revision($post_id) || wp_is_post_autosave($post_id)) {
        return;
    }
    $post = $post ?: get_post($post_id);
    if (!$post || $post->post_type !== 'post') {
        return;
    }
    if ($post->post_status !== 'publish' && $post->post_status !== 'future') {
        return;
    }
    $reasons = ssqg_reasons($post_id, $post->post_content);
    if (empty($reasons)) {
        delete_post_meta($post_id, '_ss_gate_blocked');
        return;
    }
    update_post_meta($post_id, '_ss_gate_blocked', implode(' / ', $reasons));
    update_post_meta($post_id, '_ss_gate_last_reason', implode(' / ', $reasons));
    // 自分のフックで無限に呼ばれないよう、いったん外してから戻す
    remove_action('save_post', 'ssqg_recheck', 999);
    wp_update_post(['ID' => $post_id, 'post_status' => 'draft']);
    add_action('save_post', 'ssqg_recheck', 999, 2);
}
add_action('save_post', 'ssqg_recheck', 999, 2);

// REST API はメタの保存がさらに後になるため、そこでもう一度見る
add_action('rest_after_insert_post', function ($post) {
    unset($GLOBALS['ssqg_pending']);
    ssqg_recheck($post->ID, get_post($post->ID));
}, 999, 1);


/**
 * 止めた理由を管理画面に出す。黙って下書きに戻ると、
 * 「公開したのに出ない」という問い合わせになる
 */
add_action('admin_notices', function () {
    $screen = get_current_screen();
    if (!$screen || $screen->base !== 'post') {
        return;
    }
    $post_id = get_the_ID();
    if (!$post_id) {
        return;
    }
    $why = get_post_meta($post_id, '_ss_gate_blocked', true);
    if (!$why) {
        return;
    }
    printf(
        '<div class="notice notice-error"><p><strong>品質ゲート：公開を止めました。</strong><br>%s</p>'
        . '<p>基準を満たしてから、もう一度公開してください。</p></div>',
        esc_html($why)
    );
    delete_post_meta($post_id, '_ss_gate_blocked');
});


/**
 * スコア・執筆者の区分・構造化データを REST API から読み書きできるようにする
 */
add_action('init', function () {
    $metas = [
        'post' => [SSQG_META_SCORE => 'integer', SSQG_META_BY => 'string',
                   '_ss_gate_last_reason' => 'string', SSQG_META_JSONLD => 'string',
                   SSB_META_JSONLD_EXTRA => 'string', SSB_META_ALTERNATES => 'string',
                   SSB_META_HASH => 'string', SSB_META_MEDIA => 'string'],
        // 業種のまとめ・用語集などは固定ページとして作る。_ss_managed の無いページは管制塔が触らない
        'page' => [SSQG_META_JSONLD => 'string', SSB_META_MANAGED => 'string', SSB_META_ALTERNATES => 'string'],
    ];
    foreach ($metas as $ptype => $keys) {
        foreach ($keys as $key => $type) {
            register_post_meta($ptype, $key, [
                'type'          => $type,
                'single'        => true,
                'show_in_rest'  => true,
                'auth_callback' => function () {
                    return current_user_can('edit_posts');
                },
            ]);
        }
    }
});


/**
 * 構造化データを head に出す。
 *
 * 本文に <script> を入れると、投稿ユーザーに unfiltered_html の権限が無い場合に
 * WordPress が除去する（管理者以外・マルチサイトでは既定で無い）。そこで投稿メタに
 * JSON だけを入れてもらい、ここで出す。メタは文字列なので、JSON として読めたものだけを
 * 組み直して出す（任意の HTML を出さない。< > & は \u 表記にして </script> を作らせない）
 */
function ssqg_print_jsonld($raw)
{
    if (!is_string($raw) || $raw === '') {
        return;
    }
    $data = json_decode($raw, true);
    if (!is_array($data)) {
        return;
    }
    $json = wp_json_encode($data, JSON_UNESCAPED_UNICODE | JSON_HEX_TAG | JSON_HEX_AMP);
    if ($json === false) {
        return;
    }
    echo '<script type="application/ld+json">' . $json . "</script>\n";
}

add_action('wp_head', function () {
    if (!is_singular('post') && !is_singular('page')) {
        return;
    }
    $id = get_queried_object_id();
    ssqg_print_jsonld(get_post_meta($id, SSQG_META_JSONLD, true));
    // FAQPage など、記事の BlogPosting とは別の実体（配列の JSON）
    if (is_singular('post')) {
        ssqg_print_jsonld(get_post_meta($id, SSB_META_JSONLD_EXTRA, true));
    }
    // 日本語の記事と訳のページ（固定ページ）の双方から、互いを指す hreflang（片側だけだと Google は使わない）
    foreach (ssb_alternates($id) as $lang => $url) {
        printf('<link rel="alternate" hreflang="%s" href="%s">' . "\n", esc_attr($lang), esc_url($url));
    }
});


/**
 * 日本語の記事と訳のページ（管制塔が作る固定ページ /en/<slug>/ など）の組。
 * 投稿メタ _ss_alternates（JSON）から、言語の名前の形をした鍵と、同じサイトの http(s) の URL だけを採る。
 * 指す先が公開されていなければ出さない（404 を指す hreflang を出さない）。
 * 記事は自分（ja・x-default）をパーマリンクから出す。訳のページは組をそのまま（日本語の記事も公開済みのものだけ）。
 * 2言語にならなければ何も出さない
 */
function ssb_alternates($id)
{
    $raw = get_post_meta($id, SSB_META_ALTERNATES, true);
    $data = is_string($raw) && $raw !== '' ? json_decode($raw, true) : null;
    $self = get_permalink($id);
    if (!is_array($data) || !$self) {
        return [];
    }
    $is_post = get_post_type($id) === 'post';
    $home = strtolower((string) (wp_parse_url(home_url('/'), PHP_URL_HOST) ?? ''));
    $out = [];
    foreach ($data as $lang => $url) {
        if (!is_string($lang) || !is_string($url) || ($is_post && ($lang === 'ja' || $lang === 'x-default'))
            || !preg_match('/^(x-default|[a-z]{2,3}(-[A-Za-z0-9]{2,8})*)$/', $lang)) {
            continue;
        }
        $u = wp_parse_url($url);
        if (!is_array($u) || !in_array($u['scheme'] ?? '', ['http', 'https'], true)
            || $home === '' || strtolower((string) ($u['host'] ?? '')) !== $home) {
            continue;
        }
        $pid = url_to_postid($url);
        if (!$pid || get_post_status($pid) !== 'publish') {
            continue;
        }
        $out[$lang] = $url;
    }
    if ($is_post) {
        return $out ? array_merge(['ja' => $self, 'x-default' => $self], $out) : [];
    }
    return count(array_diff(array_keys($out), ['x-default'])) >= 2 ? $out : [];
}


/*
 * 表示速度（管制塔の scripts/speed_fix.py と同じ方針のうち、テーマに手を入れずにフィルターで出来るもの）。
 *   1. 本文の画像は遅延読み込み（loading の無い img だけ。WordPress 本体は width/height の無い画像に付けない）
 *   2. 記事のアイキャッチ（LCP の候補）は優先して読む
 *   3. 計測タグ（gtag.js・172KB）は描画の後（load から1.2秒後）に読む。それまでの出来事は dataLayer に溜まる
 *   4. 日本語の Web フォント（Google Fonts）の CSS を読まない（端末のフォントで描く。1ページ 1.0〜1.4MB 減る）
 * テーマの PHP に直書きされたフォント・計測タグは直せない（FTP の接続情報があれば speed_fix.py で直す）。
 * 止めるときは wp-config.php で define('SSB_SPEED', false);、フォントだけ残すときは define('SSB_KEEP_WEBFONTS', true);
 */
if (!defined('SSB_SPEED')) {
    define('SSB_SPEED', true);
}

function ssb_speed_on()
{
    return SSB_SPEED && !is_admin() && !is_feed() && !wp_doing_ajax() && !(defined('REST_REQUEST') && REST_REQUEST);
}

add_filter('the_content', function ($html) {
    if (!ssb_speed_on() || !is_string($html) || stripos($html, '<img') === false) {
        return $html;
    }
    return preg_replace_callback('/<img\b(?![^>]*\sloading=)[^>]*>/i', function ($m) {
        $add = ' loading="lazy"' . (stripos($m[0], 'decoding=') === false ? ' decoding="async"' : '');
        return preg_replace('/^<img\b/i', '<img' . $add, $m[0], 1);
    }, $html);
}, 99);

add_filter('wp_get_attachment_image_attributes', function ($attr, $attachment) {
    static $done = false;
    if ($done || !ssb_speed_on() || !is_singular('post') || !is_object($attachment)) {
        return $attr;
    }
    if ((int) get_post_thumbnail_id(get_queried_object_id()) !== (int) $attachment->ID) {
        return $attr;
    }
    $done = true;
    $attr['fetchpriority'] = 'high';
    $attr['loading'] = 'eager';
    return $attr;
}, 99, 2);

add_filter('script_loader_tag', function ($tag, $handle, $src) {
    if (!ssb_speed_on() || !is_string($src) || strpos($src, 'https://www.googletagmanager.com/gtag/js') !== 0) {
        return $tag;
    }
    $late = '<script>window.addEventListener("load",function(){setTimeout(function(){var s=document.createElement("script");'
        . 's.async=true;s.src=' . wp_json_encode($src, JSON_HEX_TAG | JSON_HEX_AMP | JSON_UNESCAPED_SLASHES)
        . ';document.head.appendChild(s);},1200);});</script>';
    // 前後のインラインの設定（gtag('config', …)）は残し、読み込みの1行だけを差し替える
    return preg_replace_callback('#<script\b[^>]*\ssrc=["\']https://www\.googletagmanager\.com/gtag/js[^"\']*["\'][^>]*>\s*</script>#i',
        function () use ($late) {
            return $late;
        }, $tag, 1);
}, 99, 3);

add_filter('style_loader_tag', function ($tag, $handle, $href) {
    if (!ssb_speed_on() || defined('SSB_KEEP_WEBFONTS') || !is_string($href)) {
        return $tag;
    }
    if (preg_match('#^(https:)?//fonts\.googleapis\.com/css2?\?.*family=[^&]*(Noto\+Sans\+JP|Noto\+Serif\+JP|Zen\+|Shippori|M\+PLUS|Kosugi|Sawarabi|BIZ\+UD|Kiwi\+Maru|Klee|Yu\+Gothic)#i', $href)) {
        return '';
    }
    return $tag;
}, 99, 3);


/**
 * 記事一覧にスコアの列を出す。どれが採点済みか一目で分かるように
 */
add_filter('manage_post_posts_columns', function ($cols) {
    $cols['ss_score'] = '品質スコア';
    return $cols;
});

add_action('manage_post_posts_custom_column', function ($col, $post_id) {
    if ($col !== 'ss_score') {
        return;
    }
    $by = get_post_meta($post_id, SSQG_META_BY, true);
    if ($by === 'human') {
        echo '<span style="color:#666">人が執筆</span>';
        return;
    }
    $score = (int) get_post_meta($post_id, SSQG_META_SCORE, true);
    if ($score <= 0) {
        echo '<span style="color:#b42318">未採点</span>';
    } else {
        $color = $score >= SSQG_MIN_SCORE ? '#15783d' : '#b42318';
        printf('<strong style="color:%s">%d</strong>', $color, $score);
    }
}, 10, 2);

/*
 * 検索結果での見え方: 抜粋・画像・動画のプレビューを大きく出してよいと Google に伝える。
 * 根拠: https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag
 * WordPress 5.7 以降は max-image-preview:large を本体が出すので、残りの2つを足す。
 * noindex のページ（検索に出さない設定・下書きのプレビュー等）には足さない。
 */
add_filter('wp_robots', function ($robots) {
    if (!empty($robots['noindex']) || !empty($robots['none'])) {
        return $robots;
    }
    $robots['max-image-preview'] = 'large';
    $robots['max-snippet'] = '-1';
    $robots['max-video-preview'] = '-1';
    return $robots;
}, 20);


/* ============================================================
 * 橋渡し（管制塔が REST で操作する窓口）
 *
 * どの窓口も、任意の HTML を出させない・別のドメインへ飛ばさない・署名の無いコードを入れない。
 * 書き込みは「編集者以上」かつ「アプリケーションパスワードでの認証」に限る
 * （管理画面にログインしたブラウザ経由の呼び出しでは動かさない）。
 * ============================================================ */

const SSB_NS = 'ss/v1';
const SSB_MAX_REDIRECTS = 5000;
const SSB_MAX_LLMS_BYTES = 200000;
// AI のクローラー。robots.txt の「User-agent: *」の組に名前を足す（許可の範囲は * と同じまま）
const SSB_AI_BOTS = ['GPTBot', 'OAI-SearchBot', 'ChatGPT-User', 'ClaudeBot', 'Claude-SearchBot',
                     'PerplexityBot', 'Google-Extended', 'Applebot-Extended', 'Bingbot'];

function ssb_can_write()
{
    return current_user_can('edit_posts')
        && function_exists('rest_get_authenticated_app_password')
        && rest_get_authenticated_app_password() !== null;
}

/**
 * 同じサイトの中のパスか。転送先・転送元はこれを通ったものだけ持つ。
 * 「//evil.example/」や「/\evil」はブラウザが別ドメインと読むので通さない
 */
function ssb_safe_path($p)
{
    if (!is_string($p) || $p === '' || strlen($p) > 500) {
        return false;
    }
    return (bool) preg_match('#^/(?![/\\\\])[A-Za-z0-9\-._~%!$&\'()*+,;=:@/]*$#', $p);
}

function ssb_norm($p)
{
    $p = '/' . ltrim((string) $p, '/');
    return $p === '/' ? '/' : untrailingslashit($p);
}

/** いまのリクエストのパス（WordPress を下の階層に置いたサイトでも、ホームからの相対で比べる） */
function ssb_req_path()
{
    $p = (string) wp_parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
    $home = (string) wp_parse_url(home_url('/'), PHP_URL_PATH);
    if ($home !== '' && $home !== '/' && strpos($p, $home) === 0) {
        $p = '/' . substr($p, strlen($home));
    }
    return $p === '' ? '/' : $p;
}

function ssb_text_response($text)
{
    status_header(200);
    header('Content-Type: text/plain; charset=utf-8');
    header('X-Content-Type-Options: nosniff');
    header('Cache-Control: public, max-age=3600');
    echo $text;
    exit;
}


/**
 * /llms.txt と IndexNow の鍵ファイルを返す。中身はオプションに保存した文字列だけ（テキストとして出す）。
 * サーバーに同じ名前のファイルが実在すれば、そちらが先に返る（WordPress まで来ない）
 */
add_action('parse_request', function () {
    $p = ssb_norm(ssb_req_path());
    if ($p === '/ss-media-sitemap.xml') {
        status_header(200);
        header('Content-Type: application/xml; charset=utf-8');
        header('X-Content-Type-Options: nosniff');
        header('Cache-Control: public, max-age=3600');
        echo ssb_media_sitemap();
        exit;
    }
    if ($p === '/llms.txt') {
        $t = (string) get_option('ssb_llms', '');
        if ($t !== '') {
            ssb_text_response($t);
        }
        return;
    }
    $key = (string) get_option('ssb_indexnow_key', '');
    if ($key !== '' && $p === '/' . $key . '.txt') {
        ssb_text_response($key);
    }
    $bing = (string) get_option('ssb_bing_auth', '');
    if ($bing !== '' && strtolower($p) === '/bingsiteauth.xml' && preg_match('/^[A-Za-z0-9]{8,64}$/', $bing)) {
        status_header(200);
        header('Content-Type: application/xml; charset=utf-8');
        header('X-Content-Type-Options: nosniff');
        echo '<?xml version="1.0"?>' . "\n" . '<users><user>' . $bing . '</user></users>';
        exit;
    }
}, 0);


/** 統合した記事の旧URLを、残した記事へ301で送る（転送表はオプション。同じサイトのパスだけ） */
add_action('template_redirect', function () {
    $map = get_option('ssb_redirects', []);
    if (!is_array($map) || !$map) {
        return;
    }
    $from = ssb_norm(ssb_req_path());
    $to = $map[$from] ?? null;
    if (!ssb_safe_path($to) || ssb_norm($to) === $from) {
        return;
    }
    // wp_safe_redirect は許可したホスト以外へは飛ばない（パスの検査に続く2つ目の歯止め）
    wp_safe_redirect(home_url($to), 301, 'ss-bridge');
    exit;
}, 1);


/** AI のクローラーを robots.txt の「User-agent: *」の組に足し、llms.txt の場所を書き添える */
add_filter('robots_txt', function ($out, $public) {
    if (!$public) {
        return $out;
    }
    $names = '';
    foreach (SSB_AI_BOTS as $ua) {
        if (stripos($out, 'User-agent: ' . $ua) === false) {
            $names .= 'User-agent: ' . $ua . "\n";
        }
    }
    if ($names !== '' && strpos($out, "User-agent: *\n") !== false) {
        $out = preg_replace('/^User-agent: \*$/m', rtrim($names) . "\nUser-agent: *", $out, 1);
    }
    if (get_option('ssb_llms', '') !== '' && stripos($out, 'llms.txt') === false) {
        $out = rtrim($out) . "\n\n# AI向けのサイト案内: " . home_url('/llms.txt') . "\n";
    }
    if (stripos($out, 'ss-media-sitemap.xml') === false && ssb_media_posts(1)) {
        $out = rtrim($out) . "\nSitemap: " . home_url('/ss-media-sitemap.xml') . "\n";
    }
    return $out;
}, 99, 2);


/**
 * 画像・動画のサイトマップ（/ss-media-sitemap.xml）。WordPress 本体の wp-sitemap は loc・lastmod 以外の項目を
 * 受け付けない（画像・動画を載せられない）ので、管制塔が配信した記事の投稿メタ _ss_media から別に作る。
 * 出すのは JSON として読めた http(s) の URL と文字だけ（esc_xml で退避。任意の XML を出させない）
 */
function ssb_media_posts($n)
{
    $q = new WP_Query([
        'post_type' => 'post', 'post_status' => 'publish', 'has_password' => false, 'posts_per_page' => $n,
        'fields' => 'ids', 'meta_key' => SSB_META_MEDIA, 'no_found_rows' => true, 'orderby' => 'ID', 'order' => 'ASC',
    ]);
    return $q->posts;
}

function ssb_media_url($u, $https_only = false)
{
    return is_string($u) && preg_match($https_only ? '#^https://#' : '#^https?://#', $u) ? esc_xml(esc_url_raw($u)) : '';
}

function ssb_media_sitemap()
{
    $out = '<?xml version="1.0" encoding="UTF-8"?>' . "\n"
        . '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
        . ' xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"'
        . ' xmlns:video="http://www.google.com/schemas/sitemap-video/1.1">' . "\n";
    foreach (ssb_media_posts(2000) as $id) {
        $m = json_decode((string) get_post_meta($id, SSB_META_MEDIA, true), true);
        if (!is_array($m)) {
            continue;
        }
        $body = '';
        foreach (array_slice((array) ($m['images'] ?? []), 0, 1000) as $img) {
            $u = ssb_media_url($img);
            if ($u !== '') {
                $body .= '<image:image><image:loc>' . $u . '</image:loc></image:image>';
            }
        }
        foreach ((array) ($m['videos'] ?? []) as $v) {
            if (!is_array($v)) {
                continue;
            }
            $thumb = ssb_media_url($v['thumbnail_loc'] ?? '', true);
            $player = ssb_media_url($v['player_loc'] ?? '', true);
            $title = is_string($v['title'] ?? null) ? trim($v['title']) : '';
            $desc = is_string($v['description'] ?? null) ? trim($v['description']) : '';
            if ($thumb === '' || $player === '' || $title === '' || $desc === '') {
                continue;      // 必須（サムネイル・題・説明・再生の場所）がそろわない動画は載せない
            }
            $desc = function_exists('mb_substr') ? mb_substr($desc, 0, 2048) : substr($desc, 0, 2048);
            $body .= '<video:video><video:thumbnail_loc>' . $thumb . '</video:thumbnail_loc>'
                . '<video:title>' . esc_xml($title) . '</video:title>'
                . '<video:description>' . esc_xml($desc) . '</video:description>'
                . '<video:player_loc>' . $player . '</video:player_loc>';
            $d = (int) ($v['duration'] ?? 0);
            if ($d >= 1 && $d <= 28800) {
                $body .= '<video:duration>' . $d . '</video:duration>';
            }
            $body .= '</video:video>';
        }
        if ($body !== '') {
            $out .= '<url><loc>' . esc_xml(esc_url_raw(get_permalink($id))) . '</loc>' . $body . "</url>\n";
        }
    }
    return $out . "</urlset>\n";
}


/**
 * 計測（GA4）。AI集客ラボの site.js と同じ出来事を同じ名前で送る。
 * 測定IDは G- で始まる形だけ保存・出力する。gtag が既にある（Site Kit 等）ときは読み込みを足さない
 */
const SSB_MEASURE_JS = <<<'JS'
(function () {
  var id = window.SSB_GA4;
  if (id && typeof window.gtag !== 'function') {
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag('js', new Date());
    window.gtag('config', id);
    var load = function () {
      setTimeout(function () {
        var s = document.createElement('script');
        s.async = true;
        s.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(id);
        document.head.appendChild(s);
      }, 1200);
    };
    if (document.readyState === 'complete') load(); else window.addEventListener('load', load);
  }
  function ga(n, p) { if (typeof window.gtag === 'function') window.gtag('event', n, p); }
  function slugId(s) {
    return String(s || '').replace(/[^\w]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 30) || 'x';
  }
  var path = location.pathname;

  var depths = [25, 50, 75, 90], sent = {};
  document.addEventListener('scroll', function () {
    var h = document.documentElement;
    var pct = ((h.scrollTop + h.clientHeight) / h.scrollHeight) * 100;
    depths.forEach(function (d) {
      if (pct >= d && !sent[d]) { sent[d] = true; ga('scroll_depth', { depth: d, page_path: path }); }
    });
  }, { passive: true });

  document.querySelectorAll('[data-ab]').forEach(function (el) {
    var key = el.getAttribute('data-ab'), v;
    try {
      v = localStorage.getItem('ab_' + key);
      if (!v) { v = Math.random() < 0.5 ? 'a' : 'b'; localStorage.setItem('ab_' + key, v); }
    } catch (err) { v = 'a'; }
    if (v === 'b' && el.getAttribute('data-ab-b')) el.textContent = el.getAttribute('data-ab-b');
    el.setAttribute('data-ab-variant', v);
    ga('ab_impression', { ab_key: key, ab_variant: v, page_path: path });
    ga('ab_impression_' + slugId(key) + '_' + v, { ab_key: key, page_path: path });
  });

  document.addEventListener('click', function (e) {
    var a = e.target.closest ? e.target.closest('a, button') : null;
    if (!a) return;
    var href = a.getAttribute('href') || '';
    if (href.indexOf('tel:') === 0) {
      ga('cta_click', { cta_id: 'tel', page_path: path });
      ga('cta_tel', { page_path: path });
      return;
    }
    var c = a.classList;
    if (!(c.contains('btn') || c.contains('cta-button') || c.contains('wp-block-button__link') || a.hasAttribute('data-cta'))) return;
    var cid = a.getAttribute('data-cta') || slugId((a.textContent || '').trim());
    var p = { cta_id: cid, page_path: path };
    var abv = a.getAttribute('data-ab-variant');
    if (abv) {
      p.ab_variant = abv;
      ga('cta_click_' + slugId(a.getAttribute('data-ab')) + '_' + abv, p);
    }
    ga('cta_click', p);
    ga('cta_' + slugId(cid), p);
    var box = a.closest('.cta-inline, .inline-tool');
    if (box) ga('inline_tool_submit', { page_path: path, tool: box.getAttribute('data-tool') || 'tool' });
  });

  document.querySelectorAll('.cta-inline, .inline-tool').forEach(function (box) {
    var p = { page_path: path, tool: box.getAttribute('data-tool') || 'tool' };
    if ('IntersectionObserver' in window) {
      var o = new IntersectionObserver(function (es) {
        if (es[0].isIntersecting) { ga('inline_tool_view', p); o.disconnect(); }
      }, { threshold: 0.6 });
      o.observe(box);
    }
    box.addEventListener('focusin', function once() {
      ga('inline_tool_start', p);
      box.removeEventListener('focusin', once);
    });
  });

  var forms = document.querySelectorAll('form.wpcf7-form, form.wpforms-form, form.form-panel, form[data-ss-form], .entry-content form, main form');
  Array.prototype.forEach.call(forms, function (f) {
    if (f.getAttribute('role') === 'search' || f.classList.contains('search-form') || f.classList.contains('wp-block-search') || f.id === 'commentform' || f._ssm) return;
    f._ssm = true;
    var type = (f.querySelector('[name="form_type"]') || {}).value || f.getAttribute('data-ss-form') || 'form';
    var started = false, last = '', done = false;
    f.addEventListener('focusin', function (e) {
      var el = e.target;
      if (!el || !el.name || el.type === 'hidden') return;
      last = el.name;
      if (!started) { started = true; ga('form_start', { form_type: type, page_path: path }); }
    });
    window.addEventListener('pagehide', function () {
      if (started && !done) ga('form_abandon', { form_type: type, last_field: last, page_path: path });
    });
    var sent = function () {
      if (done) return;
      done = true;
      var route = type.indexOf('資料') >= 0 ? 'dl' : 'form';
      ga('form_submit', { form_type: type, page_path: path });
      ga('lead_capture', { lead_route: route, form_type: type });
      ga('lead_' + route, { form_type: type });
    };
    // Contact Form 7 は送信に失敗しても submit が起きる。送れたときの出来事で数える
    if (f.classList.contains('wpcf7-form')) {
      (f.closest('.wpcf7') || f).addEventListener('wpcf7mailsent', sent);
    } else {
      f.addEventListener('submit', sent);
    }
  });

  var bar = document.querySelector('.ss-sticky');
  if (bar && window.matchMedia && matchMedia('(max-width: 760px)').matches) {
    bar.hidden = false;
    var tick = function () { bar.style.transform = scrollY > innerHeight * 1.5 ? 'none' : 'translateY(120%)'; };
    addEventListener('scroll', tick, { passive: true });
    tick();
  }
})();
JS;

add_action('wp_footer', function () {
    if (is_admin() || is_feed() || is_robots()) {
        return;
    }
    $ga = (string) get_option('ssb_ga4', '');
    if (!preg_match('/^G-[A-Z0-9]{4,20}$/', $ga)) {
        $ga = '';
    }
    // 記事のスマホ固定ボタン（設定があるときだけ）。文言は esc_html、行き先は同じサイトのパスだけ
    $st = get_option('ssb_sticky', []);
    if (is_singular('post') && is_array($st) && ssb_safe_path($st['url'] ?? '') && !empty($st['label'])) {
        printf('<div class="ss-sticky" hidden style="position:fixed;left:12px;right:12px;bottom:12px;z-index:9999;'
            . 'transform:translateY(120%%);transition:transform .25s"><a class="cta-button" href="%s" data-cta="%s"%s '
            . 'style="display:block;text-align:center;padding:14px 18px;border-radius:10px;background:#1b4fa0;color:#fff;'
            . 'font-weight:700;text-decoration:none;box-shadow:0 6px 18px rgba(0,0,0,.18)">%s</a></div>' . "\n",
            esc_url(home_url($st['url'])), esc_attr($st['cta'] ?? 'article_sticky'),
            !empty($st['label_b']) ? ' data-ab="sticky" data-ab-b="' . esc_attr($st['label_b']) . '"' : '',
            esc_html($st['label']));
    }
    echo '<script id="ss-measure">window.SSB_GA4=' . wp_json_encode($ga) . ";\n" . SSB_MEASURE_JS . "</script>\n";
}, 99);


/* ---------- REST ---------- */

add_action('rest_api_init', function () {
    $w = ['permission_callback' => 'ssb_can_write'];

    // 公開URLの一覧（パーマリンクで）。公開済み・パスワード無しの投稿と固定ページだけなので認証は要らない
    register_rest_route(SSB_NS, '/urls', [
        'methods' => 'GET',
        'permission_callback' => '__return_true',
        'callback' => function ($req) {
            $page = max(1, (int) $req->get_param('page'));
            $q = new WP_Query([
                'post_type' => ['post', 'page'], 'post_status' => 'publish', 'has_password' => false,
                'posts_per_page' => 1000, 'paged' => $page, 'fields' => 'ids', 'orderby' => 'ID', 'order' => 'ASC',
                'no_found_rows' => false,
            ]);
            $rows = [];
            foreach ($q->posts as $id) {
                $rows[] = ['url' => get_permalink($id), 'slug' => get_post_field('post_name', $id),
                           'type' => get_post_type($id), 'modified' => get_post_modified_time('c', true, $id),
                           'managed' => get_post_meta($id, SSB_META_MANAGED, true) !== '',
                           // 配信した原稿の指紋（管制塔の publish_gap が、本文の更新が届いたかを照合する）
                           'hash' => (string) get_post_meta($id, SSB_META_HASH, true)];
            }
            return ['page' => $page, 'pages' => (int) $q->max_num_pages, 'urls' => $rows];
        },
    ]);

    register_rest_route(SSB_NS, '/status', $w + [
        'methods' => 'GET',
        'callback' => function () {
            return [
                'version' => SSB_VERSION,
                'update' => get_option('ssb_update_state', null),
                'writable' => is_writable(__FILE__) && is_writable(dirname(__FILE__)),
                'signed_updates' => SSB_PUBKEY !== '',
                'redirects' => count((array) get_option('ssb_redirects', [])),
                'llms' => get_option('ssb_llms', '') !== '',
                'indexnow' => get_option('ssb_indexnow_key', '') !== '',
                'ga4' => get_option('ssb_ga4', '') !== '',
                'permalink' => (string) get_option('permalink_structure', ''),
                'wp' => get_bloginfo('version'),
                'php' => PHP_VERSION,
            ];
        },
    ]);

    register_rest_route(SSB_NS, '/redirects', [
        ['methods' => 'GET', 'permission_callback' => 'ssb_can_write',
         'callback' => function () {
             return (array) get_option('ssb_redirects', []);
         }],
        ['methods' => 'POST', 'permission_callback' => 'ssb_can_write',
         'callback' => function ($req) {
             $map = (array) get_option('ssb_redirects', []);
             $bad = [];
             foreach ((array) $req->get_param('add') as $row) {
                 $from = $row['from'] ?? '';
                 $to = $row['to'] ?? '';
                 if (!ssb_safe_path($from) || !ssb_safe_path($to) || ssb_norm($from) === ssb_norm($to)) {
                     $bad[] = ['from' => is_string($from) ? substr($from, 0, 200) : '', 'to' => is_string($to) ? substr($to, 0, 200) : ''];
                     continue;
                 }
                 $map[ssb_norm($from)] = $to;
             }
             foreach ((array) $req->get_param('remove') as $from) {
                 if (is_string($from)) {
                     unset($map[ssb_norm($from)]);
                 }
             }
             // 転送の連鎖（A→B→C）は1回で行き先へ送る形に畳む。ループになる行は捨てる
             foreach ($map as $k => $v) {
                 $seen = [$k => true];
                 while (isset($map[ssb_norm($v)]) && !isset($seen[ssb_norm($v)])) {
                     $seen[ssb_norm($v)] = true;
                     $v = $map[ssb_norm($v)];
                 }
                 if (isset($seen[ssb_norm($v)])) {
                     unset($map[$k]);
                     $bad[] = ['from' => $k, 'to' => 'loop'];
                 } else {
                     $map[$k] = $v;
                 }
             }
             if (count($map) > SSB_MAX_REDIRECTS) {
                 return new WP_Error('ssb_too_many', '転送が多すぎます', ['status' => 400]);
             }
             update_option('ssb_redirects', $map, true);
             return ['count' => count($map), 'rejected' => $bad];
         }],
    ]);

    register_rest_route(SSB_NS, '/settings', $w + [
        'methods' => 'POST',
        'callback' => function ($req) {
            $done = [];
            $llms = $req->get_param('llms');
            if (is_string($llms)) {
                $llms = str_replace("\0", '', $llms);
                if (strlen($llms) > SSB_MAX_LLMS_BYTES || ($llms !== '' && wp_check_invalid_utf8($llms) === '')) {
                    return new WP_Error('ssb_llms', 'llms.txt が大きすぎるか、UTF-8 ではありません', ['status' => 400]);
                }
                update_option('ssb_llms', $llms, false);
                $done[] = 'llms';
            }
            $key = $req->get_param('indexnow_key');
            if (is_string($key)) {
                if ($key !== '' && !preg_match('/^[A-Za-z0-9\-]{8,128}$/', $key)) {
                    return new WP_Error('ssb_key', 'IndexNow の鍵の形が違います', ['status' => 400]);
                }
                update_option('ssb_indexnow_key', $key, true);
                $done[] = 'indexnow_key';
            }
            // Bing の所有権の確認コード（英数字だけ。XML の中身は固定の形で組むので、任意の文字は出せない）
            $bing = $req->get_param('bing_auth');
            if (is_string($bing)) {
                if ($bing !== '' && !preg_match('/^[A-Za-z0-9]{8,64}$/', $bing)) {
                    return new WP_Error('ssb_bing', 'Bing の確認コードの形が違います', ['status' => 400]);
                }
                update_option('ssb_bing_auth', $bing, true);
                $done[] = 'bing_auth';
            }
            $ga = $req->get_param('ga4');
            if (is_string($ga)) {
                if ($ga !== '' && !preg_match('/^G-[A-Z0-9]{4,20}$/', $ga)) {
                    return new WP_Error('ssb_ga4', 'GA4 の測定IDは G- で始まる形です', ['status' => 400]);
                }
                update_option('ssb_ga4', $ga, true);
                $done[] = 'ga4';
            }
            $st = $req->get_param('sticky');
            if (is_array($st)) {
                if ($st && (!ssb_safe_path($st['url'] ?? '') || empty($st['label']))) {
                    return new WP_Error('ssb_sticky', '固定ボタンの行き先は同じサイトのパスだけです', ['status' => 400]);
                }
                $keep = [];
                foreach (['url', 'label', 'label_b', 'cta'] as $k) {
                    if (isset($st[$k]) && is_string($st[$k])) {
                        $keep[$k] = sanitize_text_field($st[$k]);
                    }
                }
                update_option('ssb_sticky', $keep, true);
                $done[] = 'sticky';
            }
            return ['saved' => $done];
        },
    ]);

    register_rest_route(SSB_NS, '/update', $w + [
        'methods' => 'POST',
        'callback' => function () {
            ssb_self_update();
            return get_option('ssb_update_state', null);
        },
    ]);
});


/* ---------- 自己更新 ---------- */

/** 更新元に使ってよいURLか: 更新元の設定と同じホストで https。手元の試験（環境が local で相手が127.0.0.1）だけ http を許す */
function ssb_update_url_ok($url)
{
    $u = wp_parse_url((string) $url);
    $base = wp_parse_url((string) SSB_UPDATE_URL);
    if (!is_array($u) || !is_array($base) || empty($u['host'])
        || strtolower($u['host']) !== strtolower($base['host'] ?? '')) {
        return false;
    }
    if (($u['scheme'] ?? '') === 'https') {
        return true;
    }
    return ($u['scheme'] ?? '') === 'http' && wp_get_environment_type() === 'local'
        && in_array($u['host'], ['127.0.0.1', 'localhost'], true);
}

function ssb_update_state($state, $msg, $extra = [])
{
    update_option('ssb_update_state', array_merge(
        ['state' => $state, 'msg' => $msg, 'at' => gmdate('c'), 'version' => SSB_VERSION], $extra), false);
}

/**
 * 管制塔が公開している新しい版を確かめ、署名とハッシュが合えば自分のファイルを置き換える。
 * どこかで1つでも合わなければ、いまの版のまま動き続ける（状態は /status で管制塔が読む）
 */
function ssb_self_update()
{
    if (!ssb_update_url_ok(SSB_UPDATE_URL)) {
        ssb_update_state('error', '更新元のURLが https ではありません');
        return;
    }
    $pub = SSB_PUBKEY === '' ? false : base64_decode(SSB_PUBKEY, true);
    if ($pub === false || strlen($pub) !== 32) {
        ssb_update_state('nokey', '署名を確かめる公開鍵が無いため、自動更新しません');
        return;
    }
    if (!function_exists('sodium_crypto_sign_verify_detached')
        && file_exists(ABSPATH . WPINC . '/sodium_compat/autoload.php')) {
        require_once ABSPATH . WPINC . '/sodium_compat/autoload.php';
    }
    $r = wp_remote_get(SSB_UPDATE_URL, ['timeout' => 15, 'redirection' => 0]);
    if (is_wp_error($r) || (int) wp_remote_retrieve_response_code($r) !== 200) {
        ssb_update_state('error', '更新の案内を取得できません');
        return;
    }
    $m = json_decode(wp_remote_retrieve_body($r), true);
    if (!is_array($m) || !preg_match('/^\d+\.\d+\.\d+$/', (string) ($m['version'] ?? ''))
        || empty($m['url']) || empty($m['sha256']) || empty($m['sig'])) {
        ssb_update_state('error', '更新の案内の形が違います');
        return;
    }
    if (!version_compare($m['version'], SSB_VERSION, '>')) {
        ssb_update_state('current', '最新の版です', ['latest' => $m['version']]);
        return;
    }
    if (!ssb_update_url_ok($m['url'])) {
        ssb_update_state('error', '更新ファイルの場所が更新元と別のホストです');
        return;
    }
    $f = wp_remote_get($m['url'], ['timeout' => 30, 'redirection' => 0]);
    if (is_wp_error($f) || (int) wp_remote_retrieve_response_code($f) !== 200) {
        ssb_update_state('error', '更新ファイルを取得できません');
        return;
    }
    $body = wp_remote_retrieve_body($f);
    if (!hash_equals(strtolower((string) $m['sha256']), hash('sha256', $body))) {
        ssb_update_state('error', '更新ファイルのハッシュが案内と合いません');
        return;
    }
    $sig = base64_decode((string) $m['sig'], true);
    if (!function_exists('sodium_crypto_sign_verify_detached') || $sig === false || strlen($sig) !== 64
        || !sodium_crypto_sign_verify_detached($sig, $body, $pub)) {
        ssb_update_state('error', '更新ファイルの署名が確かめられません');
        return;
    }
    if (strpos($body, '<?php') !== 0 || strpos($body, "const SSB_VERSION = '" . $m['version'] . "';") === false) {
        ssb_update_state('error', '更新ファイルの中身が案内の版と合いません');
        return;
    }
    $file = __FILE__;
    if (!is_writable($file) || !is_writable(dirname($file))) {
        ssb_update_state('blocked', 'このサーバーではプラグインのファイルを書き換えられません', ['latest' => $m['version']]);
        return;
    }
    $tmp = $file . '.new';
    if (file_put_contents($tmp, $body, LOCK_EX) !== strlen($body) || !@rename($tmp, $file)) {
        @unlink($tmp);
        ssb_update_state('blocked', '新しい版を書き込めませんでした', ['latest' => $m['version']]);
        return;
    }
    if (function_exists('opcache_invalidate')) {
        opcache_invalidate($file, true);
    }
    ssb_update_state('updated', '新しい版に置き換えました', ['from' => SSB_VERSION, 'latest' => $m['version']]);
}

add_action('ssb_self_update', 'ssb_self_update');
add_action('init', function () {
    if (!wp_next_scheduled('ssb_self_update')) {
        wp_schedule_event(time() + 600, 'daily', 'ssb_self_update');
    }
});
