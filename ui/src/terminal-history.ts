export const TERMINAL_COMMAND_HISTORY_LIMIT = 200

export interface CommandHistoryState {
  entries: string[]
  cursor: number | null
  draft: string
}

export interface CommandHistoryNavigation {
  history: CommandHistoryState
  value: string | null
}

export function createCommandHistory(): CommandHistoryState {
  return { entries: [], cursor: null, draft: "" }
}

export function recordCommand(
  history: CommandHistoryState,
  command: string,
  limit = TERMINAL_COMMAND_HISTORY_LIMIT,
): CommandHistoryState {
  if (command.length === 0) return resetCommandHistoryNavigation(history)

  const entries = history.entries.at(-1) === command
    ? history.entries
    : [...history.entries, command].slice(-Math.max(1, limit))

  return { entries, cursor: null, draft: "" }
}

export function resetCommandHistoryNavigation(history: CommandHistoryState): CommandHistoryState {
  if (history.cursor === null && history.draft.length === 0) return history
  return { entries: history.entries, cursor: null, draft: "" }
}

export function navigateCommandHistory(
  history: CommandHistoryState,
  direction: "previous" | "next",
  currentValue: string,
): CommandHistoryNavigation {
  if (history.entries.length === 0) return { history, value: null }

  if (direction === "previous") {
    const cursor = history.cursor === null
      ? history.entries.length - 1
      : Math.max(0, history.cursor - 1)
    return {
      history: {
        entries: history.entries,
        cursor,
        draft: history.cursor === null ? currentValue : history.draft,
      },
      value: history.entries[cursor]!,
    }
  }

  if (history.cursor === null) return { history, value: null }
  if (history.cursor < history.entries.length - 1) {
    const cursor = history.cursor + 1
    return {
      history: { ...history, cursor },
      value: history.entries[cursor]!,
    }
  }

  return {
    history: { entries: history.entries, cursor: null, draft: "" },
    value: history.draft,
  }
}
