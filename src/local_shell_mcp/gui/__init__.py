"""Native desktop GUI automation backends."""

from .base import (
    GUI_STATE_TTL_S,
    GuiManager,
    GuiStaleStateError,
    GuiUnavailableError,
    get_gui_manager,
    reset_gui_manager,
)

__all__ = [
    "GUI_STATE_TTL_S",
    "GuiManager",
    "GuiStaleStateError",
    "GuiUnavailableError",
    "get_gui_manager",
    "reset_gui_manager",
]
