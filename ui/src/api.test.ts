import { afterEach, describe, expect, test } from "bun:test"
import { API_BASE, api, formatError } from "./api"

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
})

function success(data: unknown = { value: true }): Response {
  return new Response(JSON.stringify({ ok: true, message: "", data }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  })
}

describe("API client endpoint wrappers", () => {
  test("encodes every shared UI endpoint consistently", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = []
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), init })
      return success()
    }) as unknown as typeof fetch

    await api.bootstrap()
    await api.machines()
    await api.files("worker a", "src path")
    await api.filePreview("local", "")
    await api.fileContent("local", "a/b")
    await api.fileAction("rename item", { path: "a", destination: "b" })
    await api.terminals("worker a")
    await api.terminalRead("worker a", "session/1", 25)
    await api.terminalAction("send input", { session_id: "s", input_text: "x" })
    await api.todos()
    await api.writeTodos(
      [{ id: "a", content: "A", status: "pending", priority: "medium" }],
      7,
    )
    await api.audit({ node: "worker a", empty: "", zero: 0, enabled: false, omitted: null })
    await api.auditDetail("call:abc/123")
    await api.remotes()
    await api.invite({ name: "node", workdir: "/work", ttl_s: 60 })
    await api.remoteAction("rename node", { machine: "node", new_name: "next" })

    expect(calls.map((call) => call.url)).toEqual([
      `${API_BASE}/bootstrap`,
      `${API_BASE}/machines`,
      `${API_BASE}/files?machine=worker+a&path=src+path`,
      `${API_BASE}/files/preview?machine=local`,
      `${API_BASE}/files/content?machine=local&path=a%2Fb`,
      `${API_BASE}/files/rename%20item`,
      `${API_BASE}/terminals?machine=worker+a`,
      `${API_BASE}/terminals/read?machine=worker+a&session_id=session%2F1&lines=25`,
      `${API_BASE}/terminals/send%20input`,
      `${API_BASE}/todos`,
      `${API_BASE}/todos`,
      `${API_BASE}/audit?node=worker+a&zero=0&enabled=false`,
      `${API_BASE}/audit/detail?id=call%3Aabc%2F123`,
      `${API_BASE}/remotes`,
      `${API_BASE}/remotes`,
      `${API_BASE}/remotes/rename%20node`,
    ])

    expect(calls[5]!.init?.method).toBe("POST")
    expect(JSON.parse(String(calls[5]!.init?.body))).toEqual({ path: "a", destination: "b" })
    expect(calls[10]!.init?.method).toBe("PUT")
    expect(JSON.parse(String(calls[10]!.init?.body))).toEqual({
      todos: [{ id: "a", content: "A", status: "pending", priority: "medium" }],
      expected_revision: 7,
    })
    expect(calls[14]!.init?.method).toBe("POST")
    expect(calls.every((call) => new Headers(call.init?.headers).get("Accept") === "application/json")).toBe(true)
    expect(calls.every((call) => new Headers(call.init?.headers).get("Content-Type") === "application/json")).toBe(true)
  })

  test("propagates an already-aborted external signal", async () => {
    const external = new AbortController()
    external.abort(new Error("cancelled"))
    let observed: AbortSignal | undefined
    globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      observed = init?.signal as AbortSignal
      return success()
    }) as unknown as typeof fetch

    await api.files("local", ".", external.signal)

    expect(observed?.aborted).toBe(true)
    expect((observed?.reason as Error).message).toBe("cancelled")
  })
})

describe("API response handling", () => {
  test("returns envelope data", async () => {
    globalThis.fetch = (async () => success({ answer: 42 })) as unknown as typeof fetch
    expect(await api.bootstrap()).toEqual({ answer: 42 } as never)
  })

  test("uses server message or error for failed envelopes", async () => {
    globalThis.fetch = (async () =>
      new Response(JSON.stringify({ ok: false, message: "conflict", error: "fallback" }), {
        status: 409,
        statusText: "Conflict",
      })) as unknown as typeof fetch
    expect(api.todos()).rejects.toThrow("conflict")

    globalThis.fetch = (async () =>
      new Response(JSON.stringify({ ok: false, message: "", error: "typed-error" }), {
        status: 400,
        statusText: "Bad Request",
      })) as unknown as typeof fetch
    expect(api.todos()).rejects.toThrow("typed-error")
  })

  test("reports status text when JSON is unavailable or the envelope has no detail", async () => {
    globalThis.fetch = (async () =>
      new Response("not-json", { status: 502, statusText: "Bad Gateway" })) as unknown as typeof fetch
    expect(api.todos()).rejects.toThrow("502 Bad Gateway")

    globalThis.fetch = (async () =>
      new Response(JSON.stringify({ ok: true, data: null }), {
        status: 503,
        statusText: "Unavailable",
      })) as unknown as typeof fetch
    expect(api.todos()).rejects.toThrow("503 Unavailable")
  })
})

describe("formatError", () => {
  test("formats Error instances and arbitrary values", () => {
    expect(formatError(new Error("boom"))).toBe("boom")
    expect(formatError(42)).toBe("42")
    expect(formatError(null)).toBe("null")
  })
})
