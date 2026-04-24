// /account page interactions: copy + regenerate key + profile, password, delete.
// Loaded only on the account page (script tag in account.html).

document.addEventListener('DOMContentLoaded', () => {
  const copyBtn = document.getElementById('copy-api-key');
  const keyEl = document.getElementById('api-key-value');
  const regenBtn = document.getElementById('regen-api-key');
  const status = document.getElementById('regen-status');

  if (copyBtn && keyEl) {
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(keyEl.textContent.trim()).then(() => {
        const orig = copyBtn.textContent;
        copyBtn.textContent = 'Copied!';
        setTimeout(() => { copyBtn.textContent = orig; }, 1500);
      });
    });
  }

  if (regenBtn && keyEl && status) {
    regenBtn.addEventListener('click', () => {
      if (!confirm('Regenerating invalidates the current key immediately. Continue?')) {
        return;
      }
      status.textContent = 'Regenerating…';
      status.className = 'text-sm mt-2 text-gray-500';

      globalFetch('/account/regenerate_api_key', {
        method: 'POST',
        headers: { 'X-CSRF-Token': getCsrfToken() }
      }).then(data => {
        if (data && data.success && data.api_key) {
          keyEl.textContent = data.api_key;
          status.textContent = 'New API key generated.';
          status.className = 'text-sm mt-2 text-green-600 dark:text-green-400';
        } else {
          status.textContent = 'Failed to regenerate. Try again.';
          status.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
        }
      }).catch(err => {
        status.textContent = 'Error: ' + err.message;
        status.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
      });
    });
  }

  // ── Profile form ─────────────────────────────────────────────────────
  wireForm({
    formId: 'profile-form',
    statusId: 'profile-status',
    url: '/account/profile',
    okMsg: 'Profile saved.',
  });

  // ── Change password form ────────────────────────────────────────────
  wireForm({
    formId: 'password-form',
    statusId: 'password-status',
    url: '/account/password',
    okMsg: 'Password updated.',
    onSuccess: (data, form) => {
      // Server rotated the session and gave us a fresh CSRF token. Patch
      // the meta tag and every hidden _csrf_token input on the page so
      // subsequent forms keep working without a reload.
      if (data.csrf_token) {
        const meta = document.querySelector('meta[name="csrf-token"]');
        if (meta) meta.setAttribute('content', data.csrf_token);
        document.querySelectorAll('input[name="_csrf_token"]').forEach(i => {
          i.value = data.csrf_token;
        });
      }
      form.reset();
    },
  });

  // ── Create new named API key (PR #14) ───────────────────────────────
  const createKeyForm = document.getElementById('create-key-form');
  const createKeyStatus = document.getElementById('create-key-status');
  const newKeyBox = document.getElementById('new-key-display');
  const newKeyValue = document.getElementById('new-key-value');
  if (createKeyForm && createKeyStatus) {
    createKeyForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const fd = new FormData(createKeyForm);
      const body = { name: fd.get('name') };
      createKeyStatus.textContent = 'Creating…';
      createKeyStatus.className = 'text-sm mt-2 text-gray-500';

      globalFetch('/account/keys', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': getCsrfToken(),
        },
        body: JSON.stringify(body),
      }).then(data => {
        if (data && data.success && data.key) {
          createKeyStatus.textContent = 'Key created.';
          createKeyStatus.className = 'text-sm mt-2 text-green-600 dark:text-green-400';
          if (newKeyBox && newKeyValue) {
            newKeyValue.textContent = data.key;
            newKeyBox.classList.remove('hidden');
          }
          appendKeyRow(data);
          createKeyForm.reset();
        } else {
          const err = (data && data.error) || 'Failed.';
          createKeyStatus.textContent = err;
          createKeyStatus.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
        }
      }).catch(err => {
        createKeyStatus.textContent = 'Error: ' + err.message;
        createKeyStatus.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
      });
    });
  }

  document.querySelectorAll('button[data-revoke-id]').forEach(btn => {
    btn.addEventListener('click', () => revokeKey(parseInt(btn.dataset.revokeId, 10)));
  });

  // ── 2FA TOTP (rebuilt PR #25) ──────────────────────────────────────
  // Shared "render setup payload + un-hide the QR/verify card" — used by
  // both initial setup and regenerate. Calls the appropriate endpoint
  // and pipes {secret, otpauth_uri, qr_svg} into the shared #totp-setup-box.
  function showTotpSetupPayload(data) {
    const box = document.getElementById('totp-setup-box');
    if (!data || !data.success || !box) return false;
    document.getElementById('totp-secret').textContent = data.secret;
    document.getElementById('totp-uri').textContent = data.otpauth_uri;
    const qrHost = document.getElementById('totp-qr');
    if (qrHost && typeof data.qr_svg === 'string' && data.qr_svg.startsWith('<svg')) {
      // Server-rendered SVG — parse via DOMParser then attach. innerHTML
      // would also work since the SVG is from our server, but DOMParser
      // is the defense-in-depth path.
      const parsed = new DOMParser().parseFromString(data.qr_svg, 'image/svg+xml');
      const svgEl = parsed.documentElement;
      // segno's svg_inline() omits width/height (only viewBox). Without
      // intrinsic dimensions the parent's `display: flex` collapses the
      // SVG to 0×0 and the QR box renders empty. Pin to a scannable size.
      svgEl.setAttribute('width', '220');
      svgEl.setAttribute('height', '220');
      qrHost.textContent = '';
      qrHost.appendChild(svgEl);
    }
    box.classList.remove('hidden');
    return true;
  }

  // Setup (when 2FA disabled)
  const totpSetupBtn = document.getElementById('totp-setup-btn');
  if (totpSetupBtn) {
    totpSetupBtn.addEventListener('click', () => {
      globalFetch('/account/2fa/setup', {
        method: 'POST',
        headers: { 'X-CSRF-Token': getCsrfToken() },
      }).then(data => {
        if (showTotpSetupPayload(data)) {
          totpSetupBtn.disabled = true;
        } else {
          alert((data && data.error) || 'Setup failed.');
        }
      }).catch(e => alert('Error: ' + e.message));
    });
  }

  // Regenerate (when 2FA enabled): two-step — show password-confirm form,
  // then on its submit call /account/2fa/regenerate which returns the
  // same setup payload as /setup.
  const totpRegenBtn = document.getElementById('totp-regen-btn');
  const totpRegenConfirmForm = document.getElementById('totp-regen-confirm-form');
  if (totpRegenBtn && totpRegenConfirmForm) {
    totpRegenBtn.addEventListener('click', () => {
      totpRegenConfirmForm.classList.toggle('hidden');
    });
    totpRegenConfirmForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const fd = new FormData(totpRegenConfirmForm);
      const status = document.getElementById('totp-regen-status');
      status.textContent = 'Generating…';
      status.className = 'text-sm mt-2 text-gray-500';
      globalFetch('/account/2fa/regenerate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': getCsrfToken() },
        body: JSON.stringify({ current_password: fd.get('current_password') }),
      }).then(data => {
        if (showTotpSetupPayload(data)) {
          status.textContent = 'New secret ready — verify below.';
          status.className = 'text-sm mt-2 text-green-600 dark:text-green-400';
        } else {
          status.textContent = (data && data.error) || 'Regenerate failed.';
          status.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
        }
      }).catch(e => {
        status.textContent = 'Error: ' + e.message;
        status.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
      });
    });
  }

  // Verify (shared between setup + regenerate paths)
  const totpVerifyForm = document.getElementById('totp-verify-form');
  if (totpVerifyForm) {
    totpVerifyForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const fd = new FormData(totpVerifyForm);
      const status = document.getElementById('totp-verify-status');
      status.textContent = 'Verifying…';
      status.className = 'text-sm mt-2 text-gray-500';
      globalFetch('/account/2fa/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': getCsrfToken() },
        body: JSON.stringify({ code: fd.get('code') }),
      }).then(data => {
        if (data && data.success) {
          status.textContent = '2FA enabled.';
          status.className = 'text-sm mt-2 text-green-600 dark:text-green-400';
          const box = document.getElementById('totp-recovery-box');
          const list = document.getElementById('totp-recovery-list');
          if (box && list && Array.isArray(data.recovery_codes)) {
            list.textContent = '';
            data.recovery_codes.forEach(c => {
              const li = document.createElement('li');
              li.textContent = c;
              list.appendChild(li);
            });
            box.classList.remove('hidden');
          }
        } else {
          status.textContent = (data && data.error) || 'Verify failed.';
          status.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
        }
      }).catch(e => {
        status.textContent = 'Error: ' + e.message;
        status.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
      });
    });
  }

  // Disable (when 2FA enabled): button toggles the form, form submit calls API.
  const totpDisableShowBtn = document.getElementById('totp-disable-show-btn');
  const totpDisableForm = document.getElementById('totp-disable-form');
  if (totpDisableShowBtn && totpDisableForm) {
    totpDisableShowBtn.addEventListener('click', () => {
      totpDisableForm.classList.toggle('hidden');
    });
  }
  if (totpDisableForm) {
    totpDisableForm.addEventListener('submit', (e) => {
      e.preventDefault();
      if (!confirm('Disable 2FA? Your account will only be protected by your password.')) return;
      const fd = new FormData(totpDisableForm);
      const status = document.getElementById('totp-disable-status');
      status.textContent = 'Disabling…';
      status.className = 'text-sm mt-2 text-gray-500';
      globalFetch('/account/2fa/disable', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': getCsrfToken() },
        body: JSON.stringify({
          current_password: fd.get('current_password'),
          code: fd.get('code'),
        }),
      }).then(data => {
        if (data && data.success) {
          window.location.reload();
        } else {
          status.textContent = (data && data.error) || 'Disable failed.';
          status.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
        }
      }).catch(e => {
        status.textContent = 'Error: ' + e.message;
        status.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
      });
    });
  }

  // ── Live password requirements on /account change-password ────────
  // Reuses the same data-criteria DOM contract as the registration modal
  // (see common.js initializePasswordValidation). Inputs have unique IDs
  // so they don't collide with the registration modal's inputs.
  const newPwdInput = document.getElementById('changePasswordNew');
  const confirmPwdInput = document.getElementById('changePasswordConfirm');
  const reqsRoot = document.getElementById('changePasswordRequirements');
  if (newPwdInput && confirmPwdInput && reqsRoot) {
    const update = () => {
      const pw = newPwdInput.value;
      const cf = confirmPwdInput.value;
      const checks = {
        minLength: pw.length >= 8,
        number: /\d/.test(pw),
        uppercase: /[A-Z]/.test(pw),
        lowercase: /[a-z]/.test(pw),
        specialChar: /[!@#$%^&*(),.?":{}|<>]/.test(pw),
        passwordMatch: pw.length >= 8 && pw === cf,
      };
      reqsRoot.querySelectorAll('.password-requirement').forEach(el => {
        const ok = checks[el.dataset.criteria];
        el.classList.toggle('text-red-500', !ok);
        el.classList.toggle('dark:text-red-400', !ok);
        el.classList.toggle('text-green-600', ok);
        el.classList.toggle('dark:text-green-400', ok);
        const ind = el.querySelector('.indicator');
        if (ind) ind.textContent = ok ? '✓' : '✗';
      });
    };
    newPwdInput.addEventListener('input', update);
    confirmPwdInput.addEventListener('input', update);
  }

  // ── Saved locations (PR #30) ────────────────────────────────────────
  // Add / cancel / submit-create / delete / mute-toggle. Inline form
  // un-hides on click of "+ Add", collapses on cancel.
  const locAddBtn = document.getElementById('loc-add-btn');
  const locCancelBtn = document.getElementById('loc-cancel-btn');
  const locForm = document.getElementById('create-location-form');
  const locStatus = document.getElementById('create-location-status');

  if (locAddBtn && locForm) {
    locAddBtn.addEventListener('click', () => {
      locForm.classList.toggle('hidden');
      if (!locForm.classList.contains('hidden')) {
        const nameInput = locForm.querySelector('input[name="name"]');
        if (nameInput) {
          // PR #46.9: pre-fill a sensible default so the form can be
          // submitted in one click — was forcing the user to invent
          // a name before they'd even decided to save. Counts the
          // existing rows in #locations-tbody to pick "Location N+1"
          // (gives a deterministic name without scanning the DB).
          if (!nameInput.value) {
            const existing = document.querySelectorAll('#locations-tbody tr[data-loc-id]').length;
            nameInput.value = `Location ${existing + 1}`;
          }
          nameInput.focus();
          nameInput.select();
        }
      }
    });
  }
  if (locCancelBtn && locForm) {
    locCancelBtn.addEventListener('click', () => {
      locForm.classList.add('hidden');
      locForm.reset();
      if (locStatus) locStatus.textContent = '';
    });
  }

  // PR #46.6: "Use my location" — fill lat/lng from browser geolocation
  // API instead of asking the user to type coordinates by hand. Manual
  // entry stays as fallback if geolocation is denied / unavailable.
  const locUseGeoBtn = document.getElementById('loc-use-my-location-btn');
  const locLatInput = document.getElementById('loc-lat-input');
  const locLngInput = document.getElementById('loc-lng-input');
  const locGeoStatus = document.getElementById('loc-geo-status');
  if (locUseGeoBtn && locLatInput && locLngInput) {
    locUseGeoBtn.addEventListener('click', () => {
      if (!('geolocation' in navigator)) {
        if (locGeoStatus) locGeoStatus.textContent = 'Geolocation not supported by this browser.';
        return;
      }
      if (locGeoStatus) locGeoStatus.textContent = 'Locating…';
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const lat = pos.coords.latitude.toFixed(5);
          const lng = pos.coords.longitude.toFixed(5);
          locLatInput.value = lat;
          locLngInput.value = lng;
          if (locGeoStatus) {
            locGeoStatus.textContent = `Got it — ${lat}, ${lng}.`;
            locGeoStatus.className = 'text-xs text-green-600 dark:text-green-400';
          }
        },
        (err) => {
          // 1=permission denied, 2=position unavailable, 3=timeout
          const reason = err.code === 1
            ? 'Permission denied — type coordinates manually below.'
            : err.code === 3
              ? 'Timed out — try again or type coordinates manually.'
              : 'Could not determine location — type coordinates manually.';
          if (locGeoStatus) {
            locGeoStatus.textContent = reason;
            locGeoStatus.className = 'text-xs text-red-600 dark:text-red-400';
          }
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
      );
    });
  }

  if (locForm && locStatus) {
    locForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const fd = new FormData(locForm);
      const body = {
        name: fd.get('name'),
        description: fd.get('description') || null,
        lat: parseFloat(fd.get('lat')),
        lng: parseFloat(fd.get('lng')),
        radius_km: parseFloat(fd.get('radius_km') || '15'),
        alerting_enabled: fd.get('alerting_enabled') === 'on',
      };
      locStatus.textContent = 'Saving…';
      locStatus.className = 'text-sm mt-2 text-gray-500';

      globalFetch('/account/locations', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': getCsrfToken(),
        },
        body: JSON.stringify(body),
      }).then(data => {
        if (data && data.success && data.location) {
          locStatus.textContent = 'Location saved. Reloading…';
          locStatus.className = 'text-sm mt-2 text-green-600 dark:text-green-400';
          // Easiest path to refresh the table + audit log: full reload.
          setTimeout(() => window.location.reload(), 500);
        } else {
          locStatus.textContent = (data && data.error) || 'Failed.';
          locStatus.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
        }
      }).catch(err => {
        locStatus.textContent = 'Error: ' + err.message;
        locStatus.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
      });
    });
  }

  document.querySelectorAll('button[data-loc-delete-id]').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = parseInt(btn.dataset.locDeleteId, 10);
      if (!confirm('Delete this location and all its snapshots?')) return;
      globalFetch('/account/locations/' + id + '/delete', {
        method: 'POST',
        headers: { 'X-CSRF-Token': getCsrfToken() },
      }).then(data => {
        if (data && data.success) {
          const row = document.querySelector(`tr[data-loc-id="${id}"]`);
          if (row) row.remove();
        } else {
          alert((data && data.error) || 'Delete failed.');
        }
      }).catch(err => alert('Error: ' + err.message));
    });
  });

  document.querySelectorAll('button[data-loc-toggle-id]').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = parseInt(btn.dataset.locToggleId, 10);
      const wantOn = btn.dataset.current !== '1';
      globalFetch('/account/locations/' + id, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': getCsrfToken(),
        },
        body: JSON.stringify({ alerting_enabled: wantOn }),
      }).then(data => {
        if (data && data.success && data.location) {
          // Reload to keep the table label, badge, and audit log in sync —
          // fewer ways for the rendered state to drift from the server.
          window.location.reload();
        } else {
          alert((data && data.error) || 'Update failed.');
        }
      }).catch(err => alert('Error: ' + err.message));
    });
  });

  // ── Delete account form ─────────────────────────────────────────────
  const deleteForm = document.getElementById('delete-form');
  const deleteStatus = document.getElementById('delete-status');
  if (deleteForm && deleteStatus) {
    deleteForm.addEventListener('submit', (e) => {
      e.preventDefault();
      if (!confirm('This will permanently delete your account and API key. Continue?')) {
        return;
      }
      const fd = new FormData(deleteForm);
      const body = Object.fromEntries(fd.entries());
      deleteStatus.textContent = 'Deleting…';
      deleteStatus.className = 'text-sm mt-2 text-gray-500';

      globalFetch('/account/delete', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': getCsrfToken(),
        },
        body: JSON.stringify(body),
      }).then(data => {
        if (data && data.success) {
          // Account is gone. Bounce to home with replace() so /account is
          // not reachable via Back-button (would 401 anyway).
          window.location.replace('/');
        } else {
          const err = (data && data.error) || 'Delete failed.';
          deleteStatus.textContent = err;
          deleteStatus.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
        }
      }).catch(err => {
        deleteStatus.textContent = 'Error: ' + err.message;
        deleteStatus.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
      });
    });
  }
});

function wireForm({ formId, statusId, url, okMsg, onSuccess }) {
  const form = document.getElementById(formId);
  const statusEl = document.getElementById(statusId);
  if (!form || !statusEl) return;

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const body = Object.fromEntries(fd.entries());
    statusEl.textContent = 'Saving…';
    statusEl.className = 'text-sm mt-2 text-gray-500';

    globalFetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': getCsrfToken(),
      },
      body: JSON.stringify(body),
    }).then(data => {
      if (data && data.success) {
        statusEl.textContent = okMsg;
        statusEl.className = 'text-sm mt-2 text-green-600 dark:text-green-400';
        if (typeof onSuccess === 'function') onSuccess(data, form);
      } else {
        const err = (data && data.error) || 'Failed.';
        statusEl.textContent = err;
        statusEl.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
      }
    }).catch(err => {
      statusEl.textContent = 'Error: ' + err.message;
      statusEl.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
    });
  });
}

function revokeKey(keyId) {
  if (!confirm('Revoke this API key? Any client using it will get 403.')) return;
  globalFetch('/account/keys/' + keyId + '/revoke', {
    method: 'POST',
    headers: { 'X-CSRF-Token': getCsrfToken() },
  }).then(data => {
    if (data && data.success) {
      const row = document.querySelector(`tr[data-key-id="${keyId}"]`);
      if (row) {
        // Mark row as revoked: replace status cell + remove revoke button.
        const cells = row.querySelectorAll('td');
        if (cells.length >= 5) {
          cells[4].innerHTML = '<span class="text-red-600 dark:text-red-400">revoked</span>';
        }
        const btn = row.querySelector('button[data-revoke-id]');
        if (btn) btn.remove();
      }
    } else {
      alert((data && data.error) || 'Revoke failed.');
    }
  }).catch(err => alert('Error: ' + err.message));
}

function appendKeyRow(data) {
  const tbody = document.getElementById('api-keys-tbody');
  if (!tbody) return;
  const tr = document.createElement('tr');
  tr.dataset.keyId = data.id;
  tr.className = 'border-t border-gray-200 dark:border-gray-700';
  const masked = data.key.slice(0, 8) + '…' + data.key.slice(-4);
  // textContent on every cell — never innerHTML — defends against XSS in the
  // user-chosen `name` field.
  const tdName = document.createElement('td'); tdName.className = 'py-2 pr-2 font-medium'; tdName.textContent = data.name; tr.appendChild(tdName);
  const tdKey  = document.createElement('td'); tdKey.className  = 'py-2 pr-2 font-mono text-xs'; tdKey.textContent = masked; tr.appendChild(tdKey);
  const tdC    = document.createElement('td'); tdC.className    = 'py-2 pr-2 text-gray-500 dark:text-gray-400'; tdC.textContent = data.created_at.slice(0, 10); tr.appendChild(tdC);
  const tdL    = document.createElement('td'); tdL.className    = 'py-2 pr-2 text-gray-500 dark:text-gray-400'; tdL.textContent = 'never'; tr.appendChild(tdL);
  const tdS    = document.createElement('td'); tdS.className    = 'py-2 pr-2'; tdS.innerHTML = '<span class="text-green-600 dark:text-green-400">active</span>'; tr.appendChild(tdS);
  const tdA    = document.createElement('td'); tdA.className    = 'py-2 pr-2 text-right';
  const btn = document.createElement('button');
  btn.dataset.revokeId = data.id;
  btn.className = 'text-red-600 hover:underline text-xs';
  btn.textContent = 'Revoke';
  btn.addEventListener('click', () => revokeKey(data.id));
  tdA.appendChild(btn);
  tr.appendChild(tdA);
  tbody.appendChild(tr);
}
