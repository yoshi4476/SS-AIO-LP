/**
 * 各サイトの問い合わせを、管制塔スプレッドシートへ転送する共通コード
 * ------------------------------------------------------------------
 * このファイルの中身を、各サイトの Apps Script プロジェクトへ「新しいファイル」として
 * 追加し、既存の doPost の中から forwardToHub_() を1行呼ぶだけで使えます。
 *
 * なぜ「送信先の付け替え」ではなく「転送」なのか:
 *   コーポレートには送信者への自動返信、補助金には重複検出・リードスコアリング・
 *   Slack通知・種別ごとの自動返信3文面があります。送信先を管制塔に変えると
 *   これらが全て動かなくなるため、既存の処理は残したままコピーだけを送ります。
 *   また、管制塔が落ちても各サイトの受付は止まりません（転送の失敗は無視します）。
 *
 * 【導入手順】各サイトの Apps Script で:
 *   1. 左の「ファイル」＋ →「スクリプト」→ 名前を forward-to-hub にして、この中身を貼る
 *   2. HUB_URL と HUB_SECRET を下の定数に設定する
 *   3. 既存の doPost の中、シートへの保存が終わった直後に次の1行を足す
 *        forwardToHub_(data, 'corporate');   // 補助金なら 'subsidy'、AI集客ラボなら 'ai-lab'
 *      ※ data は、フォームから届いた項目が入ったオブジェクト
 *   4. 保存 →「デプロイ」→「デプロイを管理」→ 鉛筆 → バージョン「新バージョン」→ デプロイ
 */

// ▼ 管制塔のウェブアプリURL（/exec で終わるもの）
const HUB_URL = 'https://script.google.com/macros/s/XXXXXXXXXXXXXXXX/exec';
// ▼ 管制塔側の SHARED_SECRET と同じ値
const HUB_SECRET = 'XXXXXXXXXXXXXXXX';

/**
 * 管制塔へ問い合わせ1件を転送する。
 * 失敗しても例外を投げない（転送はあくまで控えの記録で、本処理を止めてはいけない）。
 *
 * @param {Object} data  フォームから届いた項目（name / company / email / tel / topic / detail など）
 * @param {string} siteId  'ai-lab' | 'corporate' | 'subsidy'
 * @param {string} [referer]  送信元ページURL（分かる場合）
 */
function forwardToHub_(data, siteId, referer) {
  if (!HUB_URL || HUB_URL.indexOf('XXXX') >= 0) return;  // 未設定なら何もしない
  try {
    // 管制塔は本文を message で受ける。フォームの項目名（コーポレートは detail）のまま送ると
    // 「必須項目が入力されていません」で弾かれる。元の data は書き換えずに写しへ足す
    const payloadData = Object.assign({}, data);
    if (!payloadData.message) payloadData.message = data.detail || data.body || data.topic || '';
    const res = UrlFetchApp.fetch(HUB_URL, {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify({
        action: 'contact',
        secret: HUB_SECRET,
        site: siteId,
        referer: referer || '',
        // 通知メールは各サイト側で既に送っている。ここで送ると1件で2通届くため止める
        silent: true,
        data: payloadData,
      }),
      muteHttpExceptions: true,   // 管制塔側が落ちていても例外にしない
      followRedirects: true,
    });
    // 応答を見ないと、弾かれても誰も気づけない（本処理は止めずにログへ残す）
    let ok = false;
    try { ok = JSON.parse(res.getContentText()).ok === true; } catch (e) { ok = false; }
    if (!ok) {
      console.error('管制塔が転送を受け付けませんでした（本処理は続行）: HTTP ' +
        res.getResponseCode() + ' ' + res.getContentText().slice(0, 300));
    }
  } catch (err) {
    console.error('管制塔への転送に失敗（本処理は続行）: ' + err);
  }
}

/** 設定が正しいかを確かめる。Apps Scriptのエディタから手動実行して使う */
function testForwardToHub() {
  forwardToHub_({
    form_type: '接続テスト',
    company: 'テスト株式会社',
    name: 'テスト太郎',
    email: 'test@example.com',
    tel: '06-0000-0000',
    topic: '動作確認',
    detail: '管制塔への転送テストです。特典コードの判定は動きません。',
  }, 'corporate', 'テスト実行');
  console.log('転送しました。管制塔の「問い合わせ」シートに1行増えていれば成功です。');
}
