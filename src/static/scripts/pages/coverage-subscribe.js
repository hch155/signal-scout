// map.html — coverage-alert subscription CTA.
//
// Surfaces a "Subscribe to coverage changes at this address" CTA in the
// sidebar after an address search. Logged-in users POST /coverage/subscribe
// straight away; anonymous users get the sign-in modal and the subscribe
// is replayed once they're in (userLoggedIn event from common.js). The CTA
// markup lives in templates/_subscribe_cta.html as an inert <template>.
(function () {
  function getTemplate() {
    return document.getElementById('coverageSubscribeCtaTemplate');
  }

  // The address the sidebar result currently describes. Set on an address
  // search (suggestion pick / Enter), cleared on a raw map click so a
  // coordinate click never offers an address subscription.
  let currentAddress = '';

  document.addEventListener('mousedown', function (e) {
    const item = e.target.closest && e.target.closest('.ss-suggestion');
    if (item) currentAddress = (item.textContent || '').trim();
  }, true);

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter') return;
    const input = e.target;
    if (input && input.id === 'addressSearchInput') {
      currentAddress = (input.value || '').trim();
    }
  }, true);

  document.addEventListener('click', function (e) {
    if (e.target.closest && e.target.closest('#mapid')) currentAddress = '';
  }, true);

  function ensureLoginState() {
    if (typeof window._isLoggedIn === 'boolean') {
      return Promise.resolve(window._isLoggedIn);
    }
    return fetch('/session_check')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        window._isLoggedIn = !!(d && d.logged_in);
        return window._isLoggedIn;
      })
      .catch(function () { return false; });
  }

  function openSignInModal() {
    if (typeof window.toggleSignInModal === 'function') {
      window.toggleSignInModal();
      return;
    }
    const btn = document.getElementById('signInBtn')
      || document.getElementById('signInBtnMobile');
    if (btn) btn.click();
  }

  function setStatus(cta, text) {
    const label = cta && cta.querySelector('[data-subscribe-label]');
    if (label) label.textContent = text;
  }

  function markDone(cta, text) {
    const row = cta && cta.querySelector('[data-subscribe-row]');
    if (row) row.remove();
    setStatus(cta, text);
  }

  function errorMessage(body) {
    const code = body && body.error;
    if (code === 'no_match') return t('No matching address found.');
    if (code === 'outside_pl') return t('That address is outside Poland.');
    if (code === 'limit_reached') {
      return t('Saved-location limit reached — manage it in your account.');
    }
    return t('Could not subscribe — try again.');
  }

  function doSubscribe(query, cta) {
    if (!query) return Promise.resolve();
    const btn = cta && cta.querySelector('#coverage-subscribe-btn');
    const original = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = t('Subscribing…'); }

    return fetch('/coverage/subscribe', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': getCsrfToken(),
      },
      body: JSON.stringify({ query: query }),
    })
      .then(function (r) {
        return r.json()
          .catch(function () { return {}; })
          .then(function (body) { return { status: r.status, body: body }; });
      })
      .then(function (res) {
        if (res.status === 401) {
          window._isLoggedIn = false;
          pendingQuery = query;
          if (btn) { btn.disabled = false; btn.textContent = original; }
          setStatus(cta, t('Sign in to get coverage alerts for this address.'));
          openSignInModal();
          return;
        }
        if (res.status >= 200 && res.status < 300 && res.body && res.body.success) {
          markDone(cta, res.body.created
            ? t("Subscribed — we'll email you when coverage here changes.")
            : t('Already watching this address — alerts are on.'));
          return;
        }
        if (btn) { btn.disabled = false; btn.textContent = original; }
        setStatus(cta, errorMessage(res.body));
      })
      .catch(function () {
        if (btn) { btn.disabled = false; btn.textContent = original; }
        setStatus(cta, t('Could not subscribe — try again.'));
      });
  }

  let pendingQuery = '';

  window.addEventListener('userLoggedIn', function () {
    if (!pendingQuery) return;
    const q = pendingQuery;
    pendingQuery = '';
    window._isLoggedIn = true;
    doSubscribe(q, document.getElementById('coverage-subscribe-cta'));
  });

  function onSubscribeClick(query, cta) {
    ensureLoginState().then(function (loggedIn) {
      if (loggedIn) { doSubscribe(query, cta); return; }
      pendingQuery = query;
      setStatus(cta, t('Sign in to get coverage alerts for this address.'));
      openSignInModal();
    });
  }

  function insertCta(sidebar, query) {
    const tpl = getTemplate();
    if (!tpl || !('content' in tpl)) return;
    if (sidebar.querySelector('#coverage-subscribe-cta')) return;

    const node = tpl.content.firstElementChild.cloneNode(true);
    const addr = node.querySelector('[data-subscribe-address]');
    if (addr) addr.textContent = query;
    const btn = node.querySelector('#coverage-subscribe-btn');
    if (btn) {
      btn.addEventListener('click', function () { onSubscribeClick(query, node); });
    }
    sidebar.insertBefore(node, sidebar.firstChild);
  }

  document.addEventListener('DOMContentLoaded', function () {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar || !getTemplate()) return;

    const observer = new MutationObserver(function () {
      const query = currentAddress;
      if (!query || query.length < 3) return;
      if (!sidebar.children.length) return;
      insertCta(sidebar, query);
    });
    observer.observe(sidebar, { childList: true });
  });

  window.SS_CoverageSubscribe = {
    subscribe: function (query) {
      onSubscribeClick(query, document.getElementById('coverage-subscribe-cta'));
    },
  };
})();
