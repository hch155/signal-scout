(function () {
  var DOT_COLORS = { play: '#a78bfa', orange: '#fb923c', plus: '#22c55e', tmobile: '#f87171' };
  var TECHS = ['5G', 'LTE', '3G', 'GSM'];

  function tr(s) { return (window.t ? window.t(s) : s); }
  function esc(s) { return (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s)); }

  function lang() {
    return (window.SS_I18N && window.SS_I18N.lang) || 'en';
  }

  function formatDistance(km) {
    if (km === null || km === undefined) return '';
    return km < 1 ? Math.round(km * 1000) + ' m' : km.toFixed(1) + ' km';
  }

  function rationaleText(op) {
    var r = op.rationale || {};
    return r[lang()] || r.en || '';
  }

  function scoreExplainer(op) {
    var parts = [];
    if (op.signal_tier) {
      parts.push(tr('Signal quality') + ': ' + tr(op.signal_tier));
    }
    if (op.real_5g) {
      parts.push(tr('Real 5G'));
    }
    var techs = op.technologies || {};
    var present = [];
    TECHS.forEach(function (tech) {
      if (techs[tech]) present.push(tech);
    });
    if (present.length) {
      parts.push(present.join(', '));
    }
    return parts.join(' · ');
  }

  function cardMarkup(op) {
    var recommended = !!op.recommended;
    var cls = recommended
      ? 'border-blue-500 ring-2 ring-blue-500/40 bg-blue-50 dark:bg-blue-900/20 dark:border-blue-400'
      : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800';
    var html = '<li class="bo-card relative rounded-xl border p-4 transition-colors ' + cls +
      '" data-slug="' + esc(op.slug) + '">';
    if (recommended) {
      html += '<span class="absolute -top-2 left-4 inline-flex items-center rounded-full bg-blue-600 text-white text-[11px] font-semibold px-2 py-0.5">' +
        esc(tr('Recommended')) + '</span>';
    }
    var explainer = scoreExplainer(op);
    var scoreCls = 'ml-auto text-xs font-medium text-gray-500 dark:text-gray-400';
    var scoreAttr = '';
    if (explainer) {
      scoreCls += ' cursor-help underline decoration-dotted decoration-gray-300 dark:decoration-gray-600 underline-offset-2';
      scoreAttr = ' title="' + esc(explainer) + '"';
    }
    html += '<div class="flex items-center gap-3">' +
      '<span class="inline-block w-3 h-3 rounded-full flex-none" style="background-color: ' +
      (DOT_COLORS[op.slug] || '#94a3b8') + '"></span>' +
      '<span class="font-semibold text-gray-900 dark:text-white">' + esc(op.operator) + '</span>' +
      '<span class="' + scoreCls + '"' + scoreAttr + '>' +
      esc(tr('Score')) + ' ' + esc(op.rank_score) + '</span>' +
      '</div>';
    html += '<p class="mt-2 text-sm text-gray-700 dark:text-gray-200">' + esc(rationaleText(op)) + '</p>';

    html += '<div class="mt-2 flex flex-wrap items-center gap-2 text-xs">';
    var dist = formatDistance(op.nearest_distance_km);
    if (dist) {
      html += '<span class="text-gray-500 dark:text-gray-400">' + esc(tr('Nearest mast:')) + ' ' + esc(dist) + '</span>';
    }
    if (op.real_5g) {
      html += '<span class="inline-flex items-center rounded-full bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300 font-semibold px-2 py-0.5">' +
        esc(tr('Real 5G')) + '</span>';
    }
    var techs = op.technologies || {};
    TECHS.forEach(function (tech) {
      if (techs[tech]) {
        html += '<span class="inline-flex items-center rounded bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300 px-1.5 py-0.5">' + esc(tech) + '</span>';
      }
    });
    html += '</div>';

    if (op.referral_path) {
      html += '<a href="' + esc(op.referral_path) + '" rel="nofollow sponsored noopener" ' +
        'title="' + esc(tr('View offer at') + ' ' + op.operator) + '" ' +
        'class="group mt-3 inline-flex items-center gap-1 text-sm font-semibold text-blue-600 dark:text-blue-400 cursor-pointer hover:text-blue-700 dark:hover:text-blue-300 hover:underline underline-offset-2 transition-colors">' +
        esc(tr('See offer')) + ' <span aria-hidden="true" class="transition-transform group-hover:translate-x-0.5">&rarr;</span></a>';
    }
    html += '</li>';
    return html;
  }

  function statusFor(data) {
    switch (data.status) {
      case 'no_match': return tr('No matching address found.');
      case 'outside_pl': return tr('This address is outside Poland.');
      case 'no_coverage': return tr('No coverage near this address.');
      case 'invalid':
      case 'empty': return tr('Enter an address to compare operators.');
      case 'error': return tr('An error occurred. Please try again.');
      case 'ok': return (data.match && data.match.display) || '';
      default: return '';
    }
  }

  function render(data, statusEl, resultsEl) {
    statusEl.textContent = statusFor(data);
    var ops = data.operators || [];
    resultsEl.innerHTML = ops.map(cardMarkup).join('');
  }

  function skeletonCard() {
    return '<li class="relative rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 animate-pulse" aria-hidden="true">' +
      '<div class="flex items-center gap-3">' +
      '<span class="inline-block w-3 h-3 rounded-full flex-none bg-gray-200 dark:bg-gray-700"></span>' +
      '<span class="h-4 w-28 rounded bg-gray-200 dark:bg-gray-700"></span>' +
      '<span class="ml-auto h-3 w-12 rounded bg-gray-200 dark:bg-gray-700"></span>' +
      '</div>' +
      '<div class="mt-3 h-3 w-3/4 rounded bg-gray-200 dark:bg-gray-700"></div>' +
      '<div class="mt-2 flex flex-wrap gap-2">' +
      '<span class="h-5 w-16 rounded-full bg-gray-200 dark:bg-gray-700"></span>' +
      '<span class="h-5 w-10 rounded bg-gray-200 dark:bg-gray-700"></span>' +
      '<span class="h-5 w-10 rounded bg-gray-200 dark:bg-gray-700"></span>' +
      '</div>' +
      '<div class="mt-3 h-4 w-24 rounded bg-gray-200 dark:bg-gray-700"></div>' +
      '</li>';
  }

  function showSkeletons(resultsEl) {
    if (!resultsEl) return;
    var html = '';
    for (var i = 0; i < 3; i++) { html += skeletonCard(); }
    resultsEl.innerHTML = html;
  }

  function setupAutocomplete(input) {
    var box = document.getElementById('bo-suggestions');
    if (!input || !box) return;
    var timer = null;
    var current = [];
    var active = -1;
    var seq = 0;

    function hide() {
      box.classList.add('hidden');
      box.innerHTML = '';
      current = [];
      active = -1;
      input.setAttribute('aria-expanded', 'false');
    }

    function paint() {
      var items = box.children;
      for (var i = 0; i < items.length; i++) {
        if (i === active) {
          items[i].classList.add('bg-blue-50', 'dark:bg-gray-700');
          items[i].setAttribute('aria-selected', 'true');
        } else {
          items[i].classList.remove('bg-blue-50', 'dark:bg-gray-700');
          items[i].setAttribute('aria-selected', 'false');
        }
      }
    }

    function choose(r) {
      if (!r) return;
      input.value = r.display;
      hide();
      input.focus();
    }

    function fetchSuggest(url) {
      if (typeof globalFetch === 'function') return globalFetch(url);
      return fetch(url, { headers: { 'X-Requested-With': 'fetch' } })
        .then(function (response) { return response.json(); });
    }

    function show(results) {
      current = results;
      active = -1;
      box.innerHTML = '';
      results.forEach(function (r, idx) {
        var item = document.createElement('div');
        item.className = 'px-3 py-2 text-sm cursor-pointer text-gray-700 dark:text-gray-200 hover:bg-blue-50 dark:hover:bg-gray-700 border-b border-gray-100 dark:border-gray-700 last:border-b-0';
        item.setAttribute('role', 'option');
        item.setAttribute('aria-selected', 'false');
        item.textContent = r.display;
        item.addEventListener('mousedown', function (e) {
          e.preventDefault();
          choose(r);
        });
        item.addEventListener('mouseenter', function () {
          active = idx;
          paint();
        });
        box.appendChild(item);
      });
      box.classList.remove('hidden');
      input.setAttribute('aria-expanded', 'true');
    }

    input.addEventListener('input', function () {
      var q = this.value.trim();
      clearTimeout(timer);
      if (q.length < 3) { hide(); return; }
      var mySeq = ++seq;
      timer = setTimeout(function () {
        fetchSuggest('/geocode?q=' + encodeURIComponent(q))
          .then(function (data) {
            if (mySeq !== seq) return;
            var results = (data && data.results) || [];
            if (!results.length) { hide(); return; }
            show(results);
          })
          .catch(function () { if (mySeq === seq) hide(); });
      }, 220);
    });

    input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { hide(); return; }
      if (box.classList.contains('hidden') || !current.length) return;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        active = (active + 1) % current.length;
        paint();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        active = (active <= 0 ? current.length : active) - 1;
        paint();
      } else if (e.key === 'Enter') {
        if (active >= 0) {
          e.preventDefault();
          choose(current[active]);
        } else {
          hide();
        }
      }
    });

    document.addEventListener('click', function (e) {
      if (e.target !== input && !box.contains(e.target)) hide();
    });
  }

  function init() {
    var form = document.getElementById('bo-form');
    if (!form) return;
    var input = document.getElementById('bo-q');
    var statusEl = document.getElementById('bo-status');
    var resultsEl = document.getElementById('bo-results');

    setupAutocomplete(input);

    form.addEventListener('submit', function (event) {
      var query = (input && input.value || '').trim();
      if (!query) return;
      event.preventDefault();
      if (statusEl) statusEl.textContent = tr('Checking…');
      showSkeletons(resultsEl);
      var url = '/best-operator?q=' + encodeURIComponent(query) + '&format=json';
      fetch(url, { headers: { 'X-Requested-With': 'fetch' } })
        .then(function (response) { return response.json(); })
        .then(function (data) {
          render(data, statusEl, resultsEl);
          try {
            window.history.replaceState({}, document.title,
              '/best-operator?q=' + encodeURIComponent(query));
          } catch (_) {}
        })
        .catch(function () {
          window.location.assign('/best-operator?q=' + encodeURIComponent(query));
        });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
