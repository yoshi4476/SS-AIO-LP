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
  const site = SITES[body.site || d.site] || body.site || d.site || '（不明）';
  const name = clean_(d.name);
  const email = clean_(d.email);

  if (d.website) return { ok: true };            // 隠しフィールド＝Bot

  // 種別ごとに必要な項目が違う。診断は本文を書かせないため message を求めない。
  if (!email || !isEmail_(email)) {
    return { ok: false, error: 'メールアドレスの形式をご確認ください。' };
  }
  if (type === 'contact' && (!name || !clean_(d.message))) {
    return { ok: false, error: '必須項目が入力されていません。' };
  }
  if ((type === 'diagnosis' || type === 'site_audit') && !name) {
    return { ok: false, error: 'お名前をご入力ください。' };
  }

  const temp = leadTemp_(type, d.message);
  const row = leadSave_(site, type, temp, d);
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
function leadTemp_(type, message) {
  if (type === 'diagnosis' || type === 'site_audit') return 'HOT';
  if (type === 'contact') {
    const msg = String(message || '');
    return LEAD_HOT_WORDS.some(function (w) { return msg.indexOf(w) !== -1; }) ? 'HOT' : 'WARM';
  }
  return 'COOL';
}

/** 「問い合わせ」タブへ記録する。24時間以内の同一メールは既存行にまとめる */
function leadSave_(site, type, temp, d) {
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
      const r = i + 2;
      const cur = String(sh.getRange(r, 13).getValue() || '');
      sh.getRange(r, 13).setValue(
        (cur ? cur + '\n' : '') + Utilities.formatDate(now, 'Asia/Tokyo', 'MM/dd HH:mm')
        + ' 再送信(' + (LEAD_TYPE_LABELS[type] || type) + ') ' + leadDetail_(type, d));
      return r;
    }
  }

  sh.appendRow([
    now, site, LEAD_TYPE_LABELS[type] || type, clean_(d.company), clean_(d.name), '',
    email, clean_(d.tel || d.phone), clean_(d.message || d.body),
    leadDetail_(type, d), '', clean_(d.referer), temp, '未対応',
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

/** 社内向けの通知。温度を件名に出して、見た瞬間に優先度が分かるようにする */
function leadNotify_(site, type, temp, d, referer) {
  const tag = { HOT: '🔥【HOT】', WARM: '🌤【WARM】', COOL: '❄️【COOL】' }[temp] || '';
  const label = LEAD_TYPE_LABELS[type] || type;
  const lines = ['サイト: ' + site, '種別: ' + label, '温度: ' + temp, '',
                 '会社・店舗: ' + clean_(d.company), 'お名前: ' + clean_(d.name),
                 'メール: ' + clean_(d.email), '電話: ' + clean_(d.tel || d.phone), ''];
  if (clean_(d.message)) lines.push('ご相談内容:', clean_(d.message), '');
  const detail = leadDetail_(type, d);
  if (detail) lines.push('詳細: ' + detail, '');
  lines.push('送信元: ' + (referer || '不明'),
             '台帳: ' + SpreadsheetApp.getActiveSpreadsheet().getUrl());

  const opts = {
    to: NOTIFY_TO,
    subject: tag + '【' + site.split(' ')[0] + '】' + label + ': '
           + clean_(d.company) + ' ' + clean_(d.name) + '様',
    body: lines.join('\n'),
  };
  if (isEmail_(d.email)) opts.replyTo = clean_(d.email);
  MailApp.sendEmail(opts);
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
  MailApp.sendEmail({ to: email, subject: subject, body: body + foot,
                      name: 'セブンセンシズ株式会社', replyTo: NOTIFY_TO });
}
