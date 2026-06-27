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
    html += '<div class="flex items-center gap-3">' +
      '<span class="inline-block w-3 h-3 rounded-full flex-none" style="background-color: ' +
      (DOT_COLORS[op.slug] || '#94a3b8') + '"></span>' +
      '<span class="font-semibold text-gray-900 dark:text-white">' + esc(op.operator) + '</span>' +
      '<span class="ml-auto text-xs font-medium text-gray-500 dark:text-gray-400">' +
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
        'class="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-blue-600 dark:text-blue-400 hover:underline">' +
        esc(tr('See offer')) + ' <span aria-hidden="true">&rarr;</span></a>';
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

  function init() {
    var form = document.getElementById('bo-form');
    if (!form) return;
    var input = document.getElementById('bo-q');
    var statusEl = document.getElementById('bo-status');
    var resultsEl = document.getElementById('bo-results');

    form.addEventListener('submit', function (event) {
      var query = (input && input.value || '').trim();
      if (!query) return;
      event.preventDefault();
      if (statusEl) statusEl.textContent = tr('Checking…');
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
