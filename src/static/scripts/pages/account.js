// /account page interactions: copy + regenerate key + profile, password, delete.
// Loaded only on the account page (script tag in account.html).

document.addEventListener('DOMContentLoaded', () => {
  initAccountTabs();
  // PR #48.3: email notifications toggle. Posts the new value to
  // /account/email_preference; status text gives instant feedback.
  // Failures revert the checkbox so the UI never lies about what's
  // stored on the server.
  const emailToggle = document.getElementById('email-alerts-toggle');
  const emailPrefStatus = document.getElementById('email-pref-status');
  if (emailToggle) {
    emailToggle.addEventListener('change', () => {
      const desired = emailToggle.checked;
      if (emailPrefStatus) {
        emailPrefStatus.textContent = t('Saving…');
        emailPrefStatus.className = 'text-xs mt-1 text-gray-500 dark:text-gray-400';
      }
      globalFetch('/account/email_preference', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': getCsrfToken(),
        },
        body: JSON.stringify({ enabled: desired }),
      }).then(data => {
        if (data && data.success) {
          if (emailPrefStatus) {
            emailPrefStatus.textContent = data.email_alerts_enabled
              ? t('✓ Email enabled.')
              : t('✓ Email disabled.');
            emailPrefStatus.className = 'text-xs mt-1 text-green-600 dark:text-green-400';
          }
        } else {
          emailToggle.checked = !desired;
          if (emailPrefStatus) {
            emailPrefStatus.textContent = (data && data.error) || t('Save failed.');
            emailPrefStatus.className = 'text-xs mt-1 text-red-600 dark:text-red-400';
          }
        }
      }).catch(() => {
        emailToggle.checked = !desired;
        if (emailPrefStatus) {
          emailPrefStatus.textContent = t('Network error — try again.');
          emailPrefStatus.className = 'text-xs mt-1 text-red-600 dark:text-red-400';
        }
      });
    });
  }

  // PR #47: `keyEl` holds only the `first8…last4` prefix now (we don't
  // store plaintext at rest). `copyBtn` was removed from the template
  // because copying the prefix is meaningless — we keep a lookup here
  // so older cached templates don't crash on re-render. The freshly
  // rotated raw key surfaces in #regen-key-value via the one-shot
  // reveal banner instead.
  const copyBtn = document.getElementById('copy-api-key');
  const keyEl = document.getElementById('api-key-value');
  const regenBtn = document.getElementById('regen-api-key');
  const status = document.getElementById('regen-status');
  const regenBox = document.getElementById('regen-key-display');
  const regenValue = document.getElementById('regen-key-value');
  const regenCopyBtn = document.getElementById('regen-copy-btn');

  if (copyBtn && keyEl) {
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(keyEl.textContent.trim()).then(() => {
        const orig = copyBtn.textContent;
        copyBtn.textContent = t('Copied!');
        setTimeout(() => { copyBtn.textContent = orig; }, 1500);
      });
    });
  }

  if (regenCopyBtn && regenValue) {
    regenCopyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(regenValue.textContent.trim()).then(() => {
        const orig = regenCopyBtn.textContent;
        regenCopyBtn.textContent = t('Copied!');
        setTimeout(() => { regenCopyBtn.textContent = orig; }, 1500);
      });
    });
  }

  const resendBtn = document.getElementById('resendVerification');
  const resendStatus = document.getElementById('resendVerificationStatus');
  if (resendBtn && resendStatus) {
    resendBtn.addEventListener('click', () => {
      resendBtn.disabled = true;
      resendStatus.textContent = t('Sending…');
      globalFetch('/account/resend_verification', {
        method: 'POST',
        headers: { 'X-CSRF-Token': getCsrfToken() }
      }).then(data => {
        resendStatus.textContent = (data && data.message) || t('Verification email sent.');
      }).catch(() => {
        resendBtn.disabled = false;
        resendStatus.textContent = t('Could not send — try again.');
      });
    });
  }

  if (regenBtn && status) {
    regenBtn.addEventListener('click', () => {
      if (!confirm(t('Regenerating invalidates the current key immediately. Continue?'))) {
        return;
      }
      status.textContent = t('Regenerating…');
      status.className = 'text-sm mt-2 text-gray-500';

      globalFetch('/account/regenerate_api_key', {
        method: 'POST',
        headers: { 'X-CSRF-Token': getCsrfToken() }
      }).then(data => {
        if (data && data.success && data.api_key) {
          // Show the raw key in the one-shot reveal box (user must copy
          // now). Replace the prefix display with first8…last4 of the
          // new key so the at-rest preview matches what they just copied.
          if (regenBox && regenValue) {
            regenValue.textContent = data.api_key;
            regenBox.classList.remove('hidden');
          }
          if (keyEl) {
            const k = data.api_key;
            keyEl.textContent = k.slice(0, 8) + '…' + k.slice(-4);
          }
          status.textContent = t('New API key generated. Save it now. It will not be shown again.');
          status.className = 'text-sm mt-2 text-green-600 dark:text-green-400';
        } else {
          status.textContent = t('Failed to regenerate. Try again.');
          status.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
        }
      }).catch(err => {
        status.textContent = t('Error: {message}').replace('{message}', err.message);
        status.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
      });
    });
  }

  // ── Profile form ─────────────────────────────────────────────────────
  wireForm({
    formId: 'profile-form',
    statusId: 'profile-status',
    url: '/account/profile',
    okMsg: t('Profile saved.'),
  });

  // ── Change password form ────────────────────────────────────────────
  wireForm({
    formId: 'password-form',
    statusId: 'password-status',
    url: '/account/password',
    okMsg: t('Password updated.'),
    onSuccess: (data, form) => {
      // Server rotated the session — patch CSRF token across the page so
      // subsequent forms keep working without a reload.
      if (window.applyRotatedCsrfToken) window.applyRotatedCsrfToken(data.csrf_token);
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
      createKeyStatus.textContent = t('Creating…');
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
          createKeyStatus.textContent = t('Key created.');
          createKeyStatus.className = 'text-sm mt-2 text-green-600 dark:text-green-400';
          if (newKeyBox && newKeyValue) {
            newKeyValue.textContent = data.key;
            newKeyBox.classList.remove('hidden');
          }
          appendKeyRow(data);
          createKeyForm.reset();
        } else {
          const err = (data && data.error) || t('Failed.');
          createKeyStatus.textContent = err;
          createKeyStatus.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
        }
      }).catch(err => {
        createKeyStatus.textContent = t('Error: {message}').replace('{message}', err.message);
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
      // PR #47.2: segno's svg_inline() omits the SVG xmlns attribute (it
      // expects to be inlined into HTML). DOMParser with image/svg+xml
      // then parses every node as a foreign element and the QR renders
      // empty. innerHTML on an HTML element correctly applies the SVG
      // namespace coercion the spec defines, so we use that — the source
      // is our own backend so XSS isn't a concern.
      qrHost.innerHTML = data.qr_svg;
      const svgEl = qrHost.querySelector('svg');
      if (svgEl) {
        if (!svgEl.getAttribute('viewBox')) {
          const nativeW = parseFloat(svgEl.getAttribute('width')) || 0;
          const nativeH = parseFloat(svgEl.getAttribute('height')) || 0;
          if (nativeW && nativeH) {
            svgEl.setAttribute('viewBox', '0 0 ' + nativeW + ' ' + nativeH);
          }
        }
        svgEl.setAttribute('width', '220');
        svgEl.setAttribute('height', '220');
      }
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
          alert((data && data.error) || t('Setup failed.'));
        }
      }).catch(e => alert(t('Error: {message}').replace('{message}', e.message)));
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
      status.textContent = t('Generating…');
      status.className = 'text-sm mt-2 text-gray-500';
      const regenBody = {};
      if (fd.get('current_password') !== null) regenBody.current_password = fd.get('current_password');
      if (fd.get('code') !== null) regenBody.code = fd.get('code');
      globalFetch('/account/2fa/regenerate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': getCsrfToken() },
        body: JSON.stringify(regenBody),
      }).then(data => {
        if (showTotpSetupPayload(data)) {
          status.textContent = t('New secret ready. Verify below.');
          status.className = 'text-sm mt-2 text-green-600 dark:text-green-400';
        } else {
          status.textContent = (data && data.error) || t('Regenerate failed.');
          status.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
        }
      }).catch(e => {
        status.textContent = t('Error: {message}').replace('{message}', e.message);
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
      status.textContent = t('Verifying…');
      status.className = 'text-sm mt-2 text-gray-500';
      globalFetch('/account/2fa/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': getCsrfToken() },
        body: JSON.stringify({ code: fd.get('code') }),
      }).then(data => {
        if (data && data.success) {
          status.textContent = t('2FA enabled.');
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
          status.textContent = (data && data.error) || t('Verify failed.');
          status.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
        }
      }).catch(e => {
        status.textContent = t('Error: {message}').replace('{message}', e.message);
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
      if (!confirm(t('Disable 2FA? Your account will only be protected by your password.'))) return;
      const fd = new FormData(totpDisableForm);
      const status = document.getElementById('totp-disable-status');
      status.textContent = t('Disabling…');
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
          status.textContent = (data && data.error) || t('Disable failed.');
          status.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
        }
      }).catch(e => {
        status.textContent = t('Error: {message}').replace('{message}', e.message);
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
            nameInput.value = t('Location {n}').replace('{n}', existing + 1);
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
        if (locGeoStatus) locGeoStatus.textContent = t('Geolocation not supported by this browser.');
        return;
      }
      if (locGeoStatus) locGeoStatus.textContent = t('Locating…');
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const lat = pos.coords.latitude.toFixed(5);
          const lng = pos.coords.longitude.toFixed(5);
          locLatInput.value = lat;
          locLngInput.value = lng;
          if (locGeoStatus) {
            locGeoStatus.textContent = t('Got it — {lat}, {lng}.').replace('{lat}', lat).replace('{lng}', lng);
            locGeoStatus.className = 'text-xs text-green-600 dark:text-green-400';
          }
        },
        (err) => {
          // 1=permission denied, 2=position unavailable, 3=timeout
          const reason = err.code === 1
            ? t('Permission denied — type coordinates manually below.')
            : err.code === 3
              ? t('Timed out — try again or type coordinates manually.')
              : t('Could not determine location — type coordinates manually.');
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
      locStatus.textContent = t('Saving…');
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
          locStatus.textContent = t('Location saved. Reloading…');
          locStatus.className = 'text-sm mt-2 text-green-600 dark:text-green-400';
          // Easiest path to refresh the table + audit log: full reload.
          setTimeout(() => window.location.reload(), 500);
        } else {
          locStatus.textContent = (data && data.error) || t('Failed.');
          locStatus.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
        }
      }).catch(err => {
        locStatus.textContent = t('Error: {message}').replace('{message}', err.message);
        locStatus.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
      });
    });
  }

  document.querySelectorAll('button[data-loc-delete-id]').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = parseInt(btn.dataset.locDeleteId, 10);
      if (!confirm(t('Delete this location and all its snapshots?'))) return;
      globalFetch('/account/locations/' + id + '/delete', {
        method: 'POST',
        headers: { 'X-CSRF-Token': getCsrfToken() },
      }).then(data => {
        if (data && data.success) {
          const row = document.querySelector(`tr[data-loc-id="${id}"]`);
          if (row) row.remove();
        } else {
          alert((data && data.error) || t('Delete failed.'));
        }
      }).catch(err => alert(t('Error: {message}').replace('{message}', err.message)));
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
          alert((data && data.error) || t('Update failed.'));
        }
      }).catch(err => alert(t('Error: {message}').replace('{message}', err.message)));
    });
  });

  // ── Delete account form ─────────────────────────────────────────────
  const deleteForm = document.getElementById('delete-form');
  const deleteStatus = document.getElementById('delete-status');
  if (deleteForm && deleteStatus) {
    deleteForm.addEventListener('submit', (e) => {
      e.preventDefault();
      if (!confirm(t('This will permanently delete your account and API key. Continue?'))) {
        return;
      }
      const fd = new FormData(deleteForm);
      const body = Object.fromEntries(fd.entries());
      deleteStatus.textContent = t('Deleting…');
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
          const err = (data && data.error) || t('Delete failed.');
          deleteStatus.textContent = err;
          deleteStatus.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
        }
      }).catch(err => {
        deleteStatus.textContent = t('Error: {message}').replace('{message}', err.message);
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
    statusEl.textContent = t('Saving…');
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
        const err = (data && data.error) || t('Failed.');
        statusEl.textContent = err;
        statusEl.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
      }
    }).catch(err => {
      statusEl.textContent = t('Error: {message}').replace('{message}', err.message);
      statusEl.className = 'text-sm mt-2 text-red-600 dark:text-red-400';
    });
  });
}

function revokeKey(keyId) {
  if (!confirm(t('Revoke this API key? Any client using it will get 403.'))) return;
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
          cells[4].innerHTML = `<span class="text-red-600 dark:text-red-400">${t('revoked')}</span>`;
        }
        const btn = row.querySelector('button[data-revoke-id]');
        if (btn) btn.remove();
      }
    } else {
      alert((data && data.error) || t('Revoke failed.'));
    }
  }).catch(err => alert(t('Error: {message}').replace('{message}', err.message)));
}

function appendKeyRow(data) {
  const tbody = document.getElementById('api-keys-tbody');
  if (!tbody) return;
  const tr = document.createElement('tr');
  tr.dataset.keyId = data.id;
  tr.className = 'border-t border-gray-200 dark:border-gray-700';
  // PR #47: prefer the server-issued `key_prefix` (sha-aware, always
  // first8…last4 of the original token). Fall back to client-side
  // slicing of the raw key for older API responses without the field.
  const masked = data.key_prefix || (data.key ? (data.key.slice(0, 8) + '…' + data.key.slice(-4)) : '—');
  // textContent on every cell — never innerHTML — defends against XSS in the
  // user-chosen `name` field.
  const tdName = document.createElement('td'); tdName.className = 'py-2 pr-2 font-medium'; tdName.textContent = data.name; tr.appendChild(tdName);
  const tdKey  = document.createElement('td'); tdKey.className  = 'py-2 pr-2 font-mono text-xs'; tdKey.textContent = masked; tr.appendChild(tdKey);
  const tdC    = document.createElement('td'); tdC.className    = 'py-2 pr-2 text-gray-500 dark:text-gray-400'; tdC.textContent = data.created_at.slice(0, 10); tr.appendChild(tdC);
  const tdL    = document.createElement('td'); tdL.className    = 'py-2 pr-2 text-gray-500 dark:text-gray-400'; tdL.textContent = t('never'); tr.appendChild(tdL);
  const tdS    = document.createElement('td'); tdS.className    = 'py-2 pr-2'; tdS.innerHTML = `<span class="text-green-600 dark:text-green-400">${t('active')}</span>`; tr.appendChild(tdS);
  const tdA    = document.createElement('td'); tdA.className    = 'py-2 pr-2 text-right';
  const btn = document.createElement('button');
  btn.dataset.revokeId = data.id;
  btn.className = 'text-red-600 hover:underline text-xs';
  btn.textContent = t('Revoke');
  btn.addEventListener('click', () => revokeKey(data.id));
  tdA.appendChild(btn);
  tr.appendChild(tdA);
  tbody.appendChild(tr);
}

function initAccountTabs() {
  const tabs = Array.from(document.querySelectorAll('.account-nav-link[data-account-tab]'));
  const panels = Array.from(document.querySelectorAll('[data-account-panel]'));
  if (!tabs.length || !panels.length) return;

  const panelName = (p) => p.dataset.accountPanel;
  const known = new Set(panels.map(panelName));

  const sectionToPanel = new Map();
  panels.forEach(p => {
    sectionToPanel.set(panelName(p), panelName(p));
    p.querySelectorAll('.account-section').forEach(sec => {
      if (sec.id) sectionToPanel.set(sec.id, panelName(p));
    });
  });

  const panelForHash = (hash) => {
    const id = (hash || '').replace(/^#/, '');
    return sectionToPanel.has(id) ? sectionToPanel.get(id) : null;
  };

  const activate = (name) => {
    if (!known.has(name)) return;
    panels.forEach(p => { p.hidden = panelName(p) !== name; });
    tabs.forEach(tab => {
      const on = tab.dataset.accountTab === name;
      tab.classList.toggle('is-active', on);
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
      tab.tabIndex = on ? 0 : -1;
    });
  };

  tabs.forEach((tab, i) => {
    tab.addEventListener('click', (e) => {
      e.preventDefault();
      activate(tab.dataset.accountTab);
      if (history.replaceState) history.replaceState(null, '', tab.getAttribute('href'));
    });
    tab.addEventListener('keydown', (e) => {
      let next = null;
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = tabs[(i + 1) % tabs.length];
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = tabs[(i - 1 + tabs.length) % tabs.length];
      else if (e.key === 'Home') next = tabs[0];
      else if (e.key === 'End') next = tabs[tabs.length - 1];
      if (!next) return;
      e.preventDefault();
      activate(next.dataset.accountTab);
      next.focus();
    });
  });

  document.querySelectorAll('a[href^="#"]:not([data-account-tab])').forEach(a => {
    const name = panelForHash(a.getAttribute('href'));
    if (!name) return;
    a.addEventListener('click', (e) => {
      e.preventDefault();
      activate(name);
      if (history.replaceState) history.replaceState(null, '', a.getAttribute('href'));
    });
  });

  activate(panelForHash(window.location.hash) || tabs[0].dataset.accountTab);
}
