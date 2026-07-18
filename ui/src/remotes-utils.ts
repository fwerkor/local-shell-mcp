import type { Machine } from "./types"

export function remoteVersion(machine: Machine): string {
  const version = machine.info?.lsm_version
  return typeof version === "string" && version.trim() ? version : "—"
}

export function remoteSystemInfo(machine: Machine): Record<string, unknown> {
  const info = { ...(machine.info || {}) }
  delete info.lsm_version
  return info
}
