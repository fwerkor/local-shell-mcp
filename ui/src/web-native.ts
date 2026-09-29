import { AuditController } from "./web-native/audit"
import type { NativePageContext, NativePageController } from "./web-native/common"
import { DesktopController } from "./web-native/desktop"
import { FilesController } from "./web-native/files"
import { RemotesController } from "./web-native/remotes"
import { SessionsController } from "./web-native/sessions"
import { TerminalsController } from "./web-native/terminals"

export type { NativePageContext, NativePageController, NoticeTone } from "./web-native/common"

export type NativeViewName = "files" | "terminals" | "desktop" | "sessions" | "remotes" | "audit"

export function createNativePage(view: NativeViewName, context: NativePageContext): NativePageController {
  if (view === "files") return new FilesController(context)
  if (view === "terminals") return new TerminalsController(context)
  if (view === "desktop") return new DesktopController(context)
  if (view === "sessions") return new SessionsController(context)
  if (view === "remotes") return new RemotesController(context)
  return new AuditController(context)
}

export function isNativeView(view: string): view is NativeViewName {
  return ["files", "terminals", "desktop", "sessions", "remotes", "audit"].includes(view)
}
