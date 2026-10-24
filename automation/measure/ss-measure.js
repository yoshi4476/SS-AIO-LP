(function () {
  var id = window.SSB_GA4;
  if (id && typeof window.gtag !== 'function') {
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag('js', new Date());
    window.gtag('config', id);
    var load = function () {
      setTimeout(function () {
        var s = document.createElement('script');
        s.async = true;
        s.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(id);
        document.head.appendChild(s);
      }, 1200);
    };
    if (document.readyState === 'complete') load(); else window.addEventListener('load', load);
  }
  function ga(n, p) { if (typeof window.gtag === 'function') window.gtag('event', n, p); }
  function slugId(s) {
    return String(s || '').replace(/[^\w]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 30) || 'x';
  }
  var path = location.pathname;

  var depths = [25, 50, 75, 90], sent = {};
  document.addEventListener('scroll', function () {
    var h = document.documentElement;
    var pct = ((h.scrollTop + h.clientHeight) / h.scrollHeight) * 100;
    depths.forEach(function (d) {
      if (pct >= d && !sent[d]) { sent[d] = true; ga('scroll_depth', { depth: d, page_path: path }); }
    });
  }, { passive: true });

  document.querySelectorAll('[data-ab]').forEach(function (el) {
    var key = el.getAttribute('data-ab'), v;
    try {
      v = localStorage.getItem('ab_' + key);
      if (!v) { v = Math.random() < 0.5 ? 'a' : 'b'; localStorage.setItem('ab_' + key, v); }
    } catch (err) { v = 'a'; }
    if (v === 'b' && el.getAttribute('data-ab-b')) el.textContent = el.getAttribute('data-ab-b');
    el.setAttribute('data-ab-variant', v);
    ga('ab_impression', { ab_key: key, ab_variant: v, page_path: path });
    ga('ab_impression_' + slugId(key) + '_' + v, { ab_key: key, page_path: path });
  });

  document.addEventListener('click', function (e) {
    var a = e.target.closest ? e.target.closest('a, button') : null;
    if (!a) return;
    var href = a.getAttribute('href') || '';
    if (href.indexOf('tel:') === 0) {
      ga('cta_click', { cta_id: 'tel', page_path: path });
      ga('cta_tel', { page_path: path });
      return;
    }
    var c = a.classList;
    if (!(c.contains('btn') || c.contains('cta-button') || c.contains('wp-block-button__link') || a.hasAttribute('data-cta'))) return;
    var cid = a.getAttribute('data-cta') || slugId((a.textContent || '').trim());
    var p = { cta_id: cid, page_path: path };
    var abv = a.getAttribute('data-ab-variant');
    if (abv) {
      p.ab_variant = abv;
      ga('cta_click_' + slugId(a.getAttribute('data-ab')) + '_' + abv, p);
    }
    ga('cta_click', p);
    ga('cta_' + slugId(cid), p);
    var box = a.closest('.cta-inline, .inline-tool');
    if (box) ga('inline_tool_submit', { page_path: path, tool: box.getAttribute('data-tool') || 'tool' });
  });

  document.querySelectorAll('.cta-inline, .inline-tool').forEach(function (box) {
    var p = { page_path: path, tool: box.getAttribute('data-tool') || 'tool' };
    if ('IntersectionObserver' in window) {
      var o = new IntersectionObserver(function (es) {
        if (es[0].isIntersecting) { ga('inline_tool_view', p); o.disconnect(); }
      }, { threshold: 0.6 });
      o.observe(box);
    }
    box.addEventListener('focusin', function once() {
      ga('inline_tool_start', p);
      box.removeEventListener('focusin', once);
    });
  });

  var forms = document.querySelectorAll('form.wpcf7-form, form.wpforms-form, form.form-panel, form[data-ss-form], .entry-content form, main form');
  Array.prototype.forEach.call(forms, function (f) {
    if (f.getAttribute('role') === 'search' || f.classList.contains('search-form') || f.classList.contains('wp-block-search') || f.id === 'commentform' || f._ssm) return;
    f._ssm = true;
    var type = (f.querySelector('[name="form_type"]') || {}).value || f.getAttribute('data-ss-form') || 'form';
    var started = false, last = '', done = false, gone = false;
    f.addEventListener('focusin', function (e) {
      var el = e.target;
      if (!el || !el.name || el.type === 'hidden') return;
      last = el.name;
      if (!started) { started = true; ga('form_start', { form_type: type, page_path: path }); }
    });
    // 離脱は1回の表示につき1回。戻る・進む（bfcache）で表示し直したら、その表示で触ったときだけ数え直す（2.0.5）
    window.addEventListener('pagehide', function () {
      if (started && !done && !gone) { gone = true; ga('form_abandon', { form_type: type, last_field: last, page_path: path }); }
    });
    window.addEventListener('pageshow', function (e) {
      if (e.persisted) { started = false; done = false; gone = false; last = ''; }
    });
    var sent = function () {
      if (done) return;
      done = true;
      var route = type.indexOf('資料') >= 0 ? 'dl' : 'form';
      ga('form_submit', { form_type: type, page_path: path });
      ga('lead_capture', { lead_route: route, form_type: type });
      ga('lead_' + route, { form_type: type });
    };
    // Contact Form 7 は送信に失敗しても submit が起きる。送れたときの出来事で数える
    if (f.classList.contains('wpcf7-form')) {
      (f.closest('.wpcf7') || f).addEventListener('wpcf7mailsent', sent);
    } else {
      f.addEventListener('submit', sent);
    }
  });

  var bar = document.querySelector('.ss-sticky');
  if (bar && window.matchMedia && matchMedia('(max-width: 760px)').matches) {
    bar.hidden = false;
    var tick = function () { bar.style.transform = scrollY > innerHeight * 1.5 ? 'none' : 'translateY(120%)'; };
    addEventListener('scroll', tick, { passive: true });
    tick();
  }
})();
