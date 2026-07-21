type WorkloadSnapshot = {
  jobs?: unknown[]
  sessions?: unknown[]
}

export function visibleWorkloadCount(data: WorkloadSnapshot): number {
  return (data.jobs?.length || 0) + (data.sessions?.length || 0)
}

export function todoTitle(todo: Record<string, unknown>): string {
  for (const key of ["content", "title", "text", "description"]) {
    const value = todo[key]
    if (typeof value === "string" && value) return value
  }
  return "Untitled todo"
}
