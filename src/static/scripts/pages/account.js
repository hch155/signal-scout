// /account page interactions: copy + regenerate key.
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
});
