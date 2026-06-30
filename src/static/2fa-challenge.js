(function () {
  const f = document.getElementById('f');
  const b = document.getElementById('b');
  const e = document.getElementById('e');
  const csrfToken = f.dataset.csrf || '';
  f.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    e.textContent = '';
    b.disabled = true;
    b.textContent = 'Checking...';
    const code = f.code.value.trim();
    try {
      const r = await fetch('/login/totp', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
        body: JSON.stringify({ code }),
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok && j.success) { window.location = '/account'; return; }
      e.textContent = j.error || j.message || 'Wrong code, try again.';
    } catch (err) {
      e.textContent = 'Network error - try again.';
    }
    b.disabled = false;
    b.textContent = 'Verify and continue';
  });
})();
