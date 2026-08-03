/**
 * AI集客ラボ お問い合わせ受付（Google Apps Script）
 *
 * 役割:
 *   1. フォーム送信をスプレッドシートに1行ずつ蓄積する（問い合わせ台帳）
 *   2. 通知メールを Gmail から送る（Resendのドメイン認証に縛られない）
 *
 * 設置手順:
 *   1. Googleドライブで新規スプレッドシートを作成（名前例: AI集客ラボ_問い合わせ台帳）
 *   2. メニュー「拡張機能 > Apps Script」を開き、このファイルの内容を全て貼り付ける
 *   3. 下の SHARED_SECRET を、Cloudflare 側の GAS_SHARED_SECRET と同じ文字列にする
 *   4. 「デプロイ > 新しいデプロイ」→ 種類「ウェブアプリ」
 *        次のユーザーとして実行: 自分
 *        アクセスできるユーザー: 全員
 *      → 発行された /exec で終わるURLを控える（Cloudflare の GAS_WEBHOOK_URL に設定）
 *   5. 初回デプロイ時に権限の承認を求められるので許可する
 *
 * 注意: コードを修正したら「デプロイ > デプロイを管理 > 編集 > バージョン: 新バージョン」で
 *       再デプロイすること（保存だけでは公開URLに反映されない）
 */

// ▼ 設定 ---------------------------------------------------------------
const SHARED_SECRET = 'vPwJAYWcenPoAUBx7TQFEufmjF5qpplc';  // Cloudflare の GAS_SHARED_SECRET と一致させる
const NOTIFY_TO = 'info.ai@7senses.co.jp';      // 通知の宛先
const SHEET_NAME = '問い合わせ';
const AUTO_REPLY = false;                       // true にすると送信者へ自動返信を送る
const AUTO_REPLY_FROM_NAME = 'セブンセンシズ株式会社 AI集客ラボ';
// ----------------------------------------------------------------------

// 特典コード。詳細欄にこの番号があれば「特典希望」として記録する
const PERK_CODE = '3010';
const PERK_LABEL = 'MEOスタンダード無料付帯';

const HEADERS = ['受信日時', '種別', '会社名', 'お名前', 'ご担当者様', 'メールアドレス',
                 '電話番号', 'ご相談内容', '詳細', '特典', '送信元ページ',
                 'その他項目', '対応状況'];

function doPost(e) {
  try {
    const body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    if (SHARED_SECRET && body.secret !== SHARED_SECRET) {
      return jsonOut_({ ok: false, error: 'unauthorized' });
    }
    const data = body.data || {};
    saveRow_(data, body.referer || '');
    notify_(data, body.referer || '');
    if (AUTO_REPLY && isEmail_(data.email)) autoReply_(data);
    return jsonOut_({ ok: true });
  } catch (err) {
    // 失敗しても呼び出し側にエラーを返す（Cloudflare側がResendへフォールバックする）
    return jsonOut_({ ok: false, error: String(err) });
  }
}

/** 動作確認用。ウェブアプリのURLをブラウザで開くと表示される */
function doGet() {
  return jsonOut_({ ok: true, message: 'AI集客ラボ お問い合わせ受付は正常に稼働しています' });
}

function sheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) {
    sh = ss.insertSheet(SHEET_NAME);
    sh.appendRow(HEADERS);
    styleHeader_(sh);
  } else {
    migrate_(sh);
  }
  return sh;
}

function styleHeader_(sh) {
  sh.getRange(1, 1, 1, HEADERS.length).setFontWeight('bold').setBackground('#0b2447')
    .setFontColor('#ffffff');
  sh.setFrozenRows(1);
  sh.setColumnWidth(9, 420); // 詳細を広めに
}

/**
 * 項目を増やしたときに、既存の行がズレないよう列を挿入して移行する。
 * ヘッダーを書き換えるだけだと、過去の「ご相談内容」が新しい「ご担当者様」の位置に
 * ずれ込んで台帳が読めなくなる。列を差し込むことで過去データの意味を保つ。
 */
function migrate_(sh) {
  const cur = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0];
  if (cur.length >= HEADERS.length && cur[4] === 'ご担当者様') return; // 移行済み
  if (cur.indexOf('ご担当者様') >= 0) return;                          // 手作業で直した場合

  // 旧: 受信日時/種別/会社名/お名前/メールアドレス/電話番号/ご相談内容/送信元ページ/その他項目/対応状況
  sh.insertColumnBefore(5);   // お名前の後ろに「ご担当者様」
  sh.insertColumnBefore(8);   // 電話番号の後ろに「ご相談内容(選択)」。旧ご相談内容は「詳細」へ送る
  sh.insertColumnBefore(10);  // 詳細の後ろに「特典」
  sh.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]);
  styleHeader_(sh);
  SpreadsheetApp.flush();
}

/**
 * 詳細欄に特典コードが書かれているか。
 * 単に「3010」を含むかで判定すると電話番号（090-3010-1234 等）を拾ってしまうため、
 * 「特典」「コード」の語とセットの場合か、コードだけが単独で書かれた場合に限る。
 */
function hasPerk_(text) {
  if (!text) return false;
  const z = String(text).replace(/[０-９]/g, function (s) {
    return String.fromCharCode(s.charCodeAt(0) - 0xFEE0);
  });
  const flat = z.replace(/[\s\-‐―ー_.]/g, '');
  if (/特典|コード|code/i.test(z)) return flat.indexOf(PERK_CODE) >= 0;
  return /(^|[^0-9])3010([^0-9]|$)/.test(z) && !/[0-9]{5,}/.test(flat);
}

function saveRow_(data, referer) {
  const known = ['form_type', 'company', 'name', 'contact_person', 'email',
                 'tel', 'phone', 'topic', 'message', 'body', 'detail'];
  const rest = Object.keys(data)
    .filter(function (k) { return known.indexOf(k) < 0 && k.charAt(0) !== '_'; })
    .map(function (k) { return k + ': ' + data[k]; })
    .join(' / ');
  const detail = data.detail || data.message || data.body || '';
  sheet_().appendRow([
    new Date(),
    data.form_type || 'お問い合わせ',
    data.company || '',
    data.name || '',
    data.contact_person || '',
    data.email || '',
    data.tel || data.phone || '',
    data.topic || '',
    detail,
    hasPerk_(detail) ? PERK_LABEL : '',
    referer,
    rest,
    '未対応',
  ]);
}

function notify_(data, referer) {
  const label = clean_(data.form_type) || 'お問い合わせ';
  const subject = '【AI集客ラボ】' + label + ': ' + clean_(data.company) + ' ' + clean_(data.name) + '様';
  const lines = Object.keys(data)
    .filter(function (k) { return k.charAt(0) !== '_'; })
    .map(function (k) { return k + ': ' + data[k]; })
    .join('\n');
  const sheetUrl = SpreadsheetApp.getActiveSpreadsheet().getUrl();
  const options = {
    to: NOTIFY_TO,
    subject: subject,
    body: 'AI集客ラボのフォームから' + label + 'が届きました。\n\n' + lines
        + '\n\n送信元ページ: ' + (referer || '不明')
        + '\n台帳: ' + sheetUrl,
  };
  if (isEmail_(data.email)) options.replyTo = data.email; // 返信でそのまま相手に届く
  MailApp.sendEmail(options);
}

function autoReply_(data) {
  MailApp.sendEmail({
    to: data.email,
    name: AUTO_REPLY_FROM_NAME,
    subject: '【受付完了】お問い合わせありがとうございます｜AI集客ラボ',
    body: (data.name || 'ご担当') + '様\n\n'
        + 'お問い合わせいただきありがとうございます。内容を確認のうえ、2営業日以内に担当者よりご連絡いたします。\n\n'
        + 'お急ぎの場合は 06-4305-7547（9:00〜20:00 / 土日祝休）までお電話ください。\n\n'
        + '——\nセブンセンシズ株式会社 AI集客ラボ\nhttps://ai.7senses.co.jp\n'
        + '〒537-0003 大阪府大阪市東成区神路1丁目7-4 コンフォートビル901・902\n',
  });
}

function isEmail_(s) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(s || ''));
}

function clean_(s) {
  return String(s || '').replace(/[\r\n]+/g, ' ').slice(0, 80);
}

function jsonOut_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
