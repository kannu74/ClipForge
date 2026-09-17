/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: "#0b0d12",
          raised: "#131722",
          border: "#1f2430",
        },
        accent: {
          DEFAULT: "#7c5cff",
          hover: "#8f72ff",
        },
      },
    },
  },
  plugins: [],
};
