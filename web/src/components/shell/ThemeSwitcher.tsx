"use client";

import { Icon } from "@/components/ui/Icon";
import { Segmented } from "@/components/ui/Segmented";
import type { ThemePref } from "@/lib/theme";
import { useTheme } from "./ThemeProvider";

export function ThemeSwitcher() {
  const { pref, setPref } = useTheme();
  return (
    <Segmented<ThemePref>
      label="Color theme"
      iconsOnly
      value={pref}
      onChange={setPref}
      options={[
        { value: "light", label: <Icon name="sun" size={14} />, ariaLabel: "Light theme" },
        { value: "dark", label: <Icon name="moon" size={14} />, ariaLabel: "Dark theme" },
        { value: "system", label: <Icon name="monitor" size={14} />, ariaLabel: "Match system theme" },
      ]}
    />
  );
}
