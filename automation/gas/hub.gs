/**
 * セブンセンシズ 自動化管制塔（Google Apps Script）
 *
 * 3サイト（AI集客ラボ / AI導入補助金 / コーポレート）の
 *   ・お問い合わせの受付と台帳化
 *   ・キーワード台帳の管理（記事工場が読み書きする）
 *   ・記事作成ログの記録
 * を1冊のスプレッドシートに集約する。
 *
 * ────────────────────────────────
 * 設置手順（初回のみ）
 * ────────────────────────────────
 * 1. スプレッドシート「セブンセンシズ 自動化管制塔」を開く
 * 2. 拡張機能 → Apps Script を開き、このファイルの内容を全て貼り付けて保存
 * 3. 上部の関数選択で「setup」を選び ▶実行 → 権限を承認（初回のみ）
 *    → 11個のタブが自動で作られる
 * 4. デプロイ → 新しいデプロイ → 種類「ウェブアプリ」
 *      次のユーザーとして実行: 自分
 *      アクセスできるユーザー: 全員
 *    → 発行された /exec で終わるURLを控える
 *
 * ※ コードを直したら「デプロイを管理 → 編集 → バージョン: 新バージョン」で再デプロイすること
 *    （保存しただけでは公開URLに反映されない）
 */

// ▼ 設定 ────────────────────────────────
const SHARED_SECRET = 'vPwJAYWcenPoAUBx7TQFEufmjF5qpplc'; // 記事工場・フォームと共有する合言葉
const NOTIFY_TO = 'info.ai@7senses.co.jp';                // 問い合わせ通知の宛先
const AUTO_REPLY = false;                                  // true にすると送信者へ自動返信
// ────────────────────────────────────

const SITES = {
  'ai-lab': 'AI集客ラボ (ai.7senses.co.jp)',
  'subsidy': 'AI導入補助金 (lp.7senses.co.jp)',
  'corporate': 'コーポレート (www.7senses.co.jp)',
};

const TABS = {
  'ダッシュボード': ['指標', '値', '前日比', '更新日時', '備考'],
  'サイト一覧': ['サイトID', 'サイト名', 'ドメイン', 'テーマ', '公開記事数', '最終公開日'],
  '問い合わせ': ['受信日時', 'サイト', '種別', '会社名', 'お名前', 'メールアドレス',
                '電話番号', 'ご相談内容', '送信元ページ', 'その他項目', '対応状況'],
  'KW台帳': ['サイト', 'キーワード', '状態', '優先度', '想定カテゴリ', '狙い',
            '登録日', '着手日', '公開日', '記事URL', '備考'],
  '記事作成ログ': ['公開日時', 'サイト', 'タイトル', 'キーワード', 'カテゴリ',
                 'スコア', '文字数', 'URL', '備考'],
  'KPIレポート': ['日付', 'サイト', 'セッション', 'PV', '表示回数', 'クリック',
                'CTR', '平均順位', 'CV', '備考'],
  'AIO計測': ['日付', 'サイト', 'AI Overview表示', 'AI参照セッション', 'ChatGPT',
             'Perplexity', 'Gemini', 'Copilot', '備考'],
  '内部リンク管理': ['設置日', 'サイト', 'リンク元', 'リンク先', 'アンカーテキスト'],
  'リライトログ': ['実施日', 'サイト', '記事', '理由', '変更概要', '前順位', '後順位', '効果'],
  'エラーログ': ['日時', 'サイト', '工程', 'エラー内容', '対応', '状態'],
  '設定': ['項目', '値', '説明'],
};

// ============================================================
// 初期セットアップ
// ============================================================
function setup() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  Object.keys(TABS).forEach(function (name) {
    let sh = ss.getSheetByName(name);
    if (!sh) sh = ss.insertSheet(name);
    if (sh.getLastRow() === 0) {
      const headers = TABS[name];
      sh.appendRow(headers);
      sh.getRange(1, 1, 1, headers.length)
        .setFontWeight('bold').setBackground('#0b2447').setFontColor('#ffffff');
      sh.setFrozenRows(1);
    }
  });

  // サイト一覧の初期値
  const sites = ss.getSheetByName('サイト一覧');
  if (sites.getLastRow() <= 1) {
    sites.appendRow(['ai-lab', 'AI集客ラボ', 'ai.7senses.co.jp', 'AIO・LLMO・SEO・MEO', 0, '']);
    sites.appendRow(['subsidy', 'AI導入補助金サポート', 'lp.7senses.co.jp', '補助金・IT導入補助金', 0, '']);
    sites.appendRow(['corporate', 'セブンセンシズ コーポレート', 'www.7senses.co.jp',
                     '店舗経営（人材・オペレーション・DX）と導入事例', 0, '']);
  }

  // 既定シート「シート1」が空なら削除して見た目を整える
  const first = ss.getSheetByName('シート1') || ss.getSheetByName('Sheet1');
  if (first && first.getLastRow() === 0 && ss.getSheets().length > 1) ss.deleteSheet(first);

  SpreadsheetApp.getActiveSpreadsheet().toast('11タブの準備が完了しました', '管制塔セットアップ', 5);
}

function sheet_(name) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(name);
  if (!sh) { setup(); sh = ss.getSheetByName(name); }
  return sh;
}

// ============================================================
// Web API（記事工場とフォームからの入口）
// ============================================================
function doGet(e) {
  const p = (e && e.parameter) || {};
  try {
    switch (p.action) {
      case 'next_kw':  return json_(nextKw_(p.site));
      case 'all_kw':   return json_({ ok: true, keywords: allKw_() });
      case 'kw_status': return json_(kwStatus_(p.site));
      default:
        return json_({ ok: true, message: 'セブンセンシズ 自動化管制塔は正常に稼働しています' });
    }
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

function doPost(e) {
  let body = {};
  try {
    body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
  } catch (err) {
    return json_({ ok: false, error: 'JSONの解析に失敗しました' });
  }
  if (SHARED_SECRET && body.secret !== SHARED_SECRET) {
    return json_({ ok: false, error: 'unauthorized' });
  }
  try {
    switch (body.action) {
      case 'claim_kw':    return json_(claimKw_(body.site, body.keyword));
      case 'publish_log': return json_(publishLog_(body));
      case 'add_kw':      return json_(addKw_(body.site, body.keywords || []));
      case 'error_log':   return json_(errorLog_(body));
      default:            return json_(contact_(body)); // 既定は問い合わせ受付
    }
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

// ============================================================
// 問い合わせ受付
// ============================================================
function contact_(body) {
  const data = body.data || {};
  const site = SITES[body.site] || body.site || '（不明）';
  const referer = body.referer || '';

  const known = ['form_type', 'company', 'name', 'email', 'tel', 'phone', 'message', 'body'];
  const rest = Object.keys(data)
    .filter(function (k) { return known.indexOf(k) < 0 && k.charAt(0) !== '_'; })
    .map(function (k) { return k + ': ' + data[k]; }).join(' / ');

  sheet_('問い合わせ').appendRow([
    new Date(), site, data.form_type || 'お問い合わせ', data.company || '', data.name || '',
    data.email || '', data.tel || data.phone || '', data.message || data.body || '',
    referer, rest, '未対応',
  ]);

  const label = clean_(data.form_type) || 'お問い合わせ';
  const lines = Object.keys(data)
    .filter(function (k) { return k.charAt(0) !== '_'; })
    .map(function (k) { return k + ': ' + data[k]; }).join('\n');
  const opts = {
    to: NOTIFY_TO,
    subject: '【' + site.split(' ')[0] + '】' + label + ': ' + clean_(data.company) + ' ' + clean_(data.name) + '様',
    body: site + ' のフォームから' + label + 'が届きました。\n\n' + lines
        + '\n\n送信元ページ: ' + (referer || '不明')
        + '\n台帳: ' + SpreadsheetApp.getActiveSpreadsheet().getUrl(),
  };
  if (isEmail_(data.email)) opts.replyTo = data.email;
  MailApp.sendEmail(opts);

  if (AUTO_REPLY && isEmail_(data.email)) autoReply_(data);
  return { ok: true };
}

function autoReply_(data) {
  MailApp.sendEmail({
    to: data.email,
    name: 'セブンセンシズ株式会社',
    subject: '【受付完了】お問い合わせありがとうございます',
    body: (data.name || 'ご担当') + '様\n\n'
        + 'お問い合わせいただきありがとうございます。内容を確認のうえ、2営業日以内に担当者よりご連絡いたします。\n\n'
        + 'お急ぎの場合は 06-4305-7547（9:00〜20:00 / 土日祝休）までお電話ください。\n\n'
        + '——\nセブンセンシズ株式会社\nhttps://www.7senses.co.jp\n',
  });
}

// ============================================================
// キーワード台帳
// ============================================================
function kwRows_() {
  const sh = sheet_('KW台帳');
  if (sh.getLastRow() < 2) return [];
  return sh.getRange(2, 1, sh.getLastRow() - 1, TABS['KW台帳'].length).getValues();
}

/** 次に書くべきKWを1件返す（状態が「未着手」で優先度の高い順） */
function nextKw_(site) {
  const rows = kwRows_();
  const cands = [];
  rows.forEach(function (r, i) {
    if (site && String(r[0]) !== site) return;
    if (String(r[2]).trim() !== '未着手') return;
    cands.push({ row: i + 2, site: r[0], keyword: r[1], priority: r[3] || 'B',
                 category: r[4] || '', aim: r[5] || '' });
  });
  cands.sort(function (a, b) { return String(a.priority).localeCompare(String(b.priority)); });
  const remaining = cands.length;
  if (!remaining) return { ok: true, keyword: null, remaining: 0, need_replenish: true };
  const top = cands[0];
  return { ok: true, keyword: top.keyword, category: top.category, aim: top.aim,
           site: top.site, remaining: remaining, need_replenish: remaining <= 5 };
}

/** 全サイトのKWを返す（サイト横断の重複チェック用） */
function allKw_() {
  return kwRows_().map(function (r) {
    return { site: r[0], keyword: r[1], status: r[2], url: r[9] || '' };
  });
}

function kwStatus_(site) {
  const rows = kwRows_().filter(function (r) { return !site || String(r[0]) === site; });
  const count = function (s) {
    return rows.filter(function (r) { return String(r[2]).trim() === s; }).length;
  };
  return { ok: true, site: site || 'all', total: rows.length,
           todo: count('未着手'), doing: count('執筆中'), done: count('公開済み') };
}

/** 執筆開始をマーク（同じKWを二重に書かないため） */
function claimKw_(site, keyword) {
  const sh = sheet_('KW台帳');
  const rows = kwRows_();
  for (let i = 0; i < rows.length; i++) {
    if (String(rows[i][0]) === site && String(rows[i][1]) === keyword) {
      sh.getRange(i + 2, 3).setValue('執筆中');
      sh.getRange(i + 2, 8).setValue(new Date());
      return { ok: true };
    }
  }
  return { ok: false, error: 'KWが見つかりません: ' + keyword };
}

/** KWをまとめて追加（自動補充） */
function addKw_(site, keywords) {
  const sh = sheet_('KW台帳');
  const exist = {};
  kwRows_().forEach(function (r) { exist[r[0] + '|' + r[1]] = true; });
  let added = 0;
  keywords.forEach(function (k) {
    const kw = typeof k === 'string' ? { keyword: k } : k;
    if (!kw.keyword || exist[site + '|' + kw.keyword]) return;
    sh.appendRow([site, kw.keyword, '未着手', kw.priority || 'B', kw.category || '',
                  kw.aim || '', new Date(), '', '', '', kw.note || '']);
    added++;
  });
  return { ok: true, added: added };
}

/** 公開完了の記録（KW台帳と記事作成ログの両方を更新） */
function publishLog_(b) {
  sheet_('記事作成ログ').appendRow([
    new Date(), SITES[b.site] || b.site, b.title || '', b.keyword || '', b.category || '',
    b.score || '', b.chars || '', b.url || '', b.note || '',
  ]);
  if (b.keyword) {
    const sh = sheet_('KW台帳');
    const rows = kwRows_();
    for (let i = 0; i < rows.length; i++) {
      if (String(rows[i][0]) === b.site && String(rows[i][1]) === b.keyword) {
        sh.getRange(i + 2, 3).setValue('公開済み');
        sh.getRange(i + 2, 9).setValue(new Date());
        sh.getRange(i + 2, 10).setValue(b.url || '');
        break;
      }
    }
  }
  return { ok: true };
}

function errorLog_(b) {
  sheet_('エラーログ').appendRow([
    new Date(), SITES[b.site] || b.site || '', b.phase || '', b.message || '', '', '未対応',
  ]);
  return { ok: true };
}

// ============================================================
// 共通
// ============================================================
function isEmail_(s) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(s || ''));
}

function clean_(s) {
  return String(s || '').replace(/[\r\n]+/g, ' ').slice(0, 80);
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
