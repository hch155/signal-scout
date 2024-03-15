// base.html

document.addEventListener('DOMContentLoaded', function() {
  initializeModalToggle();
  initializeFormSubmissions();
  adjustFooterPosition();
  initializeThemeToggle();
  conditionalCheckLoginState();
  initializeScrollToTop();
  initializePasswordValidation();
});

window.addEventListener('resize', adjustFooterPosition);

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
        backToTopBtn.classList.toggle('hidden', window.scrollY <= 200);
    });

    backToTopBtn.addEventListener('click', () => {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }
}

function toggleRegistrationModal() {
  document.getElementById('registrationModal').classList.toggle('hidden');
}

function toggleSignInModal() {
  document.getElementById('signInModal').classList.toggle('hidden');
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
  const registrationModal = document.getElementById('registrationModal');
  const signInModal = document.getElementById('signInModal');

  registerBtn.addEventListener('click', toggleRegistrationModal);
  signInBtn.addEventListener('click', toggleSignInModal);

  document.querySelectorAll('.close-modal').forEach(button => {
      button.addEventListener('click', closeModal);
  });

  [registrationModal, signInModal].forEach(modal => {
      modal.addEventListener('click', (event) => backgroundClickToClose(event, modal));
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
  const passwordInput = document.getElementById('password');
  const passwordConfirmInput = document.getElementById('confirmpassword');

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
          req.classList.toggle('text-green-500', isMet);

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
      req.classList.add('text-red-500');
      req.classList.remove('text-green-500');
      req.textContent = req.textContent.replace('✓', 'X');
  });
}

function submitForm(url, formData) {
  fetch(url, {
      method: 'POST',
      body: formData,
  })
  .then(response => response.json())
  .then(data => {
      if (data.success) {
          // window.location.href = '/path';
          resetUIAndListeners();
          showToast('Registration successful!', 'success');
          if (url === '/login') {
              localStorage.setItem('loggedIn', 'true');
              checkLoginStateAndUpdateUI();
          }
          
      } else {
        showToast('Registration failed: Email already in use.', 'error');
      }
  })
  .catch(error => {
      console.error('Error:', error);
      showToast('An error occurred during registration. Please try again.', 'error');
  });
}

function handleSignInSubmit(e) {
  e.preventDefault();
  const formData = new FormData(e.target);
  submitForm('/login', formData);
}

function submitForm(url, formData) {
  fetch(url, { method: 'POST', body: formData })
  .then(response => response.json())
  .then(data => {

      if (data.success) {
          clearLoginForm();
          adjustUIForLoggedOutState();
          if (url === '/login') {
              localStorage.setItem('loggedIn', 'true');
              checkLoginStateAndUpdateUI();
              updateDynamicContent();
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
  fetch('/logout', { method: 'POST' })
  .then(response => response.json())
  .then(data => {
      if (data.success) {
          localStorage.removeItem('loggedIn');
          clearLoginForm();
          resetUIAndListeners();
          clearSensitiveSessionData();
          updateDynamicContent();
          showToast('Logged out', 'success');
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
  fetch('/session_check')
    .then(response => response.json())
    .then(data => {
      if (data.logged_in) {
        safelyUpdateDisplay('registrationModal', 'none');
        safelyUpdateDisplay('signInModal', 'none');
        safelyUpdateDisplay('signInBtn', 'none');
        safelyUpdateDisplay('registerBtn', 'none');
        safelyUpdateDisplay('logoutButton', 'block');
      } else {
        safelyUpdateDisplay('registrationModal', 'none');
        safelyUpdateDisplay('signInModal', 'none');
        safelyUpdateDisplay('signInBtn', 'block');
        safelyUpdateDisplay('registerBtn', 'block');
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
  const registrationModal = document.getElementById('registrationModal');
  const signInModal = document.getElementById('signInModal');
  
  if (registrationModal) {
      registrationModal.style.display = '';
      registrationModal.classList.add('hidden');
  }
  if (signInModal) {
      signInModal.style.display = '';
      signInModal.classList.add('hidden');
  }

  safelyUpdateDisplay('signInBtn', 'block');
  safelyUpdateDisplay('registerBtn', 'block');
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

function debugSession() {
  fetch('/debug_session')
  .then(response => response.json())
  .then(data => {
      console.log('Debug Session:', data);
  })
  .catch(error => console.error('Error debugging session:', error));
}

