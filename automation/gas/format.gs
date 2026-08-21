/**
 * 管制塔スプレッドシートの見た目を整える
 * ------------------------------------------------------------------
 * タブが11枚あり、列幅も色もばらばらだと、どこに何があるか掴めない。
 * 見出しの色・列幅・折り返し・固定行を揃え、状態列には色を付ける。
 *
 * 何度実行しても同じ結果になる（値は触らず、書式だけを整える）。
 *
 * 使い方: エディタから formatBook を実行する。
 */

// タブごとの列幅（px）。指定がない列は既定値を使う
const COL_WIDTH = {
  'KW台帳': [90, 260, 80, 60, 130, 130, 90, 90, 90, 300, 200],
  '記事作成ログ': [140, 90, 320, 200, 120, 60, 80, 300, 200],
  '問い合わせ': [140, 130, 100, 160, 110, 110, 200, 120, 320, 280, 90, 200, 70, 90],
  'KPIレポート': [90, 90, 100, 80, 100, 90, 70, 90, 60, 200],
  'AIO計測': [90, 90, 120, 130, 90, 100, 90, 110, 200],
  '内部リンク管理': [90, 90, 280, 280, 220],
  'リライトログ': [90, 90, 260, 180, 320, 80, 80, 120],
  'エラーログ': [140, 130, 110, 420, 200, 80],
  'ダッシュボード': [220, 120, 100, 140, 300],
  'サイト一覧': [90, 200, 180, 260, 100, 120],
  '設定': [200, 300, 400],
};

// 状態の列に色を付ける。目で追える色数に絞る（多いと逆に読めない）
const STATE_COLORS = [
  { words: ['公開済み', '完了', '対応済み', 'OK', '解決'], bg: '#e6f4ea', fg: '#137333' },
  { words: ['作業中', '着手', '進行中', '未対応'], bg: '#fef7e0', fg: '#b06000' },
  { words: ['未着手', '保留'], bg: '#f1f3f4', fg: '#5f6368' },
  { words: ['エラー', '失敗', 'NG', '取り下げ'], bg: '#fce8e6', fg: '#c5221f' },
  { words: ['HOT'], bg: '#fce8e6', fg: '#c5221f' },
  { words: ['WARM'], bg: '#fef7e0', fg: '#b06000' },
  { words: ['COOL'], bg: '#e8f0fe', fg: '#1967d2' },
];


function formatBook() {
  const ss = book_();
  const log = [];

  ss.getSheets().forEach(function (sh) {
    const name = sh.getName();
    const lastCol = Math.max(1, sh.getLastColumn());
    const lastRow = Math.max(1, sh.getLastRow());

    // 見出し行
    const head = sh.getRange(1, 1, 1, lastCol);
    head.setBackground('#0b2447').setFontColor('#ffffff')
        .setFontWeight('bold').setFontSize(10)
        .setVerticalAlignment('middle').setWrap(true);
    sh.setFrozenRows(1);
    sh.setRowHeight(1, 34);

    // 列幅。定義があればそれを使い、無ければ内容に合わせる
    const widths = COL_WIDTH[name];
    for (let c = 1; c <= lastCol; c++) {
      if (widths && widths[c - 1]) {
        sh.setColumnWidth(c, widths[c - 1]);
      } else {
        sh.autoResizeColumn(c);
      }
    }

    if (lastRow > 1) {
      const body = sh.getRange(2, 1, lastRow - 1, lastCol);
      body.setFontSize(10).setVerticalAlignment('top').setWrap(true);
      // 1行おきの薄い背景。行を目で追いやすくする
      const banding = sh.getBandings();
      banding.forEach(function (b) { b.remove(); });
      sh.getRange(1, 1, lastRow, lastCol)
        .applyRowBanding(SpreadsheetApp.BandingTheme.LIGHT_GREY, true, false);
    }

    // 日付の列は幅を取りすぎないよう表示形式を短くする
    const headers = sh.getRange(1, 1, 1, lastCol).getValues()[0];
    headers.forEach(function (h, i) {
      const t = String(h);
      if (lastRow < 2) return;
      if (/日時/.test(t)) {
        sh.getRange(2, i + 1, lastRow - 1, 1).setNumberFormat('yyyy/MM/dd HH:mm');
      } else if (/日$|日付/.test(t)) {
        sh.getRange(2, i + 1, lastRow - 1, 1).setNumberFormat('yyyy/MM/dd');
      } else if (/CTR|率/.test(t)) {
        sh.getRange(2, i + 1, lastRow - 1, 1).setNumberFormat('0.00"%"');
      } else if (/回数|クリック|セッション|PV|文字数|スコア|件数/.test(t)) {
        sh.getRange(2, i + 1, lastRow - 1, 1).setNumberFormat('#,##0');
      }
    });

    // 状態・温度の列に色を付ける
    headers.forEach(function (h, i) {
      if (!/状態|ステータス|対応状況|温度|効果/.test(String(h))) return;
      const rng = sh.getRange(2, i + 1, Math.max(1, lastRow - 1), 1);
      const rules = STATE_COLORS.map(function (s) {
        return SpreadsheetApp.newConditionalFormatRule()
          .whenTextEqualTo(s.words[0])
          .setBackground(s.bg).setFontColor(s.fg).setRanges([rng]).build();
      });
      // 既存の同じ範囲のルールを消してから付け直す（重ねると効かなくなる）
      const keep = sh.getConditionalFormatRules().filter(function (r) {
        return r.getRanges().every(function (x) { return x.getColumn() !== i + 1; });
      });
      sh.setConditionalFormatRules(keep.concat(rules));
    });

    log.push(name + ': ' + (lastRow - 1) + '行 / ' + lastCol + '列');
  });

  const text = '書式を整えました\n\n' + log.join('\n');
  console.log(text);
  return text;
}
