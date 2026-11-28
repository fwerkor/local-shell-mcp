"""Regression guards for separate pinned favorites and conversations."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "ui/workspace/client/src"


def test_sidebar_has_separate_pinned_groups():
    source = (CLIENT / "components/Conversations/PinnedSection.tsx").read_text(encoding="utf-8")
    assert 'data-pinned-section="favorites"' in source
    assert 'data-pinned-section="conversations"' in source
    assert "displayEntries.filter((entry) => entry.kind === 'favorite')" in source
    assert "displayEntries.filter((entry) => entry.kind === 'convo')" in source
    assert "pinnedFavoritesSectionExpanded" in source
    assert "pinnedSectionExpanded" in source
    assert "focusFirstRow(favoriteSectionRef.current)" in source
    assert "ref={setConversationSectionRef}" in source
    assert "accept: CONVERSATION_DRAG_TYPE" in source
    assert "useUpdatePinnedOrderMutation" in source


def test_pinned_group_labels_are_localized():
    for language in ("en", "zh-Hans", "zh-Hant"):
        translations = json.loads((CLIENT / f"locales/{language}/translation.json").read_text(encoding="utf-8"))
        assert translations["com_ui_pinned_favorites"]
        assert translations["com_ui_pinned_conversations"]
        assert translations["com_ui_pinned_favorites"] != translations["com_ui_pinned_conversations"]


def test_root_sidebar_uses_unassigned_scope_without_limiting_search_or_archive():
    source = (CLIENT / "components/UnifiedSidebar/ConversationsSection.tsx").read_text(encoding="utf-8")
    assert "projectId: search.debouncedQuery || isArchivedView ? undefined : 'unassigned'" in source
    assert "pinnedConversations.filter((conversation) => !conversation.chatProjectId)" in source
    assert "conversations={rootPinnedConversations}" in source
    assert "rootPinnedConversations.length === pinnedConversations.length" in source
