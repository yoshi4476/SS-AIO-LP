/* 診断クイズ共通エンジン
   ページ側で window.QUIZ を定義して読み込む:
   { type: "meo"|"aio", max: 100,
     questions: [{ t: "設問", o: [["選択肢", 点数], ...] }],
     bands: [[最低%, { name, desc, acts:[3つ] }], ...],  // %降順
     links: [["記事名", "/path/"], ...] } */
(function () {
  var cfg = window.QUIZ;
  var body = document.getElementById("qbody");
  var bar = document.getElementById("qbar");
  if (!cfg || !body || !bar) return;
  body.setAttribute("aria-live", "polite");

  var i = 0, score = 0, started = false;

  function show() {
    var q = cfg.questions[i];
    bar.style.width = (i / cfg.questions.length * 100) + "%";
    var html = '<div class="q-num">Q' + (i + 1) + " / " + cfg.questions.length +
      '</div><div class="q-title">' + q.t + '</div><div class="q-opts">';
    q.o.forEach(function (o, j) { html += '<button class="q-opt" data-j="' + j + '">' + o[0] + "</button>"; });
    body.innerHTML = html + "</div>";
    // キーボード操作: 画面差し替えでフォーカスが失われないよう先頭の選択肢へ移す
    if (started) {
      var first = body.querySelector(".q-opt");
      if (first) first.focus();
    }
    started = true;
    body.querySelectorAll(".q-opt").forEach(function (b) {
      b.addEventListener("click", function () {
        score += q.o[+b.dataset.j][1];
        i++;
        i < cfg.questions.length ? show() : result();
      });
    });
  }

  function result() {
    bar.style.width = "100%";
    var pct = Math.min(100, Math.round(score / cfg.max * 100));
    var band = cfg.bands.filter(function (b) { return pct >= b[0]; })[0][1];
    if (window.trackLead) {
      window.trackLead("diagnosis_complete", { diagnosis_type: cfg.type, score: pct, grade: band.name });
      window.trackLead("lead_capture", { lead_route: "diagnosis", diagnosis_type: cfg.type });
      window.trackLead("lead_diagnosis", { diagnosis_type: cfg.type, score: pct });
    }
    var C = 2 * Math.PI * 62, off = C * (1 - pct / 100);

    // 85点以下は無料相談へ強く誘導（改善余地の可視化 + 専用CTAパネル）
    var nudge = "", btns;
    if (pct <= 85) {
      if (window.trackLead) window.trackLead("diagnosis_nudge_shown", { diagnosis_type: cfg.type, score: pct });
      nudge =
        '<div style="background:linear-gradient(135deg,#0b2447,#1d4ed8);color:#fff;border-radius:16px;padding:1.4rem 1.5rem;margin:1.6rem 0 .6rem;text-align:center;">' +
        '<div style="font-family:var(--head);font-weight:900;font-size:1.15rem;">改善余地が <span style="font-size:1.5em;color:#ffc36b;">' + (100 - pct) + '点分</span> 見つかりました</div>' +
        '<p style="font-size:.9rem;color:rgba(255,255,255,.88);margin:.5em auto .9em;max-width:32em;">スコアの伸びしろは、そのまま集客の伸びしろです。この診断結果をもとに、<b>どこから直すと最短で効果が出るか</b>を無料相談で具体的にご提案します（現状分析レポート付き・しつこい営業なし）。</p>' +
        '<a class="btn btn-primary" href="/lp/#form" data-cta="diagnosis_' + cfg.type + '_nudge_lp" style="font-size:1.02rem;">無料相談で改善プランをもらう <span class="arw">→</span></a>' +
        '<div style="font-size:.75rem;color:rgba(255,255,255,.65);margin-top:.7rem;">お電話でも: 06-4305-7547（9:00〜20:00 / 土日祝休）</div></div>';
      btns = '<div class="btn-row" style="justify-content:center;">' +
        '<a class="btn btn-ghost" href="' + (cfg.crossUrl || "/site-audit/") + '" data-cta="diagnosis_' + cfg.type + '_cross">' + (cfg.crossLabel || "サイトの点数も診断する") + "</a></div>";
    } else {
      btns = '<div class="btn-row" style="justify-content:center;">' +
        '<a class="btn btn-primary" href="/lp/#form" data-cta="diagnosis_' + cfg.type + '_result_lp">さらに伸ばす施策を無料相談する <span class="arw">→</span></a>' +
        '<a class="btn btn-ghost" href="' + (cfg.crossUrl || "/site-audit/") + '" data-cta="diagnosis_' + cfg.type + '_cross">' + (cfg.crossLabel || "サイトの点数も診断する") + "</a></div>";
    }

    body.innerHTML =
      '<div class="result-type"><div class="rt-label">RESULT</div>' +
      "<h2>" + band.name + "</h2>" +
      "<p style='color:var(--muted);max-width:34em;margin:0 auto;'>" + band.desc + "</p>" +
      '<div class="score-ring"><svg width="150" height="150">' +
      '<circle cx="75" cy="75" r="62" fill="none" stroke="#eef2f8" stroke-width="12"/>' +
      '<circle cx="75" cy="75" r="62" fill="none" stroke="#2563eb" stroke-width="12" stroke-linecap="round" stroke-dasharray="' + C + '" stroke-dashoffset="' + off + '"/></svg>' +
      '<div class="sv">' + pct + '<small>/100<br>スコア</small></div></div>' +
      '<h3 style="font-family:var(--head);margin:.5em 0 .4em;">最初にやるべき3つ</h3>' +
      '<ol class="action-list">' + band.acts.map(function (a) { return "<li>" + a + "</li>"; }).join("") + "</ol>" +
      nudge +
      '<p style="margin:1.2rem 0 .6rem;font-size:.9rem;">おすすめ記事: ' +
      cfg.links.map(function (l) { return '<a href="' + l[1] + '">' + l[0] + "</a>"; }).join(" ／ ") + "</p>" +
      btns +
      '<p style="font-size:.78rem;color:var(--muted);margin-top:1rem;">※ 本診断は回答にもとづく簡易判定です。無料相談では実データで詳細分析します。</p></div>';
    // 点数と「最初の3つ」を見た直後に置く。ここが最も関心の高い瞬間で、
    // 相談は身構えても、自分の点数の続きを受け取ることには抵抗が小さい。
    // 無料相談の訴求より後ろに置くと、この瞬間を過ぎてしまう。
    if (window.leadCapture) {
      var label = cfg.type === "aio" ? "AI検索の対応度" : "マップ集客の整備度";
      var lc = window.leadCapture({
        title: "この結果の詳しい読み方を、メールで受け取る",
        sub: "点数の内訳と、" + band.acts.length + "つの手を進める順番をお送りします",
        formType: label + "チェックの結果送付",
        route: "diagnosis_" + cfg.type,
        detail: label + "チェック " + pct + "点／" + band.name,
      });
      var acts = body.querySelector(".action-list");
      if (acts) acts.parentNode.insertBefore(lc, acts.nextSibling);
      else body.querySelector(".result-type").appendChild(lc);
    }
    var h2 = body.querySelector("h2");
    if (h2) { h2.setAttribute("tabindex", "-1"); h2.focus(); }
  }
  show();
})();

