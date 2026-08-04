/**
 * 3サイトのKPIを毎日自動集計してダッシュボードに書き込む（管制塔の第2弾）
 *
 * ────────────────────────────────
 * 設置手順
 * ────────────────────────────────
 * 1. Apps Script エディタの左「ファイル」の＋ → スクリプト → 名前を「kpi」にして
 *    このファイルの内容を貼り付ける
 * 2. 左メニュー「サービス」の＋ から次の2つを追加する（これが無いと動きません）
 *      ・Google Analytics Data API   → 識別子は AnalyticsData のまま
 *      ・Search Console API          → 識別子は SearchConsole のまま
 * 3. 下の GA4_PROPERTIES に各サイトのGA4プロパティID（数字）を記入する
 * 4. 関数「updateKpi」を選んで ▶実行（初回は権限承認）
 * 5. 関数「installTriggers」を1回だけ実行 → 毎朝6時の自動集計が有効になる
 *
 * サービスアカウントのJSONキーは不要。実行者のGoogleアカウント権限で読み取ります。
 * そのため、集計したいGA4プロパティとSearch Consoleに、
 * このスクリプトを実行するGoogleアカウント自身の閲覧権限が必要です。
 */

// ▼ 設定 ────────────────────────────────
const GA4_PROPERTIES = {
  'ai-lab': '547346579',   // ai.7senses.co.jp
  'subsidy': '',           // lp.7senses.co.jp （GA4プロパティIDを記入）
  'corporate': '',         // corp.7senses.co.jp （GA4プロパティIDを記入）
};

const GSC_SITES = {
  'ai-lab': 'https://ai.7senses.co.jp/',
  'subsidy': 'https://lp.7senses.co.jp/',
  'corporate': 'https://corp.7senses.co.jp/',
};

const AI_REFERRERS = ['chatgpt.com', 'chat.openai.com', 'perplexity.ai',
                      'gemini.google.com', 'copilot.microsoft.com', 'claude.ai'];
// ────────────────────────────────────

function installTriggers() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'updateKpi') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('updateKpi').timeBased().atHour(6).everyDays(1).create();
  SpreadsheetApp.getActiveSpreadsheet().toast('毎朝6時のKPI自動集計を設定しました', '管制塔', 5);
}

function ymd_(d) {
  return Utilities.formatDate(d, 'Asia/Tokyo', 'yyyy-MM-dd');
}

function daysAgo_(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d;
}

/** GA4: セッション・PV・CV・AI参照セッション */
function ga4Metrics_(propertyId, dateStr) {
  if (!propertyId) return null;
  try {
    const req = {
      dateRanges: [{ startDate: dateStr, endDate: dateStr }],
      metrics: [{ name: 'sessions' }, { name: 'screenPageViews' }, { name: 'conversions' }],
    };
    const res = AnalyticsData.Properties.runReport(req, 'properties/' + propertyId);
    const row = (res.rows && res.rows[0]) ? res.rows[0].metricValues : null;
    const base = {
      sessions: row ? Number(row[0].value) : 0,
      pv: row ? Number(row[1].value) : 0,
      cv: row ? Math.round(Number(row[2].value)) : 0,
      ai: 0, breakdown: {},
    };
    // AI参照元の内訳
    const res2 = AnalyticsData.Properties.runReport({
      dateRanges: [{ startDate: dateStr, endDate: dateStr }],
      dimensions: [{ name: 'sessionSource' }],
      metrics: [{ name: 'sessions' }],
    }, 'properties/' + propertyId);
    (res2.rows || []).forEach(function (r) {
      const src = String(r.dimensionValues[0].value).toLowerCase();
      const n = Number(r.metricValues[0].value);
      AI_REFERRERS.forEach(function (dom) {
        if (src.indexOf(dom) >= 0) {
          base.ai += n;
          base.breakdown[dom] = (base.breakdown[dom] || 0) + n;
        }
      });
    });
    return base;
  } catch (e) {
    Logger.log('GA4取得失敗（' + propertyId + '）: ' + e);
    return null;
  }
}

/** Search Console: 表示・クリック・CTR・平均順位（データ確定に3日ほどかかる） */
function gscMetrics_(siteUrl, dateStr) {
  if (!siteUrl) return null;
  try {
    const res = SearchConsole.Searchanalytics.query(
      { startDate: dateStr, endDate: dateStr }, siteUrl);
    const r = (res.rows && res.rows[0]) || {};
    return {
      impressions: Math.round(r.impressions || 0),
      clicks: Math.round(r.clicks || 0),
      ctr: r.ctr ? Math.round(r.ctr * 1000) / 10 : 0,
      position: r.position ? Math.round(r.position * 10) / 10 : 0,
    };
  } catch (e) {
    Logger.log('GSC取得失敗（' + siteUrl + '）: ' + e);
    return null;
  }
}

function updateKpi() {
  const gaDate = ymd_(daysAgo_(1));  // GA4は前日分
  const scDate = ymd_(daysAgo_(3));  // GSCは3日前が確定値
  const kpi = sheet_('KPIレポート');
  const aio = sheet_('AIO計測');
  const totals = { sessions: 0, pv: 0, cv: 0, clicks: 0, impressions: 0, ai: 0 };

  Object.keys(GSC_SITES).forEach(function (site) {
    const g = ga4Metrics_(GA4_PROPERTIES[site], gaDate) || { sessions: 0, pv: 0, cv: 0, ai: 0, breakdown: {} };
    const s = gscMetrics_(GSC_SITES[site], scDate) || { impressions: 0, clicks: 0, ctr: 0, position: 0 };

    kpi.appendRow([gaDate, SITES[site] || site, g.sessions, g.pv, s.impressions, s.clicks,
                   s.ctr + '%', s.position, g.cv,
                   'GSCは' + scDate + '時点（確定待ちのため3日前）']);
    aio.appendRow([gaDate, SITES[site] || site, '', g.ai,
                   g.breakdown['chatgpt.com'] || g.breakdown['chat.openai.com'] || 0,
                   g.breakdown['perplexity.ai'] || 0,
                   g.breakdown['gemini.google.com'] || 0,
                   g.breakdown['copilot.microsoft.com'] || 0, '']);

    Object.keys(totals).forEach(function (k) {
      totals[k] += (g[k] !== undefined ? g[k] : (s[k] || 0));
    });
  });

  writeDashboard_(totals, gaDate);
  Logger.log('KPI集計完了: ' + gaDate);
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
  const rows = [
    ['セッション（3サイト合計）', t.sessions],
    ['PV（3サイト合計）', t.pv],
    ['CV（3サイト合計）', t.cv],
    ['検索表示回数（3サイト合計）', t.impressions],
    ['検索クリック（3サイト合計）', t.clicks],
    ['AI経由セッション（3サイト合計）', t.ai],
    ['公開記事数（台帳の公開済み）', kwRows_().filter(function (r) {
      return String(r[2]).trim() === '公開済み';
    }).length],
  ];
  if (sh.getLastRow() > 1) sh.deleteRows(2, sh.getLastRow() - 1);
  rows.forEach(function (r) {
    const before = prev[r[0]];
    const diff = (before === undefined) ? '' : (r[1] - before >= 0 ? '+' : '') + (r[1] - before);
    sh.appendRow([r[0], r[1], diff, new Date(), dateStr + ' 時点']);
  });
}
