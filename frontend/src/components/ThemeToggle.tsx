import { useEffect, useState } from "react";

type Theme = "light" | "dark" | "system";

const STORAGE_KEY = "tfg.theme";

function readStoredTheme(): Theme {
  if (typeof window === "undefined") return "system";
  const v = window.localStorage.getItem(STORAGE_KEY);
  return v === "light" || v === "dark" ? v : "system";
}

function applyTheme(t: Theme) {
  const root = document.documentElement;
  if (t === "system") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", t);
  }
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => readStoredTheme());

  useEffect(() => {
    applyTheme(theme);
    if (theme === "system") {
      window.localStorage.removeItem(STORAGE_KEY);
    } else {
      window.localStorage.setItem(STORAGE_KEY, theme);
    }
  }, [theme]);

  const next: Record<Theme, Theme> = {
    system: "light",
    light: "dark",
    dark: "system",
  };

  const label = theme === "system" ? "Tema del sistema" : theme === "light" ? "Tema claro" : "Tema oscuro";
  const title =
    theme === "system"
      ? "Tema actual: sistema. Pulsa para cambiar a claro."
      : theme === "light"
        ? "Tema actual: claro. Pulsa para cambiar a oscuro."
        : "Tema actual: oscuro. Pulsa para volver al del sistema.";

  return (
    <button
      type="button"
      className="theme-toggle"
      aria-label={label}
      title={title}
      onClick={() => setTheme(next[theme])}
      data-theme-state={theme}
    >
      <ThemeIcon theme={theme} />
    </button>
  );
}

function ThemeIcon({ theme }: { theme: Theme }) {
  if (theme === "system") {
    return (
      <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <rect x="1.75" y="2.75" width="12.5" height="9" rx="1.25" stroke="currentColor" strokeWidth="1.2" />
        <path d="M5.5 13.75h5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      </svg>
    );
  }
  if (theme === "light") {
    return (
      <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <circle cx="8" cy="8" r="3" stroke="currentColor" strokeWidth="1.2" />
        <path
          d="M8 1.5v1.6M8 12.9v1.6M14.5 8h-1.6M3.1 8H1.5M12.6 3.4l-1.1 1.1M4.5 11.5l-1.1 1.1M12.6 12.6l-1.1-1.1M4.5 4.5L3.4 3.4"
          stroke="currentColor"
          strokeWidth="1.2"
          strokeLinecap="round"
        />
      </svg>
    );
  }
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M13.5 9.6A5.4 5.4 0 0 1 6.4 2.5a5.5 5.5 0 1 0 7.1 7.1Z"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function bootstrapTheme() {
  if (typeof window === "undefined") return;
  const stored = readStoredTheme();
  if (stored !== "system") {
    document.documentElement.setAttribute("data-theme", stored);
  }
}
