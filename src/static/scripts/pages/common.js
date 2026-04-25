// base.html
document.addEventListener('DOMContentLoaded', function() {
  executeCurrentPageAction();
  initializeModalToggle();
  initializeFormSubmissions();
  adjustFooterPosition();
  initializeThemeToggle();
  conditionalCheckLoginState();
  initializeScrollToTop();
  initializePasswordValidation();
  initializeSloganRotate();
  initializeLogoutButton();
  initializePasswordToggles();
});

window.addEventListener('resize', adjustFooterPosition);

function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute('content') : '';
}
window.getCsrfToken = getCsrfToken;

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

function initializeLogoutButton() {
  const btn = document.getElementById('logoutButton');
  if (btn) btn.addEventListener('click', logoutUser);
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
    const themeIcon = document.createElement('img');
    
    const updateThemeIcon = (isDarkMode) => {
        themeIcon.src = isDarkMode ? 'static/images/sunrise.svg' : 'static/images/sunset.svg';
        themeIcon.style.filter = isDarkMode ? 'invert(100%)' : 'none';
        if (!btnThemeToggler.contains(themeIcon)) {
            btnThemeToggler.appendChild(themeIcon);
        }
    };

    const storedTheme = localStorage.getItem('theme');
    const prefersDarkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const isDarkModePreferred = storedTheme === 'dark' || (!storedTheme && prefersDarkMode);

    document.documentElement.classList.toggle('dark', isDarkModePreferred);
    updateThemeIcon(isDarkModePreferred);

    btnThemeToggler.addEventListener('click', () => {
        const isDarkModeNow = document.documentElement.classList.toggle('dark');
        localStorage.setItem('theme', isDarkModeNow ? 'dark' : 'light');
        updateThemeIcon(isDarkModeNow);
        window.dispatchEvent(new CustomEvent('themeChanged', { detail: { isDarkMode: isDarkModeNow } }));
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
  document.getElementById('registrationForm').addEventListener('submit', handleRegistrationSubmit);
  document.getElementById('signInForm').addEventListener('submit', handleSignInSubmit);
}

document.addEventListener('DOMContentLoaded', () => {
  const registrationForm = document.getElementById('registrationForm');

  if (registrationForm) {
      registrationForm.addEventListener('submit', handleRegistrationSubmit);
  }
});

function handleRegistrationSubmit(e) {
  e.preventDefault(); // Prevent default form submission

  const formData = new FormData(e.target);
  const email = formData.get('email');
  const password = formData.get('password');
  const confirmPassword = formData.get('confirm_password');

  resetErrorMessages();

  // validations
  const isEmailValid = validateField(email, 'emailError', 'Please enter a valid email address.', validateEmail);
  const isPasswordValid = validateField(password, 'passwordError', 
      'Password must be at least 8 characters long, include at least one number, one uppercase letter, and one special character.', validatePassword);
  const doPasswordsMatch = validateFieldMatch(password, confirmPassword, 'confirmPasswordError', 'Passwords do not match.');

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

  // Helper fuunction to toggle password visibility
  function togglePassword(show) {
      if (show) {
          passwordInput.type = 'text';
          toggleButton.textContent = 'Hide';
          if (confirmPasswordInput) confirmPasswordInput.type = 'text';
      } else {
          passwordInput.type = 'password';
          toggleButton.textContent = 'Show';
          if (confirmPasswordInput) confirmPasswordInput.type = 'password';
      }
  }

  // Mouse and touch event listeners
  toggleButton.addEventListener('mousedown', () => togglePassword(true));
  toggleButton.addEventListener('mouseup', () => togglePassword(false));
  toggleButton.addEventListener('mouseleave', () => togglePassword(false));

  // Touch events for mobile devices
  toggleButton.addEventListener('touchstart', () => togglePassword(true));
  toggleButton.addEventListener('touchend', () => togglePassword(false));
}

function handleSignInSubmit(e) {
  e.preventDefault();
  const formData = new FormData(e.target);
  submitForm('/login', formData);
}

function submitForm(url, formData) {
  globalFetch(url, { method: 'POST', body: formData })
  .then(data => {

      if (data.success) {
          clearLoginForm();
          adjustUIForLoggedOutState();
          if (url === '/login') {
              localStorage.setItem('loggedIn', 'true');
              checkLoginStateAndUpdateUI();
              executeCurrentPageAction();
              window.dispatchEvent(new CustomEvent('userLoggedIn'));
              showToast('Logged in', 'success');
          }
          if (url === '/register') {
            showToast('User registered', 'success');
            resetPasswordCriteriaIndicators();
          }
      } else {
        if (url === '/login')
          showToast(data.errorMessage || 'Login failed. Wrong email or password. Please try again.', 'error');
      }
  })
  .catch(error => {
      console.error('Error:', error);
      showToast('An error occurred. Please try again.', 'error');
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
      if (data.logged_in) {
        safelyUpdateDisplay('authModal', 'none');
        safelyUpdateDisplay('signInBtn', 'none');
        safelyUpdateDisplay('registerBtn', 'none');
        safelyUpdateDisplay('accountLink', 'inline-flex');
        safelyUpdateDisplay('logoutButton', 'block');
      } else {
        safelyUpdateDisplay('authModal', 'none');
        safelyUpdateDisplay('signInBtn', 'block');
        safelyUpdateDisplay('registerBtn', 'block');
        safelyUpdateDisplay('accountLink', 'none');
        safelyUpdateDisplay('logoutButton', 'none');
      }
    })
    .catch(error => console.error('Error checking login state:', error));
}

function conditionalCheckLoginState() {
  const mightBeLoggedIn = localStorage.getItem('loggedIn') === 'true';

  if (mightBeLoggedIn) {
    checkLoginStateAndUpdateUI();
  } else {
    adjustUIForLoggedOutState();
  }
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
  const el = document.querySelector('.slogan-rotate');
  if (!el) return;

  const lines = el.dataset.lines.split('|');
  if (lines.length < 2) return;

  // Measure tallest line and lock height so layout never shifts
  let maxH = 0;
  const original = el.textContent;
  lines.forEach(function(line) {
      el.textContent = line;
      maxH = Math.max(maxH, el.offsetHeight);
  });
  el.textContent = original;
  el.style.minHeight = maxH + 'px';

  let idx = 0;

  setInterval(function() {
      el.classList.add('fade-out');
      setTimeout(function() {
          idx = (idx + 1) % lines.length;
          el.textContent = lines[idx];
          el.classList.remove('fade-out');
      }, 500);
  }, 3500);
}

