/**
 * Live B2B demo for /demo — calls the public coverage API from the
 * browser (anonymous tier, same-origin Referer) and renders the raw
 * JSON, an embedded coverage card, and a copy-paste curl example.
 *
 * Composes existing endpoints only:
 *   GET /coverage_by_address?q=  -> JSON shown verbatim
 *   GET /coverage_card?q=        -> full-document card, injected as an
 *                                   iframe srcdoc (the endpoint sends
 *                                   frame-ancestors 'none', so a plain
 *                                   src= navigation would be blocked).
 */
(function () {
  'use strict';

  function init() {
    var root = document.getElementById('api-demo');
    if (!root) return;

    var form = document.getElementById('api-demo-form');
    var input = document.getElementById('api-demo-input');
    var runBtn = document.getElementById('api-demo-run');
    var status = document.getElementById('api-demo-status');
    var jsonOut = document.getElementById('api-demo-json');
    var card = document.getElementById('api-demo-card');
    var curlOut = document.getElementById('api-demo-curl');
    var copyBtn = document.getElementById('api-demo-copy');

    var curlBase = (root.getAttribute('data-curl-base') || window.location.origin).replace(/\/+$/, '');
    var runLabel = runBtn ? runBtn.textContent : '';
    var copyLabel = copyBtn ? copyBtn.textContent : '';

    function buildCurl(query) {
      var url = curlBase + '/api/v1/coverage_by_address?q=' + encodeURIComponent(query);
      return 'curl -H "X-API-Key: YOUR_API_KEY" \\\n  "' + url + '"';
    }

    function setBusy(busy) {
      if (runBtn) {
        runBtn.disabled = busy;
        runBtn.textContent = busy ? t('Running…') : runLabel;
      }
    }

    function loadCard(query) {
      if (!card) return;
      fetch('/coverage_card?q=' + encodeURIComponent(query), {
        headers: { 'Accept': 'text/html' }
      })
        .then(function (r) { return r.text(); })
        .then(function (html) { card.srcdoc = html; })
        .catch(function () { card.removeAttribute('srcdoc'); });
    }

    function run(query) {
      query = (query || '').trim();
      if (!query) {
        status.textContent = t('Please enter an address.');
        return;
      }
      curlOut.textContent = buildCurl(query);
      setBusy(true);
      status.textContent = '';

      fetch('/coverage_by_address?q=' + encodeURIComponent(query), {
        headers: { 'Accept': 'application/json' }
      })
        .then(function (r) {
          return r.json()
            .catch(function () { return {}; })
            .then(function (body) { return { ok: r.ok, code: r.status, body: body }; });
        })
        .then(function (res) {
          jsonOut.textContent = JSON.stringify(res.body, null, 2);
          if (res.code === 404) {
            status.textContent = t('No matching address found.');
          } else if (res.body && res.body.outside_pl) {
            status.textContent = t('Address is outside Poland.');
          } else if (!res.ok) {
            status.textContent = (res.body && res.body.message) || t('An error occurred. Please try again.');
          } else {
            status.textContent = '';
          }
          loadCard(query);
        })
        .catch(function () {
          status.textContent = t('An error occurred. Please try again.');
        })
        .then(function () { setBusy(false); });
    }

    function copyCurl() {
      var text = curlOut.textContent;
      var done = function () {
        if (!copyBtn) return;
        copyBtn.textContent = t('Copied!');
        setTimeout(function () { copyBtn.textContent = copyLabel; }, 1500);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done).catch(function () { fallbackCopy(text, done); });
      } else {
        fallbackCopy(text, done);
      }
    }

    function fallbackCopy(text, done) {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'absolute';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); done(); } catch (e) { /* clipboard blocked */ }
      document.body.removeChild(ta);
    }

    if (form) {
      form.addEventListener('submit', function (ev) {
        ev.preventDefault();
        run(input ? input.value : '');
      });
    }
    if (copyBtn) {
      copyBtn.addEventListener('click', copyCurl);
    }

    var preset = root.getAttribute('data-default-q') || (input ? input.value : '');
    if (preset) run(preset);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
