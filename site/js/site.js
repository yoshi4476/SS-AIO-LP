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
    toggle.addEventListener('click', function () {
      var open = header.classList.toggle('nav-open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
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
          if (p < 1) requestAnimationFrame(tick);
        }
        requestAnimationFrame(tick);
      });
    }, { threshold: 0.6 });
    document.querySelectorAll('[data-count]').forEach(function (el) { cio.observe(el); });
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

  // section_view_〈セクションID〉: LP各エリア到達（ヒートマップ用。25%表示で発火）
  if ('IntersectionObserver' in window) {
    var aio = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          var el = e.target;
          var id = el.getAttribute('data-area-id') || slugId(el.getAttribute('data-area'));
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
    if (a.classList && (a.classList.contains('btn') || a.classList.contains('nav-cta'))) {
      var id = a.getAttribute('data-cta') || slugId((a.textContent || '').trim());
      ga('cta_click', { cta_id: id, page_path: location.pathname });
      ga('cta_' + slugId(id), { page_path: location.pathname });
    }
  });

  // form_submit（種別付き）+ lead_capture + lead_〈経路〉
  document.querySelectorAll('form.form-panel').forEach(function (f) {
    f.addEventListener('submit', function () {
      var typeEl = f.querySelector('[name="form_type"]');
      var type = typeEl ? typeEl.value : 'form';
      var route = type.indexOf('資料') >= 0 ? 'dl' : 'form';
      ga('form_submit', { form_type: type, page_path: location.pathname });
      ga('lead_capture', { lead_route: route, form_type: type });
      ga('lead_' + route, { form_type: type });
    });
  });

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
