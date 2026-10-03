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
  // 本文の項目名はサイトごとに違う（コーポレートは detail）。message に寄せないと
  // 転送された問い合わせが「必須項目が入力されていません」で弾かれ、台帳に残らなかった
  if (!body_(d.message)) d.message = d.detail || d.body || d.topic || '';
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
      // 列は 日時・サイト・工程・エラー内容・対応・状態 の6つ。5列で書くと「未対応」が
      // 対応の列に入り、状態（6列目）を数えるダッシュボードと errorSync_ から見えなくなる
      sheet_('エラーログ').appendRow([new Date(), site, 'メール送信', warn.join(' / '), '', '未対応']);
    } catch (e2) {}
  }
  return { ok: true, temperature: temp, row: row };
}

/** リードの温度。診断とサイト診断は、自社の情報を差し出しているので高く見る */
// 流入経路で温度を1段上げる。料金・サービス・診断・費用系の記事から来た人は、
// 「相談」と書いていなくても導入を検討している
const LEAD_HOT_PATHS = /\/lp\b|\/service|\/diagnosis|\/tools\/|\/price|\/plan|hiyou|souba|daikou|gaichuu|contact/i;

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
  // パートナー経由（/lp/?ref=ID）なら、どの種別でも紹介元を先頭に書く
  const base = leadDetailBase_(type, d);
  const ref = clean_(d.ref);
  return ref && base.indexOf('紹介元') < 0 ? ('紹介元 ' + ref + (base ? ' / ' + base : '')) : base;
}

function leadDetailBase_(type, d) {
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
    const n = a.fixes ? String(a.fixes).split('\n').filter(String).length : 0;
    return ['対象 ' + (a.url || ''), '総合 ' + (a.total || '') + '/100',
            a.grade ? '判定 ' + a.grade : '', n ? '未対応 ' + n + '項目' : ''].filter(String).join(' / ');
  }
  const known = ['type', 'site', 'name', 'company', 'email', 'tel', 'phone',
                 'message', 'body', 'referer', 'website', 'ts', 'formKey', 'ref',
                 'audit_url', 'audit_score', 'audit_grade', 'audit_fixes'];
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
  // 既存のお客様からの連絡は、担当が一目で分かるようにする（ステップメールも送られない）
  try {
    const a = d.audit || {};
    if (excluded_(excludeSet_(), d.email, a.url ? '対象 ' + a.url : '')) {
      lines.unshift('※ 既存のお客様です（配信除外に登録あり。自動のご案内メールは送りません）', '');
    }
  } catch (e) {}
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
            // 画面で「直し方をお送りします」と約束しているので、担当の連絡を待たせずに本文へ載せる
            a.fixes ? '▼ 直す項目と直し方（点数の大きい順）\n' + String(a.fixes) : '', '',
            '自社で直すのが難しい項目は、このメールにご返信ください。無料でご相談を承ります。'].filter(function (x) {
      return x !== '';
    }).join('\n');
  } else if (type === 'download') {
    // 資料ダウンロード。ページで「メールでダウンロードリンクをお送りします」と約束している。
    // 以前は普通の問い合わせと同じ文面で、リンクが入っていなかった（2026-10-02 修正）
    const CL = { dental: '歯科医院版', clinic: 'クリニック版', fudosan: '不動産会社版',
                 koumuten: '工務店・リフォーム会社版', shigyou: '士業事務所版' };
    const key = CL[String(d.checklist || '')] ? String(d.checklist) : '';
    const links = (key ? [key] : Object.keys(CL)).map(function (k) {
      return '・AI検索対策チェックリスト（' + CL[k] + '）\n  https://ai.7senses.co.jp/download/checklist-' + k + '.pdf';
    });
    subject = '【資料】AI検索対策チェックリストをお送りします';
    body = [name + ' 様', '', '資料をご請求いただきありがとうございます。',
            '下のリンクから、チェックリスト（PDF）をダウンロードしてください。', '']
      .concat(links).concat(['',
        '印をつけ終えたら、AIに御社がどう紹介されているかも確かめてみてください（無料）。',
        '  https://ai.7senses.co.jp/tools/ai-check/', '',
        '何から直せばよいかのご相談は、このメールにご返信ください。無料で承ります。']).join('\n');
  } else if (String(d.form_type || '').indexOf('AI紹介チェック') >= 0) {
    // 相談ではないので「担当よりご連絡します」とは書かない（約束していない連絡を待たせない）
    const msg = String(d.message || '');
    const failed = msg.indexOf('チェック未実行') === 0;
    subject = failed ? 'AI紹介チェックを受け付けました' : '【結果】AIにどう紹介されているか無料チェック';
    body = [name + ' 様', '', '「AIにどう紹介されているか無料チェック」をご利用いただきありがとうございます。', '']
      .concat(failed
        ? (msg.indexOf('quota') >= 0 ? ['今月の受付数に達していたため、チェックが完了していません。結果は担当からメールでお送りします。']
                                     : ['AIへの問い合わせが完了しませんでした。時間をおいて、もう一度お試しください。',
                                        '  https://ai.7senses.co.jp/tools/ai-check/'])
        : ['▼ 結果', msg.split('\n')[0].replace(/^AI紹介チェック: /, ''), '',
           '質問ごとの出典は、チェックした画面に表示しています。',
           '出典に入るための直し方は、業種別のチェックリスト（PDF・無料）にまとめています。',
           '  https://ai.7senses.co.jp/download/'])
      .concat(['', '詳しく調べたい場合は、このメールにご返信ください。']).join('\n');
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
  // 既存のお客様には送らない。状態を「成約・契約中・既存客」にした行は、先に配信除外へ写す
  const ex = excludeSet_();
  const moved = syncClientExcludes_(vals, ex);
  if (moved) console.log('配信除外に自動追加: ' + moved + '件');
  // 添える資料は AI集客ラボ（AIO）のものだけ。コーポレートや補助金の問い合わせに
  // AIOの動画を送ると、相談した内容と関係のない営業メールになる。
  // サイト列には表示名が入る（未登録ならIDのまま）ので、両方で見る
  const aiLab = { 'ai-lab': true };
  aiLab[siteLabel_('ai-lab')] = true;
  const tool = toolFollowCtx_(vals);
  let sent = 0;
  for (let i = 0; i < vals.length; i++) {
    const r = vals[i];
    if (!aiLab[String(r[1] || '').trim()]) continue;
    const at = r[0] instanceof Date ? r[0] : new Date(r[0]);
    const temp = String(r[12] || '').toUpperCase();
    const status = String(r[13] || '');
    const done = String(r[FOLLOW_COL - 1] || '');
    const email = String(r[6] || '');
    // 担当が対応を始めた（未対応でなくなった）行と、「停止」と返信があった行には送らない
    if (status !== '未対応' || !isEmail_(email)) continue;
    if (excluded_(ex, email, r[9])) continue;
    // AI紹介チェックと資料ダウンロードは相談ではない。「お問い合わせ…行き違い」の文面は送らず、
    // 道具ごとの後追い（数日後に1通だけ）に回す
    const kind = toolKind_(r);
    if (kind) {
      if (toolFollow_(sh, i + 2, r, kind, now, tool)) sent++;
      continue;
    }
    // 診断の点数がある行は、点数帯ごとのステップメールで送る（1通で終わらせない）
    const score = scoreOf_(r[9]);
    if (score !== null) {
      if (stepMail_(sh, i + 2, r, score, now)) sent++;
      continue;
    }
    const wait = FOLLOW_AFTER_DAYS[temp];
    if (!wait || done) continue;
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

/**
 * 無料ツールの後追い（followUp から呼ぶ。1人に1種類1通だけ）。
 *   aicheck:   AI紹介チェックで、どの回も出典に御社サイトが入らなかった人へ3日後
 *   checklist: チェックリストを受け取った人へ7日後
 * 相談・サイト診断を送ってきた人には送らない（担当が直接やり取りする）。
 * 本文に数字は入れない（入れるなら調査ページの値を人が確かめてから）。
 */
const TOOL_FOLLOW_DAYS = { aicheck: 3, checklist: 7 };
const CHECKLIST_LP = { dental: 'medical', clinic: 'medical', fudosan: 'fudosan', koumuten: 'koumuten', shigyou: 'shigyou' };
const CHECKLIST_LABEL = { dental: '歯科医院版', clinic: 'クリニック版', fudosan: '不動産会社版',
                          koumuten: '工務店・リフォーム会社版', shigyou: '士業事務所版' };
const AI_CHECK_WORD_KEY = { '歯医者': 'dental', 'クリニック': 'clinic', '不動産会社': 'fudosan', '工務店': 'koumuten',
  'リフォーム会社': 'koumuten', '税理士': 'shigyou', '社労士': 'shigyou', '行政書士': 'shigyou', '司法書士': 'shigyou', '弁護士': 'shigyou' };

function toolKind_(r) {
  if (/AI紹介チェック/.test(String(r[9] || '') + String(r[8] || ''))) return 'aicheck';
  if (String(r[2] || '') === LEAD_TYPE_LABELS.download) {
    // 2026-10-02 より前の資料ダウンロードは別の資料。チェックリストの後追いは送らず、従来のフォローに任せる
    return /checklist: "(dental|clinic|fudosan|koumuten|shigyou)"/.test(String(r[9] || '')) ? 'checklist' : '';
  }
  return '';
}

/** 送るかの判断に使う材料を、台帳とAI紹介チェックのシートから1回だけ集める */
function toolFollowCtx_(vals) {
  const ctx = { contacted: {}, done: {}, ai: {} };
  vals.forEach(function (r) {
    const email = String(r[6] || '').trim().toLowerCase();
    if (!email) return;
    const type = String(r[2] || '');
    if (type === LEAD_TYPE_LABELS.contact || type === LEAD_TYPE_LABELS.site_audit
        || /再送信\((無料相談|サイト無料診断)\)/.test(String(r[9] || ''))) ctx.contacted[email] = true;
    const f = String(r[FOLLOW_COL - 1] || '').match(/^(aicheck|checklist) /);
    if (f) ctx.done[f[1] + ' ' + email] = true;
  });
  const sh = book_().getSheetByName('AI紹介チェック');
  if (sh && sh.getLastRow() > 1) {
    sh.getRange(2, 1, sh.getLastRow() - 1, 7).getValues().forEach(function (r) {
      const email = String(r[1] || '').trim().toLowerCase();
      if (!email) return;
      const a = ctx.ai[email] || { cited: 0, word: '' };
      a.cited = Math.max(a.cited, Number(r[5]) || 0);
      a.word = String(r[3] || '') || a.word;
      ctx.ai[email] = a;
    });
  }
  return ctx;
}

function toolFollow_(sh, row, r, kind, now, ctx) {
  const email = String(r[6] || '').trim().toLowerCase();
  if (String(r[FOLLOW_COL - 1] || '') || ctx.contacted[email] || ctx.done[kind + ' ' + email]) return false;
  // チェックが最後まで動いた記録（AI紹介チェックのシート）がある人だけ。1回でも出典に入っていれば送らない
  if (kind === 'aicheck' && (!ctx.ai[email] || ctx.ai[email].cited > 0)) return false;
  const at = r[0] instanceof Date ? r[0] : new Date(r[0]);
  const age = (now - at) / 86400000;
  const wait = TOOL_FOLLOW_DAYS[kind];
  if (age < wait || age > wait + 7) return false;
  const name = String(r[4] || '') || 'ご担当者';
  const who = (String(r[3] || '') ? String(r[3]) + ' ' : '') + name + ' 様';
  const mail = kind === 'aicheck' ? aiCheckFollowText_(who, r, ctx.ai[email]) : checklistFollowText_(who, r);
  const foot = ['', '─────────────',
    'このご案内が不要な場合は、このメールに「停止」とだけご返信ください。以降はお送りしません。', '',
    'セブンセンシズ株式会社（AI集客ラボ）',
    '〒537-0003 大阪府大阪市東成区神路1丁目7-4 コンフォートビル901・902',
    'TEL 06-4305-7547 / info.ai@7senses.co.jp', ''].join('\n');
  try {
    MailApp.sendEmail({ to: email, subject: mail.subject, body: mail.body + foot,
                        name: 'セブンセンシズ株式会社', replyTo: NOTIFY_TO });
    sh.getRange(row, FOLLOW_COL).setValue(kind + ' ' + Utilities.formatDate(now, 'Asia/Tokyo', 'yyyy-MM-dd'));
    ctx.done[kind + ' ' + email] = true;
    return true;
  } catch (e) {
    console.error('ツールの後追いの送信に失敗: ' + e);
    return false;
  }
}

function aiCheckFollowText_(who, r, a) {
  const key = AI_CHECK_WORD_KEY[a.word] || '';
  // サイトのURLを入れずに調べた人は、出典に入ったかを判定できていない
  const noSite = /サイト: 未入力/.test(String(r[8] || ''));
  return { subject: 'AIの答えの出典に入るための3つの手順', body: [who, '',
    '先日は「AIにどう紹介されているか無料チェック」をご利用いただきありがとうございます。',
    noSite ? 'サイトのURLが未入力だったため、出典に御社のサイトが入ったかは判定できていません。'
           : '3つの質問のどれでも、AIの答えの出典に御社のサイトは入っていませんでした。',
    '出典に入るために、まず次の3つを確かめてください。', '',
    '1. AIが御社のサイトを読めるか確かめる',
    '   robots.txt やCDNの設定でAIのクローラーを止めていると、内容が良くても出典に使われません。',
    '   URLを入れるだけの30秒診断（無料）で確かめられます。',
    '   https://ai.7senses.co.jp/lp/' + (key ? CHECKLIST_LP[key] + '/' : '') + '#scan-start', '',
    '2. 御社にしか無い事実を、文字で書く',
    '   料金の決まり方・対応エリア・実績の数（集計の期間つき）・よくある質問への答えです。',
    '   AIが根拠に選ぶのは、他のサイトに無い事実です。画像の中の文字は読まれません。', '',
    '3. 予約・比較サイトの掲載情報を最新にする',
    '   「地域名＋業種 おすすめ」のような探す質問では、AIは予約・比較サイトも出典にします。',
    '   営業時間・料金・住所が古いと、その情報がそのまま答えに出ます。', '',
    '項目ごとに印をつけて確かめられるチェックリスト（PDF）もお送りできます。',
    '  https://ai.7senses.co.jp/download/' + (key ? '?ind=' + key : ''), '',
    'ご自身で進めるのが難しい場合は、このメールにご返信ください。ご相談は無料です。'].join('\n') };
}

function checklistFollowText_(who, r) {
  const key = (String(r[9] || '').match(/checklist: "(\w+)"/) || [])[1] || '';
  const lp = 'https://ai.7senses.co.jp/lp/' + (CHECKLIST_LP[key] ? CHECKLIST_LP[key] + '/' : '');
  return { subject: 'チェックリストで印がつかなかった項目の直し方', body: [who, '',
    '先日はAI検索対策チェックリスト' + (CHECKLIST_LABEL[key] ? '（' + CHECKLIST_LABEL[key] + '）' : '') + 'をお受け取りいただきありがとうございます。',
    '印がつかなかった項目の直し方を、章ごとにまとめました。', '',
    '■ 1. AIと検索に読まれる状態か',
    '・robots.txt に GPTBot などを拒否する行があれば消します。Cloudflare などを使っている場合は、AIクローラーを止める設定も確かめます。',
    '・公開したいページに noindex が残っていれば外します。',
    '・電話番号・所在地が画像の中にしか無ければ、文字で書き直します。',
    '・この章の項目は、URLを入れるだけの30秒診断（無料）でまとめて確かめられます。', '  ' + lp + '#scan-start', '',
    '■ 2.「探される」場面',
    '・社名・住所・電話番号の書き方を1つに決め、自社サイトと掲載サイトのすべてで揃えます。',
    '・掲載サイトの営業時間・料金・写真は、月に1回見直す日を決めておくと古くなりません。', '',
    '■ 3.「調べられる」場面',
    '・印がつかなかったテーマは、1テーマ1ページで書きます。冒頭の1〜2文で質問に答え、費用は幅と条件をつけて書きます。', '',
    '■ 4. 事実と書き方',
    '・実績の数字には、集計の期間と母数をつけます（「2025年4月〜2026年3月の42件」のように）。',
    '・ページに監修者・執筆者の名前と資格を載せ、更新日を表示します。', '',
    'AIに御社が今どう紹介されているかも、無料で確かめられます。',
    '  https://ai.7senses.co.jp/tools/ai-check/', '',
    'どこから直すか迷う場合は、このメールにご返信ください。ご相談は無料です。'].join('\n') };
}

/**
 * 診断の点数帯ごとのステップメール（followUp から呼ぶ）。
 *
 * 全員に同じ文面を送ると、点数が高い会社には押し売りに、低い会社には遠回りになる。
 * 帯ごとに送る日と中身を変える。送ったら15列目に「stepN 日付」と書き、次の段へ進む。
 * 担当が対応を始めた（状態が未対応でなくなった）行と、「停止」と返信があった行には送らない。
 * 数字は data/first_party_facts.json に登録済みのものと、出典つきの調査の値だけを使う。
 */
const STEP_DAYS = { low: [1, 4, 10], mid: [2, 7, 14], high: [3, 30] };

/**
 * 配信の除外（既存のお客様にステップメールや自動フォローを送らない）。
 *
 * 行の状態で止めるだけでは足りない。既存のお客様が自社サイトをもう一度診断すると、
 * 新しい行が「未対応」でできて、案内が始まってしまう。そこで相手そのもので除外する。
 * 除外に入るのは次の3つ。
 *   1) 「配信除外」シートに書いたメールアドレスかドメイン（手で足す）
 *   2) 台帳の状態を「成約」「契約中」「既存客」にした行のメールと、診断したサイトのドメイン（自動で足す）
 *   3) 「サイト一覧」に登録した受託先のドメイン（自社の7senses.co.jpは除く）
 * メールのドメインは、会社のドメインのときだけ使う（gmail.com などで除外すると他人まで止まる）。
 */
const CLIENT_STATUS = /成約|契約中|既存客/;
const FREE_MAIL = /^(gmail\.com|googlemail\.com|yahoo\.co\.jp|ymail\.ne\.jp|icloud\.com|me\.com|outlook\.(com|jp)|hotmail\.(com|co\.jp)|live\.(com|jp)|docomo\.ne\.jp|ezweb\.ne\.jp|au\.com|softbank\.ne\.jp|i\.softbank\.jp|nifty\.com|biglobe\.ne\.jp|ocn\.ne\.jp|so-net\.ne\.jp)$/i;

function excludeSheet_() {
  const ss = book_();
  let sh = ss.getSheetByName('配信除外');
  if (!sh) {
    sh = ss.insertSheet('配信除外');
    sh.appendRow(['メールアドレスかドメイン', 'メモ', '追加日']);
  }
  return sh;
}

function normHost_(v) {
  return String(v || '').trim().toLowerCase().replace(/^https?:\/\//, '').replace(/^www\./, '').replace(/[\/?#].*$/, '');
}

function excludeSet_() {
  const set = { emails: {}, domains: {} };
  const sh = excludeSheet_();
  if (sh.getLastRow() >= 2) {
    sh.getRange(2, 1, sh.getLastRow() - 1, 1).getValues().forEach(function (r) {
      const v = String(r[0] || '').trim().toLowerCase();
      if (!v) return;
      if (v.indexOf('@') > 0) set.emails[v] = true; else set.domains[normHost_(v)] = true;
    });
  }
  const site = book_().getSheetByName('サイト一覧');
  if (site && site.getLastRow() >= 2) {
    site.getRange(2, 3, site.getLastRow() - 1, 1).getValues().forEach(function (r) {
      const d = normHost_(r[0]);
      if (d && !/(^|\.)7senses\.co\.jp$/.test(d)) set.domains[d] = true;
    });
  }
  return set;
}

/** ドメインの一致（sub.example.co.jp は example.co.jp の登録でも当たる） */
function domainHit_(set, host) {
  host = normHost_(host);
  while (host && host.indexOf('.') > 0) {
    if (set.domains[host]) return true;
    host = host.slice(host.indexOf('.') + 1);
  }
  return false;
}

function excluded_(set, email, detail) {
  email = String(email || '').trim().toLowerCase();
  if (set.emails[email]) return true;
  const ed = email.split('@')[1] || '';
  if (ed && !FREE_MAIL.test(ed) && domainHit_(set, ed)) return true;
  const url = (String(detail || '').match(/対象 (https?:\/\/\S+)/) || [])[1];
  return !!(url && domainHit_(set, url));
}

/** 状態を「成約・契約中・既存客」にした行を、配信除外へ自動で写す（二重には足さない） */
function syncClientExcludes_(vals, set) {
  const sh = excludeSheet_();
  const today = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd');
  let added = 0;
  vals.forEach(function (r) {
    if (!CLIENT_STATUS.test(String(r[13] || ''))) return;
    const email = String(r[6] || '').trim().toLowerCase();
    const memo = '台帳の状態（' + String(r[13]) + '）から自動追加: ' + String(r[3] || '');
    if (email && !set.emails[email]) { sh.appendRow([email, memo, today]); set.emails[email] = true; added++; }
    const ed = email.split('@')[1] || '';
    if (ed && !FREE_MAIL.test(ed) && !set.domains[ed]) { sh.appendRow([ed, memo, today]); set.domains[ed] = true; added++; }
    const url = (String(r[9] || '').match(/対象 (https?:\/\/\S+)/) || [])[1];
    const h = normHost_(url);
    if (h && !set.domains[h]) { sh.appendRow([h, memo, today]); set.domains[h] = true; added++; }
  });
  return added;
}

/** 詳細欄から最新の点数を取り出す（「総合 54/100」）。無ければ null */
function scoreOf_(detail) {
  const m = String(detail || '').match(/総合 (\d{1,3})\/100/g);
  return m ? Number(m[m.length - 1].replace(/\D+/g, ' ').trim().split(' ')[0]) : null;
}

function stepMail_(sh, row, r, score, now) {
  const band = score < 65 ? 'low' : score < 85 ? 'mid' : 'high';
  const done = String(r[FOLLOW_COL - 1] || '');
  // 以前の1通だけのフォローを送った行は、そこで終わっている
  if (done && done.indexOf('step') !== 0) return false;
  const k = done ? Number((done.match(/^step(\d+)/) || [0, 0])[1]) : 0;
  const days = STEP_DAYS[band];
  if (k >= days.length) return false;
  const at = r[0] instanceof Date ? r[0] : new Date(r[0]);
  const age = (now - at) / 86400000;
  if (age < days[k] || age > days[k] + 7) return false;
  // 前の1通から最低2日は空ける（1通目が遅れて出たとき、翌日すぐ2通目が出ないように）
  const prev = (done.match(/(\d{4}-\d{2}-\d{2})/) || [])[1];
  if (prev && (now - new Date(prev + 'T00:00:00+09:00')) / 86400000 < 2) return false;
  const name = String(r[4] || '') || 'ご担当者';
  const company = String(r[3] || '');
  const url = (String(r[9] || '').match(/対象 (https?:\/\/\S+)/) || [])[1] || '';
  const mail = stepText_(band, k, { name: name, company: company, score: score, url: url });
  const foot = ['', '─────────────',
    'このご案内が不要な場合は、このメールに「停止」とだけご返信ください。以降はお送りしません。', '',
    'セブンセンシズ株式会社（AI集客ラボ）',
    '〒537-0003 大阪府大阪市東成区神路1丁目7-4 コンフォートビル901・902',
    'TEL 06-4305-7547 / info.ai@7senses.co.jp', ''].join('\n');
  try {
    MailApp.sendEmail({ to: String(r[6]), subject: mail.subject, body: mail.body + foot,
                        name: 'セブンセンシズ株式会社', replyTo: NOTIFY_TO });
    sh.getRange(row, FOLLOW_COL).setValue('step' + (k + 1) + ' ' +
      Utilities.formatDate(now, 'Asia/Tokyo', 'yyyy-MM-dd') + ' ' + band);
    return true;
  } catch (e) {
    console.error('ステップメールの送信に失敗: ' + e);
    return false;
  }
}

/** 帯（low/mid/high）と段（0始まり）ごとの件名と本文 */
function stepText_(band, k, v) {
  const who = (v.company ? v.company + ' ' : '') + v.name + ' 様';
  const consult = ['30分のオンラインで、診断結果の読み方と直す順番をご説明します（無料・営業電話なし）。',
    'ご都合の良い曜日と時間帯を、このメールにご返信ください。担当が合わせてご連絡します。'];
  const facts = ['・店舗集客「G-ran」で、通算3,200店舗以上のマップ集客を運用してきました（2026年7月時点）',
    '・2026年5月〜9月に契約したAIO運用15件のうち、3か月以内の解約は0件です',
    '・2026年5月にAIO運用を始めた10件は、10件すべてが3か月以内に主要な検索語の平均順位が上がりました（2026年5月〜8月の集計・わずかな上昇も含みます）'];
  const why = ['・「質問」の形で検索された場合、AIの回答（AI Overview）が出る割合は64.7%でした（全体では13.7%。arXiv 2605.14021・55,393件の調査）',
    '・当社3サイトの実測では、1〜3位のクリック率は6.28%、4〜10位は1.02%でした（2026年6月23日〜9月20日・表示7,015回）'];
  const T = {
    low: [
      { s: '【' + (v.company || '診断結果') + '】読まれない原因の直し方（' + v.score + '点）',
        b: [who, '', '先日はサイト診断をご利用いただきありがとうございます。', '',
            '御社のサイトは ' + v.score + '点でした。点数の大きい未対応の項目から直すと、少ない手間で点数が戻ります。',
            '直す項目と直し方は、診断直後のメールに一覧でお送りしています。', '',
            'ご自身で直すのが難しい項目があれば、そのままご相談ください。'].concat(consult) },
      { s: '読めない状態のままだと、候補に入らない理由',
        b: [who, '', 'AIの回答にも検索結果にも、読めないページは出てきません。数字で見ると、差ははっきりしています。', ''].concat(why)
            .concat(['', '診断で見つかった項目を直すことが、最初の一歩です。'], consult) },
      { s: '最後のご案内：直す順番のご相談について',
        b: [who, '', 'サイト診断のご案内は、今回で最後です。', '', '当社の実績（数字は集計の期間つき）:'].concat(facts)
            .concat(['', '料金は、現状を見たうえで必要な施策だけを組み合わせてお見積りします。ご契約前に費用はかかりません。'], consult) },
    ],
    mid: [
      { s: '【' + (v.company || '診断結果') + '】あと一歩の項目と、その先の差（' + v.score + '点）',
        b: [who, '', '先日はサイト診断をご利用いただきありがとうございます。', '',
            '御社のサイトは ' + v.score + '点で、土台はあと一歩です。残りの項目を直したあとの差は、',
            '「その会社にしか書けない事実」（料金の決まり方・対応エリア・実績の数字）が文字で書かれているかで付きます。', ''].concat(consult) },
      { s: '当社の実績（集計の期間つき）',
        b: [who, '', 'ご判断の材料として、当社の数字をお送りします。', ''].concat(facts).concat(['', ''], consult) },
      { s: '最後のご案内：御社の場合の進め方',
        b: [who, '', 'サイト診断のご案内は、今回で最後です。', '', ''].concat(why)
            .concat(['', '御社の場合に何から手をつけるかを、30分でご説明できます。'], consult) },
    ],
    high: [
      { s: '【' + (v.company || '診断結果') + '】土台は整っています（' + v.score + '点）',
        b: [who, '', '先日はサイト診断をご利用いただきありがとうございます。', '',
            '御社のサイトは ' + v.score + '点で、技術の土台は整っています。急いで何かを頼む必要はありません。', '',
            'この先の差は、AIや検索が答えに使える「その会社にしか無い事実」で付きます。',
            '当社は自社の実測データを公開しています。書き方の参考にどうぞ。', '  https://ai.7senses.co.jp/data/', '',
            '気になったときは、いつでもこのメールにご返信ください。'] },
      { s: '1か月たちました：もう一度測ってみませんか',
        b: [who, '', 'サイト診断から1か月がたちました。ページを更新すると、点数も変わります。',
            v.url ? 'このリンクから、同じURLで30秒で測り直せます。' : 'このページから、30秒で測り直せます。',
            '  https://ai.7senses.co.jp/lp/' + (v.url ? '?check=' + encodeURIComponent(v.url) + '#scan' : ''), '',
            'ご案内は今回で最後です。'] },
    ],
  };
  const m = T[band][k];
  return { subject: m.s, body: m.b.join('\n') };
}

/**
 * 取りこぼした問い合わせを台帳へ戻す（合言葉つきの action でだけ呼ばれる）。
 * 列は leadSave_ と同じ。メール・自動返信・フォローは一切しない（相手に今さら届かないように）。
 * 同じメール・同じ受信日の行が既にあれば書かない（2回流しても重複しない）。
 */
function restoreLead_(body) {
  const d = body.data || {};
  const email = clean_(d.email).toLowerCase();
  const at = new Date(body.received_at);
  if (!email || isNaN(at.getTime())) return { ok: false, error: 'email と received_at が必要です' };
  const sh = sheet_('問い合わせ');
  const last = sh.getLastRow();
  const day = Utilities.formatDate(at, 'Asia/Tokyo', 'yyyy-MM-dd');
  if (last > 1) {
    const vals = sh.getRange(2, 1, last - 1, 7).getValues();
    for (const v of vals) {
      if (String(v[6]).toLowerCase() === email && v[0] instanceof Date
          && Utilities.formatDate(v[0], 'Asia/Tokyo', 'yyyy-MM-dd') === day) {
        return { ok: true, skipped: 'already' };
      }
    }
  }
  const site = siteLabel_(body.site) || '（不明）';
  sh.appendRow([
    at, site, LEAD_TYPE_LABELS[body.type] || '無料相談', clean_(d.company), clean_(d.name), '',
    email, clean_(d.tel), body_(d.message), clean_(body.note || ''), '', clean_(d.referer), 'WARM', '未対応',
  ]);
  return { ok: true, row: sh.getLastRow() };
}

/**
 * 診断の記録（同業平均のため）。LPとサイトチェックの診断のたびに audit.js が送る。
 * 残すのは業種・点数・紹介元と、サイトを特定できない形に変換した値（ハッシュ）だけ。
 */
function scanLog_(body) {
  const ss = book_();
  let sh = ss.getSheetByName('診断ログ');
  if (!sh) {
    sh = ss.insertSheet('診断ログ');
    sh.appendRow(['日時', '業種', 'サイト（ハッシュ）', '点数', '紹介元']);
  }
  const score = Number(body.score);
  if (!(score >= 0 && score <= 100)) return { ok: false, error: 'score' };
  sh.appendRow([new Date(), clean_(body.industry).slice(0, 30), clean_(body.host).slice(0, 64), score,
                clean_(body.ref).slice(0, 40)]);
  return { ok: true };
}

/**
 * AI紹介チェック（ai.7senses.co.jp/tools/ai-check/）の回数制限と記録。
 * 問い合わせ台帳は同じメールの送信を1行にまとめるため、回数は数えられない。専用のシートに1回1行で残す。
 * メールアドレスごとに累計3回まで。架空のアドレスを変えれば何度でも申し込めるため、
 * 同じ回線（IPアドレス）からは1日2回まで。
 * 月の上限は、実際に行われた検索の回数で 5,000回。検索つきの Gemini は無料枠では使えず
 * （公式の料金表: Free Tier は Not available。2026-10-04 確認）、有料プランの「月5,000回まで検索料0円」に収める。
 * 1回の質問で検索が何回も行われるため、質問の数ではなく検索の回数で数える。
 */
const AI_CHECK_PER_EMAIL = 3;
const AI_CHECK_PER_IP_DAY = 2;
const AI_CHECK_MONTH_SEARCHES = 5000;
const AI_CHECK_MAX_SEARCHES_PER_CHECK = 15;   // 1回の診断で行われうる検索の上限の見込み。残りがこれ未満なら受け付けない

function aiCheckSheet_() {
  const ss = book_();
  let sh = ss.getSheetByName('AI紹介チェック');
  if (!sh) {
    sh = ss.insertSheet('AI紹介チェック');
    sh.appendRow(['日時', 'メール', '会社名', '業種', '地域', '出典に御社サイト', '回答に社名']);
  }
  // 翌月の測り直し（2026-10-03 追加）。既存のシートには見出しだけ足す
  if (String(sh.getRange(1, 8).getValue() || '') === '') {
    sh.getRange(1, 8, 1, 3).setValues([['サイト', '翌月の測り直し', '測り直し済み']]);
  }
  // 回線ごとの回数と、実際の検索回数（2026-10-04 追加）
  if (String(sh.getRange(1, 11).getValue() || '') === '') {
    sh.getRange(1, 11, 1, 2).setValues([['IPアドレス', '検索回数']]);
  }
  return sh;
}

/**
 * 翌月の測り直し（AI診断で「来月の結果を受け取る」に印をつけた人だけ）。
 * 28〜40日前のチェックのうち、まだ測り直していない行。同じメールは最新の1行だけ。
 * 配信除外（「停止」の返信・既存のお客様）は返さない。測り直しはこのシートに行を足さない（3回の上限に数えない）。
 */
function aiRecheckList_() {
  const sh = aiCheckSheet_();
  if (sh.getLastRow() < 2) return { ok: true, items: [] };
  const vals = sh.getRange(2, 1, sh.getLastRow() - 1, 10).getValues();
  const now = new Date(), ex = excludeSet_(), latest = {};
  vals.forEach(function (r, i) {
    const email = String(r[1] || '').trim().toLowerCase();
    if (!email) return;
    const at = r[0] instanceof Date ? r[0] : new Date(r[0]);
    if (!latest[email] || latest[email].at < at) latest[email] = { at: at, i: i, r: r };
  });
  const items = [];
  Object.keys(latest).forEach(function (email) {
    const x = latest[email], r = x.r;
    const age = (now - x.at) / 86400000;
    if (String(r[8]) !== '希望' || String(r[9] || '') || age < 28 || age > 40) return;
    if (excluded_(ex, email, '')) return;
    items.push({ row: x.i + 2, email: email, company: String(r[2] || ''), word: String(r[3] || ''),
                 area: String(r[4] || ''), cited: Number(r[5]) || 0, mentioned: Number(r[6]) || 0,
                 site: String(r[7] || ''), at: Utilities.formatDate(x.at, 'Asia/Tokyo', 'yyyy-MM-dd') });
  });
  return { ok: true, items: items };
}

function aiRecheckDone_(body) {
  const row = Number(body.row);
  if (!(row >= 2)) return { ok: false, error: 'row' };
  aiCheckSheet_().getRange(row, 10).setValue(Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd') + ' '
    + clean_(body.result || '').slice(0, 60));
  return { ok: true };
}

/**
 * 記事の自動処理（語の調査・引用の実測・測り直し）が Gemini で行った検索の回数。
 * AI診断と同じ「月5,000回まで検索料0円」を分け合うため、両方をここで数える（2026-10-04）。
 * 自動処理は月 GEMINI_BATCH_MONTH まで。残りを AI診断に回す。
 */
const GEMINI_BATCH_MONTH = 2000;

function geminiSheet_() {
  const ss = book_();
  let sh = ss.getSheetByName('Gemini利用');
  if (!sh) {
    sh = ss.insertSheet('Gemini利用');
    sh.appendRow(['日時', '工程', '検索回数']);
  }
  return sh;
}

function geminiBatchSearches_() {
  const sh = geminiSheet_();
  const now = new Date();
  let n = 0;
  if (sh.getLastRow() > 1) {
    sh.getRange(2, 1, sh.getLastRow() - 1, 3).getValues().forEach(function (r) {
      const at = r[0] instanceof Date ? r[0] : new Date(r[0]);
      if (at.getFullYear() === now.getFullYear() && at.getMonth() === now.getMonth()) n += Number(r[2]) || 0;
    });
  }
  return n;
}

function geminiUsage_() {
  const batch = geminiBatchSearches_();
  const diag = aiCheckQuota_({ email: '_usage_', ip: '' }).searches;
  return { ok: true, batch: batch, diagnosis: diag, total: batch + diag,
           batchCap: GEMINI_BATCH_MONTH, monthCap: AI_CHECK_MONTH_SEARCHES };
}

function geminiLog_(body) {
  geminiSheet_().appendRow([new Date(), clean_(body.job).slice(0, 40), Number(body.searches) || 0]);
  return { ok: true };
}

function aiCheckQuota_(body) {
  const email = clean_(body.email).toLowerCase();
  if (!email) return { ok: false, error: 'email' };
  const ip = clean_(body.ip);
  const sh = aiCheckSheet_();
  let used = 0, ipToday = 0, searches = 0;
  const now = new Date();
  const today = Utilities.formatDate(now, 'Asia/Tokyo', 'yyyy-MM-dd');
  if (sh.getLastRow() > 1) {
    sh.getRange(2, 1, sh.getLastRow() - 1, 12).getValues().forEach(function (r) {
      const at = r[0] instanceof Date ? r[0] : new Date(r[0]);
      if (String(r[1]).toLowerCase() === email) used++;
      if (ip && String(r[10]) === ip && Utilities.formatDate(at, 'Asia/Tokyo', 'yyyy-MM-dd') === today) ipToday++;
      // 検索回数の列が無い古い行は、1回3問×最大の見込みで数える（少なく数えて上限を越えないように）
      if (at.getFullYear() === now.getFullYear() && at.getMonth() === now.getMonth())
        searches += r[11] === '' || r[11] === null ? AI_CHECK_MAX_SEARCHES_PER_CHECK : Number(r[11]) || 0;
    });
  }
  const reason = used >= AI_CHECK_PER_EMAIL ? 'email'
    : (ipToday >= AI_CHECK_PER_IP_DAY ? 'ip'
    : (searches + geminiBatchSearches_() + AI_CHECK_MAX_SEARCHES_PER_CHECK > AI_CHECK_MONTH_SEARCHES ? 'month' : ''));
  return { ok: true, used: used, perEmail: AI_CHECK_PER_EMAIL, perIpDay: AI_CHECK_PER_IP_DAY,
           searches: searches, allowed: !reason, reason: reason };
}

function aiCheckLog_(body) {
  aiCheckSheet_().appendRow([new Date(), clean_(body.email).toLowerCase(), clean_(body.company).slice(0, 80),
    clean_(body.word).slice(0, 20), clean_(body.area).slice(0, 40), Number(body.cited) || 0, Number(body.mentioned) || 0,
    String(body.site || '').replace(/[\r\n\s]+/g, '').slice(0, 200), body.recheck ? '希望' : '', '',
    clean_(body.ip).slice(0, 64), Number(body.searches) || 0]);
  return { ok: true };
}

/**
 * 業種ごとの平均点（同じサイトは最新の1回だけ数える）。10社未満の業種は出さない。
 * 公開の入口から呼ばれるので、返すのは集計値だけ（個々の行は返さない）。
 */
const BENCH_MIN = 10;
function scanBench_() {
  const sh = book_().getSheetByName('診断ログ');
  if (!sh || sh.getLastRow() < 2) return { ok: true, industries: {}, since: '' };
  const vals = sh.getRange(2, 1, sh.getLastRow() - 1, 4).getValues();
  const latest = {};
  let since = null;
  vals.forEach(function (r) {
    const at = r[0] instanceof Date ? r[0] : new Date(r[0]);
    if (!since || at < since) since = at;
    const key = String(r[2] || '');
    if (!key) return;
    if (!latest[key] || latest[key].at < at) latest[key] = { at: at, ind: String(r[1] || ''), score: Number(r[3]) };
  });
  const agg = {};
  Object.keys(latest).forEach(function (k) {
    const x = latest[k];
    // 業種を選ばずに診断した分は、全体の平均にだけ数える
    [x.ind, '全体'].filter(String).forEach(function (g) {
      agg[g] = agg[g] || { n: 0, sum: 0 };
      agg[g].n++; agg[g].sum += x.score;
    });
  });
  const out = {};
  Object.keys(agg).forEach(function (g) {
    if (agg[g].n >= BENCH_MIN) out[g] = { n: agg[g].n, avg: Math.round(agg[g].sum / agg[g].n) };
  });
  return { ok: true, industries: out, min: BENCH_MIN,
           since: since ? Utilities.formatDate(since, 'Asia/Tokyo', 'yyyy-MM-dd') : '' };
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
