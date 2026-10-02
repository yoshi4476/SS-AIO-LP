/* 「AIにどう紹介されているか」無料チェック（/tools/ai-check/）。/api/ai-check に送り、結果をその場で出す */
(function () {
  "use strict";
  var root = document.getElementById("ac");
  if (!root) return;
  var form = root.querySelector("form");
  var out = root.querySelector(".ac-out");
  var btn = form.querySelector("button[type=submit]");

  function ev(n, p) { try { if (window.gtag) window.gtag("event", n, p || {}); } catch (e) {} }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  var LPNAME = { medical: "クリニック・歯科医院", fudosan: "不動産会社", koumuten: "工務店・リフォーム会社", shigyou: "士業事務所" };

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (!form.checkValidity()) { form.reportValidity(); return; }
    var data = {};
    new FormData(form).forEach(function (v, k) { data[k] = v; });
    btn.disabled = true;
    out.innerHTML = '<p class="ac-wait" role="status">AIに3つの質問を聞いています（15〜30秒ほどかかります）…</p>';
    ev("ai_check_start", { industry: data.industry });
    fetch("/api/ai-check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        btn.disabled = false;
        if (!d.ok) { out.innerHTML = '<p class="ac-err" role="alert">' + esc(d.error || "チェックできませんでした。") + "</p>"; return; }
        if (window.trackLead) window.trackLead("lead_capture", { lead_route: "ai_check", form_type: "AI紹介チェック" });
        ev("ai_check_done", { industry: data.industry, cited: d.cited, mentioned: d.mentioned });
        var head = d.cited || d.mentioned
          ? "3問中" + d.cited + "問で、AIの答えの出典に御社のサイトが入っていました。"
          : "3問とも、AIの答えに御社のサイトも社名も出てきませんでした。";
        var html = '<div class="ac-sum"><p class="ac-big">' + esc(head) + "</p>" +
          '<p>回答に社名が出た質問は3問中' + d.mentioned + "問でした。AIの答えは日によって変わるため、これは今日の1回の結果です。</p></div>";
        d.results.forEach(function (r) {
          var src = r.sources.map(function (s) {
            return '<li class="' + (s.own ? "own" : s.portal ? "portal" : "") + '">' + esc(s.host) +
              (s.own ? '<span class="tag">御社</span>' : s.portal ? '<span class="tag">ポータル・比較</span>' : "") + "</li>";
          }).join("") || "<li>（出典なし）</li>";
          html += '<div class="ac-card"><p class="ac-q">「' + esc(r.q) + '」</p>' +
            '<p class="ac-mk"><span class="' + (r.cited ? "ok" : "ng") + '">出典に御社サイト ' + (r.cited ? "あり" : "なし") + "</span>" +
            '<span class="' + (r.mentioned ? "ok" : "ng") + '">回答に社名 ' + (r.mentioned ? "あり" : "なし") + "</span></p>" +
            '<p class="ac-l">AIが出典にしたサイト</p><ul class="ac-src">' + src + "</ul></div>";
        });
        var lp = d.lp ? '<a class="btn btn-ghost" href="/lp/' + d.lp + '/" data-cta="ai_check_lp_' + d.lp + '">' + esc(LPNAME[d.lp] || "") + "のSEO・AI検索対策を見る</a>" : "";
        html += '<div class="ac-next"><p><b>AIの答えに出るには、「調べられる質問」に答えるページと、会社の事実をAIが読める形に整えることが近道です。</b>' +
          "結果をもとに、何から直せばよいかを無料でお伝えします。</p><div class=\"btns\">" +
          '<a class="btn btn-primary" href="/lp/#form" data-cta="ai_check_consult">この結果について無料で相談する</a>' + lp + "</div></div>";
        out.innerHTML = html;
        var h = out.querySelector(".ac-big");
        if (h) { h.setAttribute("tabindex", "-1"); h.focus(); }
      })
      .catch(function () {
        btn.disabled = false;
        out.innerHTML = '<p class="ac-err" role="alert">通信に失敗しました。時間をおいてもう一度お試しください。</p>';
      });
  });
})();
