export const theme = {
  bg: "#080b14",
  panel: "#111827",
  panelAlt: "#172033",
  panelSoft: "#1d2940",
  border: "#33415c",
  borderBright: "#66789a",
  text: "#edf3ff",
  muted: "#a0aec6",
  faint: "#68758e",
  cyan: "#5eead4",
  blue: "#7aa2f7",
  green: "#79d69f",
  yellow: "#e0af68",
  orange: "#f6c177",
  red: "#f7768e",
  magenta: "#bb9af7",
  pink: "#f38ba8",
  selected: "#1d2a42",
  selectedStrong: "#263654",
}

export const screenTheme = {
  Dashboard: {
    accent: theme.green,
    selected: "#19372f",
    panel: "#10251f",
  },
  Files: {
    accent: theme.cyan,
    selected: "#173b3a",
    panel: "#102321",
  },
  Terminals: {
    accent: theme.magenta,
    selected: "#352846",
    panel: "#1d1829",
  },
  Todos: {
    accent: theme.orange,
    selected: "#44351f",
    panel: "#251f15",
  },
  Audit: {
    accent: theme.pink,
    selected: "#46283b",
    panel: "#261824",
  },
  Remotes: {
    accent: theme.blue,
    selected: "#263b59",
    panel: "#151f2e",
  },
} as const

export const borders = {
  panel: {
    border: true,
    borderStyle: "rounded" as const,
    borderColor: theme.border,
    backgroundColor: theme.panel,
  },
  active: {
    border: true,
    borderStyle: "rounded" as const,
    borderColor: theme.cyan,
    backgroundColor: theme.panelAlt,
  },
}
