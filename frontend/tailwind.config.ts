import type { Config } from "tailwindcss";

/**
 * Design tokens sampled directly from the mockups in UI_SCREENS/.
 * Components reference these names; no component hard-codes a hex value.
 */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        sidebar: {
          DEFAULT: "#0f1c3f",
          active: "#1e3a7a",
          border: "#1c2c52",
          text: "#e6ecf5",
          muted: "#7c8db0",
        },
        canvas: "#f4f6f9",
        card: "#ffffff",
        line: "#e2e8f0",
        chip: "#e2e8f0",
        ink: {
          DEFAULT: "#0f172a",
          soft: "#334155",
          muted: "#65758c",
          faint: "#94a3b8",
        },
        primary: {
          DEFAULT: "#0050c8",
          hover: "#0044ab",
          soft: "#dbeafe",
          faint: "#eff5ff",
        },
        success: {
          DEFAULT: "#16a34a",
          text: "#15803d",
          soft: "#dcfce7",
          border: "#86efac",
        },
        warning: {
          DEFAULT: "#d97706",
          text: "#b45309",
          soft: "#fef3c7",
          border: "#fcd34d",
        },
        danger: {
          DEFAULT: "#dc2626",
          text: "#b91c1c",
          soft: "#fee2e2",
          border: "#fca5a5",
        },
      },
      borderRadius: {
        card: "10px",
        control: "8px",
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(15 23 42 / 0.04), 0 1px 3px 0 rgb(15 23 42 / 0.06)",
        raised: "0 4px 12px -2px rgb(15 23 42 / 0.10)",
      },
      fontSize: {
        meta: ["0.75rem", { lineHeight: "1rem" }],
        table: ["0.8125rem", { lineHeight: "1.25rem" }],
      },
      maxWidth: {
        form: "56rem",
        detail: "72rem",
      },
    },
  },
  plugins: [],
};

export default config;
