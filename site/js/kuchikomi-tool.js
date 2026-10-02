/* 口コミ返信文の作成ツール（/tools/kuchikomi-henshin/）
 *
 * ブラウザの中だけで動く。口コミの本文はどこにも送らない（外部のAIも呼ばない）。
 * 返信の型と NG 表現は、記事「病院・クリニックの口コミ返信｜違反になるNG表現と例文8つ」
 * （/meo/byoin-kuchikomi-henshin-reibun/）の表にそろえている。記事に無い言い換えを足さない。
 * 医療（病院・歯科・整骨院）では、口コミに症状や施術の言葉があっても返信では拾わない（守秘義務）。
 */
(function () {
  "use strict";
  var root = document.getElementById("kt");
  if (!root) return;

  function ev(name, params) { try { if (window.gtag) window.gtag("event", name, params || {}); } catch (e) {} }

  var IND = {
    clinic: { label: "病院・クリニック", medical: true, place: "当院", visit: "ご来院", contact: "受付またはお電話" },
    dental: { label: "歯科医院", medical: true, place: "当院", visit: "ご来院", contact: "受付またはお電話" },
    seikotsu: { label: "整骨院・接骨院", medical: true, place: "当院", visit: "ご来院", contact: "受付またはお電話" },
    food: { label: "飲食店", medical: false, place: "当店", visit: "ご来店", contact: "店舗またはお電話" },
    beauty: { label: "美容室・サロン", medical: false, place: "当店", visit: "ご来店", contact: "店舗またはお電話" },
    shop: { label: "その他の店舗・サービス", medical: false, place: "当店", visit: "ご利用", contact: "店舗またはお電話" }
  };

  // 口コミから拾ってよい観点。医療では症状・施術の言葉は拾わない（ここに入れない）
  var ASPECTS = [
    { re: /待ち時間|待たさ|待った|待ち/, word: "待ち時間" },
    { re: /受付|スタッフ|接客|対応/, word: "スタッフの対応" },
    { re: /清潔|きれい|綺麗|掃除/, word: "清潔さ", place: true },
    { re: /説明/, word: "ご説明" },
    { re: /予約/, word: "ご予約" },
    { re: /駐車場|駐車/, word: "駐車場" },
    { re: /雰囲気|居心地/, word: "雰囲気" },
    { re: /味|料理|美味|おいし/, word: "お料理", only: ["food"] },
    { re: /仕上がり|カット|カラー|ネイル/, word: "仕上がり", only: ["beauty"] },
    { re: /料金|値段|価格|会計/, word: "料金" }
  ];

  function aspectsOf(text, ind) {
    var out = [];
    ASPECTS.forEach(function (a) {
      if (a.only && a.only.indexOf(ind) < 0) return;
      if (a.re.test(text) && out.indexOf(a.word) < 0) out.push(a.word);
    });
    return out.slice(0, 2);
  }

  function aspectPhrase(list, i) {
    var w = list.map(function (x) { return x === "清潔さ" ? (i.place === "当院" ? "院内の清潔さ" : "店内の清潔さ") : x; });
    return w.join("や");
  }

  // 型（記事の表と同じ）: 高評価=感謝→具体への言及→次回の一言／待ち時間・対応=謝罪→改善の事実→お礼
  // 料金・内容の主張=反論せず窓口へ／事実誤認=相違を伝え窓口へ／暴言・中傷=返信より先に報告
  function build(o) {
    var i = IND[o.ind], p = i.place, v = i.visit, a = aspectPhrase(o.aspects, i);
    var sign = o.sign ? "\n" + o.sign : "";
    var name = o.name ? o.name + "の" : "";
    var thanks = ["このたびは" + v + "いただき、ありがとうございます。",
                  "このたびは" + name + "口コミをお寄せいただき、ありがとうございます。",
                  v + "いただき、また温かいお言葉をありがとうございます。"];
    var out = [];
    if (o.kind === "good") {
      var mid = a ? [a + "についてのお言葉、私たち一同の励みになります。",
                     a + "にふれていただき、うれしく思います。",
                     "とくに" + a + "について書いてくださったこと、スタッフにも共有いたしました。"]
                  : ["いただいたお言葉は、スタッフ一同の励みになります。",
                     "スタッフ全員で読ませていただきました。",
                     "いただいた内容は、スタッフにも共有いたしました。"];
      var end = i.medical ? ["またお困りのことがあれば、いつでもご相談ください。",
                             "今後も皆さまに安心してお越しいただけるよう努めてまいります。",
                             "今後とも" + p + "をよろしくお願いいたします。"]
                          : ["またのお越しを、スタッフ一同お待ちしております。",
                             "次回も楽しんでいただけるよう努めてまいります。",
                             "今後とも" + p + "をよろしくお願いいたします。"];
      for (var k = 0; k < 3; k++) out.push(thanks[k] + "\n" + mid[k] + "\n" + end[k] + sign);
    } else if (o.kind === "wait") {
      var w = a || "待ち時間やスタッフの対応";
      var heads = [w + "について、ご不快な思いをおかけし申し訳ございません。",
                   "このたびは" + w + "で、ご迷惑をおかけいたしました。",
                   "貴重なご意見をありがとうございます。" + w + "について、申し訳ございませんでした。"];
      var fix = "現在、【実際に行っている改善の内容（例：予約枠の見直し）】に取り組んでおります。";
      var tail = ["いただいたご意見は、スタッフ全員で共有いたしました。",
                  "お知らせくださったことに、感謝申し上げます。",
                  "今後も改善を続けてまいります。"];
      for (var k2 = 0; k2 < 3; k2++) out.push(heads[k2] + "\n" + fix + "\n" + tail[k2] + sign);
    } else if (o.kind === "claim") {
      var heads2 = ["このたびはご不安な思いをおかけし、申し訳ございません。",
                    "貴重なご意見をありがとうございます。ご期待に沿えず申し訳ございません。",
                    "このたびはご迷惑をおかけいたしました。"];
      var body2 = (i.medical ? "個別の内容については、この場ではお答えを控えさせていただきます。"
                              : "詳しい状況をうかがい、きちんと確認させていただきたいと考えております。") +
                  "\nお手数ですが、" + i.contact + "でご連絡いただけますでしょうか。";
      for (var k3 = 0; k3 < 3; k3++) out.push(heads2[k3] + "\n" + body2 + sign);
    } else if (o.kind === "wrong") {
      var heads3 = ["口コミをお寄せいただき、ありがとうございます。",
                    "ご意見をお寄せいただき、ありがとうございます。",
                    "このたびはご投稿いただき、ありがとうございます。"];
      var body3 = "記載いただいた内容の一部に、" + p + "で把握している事実と異なる点がございます。" +
                  "\n事実を確認いたしますので、お手数ですが" + i.contact + "でご連絡いただけますでしょうか。";
      for (var k4 = 0; k4 < 3; k4++) out.push(heads3[k4] + "\n" + body3 + sign);
    }
    return out;
  }

  // NG 表現（記事の表「返信で避けたい6つのNG表現」と同じ。医療だけのものは medical）
  var NG = [
    { re: /(良くなりましたか|治りましたか|のお薬|の症状|の治療は|の施術は)/, why: "守秘義務（受診の内容にふれている）", alt: "「ご来院ありがとうございます」", medical: true },
    { re: /(必ず|絶対に?)(治|改善|良く)/, why: "誇大広告（効果の保証）", alt: "「改善に向けて取り組んでおります」", medical: true },
    { re: /(一番|No\.?\s?1|ナンバーワン|日本一|地域一|最高の)/i, why: "比較優良広告（他より優れていると言う）", alt: "「丁寧な対応を心がけております」", medical: true },
    { re: /(良くなったとの|治ったとの|改善したとの)/, why: "体験談広告に近い表現", alt: "「お言葉をありがとうございます」", medical: true },
    { re: /(そのようなことはございません|事実ではありません|嘘|虚偽|営業妨害|二度と)/, why: "感情的な反論", alt: "「事実を確認いたします」" },
    { re: /(他院|他店|よそ)(より|と違|とは違)/, why: "他との比較", alt: "比べる文は消し、自分のことだけを書く" }
  ];

  function ngCheck(text, ind) {
    var med = IND[ind].medical, hits = [];
    NG.forEach(function (n) {
      if (n.medical && !med) return;
      var m = text.match(n.re);
      if (m) hits.push({ word: m[0], why: n.why, alt: n.alt });
    });
    return hits;
  }

  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  var form = root.querySelector("form");
  var out = root.querySelector(".kt-out");
  var shownLead = false;
  // 記事から来たときは、その記事の業種を選んだ状態で開く（?ind=dental など）
  try {
    var qi = new URLSearchParams(location.search).get("ind");
    if (qi && IND[qi]) form.ind.value = qi;
  } catch (e) {}

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var o = {
      ind: form.ind.value, kind: form.kind.value,
      name: form.shop.value.trim(), sign: form.sign.value.trim(),
      aspects: aspectsOf(form.review.value, form.ind.value)
    };
    ev("tool_kuchikomi_generate", { industry: o.ind, kind: o.kind, aspects: o.aspects.length });
    if (o.kind === "abuse") {
      out.innerHTML = '<div class="kt-note"><strong>暴言・誹謗中傷の口コミには、返信より先に Google へ報告してください。</strong>' +
        '<p>Googleビジネスプロフィールの管理画面で、その口コミの「︙」から「不適切なクチコミを報告」を選びます。' +
        '返信で言い返すと、やり取りそのものが公開され、ほかの人の目に長く残ります。</p></div>';
      return;
    }
    var list = build(o);
    var med = IND[o.ind].medical;
    var html = '<p class="kt-lead">返信案を3つ作りました。<b>【　】</b>の部分は、実際の内容に書き換えてから投稿してください。</p>';
    if (med) html += '<p class="kt-warn">医療機関では、口コミに症状や施術の内容が書かれていても、返信ではふれません（守秘義務）。この返信案もふれていません。</p>';
    list.forEach(function (t, n) {
      html += '<div class="kt-card"><div class="kt-card-h"><span>返信案 ' + (n + 1) + '</span><span class="kt-len">' + t.replace(/\s/g, "").length + '字</span></div>' +
              '<pre class="kt-text">' + esc(t).replace(/【([^】]*)】/g, '<mark>【$1】</mark>') + '</pre>' +
              '<button type="button" class="btn btn-ghost kt-copy" data-i="' + n + '">コピーする</button></div>';
    });
    out.innerHTML = html;
    out.querySelectorAll(".kt-copy").forEach(function (b) {
      b.addEventListener("click", function () {
        var t = list[+b.dataset.i];
        var done = function () { b.textContent = "コピーしました"; setTimeout(function () { b.textContent = "コピーする"; }, 1800); };
        if (navigator.clipboard) navigator.clipboard.writeText(t).then(done, function () {}); else done();
        ev("tool_kuchikomi_copy", { industry: o.ind, kind: o.kind, variant: +b.dataset.i + 1 });
      });
    });
    if (!shownLead && window.leadCapture) {
      shownLead = true;
      out.parentNode.insertBefore(window.leadCapture({
        title: "口コミの返信を、毎回考えなくて済むようにしませんか",
        sub: "口コミ返信・投稿・月次レポートまで任せられるMEO運用について、無料でご相談を受け付けています",
        formType: "口コミ返信ツールからの相談",
        route: "tool_kuchikomi",
        detail: "口コミ返信ツール利用（" + IND[o.ind].label + "）",
        button: "無料で相談する",
        note: "担当者からメールでご連絡します。",
        done: '<p class="lc-done"><strong>受け付けました。</strong>担当者からメールでご連絡します。</p>'
      }), out.nextSibling);
    }
    var h = out.querySelector(".kt-lead");
    if (h) { h.setAttribute("tabindex", "-1"); h.focus(); }
  });

  // 自分で書いた返信の NG チェック
  var chk = root.querySelector(".kt-check");
  chk.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = chk.mine.value, res = chk.querySelector(".kt-res");
    var hits = ngCheck(text, form.ind.value);
    ev("tool_kuchikomi_ngcheck", { industry: form.ind.value, hits: hits.length });
    if (!text.trim()) { res.innerHTML = "<p>返信文を入れてください。</p>"; return; }
    res.innerHTML = hits.length
      ? "<ul>" + hits.map(function (h) {
          return "<li><b>「" + esc(h.word) + "」</b>… " + esc(h.why) + "。言い換え例: " + esc(h.alt) + "</li>";
        }).join("") + "</ul>"
      : "<p><b>このツールで見ている言い回しは、見つかりませんでした。</b>ただし、すべての違反を見つけられるわけではありません。投稿前に、書いた人とは別の人が読んで確かめてください。</p>";
  });
})();
