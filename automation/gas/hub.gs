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
// 台帳として使うスプレッドシート。
// このGASは別のスプレッドシートに紐づいているため、getActiveSpreadsheet() だと
// 意図しない先に書き込む。IDで固定して、どこに書くかを一意にする。
// 空にすると、紐づいているスプレッドシート（従来どおり）を使う。
const BOOK_ID = '1ew-xG28Nd-jWSorqGgwYmHoV-DCwUtI40bRH2Y4IDOQ';

/** 台帳の本体を返す。以降 getActiveSpreadsheet() は直接使わない */
function book_() {
  return BOOK_ID ? SpreadsheetApp.openById(BOOK_ID) : SpreadsheetApp.getActiveSpreadsheet();
}

const SHARED_SECRET = 'vPwJAYWcenPoAUBx7TQFEufmjF5qpplc'; // 記事工場・フォームと共有する合言葉
const NOTIFY_TO = 'info.ai@7senses.co.jp';                // 問い合わせ通知の宛先
const AUTO_REPLY = false;                                  // true にすると送信者へ自動返信
// ────────────────────────────────────

/**
 * サイトの一覧は「サイト一覧」タブが正。ここに書くと、別の会社へ移したときに
 * 使わないサイトを集計しにいって毎朝失敗する。しかも失敗はログの中だけで、
 * 表からは気づけない。
 * 返す形: { 'site-id': { name, domain, ga4, gsc, label } }
 */
function siteMap_() {
  const sh = book_().getSheetByName('サイト一覧');
  const out = {};
  if (!sh || sh.getLastRow() < 2) return out;
  sh.getRange(2, 1, sh.getLastRow() - 1, 8).getValues().forEach(function (r) {
    const id = String(r[0] || '').trim();
    if (!id) return;
    const name = String(r[1] || id).trim();
    const dom = String(r[2] || '').trim();
    out[id] = {
      name: name, domain: dom,
      ga4: String(r[6] || '').trim(),
      gsc: String(r[7] || '').trim() || (dom ? 'https://' + dom + '/' : ''),
      label: dom ? name + ' (' + dom + ')' : name,
    };
  });
  return out;
}

/** 台帳に出す表示名。未登録のサイトはIDのまま出す（消さずに気づけるように） */
function siteLabel_(id) {
  const m = siteMap_()[id];
  return m ? m.label : (id || '');
}

const TABS = {
  'ダッシュボード': ['指標', '値', '前日比', '更新日時', '備考'],
  'サイト一覧': ['サイトID', 'サイト名', 'ドメイン', 'テーマ', '公開記事数', '最終公開日',
                'GA4プロパティID', 'Search ConsoleのURL'],
  '問い合わせ': ['受信日時', 'サイト', '種別', '会社名', 'お名前', 'ご担当者様',
                'メールアドレス', '電話番号', 'ご相談内容', '診断・詳細', '特典',
                '送信元ページ', '温度', '対応状況'],
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

/**
 * 立ち上げのときに、この関数だけを1回実行する。
 *
 * メール送信とトリガー登録は、本人が画面で承認したときにしか許可されない。
 * APIからは実行できないため、ここだけ手作業が残る。
 * 3つに分けると実行漏れが起き、問い合わせに気づけない・ダッシュボードが
 * 空のままといった形で、あとから分かりにくい壊れ方をする。
 */
function 初期設定() {
  const log = [];
  try {
    setup();
    log.push('○ タブを作りました');
  } catch (e) {
    log.push('× タブの作成に失敗: ' + e.message);
  }
  try {
    formatBook();
    log.push('○ 幅と色を整えました');
  } catch (e) {
    log.push('- 見た目の調整は飛ばしました（' + e.message + '）');
  }
  try {
    authorizeMail();
    log.push('○ メール送信を承認しました');
  } catch (e) {
    log.push('× メール送信の承認に失敗: ' + e.message);
  }
  try {
    installTriggers();
    log.push('○ 毎朝の集計を登録しました');
  } catch (e) {
    log.push('× 集計の登録に失敗: ' + e.message);
  }
  const msg = log.join('\n');
  Logger.log(msg);
  try {
    SpreadsheetApp.getUi().alert('初期設定', msg, SpreadsheetApp.getUi().ButtonSet.OK);
  } catch (e) {
    // エディタから実行したときは画面が無い。ログに出ていればよい
  }
  return msg;
}

function setup() {
  const ss = book_();
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

  // サイト一覧は空のまま作る。
  // setup_from_sheet.py が register_site で登録する。ここにサイトIDを
  // 直接書くと、別の会社でも使わない行が残り、KPIがその行を集めにいって
  // 毎朝失敗する（しかも失敗はログの中だけで、表からは気づけない）。

  // 既定シート「シート1」が空なら削除して見た目を整える
  const first = ss.getSheetByName('シート1') || ss.getSheetByName('Sheet1');
  if (first && first.getLastRow() === 0 && ss.getSheets().length > 1) ss.deleteSheet(first);

  book_().toast('11タブの準備が完了しました', '管制塔セットアップ', 5);
}

function sheet_(name) {
  const ss = book_();
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
  // 記事工場からの操作（action あり）は合言葉を必須にする。
  // 各サイトのフォームは合言葉を持たない（ブラウザのJSに書けば誰でも読めるため）。
  // フォームは action を持たないので、その場合だけ合言葉を求めない。
  // 転送（forwardToHub_）は合言葉を付けてくるので、あれば照合する。
  const hasAction = !!body.action;
  if (SHARED_SECRET && (hasAction || body.secret) && body.secret !== SHARED_SECRET) {
    return json_({ ok: false, error: 'unauthorized' });
  }
  try {
    switch (body.action) {
      case 'claim_kw':    return json_(claimKw_(body.site, body.keyword));
      case 'retire_kw':   return json_(retireKw_(body.site, body.keywords, body.reason, body.force));
      case 'publish_log': return json_(publishLog_(body));
      case 'add_kw':      return json_(addKw_(body.site, body.keywords || []));
      case 'error_log':   return json_(errorLog_(body));
      case 'kpi_log':     return json_(kpiLog_(body));
      // 保守用の操作。エディタを開かなくても実行できるようにする
      // （書式の適用や定期実行の登録は、手で押すと忘れるため）
      case 'clean_inquiry': return json_(cleanInquiry_(body));
      case 'link_log':    return json_(linkLog_(body));
      case 'rewrite_log': return json_(rewriteLog_(body));
      case 'admin':       return json_(admin_(body.task));
      // サイトの登録。setup_from_sheet.py が呼ぶ。
      // 手で書かせると、GA4のIDだけ空のままKPIが毎朝0で埋まる
      case 'register_site': return json_(registerSite_(body));
      // 各サイトのフォームは action を持たない。種別ごとに必要項目が違うため、
      // 判定と記録は contact.hub.gs の form_() にまとめている。
      default:            return json_(form_(body));
    }
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

// ============================================================
// 問い合わせ受付
// ============================================================




/** サイトを「サイト一覧」に登録する。同じIDがあれば上書きする */
function registerSite_(b) {
  const id = String(b.id || '').trim();
  if (!id) return { ok: false, error: 'id が必要です' };
  const sh = sheet_('サイト一覧');
  const row = [id, b.name || id, b.domain || '', b.theme || '', 0, '',
               b.ga4 || '', b.gsc || (b.domain ? 'https://' + b.domain + '/' : '')];
  const last = sh.getLastRow();
  if (last >= 2) {
    const ids = sh.getRange(2, 1, last - 1, 1).getValues();
    for (let i = 0; i < ids.length; i++) {
      if (String(ids[i][0]).trim() === id) {
        sh.getRange(i + 2, 1, 1, row.length).setValues([row]);
        return { ok: true, updated: id };
      }
    }
  }
  sh.appendRow(row);
  return { ok: true, added: id };
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

/** 全サイトのKWを返す（サイト横断の重複チェック・領域侵食チェック用） */
function allKw_() {
  return kwRows_().map(function (r) {
    return { site: r[0], keyword: r[1], status: r[2], priority: r[3] || 'B',
             category: r[4] || '', aim: r[5] || '', url: r[9] || '' };
  });
}

/** 担当領域の違うKWを取り下げる（状態を「対象外」にして書かせない） */
function retireKw_(site, keywords, reason, force) {
  const sh = sheet_('KW台帳');
  const rows = kwRows_();
  const set = {};
  (keywords || []).forEach(function (k) { set[k] = true; });
  let n = 0;
  for (let i = 0; i < rows.length; i++) {
    if (String(rows[i][0]) !== site || !set[String(rows[i][1])]) continue;
    // 公開済みは既定で触らない（誤って生きている記事を落とさないため）。
    // ただし実際に取り下げた記事は台帳も現況に合わせる必要があるため、
    // force 指定時だけ「取り下げ」にする。反映しないと本数を過大に報告する。
    if (String(rows[i][2]).trim() === '公開済み') {
      if (!force) continue;
      sh.getRange(i + 2, 3).setValue('取り下げ');
      sh.getRange(i + 2, 11).setValue(reason || 'サイトから取り下げ');
      n++;
      continue;
    }
    sh.getRange(i + 2, 3).setValue('対象外');
    sh.getRange(i + 2, 11).setValue(reason || '担当領域が異なるため取り下げ');
    n++;
  }
  return { ok: true, retired: n };
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
    new Date(), siteLabel_(b.site), b.title || '', b.keyword || '', b.category || '',
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
  // fix（対応）を捨てていた。原因だけ残しても、次に何をすればいいかが
  // 記録されず、時間が経つと本人にも分からなくなる
  sheet_('エラーログ').appendRow([
    new Date(), siteLabel_(b.site) || '', b.phase || '', b.message || '',
    b.fix || '', b.status || '未対応',
  ]);
  return { ok: true };
}

/**
 * KPIの受け取り（集計はGitHub Actions側のPythonが行う）
 *
 * Search Console API は Apps Script の追加サービスに存在しないため、
 * GA4/GSCからの取得はサービスアカウントを持つPython側に任せ、
 * ここは受け取って台帳に書くだけにしている。
 * body.rows = [{site, date, sessions, pv, cv, impressions, clicks, ctr, position, ai, breakdown}]
 */
function kpiLog_(b) {
  const rows = b.rows || [];
  const kpi = sheet_('KPIレポート');
  const aio = sheet_('AIO計測');
  const total = { sessions: 0, pv: 0, cv: 0, impressions: 0, clicks: 0, ai: 0 };

  rows.forEach(function (r) {
    kpi.appendRow([r.date || '', siteLabel_(r.site), r.sessions || 0, r.pv || 0,
                   r.impressions || 0, r.clicks || 0, (r.ctr || 0) + '%', r.position || 0,
                   r.cv || 0, r.note || '']);
    const bd = r.breakdown || {};
    aio.appendRow([r.date || '', siteLabel_(r.site), '', r.ai || 0,
                   bd.chatgpt || 0, bd.perplexity || 0, bd.gemini || 0, bd.copilot || 0, '']);
    Object.keys(total).forEach(function (k) { total[k] += Number(r[k] || 0); });
  });

  writeDashboard_(total, (rows[0] && rows[0].date) || '');
  return { ok: true, rows: rows.length };
}

/** ダッシュボードを3サイト合計で書き換える（前日比つき） */
function writeDashboard_(t, dateStr) {
  const sh = sheet_('ダッシュボード');
  const prev = {};
  if (sh.getLastRow() > 1) {
    sh.getRange(2, 1, sh.getLastRow() - 1, 2).getValues().forEach(function (r) {
      prev[r[0]] = Number(r[1]) || 0;
    });
  }
  const published = kwRows_().filter(function (r) {
    return String(r[2]).trim() === '公開済み';
  }).length;
  const rows = [
    ['セッション（3サイト合計）', t.sessions],
    ['PV（3サイト合計）', t.pv],
    ['CV（3サイト合計）', t.cv],
    ['検索表示回数（3サイト合計）', t.impressions],
    ['検索クリック（3サイト合計）', t.clicks],
    ['AI経由セッション（3サイト合計）', t.ai],
    ['公開記事数（台帳の公開済み）', published],
  ];
  if (sh.getLastRow() > 1) sh.deleteRows(2, sh.getLastRow() - 1);
  rows.forEach(function (r) {
    const before = prev[r[0]];
    const diff = (before === undefined) ? '' : (r[1] - before >= 0 ? '+' : '') + (r[1] - before);
    sh.appendRow([r[0], r[1], diff, new Date(), dateStr + ' 時点']);
  });
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

/**
 * メール送信の権限を承認する。
 *
 * 関数の選択欄には、いま開いているファイルの関数しか出てこない。
 * 承認作業でファイルを切り替えさせるのは分かりにくいので、
 * 最初に開かれる「コード」側にも置いておく。
 *
 * 使い方: 関数一覧から authorizeMail を選んで実行し、承認画面で許可する。
 *         テストメールが1通届けば完了。
 */
function authorizeMail() {
  MailApp.sendEmail({
    to: NOTIFY_TO,
    subject: '【設定確認】メール送信の権限が有効になりました',
    body: [
      'このメールが届いていれば、管制塔からの通知メールが使えるようになっています。',
      '',
      'これ以降、次のメールが自動で送られます。',
      '  ・問い合わせ / 無料診断 / サイト無料診断 の受信通知（社内向け）',
      '  ・送信者への自動返信（診断は結果つき）',
      '',
      '台帳: ' + book_().getUrl(),
    ].join('\n'),
  });
  console.log('テストメールを ' + NOTIFY_TO + ' へ送りました。届いていれば承認は完了です。');
}

// ============================================================
// 保守（合言葉つきで外から呼ぶ）
// ============================================================
function admin_(task) {
  switch (task) {
    case 'format':    return { ok: true, result: formatBook() };
    case 'triggers':  return { ok: true, result: installTriggers() };
    case 'kpi':       return { ok: true, result: updateKpi() };
    case 'dashboard': return { ok: true, result: refreshDashboard() };
    case 'setup':     setup(); return { ok: true, result: 'タブを整えました' };
    default:
      return { ok: false, error: '不明なtask: ' + task
               + '（format / triggers / kpi / dashboard / setup）' };
  }
}
