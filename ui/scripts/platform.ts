export const OPEN_TUI_NATIVE_PACKAGES = [
  "@opentui/core-darwin-x64",
  "@opentui/core-darwin-arm64",
  "@opentui/core-linux-x64",
  "@opentui/core-linux-arm64",
  "@opentui/core-linux-x64-musl",
  "@opentui/core-linux-arm64-musl",
  "@opentui/core-win32-x64",
  "@opentui/core-win32-arm64",
] as const

export function currentOpenTuiNativePackage(): string {
  const arch = process.arch === "arm64" ? "arm64" : "x64"
  if (process.platform === "darwin") return `@opentui/core-darwin-${arch}`
  if (process.platform === "win32") return `@opentui/core-win32-${arch}`
  const libc = process.env.OPENTUI_LIBC === "musl" ? "-musl" : ""
  return `@opentui/core-linux-${arch}${libc}`
}

export function nonCurrentOpenTuiNativePackages(): string[] {
  const current = currentOpenTuiNativePackage()
  return OPEN_TUI_NATIVE_PACKAGES.filter((name) => name !== current)
}
