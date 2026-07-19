import { describe, expect, test } from "bun:test"
import {
  createCommandHistory,
  navigateCommandHistory,
  recordCommand,
  resetCommandHistoryNavigation,
} from "./terminal-history"

describe("terminal command history", () => {
  test("records commands, removes adjacent duplicates, and applies the size limit", () => {
    let history = createCommandHistory()
    history = recordCommand(history, "pwd", 2)
    history = recordCommand(history, "pwd", 2)
    history = recordCommand(history, "ls", 2)
    history = recordCommand(history, "git status", 2)

    expect(history.entries).toEqual(["ls", "git status"])
    expect(history.cursor).toBeNull()
  })

  test("walks backward from the newest command and clamps at the oldest", () => {
    let history = recordCommand(createCommandHistory(), "first")
    history = recordCommand(history, "second")

    const newest = navigateCommandHistory(history, "previous", "draft")
    expect(newest.value).toBe("second")
    expect(newest.history.draft).toBe("draft")

    const oldest = navigateCommandHistory(newest.history, "previous", "second")
    expect(oldest.value).toBe("first")

    const clamped = navigateCommandHistory(oldest.history, "previous", "first")
    expect(clamped.value).toBe("first")
    expect(clamped.history.cursor).toBe(0)
  })

  test("walks forward and restores the unfinished draft", () => {
    let history = recordCommand(createCommandHistory(), "first")
    history = recordCommand(history, "second")
    history = navigateCommandHistory(history, "previous", "unfinished").history
    history = navigateCommandHistory(history, "previous", "second").history

    const newer = navigateCommandHistory(history, "next", "first")
    expect(newer.value).toBe("second")

    const draft = navigateCommandHistory(newer.history, "next", "second")
    expect(draft.value).toBe("unfinished")
    expect(draft.history.cursor).toBeNull()
  })

  test("does nothing when no history is available", () => {
    const history = createCommandHistory()
    const result = navigateCommandHistory(history, "previous", "draft")

    expect(result.value).toBeNull()
    expect(result.history).toBe(history)
  })

  test("resets active navigation after the recalled command is edited", () => {
    let history = recordCommand(createCommandHistory(), "pwd")
    history = navigateCommandHistory(history, "previous", "draft").history

    expect(resetCommandHistoryNavigation(history)).toEqual({
      entries: ["pwd"],
      cursor: null,
      draft: "",
    })
  })
})
