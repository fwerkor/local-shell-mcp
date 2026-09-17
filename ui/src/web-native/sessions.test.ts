import { describe, expect, test } from "bun:test"
import { SessionsController } from "./sessions"

function summary(updatedAt = 1) {
  return {
    session_id: "s1",
    status: "active",
    label: "Task",
    objective: "Do work",
    created_at: 1,
    updated_at: updatedAt,
    progress: { findings: [], blockers: [] },
    plan: null,
    recent_activity: [],
  }
}

describe("Native WebUI logical session performance", () => {
  test("forced refresh waits for an in-flight refresh and then fetches fresh state", async () => {
    let requests = 0
    let resolveFirst!: (value: unknown) => void
    const active = summary(1)
    const completed = { ...summary(2), status: "completed" }
    const payload = (session: any) => ({
      sessions: [session],
      counts: {
        active: session.status === "active" ? 1 : 0,
        completed: session.status === "completed" ? 1 : 0,
        cancelled: 0,
        total: 1,
      },
    })
    const controller: any = new SessionsController({
      api: {
        get: async () => {
          requests += 1
          if (requests === 1) return new Promise((resolve) => { resolveFirst = resolve })
          return payload(completed)
        },
      },
      notify: () => undefined,
    } as any)
    controller.root = { querySelector: () => null }
    controller.renderSummary = () => undefined
    controller.renderList = () => undefined
    controller.renderActions = () => undefined
    controller.renderBulkActions = () => undefined
    controller.loadDetail = async () => undefined

    const first = controller.refresh()
    const forced = controller.refresh(true)
    expect(requests).toBe(1)

    resolveFirst(payload(active))
    await first
    await forced

    expect(requests).toBe(2)
    expect(controller.sessions[0].status).toBe("completed")
  })

  test("does not refetch unchanged selected detail", async () => {
    let requests = 0
    const controller: any = new SessionsController({
      api: { get: async () => { requests += 1; return summary(1) } },
      notify: () => undefined,
    } as any)
    controller.sessions = [summary(1)]
    controller.selectedId = "s1"
    controller.root = { querySelector: () => null }
    controller.renderDetail = () => undefined
    controller.renderActions = () => undefined

    await controller.loadDetail()
    await controller.loadDetail()

    expect(requests).toBe(1)
  })

  test("refetches detail when the selected session revision changes", async () => {
    let requests = 0
    const controller: any = new SessionsController({
      api: { get: async () => { requests += 1; return summary(requests) } },
      notify: () => undefined,
    } as any)
    controller.sessions = [summary(1)]
    controller.selectedId = "s1"
    controller.root = { querySelector: () => null }
    controller.renderDetail = () => undefined
    controller.renderActions = () => undefined

    await controller.loadDetail()
    controller.sessions = [summary(2)]
    await controller.loadDetail()

    expect(requests).toBe(2)
  })

  test("does not duplicate an in-flight detail request when the selected row is clicked again", async () => {
    let requests = 0
    let resolveDetail!: (value: unknown) => void
    const controller: any = new SessionsController({
      api: {
        get: async () => {
          requests += 1
          return new Promise((resolve) => { resolveDetail = resolve })
        },
      },
      notify: () => undefined,
    } as any)
    controller.sessions = [summary(1)]
    controller.selectedId = "s1"
    controller.root = { querySelector: () => null }
    controller.renderDetail = () => undefined
    controller.renderActions = () => undefined

    const first = controller.loadDetail()
    controller.selectSession("s1")
    expect(requests).toBe(1)
    resolveDetail(summary(1))
    await first
    expect(requests).toBe(1)
  })

  test("changes selection without rebuilding the full session table", () => {
    const controller: any = new SessionsController({} as any)
    controller.selectedId = "s1"
    controller.detail = summary(1)
    let selectionUpdates = 0
    let listRenders = 0
    controller.updateSelectionState = () => { selectionUpdates += 1 }
    controller.renderActions = () => undefined
    controller.renderList = () => { listRenders += 1 }
    controller.loadDetail = async () => undefined
    controller.root = { querySelector: () => null }

    controller.selectSession("s2")

    expect(controller.selectedId).toBe("s2")
    expect(selectionUpdates).toBe(1)
    expect(listRenders).toBe(0)
  })

  test("updates session row content without replacing its checkbox", () => {
    const checkbox: any = {
      dataset: { sessionSelect: "s1" },
      ariaLabel: "Select Task",
      setAttribute(name: string, value: string) {
        if (name === "aria-label") this.ariaLabel = value
      },
    }
    const checkboxCell: any = {
      querySelector: () => checkbox,
      set innerHTML(_: string) {
        throw new Error("checkbox cell must not be rebuilt")
      },
    }
    const cells: any[] = [
      checkboxCell,
      { innerHTML: "" },
      { innerHTML: "" },
      { textContent: "" },
      { textContent: "" },
    ]
    const row: any = {
      dataset: { sessionId: "s1" },
      cells,
      remove: () => undefined,
    }
    const body: any = {
      rows: [row],
      insertBefore: () => undefined,
    }
    const controller: any = new SessionsController({} as any)
    controller.rowRevisions.set("s1", "stale")

    controller.reconcileSessionRows(body, [{ ...summary(2), label: "Renamed" }])

    expect(cells[0].querySelector()).toBe(checkbox)
    expect(checkbox.dataset.sessionSelect).toBe("s1")
    expect(checkbox.ariaLabel).toBe("Select Renamed")
    expect(cells[2].innerHTML).toContain("Renamed")
  })

  test("batch lifecycle actions only target eligible selected sessions", () => {
    const active = summary(1)
    const activeWithPlan = {
      ...summary(2),
      session_id: "s2",
      plan: { status: "active", steps: [], objective: "Plan" },
    }
    const completed = { ...summary(3), session_id: "s3", status: "completed" }
    const cancelled = { ...summary(4), session_id: "s4", status: "cancelled" }
    const controller: any = new SessionsController({} as any)
    controller.sessions = [active, activeWithPlan, completed, cancelled]
    controller.selectedIds.add("s1")
    controller.selectedIds.add("s2")
    controller.selectedIds.add("s3")
    controller.selectedIds.add("s4")

    expect(controller.bulkTargets("finish")).toEqual({ targets: [active], skipped: 3 })
    expect(controller.bulkTargets("cancel")).toEqual({ targets: [active, activeWithPlan], skipped: 2 })
    expect(controller.bulkTargets("delete")).toEqual({ targets: [completed, cancelled], skipped: 2 })
  })
})
