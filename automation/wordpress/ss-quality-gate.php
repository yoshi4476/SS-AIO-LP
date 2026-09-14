<?php
/**
 * Plugin Name: 品質ゲート（公開前の最終関門）
 * Description: 採点を通っていない記事が公開されるのを、保存のたびに止める。
 * Version: 1.0.0
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

// 人が管理画面で書いた記事に求める最低限。採点の仕組みを通らないぶん、
// 数えられるものだけを見る。0 にすると人の投稿を素通しできる
const SSQG_HUMAN_MIN_CHARS = 3000;
const SSQG_HUMAN_MIN_H2    = 4;


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
function ssqg_reasons($post_id, $content)
{
    $by = get_post_meta($post_id, SSQG_META_BY, true);

    // パイプラインが入れた記事: 採点の結果だけを見る
    if ($by !== 'human') {
        $score = (int) get_post_meta($post_id, SSQG_META_SCORE, true);
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
 */
add_filter('wp_insert_post_data', function ($data, $postarr) {
    if ($data['post_status'] !== 'publish' && $data['post_status'] !== 'future') {
        return $data;
    }
    if (($data['post_type'] ?? 'post') !== 'post') {
        return $data;   // 固定ページ・カスタム投稿は対象外
    }
    $post_id = (int) ($postarr['ID'] ?? 0);
    if (!$post_id) {
        return $data;   // 新規。メタがまだ無いので②で見る
    }
    $reasons = ssqg_reasons($post_id, $data['post_content'] ?? '');
    if (empty($reasons)) {
        return $data;
    }
    $data['post_status'] = 'draft';
    update_post_meta($post_id, '_ss_gate_blocked', implode(' / ', $reasons));
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
    ssqg_recheck($post->ID, $post);
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
 * スコアと執筆者の区分を REST API から読み書きできるようにする
 */
add_action('init', function () {
    foreach ([SSQG_META_SCORE => 'integer', SSQG_META_BY => 'string',
              '_ss_gate_last_reason' => 'string'] as $key => $type) {
        register_post_meta('post', $key, [
            'type'          => $type,
            'single'        => true,
            'show_in_rest'  => true,
            'auth_callback' => function () {
                return current_user_can('edit_posts');
            },
        ]);
    }
});


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
