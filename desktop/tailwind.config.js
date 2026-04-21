/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
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
          DEFAULT: "#1e1e2e",
          raised: "#282838",
          overlay: "#313145",
          border: "#45455a",
        },
        accent: { DEFAULT: "#7c3aed", hover: "#6d28d9" },
      },
    },
  },
  plugins: [],
};
