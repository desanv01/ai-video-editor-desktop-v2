/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ["Segoe UI", "Arial", "sans-serif"] },
      colors: {
        // Segment action colors
        action: {
          keep: { DEFAULT: "#22c55e", light: "#dcfce7", dark: "#166534" },
          cut: { DEFAULT: "#ef4444", light: "#fee2e2", dark: "#991b1b" },
          shorten: { DEFAULT: "#3b82f6", light: "#dbeafe", dark: "#1e40af" },
          highlight: { DEFAULT: "#eab308", light: "#fef9c3", dark: "#854d0e" },
        },
        // App palette
        surface: {
          DEFAULT: "#191e23",
          raised: "#232a31",
          overlay: "#2d363f",
          border: "#46535f",
        },
        accent: { DEFAULT: "#0f766e", hover: "#115e59", foreground: "#5eead4", focus: "#99f6e4" },
        gray: { 300: "#c8d1db", 400: "#b3bfcb", 500: "#a3b0be", 600: "#96a4b3" },
      },
    },
  },
  plugins: [],
};
