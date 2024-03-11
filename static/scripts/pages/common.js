// base.html

document.addEventListener('DOMContentLoaded', function() {
  initializeModalToggle();
  initializeFormSubmissions();
  adjustFooterPosition();
  initializeThemeToggle();
  conditionalCheckLoginState();
  initializeScrollToTop();
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
  const storedTheme = localStorage.getItem('theme');
  const prefersDarkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const isDarkModePreferred = storedTheme === 'dark' || (!storedTheme && prefersDarkMode);

  document.documentElement.classList.toggle('dark', isDarkModePreferred);

  const btnThemeToggler = document.getElementById('themeToggle');
  if (btnThemeToggler) {
      btnThemeToggler.textContent = isDarkModePreferred ? 'Light Mode' : 'Dark Mode';

      btnThemeToggler.addEventListener('click', () => {
          const isDarkModeNow = document.documentElement.classList.toggle('dark');
          localStorage.setItem('theme', isDarkModeNow ? 'dark' : 'light');
          btnThemeToggler.textContent = isDarkModeNow ? 'Light Mode' : 'Dark Mode';

          // Custom event indicating the theme has changed
          window.dispatchEvent(new CustomEvent('themeChanged', { detail: { isDarkMode: isDarkModeNow } }));
      });
  }
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

function submitForm(url, formData) {
  fetch(url, {
      method: 'POST',
      body: formData,
  })
  .then(response => response.json())
  .then(data => {
      if (data.success) {
          alert('Registration successful!');
          // window.location.href = '/path';
          resetUIAndListeners();
          document.getElementById(registrationModal).classList.toggle('hidden')
          if (url === '/login') {
              localStorage.setItem('loggedIn', 'true');
              checkLoginStateAndUpdateUI();
          }
          
      } else {
          alert('Registration failed: ' + data.message);
      }
  })
  .catch(error => {
      console.error('Error:', error);
      alert('An error occurred during registration. Please try again.');
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
      alert(data.message);
      if (data.success) {
          clearLoginForm();
          if (url === '/login') {
              localStorage.setItem('loggedIn', 'true');
              checkLoginStateAndUpdateUI();
          }
      }
  })
  .catch(error => {
      console.error('Error:', error);
      alert('An error occurred. Please try again.');
  });
}

function logoutUser() {
  fetch('/logout', { method: 'POST' })
  .then(response => response.json())
  .then(data => {
      if (data.success) {
          localStorage.removeItem('loggedIn');
          resetUIAndListeners();
          clearSensitiveSessionData();
          clearLoginForm();
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
  document.getElementById('email').value = '';
  document.getElementById('password').value = '';
  document.getElementById('confirmpassword').value = '';  
}

function debugSession() {
  fetch('/debug_session')
  .then(response => response.json())
  .then(data => {
      console.log('Debug Session:', data);
  })
  .catch(error => console.error('Error debugging session:', error));
}

