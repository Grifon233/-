/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html","./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        primary: '#006d5b',
        'primary-light': '#e6f0ef',
        'primary-dark': '#005a4b',
      },
      borderRadius: {
        '2xl': '1rem',
        '4xl': '1.25rem',
        '5xl': '2rem',
      },
    },
  },
  plugins: [],
}