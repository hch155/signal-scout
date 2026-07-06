// map.html — coverage-alert subscription CTA.
//
// Surfaces a "Subscribe to coverage changes at this location" CTA in the
// sidebar after ANY location resolves — an address search, a GPS fix, or a
// manual map pin. ui-interactions.js publishes the current target on
// window.SS_SubscribeTarget: an address search carries {addressQuery} (the
// backend geocodes it); a GPS/manual point carries {lat, lng, name} (the
// nearest-city label). Logged-in users POST /coverage/subscribe straight
// away; anonymous users get the sign-in modal and the subscribe is replayed
// once they're in (userLoggedIn event from common.js). The CTA markup lives
// in templates/_subscribe_cta.html as an inert <template>.
(function () {
  function getTemplate() {
    return document.getElementById('coverageSubscribeCtaTemplate');
  }

  // The target the sidebar result currently describes. Published by
  // ui-interactions.js on every resolved location; null while loading or on
  // an empty/failed resolution. Either {addressQuery} or {lat, lng, name}.
  function readTarget() {
    const target = window.SS_SubscribeTarget;
    if (!target) return null;
    if (typeof target.addressQuery === 'string') {
      const q = target.addressQuery.trim();
      return q.length >= 3 ? { addressQuery: q } : null;
    }
    if (typeof target.lat === 'number' && typeof target.lng === 'number') {
      return { lat: target.lat, lng: target.lng, name: (target.name || '').trim() };
    }
    return null;
  }

  function targetLabel(target) {
    if (target.addressQuery) return target.addressQuery;
    return target.name || t('this location');
  }

  function requestBody(target) {
    if (target.addressQuery) return { query: target.addressQuery };
    return { lat: target.lat, lng: target.lng, name: target.name };
  }

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

  function doSubscribe(target, cta) {
    if (!target) return Promise.resolve();
    const btn = cta && cta.querySelector('#coverage-subscribe-btn');
    const original = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = t('Subscribing…'); }

    return fetch('/coverage/subscribe', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': getCsrfToken(),
      },
      body: JSON.stringify(requestBody(target)),
    })
      .then(function (r) {
        return r.json()
          .catch(function () { return {}; })
          .then(function (body) { return { status: r.status, body: body }; });
      })
      .then(function (res) {
        if (res.status === 401) {
          window._isLoggedIn = false;
          pendingTarget = target;
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

  let pendingTarget = null;

  window.addEventListener('userLoggedIn', function () {
    if (!pendingTarget) return;
    const target = pendingTarget;
    pendingTarget = null;
    window._isLoggedIn = true;
    doSubscribe(target, document.getElementById('coverage-subscribe-cta'));
  });

  function onSubscribeClick(target, cta) {
    ensureLoginState().then(function (loggedIn) {
      if (loggedIn) { doSubscribe(target, cta); return; }
      pendingTarget = target;
      setStatus(cta, t('Sign in to get coverage alerts for this address.'));
      openSignInModal();
    });
  }

  function insertCta(sidebar, target) {
    const tpl = getTemplate();
    if (!tpl || !('content' in tpl)) return;
    if (sidebar.querySelector('#coverage-subscribe-cta')) return;

    const node = tpl.content.firstElementChild.cloneNode(true);
    const addr = node.querySelector('[data-subscribe-address]');
    if (addr) addr.textContent = targetLabel(target);
    const btn = node.querySelector('#coverage-subscribe-btn');
    if (btn) {
      btn.addEventListener('click', function () { onSubscribeClick(target, node); });
    }
    sidebar.insertBefore(node, sidebar.firstChild);
  }

  document.addEventListener('DOMContentLoaded', function () {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar || !getTemplate()) return;

    const observer = new MutationObserver(function () {
      const target = readTarget();
      if (!target) return;
      if (!sidebar.children.length) return;
      insertCta(sidebar, target);
    });
    observer.observe(sidebar, { childList: true });
  });

  window.SS_CoverageSubscribe = {
    subscribe: function (query) {
      onSubscribeClick({ addressQuery: query },
        document.getElementById('coverage-subscribe-cta'));
    },
  };
})();
