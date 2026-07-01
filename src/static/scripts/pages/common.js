// base.html
document.addEventListener('DOMContentLoaded', function() {
  executeCurrentPageAction();
  initializeModalToggle();
  initializeFormSubmissions();
  adjustFooterPosition();
  initializeThemeToggle();
  initializeNavMenu();
  conditionalCheckLoginState();
  initializeScrollToTop();
  initializePasswordValidation();
  initializeSloganRotate();
  initializeLogoutButton();
  initializePasswordToggles();
  showOAuthErrorIfPresent();
  fireAnalyticsPulse();
  initializeAutoSubmitSelects();
});

// One-shot fire-and-forget GET to /api/v1/_pulse. The server uses the
// presence of this hit as a "this client executes JS" signal in the
// composite bot score. No payload, no response handling — 204 by
// design. Wrapped in try so a
// network failure here never breaks page boot.
function fireAnalyticsPulse() {
  try {
    if (window.__ssAnalyticsPulseFired) return;
    window.__ssAnalyticsPulseFired = true;
    fetch('/api/v1/_pulse', {
      method: 'GET',
      credentials: 'same-origin',
      cache: 'no-store',
      keepalive: true,
    }).catch(function() { /* swallow */ });
  } catch (_) { /* old browser without fetch — that's fine, bot score handles it */ }
}

// OAuth callbacks land on the home page with `?oauth_error=<code>` when
// the server refused the sign-in (account-takeover guard, missing email,
// expired 2FA session, etc.). Before this, the redirect happened
// silently — user saw "click Google → land on home logged-out", which
// looks like a broken success. Now we surface a human-readable toast
// and strip the param so refresh doesn't replay the message.
function showOAuthErrorIfPresent() {
  let params;
  try { params = new URLSearchParams(window.location.search); }
  catch (_) { return; }
  const code = params.get('oauth_error');
  if (!code) return;

  const messages = {
    no_email:
      t('Your sign-in provider didn\'t share an email address with us. Please use a different sign-in method.'),
    no_pending_2fa:
      t('Your two-factor session expired. Please sign in again.'),
    state_mismatch:
      t('Sign-in could not be verified. Please try again from the home page.'),
    provider_rejected:
      t('The sign-in provider rejected the request (most likely a missing permission on the app side). Please try a different method, or let the operator know.'),
    token_exchange:
      t('Sign-in could not be completed (token exchange failed). Please try again — if it keeps failing, use a different provider.'),
    db:
      t('Sign-in completed but we couldn\'t save your session. Please try again.'),
    provider_not_configured:
      t('This sign-in method isn\'t enabled. Please use a different one.'),
    provider_error:
      t('Sign-in failed at the provider. Please try again or use another method.'),
  };
  const msg = messages[code]
    || t('Sign-in failed. Please try again or use another method.');
  if (typeof showToast === 'function') {
    showToast(msg, 'error');
  } else {
    // Fallback if toast helper isn't loaded for some reason.
    console.warn('[oauth]', msg);
  }
  // Clean the URL so a refresh / share doesn't re-trigger the message.
  params.delete('oauth_error');
  const qs = params.toString();
  const cleanUrl = window.location.pathname + (qs ? '?' + qs : '') + window.location.hash;
  try { window.history.replaceState({}, document.title, cleanUrl); }
  catch (_) { /* old browsers — leave it */ }
}

window.addEventListener('resize', adjustFooterPosition);

window.SS_I18N = (function() {
  try {
    const el = document.getElementById('ss-i18n');
    const parsed = el ? JSON.parse(el.textContent) : null;
    if (parsed && typeof parsed === 'object') {
      return { lang: parsed.lang || 'en', strings: parsed.strings || {} };
    }
  } catch (_) { /* fall through to English */ }
  return { lang: 'en', strings: {} };
})();

function t(s) {
  const strings = window.SS_I18N && window.SS_I18N.strings;
  return (strings && strings[s]) || s;
}
window.t = t;

function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute('content') : '';
}
window.getCsrfToken = getCsrfToken;

// Apply a server-rotated CSRF token after session.clear() boundaries
// (login, logout, password change, totp setup/disable) so subsequent
// CSRF-protected POSTs from the same page don't 403 against the new
// session token.
function applyRotatedCsrfToken(token) {
  if (!token) return;
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta) meta.setAttribute('content', token);
  document.querySelectorAll('input[name="_csrf_token"]').forEach(i => {
    i.value = token;
  });
}
window.applyRotatedCsrfToken = applyRotatedCsrfToken;

function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/\//g, '&#x2F;');
}
window.escapeHtml = escapeHtml;

// CSP-safe replacement for inline `onchange="this.form.submit()"` (blocked by
// script-src 'self'): auto-submit any <select data-submit-on-change> on change.
function initializeAutoSubmitSelects() {
  document.querySelectorAll('select[data-submit-on-change]').forEach(function (sel) {
    sel.addEventListener('change', function () {
      if (sel.form) sel.form.submit();
    });
  });
}

function initializeLogoutButton() {
  document.querySelectorAll('#logoutButton, #logoutButtonMobile').forEach(btn => {
    btn.addEventListener('click', logoutUser);
  });
}

function initializePasswordToggles() {
  document.querySelectorAll('[data-toggle-password]').forEach(btn => {
    const passwordId = btn.getAttribute('data-toggle-password');
    const confirmId = btn.getAttribute('data-toggle-confirm') || null;
    passwordVisibilityToggle(passwordId, confirmId, btn.id);
  });
}

function globalFetch(url, options) {
  return fetch(url, options)
  .then(response => {
      if (!response.ok) {
          handleErrors(response);
          throw new Error(`HTTP error, status = ${response.status}`);
      }
      if (response.headers.get("Content-Type")?.includes("application/json")) {
          return response.json(); // Parse JSON only if the content type is correct
      } else {
          return response.text().then(text => {
              throw new Error('Expected JSON but received text');
          });
      }
  })
  .catch(error => {
      console.error('There was a problem with the fetch operation:', error.message);
      throw error;
  });
}

function handleErrors(response) {
    if (response.status === 429) {
        localStorage.setItem('rateLimitedUntil', Date.now() + 60000);
        showRateLimitModal();
        document.getElementById('rateLimitModal').classList.remove('hidden');
        setTimeout(() => {
            document.getElementById('rateLimitModal').classList.add('hidden');
        }, 60000); 
    }
    // more error handling to be added
}

function showRateLimitModal() {
  const modal = document.getElementById('rateLimitModal');
  const countdownElement = document.getElementById('countdown');

  // Calculate the remaining time based on what's stored or default to 60 seconds
  let endTime = parseInt(localStorage.getItem('rateLimitedUntil'), 10);
  let timeLeft = endTime ? Math.round((endTime - Date.now()) / 1000) : 60; // Fallback to 60 seconds if endTime is not valid

  // Check for NaN or non-positive values and adjust accordingly
  if (isNaN(timeLeft) || timeLeft <= 0) {
      console.error('Invalid time left calculated:', timeLeft);
      timeLeft = 60; // Reset to default 60 seconds if calculated time is invalid
      localStorage.setItem('rateLimitedUntil', Date.now() + timeLeft * 1000); // Reset endTime in storage
  }

  countdownElement.textContent = timeLeft;
  modal.classList.remove('hidden');

  const timer = setInterval(() => {
      timeLeft = Math.max(0, Math.round((endTime - Date.now()) / 1000)); // Recalculate timeLeft to avoid drift
      countdownElement.textContent = timeLeft;

      if (timeLeft <= 0) {
          clearInterval(timer);
          modal.classList.add('hidden');
          localStorage.removeItem('rateLimitedUntil'); // Clean up
      }
  }, 1000);
}

document.addEventListener('DOMContentLoaded', () => {
  let endTime = parseInt(localStorage.getItem('rateLimitedUntil'), 10);
  let timeLeft = endTime ? Math.max(0, Math.round((endTime - Date.now()) / 1000)) : 0;

  if (timeLeft > 0) {
      showRateLimitModal(timeLeft); // Display the modal with the remaining time
  }
});

function adjustFooterPosition() {
    const footer = document.querySelector('footer'); 
    const bodyHeight = document.body.offsetHeight;
    const viewportHeight = window.innerHeight;

   if (bodyHeight <= viewportHeight) {
       footer.classList.add('mt-auto');
   } else {
       footer.classList.remove('mt-auto');
   }
}

function initializeThemeToggle() {
    const btnThemeToggler = document.getElementById('themeToggle');
    if (!btnThemeToggler) return;

    // The icon is two inline SVGs in the button (sun/moon) toggled by the
    // `dark` class in CSS — no <img> swap here (that broke in Safari).
    // theme-init.js already set the `dark` class before first paint; this
    // just keeps it in sync and persists the user's choice.
    const storedTheme = localStorage.getItem('theme');
    const prefersDarkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const isDarkModePreferred = storedTheme === 'dark' || (!storedTheme && prefersDarkMode);
    document.documentElement.classList.toggle('dark', isDarkModePreferred);

    btnThemeToggler.addEventListener('click', () => {
        const isDarkModeNow = document.documentElement.classList.toggle('dark');
        localStorage.setItem('theme', isDarkModeNow ? 'dark' : 'light');
        window.dispatchEvent(new CustomEvent('themeChanged', { detail: { isDarkMode: isDarkModeNow } }));
    });
}

function initializeNavMenu() {
    const toggle = document.getElementById('navMenuToggle');
    const menu = document.getElementById('mobileNav');
    if (!toggle || !menu) return;

    const closeMenu = () => {
        menu.classList.add('hidden');
        toggle.setAttribute('aria-expanded', 'false');
    };

    toggle.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = !menu.classList.toggle('hidden');
        toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    });

    menu.querySelectorAll('a, button').forEach((el) => {
        el.addEventListener('click', closeMenu);
    });

    document.addEventListener('click', (e) => {
        if (menu.classList.contains('hidden')) return;
        if (!menu.contains(e.target) && !toggle.contains(e.target)) closeMenu();
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !menu.classList.contains('hidden')) {
            closeMenu();
            toggle.focus();
        }
    });
}

// Scroll up
function initializeScrollToTop() {
  const backToTopBtn = document.getElementById('backToTopBtn');

  if (backToTopBtn) {
    window.addEventListener('scroll', () => {
        const scrollThreshold = window.innerWidth < 768 ? 300 : 200;
        backToTopBtn.classList.toggle('hidden', window.scrollY <= scrollThreshold);
    });

    backToTopBtn.addEventListener('click', () => {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }
}

// PR #48.8: unified auth modal. Old toggleRegistrationModal /
// toggleSignInModal kept as thin shims so any other code that called
// them still works — they now open #authModal and switch to the right
// tab. The "modal" identity moved from per-form to per-tab-panel.
function _setAuthTab(which) {
  const signinPanel = document.getElementById('signInModal');
  const registerPanel = document.getElementById('registrationModal');
  const signinTab = document.getElementById('authTabSignin');
  const registerTab = document.getElementById('authTabRegister');
  if (!signinPanel || !registerPanel) return;

  const activeClasses = ['bg-white', 'dark:bg-gray-700', 'text-gray-900', 'dark:text-white', 'shadow-sm'];
  const inactiveClasses = ['text-gray-600', 'dark:text-gray-300', 'hover:text-gray-900', 'dark:hover:text-white'];

  const setActive = (el) => {
    if (!el) return;
    inactiveClasses.forEach(c => el.classList.remove(c));
    activeClasses.forEach(c => el.classList.add(c));
  };
  const setInactive = (el) => {
    if (!el) return;
    activeClasses.forEach(c => el.classList.remove(c));
    inactiveClasses.forEach(c => el.classList.add(c));
  };

  if (which === 'register') {
    signinPanel.classList.add('hidden');
    registerPanel.classList.remove('hidden');
    setInactive(signinTab);
    setActive(registerTab);
  } else {
    registerPanel.classList.add('hidden');
    signinPanel.classList.remove('hidden');
    setInactive(registerTab);
    setActive(signinTab);
  }
}

function _openAuthModal(tab) {
  const m = document.getElementById('authModal');
  if (!m) return;
  _setAuthTab(tab || 'signin');
  // Defensive: clear any inline display:none that an earlier code path
  // (e.g. logout flow) may have stamped on the modal — without this,
  // class-based show via removing `hidden` would lose to the inline
  // style and the modal would stay invisible.
  m.style.display = '';
  m.classList.remove('hidden');
}

function toggleRegistrationModal() {
  _openAuthModal('register');
}

function toggleSignInModal() {
  _openAuthModal('signin');
}

function closeModal(event) {
  event.target.closest('.modal').classList.add('hidden');
}

function backgroundClickToClose(event, modal) {
  if (event.target === modal) modal.classList.add('hidden');
}

function initializeModalToggle() {
  const registerBtn = document.getElementById('registerBtn');
  const signInBtn = document.getElementById('signInBtn');
  const authModal = document.getElementById('authModal');

  if (registerBtn) registerBtn.addEventListener('click', () => _openAuthModal('register'));
  if (signInBtn) signInBtn.addEventListener('click', () => _openAuthModal('signin'));

  const signInBtnMobile = document.getElementById('signInBtnMobile');
  if (signInBtnMobile) signInBtnMobile.addEventListener('click', () => _openAuthModal('signin'));

  // Tab switcher inside the modal.
  document.querySelectorAll('.auth-tab').forEach(btn => {
    btn.addEventListener('click', () => _setAuthTab(btn.dataset.tab));
  });

  document.querySelectorAll('.close-modal').forEach(button => {
      button.addEventListener('click', closeModal);
  });

  if (authModal) {
    authModal.addEventListener('click', (event) => backgroundClickToClose(event, authModal));
  }

  // Close modal with ESC key
  document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && authModal && !authModal.classList.contains('hidden')) {
          authModal.classList.add('hidden');
      }
  });
}

function initializeFormSubmissions() {
  // Idempotent: forms live in base.html as persistent modal elements (not
  // re-created on logout), so we must guard against the bootstrap path
  // calling us a second time (e.g. via resetUIAndListeners after logout).
  // Without this guard, every logout/login cycle stacked another listener
  // and the success toast fired N times.
  const signIn = document.getElementById('signInForm');
  const register = document.getElementById('registrationForm');
  if (signIn && !signIn.dataset.submitBound) {
      signIn.addEventListener('submit', handleSignInSubmit);
      signIn.dataset.submitBound = '1';
  }
  if (register && !register.dataset.submitBound) {
      register.addEventListener('submit', handleRegistrationSubmit);
      register.dataset.submitBound = '1';
  }
}

function handleRegistrationSubmit(e) {
  e.preventDefault(); // Prevent default form submission

  const formData = new FormData(e.target);
  const email = formData.get('email');
  const password = formData.get('password');
  const confirmPassword = formData.get('confirm_password');

  resetErrorMessages();

  // validations
  const isEmailValid = validateField(email, 'emailError', t('Please enter a valid email address.'), validateEmail);
  const isPasswordValid = validateField(password, 'passwordError',
      t('Password must be at least 8 characters long, include at least one number, one uppercase letter, and one special character.'), validatePassword);
  const doPasswordsMatch = validateFieldMatch(password, confirmPassword, 'confirmPasswordError', t('Passwords do not match.'));

  if (isEmailValid && isPasswordValid && doPasswordsMatch) {
      submitForm('/register', formData); 
  }
}

function validateField(value, errorElementId, errorMessage, validationFunction) {
  if (!validationFunction(value)) {
      showError(errorElementId, errorMessage);
      return false;
  }
  return true;
}

function validateFieldMatch(value1, value2, errorElementId, errorMessage) {
  if (value1 !== value2) {
      showError(errorElementId, errorMessage);
      return false;
  }
  return true;
}

function showError(elementId, message) {
  const errorElement = document.getElementById(elementId);
  errorElement.textContent = message;
  errorElement.classList.remove('hidden'); 
}

function resetErrorMessages() {
  document.querySelectorAll('.error-message').forEach((errorElement) => {
      errorElement.classList.add('hidden');
  });
}

// validation functions
function validateEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

function validatePassword(password) {
  return /^(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*\W).{8,}$/.test(password);
}

function initializePasswordValidation() {
  const passwordInput = document.getElementById('registrationPassword');
  const passwordConfirmInput = document.getElementById('confirmRegistrationPassword');

  function updatePasswordRequirements() {
      const password = passwordInput.value;
      const confirmPassword = passwordConfirmInput.value;

      const requirements = {
          minLength: password.length >= 8,
          number: /\d/.test(password),
          uppercase: /[A-Z]/.test(password),
          lowercase: /[a-z]/.test(password),
          specialChar: /[!@#$%^&*(),.?":{}|<>]/.test(password),
          passwordMatch: password.length >= 8 && password === confirmPassword
      };

      document.querySelectorAll('.password-requirement').forEach(req => {
          const criteria = req.getAttribute('data-criteria');
          const isMet = requirements[criteria];

          req.classList.toggle('text-red-500', !isMet);
          req.classList.toggle('dark:text-red-400', !isMet);
          req.classList.toggle('text-green-500', isMet);
          req.classList.toggle('dark:text-green-400', isMet);

          const indicator = req.querySelector('.indicator');
          if (indicator) {
              indicator.textContent = isMet ? '✓' : 'X';
          } else {
              const newIndicator = document.createElement('span');
              newIndicator.className = 'indicator';
              newIndicator.textContent = isMet ? '✓' : 'X';
              req.prepend(newIndicator);
          }
      });
  }

  if (passwordInput && passwordConfirmInput) {
      [passwordInput, passwordConfirmInput].forEach(input => {
          input.addEventListener('input', updatePasswordRequirements);
      });
  }
}

function resetPasswordCriteriaIndicators() {
  document.querySelectorAll('.password-requirement').forEach(req => {
      req.classList.add('text-red-500', 'dark:text-red-400');
      req.classList.remove('text-green-500', 'dark:text-green-400');
      req.textContent = req.textContent.replace('✓', 'X');
  });
}

function passwordVisibilityToggle(passwordInputId, confirmPasswordInputId, toggleButtonId) {
  let passwordInput = document.getElementById(passwordInputId);
  let confirmPasswordInput = confirmPasswordInputId ? document.getElementById(confirmPasswordInputId) : null;
  let toggleButton = document.getElementById(toggleButtonId);

  toggleButton.setAttribute('type', 'button');
  toggleButton.textContent = t('Hold to show');
  toggleButton.setAttribute('title', t('Press and hold to reveal the password'));

  function togglePassword(show) {
      const type = show ? 'text' : 'password';
      passwordInput.type = type;
      if (confirmPasswordInput) confirmPasswordInput.type = type;
      toggleButton.textContent = show ? t('Holding') : t('Hold to show');
      toggleButton.setAttribute('aria-pressed', show ? 'true' : 'false');
  }

  toggleButton.addEventListener('mousedown', () => togglePassword(true));
  toggleButton.addEventListener('mouseup', () => togglePassword(false));
  toggleButton.addEventListener('mouseleave', () => togglePassword(false));

  toggleButton.addEventListener('touchstart', (e) => { e.preventDefault(); togglePassword(true); });
  toggleButton.addEventListener('touchend', () => togglePassword(false));
  toggleButton.addEventListener('touchcancel', () => togglePassword(false));
}

function handleSignInSubmit(e) {
  e.preventDefault();
  resetErrorMessages();
  const formData = new FormData(e.target);
  submitForm('/login', formData);
}

function submitForm(url, formData) {
  globalFetch(url, { method: 'POST', body: formData })
  .then(data => {

      if (data.success) {
          applyRotatedCsrfToken(data.csrf_token);
          clearLoginForm();
          adjustUIForLoggedOutState();
          if (url === '/login') {
              localStorage.setItem('loggedIn', 'true');
              checkLoginStateAndUpdateUI();
              executeCurrentPageAction();
              window.dispatchEvent(new CustomEvent('userLoggedIn'));
              showToast(t('Logged in'), 'success');
          }
          if (url === '/register') {
            showToast(t('User registered'), 'success');
            resetPasswordCriteriaIndicators();
          }
      } else {
        if (url === '/login')
          showError('signInError', data.errorMessage || t('Login failed. Wrong email or password. Please try again.'));
      }
  })
  .catch(error => {
      console.error('Error:', error);
      showToast(t('An error occurred. Please try again.'), 'error');
  });
}

function logoutUser() {
  globalFetch('/logout', {
    method: 'POST',
    headers: { 'X-CSRF-Token': getCsrfToken() }
  })
  .then(data => {
      if (data.success) {
          localStorage.removeItem('loggedIn');
          clearLoginForm();
          resetUIAndListeners();
          clearSensitiveSessionData();
          window.dispatchEvent(new CustomEvent('userLoggedOut'));
          // Hard navigate to home with replace() so /account (or any other
          // authenticated page) does not stay in the Back-button history
          // showing its previously-rendered, now-stale HTML.
          window.location.replace('/');
      } else {
          console.error('Logout failed:', data.message);
      }
  })
  .catch(error => console.error('Error during logout:', error));
}

function safelyUpdateDisplay(elementId, displayStyle) {
  const element = document.getElementById(elementId);
  if (element) {
    element.style.display = displayStyle;
  }
}

function checkLoginStateAndUpdateUI() {
  globalFetch('/session_check')
    .then(data => {
      // Don't touch authModal here. Setting inline `style.display='none'`
      // on it pins it shut — _openAuthModal removes the `hidden` class
      // but the inline style wins (higher specificity). The modal's
      // baseline `hidden` class already keeps it closed; opening clears
      // the class and the modal renders. This was dormant until PR #303
      // started running this function on every page load (was guarded
      // behind localStorage.loggedIn before).
      if (data.logged_in) {
        safelyUpdateDisplay('signInBtn', 'none');
        safelyUpdateDisplay('registerBtn', 'none');
        safelyUpdateDisplay('accountLink', 'inline-flex');
        safelyUpdateDisplay('logoutButton', 'block');
        safelyUpdateDisplay('signInBtnMobile', 'none');
        safelyUpdateDisplay('accountLinkMobile', 'block');
        safelyUpdateDisplay('logoutButtonMobile', 'block');
      } else {
        safelyUpdateDisplay('signInBtn', 'block');
        safelyUpdateDisplay('registerBtn', 'block');
        safelyUpdateDisplay('accountLink', 'none');
        safelyUpdateDisplay('logoutButton', 'none');
        safelyUpdateDisplay('signInBtnMobile', 'block');
        safelyUpdateDisplay('accountLinkMobile', 'none');
        safelyUpdateDisplay('logoutButtonMobile', 'none');
      }
    })
    .catch(error => console.error('Error checking login state:', error));
}

function conditionalCheckLoginState() {
  // Always ask the server. The localStorage 'loggedIn' flag is set by
  // the AJAX login flow, but OAuth flows are full-page redirects with
  // zero JS in the loop — meaning a user who just signed in via Google
  // / GitHub would land on /account with the server holding a real
  // session yet the header still showing "Sign in". Cost is one tiny
  // /session_check request per page load (returns ~20 bytes); benefit
  // is the header always matches the actual session.
  //
  // Render the logged-out state immediately so the header doesn't
  // flicker through a half-second of "logged-in chrome" while the
  // request is in flight; checkLoginStateAndUpdateUI() patches it back
  // up if /session_check confirms a session.
  adjustUIForLoggedOutState();
  checkLoginStateAndUpdateUI();
}

function adjustUIForLoggedOutState() {
  const authModal = document.getElementById('authModal');
  if (authModal) {
      authModal.style.display = '';
      authModal.classList.add('hidden');
  }

  safelyUpdateDisplay('signInBtn', 'block');
  safelyUpdateDisplay('registerBtn', 'block');
  safelyUpdateDisplay('accountLink', 'none');
  safelyUpdateDisplay('logoutButton', 'none');
  safelyUpdateDisplay('signInBtnMobile', 'block');
  safelyUpdateDisplay('accountLinkMobile', 'none');
  safelyUpdateDisplay('logoutButtonMobile', 'none');
}

function resetUIAndListeners() {
  adjustUIForLoggedOutState(); 
  initializeModalToggle();
  initializeFormSubmissions();
}

function clearSensitiveSessionData() {
  sessionStorage.removeItem('userSessionInfo');
}

function clearLoginForm() {
  document.getElementById('registrationForm').reset();
  document.getElementById('signInForm').reset();
}

function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  const bgColorClass = type === 'success' ? 'bg-blue-500' : 'bg-red-500';
  toast.className = `${bgColorClass} text-white px-4 py-2 rounded shadow-lg mb-2 toast-transition`;
  toast.textContent = message;

  container.appendChild(toast); 

 
  setTimeout(() => {
    toast.classList.add('opacity-0');
    setTimeout(() => {
      container.removeChild(toast); 
    }, 1000);
  }, 2500);
}

const pageActions = {
  '/': () => {
      if (typeof window.updateDynamicContent === 'function') {
          window.updateDynamicContent();
      }
  },
  '/tips': () => {
      if (typeof window.loadTipsContent === 'function') {
          window.loadTipsContent();
      }
  },
};

function executeCurrentPageAction() {
  const path = window.location.pathname;
  const action = pageActions[path];

  if (action) {
      action();
  }
}


function initializeSloganRotate() {
  const el = document.querySelector('.tagline-text');
  if (!el) return;

  const lines = [];
  if (el.dataset.sloganTitle) lines.push(el.dataset.sloganTitle);
  if (el.dataset.sloganText) lines.push(el.dataset.sloganText);
  lines.push(
      t('Click anywhere on the map to find the nearest masts'),
      t('~22,000 base stations across Poland'),
      t('5G to GSM — Orange, Play, Plus & T-Mobile'),
      t('Live data from UKE, refreshed continuously'),
  );
  const dotsWrap = document.querySelector('.tagline-dots');

  // Measure tallest line and lock height so layout never shifts.
  let maxH = 0;
  lines.forEach(function(line) {
      el.textContent = line;
      maxH = Math.max(maxH, el.offsetHeight);
  });
  el.textContent = lines[0];
  el.style.minHeight = maxH + 'px';

  if (dotsWrap) {
      dotsWrap.innerHTML = '';
      lines.forEach(function(_, i) {
          const dot = document.createElement('span');
          dot.className = 'tagline-dot' + (i === 0 ? ' active' : '');
          dotsWrap.appendChild(dot);
      });
  }

  function setDot(i) {
      if (!dotsWrap) return;
      dotsWrap.querySelectorAll('.tagline-dot').forEach(function(d, j) {
          d.classList.toggle('active', j === i);
      });
  }

  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  let idx = 0;
  let timer = null;
  function tick() {
      el.classList.add('fade-out');
      setTimeout(function() {
          idx = (idx + 1) % lines.length;
          el.textContent = lines[idx];
          setDot(idx);
          el.classList.remove('fade-out');
      }, 350);
  }
  function start() { if (!timer) timer = setInterval(tick, 3800); }
  function stop() { if (timer) { clearInterval(timer); timer = null; } }

  start();
  document.addEventListener('visibilitychange', function() {
      if (document.hidden) stop(); else start();
  });
}

