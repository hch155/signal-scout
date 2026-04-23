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
