/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/js/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        'custom-blue-start': '#eff6ff',
        'custom-blue-mid': '#dbeafe',
        'custom-blue-end': '#bfdbfe',
    },
  },
},
  plugins: [],
}

