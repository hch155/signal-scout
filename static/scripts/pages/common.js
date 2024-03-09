// base.html

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

function logoutUser() {
  fetch('/logout', { method: 'POST' })
  .then(response => {
      if (response.ok) {
          alert('Logged out successfully.');
      } else {
          alert('Logout failed. Please try again.');
      }
  })
  .catch(error => {
      console.error('Error:', error);
      alert('An error occurred. Please try again.');
  });
}

document.addEventListener('DOMContentLoaded', function() {
    adjustFooterPosition();
});

window.addEventListener('resize', adjustFooterPosition);

document.addEventListener('DOMContentLoaded', () => {
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
});

// Scroll up
document.addEventListener('DOMContentLoaded', (event) => {
    const backToTopBtn = document.getElementById('backToTopBtn');
    window.addEventListener('scroll', () => {
        if (window.scrollY > 200) {
            backtoTopBtn.classList.remove('hidden');
        } else {
            backtoTopBtn.classList.add('hidden');
        }
    backtoTopBtn.addEventListener('click', () => {
        window.scrollTo({
            top: 0,
            behavior: 'smooth'
        });
    });
 });
});

document.addEventListener('DOMContentLoaded', () => {
    const registerBtn = document.getElementById('registerBtn');
    const signInBtn = document.getElementById('signInBtn');
    const registrationModal = document.getElementById('registrationModal');
    const signInModal = document.getElementById('signInModal');
  
    registerBtn.addEventListener('click', () => {
      registrationModal.classList.toggle('hidden');
    });
  
    signInBtn.addEventListener('click', () => {
      signInModal.classList.toggle('hidden');
    });
  
    document.querySelectorAll('.close-modal').forEach(button => {
      button.addEventListener('click', () => {
        const modalToClose = button.closest('.modal'); // common class for all modals
        if (modalToClose) {
          modalToClose.classList.add('hidden');
        }
      });
    });
  
    registrationModal.addEventListener('click', (event) => {
      if (event.target === registrationModal) {
        registrationModal.classList.add('hidden');
      }
    });
  
    signInModal.addEventListener('click', (event) => {
      if (event.target === signInModal) {
        signInModal.classList.add('hidden');
      }
    });
  });

  document.getElementById('registrationForm').addEventListener('submit', function(e) {
    e.preventDefault(); // Prevent default form submission
  
    const formData = new FormData(this); // 'this' refers to the form
    const password = formData.get('password');
    const confirmPassword = formData.get('confirm_password');

    if (password !== confirmPassword) {
      alert('Passwords do not match.');
      return;
    }
  
    fetch('/register', { 
      method: 'POST',
      body: formData
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        alert('Registration successful!');
      } else {
        alert('Registration failed: ' + data.error);
      }
    })
    .catch(error => {
      console.error('Error:', error);
      alert('An error occurred. Please try again.');
    });
  });

  document.getElementById('signInForm').addEventListener('submit', function(e) {
    e.preventDefault();

    const formData = new FormData(this);

    fetch('/login', { 
        method: 'POST',
        body: new FormData(document.getElementById('signInForm'))
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        return response.json();
    })
    .then(data => {
        if (data.success) {
            alert(data.message);
        } else {
            alert(data.message);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('An error occurred during login. Please try again.');
    });
});

document.addEventListener('DOMContentLoaded', (event) => {
  fetch('/session_check')
      .then(response => response.json())
      .then(data => {
          if (data.logged_in) {
              document.getElementById('signInForm').style.display = 'none'; // hide
              document.getElementById('registrationForm').style.display = 'none';
              document.getElementById('logoutButton').style.display = 'block';

          } else {
              document.getElementById('signInForm').style.display = 'block';
              document.getElementById('registrationForm').style.display = 'block'
              document.getElementById('logoutButton').style.display = 'none';
          }
      })
      .catch(error => console.error('Error checking session state:', error));
});

