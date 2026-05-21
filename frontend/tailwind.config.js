// Lusaber · Լուսաբեր — Tailwind config.
//
// Editorial / newsroom palette: light backgrounds only, dark text,
// color used sparingly for verdict + red-flag signals.

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./*.{js,jsx}",
    "./components/**/*.{js,jsx}",
  ],
  theme: {
    extend: {
      colors: {
        paper: {
          DEFAULT: "#FAFAF9", // page background — warm white
          card: "#FFFFFF",
          border: "#E8E6E1",
        },
        ink: {
          DEFAULT: "#1A1917",
          muted: "#6B6860",
        },
        verdict: {
          credible: "#2D6A4F",
          uncertain: "#B45309",
          disinfo: "#991B1B",
        },
        armenian: {
          red: "#8B1A1A",
        },
      },
      fontFamily: {
        serif: ['"Playfair Display"', "Georgia", "serif"],
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      letterSpacing: {
        verdict: "0.1em",
      },
      transitionDuration: {
        button: "200ms",
      },
      keyframes: {
        fadeRise: {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        fadeRise: "fadeRise 360ms ease-out both",
      },
      maxWidth: {
        page: "1100px",
      },
    },
  },
  plugins: [],
};
