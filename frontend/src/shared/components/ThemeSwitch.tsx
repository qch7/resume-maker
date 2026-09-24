import { storage } from "../lib/storage";
import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

type Theme = "light" | "dark" | "system";
const options = [
  { value: "light", label: "浅色", icon: Sun },
  { value: "dark", label: "深色", icon: Moon },
  { value: "system", label: "跟随系统", icon: Monitor },
] as const;

/** 切换浅色、深色或系统主题并持久化用户偏好 */
export default function ThemeSwitch() {
  const [theme, setTheme] = useState<Theme>(() => {
    const value = document.documentElement.dataset.theme;
    return value === "light" || value === "dark" ? value : "system";
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      storage.setItem("rm.theme", theme);
    } catch {
      // 存储不可用时仍切换本次主题
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
