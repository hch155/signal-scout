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
    }),
  },
},
  plugins: [
    require('@tailwindcss/typography'),
  ],
}

