/* 軽量演出スクリプト（依存なし・約1KB）
   - .reveal: スクロールで表示
   - [data-count]: 数値カウントアップ
   - .progress-bar: 読了プログレス（記事ページ）
   reduced-motion はCSS側で無効化済み */
(function () {
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  var toggle = document.querySelector('.nav-toggle');
  var header = document.querySelector('.site-header');
  if (toggle && header) {
    // メニューを畳む幅でも無料ツールが見えるよう、ヘッダーの下に細い帯を出す（CSSで広い幅では隠す）。
    // ロゴの横にボタンを並べると、スマホでロゴの文字が3行に折れた（2026-10-03）。
    // 出すのはトップと /tools/ だけ（CSS が場所を取るのと同じ条件）。全ページに出すと固定のヘッダーが 111px になり、
    // 記事では下の固定ボタンと合わせて画面の約1/4を常に覆っていた（2026-10-08）
    var toolsPage = document.body.classList.contains('home') || document.querySelector('.tools-main');
    if (toolsPage && header.querySelector('.global-nav .nav-tool') && !header.querySelector('.hdr-tools')) {
      var bar = document.createElement('div');
      bar.className = 'hdr-tools';
      bar.innerHTML = '<a href="/tools/" data-cta="hdr_tools">無料ツール</a>'
        + '<a href="/tools/url-check/" data-cta="hdr_tools_url">URL診断</a>'
        + '<a href="/tools/ai-check/" data-cta="hdr_tools_ai">AI診断</a>';
      header.appendChild(bar);
    }
    toggle.addEventListener('click', function () {
      var open = header.classList.toggle('nav-open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }

  // ===== MOTION v2: 自動エンハンス（IO登録より先に実行） =====

  // グリッド系の子要素へ reveal + スタガー遅延を自動付与（マークアップ変更なしで全ページに波及）
  if (!reduce) {
    ['.pillar-grid', '.card-grid', '.term-grid', '.post-list', '.stat-band', '.check-list', '.faq-grid'].forEach(function (sel) {
      document.querySelectorAll(sel).forEach(function (grid) {
        Array.prototype.forEach.call(grid.children, function (child, idx) {
          child.classList.add('reveal');
          child.style.setProperty('--d', Math.min(idx, 7) * 80 + 'ms');
        });
      });
    });
  }

  // キネティックタイプ: .kinetic 内のテキストを1文字ずつ<span>化（em/br等の構造は保持）
  document.querySelectorAll('.kinetic').forEach(function (root) {
    if (reduce) return;
    var count = 0;
    (function split(node) {
      Array.prototype.slice.call(node.childNodes).forEach(function (n) {
        if (n.nodeType === 3) {
          var frag = document.createDocumentFragment();
          n.textContent.split('').forEach(function (ch) {
            if (ch.trim() === '') { frag.appendChild(document.createTextNode(ch)); return; }
            var s = document.createElement('span');
            s.className = 'k-ch';
            s.style.setProperty('--i', count++);
            s.textContent = ch;
            frag.appendChild(s);
          });
          node.replaceChild(frag, n);
        } else if (n.nodeType === 1 && n.tagName === 'EM') {
          // グラデーション文字はclip崩れ防止のため1チャンクで動かす
          n.classList.add('k-ch');
          n.style.setProperty('--i', count);
          count += 3;
        } else if (n.nodeType === 1 && n.tagName !== 'BR') {
          split(n);
        }
      });
    })(root);
  });

  // マグネティックボタン: カーソルに吸い付く主要CTA（pointer:fineのみ）
  if (!reduce && window.matchMedia('(pointer: fine)').matches) {
    document.querySelectorAll('.btn-primary, .nav-cta').forEach(function (btn) {
      btn.addEventListener('pointermove', function (e) {
        var r = btn.getBoundingClientRect();
        var dx = (e.clientX - r.left - r.width / 2) / r.width;
        var dy = (e.clientY - r.top - r.height / 2) / r.height;
        btn.style.transform = 'translate(' + (dx * 7).toFixed(1) + 'px,' + (dy * 5).toFixed(1) + 'px)';
      });
      btn.addEventListener('pointerleave', function () { btn.style.transform = ''; });
    });

    // カーソルグロー（青の残光がゆっくり追従）
    var glow = document.createElement('div');
    glow.className = 'cursor-glow';
    glow.setAttribute('aria-hidden', 'true');
    document.body.appendChild(glow);
    var gx = 0, gy = 0, tx = 0, ty = 0, glowOn = false;
    document.addEventListener('pointermove', function (e) {
      tx = e.clientX; ty = e.clientY;
      if (!glowOn) { glow.style.opacity = '1'; glowOn = true; }
    }, { passive: true });
    (function loop() {
      gx += (tx - gx) * 0.09;
      gy += (ty - gy) * 0.09;
      glow.style.transform = 'translate(' + gx.toFixed(1) + 'px,' + gy.toFixed(1) + 'px)';
      requestAnimationFrame(loop);
    })();
  }

  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.classList.add('in');
          io.unobserve(e.target);
        }
      });
    }, { threshold: 0.18 });
    document.querySelectorAll('.reveal, .bar-grow, .line-draw').forEach(function (el) { io.observe(el); });

    var cio = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        cio.unobserve(e.target);
        var el = e.target, target = parseFloat(el.getAttribute('data-count'));
        if (reduce) { el.textContent = target; return; }
        var start = null, dur = 1400;
        function tick(ts) {
          if (!start) start = ts;
          var p = Math.min((ts - start) / dur, 1);
          p = 1 - Math.pow(1 - p, 3);
          el.textContent = Math.round(target * p);
          if (p < 1) { requestAnimationFrame(tick); } else { el.classList.add('num-pop'); }
        }
        requestAnimationFrame(tick);
      });
    }, { threshold: 0.6 });
    document.querySelectorAll('[data-count]').forEach(function (el) { cio.observe(el); });
  } else {
    // IntersectionObserver非対応ブラウザ: reveal要素が非表示のままにならないよう即表示
    document.querySelectorAll('.reveal, .bar-grow, .line-draw').forEach(function (el) { el.classList.add('in'); });
    document.querySelectorAll('[data-count]').forEach(function (el) {
      el.textContent = el.getAttribute('data-count');
    });
  }

  // ヒーローカードの3Dチルト（マウス追従。タッチ/reduced-motionでは無効）
  var art = document.querySelector('.hero-art');
  var heroWrap = document.querySelector('.hero-dark');
  if (art && heroWrap && !reduce && window.matchMedia('(pointer: fine)').matches) {
    heroWrap.addEventListener('pointermove', function (e) {
      var r = art.getBoundingClientRect();
      var dx = (e.clientX - (r.left + r.width / 2)) / r.width;
      var dy = (e.clientY - (r.top + r.height / 2)) / r.height;
      dx = Math.max(-0.6, Math.min(0.6, dx));
      dy = Math.max(-0.6, Math.min(0.6, dy));
      art.style.transform = 'perspective(900px) rotateY(' + (dx * 12).toFixed(2) + 'deg) rotateX(' + (-dy * 12).toFixed(2) + 'deg)';
    });
    heroWrap.addEventListener('pointerleave', function () { art.style.transform = ''; });
  }

  // ===== GA4計測（第7章 計測設計。gtag未設置時は何もしない） =====
  function ga(name, params) {
    if (typeof window.gtag === 'function') window.gtag('event', name, params);
  }
  function slugId(s) {
    return String(s || '').replace(/[^\w]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 30) || 'x';
  }

  // ===== 地図は押したときだけ読む（Googleマップは1枚で数百KB。表示速度を落とさない） =====
  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('.map-load');
    if (!btn) return;
    var box = btn.closest('.map-facade');
    if (!box || box.classList.contains('is-loaded')) return;
    var f = document.createElement('iframe');
    f.src = box.getAttribute('data-map-src');
    f.title = 'セブンセンシズ株式会社の地図（Googleマップ）';
    f.loading = 'lazy';
    f.referrerPolicy = 'no-referrer-when-downgrade';
    f.setAttribute('allowfullscreen', '');
    f.addEventListener('load', function () { box.classList.add('is-ready'); });
    box.appendChild(f);
    box.classList.add('is-loaded');
    ga('map_load', { page_path: location.pathname });
  });

  // section_view_〈セクションID〉: LP各エリア到達（ヒートマップ用。25%表示で発火）
  if ('IntersectionObserver' in window) {
    var aio = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          var el = e.target;
          // GA4 のイベント名は英数字と _ だけ。ハイフン入りの id（cat-services 等）は記録されないため、
          // 集計側（report_heat.slug_id）と同じ規則で揃える
          var id = slugId(el.getAttribute('data-area-id') || el.getAttribute('data-area'));
          ga('section_view_' + id, { area_name: el.getAttribute('data-area'), page_path: location.pathname });
          ga('area_reach', { area_name: el.getAttribute('data-area'), area_id: id, page_path: location.pathname });
          aio.unobserve(el);
        }
      });
    }, { threshold: 0.25 });
    document.querySelectorAll('[data-area]').forEach(function (el) { aio.observe(el); });
  }

  // scroll_depth: 25/50/75/90%
  var depths = [25, 50, 75, 90];
  var sent = {};
  document.addEventListener('scroll', function () {
    var h = document.documentElement;
    var pct = ((h.scrollTop + h.clientHeight) / h.scrollHeight) * 100;
    depths.forEach(function (d) {
      if (pct >= d && !sent[d]) {
        sent[d] = true;
        ga('scroll_depth', { depth: d, page_path: location.pathname });
      }
    });
  }, { passive: true });

  // 入口（/lp/・/contact/・/download/・/tools/ の診断）へのリンク。ボタンでも本文の文字リンクでも押されたら数える。
  // 本文の普通のリンクの入口（約200本）は押されても送られず、どの入口が効いているか分からなかった（2026-10-08）
  var ENTRY = /^\/(?:lp|contact|download|tools)(?:\/|$)/;
  function isEntry(a) {
    if (a.tagName !== 'A' || !a.getAttribute('href') || (a.host && a.host !== location.host)) return false;
    return ENTRY.test(a.pathname);
  }
  // data-cta の無いボタン・リンクの名前は「ページの種類＋位置＋行き先」で付ける（例: article_body3_tools_ai_check）。
  // 文言から作ると日本語が落ち、305本が同じ「AI」になっていた
  function pageKind() {
    var p = location.pathname;
    if (p === '/' || p === '/index.html') return 'top';
    if (document.querySelector('main.article .article-body')) return 'article';
    return slugId(p.split('/')[1]);
  }
  function region(el) {
    if (!el.closest) return 'main';
    var r = el.closest('.site-header') ? 'head' : el.closest('.site-footer') ? 'foot'
      : el.closest('.scan-sticky, .sticky-cta') ? 'sticky' : el.closest('.article-side') ? 'side'
      : el.closest('.article-body') ? 'body' : '';
    if (r) return r;
    var s = el.closest('[data-area-id]');
    return s ? slugId(s.getAttribute('data-area-id')) : 'main';
  }
  function dest(el) {
    var f = el.form || (el.closest && el.closest('form'));
    var to = el.tagName === 'A' ? el.pathname + el.hash : (f && f.getAttribute('action')) || '';
    return slugId(to.replace(/#/g, '_')) || 'here';
  }
  function autoId(el) {
    var r = region(el), d = dest(el);
    // 同じ位置・同じ行き先が2つ以上あれば、ページの中の順番を付けて分ける
    var same = Array.prototype.filter.call(document.querySelectorAll('a[href], button'), function (x) {
      return region(x) === r && dest(x) === d;
    });
    return pageKind() + '_' + r + (same.length > 1 ? same.indexOf(el) + 1 : '') + '_' + d;
  }

  // cta_click + cta_〈ボタンID〉（設置場所別）/ 電話タップ
  document.addEventListener('click', function (e) {
    var a = e.target.closest ? e.target.closest('a, button') : null;
    if (!a) return;
    var href = a.getAttribute && (a.getAttribute('href') || '');
    if (href && href.indexOf('tel:') === 0) {
      ga('cta_click', { cta_id: 'tel', page_path: location.pathname });
      ga('cta_tel', { page_path: location.pathname });
      return;
    }
    // 記事本文のCTAは cta-button / cta-box を使う。ここを入れ忘れると
    // 記事からの反応が1件も記録されず、導線が効いているか判断できなくなる
    // data-cta を付けた文字リンク（記事の診断の下の「AI診断」など）も数える。ボタンの形のものだけを
    // 数えていたため、足した入口が効いたかを測れなかった（2026-10-04）
    if (a.classList && (a.classList.contains('btn') || a.classList.contains('nav-cta') ||
                        a.classList.contains('cta-button') || a.hasAttribute('data-cta') || isEntry(a))) {
      var id = a.getAttribute('data-cta') || autoId(a);
      var params = { cta_id: id, page_path: location.pathname };
      var abv = a.getAttribute('data-ab-variant');
      if (abv) {
        params.ab_variant = abv;
        // 出来事の名前にA/Bを入れる。GA4のパラメータは管理画面で登録しないと
        // 後から集計できないが、名前なら登録なしで数えられる
        // 試験が2つ以上あると名前の a/b だけでは混ざる。試験名入りの名前も送る（ab_result が試験ごとに数える）
        var abk = a.getAttribute('data-ab');
        if (abk === 'article_cta') ga('cta_click_' + abv, params);
        else if (abk) ga('cta_click_' + slugId(abk) + '_' + abv, params);
      }
      ga('cta_click', params);
      ga('cta_' + slugId(id), params);
    }
  });

  // 軽量A/Bテスト: [data-ab] の文言を50%でB案（data-ab-b）に差し替え。
  // localStorageで同一訪問者のバリアントを固定し、GA4に ab_impression を送る。
  document.querySelectorAll('[data-ab]').forEach(function (el) {
    var key = el.getAttribute('data-ab');
    var stKey = 'ab_' + key;
    var v;
    try {
      v = localStorage.getItem(stKey);
      if (!v) { v = Math.random() < 0.5 ? 'a' : 'b'; localStorage.setItem(stKey, v); }
    } catch (err) { v = 'a'; }
    if (v === 'b') {
      var alt = el.getAttribute('data-ab-b');
      if (alt) {
        // 矢印スパン等の子要素を保持したまま文言だけ差し替える
        var arw = el.querySelector('.arw');
        if (arw) {
          el.textContent = '';
          el.appendChild(document.createTextNode(alt.replace(/\s*→\s*$/, ' ')));
          el.appendChild(arw);
        } else {
          el.textContent = alt;
        }
      }
    }
    el.setAttribute('data-ab-variant', v);
    ga('ab_impression', { ab_key: key, ab_variant: v, page_path: location.pathname });
    if (key === 'article_cta') ga('ab_impression_' + v, { ab_key: key, page_path: location.pathname });
    else ga('ab_impression_' + slugId(key) + '_' + v, { ab_key: key, page_path: location.pathname });
  });

  // 記事の音声読み上げ（Web Speech API。非対応ブラウザではボタンを隠す）
  var listenBtn = document.querySelector('.listen-btn');
  if (listenBtn && 'speechSynthesis' in window) {
    var speaking = false;
    listenBtn.addEventListener('click', function () {
      if (speaking) {
        speechSynthesis.cancel();
        speaking = false;
        listenBtn.textContent = '🎧 聴く';
        return;
      }
      var h1 = document.querySelector('h1');
      var body = document.querySelector('.article-body');
      var text = ((h1 ? h1.textContent : '') + '。' + (body ? body.innerText : '')).slice(0, 9000);
      var u = new SpeechSynthesisUtterance(text);
      u.lang = 'ja-JP';
      u.rate = 1.05;
      u.onend = function () { speaking = false; listenBtn.textContent = '🎧 聴く'; };
      speechSynthesis.cancel();
      speechSynthesis.speak(u);
      speaking = true;
      listenBtn.textContent = '⏹ 停止';
      ga('cta_click', { cta_id: 'listen_article', page_path: location.pathname });
    });
    window.addEventListener('beforeunload', function () { speechSynthesis.cancel(); });
  } else if (listenBtn) {
    listenBtn.style.display = 'none';
  }

  // ニュースレター購読フォームの計測+送信中表示
  document.querySelectorAll('form.nl-form').forEach(function (f) {
    f.addEventListener('submit', function () {
      ga('form_submit', { form_type: 'ニュースレター購読', page_path: location.pathname });
      ga('lead_capture', { lead_route: 'newsletter', form_type: 'ニュースレター購読' });
      ga('lead_newsletter', {});
      var btn = f.querySelector('button[type="submit"]');
      if (btn && !btn.disabled) {
        btn.disabled = true;
        btn.textContent = '登録中…';
        setTimeout(function () { btn.disabled = false; btn.textContent = '購読する'; }, 8000);
      }
    });
  });

  // form_submit（種別付き）+ lead_capture + lead_〈経路〉 + 送信中フィードバック
  document.querySelectorAll('form.form-panel').forEach(function (f) {
    // 「開いたのに送らなかった」を項目つきで数える。開いた7人中1人しか送らない原因を
    // 分けるため。form_start = 最初の入力、form_abandon = 送らずに離れた（最後に触った項目つき）
    var started = false, lastField = '', submitted = false, abandoned = false;
    f.addEventListener('focusin', function (e) {
      var el = e.target;
      if (!el || !el.name || el.type === 'hidden') return;
      lastField = el.name;
      if (!started) {
        started = true;
        var t = f.querySelector('[name="form_type"]');
        ga('form_start', { form_type: t ? t.value : 'form', page_path: location.pathname });
      }
    });
    window.addEventListener('pagehide', function () {
      if (started && !submitted && !abandoned) {
        abandoned = true;
        var t = f.querySelector('[name="form_type"]');
        ga('form_abandon', { form_type: t ? t.value : 'form', last_field: lastField, page_path: location.pathname });
      }
    });
    // 戻る・進む（bfcache）で表示し直したら、その表示で触ったときだけ開始・離脱を数え直す。
    // 以前は同じ人の離脱を、戻る・進むのたびに送っていた（開始1回に離脱4回。2026-10-07 Chromium で再現）
    window.addEventListener('pageshow', function (e) {
      if (e.persisted) { started = false; abandoned = false; submitted = false; lastField = ''; }
    });
    f.addEventListener('submit', function () {
      submitted = true;
      var typeEl = f.querySelector('[name="form_type"]');
      var type = typeEl ? typeEl.value : 'form';
      var route = type.indexOf('資料') >= 0 ? 'dl' : 'form';
      ga('form_submit', { form_type: type, page_path: location.pathname });
      ga('lead_capture', { lead_route: route, form_type: type });
      ga('lead_' + route, { form_type: type });
      // 二重送信防止 + 送信中表示（ネイティブPOSTのため遷移までの間のみ）
      var btn = f.querySelector('button[type="submit"]');
      if (btn && !btn.disabled) {
        btn.disabled = true;
        btn.dataset.orig = btn.textContent;
        btn.textContent = '送信中…';
        setTimeout(function () { // 万一遷移しない場合の復帰
          btn.disabled = false;
          if (btn.dataset.orig) btn.textContent = btn.dataset.orig;
        }, 8000);
      }
    });
  });

  // 記事の最初の章の入力欄（build.py の inline_tool）。見えた・入力を始めた・送った を記事のパスつきで数える。
  // 押下だけでは、見られずに終わったのか、入れかけてやめたのかが分からないため
  document.querySelectorAll('.inline-tool').forEach(function (box) {
    var f = box.querySelector('form');
    if (!f) return;
    var p = { page_path: location.pathname, tool: box.getAttribute('data-tool') || 'tool' };
    if ('IntersectionObserver' in window) {
      var vio = new IntersectionObserver(function (es) {
        if (es[0].isIntersecting) { ga('inline_tool_view', p); vio.disconnect(); }
      }, { threshold: 0.6 });
      vio.observe(box);
    }
    var started = false;
    f.addEventListener('focusin', function () {
      if (!started) { started = true; ga('inline_tool_start', p); }
    });
    // 「example.co.jp」のように https:// を省いた入力は、type=url の検査で黙って止まる。先頭を補って送り直す
    var u = f.querySelector('input[type="url"]');
    u.addEventListener('invalid', function () {
      var v = u.value.trim();
      if (v && !/^https?:\/\//i.test(v) && v.indexOf('.') > 0) {
        u.value = 'https://' + v;
        // 検査の途中で送り直すとブラウザが受け付けないので、検査が終わってから送る
        setTimeout(function () { if (f.requestSubmit) f.requestSubmit(); else f.submit(); }, 0);
      }
    });
    f.addEventListener('submit', function () { ga('inline_tool_submit', p); });
  });

  // 記事目次のスクロールスパイ（現在読んでいる見出しをハイライト）
  var tocLinks = document.querySelectorAll('.toc a[href^="#"]');
  if (tocLinks.length && 'IntersectionObserver' in window) {
    var map = {};
    tocLinks.forEach(function (a) { map[decodeURIComponent(a.getAttribute('href')).slice(1)] = a; });
    var headings = [];
    Object.keys(map).forEach(function (id) {
      var h = document.getElementById(id);
      if (h) headings.push(h);
    });
    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          tocLinks.forEach(function (a) { a.classList.remove('toc-active'); });
          var a = map[e.target.id];
          if (a) a.classList.add('toc-active');
        }
      });
    }, { rootMargin: '-15% 0px -70% 0px' });
    headings.forEach(function (h) { spy.observe(h); });
  }

  // トップへ戻るボタン（全ページ・JSで生成）
  var toTop = document.createElement('button');
  toTop.className = 'to-top';
  toTop.setAttribute('aria-label', 'ページの先頭へ戻る');
  toTop.innerHTML = '↑';
  document.body.appendChild(toTop);
  toTop.addEventListener('click', function () {
    window.scrollTo({ top: 0, behavior: reduce ? 'auto' : 'smooth' });
  });
  document.addEventListener('scroll', function () {
    toTop.classList.toggle('show', document.documentElement.scrollTop > 600);
  }, { passive: true });

  // URLコピー（記事シェア）
  document.querySelectorAll('.copy-url').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var url = btn.getAttribute('data-url') || location.href;
      function done() {
        var orig = btn.textContent;
        btn.textContent = '✓ コピーしました';
        btn.classList.add('copied');
        ga('cta_click', { cta_id: 'share_copy', page_path: location.pathname });
        setTimeout(function () { btn.textContent = orig; btn.classList.remove('copied'); }, 2000);
      }
      function fallback() {
        var ta = document.createElement('textarea');
        ta.value = url; document.body.appendChild(ta); ta.select();
        try { document.execCommand('copy'); } catch (err) { /* noop */ }
        document.body.removeChild(ta); done();
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(done).catch(fallback);
      } else {
        fallback();
      }
    });
  });

  // 記事一覧のライブ検索（/blog/ の #blogSearch）
  var search = document.getElementById('blogSearch');
  if (search) {
    var items = Array.prototype.slice.call(document.querySelectorAll('.post-list li'));
    var empty = document.getElementById('blogSearchEmpty');
    search.addEventListener('input', function () {
      var q = search.value.trim().toLowerCase();
      var hit = 0;
      items.forEach(function (li) {
        var show = !q || li.textContent.toLowerCase().indexOf(q) >= 0;
        li.style.display = show ? '' : 'none';
        if (show) hit++;
      });
      if (empty) empty.style.display = hit ? 'none' : 'block';
    });
  }

  // 記事一覧のカテゴリ絞り込み（/blog/ の #catFilter）
  var filter = document.getElementById('catFilter');
  if (filter) {
    var blocks = Array.prototype.slice.call(document.querySelectorAll('.latest-block'));
    filter.addEventListener('click', function (e) {
      var btn = e.target.closest('button[data-target]');
      if (!btn) return;
      var target = btn.getAttribute('data-target');
      filter.querySelectorAll('button').forEach(function (b) {
        b.setAttribute('aria-pressed', String(b === btn));
      });
      blocks.forEach(function (bl) {
        var cat = bl.getAttribute('data-cat');
        // 「すべて」は新着も含めて全部、カテゴリ選択時は新着を隠して該当カテゴリだけ見せる
        bl.style.display = (target === 'all' || cat === target) ? '' : 'none';
      });
      var search = document.getElementById('blogSearch');
      if (search && search.value) { search.value = ''; search.dispatchEvent(new Event('input')); }
    });
  }

  // 将来の診断ツール用フック（diagnosis_complete / site_audit_complete 等をここから送信）
  window.trackLead = function (eventName, params) { ga(eventName, params || {}); };

  var bar = document.querySelector('.progress-bar');
  if (bar) {
    var onScroll = function () {
      var h = document.documentElement;
      var max = h.scrollHeight - h.clientHeight;
      bar.style.width = (max > 0 ? (h.scrollTop / max) * 100 : 0) + '%';
    };
    document.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }
})();

/* 結果画面でリードを受け取る（quiz.js / site-audit.js から呼ぶ）
 *
 * これまで3つの診断ツールは点数を出して終わりで、誰が受けたのか分からなかった。
 * 相談は身構えるが、自分の点数の続きを受け取ることには抵抗が小さい。
 *
 * ページ遷移させないのが要点。/api/lead は成功時に /thanks/ へ303を返すが、
 * 画面ごと移ると、いま見せた点数が消える。fetchで送って画面に留める。 */
window.leadCapture = function (opts) {
  var wrap = document.createElement("section");
  wrap.className = "lead-capture";
  wrap.innerHTML =
    '<div class="lc-head"><strong>' + opts.title + '</strong>' +
    '<span>' + opts.sub + '</span></div>' +
    '<form class="lc-form" novalidate>' +
    '<input type="text" name="_gotcha" tabindex="-1" autocomplete="off" aria-hidden="true">' +
    '<label>お名前 <input type="text" name="name" required autocomplete="name"></label>' +
    '<label>会社名・店舗名 <input type="text" name="company" required autocomplete="organization"></label>' +
    '<label>メールアドレス <input type="email" name="email" required autocomplete="email"></label>' +
    '<button type="submit" class="btn btn-primary">' + (opts.button || '診断結果を受け取る') + '</button>' +
    '<p class="lc-note">' + (opts.note || '送るのは診断結果とその読み方だけです。') +
    '<a href="/privacy/" target="_blank" rel="noopener">プライバシーポリシー</a>に同意のうえ送信してください。</p>' +
    '<p class="lc-msg" role="status" aria-live="polite"></p></form>';

  var form = wrap.querySelector(".lc-form");
  var msg = wrap.querySelector(".lc-msg");
  var btn = wrap.querySelector("button");
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (!form.checkValidity()) { msg.textContent = "未入力の項目があります。"; return; }
    btn.disabled = true;
    msg.textContent = "送信しています…";
    var fd = new FormData(form);
    fd.append("form_type", opts.formType);
    fd.append("message", opts.detail);
    // 診断の結果（URL・点数・直し方）。受付側でサイト無料診断として扱い、自動返信に直し方を載せる
    if (opts.extra) Object.keys(opts.extra).forEach(function (k) { fd.append(k, opts.extra[k]); });
    fetch("/api/lead", { method: "POST", body: fd })
      .then(function (r) {
        if (!r.ok) return r.text().then(function (t) { throw new Error(t); });
        // CVは送れたときに1回だけ数える（診断の完了時には数えない。受けただけでは連絡先が無い）
        if (window.trackLead) {
          window.trackLead("lead_form_submit", { lead_route: opts.route });
          window.trackLead("lead_capture", { lead_route: opts.route, form_type: opts.formType });
        }
        form.innerHTML = opts.done ||
          ('<p class="lc-done"><strong>お送りしました。</strong>' +
           '数分で届かない場合は迷惑メールをご確認ください。</p>');
      })
      .catch(function (err) {
        btn.disabled = false;
        msg.textContent = String(err.message || "").slice(0, 120) ||
          "送信できませんでした。恐れ入りますが 06-4305-7547 までご連絡ください。";
      });
  });
  return wrap;
};

/* 購読フォームを画面内で送る
 *
 * これまでは素のPOSTで、送信に失敗すると訪問者は
 * 「購読設定が未完了です。」だけが書かれたページに飛ばされていた。
 * 戻る導線もなく、そこでサイトから出てしまう。記事84本すべてに
 * 置いてあるフォームなので、失敗したときの見え方は無視できない。 */
(function () {
  document.querySelectorAll('form.nl-form[action="/api/subscribe"]').forEach(function (f) {
    var msg = document.createElement("p");
    msg.className = "nl-msg";
    msg.setAttribute("role", "status");
    msg.setAttribute("aria-live", "polite");
    f.appendChild(msg);
    f.addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = f.querySelector("button");
      if (!f.checkValidity()) { msg.textContent = "メールアドレスをご確認ください。"; return; }
      btn.disabled = true;
      msg.textContent = "送信しています…";
      fetch("/api/subscribe", { method: "POST", body: new FormData(f) })
        .then(function (r) {
          if (!r.ok) return r.text().then(function (t) { throw new Error(t); });
          if (window.trackLead) window.trackLead("newsletter_submit", { page_path: location.pathname });
          f.innerHTML = '<p class="nl-done"><strong>登録しました。</strong>' +
            '次回の配信からお届けします。</p>';
        })
        .catch(function (err) {
          btn.disabled = false;
          msg.textContent = String(err.message || "").slice(0, 110) ||
            "登録できませんでした。恐れ入りますがお問い合わせフォームからご連絡ください。";
        });
    });
  });
})();

/* 資料のスライド送り（.slide-viewer）。画像は /images/proposal/pNN.jpg */
document.querySelectorAll(".slide-viewer").forEach(function (v) {
  var total = +v.dataset.total || 1, cur = 1;
  var img = v.querySelector(".sv-img"), count = v.querySelector(".sv-count");
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function go(d) {
    cur = Math.min(total, Math.max(1, cur + d));
    img.src = "/images/proposal/p" + pad(cur) + ".jpg";
    img.alt = "サービス資料 " + cur + "ページ目";
    count.textContent = cur + " / " + total;
    var nx = new Image(); nx.src = "/images/proposal/p" + pad(Math.min(total, cur + 1)) + ".jpg";
    if (window.trackLead && cur === 2 && !v.dataset.seen) {
      v.dataset.seen = "1";
      window.trackLead("proposal_view", { lead_route: "proposal" });
    }
  }
  v.querySelector(".sv-prev").addEventListener("click", function () { go(-1); });
  v.querySelector(".sv-next").addEventListener("click", function () { go(1); });
  v.setAttribute("tabindex", "0");
  v.addEventListener("keydown", function (e) {
    if (e.key === "ArrowLeft") { go(-1); e.preventDefault(); }
    if (e.key === "ArrowRight") { go(1); e.preventDefault(); }
  });
});

/* パートナー経由の紹介元（?ref=）
 *
 * 制作会社・士業・商工会議所などに /lp/?ref=<ID> を配る。来た人の紹介元を90日覚え、
 * どのフォームから送っても ref として一緒に送る（台帳と通知メールに載る）。
 * 最初に来た経路を優先する（あとから別の紹介で来ても上書きしない）。 */
(function () {
  var KEY = "ss_ref", DAYS = 90;
  function read() {
    try {
      var v = JSON.parse(localStorage.getItem(KEY) || "null");
      return v && Date.now() - v.at < DAYS * 864e5 ? v.ref : "";
    } catch (e) { return ""; }
  }
  var q = (new URLSearchParams(location.search).get("ref") || "").trim();
  if (/^[A-Za-z0-9_-]{1,40}$/.test(q) && !read()) {
    try { localStorage.setItem(KEY, JSON.stringify({ ref: q, at: Date.now() })); } catch (e) {}
  }
  window.ssRef = read;
  // 送信の直前（各フォームの処理より先）に、隠し項目として足す
  document.addEventListener("submit", function (e) {
    var f = e.target, r = read();
    if (!r || !f || !f.querySelector || f.querySelector('input[name="ref"]')) return;
    var act = f.getAttribute("action") || "";
    if (act.indexOf("/api/lead") < 0 && !f.classList.contains("lc-form") && !(f.closest && f.closest(".lx-gate"))) return;
    var i = document.createElement("input");
    i.type = "hidden"; i.name = "ref"; i.value = r;
    f.appendChild(i);
  }, true);
})();

/* 相談の直前に見たページ
 * 同じ訪問の中で見たページ（直近6つ）を覚え、問い合わせ・資料請求・AI診断の送信に隠し項目 pages として足す。
 * 台帳に残り、商談の準備と「問い合わせにつながる記事」の判断に使う。送るのはページの場所だけ（個人の情報は含まない）。 */
(function () {
  var KEY = "ss_pages", MAX = 6;
  var list = [];
  try { list = JSON.parse(sessionStorage.getItem(KEY) || "[]"); } catch (e) {}
  if (list[list.length - 1] !== location.pathname) list.push(location.pathname);
  list = list.slice(-MAX);
  try { sessionStorage.setItem(KEY, JSON.stringify(list)); } catch (e) {}
  document.addEventListener("submit", function (e) {
    var f = e.target;
    if (!f || !f.querySelector || f.querySelector('input[name="pages"]')) return;
    var act = f.getAttribute("action") || "";
    if (act.indexOf("/api/lead") < 0 && !f.hasAttribute("data-pages") && !f.classList.contains("lc-form")
        && !(f.closest && f.closest(".lx-gate"))) return;
    var i = document.createElement("input");
    i.type = "hidden"; i.name = "pages"; i.value = list.join(" → ").slice(0, 400);
    f.appendChild(i);
  }, true);
})();

/* スマホの固定ボタン（記事の .scan-sticky・LP の .sticky-cta）
 * 1画面半ほど読み進めたら出し、フォーム・診断欄・フッターが見えている間と、入力している間は引っ込める
 * （同じ誘いを二重に見せない）。LP の帯は最初の画面から出てヒーローの「30秒で診断する」に重なり、
 * フォームの入力中も出たままで、「30秒診断」が入力中の人をフォームの外へ連れ出していた（2026-10-08） */
(function () {
  var bar = document.querySelector(".scan-sticky, .sticky-cta");
  if (!bar || !window.matchMedia || !matchMedia("(max-width: 760px)").matches) return;
  bar.hidden = false;
  // 申し込み・診断の区画（#form・#scan-start）は、フォームの前の説明が見えている間から引っ込める
  var ends = document.querySelectorAll(".scan-bottom, .site-footer, form, #scan, #form, #scan-start");
  var near = false, typing = false, seen = [];
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        var i = seen.indexOf(e.target);
        if (e.isIntersecting && i < 0) seen.push(e.target);
        if (!e.isIntersecting && i >= 0) seen.splice(i, 1);
      });
      near = seen.length > 0;
      tick();
    });
    ends.forEach(function (el) { if (!bar.contains(el)) io.observe(el); });
  }
  function field(t) { return t && t.closest && t.closest("input, textarea, select"); }
  document.addEventListener("focusin", function (e) { if (field(e.target)) { typing = true; tick(); } });
  document.addEventListener("focusout", function (e) { if (field(e.target)) { typing = false; setTimeout(tick, 60); } });
  function tick() {
    // 割合で決めると、長い記事（スマホで2万px）ほど出るのが遅れる。1画面半を読み進めたら出す
    var on = scrollY > innerHeight * 1.5 && !near && !typing;
    bar.classList.toggle("is-on", on);
  }
  addEventListener("scroll", tick, { passive: true });
  tick();
})();

/* 業種別のページ（/lp/medical/ など）から ?ind= で来た人の業種を、相談フォームの隠し項目に入れる。
 * 業種LPの「無料で相談する」は全業種向けの /lp/ のフォームへ移るため、業種が引き継がれていなかった（2026-10-08）。
 * 値は診断欄の業種の選択肢にあるものだけ（lp-scan.js が ?ind= で診断欄の業種を選ぶのと同じ値） */
(function () {
  var box = document.querySelector('form input[name="industry"]');
  if (!box) return;
  var v = (new URLSearchParams(location.search).get("ind") || "").trim();
  var ok = Array.prototype.some.call(document.querySelectorAll("#lx-industry option"), function (o) {
    return o.value && o.value === v;
  });
  if (ok) box.value = v;
})();
