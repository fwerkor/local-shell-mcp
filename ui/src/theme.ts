export const theme = {
  bg: "#07111f",
  panel: "#0b1729",
  panelAlt: "#0e2036",
  panelSoft: "#102841",
  border: "#27445f",
  borderBright: "#4f84a8",
  text: "#d8e9f5",
  muted: "#7893a8",
  faint: "#496479",
  cyan: "#57d7ff",
  blue: "#6ca7ff",
  green: "#6ee7a8",
  yellow: "#ffd479",
  orange: "#ffad66",
  red: "#ff7b8b",
  magenta: "#d9a7ff",
  selected: "#173d59",
  selectedStrong: "#1d5273",
}

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
