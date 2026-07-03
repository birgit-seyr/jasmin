import { MoonOutlined, SunOutlined } from "@ant-design/icons";
import { Switch } from "antd";
import { useLocale } from "@shared/contexts/LocalContext";

// not used right now, but will be wired in the future

export default function ThemeToggle() {
  const { theme, saveTheme, loading } = useLocale();
  const isDark = theme === "dark";

  const handleChange = async (checked: boolean) => {
    try {
      await saveTheme(checked ? "dark" : "light");
    } catch (err) {
      console.error("Failed to save theme:", err);
    }
  };

  return (
    <Switch
      checked={isDark}
      onChange={handleChange}
      checkedChildren={<MoonOutlined />}
      unCheckedChildren={<SunOutlined />}
      size="small"
      loading={loading}
      disabled={false}
    />
  );
}
