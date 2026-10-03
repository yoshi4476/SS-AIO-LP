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
  // 業種 → 業種別チェックリスト（/download/?ind=）
  var CHECKLIST = { dental: "dental", clinic: "clinic", fudosan: "fudosan", koumuten: "koumuten", reform: "koumuten",
    zeirishi: "shigyou", sharoushi: "shigyou", gyousei: "shigyou", shihou: "shigyou", bengoshi: "shigyou" };
  // 結果画面の次の一歩を押したか（段階ごとの数を週次で出すため。F5）
  out.addEventListener("click", function (e) {
    var a = e.target.closest ? e.target.closest("a[data-next]") : null;
    if (a) ev("ai_check_next", { step: a.getAttribute("data-next") });
  });

  // ロボットよけ（Cloudflare Turnstile）。サイトキーが設定されているときだけ、送信ボタンの上に出す
  fetch("/api/ai-check").then(function (r) { return r.json(); }).then(function (c) {
    if (!c || !c.turnstile) return;
    var box = document.createElement("div");
    box.className = "cf-turnstile";
    box.setAttribute("data-sitekey", c.turnstile);
    box.style.margin = "12px 0";
    btn.parentNode.insertBefore(box, btn);
    var s = document.createElement("script");
    s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js";
    s.async = true;
    document.head.appendChild(s);
  }).catch(function () {});

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
        try { if (window.turnstile) window.turnstile.reset(); } catch (x) {}   // 確認は1回きり。次の送信のためにやり直す
        if (!d.ok) {
          var more = d.limit
            ? '<div class="ac-next"><div class="btns"><a class="btn btn-primary" href="/lp/#form" data-cta="ai_check_limit_consult">詳しく調べたい方はお問い合わせ（無料）</a>' +
              '<a class="btn btn-ghost" href="/contact/" data-cta="ai_check_limit_contact">お問い合わせフォーム</a></div></div>'
            : "";
          if (d.limit) ev("ai_check_limit", { reason: d.limit });
          out.innerHTML = '<p class="ac-err" role="alert">' + esc(d.error || "チェックできませんでした。") + "</p>" + more;
          return;
        }
        if (window.trackLead) window.trackLead("lead_capture", { lead_route: "ai_check", form_type: "AI紹介チェック" });
        ev("ai_check_done", { industry: data.industry, cited: d.cited, mentioned: d.mentioned });
        var head = d.cited || d.mentioned
          ? "3問中" + d.cited + "問で、AIの答えの出典に御社のサイトが入っていました。"
          : "3問とも、AIの答えに御社のサイトも社名も出てきませんでした。";
        var html = '<div class="ac-sum"><p class="ac-big">' + esc(head) + "</p>" +
          '<p>回答に社名が出た質問は3問中' + d.mentioned + "問でした。AIの答えは日によって変わるため、これは今日の1回の結果です。</p>" +
          (d.used ? "<p>このメールアドレスでのチェック: " + d.used + "回目（" + (d.perEmail || 3) + "回まで）</p>" : "") + "</div>";
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
        // 結果に合わせて次の一歩を変える（0問: 直す順番 / 1〜2問: 残りを取る相談 / 3問: 競合との比較）。
        // 同じボタンを全員に出していたが、出典に入っていない人と全部入っている人では、次にやることが違う
        var ck = CHECKLIST[data.industry] || "";
        var step, nextHtml;
        if (!d.cited) {
          step = "fix_order";
          nextHtml = "<p><b>まず、AIが御社を出典に選べる状態かを確かめる順番があります。</b>業種別のチェックリスト（無料・PDF）に、直す順に並べています。</p><div class=\"btns\">" +
            '<a class="btn btn-primary" data-next="' + step + '" href="/download/' + (ck ? "?ind=" + ck : "") + '" data-cta="ai_check_next_checklist">直す順番のチェックリストを受け取る</a>' +
            '<a class="btn btn-ghost" data-next="' + step + '_consult" href="/lp/?src=ai_check_0#form" data-cta="ai_check_next_consult0">何から直すか無料で相談する</a></div>';
        } else if (d.cited < 3) {
          step = "partial";
          nextHtml = "<p><b>3問中" + d.cited + "問で出典に入っています。残りの質問で出典に入らない理由は、質問ごとに違います。</b>出典に入った質問と入らなかった質問の差を、無料でお伝えします。</p><div class=\"btns\">" +
            '<a class="btn btn-primary" data-next="' + step + '" href="/lp/?src=ai_check_partial#form" data-cta="ai_check_next_partial">残りの質問で出典に入る方法を相談する（無料）</a>' + lp + "</div>";
        } else {
          step = "all";
          nextHtml = "<p><b>3問とも出典に入っています。</b>次は、同じ地域の競合と比べて、ChatGPT・Claude を含めたほかのAIでも同じように出ているかを確かめる段階です。</p><div class=\"btns\">" +
            '<a class="btn btn-primary" data-next="' + step + '" href="/lp/?src=ai_check_all#form" data-cta="ai_check_next_compare">競合との比較を無料で依頼する</a>' + lp + "</div>";
        }
        ev("ai_check_next_shown", { step: step });
        html += '<div class="ac-next">' + nextHtml + "</div>";
        out.innerHTML = html;
        var h = out.querySelector(".ac-big");
        if (h) { h.setAttribute("tabindex", "-1"); h.focus(); }
      })
      .catch(function () {
        btn.disabled = false;
        try { if (window.turnstile) window.turnstile.reset(); } catch (x) {}   // 確認は1回きり。次の送信のためにやり直す
        out.innerHTML = '<p class="ac-err" role="alert">通信に失敗しました。時間をおいてもう一度お試しください。</p>';
      });
  });
})();
