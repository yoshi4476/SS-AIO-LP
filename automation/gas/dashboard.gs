/**
 * ダッシュボードと、内部リンク・リライトの記録
 * ------------------------------------------------------------------
 * ダッシュボードは KPI 集計（GA4/GSC）が動いて初めて埋まる作りだった。
 * 集計の定期実行が未設定だったため、ずっと空のままだった。
 *
 * ここでは台帳の中身だけで埋まる指標を先に出す。外部APIに依存しないので、
 * 何が起きていても必ず表示される。GA4/GSCの数値は KPI 集計が動けば上書きされる。
 *
 * あわせて「内部リンク管理」「リライトログ」への記録口を用意する。
 * タブの定義だけあって書き込む処理が無く、ずっと空だった。
 */

/** 台帳から数えられるものだけでダッシュボードを埋める */
function refreshDashboard() {
  const ss = book_();
  const sh = sheet_('ダッシュボード');

  // 前回値を控えて増減を出す（推移が見えないと数字を見る意味が薄い）
  const prev = {};
  if (sh.getLastRow() > 1) {
    sh.getRange(2, 1, sh.getLastRow() - 1, 2).getValues().forEach(function (r) {
      prev[r[0]] = Number(r[1]) || 0;
    });
  }

  const kw = kwRows_();
  const count = function (site, state) {
    return kw.filter(function (r) {
      return (!site || String(r[0]).trim() === site)
          && (!state || String(r[2]).trim() === state);
    }).length;
  };

  const logSh = ss.getSheetByName('記事作成ログ');
  const logs = logSh && logSh.getLastRow() > 1
    ? logSh.getRange(2, 1, logSh.getLastRow() - 1, 8).getValues() : [];
  const today = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy/MM/dd');
  const thisMonth = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy/MM');
  const fmt = function (d) {
    return d instanceof Date ? Utilities.formatDate(d, 'Asia/Tokyo', 'yyyy/MM/dd') : String(d);
  };
  const todayN = logs.filter(function (r) { return fmt(r[0]) === today; }).length;
  const monthN = logs.filter(function (r) { return fmt(r[0]).slice(0, 7) === thisMonth; }).length;
  const scores = logs.map(function (r) { return Number(r[5]) || 0; }).filter(Boolean);
  const avg = scores.length
    ? Math.round(scores.reduce(function (a, b) { return a + b; }, 0) / scores.length * 10) / 10 : 0;

  const inqSh = ss.getSheetByName('問い合わせ');
  const inq = inqSh && inqSh.getLastRow() > 1
    ? inqSh.getRange(2, 1, inqSh.getLastRow() - 1, 14).getValues() : [];
  const hot = inq.filter(function (r) { return String(r[12]).trim() === 'HOT'; }).length;
  const open = inq.filter(function (r) { return String(r[13]).trim() === '未対応'; }).length;

  // 解消した行まで数えると、自動で閉じても数字が減らない。未対応だけを数える
  const errSh = ss.getSheetByName('エラーログ');
  const errRows = (errSh && errSh.getLastRow() > 1) ? errSh.getRange(2, 6, errSh.getLastRow() - 1, 1).getValues() : [];
  const errN = errRows.filter(function (r) { return String(r[0]).trim() === '未対応'; }).length;

  // どのページが問い合わせを生んだか。送信元ページ（12列目）を数え、
  // 記事作成ログのURL（8列目）と突き合わせて題名を添える
  const byPage = {};
  inq.forEach(function (r) {
    const src = String(r[11] || '').trim().replace(/[?#].*$/, '');
    if (!src) return;
    byPage[src] = (byPage[src] || 0) + 1;
  });
  const titleOf = {};
  logs.forEach(function (r) {
    const u = String(r[7] || '').trim().replace(/[?#].*$/, '');
    if (u) titleOf[u] = String(r[2] || '');
  });
  const topPages = Object.keys(byPage).sort(function (a, b) { return byPage[b] - byPage[a]; }).slice(0, 3);

  const rows = [
    ['公開記事数（累計）', logs.length],
    ['本日の公開数', todayN],
    ['今月の公開数', monthN],
    ['平均品質スコア', avg],
    ['KW在庫（未着手・全サイト計）', count('', '未着手')],
    // サイトごとの内訳は「サイト一覧」の登録から作る。ここにIDを直接書くと、
    // 別の会社では常に0のまま並び、本当に在庫が切れても気づけない
    ...Object.keys(siteMap_()).map(function (id) {
      return ['　' + siteMap_()[id].name, count(id, '未着手')];
    }),
    ['問い合わせ（累計）', inq.length],
    ['　うちHOT', hot],
    ['　未対応', open],
    ['エラーログ（未対応）', errN],
    ...topPages.map(function (u, i) {
      const t = titleOf[u] || titleOf[u.replace(/\/$/, '')] || u.replace(/^https?:\/\/[^/]+/, '');
      return ['　問い合わせを生んだページ ' + (i + 1) + '位', byPage[u] + '件 ｜ ' + t.slice(0, 40)];
    }),
  ];

  // 全行を消さない。流入の合計（kpi_log が書く7項目）が消えていた
  upsertDashboard_(rows, '台帳から集計');
  // 名前を変えた項目の古い行は残ると二重に見える
  ['エラーログ件数'].forEach(function (name) {
    const v = sh.getRange(2, 1, Math.max(1, sh.getLastRow() - 1), 1).getValues();
    for (let i = v.length - 1; i >= 0; i--) if (String(v[i][0]) === name) sh.deleteRow(i + 2);
  });
  return rows.length + '項目を更新しました';
}

/** 内部リンクの設置を記録する（action: link_log） */
function linkLog_(body) {
  const rows = body.rows || [];
  if (!rows.length) return { ok: false, error: '記録する行がありません' };
  const sh = sheet_('内部リンク管理');
  const now = new Date();
  // appendRow を1行ずつ呼ぶと数百件で応答が返らなくなる。
  // まとめて1回で書き込む。
  const values = rows.map(function (r) {
    return [now, r.site || body.site || '', r.from || '', r.to || '', r.anchor || ''];
  });
  if (body.replace === true && sh.getLastRow() > 1) {
    sh.deleteRows(2, sh.getLastRow() - 1);   // 貼り直しのとき、古い行と混ざらないように
  }
  sh.getRange(sh.getLastRow() + 1, 1, values.length, 5).setValues(values);
  return { ok: true, added: values.length };
}

/** リライトの実施を記録する（action: rewrite_log） */
function rewriteLog_(body) {
  const rows = body.rows || [body];
  const sh = sheet_('リライトログ');
  let n = 0;
  rows.forEach(function (r) {
    if (!r.article) return;
    sh.appendRow([new Date(), r.site || body.site || '', r.article, r.reason || '',
                  r.summary || '', r.posBefore || '', r.posAfter || '', r.effect || '']);
    n++;
  });
  return n ? { ok: true, added: n } : { ok: false, error: '記録する行がありません' };
}

/**
 * 問い合わせ台帳から、動作確認で入れた行と中身の無い行を消す（action: clean_inquiry）
 *
 * 通知メールの権限が通っていなかった時期に、記録だけが残って中身が空の行ができた。
 * 動作確認の送信も混ざっている。実際の問い合わせと見分けがつかないと、
 * 未対応の件数が信用できなくなる。
 *
 * dry を true で呼ぶと、消す対象を数えるだけで消さない。
 */
function cleanInquiry_(body) {
  const sh = sheet_('問い合わせ');
  const last = sh.getLastRow();
  if (last < 2) return { ok: true, removed: 0, kept: 0 };

  const width = sh.getLastColumn();
  const rows = sh.getRange(2, 1, last - 1, width).getValues();
  const MARK = ['接続テスト', '列テスト', '反映確認', '権限確認', '移行後確認',
                'テスト株式会社', 'example.com', '対応不要'];

  const del = [];
  rows.forEach(function (r, i) {
    const blob = r.join(' ');
    const isTest = MARK.some(function (m) { return blob.indexOf(m) !== -1; });
    // 名前もメールも本文も無い行は、記録だけが残った失敗の跡
    const empty = !String(r[3] || '').trim() && !String(r[4] || '').trim()
               && !String(r[6] || '').trim() && !String(r[8] || '').trim();
    if (isTest || empty) del.push(i + 2);
  });

  if (body && body.dry) {
    return { ok: true, wouldRemove: del.length, kept: rows.length - del.length };
  }
  // 下から消す。上から消すと行番号がずれる
  del.reverse().forEach(function (r) { sh.deleteRow(r); });
  return { ok: true, removed: del.length, kept: rows.length - del.length };
}
