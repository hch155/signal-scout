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

function initializeModalToggle() {
  const registerBtn = document.getElementById('registerBtn');
  const signInBtn = document.getElementById('signInBtn');
  const registrationModal = document.getElementById('registrationModal');
  const signInModal = document.getElementById('signInModal');

  registerBtn.addEventListener('click', () => registrationModal.classList.toggle('hidden'));
  signInBtn.addEventListener('click', () => signInModal.classList.toggle('hidden'));

  document.querySelectorAll('.close-modal').forEach(button => {
      button.addEventListener('click', () => button.closest('.modal').classList.add('hidden'));
  });

  [registrationModal, signInModal].forEach(modal => {
      modal.addEventListener('click', (event) => {
          if (event.target === modal) modal.classList.add('hidden');
      });
  });
}

function initializeFormSubmissions() {
  document.getElementById('registrationForm').addEventListener('submit', handleRegistrationSubmit);
  document.getElementById('signInForm').addEventListener('submit', handleSignInSubmit);
}

function handleRegistrationSubmit(e) {
  e.preventDefault(); // Prevent default form submission
  const formData = new FormData(e.target);
  const password = formData.get('password');
  const confirmPassword = formData.get('confirm_password');

  if (password !== confirmPassword) {
      alert('Passwords do not match.');
      return;
  }

  submitForm('/register', formData);
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
          checkLoginStateAndUpdateUI();
          if (url === '/login') {
              localStorage.setItem('loggedIn', 'true');
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
  document.getElementById('registrationModal').classList.add('hidden');
  document.getElementById('signInModal').classList.add('hidden');
  document.getElementById('signInBtn').style.display = 'block'; 
  document.getElementById('registerBtn').style.display = 'block'; 
  document.getElementById('logoutButton').style.display = 'none';
}

function resetUIAndListeners() {
  adjustUIForLoggedOutState(); 
  initializeModalToggle();
  initializeFormSubmissions();
}

function debugSession() {
  fetch('/debug_session')
  .then(response => response.json())
  .then(data => {
      console.log('Debug Session:', data);
  })
  .catch(error => console.error('Error debugging session:', error));
}

