/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        risk: "#dc2626",
        protected: "#16a34a",
        estimate: "#d97706",
      },
    },
  },
  plugins: [],
};
