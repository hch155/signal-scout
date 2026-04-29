/**
 * Interactive trend chart for /stats — renders an SVG bar chart from
 * the monthly_history JSON blob baked into #stats-chart-host's data
 * attribute, with toggle buttons to swap which series is shown.
 *
 * Vanilla SVG (no Chart.js / uPlot) so we don't need another vendored
 * dependency or a CSP carve-out. Single-axis charts only — mixing
 * units across two axes is the #1 source of misleading dashboards.
 */
(function () {
  'use strict';

  var GENERATION_COLORS = {
    '5G':   { light: '#10b981', dark: '#34d399' },   // emerald
    'LTE':  { light: '#3b82f6', dark: '#60a5fa' },   // blue
    'UMTS': { light: '#f59e0b', dark: '#fbbf24' },   // amber
    'GSM':  { light: '#9ca3af', dark: '#d1d5db' },   // gray
  };

  function isDark() {
    return document.documentElement.classList.contains('dark');
  }

  function colorFor(gen) {
    var c = GENERATION_COLORS[gen];
    if (!c) return isDark() ? '#9ca3af' : '#6b7280';
    return isDark() ? c.dark : c.light;
  }

  function fmt(n) {
    return n.toLocaleString('en-US');
  }

  function pluralize(n, singular, plural) {
    return n === 1 ? singular : plural;
  }

  function svgEl(name, attrs) {
    var el = document.createElementNS('http://www.w3.org/2000/svg', name);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        el.setAttribute(k, attrs[k]);
      });
    }
    return el;
  }

  /** Render a stacked-or-single bar chart into the given <svg>. */
  function renderChart(host, history, view) {
    // Clear previous render.
    while (host.firstChild) host.removeChild(host.firstChild);

    var width = host.clientWidth || 600;
    var height = host.clientHeight || 220;
    var padTop = 8, padBottom = 22, padLeft = 44, padRight = 8;
    var plotW = Math.max(1, width - padLeft - padRight);
    var plotH = Math.max(1, height - padTop - padBottom);

    var svg = svgEl('svg', {
      width: width, height: height,
      viewBox: '0 0 ' + width + ' ' + height,
      role: 'img',
      'aria-label': 'Monthly trend chart',
    });

    // Series for the active view.
    var series; // [{ key, color, get(h) -> number }]
    if (view === 'sites') {
      series = [{ key: 'Sites', color: colorFor('LTE'),
                  get: function (h) { return h.sites || 0; } }];
    } else if (view === 'generations') {
      series = ['5G', 'LTE', 'UMTS', 'GSM'].map(function (g) {
        return {
          key: g, color: colorFor(g),
          get: function (h) { return (h.gen && h.gen[g]) || 0; },
        };
      });
    } else if (view === '5G' || view === 'LTE' || view === 'UMTS' || view === 'GSM') {
      var g = view;
      series = [{ key: g, color: colorFor(g),
                  get: function (h) { return (h.gen && h.gen[g]) || 0; } }];
    } else {
      // Default: total band entries.
      series = [{ key: 'Band entries', color: colorFor('5G'),
                  get: function (h) { return h.entries || 0; } }];
    }

    // Compute y-max as the max stacked total across all months.
    var yMax = 0;
    history.forEach(function (h) {
      var sum = 0;
      series.forEach(function (s) { sum += s.get(h); });
      if (sum > yMax) yMax = sum;
    });
    if (yMax <= 0) yMax = 1;

    // Y-axis gridlines + labels (5 ticks).
    var ticks = 4;
    var axisColor = isDark() ? '#374151' : '#e5e7eb';
    var labelColor = isDark() ? '#9ca3af' : '#6b7280';
    for (var i = 0; i <= ticks; i++) {
      var y = padTop + plotH - (plotH * i / ticks);
      var v = Math.round(yMax * i / ticks);
      svg.appendChild(svgEl('line', {
        x1: padLeft, x2: padLeft + plotW, y1: y, y2: y,
        stroke: axisColor, 'stroke-width': '1',
      }));
      var tx = svgEl('text', {
        x: padLeft - 4, y: y + 3,
        'text-anchor': 'end',
        'font-size': '10', fill: labelColor,
      });
      tx.textContent = v >= 1000 ? (v / 1000).toFixed(0) + 'k' : String(v);
      svg.appendChild(tx);
    }

    // Bars.
    var n = history.length;
    var slot = plotW / n;
    var barW = Math.max(2, Math.min(28, slot * 0.78));
    history.forEach(function (h, idx) {
      var cx = padLeft + slot * idx + slot / 2;
      var x = cx - barW / 2;
      var stackBottomY = padTop + plotH;

      var totalForRow = 0;
      series.forEach(function (s) { totalForRow += s.get(h); });

      // Tooltip-target group covering the whole column for easier hover.
      var g = svgEl('g', { class: 'stats-chart-col' });
      var hover = svgEl('rect', {
        x: padLeft + slot * idx, y: padTop,
        width: slot, height: plotH,
        fill: 'transparent',
      });
      hover.setAttribute('data-month', h.month);
      hover.setAttribute('data-total', totalForRow);
      g.appendChild(hover);

      series.forEach(function (s) {
        var v = s.get(h);
        if (v <= 0) return;
        var hpx = (v / yMax) * plotH;
        var y = stackBottomY - hpx;
        var rect = svgEl('rect', {
          x: x, y: y, width: barW, height: hpx,
          fill: s.color, rx: '1.5', ry: '1.5',
        });
        var title = svgEl('title');
        title.textContent = h.month + ' — ' + s.key + ': ' + fmt(v);
        rect.appendChild(title);
        g.appendChild(rect);
        stackBottomY = y;
      });

      svg.appendChild(g);
    });

    // X-axis: first / mid / last labels (avoid clutter at 25 bars).
    var labelMonths = [];
    if (n >= 1) labelMonths.push({ idx: 0, label: history[0].month });
    if (n >= 3) labelMonths.push({ idx: Math.floor(n / 2), label: history[Math.floor(n / 2)].month });
    if (n >= 2) labelMonths.push({ idx: n - 1, label: history[n - 1].month });
    labelMonths.forEach(function (lm) {
      var cx = padLeft + slot * lm.idx + slot / 2;
      var anchor = lm.idx === 0 ? 'start' : (lm.idx === n - 1 ? 'end' : 'middle');
      var tx = svgEl('text', {
        x: cx, y: padTop + plotH + 14,
        'text-anchor': anchor,
        'font-size': '10', fill: labelColor,
      });
      tx.textContent = lm.label;
      svg.appendChild(tx);
    });

    host.appendChild(svg);

    // Legend (only meaningful for stacked-by-generation). Rendered as
    // a SIBLING of the chart host — the host has a fixed h-56/h-64
    // utility class, so anything appended INSIDE the host gets pushed
    // past the bottom edge and overlaps the readout below it. A
    // dedicated #stats-chart-legend slot below the host handles this.
    var legendHost = document.getElementById('stats-chart-legend');
    if (legendHost) {
      while (legendHost.firstChild) legendHost.removeChild(legendHost.firstChild);
      if (view === 'generations') {
        legendHost.className = 'flex flex-wrap gap-3 mt-2 text-xs text-gray-600 dark:text-gray-300';
        series.forEach(function (s) {
          var item = document.createElement('span');
          item.className = 'inline-flex items-center gap-1.5';
          var swatch = document.createElement('span');
          swatch.className = 'inline-block w-3 h-3 rounded-sm';
          swatch.style.background = s.color;
          item.appendChild(swatch);
          item.appendChild(document.createTextNode(s.key));
          legendHost.appendChild(item);
        });
      }
    }

    return { series: series, yMax: yMax };
  }

  function updateReadout(readout, history, view) {
    if (!history.length) {
      readout.textContent = '';
      return;
    }
    var first = history[0], last = history[history.length - 1];
    var label, get;
    switch (view) {
      case 'sites':
        label = 'physical ' + pluralize(2, 'site', 'sites');
        get = function (h) { return h.sites || 0; };
        break;
      case 'generations':
        label = 'total band entries (all generations)';
        get = function (h) { return h.entries || 0; };
        break;
      case '5G': case 'LTE': case 'UMTS': case 'GSM':
        label = view + ' band entries';
        get = function (h) { return (h.gen && h.gen[view]) || 0; };
        break;
      default:
        label = 'band entries';
        get = function (h) { return h.entries || 0; };
    }
    var d = get(last) - get(first);
    var sign = d >= 0 ? '+' : '';
    readout.textContent = fmt(get(first)) + ' → ' + fmt(get(last)) + ' ' + label
      + ' (' + sign + fmt(d) + ' from ' + first.month + ' to ' + last.month + ')';
  }

  function setActive(buttons, view) {
    buttons.forEach(function (btn) {
      var active = btn.getAttribute('data-view') === view;
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
      // Tailwind classes already applied; toggle the active palette.
      if (active) {
        btn.classList.add('bg-blue-600', 'text-white');
        btn.classList.remove('bg-white', 'text-gray-700', 'dark:bg-gray-700', 'dark:text-gray-100');
      } else {
        btn.classList.remove('bg-blue-600', 'text-white');
        btn.classList.add('bg-white', 'text-gray-700', 'dark:bg-gray-700', 'dark:text-gray-100');
      }
    });
  }

  function init() {
    var host = document.getElementById('stats-chart-host');
    var controls = document.getElementById('stats-chart-controls');
    var readout = document.getElementById('stats-chart-readout');
    if (!host || !controls) return;

    var raw = host.getAttribute('data-history');
    if (!raw) return;
    var history;
    try { history = JSON.parse(raw); } catch (e) { return; }
    if (!Array.isArray(history) || history.length < 2) return;

    var buttons = Array.prototype.slice.call(
      controls.querySelectorAll('button[data-view]')
    );
    var current = 'entries';

    function rerender() {
      renderChart(host, history, current);
      if (readout) updateReadout(readout, history, current);
      setActive(buttons, current);
    }

    buttons.forEach(function (btn) {
      btn.addEventListener('click', function () {
        var v = btn.getAttribute('data-view');
        if (!v || v === current) return;
        current = v;
        rerender();
      });
    });

    // Re-render on resize (debounced) so the chart fills the new
    // width when the user rotates a phone or resizes a desktop window.
    var resizeTimer;
    window.addEventListener('resize', function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(rerender, 100);
    });

    // Re-render when the user toggles dark mode (palette changes).
    var themeObserver = new MutationObserver(function (muts) {
      for (var i = 0; i < muts.length; i++) {
        if (muts[i].attributeName === 'class') { rerender(); return; }
      }
    });
    themeObserver.observe(document.documentElement, { attributes: true });

    rerender();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
