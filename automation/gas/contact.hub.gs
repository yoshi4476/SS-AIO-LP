/**
 * 3サイト共通のフォーム受付（管制塔GASへ同居させる）
 * ------------------------------------------------------------------
 * これまでフォームの受付は、コーポレート用に作った1つのGASを
 * 補助金サイトと共用していた。そのため補助金サイト固有の
 *   ・無料診断（type: diagnosis）
 *   ・サイト無料診断（type: site_audit）
 * が「必須項目が入力されていません」で弾かれ、動いていなかった。
 * （corp用の受付は name / email / message の3つを必須にしているが、
 *   診断フォームは message を送らないため）
 *
 * ここでは種別ごとに必要な項目を分けて判定し、リードの温度・診断結果まで
 * 1枚のスプレッドシートに記録する。通知と自動返信も種別に合わせて出し分ける。
 *
 * hub.gs と同じプロジェクトに置くこと（SHEETS/SITES/sheet_/json_ を共用する）。
 */

// 相談本文にこれらが含まれていれば、温度をWARMからHOTへ上げる
const LEAD_HOT_WORDS = ['補助金', '見積', '見積もり', '見積り', '導入', '申請',
                        '予算', '急ぎ', '至急', '締め切り', '締切'];
const LEAD_TYPE_LABELS = {
  contact: '無料相談', diagnosis: '無料診断',
  download: '資料ダウンロード', site_audit: 'サイト無料診断',
};
const DIAG_KIND_LABELS = { hojokin: 'AI補助金診断', meo: 'MEO集客診断', ai: 'AI活用診断' };
// 同じメールから24時間以内の再送信は、新しい行を作らず既存行に追記する
const LEAD_DUP_WINDOW_MS = 24 * 60 * 60 * 1000;

/**
 * フォーム受付の入口。hub.gs の doPost から、action が無いときに呼ばれる。
 * @param {Object} body  { site, type, name, email, ... } もしくは { data: {...} }
 */
function form_(body) {
  // 転送（forwardToHub_）は data の中に入れて送ってくる。直接送信は平置き。
  const d = body.data && Object.keys(body.data).length ? body.data : body;
  const type = String(d.type || 'contact');
  const site = siteLabel_(body.site || d.site) || '（不明）';
  const name = clean_(d.name);
  const email = clean_(d.email);

  if (d.website) return { ok: true };            // 隠しフィールド＝Bot

  // 種別ごとに必要な項目が違う。診断は本文を書かせないため message を求めない。
  if (!email || !isEmail_(email)) {
    return { ok: false, error: 'メールアドレスの形式をご確認ください。' };
  }
  if (type === 'contact' && (!name || !body_(d.message))) {
    return { ok: false, error: '必須項目が入力されていません。' };
  }
  if ((type === 'diagnosis' || type === 'site_audit') && !name) {
    return { ok: false, error: 'お名前をご入力ください。' };
  }

  const temp = leadTemp_(type, d.message, d, body.referer || d.referer || '');
  const row = leadSave_(site, type, temp, d, body.referer || d.referer || '');
  const silent = body.silent === true || body.silent === 'true';
  // 記録は済んでいる。メールで失敗しても、送信者にはエラーを返さない。
  // ここで例外を投げると、問い合わせが届いていないと誤解される。
  const warn = [];
  if (!silent) {
    try {
      leadNotify_(site, type, temp, d, body.referer || d.referer || '');
    } catch (err) {
      warn.push('通知メール: ' + err);
    }
    try {
      leadReply_(site, type, d);
    } catch (err) {
      warn.push('自動返信: ' + err);
    }
  }
  if (warn.length) {
    console.error('メール送信に失敗（記録は済んでいます）: ' + warn.join(' / '));
    try {
      sheet_('エラーログ').appendRow([new Date(), site, 'メール送信', warn.join(' / '), '未対応']);
    } catch (e2) {}
  }
  return { ok: true, temperature: temp, row: row };
}

/** リードの温度。診断とサイト診断は、自社の情報を差し出しているので高く見る */
// 流入経路で温度を1段上げる。料金・サービス・診断・費用系の記事から来た人は、
// 「相談」と書いていなくても導入を検討している
const LEAD_HOT_PATHS = /\/lp\b|\/service|\/diagnosis|\/price|\/plan|hiyou|souba|daikou|gaichuu|contact/i;

function leadTemp_(type, message, d, referer) {
  if (type === 'diagnosis' || type === 'site_audit') return 'HOT';
  let level = 0;                                   // 0=COOL 1=WARM 2=HOT
  if (type === 'contact') {
    const msg = String(message || '');
    level = LEAD_HOT_WORDS.some(function (w) { return msg.indexOf(w) !== -1; }) ? 2 : 1;
  }
  // 会社名と電話番号の両方がある＝連絡を受ける前提で書いている
  if (d && clean_(d.company) && clean_(d.tel || d.phone)) level++;
  if (referer && LEAD_HOT_PATHS.test(String(referer))) level++;
  return ['COOL', 'WARM', 'HOT'][Math.min(level, 2)];
}

/** 「問い合わせ」タブへ記録する。24時間以内の同一メールは既存行にまとめる */
function leadSave_(site, type, temp, d, referer) {
  const sh = sheet_('問い合わせ');
  const email = clean_(d.email);
  const now = new Date();

  const last = sh.getLastRow();
  if (last > 1) {
    const vals = sh.getRange(2, 1, last - 1, 7).getValues();
    for (let i = vals.length - 1; i >= 0; i--) {
      const t = vals[i][0];
      if (String(vals[i][6]).toLowerCase() !== email.toLowerCase()) continue;
      if (!(t instanceof Date) || now - t > LEAD_DUP_WINDOW_MS) break;
      // 既存行の「その他項目」へ追記する（別々の行にすると同一人物と分からない）
      // 追記先は「診断・詳細」(10列目)。13列目は温度なので上書きしてはいけない。
      const r = i + 2;
      const RANK = { HOT: 3, WARM: 2, COOL: 1 };
      const before = String(sh.getRange(r, 13).getValue() || '');
      // 診断を出した人が後から相談してきたときに、温度が下がらないようにする
      if ((RANK[temp] || 0) > (RANK[before] || 0)) sh.getRange(r, 13).setValue(temp);
      const cur = String(sh.getRange(r, 10).getValue() || '');
      sh.getRange(r, 10).setValue(
        (cur ? cur + '\n' : '') + Utilities.formatDate(now, 'Asia/Tokyo', 'MM/dd HH:mm')
        + ' 再送信(' + (LEAD_TYPE_LABELS[type] || type) + ') ' + leadDetail_(type, d));
      return r;
    }
  }

  sh.appendRow([
    now, site, LEAD_TYPE_LABELS[type] || type, clean_(d.company), clean_(d.name), '',
    email, clean_(d.tel || d.phone), body_(d.message || d.body),
    // AI集客ラボは referer を body の外側に載せて送る。d.referer だけ見ると空欄になる
    leadDetail_(type, d), '', clean_(referer || d.referer), temp, '未対応',
  ]);
  return sh.getLastRow();
}

/** 診断・監査の結果を1つの文字列にまとめる（列を増やさず後から読める形にする） */
function leadDetail_(type, d) {
  if (type === 'diagnosis' && d.diagnosis) {
    const g = d.diagnosis;
    const parts = [DIAG_KIND_LABELS[g.kind] || g.kind || '診断'];
    if (g.total !== undefined) parts.push('総合 ' + g.total + '/100');
    if (g.grade) parts.push('判定 ' + g.grade);
    if (g.scores) {
      for (const k in g.scores) parts.push(k + ':' + g.scores[k]);
    }
    return parts.join(' / ');
  }
  if (type === 'site_audit' && d.audit) {
    const a = d.audit;
    return ['対象 ' + (a.url || ''), '総合 ' + (a.total || '') + '/100',
            a.grade ? '判定 ' + a.grade : ''].filter(String).join(' / ');
  }
  const known = ['type', 'site', 'name', 'company', 'email', 'tel', 'phone',
                 'message', 'body', 'referer', 'website', 'ts', 'formKey'];
  return Object.keys(d)
    .filter(function (k) { return known.indexOf(k) < 0 && k.charAt(0) !== '_'; })
    .map(function (k) { return k + ': ' + JSON.stringify(d[k]); }).join(' / ');
}

/**
 * 相談内容など、長い本文のためのもの。
 *
 * clean_() は件名や会社名のための関数で、改行を空白に潰して80字で切る。
 * これを相談内容にも使っていたため、**届いた相談が80字で切れていた**。
 * 実際に「インド人新卒採用支援サービスを…検索され」でちょうど80字で途切れた
 * 問い合わせが届き、続きが読めなかった。台帳にも切れたまま保存されていた。
 *
 * 本文は改行が意味を持つ。潰さずに残す。長さの上限は、送信側
 * （functions/api/lead.js）が 2000字で切っているので、それを超える値にして
 * ここでは実質切らない。ただし無制限にはしない（壊れた入力で台帳が壊れるため）。
 */
function body_(s) {
  return String(s == null ? '' : s)
    .replace(/\r\n?/g, '\n')      // 改行コードを揃える。改行自体は残す
    .replace(/\u0000/g, '')       // 制御文字だけ落とす
    .slice(0, 5000)
    .trim();
}

/** 社内向けの通知。温度を件名に出して、見た瞬間に優先度が分かるようにする */
function leadNotify_(site, type, temp, d, referer) {
  const tag = { HOT: '🔥【HOT】', WARM: '🌤【WARM】', COOL: '❄️【COOL】' }[temp] || '';
  const label = LEAD_TYPE_LABELS[type] || type;
  const lines = ['サイト: ' + site, '種別: ' + label, '温度: ' + temp, '',
                 '会社・店舗: ' + clean_(d.company), 'お名前: ' + clean_(d.name),
                 'メール: ' + clean_(d.email), '電話: ' + clean_(d.tel || d.phone), ''];
  if (body_(d.message)) lines.push('ご相談内容:', body_(d.message), '');
  const detail = leadDetail_(type, d);
  if (detail) lines.push('詳細: ' + detail, '');
  lines.push('送信元: ' + (referer || '不明'),
             '台帳: ' + book_().getUrl());

  const opts = {
    to: NOTIFY_TO,
    subject: tag + '【' + site.split(' ')[0] + '】' + label + ': '
           + clean_(d.company) + ' ' + clean_(d.name) + '様',
    body: lines.join('\n'),
  };
  if (isEmail_(d.email)) opts.replyTo = clean_(d.email);
  MailApp.sendEmail(opts);
  // HOTは待たせない。スクリプトのプロパティに SLACK_WEBHOOK_URL があればSlackにも送る
  if (temp === 'HOT') {
    try {
      const hook = PropertiesService.getScriptProperties().getProperty('SLACK_WEBHOOK_URL');
      if (hook) {
        UrlFetchApp.fetch(hook, { method: 'post', contentType: 'application/json',
          payload: JSON.stringify({ text: opts.subject + '\n' + lines.join('\n') }),
          muteHttpExceptions: true });
      }
    } catch (e) { Logger.log('Slack通知に失敗: ' + e); }
  }
}

/** 送信者への自動返信。種別ごとに文面を変える */
function leadReply_(site, type, d) {
  const email = clean_(d.email);
  if (!isEmail_(email)) return;
  const name = clean_(d.name) || 'ご担当者';
  const foot = ['', '─────────────', 'セブンセンシズ株式会社',
                '〒537-0003 大阪府大阪市東成区神路1丁目7-4 コンフォートビル901・902',
                'TEL 06-4305-7547 / info.ai@7senses.co.jp', ''].join('\n');
  let subject = 'お問い合わせありがとうございます';
  let body = '';

  if (type === 'diagnosis' && d.diagnosis) {
    const g = d.diagnosis;
    subject = '【診断結果】' + (DIAG_KIND_LABELS[g.kind] || '無料診断') + 'のご回答ありがとうございます';
    const rows = [];
    if (g.scores) {
      for (const k in g.scores) rows.push('  ' + k + ': ' + g.scores[k] + ' / 100');
    }
    body = [name + ' 様', '', 'このたびは無料診断にご回答いただきありがとうございます。',
            '結果をお送りします。', '',
            '総合スコア: ' + (g.total !== undefined ? g.total + ' / 100' : '算出中'),
            g.grade ? '判定: ' + g.grade : '', '',
            rows.length ? '項目別' : '', rows.join('\n'), '',
            '結果の読み解きや、次に何から着手すべきかのご相談は無料で承っています。',
            'このメールにご返信ください。3営業日以内にご連絡します。'].filter(function (x) {
      return x !== '';
    }).join('\n');
  } else if (type === 'site_audit' && d.audit) {
    const a = d.audit;
    subject = '【診断結果】サイト無料診断のご依頼ありがとうございます';
    body = [name + ' 様', '', 'サイト無料診断のご依頼をいただきありがとうございます。', '',
            '対象URL: ' + (a.url || ''),
            '総合スコア: ' + (a.total !== undefined ? a.total + ' / 100' : '算出中'),
            a.grade ? '判定: ' + a.grade : '', '',
            '詳細な改善点は、担当より3営業日以内にご連絡します。'].filter(function (x) {
      return x !== '';
    }).join('\n');
  } else {
    body = [name + ' 様', '', 'お問い合わせいただきありがとうございます。',
            '内容を確認のうえ、3営業日以内に担当よりご連絡します。', '',
            'なお、こちらのメールは自動送信です。', ''].join('\n');
  }
  // 返信を待つ間に、判断に必要な材料を先に渡す（商談化を機械が進める）。
  // 載せるのは公開済みのものだけ。個別の見積りや約束は人が書く
  const materials = ['', '▼ ご連絡までの間にご覧いただける資料',
    '・なぜ今AI検索対策なのか（PR動画・約21分）',
    '  https://ai.7senses.co.jp/videos/aio-pr.mp4',
    '・運用の実態（システムの画面そのまま・約14分）',
    '  https://ai.7senses.co.jp/videos/console-demo.mp4',
    '・提案資料の説明動画（約18分）',
    '  https://ai.7senses.co.jp/videos/doc-guide.mp4',
    '・サービス案内と無料診断',
    '  https://ai.7senses.co.jp/lp/', ''].join('\n');
  // 診断は「弱かった項目にまず効く記事」を3本添える。対応表はサイトのビルドが
  // /data/reco.json に出す（記事が増えれば自動で新しくなる）。取れなければ何も足さない
  let reco = '';
  if (type === 'diagnosis' && d.diagnosis) {
    try {
      const map = JSON.parse(UrlFetchApp.fetch('https://ai.7senses.co.jp/data/reco.json',
                                               { muteHttpExceptions: true }).getContentText());
      const rows = map[String(d.diagnosis.kind || '')] || [];
      if (rows.length) {
        reco = ['', '▼ 結果を踏まえて、まず読んでいただきたい記事']
          .concat(rows.slice(0, 3).map(function (r) { return '・' + r.title + '\n  ' + r.url; }))
          .concat(['']).join('\n');
      }
    } catch (e) {}
  }
  MailApp.sendEmail({ to: email, subject: subject, body: body + reco + materials + foot,
                      name: 'セブンセンシズ株式会社', replyTo: NOTIFY_TO });
}

/**
 * リード温度別の自動フォロー（時間トリガーで毎日）。
 * HOT は翌日、WARM は3日後に1通だけ。COOL は送らない。対応状況が「未対応」のままの行だけ。
 * 送ったら15列目（フォロー）に日付を書き、二度は送らない。内容は公開済みの資料だけ。
 * 有効化: installFollowUpTrigger を1回実行する（毎日 09:00 に followUp が動く）
 */
const FOLLOW_COL = 15;
const FOLLOW_AFTER_DAYS = { HOT: 1, WARM: 3 };

function followUp() {
  const sh = sheet_('問い合わせ');
  const last = sh.getLastRow();
  if (last < 2) return;
  const vals = sh.getRange(2, 1, last - 1, FOLLOW_COL).getValues();
  const now = new Date();
  let sent = 0;
  for (let i = 0; i < vals.length; i++) {
    const r = vals[i];
    const at = r[0] instanceof Date ? r[0] : new Date(r[0]);
    const temp = String(r[12] || '').toUpperCase();
    const status = String(r[13] || '');
    const done = String(r[FOLLOW_COL - 1] || '');
    const email = String(r[6] || '');
    const wait = FOLLOW_AFTER_DAYS[temp];
    if (!wait || done || status !== '未対応' || !isEmail_(email)) continue;
    if ((now - at) / 86400000 < wait || (now - at) / 86400000 > wait + 7) continue;
    const name = String(r[4] || '') || 'ご担当者';
    const body = [name + ' 様', '',
      '先日はお問い合わせいただきありがとうございます。担当からのご連絡が行き違いになっていましたら申し訳ありません。', '',
      'ご都合の良い曜日・時間帯をこのメールにご返信いただければ、担当が合わせてご連絡します。', '',
      '▼ お待ちいただく間にご覧いただける資料',
      '・なぜ今AI検索対策なのか（PR動画・約21分）', '  https://ai.7senses.co.jp/videos/aio-pr.mp4',
      '・運用の実態（システムの画面そのまま・約14分）', '  https://ai.7senses.co.jp/videos/console-demo.mp4',
      '・サービス案内と無料診断', '  https://ai.7senses.co.jp/lp/', '',
      '─────────────', 'セブンセンシズ株式会社', 'TEL 06-4305-7547 / info.ai@7senses.co.jp', ''].join('\n');
    try {
      MailApp.sendEmail({ to: email, subject: 'ご相談内容の確認とご案内（セブンセンシズ株式会社）',
                          body: body, name: 'セブンセンシズ株式会社', replyTo: NOTIFY_TO });
      sh.getRange(i + 2, FOLLOW_COL).setValue(Utilities.formatDate(now, 'Asia/Tokyo', 'yyyy-MM-dd') + ' ' + temp);
      sent++;
    } catch (e) {
      console.error('フォロー送信に失敗: ' + e);
    }
  }
  console.log('フォロー送信: ' + sent + '件');
}

function installFollowUpTrigger() {
  const has = ScriptApp.getProjectTriggers().some(function (t) { return t.getHandlerFunction() === 'followUp'; });
  if (has) { console.log('followUp のトリガーは既にあります'); return; }
  ScriptApp.newTrigger('followUp').timeBased().everyDays(1).atHour(9).create();
  console.log('followUp を毎日 09:00 に動かすトリガーを作りました');
}

/**
 * メール送信の権限を承認するための関数。
 *
 * setup を実行しても承認画面は出ない。スプレッドシート操作しか使っておらず、
 * その権限は既に承認済みだから。MailApp を実際に呼ぶこの関数を実行して初めて
 * 「メールの送信」の承認が求められる。
 *
 * 使い方: Apps Script エディタの関数一覧からこれを選んで実行する。
 *         承認画面が出たら許可する。テストメールが1通届けば完了。
 */
function メール権限を承認する() {
  const to = NOTIFY_TO;
  MailApp.sendEmail({
    to: to,
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
  console.log('テストメールを ' + to + ' へ送りました。届いていれば承認は完了です。');
}
