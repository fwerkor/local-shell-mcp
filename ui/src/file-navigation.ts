export interface PathBreadcrumb {
  label: string
  path: string
}

export interface PointerClick {
  target: string
  at: number
}

export const DOUBLE_CLICK_WINDOW_MS = 500

export function isDoubleClick(
  previous: PointerClick | null,
  target: string,
  at: number,
  windowMs = DOUBLE_CLICK_WINDOW_MS,
): boolean {
  return Boolean(
    previous
      && previous.target === target
      && at >= previous.at
      && at - previous.at <= windowMs,
  )
}

export function pathBreadcrumbs(path: string): PathBreadcrumb[] {
  if (!path || path === ".") return [{ label: ".", path: "." }]

  if (path.startsWith("\\\\")) {
    const parts = path.slice(2).split(/\\+/).filter(Boolean)
    if (parts.length < 2) return [{ label: path, path }]
    const root = `\\\\${parts[0]}\\${parts[1]}`
    const crumbs: PathBreadcrumb[] = [{ label: root, path: root }]
    let current = root
    for (const part of parts.slice(2)) {
      current = `${current}\\${part}`
      crumbs.push({ label: part, path: current })
    }
    return crumbs
  }

  const drive = path.match(/^([A-Za-z]:)[\\/]/)
  if (drive) {
    const root = `${drive[1]}\\`
    const parts = path.slice(drive[0].length).split(/[\\/]+/).filter(Boolean)
    const crumbs: PathBreadcrumb[] = [{ label: root, path: root }]
    let current = root
    for (const part of parts) {
      current = `${current.replace(/\\$/, "")}\\${part}`
      crumbs.push({ label: part, path: current })
    }
    return crumbs
  }

  if (path.startsWith("/")) {
    const parts = path.split(/\/+/).filter(Boolean)
    const crumbs: PathBreadcrumb[] = [{ label: "/", path: "/" }]
    let current = ""
    for (const part of parts) {
      current = `${current}/${part}`
      crumbs.push({ label: part, path: current })
    }
    return crumbs
  }

  const separator = path.includes("\\") ? "\\" : "/"
  const parts = path.split(/[\\/]+/).filter(Boolean)
  const crumbs: PathBreadcrumb[] = [{ label: ".", path: "." }]
  let current = ""
  for (const part of parts) {
    current = current ? `${current}${separator}${part}` : part
    crumbs.push({ label: part, path: current })
  }
  return crumbs
}
