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

  const errSh = ss.getSheetByName('エラーログ');
  const errN = errSh ? Math.max(0, errSh.getLastRow() - 1) : 0;

  const rows = [
    ['公開記事数（累計）', logs.length],
    ['本日の公開数', todayN],
    ['今月の公開数', monthN],
    ['平均品質スコア', avg],
    ['KW在庫（未着手・3サイト計）', count('', '未着手')],
    ['　AI集客ラボ', count('ai-lab', '未着手')],
    ['　コーポレート', count('corporate', '未着手')],
    ['　AI導入補助金', count('subsidy', '未着手')],
    ['問い合わせ（累計）', inq.length],
    ['　うちHOT', hot],
    ['　未対応', open],
    ['エラーログ件数', errN],
  ];

  if (sh.getLastRow() > 1) sh.deleteRows(2, sh.getLastRow() - 1);
  rows.forEach(function (r) {
    const before = prev[r[0]];
    const diff = (before === undefined) ? ''
      : ((r[1] - before >= 0 ? '+' : '') + (Math.round((r[1] - before) * 10) / 10));
    sh.appendRow([r[0], r[1], diff, new Date(), '台帳から集計']);
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
