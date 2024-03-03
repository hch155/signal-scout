/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    "./templates/*.html",
    "./static/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        'custom-blue-start': '#eff6ff',
        'custom-blue-mid': '#dbeafe',
        'custom-blue-end': '#bfdbfe',
        'custom-dark-start': '#374151',
        'custom-dark-mid': '#374151',
        'custom-dark-end': '#030712',
        'dark': {
          'text': '#f0f0f0',
          'h2': '#e5e7eb',
          'p': '#e5e7eb',
          'a': '#e5e7eb',
          'a-hover': '#1e40af', 
    },
    typography: (theme) => ({
      DEFAULT: {
        css: {
          color: theme('colors.gray.700'),
          h2: {
            textAlign: 'center',
            fontWeight: '700',
            color: theme('colors.gray.700'),
          },
          p: {
            marginBottom: '1em',
          },
          a: {
            color: theme('colors.gray.700'), 
            '&:hover': {
              color: theme('colors.custom-blue-end'), 
            },
          },
        },
      },
      dark: {
        css: {
          color: theme('colors.dark.text'),
          h2: {
            color: theme('colors.dark.h2'),
          },
          p: {
            color: theme('colors.dark.p'),
          },
          a: {
            color: theme('colors.dark.a'),
            '&:hover': {
              color: theme('colors.dark.a-hover'), 
            },
          },
        },
      },
    }),
  },
},
  plugins: [
    require('@tailwindcss/typography'),
  ],
}
}
