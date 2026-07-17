import { ImageAddon, type IImageAddonOptions } from "@xterm/addon-image"

export const WEB_IMAGE_ADDON_OPTIONS = {
  enableSizeReports: true,
  sixelSupport: true,
  sixelScrolling: true,
  iipSupport: true,
  storageLimit: 64,
  showPlaceholder: false,
} satisfies IImageAddonOptions

export function createImageAddon(): ImageAddon {
  return new ImageAddon(WEB_IMAGE_ADDON_OPTIONS)
}
