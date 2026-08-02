/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Mirrors the CSS variables in src/index.css -- one centralized
        // solar-gold theme, usable as ordinary Tailwind utilities
        // (bg-ra-surface, text-ra-primary, border-ra-border, ...).
        ra: {
          bg: "var(--ra-bg)",
          "bg-elevated": "var(--ra-bg-elevated)",
          surface: "var(--ra-surface)",
          "surface-hover": "var(--ra-surface-hover)",
          border: "var(--ra-border)",
          "border-soft": "var(--ra-border-soft)",
          primary: "var(--ra-primary)",
          "primary-strong": "var(--ra-primary-strong)",
          "primary-dark": "var(--ra-primary-dark)",
          "primary-soft": "var(--ra-primary-soft)",
          "primary-glow": "var(--ra-primary-glow)",
          text: "var(--ra-text)",
          "text-secondary": "var(--ra-text-secondary)",
          "text-muted": "var(--ra-text-muted)",
          focus: "var(--ra-focus)",
        },
      },
    },
  },
  plugins: [],
};
