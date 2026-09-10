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
})
