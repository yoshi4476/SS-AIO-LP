// 管制塔の受付（hub.gs + contact.hub.gs）を、Apps Script の代わりの作り物の上で動かす（門 gates_history_h82_leads が使う）。
// node gas_leads_harness.js <hub.gs> <contact.hub.gs> < 筋書き（JSON）
// 筋書き: { gemini: { "<本文に含まれる語>": {kind, reason} | "fail" }, props: {...}, posts: [<doPost の本文>…], calls: [[関数名, 引数…]…] }
// 返す: { results, rows（問い合わせタブ）, probe, mails, fetches, calls }
const vm = require('vm'), fs = require('fs');
const plan = JSON.parse(fs.readFileSync(0, 'utf8'));
const HEAD = ['受信日時', 'サイト', '種別', '会社名', 'お名前', 'ご担当者様', 'メールアドレス', '電話番号', 'ご相談内容',
              '診断・詳細', '特典', '送信元ページ', '温度', '対応状況'];
const tabs = {
  'サイト一覧': [['サイトID', 'サイト名', 'ドメイン', 'テーマ', '公開記事数', '最終公開日', 'GA4', 'GSC'],
                ['ai-lab', 'AI集客ラボ', 'ai.7senses.co.jp', '', '', '', '', ''],
                ['subsidy', 'AI導入補助金サポート', 'lp.7senses.co.jp', '', '', '', '', ''],
                ['corporate', 'コーポレート', 'corp.7senses.co.jp', '', '', '', '', ''],
                ['partner', '別事業', 'partner.example.jp', '', '', '', '', '']],
  // 筋書きの行の受信日時は ISO の文字列で渡し、ここで日時にする（台帳は日時で持つ）
  '問い合わせ': [HEAD.slice()].concat((plan.rows || []).map((r) => [new Date(r[0])].concat(r.slice(1)))),
};
const sheet = (name) => {
  if (!tabs[name]) tabs[name] = [];
  const t = tabs[name];
  return {
    getLastRow: () => t.length,
    appendRow: (r) => { t.push(r.slice()); },
    getRange: (r, c, nr, nc) => ({
      getValues: () => t.slice(r - 1, r - 1 + (nr || 1)).map((x) => {
        const y = (x || []).slice(c - 1, c - 1 + (nc || 1)); while (y.length < (nc || 1)) y.push(''); return y; }),
      getValue: () => ((t[r - 1] || [])[c - 1] === undefined ? '' : t[r - 1][c - 1]),
      setValue: (v) => { while (t[r - 1].length < c) t[r - 1].push(''); t[r - 1][c - 1] = v; },
      setValues: (vs) => { vs.forEach((row, i) => row.forEach((v, j) => { t[r - 1 + i][c - 1 + j] = v; })); },
    }),
  };
};
const book = { getSheetByName: (n) => (tabs[n] ? sheet(n) : null), insertSheet: (n) => { tabs[n] = []; return sheet(n); },
               getUrl: () => 'https://docs.google.com/spreadsheets/d/x' };
const props = Object.assign({}, plan.props || {});
const mails = [], fetches = [];
const ctx = {
  console: { log() {}, error() {} },
  ContentService: { createTextOutput: (o) => ({ setMimeType: () => JSON.parse(o) }), MimeType: { JSON: 'json' } },
  SpreadsheetApp: { openById: () => book, getActiveSpreadsheet: () => book },
  PropertiesService: { getScriptProperties: () => ({ getProperty: (k) => (k in props ? props[k] : null),
                                                     setProperty: (k, v) => { props[k] = String(v); },
                                                     deleteProperty: (k) => { delete props[k]; } }) },
  CacheService: { getScriptCache: () => ({ get: () => null, put: () => {} }) },
  Utilities: { formatDate: (d, tz, f) => {
    const j = new Date(d.getTime() + 9 * 3600e3), p = (n) => String(n).padStart(2, '0');
    const Y = j.getUTCFullYear(), M = p(j.getUTCMonth() + 1), D = p(j.getUTCDate()), h = p(j.getUTCHours()), m = p(j.getUTCMinutes());
    return f.replace('yyyy', Y).replace('MM', M).replace('dd', D).replace('HH', h).replace('mm', m);
  } },
  MailApp: { sendEmail: (o) => mails.push({ to: o.to, subject: o.subject, body: o.body }) },
  UrlFetchApp: { fetch: (url, opt) => {
    fetches.push(url);
    if (url.indexOf('generativelanguage') >= 0) {
      const text = JSON.parse(opt.payload).contents[0].parts[0].text;
      const hit = Object.keys(plan.gemini || {}).find((k) => text.indexOf(k) >= 0);
      const ans = hit ? plan.gemini[hit] : { kind: '相談', reason: '当社のサービスの相談' };
      if (ans === 'fail') return { getResponseCode: () => 500, getContentText: () => '' };
      if (ans === 'throw') throw new Error('Address unavailable');
      if (ans === 'garbage') return { getResponseCode: () => 200, getContentText: () => '{"candidates":[{"content":{"parts":[{"text":"はい"}]}}]}' };
      const body = { candidates: [{ content: { parts: [{ text: JSON.stringify(ans) }] } }] };
      return { getResponseCode: () => 200, getContentText: () => JSON.stringify(body) };
    }
    return { getResponseCode: () => 200, getContentText: () => '{}' };
  } },
  Session: { getEffectiveUser: () => ({ getEmail: () => 'me@example.com' }) },
  LockService: { getScriptLock: () => ({ tryLock: () => true, waitLock: () => {}, releaseLock: () => {} }) },
};
vm.createContext(ctx);
for (const f of process.argv.slice(2)) vm.runInContext(fs.readFileSync(f, 'utf8'), ctx, { filename: f });
const secret = vm.runInContext('SHARED_SECRET', ctx);
const results = (plan.posts || []).map((b) => {
  const body = JSON.parse(JSON.stringify(b));
  if (body.secret === '$SECRET') body.secret = secret;
  try { return ctx.doPost({ postData: { contents: JSON.stringify(body) } }); } catch (e) { return { thrown: String(e) }; }
});
const calls = (plan.calls || []).map((c) => { try { return ctx[c[0]].apply(null, c.slice(1)); } catch (e) { return { thrown: String(e) }; } });
console.log(JSON.stringify({ results, calls, rows: tabs['問い合わせ'].slice(1).map((r) => r.map((v) => (v && v.toISOString ? v.toISOString() : v))),
                             probe: (tabs['疎通確認'] || []).slice(1).map((r) => r.slice(1)), mails, fetches, props }));
