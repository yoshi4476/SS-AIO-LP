/* LP v2: URLを入れるだけの実測診断（/api/audit）
 *
 * 流れ: 計測盤が順に点灯 → 結果の到着で各項目が合否に変わる → 下に結果の詳細。
 * 「今日できる修正」1つは無料で見せ、残りの直し方は連絡先と引き換えに開く（先に価値を渡す）。
 * 点数が高い会社には正直に「急がなくていい」と伝える。売り込みより信頼のほうが後で効く。
 *
 * 画面に出す文字は textContent で入れる。API の detail だけは API 側で無害化済みの HTML。 */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var form = $("#lx-scan-form");
  if (!form) return;
  var input = $("#lx-url"), ind = $("#lx-industry"), btn = $("#lx-go"), err = $("#lx-err");
  var items = $$(".lx-item");
  var result = $("#scan");
  var KEY = "lx_scan_last";
  var ran = false;

  // 業種ごとに、見込み客がAIや検索に打ち込みそうな質問（例）。数字や事実は入れない
  var ASK = {
    "クリニック・歯科医院": "「◯◯駅の近くで土曜も診てくれる歯医者は？」",
    "不動産": "「◯◯市でマンションを売るならどこに相談する？」",
    "工務店・リフォーム": "「◯◯市で高気密の家を建てる工務店は？」",
    "士業・コンサル": "「◯◯市で相続に強い税理士は？」",
    "BtoB・IT": "「中小企業向けの勤怠管理、どれがいい？」",
    "店舗・飲食・美容": "「◯◯駅で個室のあるランチは？」"
  };

  function ev(name, params) { try { if (window.gtag) window.gtag("event", name, params || {}); } catch (e) {} }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function store(v) { try { if (v) localStorage.setItem(KEY, JSON.stringify(v)); return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { return null; } }

  // 計測中: 項目を1つずつ照らす（応答が来るまで回り続ける）
  var spin = null;
  function startScan() {
    items.forEach(function (li) { li.classList.remove("is-ok", "is-ng", "is-scan"); });
    var i = 0;
    spin = setInterval(function () {
      items.forEach(function (li) { li.classList.remove("is-scan"); });
      items[i % items.length].classList.add("is-scan");
      i++;
    }, 170);
  }
  function stopScan() { clearInterval(spin); items.forEach(function (li) { li.classList.remove("is-scan"); }); }

  function paint(checks) {
    checks.forEach(function (c, i) {
      setTimeout(function () {
        var li = items[i];
        if (li) li.classList.add(c.ok ? "is-ok" : "is-ng");
      }, i * 70);
    });
    $$(".lx-group").forEach(function (g) {
      var name = g.getAttribute("data-group");
      var got = 0, all = 0;
      checks.forEach(function (c) { if (c.group === name) { all += c.pts; if (c.ok) got += c.pts; } });
      var s = $("h3 span", g);
      if (s && all) s.textContent = got + " / " + all;
    });
    var foot = $(".lx-console-foot");
    if (foot) foot.textContent = "計測しました（" + new Date().toLocaleString("ja-JP") + "）。詳しい結果は下に出ています。";
  }

  function render(d, url) {
    var box = $("#lx-res");
    box.textContent = "";
    var checks = d.checks || [];
    var ng = checks.filter(function (c) { return !c.ok; }).sort(function (a, b) { return b.pts - a.pts; });
    var industry = ind.value;

    // 上段: 点数・評価・3群の内訳
    var top = el("div", "lx-res-top");
    var ring = el("div", "lx-ring");
    var r = 64, len = 2 * Math.PI * r, pct = Math.max(0, Math.min(100, d.score)) / 100;
    ring.innerHTML = '<svg viewBox="0 0 150 150" aria-hidden="true"><circle cx="75" cy="75" r="64" fill="none" stroke="#dfe6ef" stroke-width="12"/>' +
      '<circle cx="75" cy="75" r="64" fill="none" stroke="' + (d.critical && d.critical.length ? "#c2362b" : "#2563eb") +
      '" stroke-width="12" stroke-linecap="round" stroke-dasharray="' + (len * pct).toFixed(1) + " " + len.toFixed(1) + '"/></svg>';
    var v = el("div", "v"); var b = el("b", null, String(d.score)); v.appendChild(b); v.appendChild(el("small", null, "/ 100点"));
    ring.appendChild(v);
    var info = el("div");
    info.appendChild(el("p", "lx-res-grade", d.grade));
    var u = el("p", "lx-res-url"); u.innerHTML = d.url; info.appendChild(u);
    var bars = el("div", "lx-bars");
    ["AIが入れるか", "検索に出るか", "内容を読み取れるか"].forEach(function (g) {
      var got = 0, all = 0;
      checks.forEach(function (c) { if (c.group === g) { all += c.pts; if (c.ok) got += c.pts; } });
      var row = el("div", "lx-bar");
      row.appendChild(el("span", null, g));
      var i = el("i"); i.style.setProperty("--w", "0%"); row.appendChild(i);
      row.appendChild(el("em", null, got + "/" + all));
      bars.appendChild(row);
      requestAnimationFrame(function () { setTimeout(function () { i.style.setProperty("--w", (all ? got / all * 100 : 0) + "%"); }, 60); });
    });
    info.appendChild(bars);
    // 同業の平均（10社分たまった業種だけ。たまる前は何も出さない）
    var bench = el("p", "lx-bench");
    info.appendChild(bench);
    fetch("/api/bench").then(function (r) { return r.json(); }).then(function (b) {
      var g = (b && b.industries) || {};
      var hit = (industry && g[industry]) ? [industry, g[industry]] : (g["全体"] ? ["診断した全社", g["全体"]] : null);
      if (!hit) return;
      var diff = d.score - hit[1].avg;
      bench.textContent = (hit[0] === "診断した全社" ? "診断した全社" : "同業（" + hit[0] + "）") + "の平均 " + hit[1].avg + "点（" +
        hit[1].n + "社・" + (b.since || "").replace(/-/g, "/") + "以降の診断）。御社は" +
        (diff === 0 ? "平均と同じです。" : "平均より" + Math.abs(diff) + "点" + (diff > 0 ? "高い" : "低い") + "です。");
    }).catch(function () {});
    top.appendChild(ring); top.appendChild(info);
    box.appendChild(top);

    if (d.critical && d.critical.length) {
      var al = el("div", "lx-alert");
      al.appendChild(el("strong", null, "読まれない原因があります: "));
      al.appendChild(document.createTextNode(d.critical.join("／") + "。この状態では、記事や情報をどれだけ整えても、AIの回答にも検索にも出ません。最初にここを直してください。"));
      box.appendChild(al);
    } else if (d.score >= 85) {
      box.appendChild(el("div", "lx-calm", "土台は整っています。急いで何かを頼む必要はありません。次の差は「その会社にしか書けない事実（数字・事例・一次データ）」が載っているかで付きます。気になったときに、いつでもご相談ください。"));
    }

    var cols = el("div", "lx-cols");
    // 左: 今日できる修正（無料）と、残りの項目（直し方は連絡先と引き換え）
    var left = el("div");
    if (ng.length) {
      var now = el("div", "lx-card lx-fix-now");
      now.appendChild(el("span", "tag tag-free", "今日できる修正（無料）"));
      now.appendChild(el("h3", null, ng[0].name));
      if (ng[0].detail) { var dt = el("p", "why"); dt.innerHTML = "いまの状態: " + ng[0].detail; now.appendChild(dt); }
      now.appendChild(el("p", null, ng[0].advice));
      left.appendChild(now);
    }
    var rest = el("div", "lx-card lx-locked");
    rest.style.marginTop = ng.length ? "1rem" : "0";
    rest.appendChild(el("span", "tag tag-lock", ng.length > 1 ? "残り" + (ng.length - 1) + "項目の直し方" : "全項目の結果"));
    rest.appendChild(el("h3", null, ng.length > 1 ? "ほかに直すところ" : "見た項目と結果"));
    var ul = el("ul", "lx-list");
    ng.slice(1).concat(checks.filter(function (c) { return c.ok; })).forEach(function (c) {
      var li = el("li", c.ok ? "ok" : "ng");
      li.appendChild(el("span", "mk", c.ok ? "✓" : "!"));
      var t = el("div", null, c.name + "（" + c.pts + "点）");
      if (!c.ok) t.appendChild(el("span", "ad", c.advice));
      li.appendChild(t); ul.appendChild(li);
    });
    rest.appendChild(ul);
    if (ng.length > 1) rest.appendChild(gate(d, url, ng, rest));
    else rest.classList.remove("lx-locked");
    left.appendChild(rest);

    // 右: 見込み客の質問（例）と次の一歩
    var right = el("div", "lx-card");
    right.appendChild(el("h3", null, "この結果を、問い合わせにつなげるには"));
    right.appendChild(el("p", null, "技術の土台が整っていても、AIや検索が答えに使うのは「その会社にしか書けない事実」です。料金の決まり方・対応エリア・実績の数字が文字で書かれているかで、候補に入るかが決まります。"));
    if (ASK[industry]) {
      var ex = el("p", "lx-examples");
      ex.appendChild(el("b", null, industry + "の見込み客は、たとえばこう聞いています（例）"));
      ex.appendChild(document.createElement("br"));
      ex.appendChild(document.createTextNode(ASK[industry]));
      right.appendChild(ex);
    }
    var sh = el("div", "lx-share");
    var consult = el("a", "primary", "結果をもとに無料で相談する →");
    consult.href = "#form"; consult.setAttribute("data-cta", "lp_scan_consult");
    var copy = el("button", null, "結果のリンクを社内に共有");
    copy.type = "button";
    copy.addEventListener("click", function () {
      var link = location.origin + "/lp/?check=" + encodeURIComponent(url) + "#scan";
      var done = function () { copy.textContent = "リンクをコピーしました"; ev("lp_scan_share"); };
      if (navigator.clipboard) navigator.clipboard.writeText(link).then(done, function () { prompt("このリンクを共有してください", link); });
      else prompt("このリンクを共有してください", link);
    });
    sh.appendChild(consult); sh.appendChild(copy);
    right.appendChild(sh);
    right.appendChild(el("p", "lx-measured", "計測日時: " + new Date(d.measured_at || Date.now()).toLocaleString("ja-JP") +
      "。ページの公開状態が変わると結果も変わります。点数は技術の土台だけを見たもので、検索順位やAIの回答を保証するものではありません。"));

    cols.appendChild(left); cols.appendChild(right);
    box.appendChild(cols);

    // 下の相談フォームに、結果の要点を下書きしておく（書き直してもらってよい）
    var msg = $("#form textarea[name=message]");
    if (msg && !msg.value.trim()) {
      msg.value = "【サイト診断の結果】" + url + " … " + d.score + "点" + (ng.length ? "（未対応: " + ng.slice(0, 4).map(function (c) { return c.name; }).join("・") + "）" : "") + (industry ? "／業種: " + industry : "");
    }
  }

  // 残りの直し方は、連絡先と引き換えに開く
  function gate(d, url, ng, card) {
    var g = el("div", "lx-gate");
    g.appendChild(el("p", null, "残りの直し方と、御社向けの優先順位をお送りします。この画面でもすぐ開きます。"));
    var f = el("form");
    f.noValidate = true;
    f.innerHTML =
      '<input type="text" name="_gotcha" tabindex="-1" autocomplete="off" aria-hidden="true" style="position:absolute;left:-9999px">' +
      '<input type="text" name="name" placeholder="お名前" required autocomplete="name" aria-label="お名前">' +
      '<input type="text" name="company" placeholder="会社名・店舗名" required autocomplete="organization" aria-label="会社名・店舗名">' +
      '<input type="email" name="email" placeholder="メールアドレス" required autocomplete="email" aria-label="メールアドレス">' +
      '<label class="consent"><input type="checkbox" required> <span><a href="/privacy/" target="_blank" rel="noopener">プライバシーポリシー</a>に同意する</span></label>' +
      '<button type="submit" class="lx-go" data-cta="lp_scan_gate">残りの直し方を見る</button>' +
      '<p class="note">営業電話はしません。お送りするのは結果と直し方だけです。</p>' +
      '<p class="msg" role="status" aria-live="polite"></p>';
    var m = $(".msg", f), b = $("button", f);
    f.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!f.checkValidity()) { m.textContent = "未入力の項目があります。"; return; }
      b.disabled = true; m.textContent = "送信しています…";
      var fd = new FormData(f);
      fd.append("form_type", "LP実測診断の結果送付");
      fd.append("audit_url", url);
      fd.append("audit_score", d.score);
      fd.append("audit_grade", d.grade);
      fd.append("audit_fixes", ng.map(function (c) { return "・" + c.name + "（" + c.pts + "点）: " + c.advice; }).join("\n"));
      fd.append("message", "【サイト診断】" + url + " / " + d.score + "点 / " + d.grade +
        (ind.value ? " / 業種: " + ind.value : "") + " / 未対応: " + ng.map(function (c) { return c.name; }).join("・"));
      fetch("/api/lead", { method: "POST", body: fd })
        .then(function (r) { if (!r.ok) return r.text().then(function (t) { throw new Error(t); }); })
        .then(function () {
          card.classList.remove("lx-locked");
          g.textContent = "";
          var ok = el("p", null, "お送りしました。直し方は上に開いています。");
          ok.style.fontWeight = "700"; ok.style.color = "#12805c";
          g.appendChild(ok);
          g.appendChild(el("p", "note", "自社で直すのが難しい項目は、そのまま無料相談でお手伝いします（2営業日以内にご連絡・営業電話なし）。"));
          if (window.trackLead) { window.trackLead("lead_form_submit", { lead_route: "lp_scan" }); window.trackLead("lead_capture", { lead_route: "lp_scan", form_type: "LP実測診断の結果送付" }); }
          ev("lp_scan_unlock", { score: d.score });
        })
        .catch(function (x) {
          b.disabled = false;
          m.textContent = String(x.message || "").slice(0, 120) || "送信できませんでした。恐れ入りますが 06-4305-7547 までご連絡ください。";
        });
    });
    g.appendChild(f);
    return g;
  }

  function run(url) {
    err.textContent = "";
    url = (url || "").trim();
    if (!url) { err.textContent = "URLを入れてください。"; input.focus(); return; }
    ran = true;
    btn.disabled = true; btn.textContent = "計測しています…";
    startScan();
    ev("lp_scan_start");
    fetch("/api/audit", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: url, industry: ind.value, ref: window.ssRef ? window.ssRef() : "" }) })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || "診断できませんでした"); return j; }); })
      .then(function (d) {
        stopScan(); paint(d.checks || []);
        render(d, url);
        result.hidden = false;
        setTimeout(function () { result.scrollIntoView({ behavior: "smooth", block: "start" }); }, 900);
        store({ url: url, score: d.score, at: Date.now() });
        ev("lp_scan_complete", { score: d.score });
      })
      .catch(function (x) {
        stopScan();
        err.textContent = x.message + "（URLをご確認ください。社内ネットワーク限定のページは診断できません）";
      })
      .then(function () { btn.disabled = false; btn.textContent = "もう一度診断する"; });
  }

  form.addEventListener("submit", function (e) { e.preventDefault(); run(input.value); });

  // 共有リンク（?check=）で来たら、そのURLで自動で測る
  var q = new URLSearchParams(location.search).get("check");
  if (q) { input.value = q; run(q); }

  // 前回の結果がある人には、続きから
  var last = store();
  var again = $("#lx-again");
  if (!q && last && last.url && again) {
    var dd = new Date(last.at);
    $("span", again).textContent = "前回（" + (dd.getMonth() + 1) + "/" + dd.getDate() + "）の診断: " + last.url.replace(/^https?:\/\//, "").slice(0, 40) + " … " + last.score + "点";
    again.style.display = "block";
    $("button", again).addEventListener("click", function () { input.value = last.url; run(last.url); });
  }

  // 帯のボタンなどから診断へ
  $$('a[href="#scan-start"]').forEach(function (a) {
    a.addEventListener("click", function (e) {
      e.preventDefault();
      form.scrollIntoView({ behavior: "smooth", block: "center" });
      setTimeout(function () { input.focus({ preventScroll: true }); }, 500);
    });
  });

  // 離脱しかけたとき（PCだけ・1回だけ・まだ測っていない人だけ）
  var exit = $("#lx-exit");
  if (exit && window.matchMedia && matchMedia("(pointer:fine)").matches) {
    var shown = false;
    try { shown = sessionStorage.getItem("lx_exit") === "1"; } catch (e) {}
    document.addEventListener("mouseout", function (e) {
      if (shown || ran || e.relatedTarget || e.clientY > 0) return;
      shown = true;
      try { sessionStorage.setItem("lx_exit", "1"); } catch (x) {}
      exit.hidden = false; ev("lp_exit_shown");
      var ei = $("input", exit); if (ei) ei.focus();
    });
    var close = function () { exit.hidden = true; };
    $(".lx-exit-close", exit).addEventListener("click", close);
    exit.addEventListener("click", function (e) { if (e.target === exit) close(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });
    $("form", exit).addEventListener("submit", function (e) {
      e.preventDefault(); close();
      input.value = $("input", exit).value;
      form.scrollIntoView({ behavior: "smooth", block: "center" });
      run(input.value);
    });
  }
})();
