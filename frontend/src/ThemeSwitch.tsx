import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";

type Theme = "light" | "dark" | "system";
const options = [
  { value: "light", label: "浅色", icon: Sun },
  { value: "dark", label: "深色", icon: Moon },
  { value: "system", label: "跟随系统", icon: Monitor },
] as const;

export default function ThemeSwitch() {
  const [theme, setTheme] = useState<Theme>(() => {
    const value = document.documentElement.dataset.theme;
    return value === "light" || value === "dark" ? value : "system";
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("rm.theme", theme);
    } catch {
      // Theme switching still works when browser storage is unavailable.
    }
  }, [theme]);
  return (
    <div className="theme-switch" role="group" aria-label="界面主题">
      {options.map(({ value, label, icon: Icon }) => (
        <button
          key={value}
          aria-label={label}
          aria-pressed={theme === value}
          title={label}
          onClick={() => setTheme(value)}
        >
          <Icon size={15} />
          <span>{label}</span>
        </button>
      ))}
    </div>
  );
}
