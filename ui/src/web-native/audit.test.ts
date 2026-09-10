import { describe, expect, test } from "bun:test"
import type { AuditEntry, AuditPayload } from "../types"
import type { NativePageContext } from "./common"
import { AuditController } from "./audit"

describe("Native WebUI audit refresh", () => {
  test("preserves detail scroll on refresh and resets it for another record", () => {
    const values = [{ scrollTop: 120, scrollLeft: 24 }, { scrollTop: 40, scrollLeft: 0 }]
    const target = {
      querySelectorAll: () => values,
      set innerHTML(_html: string) {
        values.forEach((value) => { value.scrollTop = 0; value.scrollLeft = 0 })
      },
    }
    const controller = new AuditController({} as NativePageContext) as unknown as {
      entries: AuditEntry[]
      selected: number
      root: unknown
      renderedDetailId: string
      renderDetail: () => void
    }
    controller.entries = [{ id: "a", ts: 1, node: "local", operation: "tool", event: "a" }]
    controller.selected = 0
    controller.renderedDetailId = "a"
    controller.root = { querySelector: (selector: string) => selector === "[data-role=audit-detail]" ? target : null }
    controller.renderDetail()
    expect(values).toEqual([{ scrollTop: 120, scrollLeft: 24 }, { scrollTop: 40, scrollLeft: 0 }])
    controller.entries = [{ id: "b", ts: 2, node: "local", operation: "tool", event: "b" }]
    controller.renderDetail()
    expect(values).toEqual([{ scrollTop: 0, scrollLeft: 0 }, { scrollTop: 0, scrollLeft: 0 }])
  })

  test("keeps following the first row when new audit entries arrive", async () => {
    let resolvePayload!: (payload: AuditPayload) => void
    const context: NativePageContext = {
      api: {
        get: async () => new Promise<AuditPayload>((resolve) => { resolvePayload = resolve }) as never,
        send: async () => undefined as never,
      },
      uiPath: "/ui",
      accessToken: () => null,
      machines: () => [],
      notify: () => undefined,
      refreshChrome: async () => undefined,
    }
    const controller = new AuditController(context) as unknown as {
      entries: AuditEntry[]
      selected: number
      renderList: () => void
      loadDetail: () => Promise<void>
      refresh: () => Promise<void>
    }
    controller.entries = [{ id: "old-a", ts: 1, node: "local", operation: "tool", event: "a" }]
    controller.selected = 0
    controller.renderList = () => undefined
    controller.loadDetail = async () => undefined

    const refresh = controller.refresh()
    resolvePayload({
      count: 2,
      total_matched: 2,
      entries: [
        { id: "new-b", ts: 2, node: "local", operation: "tool", event: "b" },
        { id: "old-a", ts: 1, node: "local", operation: "tool", event: "a" },
      ],
    })
    await refresh

    expect(controller.selected).toBe(0)
    expect(controller.entries[controller.selected]?.id).toBe("new-b")
  })

  test("preserves a selection changed while refresh is pending", async () => {
    let resolvePayload!: (payload: AuditPayload) => void
    const context: NativePageContext = {
      api: {
        get: async () => new Promise<AuditPayload>((resolve) => { resolvePayload = resolve }) as never,
        send: async () => undefined as never,
      },
      uiPath: "/ui",
      accessToken: () => null,
      machines: () => [],
      notify: () => undefined,
      refreshChrome: async () => undefined,
    }
    const controller = new AuditController(context) as unknown as {
      entries: AuditEntry[]
      selected: number
      renderList: () => void
      loadDetail: () => Promise<void>
      refresh: () => Promise<void>
    }
    controller.entries = [
      { id: "old-a", ts: 1, node: "local", operation: "tool", event: "a" },
      { id: "old-b", ts: 2, node: "local", operation: "tool", event: "b" },
    ]
    controller.selected = 0
    controller.renderList = () => undefined
    controller.loadDetail = async () => undefined

    const refresh = controller.refresh()
    controller.selected = 1
    resolvePayload({
      count: 2,
      total_matched: 2,
      entries: [
        { id: "old-b", ts: 3, node: "local", operation: "tool", event: "b" },
        { id: "old-a", ts: 4, node: "local", operation: "tool", event: "a" },
      ],
    })
    await refresh

    expect(controller.selected).toBe(0)
    expect(controller.entries[controller.selected]?.id).toBe("old-b")
  })

  test("preserves the selected record when a filter or sort refresh reorders the list", async () => {
    let resolvePayload!: (payload: AuditPayload) => void
    const context: NativePageContext = {
      api: {
        get: async () => new Promise<AuditPayload>((resolve) => { resolvePayload = resolve }) as never,
        send: async () => undefined as never,
      },
      uiPath: "/ui",
      accessToken: () => null,
      machines: () => [],
      notify: () => undefined,
      refreshChrome: async () => undefined,
    }
    const controller = new AuditController(context) as unknown as {
      entries: AuditEntry[]
      selected: number
      renderList: () => void
      loadDetail: () => Promise<void>
      refresh: (preserveSelection?: boolean) => Promise<void>
    }
    controller.entries = [
      { id: "newest", ts: 3, node: "local", operation: "tool", event: "newest" },
      { id: "middle", ts: 2, node: "local", operation: "tool", event: "middle" },
      { id: "oldest", ts: 1, node: "local", operation: "tool", event: "oldest" },
    ]
    controller.selected = 0
    controller.renderList = () => undefined
    controller.loadDetail = async () => undefined

    const refresh = controller.refresh(true)
    resolvePayload({
      count: 3,
      total_matched: 3,
      entries: [
        { id: "oldest", ts: 1, node: "local", operation: "tool", event: "oldest" },
        { id: "middle", ts: 2, node: "local", operation: "tool", event: "middle" },
        { id: "newest", ts: 3, node: "local", operation: "tool", event: "newest" },
      ],
    })
    await refresh

    expect(controller.selected).toBe(2)
    expect(controller.entries[controller.selected]?.id).toBe("newest")
  })

  test("drops stale detail immediately when the selection changes", async () => {
    let resolveDetail!: (entry: AuditEntry) => void
    const context: NativePageContext = {
      api: {
        get: async () => new Promise<AuditEntry>((resolve) => { resolveDetail = resolve }) as never,
        send: async () => undefined as never,
      },
      uiPath: "/ui",
      accessToken: () => null,
      machines: () => [],
      notify: () => undefined,
      refreshChrome: async () => undefined,
    }
    const controller = new AuditController(context) as unknown as {
      entries: AuditEntry[]
      selected: number
      detail: AuditEntry | null
      renderDetail: () => void
      loadDetail: () => Promise<void>
    }
    controller.entries = [
      { id: "a", ts: 1, node: "local", operation: "tool", event: "a" },
      { id: "b", ts: 2, node: "local", operation: "tool", event: "b" },
    ]
    controller.selected = 1
    controller.detail = { id: "a", ts: 1, node: "local", operation: "tool", event: "a", output: "old" }
    let renders = 0
    controller.renderDetail = () => { renders += 1 }

    const loading = controller.loadDetail()
    expect(controller.detail).toBeNull()
    expect(renders).toBe(1)

    resolveDetail({ id: "b", ts: 2, node: "local", operation: "tool", event: "b", output: "new" })
    await loading
    expect(controller.detail?.id).toBe("b")
    expect(renders).toBe(2)
  })

  test("skips row reconciliation when periodic refresh returns the same rendered rows", async () => {
    const current: AuditEntry = { id: "same", ts: 1, node: "local", operation: "tool", event: "same", status: "success", ok: true }
    const context: NativePageContext = {
      api: {
        get: async () => ({ count: 1, total_matched: 1, entries: [{ ...current }] }) as never,
        send: async () => undefined as never,
      },
      uiPath: "/ui",
      accessToken: () => null,
      machines: () => [],
      notify: () => undefined,
      refreshChrome: async () => undefined,
    }
    const controller = new AuditController(context) as unknown as {
      entries: AuditEntry[]
      selected: number
      renderList: (rowsChanged?: boolean) => void
      loadDetail: () => Promise<void>
      refresh: () => Promise<void>
    }
    controller.entries = [current]
    controller.selected = 0
    const reconciliations: boolean[] = []
    controller.renderList = (rowsChanged = true) => { reconciliations.push(rowsChanged) }
    controller.loadDetail = async () => undefined

    await controller.refresh()

    expect(reconciliations).toEqual([false])
  })

  test("does not refetch unchanged selected detail", async () => {
    let requests = 0
    const current: AuditEntry = { id: "same", ts: 1, node: "local", operation: "tool", event: "same", status: "success", ok: true, output: { value: 1 } }
    const context: NativePageContext = {
      api: {
        get: async () => { requests += 1; return { ...current } as never },
        send: async () => undefined as never,
      },
      uiPath: "/ui",
      accessToken: () => null,
      machines: () => [],
      notify: () => undefined,
      refreshChrome: async () => undefined,
    }
    const controller = new AuditController(context) as unknown as {
      entries: AuditEntry[]
      selected: number
      renderDetail: () => void
      loadDetail: () => Promise<void>
    }
    controller.entries = [current]
    controller.selected = 0
    controller.renderDetail = () => undefined

    await controller.loadDetail()
    await controller.loadDetail()

    expect(requests).toBe(1)
  })

  test("coalesces duplicate detail loads while the same revision is in flight", async () => {
    let requests = 0
    let resolveDetail!: (entry: AuditEntry) => void
    const current: AuditEntry = { id: "same", ts: 1, node: "local", operation: "tool", event: "same", status: "running" }
    const context: NativePageContext = {
      api: {
        get: async () => {
          requests += 1
          return new Promise<AuditEntry>((resolve) => { resolveDetail = resolve }) as never
        },
        send: async () => undefined as never,
      },
      uiPath: "/ui",
      accessToken: () => null,
      machines: () => [],
      notify: () => undefined,
      refreshChrome: async () => undefined,
    }
    const controller = new AuditController(context) as unknown as {
      entries: AuditEntry[]
      selected: number
      renderDetail: () => void
      loadDetail: () => Promise<void>
    }
    controller.entries = [current]
    controller.selected = 0
    controller.renderDetail = () => undefined

    const first = controller.loadDetail()
    const duplicate = controller.loadDetail()
    expect(requests).toBe(1)
    resolveDetail({ ...current })
    await Promise.all([first, duplicate])
    expect(requests).toBe(1)
  })

  test("refreshes detail when the selected preview revision changes", async () => {
    let requests = 0
    const context: NativePageContext = {
      api: {
        get: async () => { requests += 1; return { id: "same", ts: 1, node: "local", operation: "tool", event: "same", output: { request: requests } } as never },
        send: async () => undefined as never,
      },
      uiPath: "/ui",
      accessToken: () => null,
      machines: () => [],
      notify: () => undefined,
      refreshChrome: async () => undefined,
    }
    const controller = new AuditController(context) as unknown as {
      entries: AuditEntry[]
      selected: number
      renderDetail: () => void
      loadDetail: () => Promise<void>
    }
    controller.entries = [{ id: "same", ts: 1, node: "local", operation: "tool", event: "same", status: "running" }]
    controller.selected = 0
    controller.renderDetail = () => undefined

    await controller.loadDetail()
    controller.entries = [{ id: "same", ts: 1, node: "local", operation: "tool", event: "same", status: "success", ok: true, output: { value: 2 } }]
    await controller.loadDetail()

    expect(requests).toBe(2)
  })

  test("moves selection without rebuilding the audit table", () => {
    const controller = new AuditController({} as NativePageContext) as unknown as {
      entries: AuditEntry[]
      selected: number
      root: { querySelector: () => null }
      renderList: () => void
      updateSelectionState: () => void
      loadDetail: () => Promise<void>
      moveSelection: (delta: number) => void
    }
    controller.entries = [
      { id: "a", ts: 2, node: "local", operation: "tool", event: "a" },
      { id: "b", ts: 1, node: "local", operation: "tool", event: "b" },
    ]
    controller.selected = 0
    controller.root = { querySelector: () => null }
    let tableRebuilds = 0
    let selectionUpdates = 0
    controller.renderList = () => { tableRebuilds += 1 }
    controller.updateSelectionState = () => { selectionUpdates += 1 }
    controller.loadDetail = async () => undefined

    controller.moveSelection(1)

    expect(controller.selected).toBe(1)
    expect(selectionUpdates).toBe(1)
    expect(tableRebuilds).toBe(0)
  })

  test("retains full detail while refreshing the same selected record", async () => {
    let resolveDetail!: (entry: AuditEntry) => void
    const context: NativePageContext = {
      api: {
        get: async () => new Promise<AuditEntry>((resolve) => { resolveDetail = resolve }) as never,
        send: async () => undefined as never,
      },
      uiPath: "/ui",
      accessToken: () => null,
      machines: () => [],
      notify: () => undefined,
      refreshChrome: async () => undefined,
    }
    const controller = new AuditController(context) as unknown as {
      entries: AuditEntry[]
      selected: number
      detail: AuditEntry | null
      renderDetail: () => void
      loadDetail: () => Promise<void>
    }
    controller.entries = [{ id: "a", ts: 1, node: "local", operation: "tool", event: "a" }]
    controller.selected = 0
    controller.detail = { id: "a", ts: 1, node: "local", operation: "tool", event: "a", output: "full-old" }
    let renders = 0
    controller.renderDetail = () => { renders += 1 }

    const loading = controller.loadDetail()
    expect(controller.detail?.output).toBe("full-old")
    expect(renders).toBe(0)

    resolveDetail({ id: "a", ts: 1, node: "local", operation: "tool", event: "a", output: "full-new" })
    await loading
    expect(controller.detail?.output).toBe("full-new")
    expect(renders).toBe(1)
  })
})
