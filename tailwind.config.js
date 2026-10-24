/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#090b10",
        panel: "#12151c",
        panel2: "#191e28",
        line: "#2a3140",
        amber: "#f0b429",
        mist: "#9aa3b2",
      },
      fontFamily: {
        sans: ['"Segoe UI Variable Text"', '"Segoe UI"', "sans-serif"],
        mono: ['"Cascadia Mono"', '"Cascadia Code"', "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
