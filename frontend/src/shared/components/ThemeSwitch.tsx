import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

type Theme = "light" | "dark" | "system";
const options = [
  { value: "light", label: "浅色", icon: Sun },
  { value: "dark", label: "深色", icon: Moon },
  { value: "system", label: "跟随系统", icon: Monitor },
] as const;

/** 切换浅色、深色或系统主题，并持久化用户偏好。 */
export default function ThemeSwitch() {
  const [theme, setTheme] = useState<Theme>(
    /* 仅在首次挂载时读取缓存或计算初始状态。 */ () => {
      const value = document.documentElement.dataset.theme;
      return value === "light" || value === "dark" ? value : "system";
    },
  );
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      document.documentElement.dataset.theme = theme;
      try {
        localStorage.setItem("rm.theme", theme);
      } catch {
        // 浏览器禁用存储时仍即时切换主题，只是不持久化该偏好。
      }
    },
    [theme],
  );
  return (
    <div className="theme-switch" role="group" aria-label="界面主题">
      {options.map(
        /* 按稳定标识生成对应的列表条目。 */ ({ value, label, icon: Icon }) => (
          <button
            key={value}
            aria-label={label}
            aria-pressed={theme === value}
            title={label}
            onClick={
              /* 响应当前操作按钮，执行对应业务动作。 */ () => setTheme(value)
            }
          >
            <Icon size={15} />
            <span>{label}</span>
          </button>
        ),
      )}
    </div>
  );
}
