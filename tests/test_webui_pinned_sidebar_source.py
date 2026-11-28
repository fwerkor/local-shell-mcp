"""Regression guards for separate pinned favorites and conversations."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "ui/workspace/client/src"


def test_sidebar_pins_conversations_and_model_selector_pins_favorites():
    sidebar = (CLIENT / "components/Conversations/PinnedSection.tsx").read_text(encoding="utf-8")
    selector = (CLIENT / "components/Chat/Menus/Endpoints/ModelSelector.tsx").read_text(encoding="utf-8")
    favorites = (CLIENT / "components/Chat/Menus/Endpoints/components/PinnedModels.tsx").read_text(encoding="utf-8")
    assert 'data-pinned-section="favorites"' not in sidebar
    assert 'data-pinned-section="conversations"' in sidebar
    assert 'data-pinned-section="favorites"' in favorites
    assert '<PinnedModels />' in selector
    assert "ref={setConversationSectionRef}" in sidebar
    assert "accept: CONVERSATION_DRAG_TYPE" in sidebar
    assert "useUpdatePinnedOrderMutation" in sidebar
    assert "useUpdatePinnedOrderMutation" in favorites
    assert "orderPinnedFavorites" in favorites


def test_pinned_group_labels_are_localized():
    for language in ("en", "zh-Hans", "zh-Hant"):
        translations = json.loads((CLIENT / f"locales/{language}/translation.json").read_text(encoding="utf-8"))
        assert translations["com_ui_pinned_favorites"]
        assert translations["com_ui_pinned_conversations"]
        assert translations["com_ui_pinned_favorites"] != translations["com_ui_pinned_conversations"]
