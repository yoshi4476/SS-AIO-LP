/**
 * 管制塔のデータを、別のスプレッドシートへ移す
 * ------------------------------------------------------------------
 * このGASは「無題のスプレッドシート」に紐づいており、
 * SpreadsheetApp.getActiveSpreadsheet() はそちらを指している。
 * 名前のついた「セブンセンシズ自動化管制塔」へ中身を移すために使う。
 *
 * コンテナバインドのGASは親を変えられないため、移した後は
 * hub.gs 側で「どのシートを使うか」をIDで指定する（HUB_SHEET_ID）。
 *
 * 使い方: エディタから migrateToNamedSheet を実行する。
 *         移行元のタブをそのまま作り直し、値を写して、行数を突き合わせる。
 */

// 移し先。名前のついた管制塔スプレッドシート
const MIGRATE_TO = '1ew-xG28Nd-jWSorqGgwYmHoV-DCwUtI40bRH2Y4IDOQ';

function migrateToNamedSheet() {
  const src = SpreadsheetApp.getActiveSpreadsheet();
  const dst = SpreadsheetApp.openById(MIGRATE_TO);
  const log = ['移行元: ' + src.getName(), '移行先: ' + dst.getName(), ''];

  src.getSheets().forEach(function (sh) {
    const name = sh.getName();
    const last = sh.getLastRow();
    const lastCol = sh.getLastColumn();
    if (!last || !lastCol) {
      log.push(name + ': 空のため飛ばしました');
      return;
    }
    const values = sh.getRange(1, 1, last, lastCol).getValues();

    // 同名タブがあれば中身を消してから入れ直す（古い行と混ざらないように）
    let to = dst.getSheetByName(name);
    if (to) {
      to.clear();
    } else {
      to = dst.insertSheet(name);
    }
    to.getRange(1, 1, values.length, values[0].length).setValues(values);
    to.setFrozenRows(1);
    log.push(name + ': ' + (values.length - 1) + '行を移しました');
  });

  // 移し終えたら行数を突き合わせる。ここで差が出たら移行は失敗とみなす
  log.push('', '── 照合 ──');
  let ng = 0;
  src.getSheets().forEach(function (sh) {
    const to = dst.getSheetByName(sh.getName());
    const a = sh.getLastRow();
    const b = to ? to.getLastRow() : 0;
    if (a !== b) ng++;
    log.push(sh.getName() + ': 元' + a + '行 / 先' + b + '行' + (a === b ? '' : '  ← 不一致'));
  });
  log.push('', ng ? ng + '枚で不一致。やり直してください' : 'すべて一致しました');
  log.push('', '移行先: ' + dst.getUrl());

  const text = log.join('\n');
  console.log(text);
  try {
    MailApp.sendEmail({ to: NOTIFY_TO, subject: '【管制塔】シート移行の結果', body: text });
  } catch (e) {}
  return text;
}
