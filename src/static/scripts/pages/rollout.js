/**
 * Interactive trend chart for /rollout — renders an SVG bar chart from the
 * monthly_history JSON blob baked into #rollout-chart-host, with toggle
 * buttons to swap between total 3.5 GHz sites, a per-operator stack, and a
 * single operator. Mirrors stats-chart.js (vanilla SVG, no Chart.js).
 */
(function () {
  'use strict';

  var OPERATOR_COLORS = {
    'Orange':   { light: '#f97316', dark: '#fb923c' },
    'Play':     { light: '#7c3aed', dark: '#a78bfa' },
    'Plus':     { light: '#16a34a', dark: '#4ade80' },
    'T-Mobile': { light: '#ec4899', dark: '#f472b6' },
  };

  function isDark() {
    return document.documentElement.classList.contains('dark');
  }

  function colorFor(op) {
    var c = OPERATOR_COLORS[op];
    if (!c) return isDark() ? '#9ca3af' : '#6b7280';
    return isDark() ? c.dark : c.light;
  }

  function fmt(n) {
    return n.toLocaleString('en-US');
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

  function getTooltip(host) {
    var tip = host.querySelector('.rollout-chart-tooltip');
    if (tip) return tip;
    tip = document.createElement('div');
    tip.className = 'rollout-chart-tooltip';
    tip.style.cssText = [
      'position:absolute',
      'pointer-events:none',
      'z-index:10',
      'padding:6px 8px',
      'border-radius:4px',
      'font-size:11px',
      'line-height:1.4',
      'background:rgba(17,24,39,0.95)',
      'color:#fff',
      'box-shadow:0 4px 12px rgba(0,0,0,0.25)',
      'opacity:0',
      'transition:opacity 80ms ease-out',
      'white-space:nowrap',
    ].join(';');
    host.appendChild(tip);
    return tip;
  }

  function showTooltip(host, tip, x, contentLines) {
    tip.innerHTML = '';
    contentLines.forEach(function (line, i) {
      var div = document.createElement('div');
      if (i === 0) div.style.fontWeight = '600';
      div.textContent = line;
      tip.appendChild(div);
    });
    tip.style.opacity = '0';
    tip.style.left = '0px';
    tip.style.top = '0px';
    tip.style.display = 'block';
    var hostRect = host.getBoundingClientRect();
    var w = tip.offsetWidth;
    var left = Math.max(2, Math.min(hostRect.width - w - 2, x - w / 2));
    tip.style.left = left + 'px';
    tip.style.top = '4px';
    tip.style.opacity = '1';
  }

  function hideTooltip(tip) {
    if (tip) tip.style.opacity = '0';
  }

  function seriesFor(view, operators) {
    if (view === 'stacked') {
      return operators.map(function (op) {
        return {
          key: op, color: colorFor(op),
          get: function (h) { return (h.ops && h.ops[op]) || 0; },
        };
      });
    }
    if (operators.indexOf(view) !== -1) {
      return [{
        key: view, color: colorFor(view),
        get: function (h) { return (h.ops && h.ops[view]) || 0; },
      }];
    }
    return [{
      key: t('3.5 GHz sites'), color: colorFor('Plus'),
      get: function (h) { return h.total || 0; },
    }];
  }

  function renderChart(host, history, operators, view) {
    var tip = getTooltip(host);
    hideTooltip(tip);
    Array.prototype.slice.call(host.childNodes).forEach(function (n) {
      if (n !== tip) host.removeChild(n);
    });

    var width = host.clientWidth || 600;
    var height = host.clientHeight || 220;
    var padTop = 8, padBottom = 22, padLeft = 44, padRight = 8;
    var plotW = Math.max(1, width - padLeft - padRight);
    var plotH = Math.max(1, height - padTop - padBottom);

    var svg = svgEl('svg', {
      width: width, height: height,
      viewBox: '0 0 ' + width + ' ' + height,
      role: 'img',
      'aria-label': t('3.5 GHz site rollout chart'),
    });

    var series = seriesFor(view, operators);

    var yMax = 0;
    history.forEach(function (h) {
      var sum = 0;
      series.forEach(function (s) { sum += s.get(h); });
      if (sum > yMax) yMax = sum;
    });
    if (yMax <= 0) yMax = 1;

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

    var n = history.length;
    var slot = plotW / n;
    var barW = Math.max(2, Math.min(28, slot * 0.78));
    history.forEach(function (h, idx) {
      var cx = padLeft + slot * idx + slot / 2;
      var x = cx - barW / 2;
      var stackBottomY = padTop + plotH;

      var totalForRow = 0;
      series.forEach(function (s) { totalForRow += s.get(h); });

      var g = svgEl('g', { class: 'rollout-chart-col' });
      var hover = svgEl('rect', {
        x: padLeft + slot * idx, y: padTop,
        width: slot, height: plotH,
        fill: 'transparent',
      });
      g.appendChild(hover);

      var tipLines = [h.month];
      if (series.length === 1) {
        tipLines.push(series[0].key + ': ' + fmt(series[0].get(h)));
      } else {
        series.forEach(function (s) {
          var sv = s.get(h);
          if (sv > 0) tipLines.push(s.key + ': ' + fmt(sv));
        });
        tipLines.push(t('Total:') + ' ' + fmt(totalForRow));
      }

      g.addEventListener('mouseenter', function () {
        showTooltip(host, tip, cx, tipLines);
      });
      g.addEventListener('mouseleave', function () { hideTooltip(tip); });
      g.addEventListener('touchstart', function (ev) {
        ev.preventDefault();
        showTooltip(host, tip, cx, tipLines);
      }, { passive: false });

      series.forEach(function (s) {
        var sv = s.get(h);
        if (sv <= 0) return;
        var hpx = (sv / yMax) * plotH;
        var ry = stackBottomY - hpx;
        var rect = svgEl('rect', {
          x: x, y: ry, width: barW, height: hpx,
          fill: s.color, rx: '1.5', ry: '1.5',
        });
        g.appendChild(rect);
        stackBottomY = ry;
      });

      svg.appendChild(g);
    });

    svg.addEventListener('mouseleave', function () { hideTooltip(tip); });

    var labelMonths = [];
    if (n >= 1) labelMonths.push({ idx: 0, label: history[0].month });
    if (n >= 3) labelMonths.push({ idx: Math.floor(n / 2), label: history[Math.floor(n / 2)].month });
    if (n >= 2) labelMonths.push({ idx: n - 1, label: history[n - 1].month });
    labelMonths.forEach(function (lm) {
      var lx = padLeft + slot * lm.idx + slot / 2;
      var anchor = lm.idx === 0 ? 'start' : (lm.idx === n - 1 ? 'end' : 'middle');
      var tx2 = svgEl('text', {
        x: lx, y: padTop + plotH + 14,
        'text-anchor': anchor,
        'font-size': '10', fill: labelColor,
      });
      tx2.textContent = lm.label;
      svg.appendChild(tx2);
    });

    host.appendChild(svg);

    var legendHost = document.getElementById('rollout-chart-legend');
    if (legendHost) {
      while (legendHost.firstChild) legendHost.removeChild(legendHost.firstChild);
      if (view === 'stacked') {
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
  }

  function updateReadout(readout, history, operators, view) {
    if (!history.length) {
      readout.textContent = '';
      return;
    }
    var first = history[0], last = history[history.length - 1];
    var label, get;
    if (view === 'stacked' || view === 'total') {
      label = t('3.5 GHz sites');
      get = function (h) { return h.total || 0; };
    } else if (operators.indexOf(view) !== -1) {
      label = view + ' ' + t('3.5 GHz sites');
      get = function (h) { return (h.ops && h.ops[view]) || 0; };
    } else {
      label = t('3.5 GHz sites');
      get = function (h) { return h.total || 0; };
    }
    var d = get(last) - get(first);
    var sign = d >= 0 ? '+' : '';
    readout.textContent = fmt(get(first)) + ' → ' + fmt(get(last)) + ' ' + label
      + ' (' + sign + fmt(d) + ' ' + t('from') + ' ' + first.month + ' ' + t('to') + ' ' + last.month + ')';
  }

  function setActive(buttons, view) {
    buttons.forEach(function (btn) {
      var active = btn.getAttribute('data-view') === view;
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
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
    var host = document.getElementById('rollout-chart-host');
    var controls = document.getElementById('rollout-chart-controls');
    var readout = document.getElementById('rollout-chart-readout');
    if (!host || !controls) return;

    var raw = host.getAttribute('data-history');
    if (!raw) return;
    var history;
    try { history = JSON.parse(raw); } catch (e) { return; }
    if (!Array.isArray(history) || history.length < 2) return;

    var operators = [];
    try { operators = JSON.parse(host.getAttribute('data-operators') || '[]'); }
    catch (e) { operators = []; }
    if (!Array.isArray(operators)) operators = [];

    var buttons = Array.prototype.slice.call(
      controls.querySelectorAll('button[data-view]')
    );
    var current = 'total';

    function rerender() {
      renderChart(host, history, operators, current);
      if (readout) updateReadout(readout, history, operators, current);
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

    var resizeTimer;
    window.addEventListener('resize', function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(rerender, 100);
    });

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
