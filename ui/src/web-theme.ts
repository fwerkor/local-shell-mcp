export type ThemePreference = "system" | "light" | "dark"

export function parseThemePreference(value: string | null): ThemePreference {
  return value === "light" || value === "dark" ? value : "system"
}

export function resolvedTheme(preference: ThemePreference, systemDark: boolean): "light" | "dark" {
  return preference === "system" ? (systemDark ? "dark" : "light") : preference
}

export function nextThemePreference(preference: ThemePreference): ThemePreference {
  return preference === "system" ? "light" : preference === "light" ? "dark" : "system"
}

export function installWebTheme(button: HTMLButtonElement): void {
  const key = "lsm.ui.theme"
  const media = window.matchMedia("(prefers-color-scheme: dark)")
  let preference: ThemePreference = "system"
  try { preference = parseThemePreference(localStorage.getItem(key)) } catch { /* Storage may be blocked. */ }
  const apply = () => {
    const theme = resolvedTheme(preference, media.matches)
    document.documentElement.dataset.theme = theme
    button.textContent = `Theme: ${preference === "system" ? "Auto" : preference === "dark" ? "Dark" : "Light"}`
    button.title = `Current theme: ${theme}. Click to switch between auto, light and dark.`
    button.setAttribute("aria-label", button.title)
  }
  button.addEventListener("click", () => {
    preference = nextThemePreference(preference)
    try { localStorage.setItem(key, preference) } catch { /* Use the in-memory preference. */ }
    apply()
  })
  media.addEventListener("change", apply)
  apply()
}
