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

const SHARED_SECRET = 'XXXXXXXXXXXXXXXX'; // 記事工場・フォームと共有する合言葉
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
  'AI参照': ['日付', 'サイト', '参照元', '着地ページ', 'セッション'],
  'KPIレポート': ['日付', 'サイト', 'セッション', 'PV', '表示回数', 'クリック',
                'CTR', '平均順位', 'CV', '備考'],
  'AIO計測': ['日付', 'サイト', 'AI Overview表示', 'AI参照セッション', 'ChatGPT',
             'Perplexity', 'Gemini', 'Copilot', '備考'],
  '内部リンク管理': ['設置日', 'サイト', 'リンク元', 'リンク先', 'アンカーテキスト'],
  'リライトログ': ['実施日', 'サイト', '記事', '理由', '変更概要', '前順位', '後順位', '効果'],
  'エラーログ': ['日時', 'サイト', '工程', 'エラー内容', '対応', '状態'],
  '設定': ['項目', '値', '説明'],
  // 組の違う社（お客様どうし・お客様と自社）が同じ語を持った記録。弾かずに登録し、運用者が状態を決める
  // 状態: 未確認 / 両方使う / 片方を外す（外すのは retire_kw の仕組みで行う）
  'KW重複の確認': ['日時', '語', '社A', '地域A', '社B', '地域B', '状態', '備考'],
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
    const headers = TABS[name];
    if (sh.getLastRow() === 0) {
      sh.appendRow(headers);
      sh.getRange(1, 1, 1, headers.length)
        .setFontWeight('bold').setBackground('#0b2447').setFontColor('#ffffff');
      sh.setFrozenRows(1);
    } else {
      // 列が増えたのに見出しが古いままだと、送信元ページの列に「ご相談内容」と
      // 書いてある表になる（問い合わせで実際にそうなっていた）。見出し行だけ揃える
      const cur = sh.getRange(1, 1, 1, headers.length).getValues()[0].map(String);
      if (cur.join('	') !== headers.join('	')) {
        sh.getRange(1, 1, 1, headers.length).setValues([headers])
          .setFontWeight('bold').setBackground('#0b2447').setFontColor('#ffffff');
      }
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
      case 'kw_overlaps': return json_(kwOverlaps_());
      // 同業平均（集計値だけ。LPの診断結果に「同業の平均」を出すため /api/bench が呼ぶ）
      case 'scan_bench': return json_(scanBench_());
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
      // ctx は記事工場が送る組と地域（sites.kw_context）。古い呼び出しは送らず、全社を1つの組として扱う
      case 'claim_kw':    return json_(claimKw_(body.site, body.keyword, body.ctx));
      // 書く前の食い合い審査。記事工場が Phase 1 と Phase 3 の両方で呼ぶ
      case 'kw_conflict': return json_(kwConflict_(body.site, body.keyword, null, null, body.ctx));
      case 'retire_kw':   return json_(retireKw_(body.site, body.keywords, body.reason, body.force));
      // 執筆中のまま記事が残らなかったKWを、未着手へ戻す。
      // ゲートの不具合で実行が途中で落ちると、KWだけが執筆中で取り残される
      case 'unclaim_kw':  return json_(unclaimKw_(body.site, body.keywords));
      case 'publish_log': return json_(publishLog_(body));
      case 'add_kw':      return json_(addKw_(body.site, body.keywords || [], body.ctx));
      case 'error_log':   return json_(errorLog_(body));
      case 'kpi_log':     return json_(kpiLog_(body));
      // 保守用の操作。エディタを開かなくても実行できるようにする
      // （書式の適用や定期実行の登録は、手で押すと忘れるため）
      case 'clean_inquiry': return json_(cleanInquiry_(body));
      case 'link_log':    return json_(linkLog_(body));
      case 'rewrite_log': return json_(rewriteLog_(body));
      // 直した記事の「後順位・効果」を、あとから埋める（rank_up --effect が週次で呼ぶ）
      case 'rewrite_effect': return json_(rewriteEffect_(body));
      // 救済のTODOのうち、今回出なかったものを「解消」にする（増えるだけの表を止める）
      case 'error_sync': return json_(errorSync_(body));
      case 'admin':       return json_(admin_(body.task));
      // サイトの登録。setup_from_sheet.py が呼ぶ。
      // 手で書かせると、GA4のIDだけ空のままKPIが毎朝0で埋まる
      case 'register_site': return json_(registerSite_(body));
      // 診断の記録（業種・点数・ハッシュ化したサイト・紹介元）。audit.js が合言葉つきで送る
      case 'scan_log':    return json_(scanLog_(body));
      // 取りこぼした問い合わせを台帳へ戻す（lead_reconcile で見つけ、送信履歴から復元した分）。
      // メールは送らない。フォームの経路（form_）を通すと、今になって自動返信が相手に届く
      case 'restore_lead': return json_(restoreLead_(body));
      // AI紹介チェックの回数（メールごと3回・月の全体の上限）と記録。functions/api/ai-check.js が合言葉つきで呼ぶ
      case 'ai_check_quota': return json_(aiCheckQuota_(body));
      case 'gemini_usage':   return json_(geminiUsage_());
      case 'gemini_log':     return json_(geminiLog_(body));
      case 'ai_check_stats': return json_(aiCheckStats_(body));
      case 'probe_status':   return json_(probeStatus_());
      case 'ai_check_log':   return json_(aiCheckLog_(body));
      case 'ai_recheck_list': return json_(aiRecheckList_());
      case 'ai_recheck_done': return json_(aiRecheckDone_(body));
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

/**
 * 狙う語の正規化。空白・記号・全半角のゆれを落として同一視する。
 *
 * 「aio 診断」と「aio診断」は検索エンジンからは同じ意図に見える。
 * 文字列の完全一致で重複を見ていたため、両方が台帳に入り、
 * 2記事が同じ語を狙って順位が割れた。
 */
function normKw_(s) {
  return String(s || '')
    .replace(/[Ａ-Ｚａ-ｚ０-９]/g, function (c) {
      return String.fromCharCode(c.charCodeAt(0) - 0xFEE0);
    })
    .replace(/[\s　・|｜:：\-—?？!！。、,.／\/（）()【】\[\]]/g, '')
    .toLowerCase();
}

/**
 * 重複を見る組。自社3サイトで1つ、お客様は1社で1つ（scripts/sites.py の group_key）。
 * ctx.groups を送らない呼び出し（古い記事工場・手での実行）は全社を1つの組として扱い、従来どおり弾く。
 * 台帳にあって ctx に無い社は、その社だけの組にする（hub_sheets._grp と同じ）
 */
function kwGroup_(ctx, site) {
  const g = ctx && ctx.groups;
  if (!g) return '';
  const s = String(site);
  return Object.prototype.hasOwnProperty.call(g, s) ? String(g[s]) : '?' + s;
}

function sameGroup_(ctx, a, b) {
  return kwGroup_(ctx, a) === kwGroup_(ctx, b);
}

/** 登録日の比較用の値。読めなければ「いちばん古い」扱い（既にある行を先に登録した側とみなす） */
function kwTime_(v) {
  if (v instanceof Date) return v.getTime();
  if (typeof v === 'number') return (v - 25569) * 86400000;
  const t = Date.parse(String(v || '').replace(' ', 'T'));
  return isNaN(t) ? -Infinity : t;
}

/**
 * 組の違う社が同じ語を持ったことを「KW重複の確認」に残す（同じ語・同じ2社は1行だけ）。
 * 社Aが先に登録した側。弾かないのは、地域が違えばお客様どうしで同じ語を使ってよい場合があるため。
 * どちらかを外すかは運用者が決める
 */
function noteOverlap_(keyword, first, second, ctx) {
  const sh = sheet_('KW重複の確認');
  const n = normKw_(keyword);
  const pair = [String(first), String(second)].sort().join('|');
  if (sh.getLastRow() >= 2) {
    const rows = sh.getRange(2, 1, sh.getLastRow() - 1, 6).getValues();
    for (let i = 0; i < rows.length; i++) {
      if (normKw_(rows[i][1]) === n && [String(rows[i][2]), String(rows[i][4])].sort().join('|') === pair) return false;
    }
  }
  const reg = (ctx && ctx.regions) || {};
  sh.appendRow([new Date(), keyword, first, reg[first] || '', second, reg[second] || '', '未確認',
                '社Aが先に登録。片方を外すときは retire_kw で外す側の語を対象外にする']);
  return true;
}

/** 「KW重複の確認」の行（週次の findings が未確認を要対応として知らせる） */
function kwOverlaps_() {
  const sh = sheet_('KW重複の確認');
  if (sh.getLastRow() < 2) return { ok: true, rows: [] };
  return { ok: true, rows: sh.getRange(2, 1, sh.getLastRow() - 1, 8).getValues().map(function (r) {
    return { at: r[0], keyword: r[1], site_a: r[2], region_a: r[3], site_b: r[4], region_b: r[5],
             status: String(r[6] || '').trim() || '未確認', note: r[7] || '' };
  }) };
}

/**
 * その語が既存の台帳とぶつかっていないかを返す。
 *
 * 同一サイト内の重複は順位が割れる。サイトをまたぐ重複は担当領域の侵食で、
 * グループ全体で見ると同じ語を自社2サイトで奪い合うことになる。どちらも止める。
 */
function kwConflict_(site, keyword, rows, selfRow, ctx) {
  const n = normKw_(keyword);
  if (!n) return { ok: false, error: 'キーワードが空です' };
  const same = [], cross = [], otherGroup = [];
  // rows を渡せるようにしてある。渡さないと1件ごとに台帳を読み直すことになり、
  // 未着手が数百件あるとGASの実行時間の上限に当たる。
  // selfRow は「その語自身の台帳行」。台帳から取り出したKWを審査するときは、
  // 自分の行を重複として数えてしまい、どのKWも着手できなくなる。
  (rows || kwRows_()).forEach(function (r, idx) {
    if (selfRow && idx + 2 === selfRow) return;
    const st = String(r[2]).trim();
    if (st === '対象外' || st === '取り下げ') return;   // 生きている行だけ見る
    const m = normKw_(r[1]);
    if (!m) return;
    const hit = (m === n) ? '完全一致'
      : (m.indexOf(n) === 0 || n.indexOf(m) === 0) ? '包含' : '';
    if (!hit) return;
    const rec = { site: r[0], keyword: r[1], status: st, url: r[9] || '', match: hit };
    // 組の違う社とは食い合わない（別の会社のサイト）。止めずに other_group として返す
    if (!sameGroup_(ctx, r[0], site)) { otherGroup.push(rec); return; }
    (String(r[0]) === String(site) ? same : cross).push(rec);
  });
  const level = same.length ? 2 : (cross.length ? 1 : 0);
  return { ok: true, level: level, same_site: same, other_site: cross, other_group: otherGroup,
           verdict: level === 2 ? '着手禁止（同じサイトに同じ語がある）'
             : level === 1 ? '要確認（他サイトが同じ語を持っている）' : '着手可' };
}

/** 次に書くべきKWを1件返す（状態が「未着手」で優先度の高い順） */
function nextKw_(site) {
  const rows = kwRows_();
  const cands = [];
  rows.forEach(function (r, i) {
    if (site && String(r[0]) !== site) return;
    if (String(r[2]).trim() !== '未着手') return;
    // 語が空欄・記号だけの行は候補にも残数にも数えない（hub_sheets.next_kw と同じ扱い）。
    // 数えると kwConflict_ が {ok:false} を返し、空の語を次に書く語として渡していた
    if (!normKw_(r[1])) return;
    cands.push({ row: i + 2, site: r[0], keyword: r[1], priority: r[3] || 'B',
                 category: r[4] || '', aim: r[5] || '' });
  });
  cands.sort(function (a, b) { return String(a.priority).localeCompare(String(b.priority)); });
  const remaining = cands.length;
  if (!remaining) return { ok: true, keyword: null, remaining: 0, need_replenish: true };

  // 渡す前に食い合いを確かめる。台帳に残った古い重複を、
  // そのまま次の記事のKWとして渡すと、書いたあとに気づくことになる。
  const blocked = [];
  for (let i = 0; i < cands.length; i++) {
    const c = cands[i];
    const cf = kwConflict_(c.site, c.keyword, rows, c.row);  // 台帳は使い回し、自分の行は除く
    if (cf.level === 2 || cf.ok === false) { blocked.push({ keyword: c.keyword, why: cf.verdict }); continue; }
    return { ok: true, keyword: c.keyword, category: c.category, aim: c.aim,
             site: c.site, remaining: remaining, need_replenish: remaining <= 5,
             cross_site_warning: cf.other_site, skipped_conflict: blocked };
  }
  return { ok: true, keyword: null, remaining: remaining, need_replenish: true,
           skipped_conflict: blocked,
           note: '未着手のKWはすべて既存記事と食い合います。台帳の補充が必要です' };
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

/**
 * 執筆開始をマーク（同じKWを二重に書かないため）
 *
 * ここが最後の砦。この先は本文を書く工程で、公開後に気づくと
 * 統合か削除しか残らない。既存記事と食い合う語は、ここで止める。
 */
function claimKw_(site, keyword, ctx) {
  const sh = sheet_('KW台帳');
  const rows = kwRows_();
  const n = normKw_(keyword);
  for (let i = 0; i < rows.length; i++) {
    if (String(rows[i][0]) !== site || normKw_(rows[i][1]) !== n) continue;
    // 自分の行を除いて、生きている同じ語がないか見る。止めるのは同じ組の中だけ
    const dup = [], other = [];
    rows.forEach(function (r, j) {
      if (j === i || normKw_(r[1]) !== n) return;
      const st = String(r[2]).trim();
      if (st === '対象外' || st === '取り下げ') return;
      const rec = { site: r[0], keyword: r[1], status: st, url: r[9] || '' };
      if (sameGroup_(ctx, r[0], site)) dup.push(rec);
      else other.push({ rec: rec, first: kwTime_(r[6]) <= kwTime_(rows[i][6]) });
    });
    if (dup.length) {
      return { ok: false, error: '同じ語が台帳にすでにあります。書くと順位が割れます',
               conflicts: dup };
    }
    other.forEach(function (o) {
      if (o.first) noteOverlap_(keyword, String(o.rec.site), site, ctx);
      else noteOverlap_(keyword, site, String(o.rec.site), ctx);
    });
    sh.getRange(i + 2, 3).setValue('執筆中');
    sh.getRange(i + 2, 8).setValue(new Date());
    return other.length ? { ok: true, overlaps: other.map(function (o) { return o.rec; }) } : { ok: true };
  }
  return { ok: false, error: 'KWが見つかりません: ' + keyword };
}

/**
 * 執筆中のまま記事が残らなかったKWを、未着手へ戻す。
 * 実行が途中で落ちると、記事は消えるのにKWだけが執筆中で取り残され、
 * そのKWは二度と書かれなくなる。
 */
function unclaimKw_(site, keywords) {
  const sh = sheet_('KW台帳');
  const rows = kwRows_();
  const set = {};
  (keywords || []).forEach(function (k) { set[normKw_(k)] = true; });
  let n = 0;
  for (let i = 0; i < rows.length; i++) {
    if (String(rows[i][0]) !== site || !set[normKw_(rows[i][1])]) continue;
    if (String(rows[i][2]).trim() !== '執筆中') continue;   // 公開済みは触らない
    sh.getRange(i + 2, 3).setValue('未着手');
    sh.getRange(i + 2, 8).setValue('');
    n++;
  }
  return { ok: true, unclaimed: n };
}


/** KWをまとめて追加（自動補充）。表記ゆれを吸収して重複を弾く */
function addKw_(site, keywords, ctx) {
  const sh = sheet_('KW台帳');
  // 文字列の完全一致では「aio 診断」と「aio診断」が両方通る。正規化して比べる。
  // other は同じ組の他サイト、outside は組の違う社（語ごとに社の並び）
  const exist = {}, other = {}, outside = {};
  kwRows_().forEach(function (r) {
    const st = String(r[2]).trim();
    if (st === '対象外' || st === '取り下げ') return;
    const n = normKw_(r[1]);
    if (!n) return;
    if (String(r[0]) === String(site)) exist[n] = r[1];
    else if (sameGroup_(ctx, r[0], site)) other[n] = r[0];
    else (outside[n] = outside[n] || []).push(String(r[0]));
  });
  let added = 0;
  const skipped = [], crossed = [], overlaps = [];
  keywords.forEach(function (k) {
    const kw = typeof k === 'string' ? { keyword: k } : k;
    const n = normKw_(kw.keyword);
    if (!n) return;
    if (exist[n]) { skipped.push({ keyword: kw.keyword, dup: exist[n] }); return; }
    // 同じ組の他サイトが持つ語は入れない。グループ内で同じ語を奪い合うことになる
    if (other[n]) { crossed.push({ keyword: kw.keyword, site: other[n] }); return; }
    sh.appendRow([site, kw.keyword, '未着手', kw.priority || 'B', kw.category || '',
                  kw.aim || '', new Date(), '', '', '', kw.note || '']);
    exist[n] = kw.keyword;
    added++;
    // 組の違う社（別の会社）が持つ語は入れたうえで、運用者に知らせる
    (outside[n] || []).filter(function (s, j, a) { return a.indexOf(s) === j; }).forEach(function (s) {
      noteOverlap_(kw.keyword, s, site, ctx);
      overlaps.push({ keyword: kw.keyword, site: s });
    });
  });
  return { ok: true, added: added, skipped_dup: skipped, skipped_other_site: crossed, overlaps: overlaps };
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
    // 完全一致だと表記ゆれ（「aio 診断」と「aio診断」）で公開済みにならず、未着手のまま
    // 残って同じ語がまた書かれる。claim_kw と同じく正規化して照合する
    // 完全一致の行を優先し、無ければ生きている（対象外・取り下げでない）行に当てる
    const want = normKw_(b.keyword);
    let hit = -1;
    for (let i = 0; i < rows.length; i++) {
      if (String(rows[i][0]) !== b.site || normKw_(rows[i][1]) !== want) continue;
      if (String(rows[i][1]) === b.keyword) { hit = i; break; }
      const st = String(rows[i][2]).trim();
      if (hit < 0 && st !== '対象外' && st !== '取り下げ') hit = i;
    }
    if (hit >= 0) {
      sh.getRange(hit + 2, 3).setValue('公開済み');
      sh.getRange(hit + 2, 9).setValue(new Date());
      sh.getRange(hit + 2, 10).setValue(b.url || '');
    }
  }
  return { ok: true };
}

/** 救済のTODOを同期する。今回のTODOに無い「未対応」の同じ工程の行は「解消」にする */
function errorSync_(b) {
  const sh = sheet_('エラーログ');
  const phase = String(b.phase || '').trim();
  const now = {};
  (b.messages || []).forEach(function (m) { now[String(m || '').trim()] = true; });
  if (!phase || sh.getLastRow() < 2) return { ok: true, closed: 0 };
  const rows = sh.getRange(2, 1, sh.getLastRow() - 1, 6).getValues();
  let closed = 0;
  const seen = {};                                  // 重複を止める前に積まれた同じTODOは最新の1行だけ残す
  for (let i = rows.length - 1; i >= 0; i--) {
    if (String(rows[i][2]).trim() !== phase) continue;
    if (String(rows[i][5]).trim() !== '未対応') continue;
    const msg = String(rows[i][3]).trim();
    let why = '';
    if (!now[msg]) why = '翌日の再監査で再発せず（自動）';
    else if (seen[msg]) why = '同じ内容の新しい行に集約（自動）';
    seen[msg] = true;
    if (!why) continue;
    sh.getRange(i + 2, 5).setValue(why);
    sh.getRange(i + 2, 6).setValue('解消');
    closed++;
  }
  return { ok: true, closed: closed };
}

/** リライトログの「後順位・効果」を埋める。同じサイト・記事の、後順位が空の最新行 */
function rewriteEffect_(b) {
  const sh = sheet_('リライトログ');
  if (sh.getLastRow() < 2) return { ok: true, updated: 0 };
  const rows = sh.getRange(2, 1, sh.getLastRow() - 1, 8).getValues();
  let updated = 0;
  (b.rows || []).forEach(function (r) {
    for (let i = rows.length - 1; i >= 0; i--) {
      if (String(rows[i][1]).trim() !== String(r.site || '').trim()) continue;
      if (String(rows[i][2]).trim() !== String(r.article || '').trim()) continue;
      const noAfter = String(rows[i][6] || '').trim() === '';
      const noBefore = String(rows[i][5] || '').trim() === '';
      if (!noAfter && !(noBefore && r.posBefore)) continue;   // 両方入っている行は触らない
      if (noBefore && r.posBefore) sh.getRange(i + 2, 6).setValue(r.posBefore);
      if (noAfter) {
        sh.getRange(i + 2, 7).setValue(r.posAfter || '');
        sh.getRange(i + 2, 8).setValue(r.effect || '');
      }
      updated++;
      break;
    }
  });
  return { ok: true, updated: updated };
}

function errorLog_(b) {
  // fix（対応）を捨てていた。原因だけ残しても、次に何をすればいいかが
  // 記録されず、時間が経つと本人にも分からなくなる
  // 同じ内容が「未対応」で残っていれば積まない。救済が毎日同じTODOを書き、
  // 214行が全部「未対応」で並んでいた。増えるだけの表は誰も読まない
  const sh = sheet_('エラーログ');
  const msg = String(b.message || '').trim();
  if (sh.getLastRow() > 1 && msg) {
    const rows = sh.getRange(2, 1, sh.getLastRow() - 1, 6).getValues();
    for (let i = 0; i < rows.length; i++) {
      if (String(rows[i][3]).trim() === msg && String(rows[i][2]).trim() === String(b.phase || '')
          && String(rows[i][5]).trim() === '未対応') {
        return { ok: true, skipped: 'same_open' };
      }
    }
  }
  sh.appendRow([
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
                   r.impressions || 0, r.clicks || 0, Number(r.ctr) || 0, r.position || 0,
                   r.cv || 0, r.note || '']);
    const bd = r.breakdown || {};
    // AI Overview の表示回数はAPIで取れない。CTRの歪みからの推定（ai_citation_check）を
    // 「推定」と明記して入れる。空欄のままだと計測していないように見えた
    aio.appendRow([r.date || '', siteLabel_(r.site),
                   (r.aio_est === undefined || r.aio_est === null) ? '' : r.aio_est, r.ai || 0,
                   bd.chatgpt || 0, bd.perplexity || 0, bd.gemini || 0, bd.copilot || 0,
                   r.aio_note || '']);
    // AI検索からの流入は「どのページに着地したか」が価値。0か非0かだけでは何も分からない
    (r.ai_pages || []).forEach(function (p) {
      sheet_('AI参照').appendRow([r.date || '', siteLabel_(r.site), p.source || '',
                                  p.page || '', Number(p.sessions) || 0]);
    });
    Object.keys(total).forEach(function (k) { total[k] += Number(r[k] || 0); });
  });

  writeDashboard_(total, (rows[0] && rows[0].date) || '');
  return { ok: true, rows: rows.length };
}

/** ダッシュボードを3サイト合計で書き換える（前日比つき） */
/** KPIレポート・AIO計測から、指標が全部0（または空）の行を消す。
 *  GAS側の集計がサイト一覧のGA4/GSCが空のまま毎日3本書いていた行。
 *  0の行は情報を持たず、グラフと前日比を歪めるだけ */
function cleanKpi_() {
  const out = [];
  [['KPIレポート', [2, 3, 4, 5, 8]], ['AIO計測', [3, 4, 5, 6, 7]]].forEach(function (spec) {
    const sh = sheet_(spec[0]);
    if (!sh || sh.getLastRow() < 2) { out.push(spec[0] + ': 0行'); return; }
    const rows = sh.getRange(2, 1, sh.getLastRow() - 1, 9).getValues();
    let removed = 0;
    for (let i = rows.length - 1; i >= 0; i--) {
      const zero = spec[1].every(function (c) { return !Number(rows[i][c]); });
      if (zero) { sh.deleteRow(i + 2); removed++; }
    }
    out.push(spec[0] + ': ' + removed + '行を消しました');
  });
  // CTRは文字列 '2.4%' で書かれて 0.024 に解釈されていた。クリック÷表示から入れ直す
  const kpi = sheet_('KPIレポート');
  if (kpi && kpi.getLastRow() > 1) {
    const n = kpi.getLastRow() - 1;
    const v = kpi.getRange(2, 5, n, 2).getValues();     // 表示回数, クリック
    const ctr = v.map(function (r) {
      const imp = Number(r[0]) || 0, clk = Number(r[1]) || 0;
      return [imp ? Math.round(clk / imp * 10000) / 100 : 0];
    });
    kpi.getRange(2, 7, n, 1).setValues(ctr).setNumberFormat('0.00"%"');
    out.push('CTRを' + n + '行入れ直しました');
  }
  return out.join(' / ');
}

/** ダッシュボードの行を項目名で上書きする（無ければ追加）。
 *  流入の合計（kpi_log）と台帳の集計（refreshDashboard）が同じタブを
 *  全行消して書き直し合い、最後に書いた側の項目しか残らなかった */
function upsertDashboard_(rows, note) {
  const sh = sheet_('ダッシュボード');
  const last = sh.getLastRow();
  const cur = last > 1 ? sh.getRange(2, 1, last - 1, 5).getValues() : [];
  const index = {};
  cur.forEach(function (r, i) { index[String(r[0])] = i; });
  const now = new Date();
  rows.forEach(function (r) {
    const i = index[String(r[0])];
    const before = (i === undefined) ? undefined : Number(cur[i][1]);
    const diff = (before === undefined || isNaN(before) || typeof r[1] !== 'number') ? ''
      : ((r[1] - before >= 0 ? '+' : '') + (Math.round((r[1] - before) * 10) / 10));
    const line = [r[0], r[1], diff, now, note];
    if (i === undefined) sh.appendRow(line);
    else sh.getRange(i + 2, 1, 1, 5).setValues([line]);
  });
}

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
  // 全部0の集計で上書きしない。計測に失敗した回や、設定の無い書き手が
  // 「0」を実績として残し、前日比まで壊す。実際にそれで合計が0のまま表示されていた
  const allZero = !(t.sessions || t.pv || t.cv || t.impressions || t.clicks || t.ai);
  const hadValue = Object.keys(prev).some(function (k) { return prev[k] > 0 && k.indexOf('公開記事数') < 0; });
  if (allZero && hadValue) {
    Logger.log('集計が全て0のため、ダッシュボードは更新しません（' + dateStr + '）');
    return;
  }
  const rows = [
    ['セッション（3サイト合計）', t.sessions],
    ['PV（3サイト合計）', t.pv],
    ['CV（3サイト合計）', t.cv],
    ['検索表示回数（3サイト合計）', t.impressions],
    ['検索クリック（3サイト合計）', t.clicks],
    ['AI経由セッション（3サイト合計）', t.ai],
    ['公開記事数（台帳の公開済み）', published],
  ];
  upsertDashboard_(rows, dateStr + ' 時点');
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

/**
 * 配信除外を管理しやすい形に整え、診断ログのテスト行を消す（何度呼んでも同じ結果になる）。
 * 判定に使うのは1列目だけ。B列より右は人が並べ替え・絞り込みに使う管理用の欄。
 * 診断ログは 2026-09-28 5:20〜5:21 のテスト2行（紹介元 partner-test01 を含む）だけを、中身で確かめて消す。
 */
function tidyExclude_() {
  const out = [];
  const ss = book_();
  const sh = excludeSheet_();
  const head = sh.getRange(1, 1, 1, EXCLUDE_HEAD.length).getValues()[0];
  if (head.join('|') !== EXCLUDE_HEAD.join('|')) {
    // 旧い3列（メール/メモ/追加日）の行があれば、新しい6列の位置へ移す
    const n = sh.getLastRow() - 1;
    if (n > 0 && String(head[1]) === 'メモ') {
      const old = sh.getRange(2, 1, n, 3).getValues();
      sh.getRange(2, 1, n, 6).clearContent();
      sh.getRange(2, 1, n, 6).setValues(old.map(function (r) { return [r[0], '', '', r[1], r[2], '手入力']; }));
    }
    sh.getRange(1, 1, 1, EXCLUDE_HEAD.length).setValues([EXCLUDE_HEAD]);
    out.push('配信除外の列を6列にしました');
  }
  sh.setFrozenRows(1);
  sh.getRange(1, 1, 1, EXCLUDE_HEAD.length).setFontWeight('bold').setBackground('#0b2447').setFontColor('#ffffff');
  [260, 200, 110, 320, 100, 120].forEach(function (w, i) { sh.setColumnWidth(i + 1, w); });
  sh.getRange(2, 3, 998, 1).setDataValidation(SpreadsheetApp.newDataValidation()
    .requireValueInList(['既存客', '取引先', '営業お断り', '配信停止', 'テスト'], true).setAllowInvalid(true).build());
  sh.getRange(1, 1).setNote('ここに書いたメールアドレス（例: taro@example.co.jp）かドメイン（例: example.co.jp）には、'
    + 'ステップメール・自動フォロー・測り直しのメールを送りません。問い合わせの通知は届きます。\n'
    + '判定に使うのはこの列だけです。B列より右は管理用（並べ替え・絞り込みに使えます）。\n'
    + 'gmail.com などのフリーメールはドメインで書かず、メールアドレスで書いてください（他の人まで止まるため）。\n'
    + '問い合わせシートの「対応状況」を「既存客」「契約中」「成約」にした人は、自動でここに追加されます。');
  if (!sh.getFilter()) sh.getRange(1, 1, Math.max(sh.getLastRow(), 2), EXCLUDE_HEAD.length).createFilter();
  out.push('配信除外の書式・選択肢・説明を整えました');

  const dg = ss.getSheetByName('診断ログ');
  if (dg && dg.getLastRow() >= 3) {
    const v = dg.getRange(2, 1, 2, 5).getDisplayValues();
    const isTest = v[0][0].indexOf('2026/09/28 5:20') === 0 && v[1][0].indexOf('2026/09/28 5:21') === 0 && v[1][4] === 'partner-test01';
    if (isTest) { dg.deleteRows(2, 2); out.push('診断ログのテスト2行を削除しました'); }
    else out.push('診断ログ: テスト行は見つかりません（削除済み）');
  }
  return out.join(' / ');
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
    case 'clean_kpi': return { ok: true, result: cleanKpi_() };
    case 'tidy_exclude': return { ok: true, result: tidyExclude_() };
    default:
      return { ok: false, error: '不明なtask: ' + task
               + '（format / triggers / kpi / dashboard / setup）' };
  }
}
