type WorkloadSnapshot = {
  jobs?: unknown[]
  sessions?: unknown[]
}

export function visibleWorkloadCount(data: WorkloadSnapshot): number {
  return (data.jobs?.length || 0) + (data.sessions?.length || 0)
}

export function activeJobCount(data: { job_counts?: Record<string, number>; jobs?: unknown[] }): number {
  if (!data.job_counts) return data.jobs?.length || 0
  return ["starting", "running", "stopping", "retrying"].reduce((total, state) => total + (data.job_counts?.[state] || 0), 0)
}
