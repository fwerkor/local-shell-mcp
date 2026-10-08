from __future__ import annotations

import json
import sys
from types import ModuleType, SimpleNamespace

import pytest


def test_atspi_window_identity_survives_child_reordering(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    class Window:
        def __init__(self, title, stable_id):
            self.title = title
            self.stable_id = stable_id

        def get_name(self):
            return self.title

        def get_role_name(self):
            return "frame"

        def get_accessible_id(self):
            return self.stable_id

    class App:
        def __init__(self, children):
            self.children = children

        def get_process_id(self):
            return 42

        def get_child_count(self):
            return len(self.children)

        def get_child_at_index(self, index):
            return self.children[index]

    target = Window("Target", "target-window")
    other = Window("Other", "other-window")
    monkeypatch.setattr(
        helper,
        "_bounds",
        lambda window: {
            "x": 100 if window is target else 400,
            "y": 50,
            "width": 300,
            "height": 200,
        },
    )
    signature = helper._window_signature(target)
    target.title = "Target — changed"
    assert helper._window_signature(target) == signature
    app = App([other, target])
    monkeypatch.setattr(helper, "_apps", lambda: [app])

    _app, resolved, index = helper._resolve_window(f"atspi:42:0:{signature}")
    assert resolved is target
    assert index == 1

    monkeypatch.setattr(
        helper,
        "_bounds",
        lambda _window: {"x": 0, "y": 0, "width": 300, "height": 200},
    )
    replacement_signature = helper._window_signature(target)
    replacement = Window("Replacement", "replacement-window")
    app.children = [replacement]
    with pytest.raises(LookupError, match="no longer available"):
        helper._resolve_window(f"atspi:42:0:{replacement_signature}")

    duplicate = Window("Target copy", "target-window")
    app.children = [target, duplicate]
    ambiguous_signature = helper._window_signature(target)
    with pytest.raises(LookupError, match="ambiguous"):
        helper._resolve_window(f"atspi:42:0:{ambiguous_signature}")

def test_atspi_window_without_stable_provider_identity_is_not_exposed():
    import local_shell_mcp.gui.linux_atspi_helper as helper

    class Window:
        def get_accessible_id(self):
            return ""

        def get_role_name(self):
            return "frame"

        def get_name(self):
            return "Mutable"

    class App:
        def get_process_id(self):
            return 42

        def get_name(self):
            return "App"

    window = Window()
    assert helper._window_signature(window) is None
    with pytest.raises(LookupError, match="stable provider identity"):
        helper._record(App(), window, 0)

def test_atspi_window_uses_stable_bus_object_identity_without_accessible_id(monkeypatch):
    import local_shell_mcp.gui.linux_atspi_helper as helper

    class Provider:
        bus_name = ":1.42"

    class Window:
        app = Provider()

        def __init__(self, title, path):
            self.title = title
            self.path = path

        def get_accessible_id(self):
            return ""

        def get_role_name(self):
            return "frame"

        def get_name(self):
            return self.title

    class App:
        def __init__(self, children):
            self.children = children

        def get_process_id(self):
            return 42

        def get_name(self):
            return "App"

        def get_child_count(self):
            return len(self.children)

        def get_child_at_index(self, index):
            return self.children[index]

    target = Window("Target", "/org/a11y/atspi/accessible/1")
    other = Window("Other", "/org/a11y/atspi/accessible/2")
    app = App([target, other])
    monkeypatch.setattr(helper, "_apps", lambda: [app])

    bounds = {
        target: {"x": 10, "y": 20, "width": 300, "height": 200},
        other: {"x": 400, "y": 20, "width": 300, "height": 200},
    }
    monkeypatch.setattr(helper, "_bounds", lambda window: dict(bounds[window]))

    first_id = helper._record(app, target, 0)["id"]
    first_signature = helper._window_signature(target)
    assert first_signature is not None

    target.title = "Target — changed"
    bounds[target] = {"x": 50, "y": 60, "width": 500, "height": 400}
    app.children = [other, target]

    assert helper._record(app, target, 1)["id"] == first_id
    assert helper._window_signature(target) == first_signature
    _resolved_app, resolved, index = helper._resolve_window(first_id)
    assert resolved is target
    assert index == 1

def test_atspi_raw_validators_accept_provider_identity_without_accessible_id(monkeypatch):
    import local_shell_mcp.gui.linux_atspi_helper as helper

    identity = "bus\0:1.42\0path\0/org/a11y/atspi/accessible/7"

    class Component:
        def grab_focus(self):
            return True

    class Window:
        def get_component_iface(self):
            return Component()

    window = Window()
    element = object()
    bounds = {"x": 10, "y": 20, "width": 100, "height": 80}

    monkeypatch.setattr(helper, "_semantic_action", lambda _payload: {"semantic": True})
    monkeypatch.setattr(helper, "_resolve_window", lambda _id: (object(), window, 0))
    monkeypatch.setattr(helper, "_resolve_path", lambda _window, _path: element)
    monkeypatch.setattr(helper, "_element_provider_identity", lambda obj: identity if obj is element else None)
    monkeypatch.setattr(helper, "_element_signature", lambda _obj: "fingerprint")
    monkeypatch.setattr(helper, "_bounds", lambda obj: dict(bounds) if obj is window else {})
    monkeypatch.setattr(helper, "_state", lambda obj, _state: obj is element)
    monkeypatch.setattr(
        helper,
        "Atspi",
        SimpleNamespace(StateType=SimpleNamespace(FOCUSED="focused")),
    )

    locator = {
        "path": [0],
        "identity": identity,
        "accessible_id": "",
        "fingerprint": "fingerprint",
    }
    helper._focus_keyboard_target(
        {
            "window_id": "atspi:1:sig",
            "locator": locator,
        }
    )
    assert (
        helper._prepare_pointer_target(
            {
                "window_id": "atspi:1:sig",
                "window_bounds": bounds,
                "locator": locator,
            }
        )
        == bounds
    )

def test_atspi_window_rejects_oversized_accessible_id_before_fingerprinting():
    import local_shell_mcp.gui.linux_atspi_helper as helper

    class Window:
        def get_accessible_id(self):
            return "x" * (helper.GUI_MAX_WINDOW_TEXT_BYTES + 1)

        def get_role_name(self):
            return "frame"

        def get_name(self):
            return "Huge"

    class App:
        def get_process_id(self):
            return 42

        def get_name(self):
            return "App"

    window = Window()
    assert helper._window_signature(window) is None
    with pytest.raises(LookupError, match="stable provider identity"):
        helper._record(App(), window, 0)

def test_atspi_public_window_id_ignores_sibling_index(monkeypatch):
    import local_shell_mcp.gui.linux_atspi_helper as helper

    class Window:
        def get_accessible_id(self):
            return "stable-window"

        def get_role_name(self):
            return "frame"

        def get_name(self):
            return "Target"

    class App:
        def __init__(self, children):
            self.children = children

        def get_process_id(self):
            return 42

        def get_name(self):
            return "App"

        def get_child_count(self):
            return len(self.children)

        def get_child_at_index(self, index):
            return self.children[index]

    target = Window()
    other = Window()
    other.get_accessible_id = lambda: "other-window"
    app = App([target, other])
    monkeypatch.setattr(helper, "_apps", lambda: [app])
    monkeypatch.setattr(
        helper,
        "_bounds",
        lambda _window: {"x": 0, "y": 0, "width": 100, "height": 100},
    )

    first_id = helper._record(app, target, 0)["id"]
    app.children = [other, target]
    second_id = helper._record(app, target, 1)["id"]
    assert first_id == second_id
    assert first_id.count(":") == 2
    _resolved_app, resolved, index = helper._resolve_window(first_id)
    assert resolved is target
    assert index == 1

def test_atspi_window_focus_accepts_already_active_nonfocusable_window(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    class StateSet:
        def contains(self, state):
            return state == "active"

    class Window:
        def get_state_set(self):
            return StateSet()

        def get_component_iface(self):
            pytest.fail("already-active top-level window must not require grab_focus")

    window = Window()
    monkeypatch.setattr(helper, "_resolve_window", lambda _window_id: (object(), window, 0))
    helper.Atspi = SimpleNamespace(StateType=SimpleNamespace(ACTIVE="active"))

    result = helper._semantic_action(
        {
            "window_id": "atspi:1:sig",
            "locator": [],
            "action": {"type": "focus"},
        }
    )
    assert result == {"semantic": True, "already_active": True}

def test_atspi_raw_keyboard_focuses_and_revalidates_before_injection(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    events = []

    class Component:
        def grab_focus(self):
            events.append(("focus",))
            return True

    class StateSet:
        def contains(self, _state):
            return True

    class Target:
        def get_component_iface(self):
            return Component()

        def get_state_set(self):
            return StateSet()

    target = Target()

    def generate_keyboard_event(keysym, text, synth_type):
        events.append(("key", keysym, text, synth_type))
        return True

    helper.Atspi = SimpleNamespace(
        StateType=SimpleNamespace(FOCUSED="focused"),
        KeySynthType=SimpleNamespace(
            STRING="string",
            PRESS="press",
            RELEASE="release",
            SYM="sym",
        ),
        generate_keyboard_event=generate_keyboard_event,
    )
    monkeypatch.setattr(
        helper,
        "_resolve_window",
        lambda _window_id: (None, target, 0),
    )

    result = helper._raw(
        {
            "kind": "text",
            "window_id": "atspi:1:sig",
            "text": "secret",
        }
    )
    assert result["characters"] == 6
    assert events[:2] == [
        ("focus",),
        ("key", 0, "secret", "string"),
    ]

    events.clear()
    result = helper._raw(
        {
            "kind": "key_chord",
            "window_id": "atspi:1:sig",
            "keys": ["CTRL", "A"],
        }
    )
    assert result["generated"] is True
    assert events[0] == ("focus",)
    assert [item[-1] for item in events[1:]] == [
        "press",
        "press",
        "release",
        "release",
    ]

    events.clear()
    monkeypatch.setattr(helper, "_state", lambda *_args: False)
    with pytest.raises(RuntimeError, match="did not remain focused"):
        helper._raw(
            {
                "kind": "text",
                "window_id": "atspi:1:sig",
                "text": "must-not-leak",
            }
        )
    assert events == [("focus",)]

def test_atspi_mouse_sequence_runs_in_one_helper_process(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    generated = []

    class Atspi:
        @staticmethod
        def generate_mouse_event(x, y, event):
            generated.append((x, y, event))
            return True

    monkeypatch.setattr(helper, "Atspi", Atspi)
    result = helper._raw(
        {
            "kind": "mouse_sequence",
            "events": [
                {"x": 1, "y": 2, "event": "b1c"},
                {"x": 1, "y": 2, "event": "b1c"},
            ],
        }
    )
    assert result == {"generated": True, "events": 2}
    assert generated == [(1, 2, "b1c"), (1, 2, "b1c")]

def test_atspi_bound_pointer_releases_button_after_motion_failure(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    events = []

    class Atspi:
        @staticmethod
        def generate_mouse_event(x, y, event):
            events.append((x, y, event))
            return event != "abs"

    monkeypatch.setattr(helper, "Atspi", Atspi)
    monkeypatch.setattr(
        helper,
        "_prepare_pointer_target",
        lambda _payload: {"x": 0, "y": 0, "width": 100, "height": 100},
    )

    with pytest.raises(RuntimeError, match="mouse synthesis failed"):
        helper._raw(
            {
                "kind": "bound_pointer",
                "window_id": "atspi:1:sig",
                "window_bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
                "events": [
                    {"x": 1, "y": 1, "event": "b1p"},
                    {"x": 10, "y": 10, "event": "abs"},
                    {"x": 10, "y": 10, "event": "b1r"},
                ],
            }
        )

    assert events == [
        (1, 1, "b1p"),
        (10, 10, "abs"),
        (1, 1, "b1r"),
    ]

def test_atspi_bound_pointer_focuses_and_revalidates_before_injection(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    calls = []

    class Component:
        def grab_focus(self):
            calls.append("focus")
            return True

        def get_extents(self, _coord_type):
            return SimpleNamespace(x=10, y=20, width=100, height=80)

    class Window:
        def get_component_iface(self):
            return Component()

    class Atspi:
        CoordType = SimpleNamespace(SCREEN="screen")

        @staticmethod
        def generate_mouse_event(x, y, event):
            calls.append(("mouse", x, y, event))
            return True

    window = Window()
    resolves = []

    def resolve(window_id):
        resolves.append(window_id)
        return object(), window, 0

    monkeypatch.setattr(helper, "Atspi", Atspi)
    monkeypatch.setattr(helper, "_resolve_window", resolve)

    result = helper._raw(
        {
            "kind": "bound_pointer",
            "window_id": "atspi:1:sig",
            "window_bounds": {"x": 10, "y": 20, "width": 100, "height": 80},
            "events": [{"x": 15, "y": 25, "event": "b1c"}],
        }
    )

    assert result == {"generated": True, "events": 1}
    assert resolves == ["atspi:1:sig", "atspi:1:sig"]
    assert calls == ["focus", ("mouse", 15, 25, "b1c")]

def test_atspi_snapshot_bounds_direct_child_provider_calls(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    child_calls = []

    class Node:
        def __init__(self, child_count=0):
            self.child_count = child_count

        def get_role_name(self):
            return "node"

        def get_name(self):
            return "n"

        def get_action_iface(self):
            return None

        def get_child_count(self):
            return self.child_count

        def get_child_at_index(self, index):
            child_calls.append(index)
            return Node()

    root = Node(child_count=100000)
    app = object()
    monkeypatch.setattr(helper, "_resolve_window", lambda _id: (app, root, 0))
    monkeypatch.setattr(helper, "_record", lambda *_args: {"id": "w"})
    monkeypatch.setattr(helper, "_bounds", lambda _obj: {})
    monkeypatch.setattr(helper, "_state", lambda *_args: False)
    monkeypatch.setattr(helper, "_element_signature", lambda _obj: "sig")
    monkeypatch.setattr(
        helper,
        "Atspi",
        SimpleNamespace(StateType=SimpleNamespace(ENABLED=1, FOCUSED=2, EDITABLE=3)),
    )

    result = helper._snapshot(
        {
            "window_id": "w",
            "include_elements": True,
            "max_elements": 3,
            "max_depth": 5,
        }
    )
    assert len(result["elements"]) == 3
    assert child_calls == [0, 1]

def test_atspi_element_signature_bounds_provider_role_and_name(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    huge = "x" * (helper.GUI_MAX_ELEMENT_TEXT_BYTES * 100)
    hashed = []

    class Node:
        def get_accessible_id(self):
            return "stable-id"

        def get_role_name(self):
            return huge

        def get_name(self):
            return huge

    class Digest:
        def hexdigest(self):
            return "a" * 64

    def sha256(data):
        hashed.append(data)
        return Digest()

    monkeypatch.setattr(helper.hashlib, "sha256", sha256)
    monkeypatch.setattr(
        helper,
        "_bounds",
        lambda _obj: {"x": 1, "y": 2, "width": 3, "height": 4},
    )

    assert helper._element_signature(Node()) == "a" * 16
    assert len(hashed) == 1
    assert len(hashed[0]) <= helper.GUI_MAX_ELEMENT_TEXT_BYTES * 3 + 128

def test_atspi_element_signature_uses_provider_object_identity_without_accessible_id(
    monkeypatch,
):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    class Provider:
        bus_name = ":1.42"

    class Node:
        app = Provider()
        path = "/org/a11y/atspi/accessible/7"

        def get_accessible_id(self):
            return ""

        def get_role_name(self):
            return "text"

        def get_name(self):
            return "LSM Input"

    node = Node()
    monkeypatch.setattr(
        helper,
        "_bounds",
        lambda _obj: {"x": 1, "y": 2, "width": 300, "height": 40},
    )

    identity = helper._element_provider_identity(node)
    assert identity == "object\0:1.42\0/org/a11y/atspi/accessible/7"
    assert helper._element_signature(node) is not None

def test_atspi_semantic_action_accepts_provider_object_identity(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    class Component:
        def grab_focus(self):
            return True

    class Provider:
        bus_name = ":1.42"

    class Element:
        app = Provider()
        path = "/org/a11y/atspi/accessible/7"

        def get_accessible_id(self):
            return ""

        def get_component_iface(self):
            return Component()

    element = Element()
    identity = "object\0:1.42\0/org/a11y/atspi/accessible/7"
    monkeypatch.setattr(
        helper,
        "_resolve_window",
        lambda _window_id: (None, object(), 0),
    )
    monkeypatch.setattr(helper, "_resolve_path", lambda _window, _path: element)
    monkeypatch.setattr(helper, "_element_signature", lambda _obj: "observed-fp")
    monkeypatch.setattr(
        helper,
        "Atspi",
        SimpleNamespace(StateType=SimpleNamespace(ACTIVE=object())),
    )

    result = helper._semantic_action(
        {
            "window_id": "atspi:1:sig",
            "locator": {
                "path": [2],
                "identity": identity,
                "accessible_id": "",
                "fingerprint": "observed-fp",
            },
            "action": {"type": "focus"},
        }
    )
    assert result == {"semantic": True}

def test_atspi_element_locator_requires_stable_accessible_identity(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    replacement = object()
    monkeypatch.setattr(
        helper,
        "_resolve_window",
        lambda _window_id: (None, object(), 0),
    )
    monkeypatch.setattr(helper, "_resolve_path", lambda _window, _path: replacement)
    monkeypatch.setattr(helper, "_accessible_id", lambda _obj: "replacement-id")
    monkeypatch.setattr(helper, "_element_signature", lambda _obj: "same-fingerprint")

    with pytest.raises(LookupError, match="changed since observation"):
        helper._semantic_action(
            {
                "window_id": "atspi:1:sig",
                "locator": {
                    "path": [2],
                    "accessible_id": "observed-id",
                    "fingerprint": "same-fingerprint",
                },
                "action": {"type": "focus"},
            }
        )

def test_atspi_semantic_click_rejects_unrelated_actions(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    class ActionIface:
        def get_n_actions(self):
            return 2

        def get_action_name(self, index):
            return ["decrement", "expand"][index]

        def do_action(self, _index):
            pytest.fail("unrelated AT-SPI action must not be invoked as a click")

    class Element:
        def get_action_iface(self):
            return ActionIface()

    element = Element()
    monkeypatch.setattr(
        helper,
        "_resolve_window",
        lambda _window_id: (None, object(), 0),
    )
    monkeypatch.setattr(helper, "_resolve_path", lambda _window, _path: element)
    monkeypatch.setattr(helper, "_accessible_id", lambda _obj: "button-id")
    monkeypatch.setattr(helper, "_element_signature", lambda _obj: "button-fp")

    with pytest.raises(ValueError, match="preferred AT-SPI activation action"):
        helper._semantic_action(
            {
                "window_id": "atspi:1:sig",
                "locator": {
                    "path": [0],
                    "accessible_id": "button-id",
                    "fingerprint": "button-fp",
                },
                "action": {"type": "click"},
            }
        )

def test_atspi_element_locator_rejects_reordered_replacement(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    replacement = object()
    monkeypatch.setattr(helper, "_resolve_window", lambda _window_id: (None, object(), 0))
    monkeypatch.setattr(helper, "_resolve_path", lambda _window, _path: replacement)
    monkeypatch.setattr(helper, "_element_signature", lambda _obj: "replacement")

    with pytest.raises(LookupError, match="changed since observation"):
        helper._semantic_action(
            {
                "window_id": "atspi:1:0:sig",
                "locator": {"path": [2], "fingerprint": "observed"},
                "action": {"type": "focus"},
            }
        )

def test_atspi_apps_skip_defunct_desktop_children(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    good = object()

    class Desktop:
        def get_child_count(self):
            return 3

        def get_child_at_index(self, index):
            if index == 1:
                raise RuntimeError("defunct app")
            return good if index == 2 else None

    monkeypatch.setattr(
        helper,
        "Atspi",
        SimpleNamespace(
            get_desktop_count=lambda: 1,
            get_desktop=lambda _index: Desktop(),
        ),
    )
    assert helper._apps() == [good]

def test_atspi_apps_stop_at_explicit_scan_budget(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    calls = []

    class Desktop:
        def get_child_count(self):
            return 1000

        def get_child_at_index(self, index):
            calls.append(index)
            return None

    monkeypatch.setattr(helper, "GUI_MAX_ATSPI_SCAN", 3)
    monkeypatch.setattr(
        helper,
        "Atspi",
        SimpleNamespace(
            get_desktop_count=lambda: 1,
            get_desktop=lambda _index: Desktop(),
        ),
    )
    assert helper._apps() == []
    assert calls == [0, 1, 2]

def test_atspi_listing_skips_defunct_children(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    class GoodWindow:
        def get_role_name(self):
            return "frame"

    good = GoodWindow()

    class App:
        def get_process_id(self):
            return 42

        def get_child_count(self):
            return 2

        def get_child_at_index(self, index):
            if index == 0:
                raise RuntimeError("defunct")
            return good

    monkeypatch.setattr(helper, "_apps", lambda: [App()])
    monkeypatch.setattr(
        helper,
        "_bounds",
        lambda _window: {"x": 0, "y": 0, "width": 100, "height": 100},
    )
    windows = helper._windows()
    assert len(windows) == 1
    assert windows[0][1] is good

def test_atspi_windows_stop_at_explicit_scan_budget(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    calls = []

    class App:
        def get_process_id(self):
            return 42

        def get_child_count(self):
            return 1000

        def get_child_at_index(self, index):
            calls.append(index)
            return object()

    monkeypatch.setattr(helper, "GUI_MAX_ATSPI_SCAN", 3)
    monkeypatch.setattr(helper, "_apps", lambda: [App()])
    monkeypatch.setattr(
        helper,
        "_bounds",
        lambda _window: {"x": 0, "y": 0, "width": 0, "height": 0},
    )
    assert helper._windows() == []
    assert calls == [0, 1, 2]

def test_atspi_rejects_oversized_element_accessible_id():
    from local_shell_mcp.gui import linux_atspi_helper as helper

    class Element:
        def get_accessible_id(self):
            return "x" * (helper.GUI_MAX_ELEMENT_TEXT_BYTES + 1)

    element = Element()
    assert helper._accessible_id(element) is None
    assert helper._element_signature(element) is None

def test_atspi_listing_skips_iconified_and_nonshowing_windows(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    class StateSet:
        def __init__(self, states):
            self.states = set(states)

        def contains(self, state):
            return state in self.states

    class Window:
        def __init__(self, states):
            self.states = states

        def get_role_name(self):
            return "frame"

        def get_state_set(self):
            return StateSet(self.states)

    visible = Window({"showing"})
    minimized = Window({"showing", "iconified"})
    hidden = Window(set())

    class App:
        def get_process_id(self):
            return 42

        def get_child_count(self):
            return 3

        def get_child_at_index(self, index):
            return [visible, minimized, hidden][index]

    monkeypatch.setattr(
        helper,
        "Atspi",
        SimpleNamespace(StateType=SimpleNamespace(ICONIFIED="iconified", SHOWING="showing")),
    )
    monkeypatch.setattr(helper, "_apps", lambda: [App()])
    monkeypatch.setattr(
        helper,
        "_bounds",
        lambda _window: {"x": 0, "y": 0, "width": 100, "height": 100},
    )

    windows = helper._windows()
    assert [item[1] for item in windows] == [visible]

def test_atspi_helper_bounds_provider_controlled_snapshot_fields(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    huge = "x" * (helper.GUI_MAX_ELEMENT_TEXT_BYTES * 4)

    class StateSet:
        def contains(self, _state):
            return False

    class ActionIface:
        def get_n_actions(self):
            return helper.GUI_MAX_ELEMENT_ACTIONS * 4

        def get_action_name(self, _index):
            return huge

    class Element:
        def __init__(self, index=0):
            self.index = index

        def get_accessible_id(self):
            return f"element-{self.index}"

        def get_role_name(self):
            return huge

        def get_name(self):
            return huge

        def get_action_iface(self):
            return ActionIface()

        def get_state_set(self):
            return StateSet()

        def get_child_count(self):
            return 100 if self.index == 0 else 0

        def get_child_at_index(self, index):
            return Element(index + 1)

    class App:
        def get_process_id(self):
            return 42

        def get_name(self):
            return huge

    root = Element()
    monkeypatch.setattr(
        helper,
        "Atspi",
        SimpleNamespace(
            StateType=SimpleNamespace(
                ENABLED="enabled",
                FOCUSED="focused",
                EDITABLE="editable",
            )
        ),
    )
    monkeypatch.setattr(helper, "_resolve_window", lambda _id: (App(), root, 0))
    monkeypatch.setattr(
        helper,
        "_bounds",
        lambda _obj: {"x": 0, "y": 0, "width": 100, "height": 100},
    )

    result = helper._snapshot(
        {
            "window_id": "atspi:42:sig",
            "include_elements": True,
            "max_elements": helper.GUI_MAX_ELEMENTS,
            "max_depth": helper.GUI_MAX_DEPTH,
        }
    )

    assert len(result["window"]["title"].encode()) <= helper.GUI_MAX_WINDOW_TEXT_BYTES
    assert len(result["window"]["app"].encode()) <= helper.GUI_MAX_WINDOW_TEXT_BYTES
    assert len(json.dumps(result["elements"], ensure_ascii=False).encode()) <= (
        helper.GUI_MAX_ELEMENTS_TOTAL_BYTES
    )
    assert result["elements"]
    for element in result["elements"]:
        assert len(element["role"].encode()) <= helper.GUI_MAX_ELEMENT_TEXT_BYTES
        assert len(element["name"].encode()) <= helper.GUI_MAX_ELEMENT_TEXT_BYTES
        assert len(element["actions"]) <= helper.GUI_MAX_ELEMENT_ACTIONS
        assert all(
            len(action.encode()) <= helper.GUI_MAX_ELEMENT_TEXT_BYTES
            for action in element["actions"]
        )

def test_atspi_window_resolver_stops_at_scan_budget(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    calls = []

    class App:
        def get_process_id(self):
            return 42

        def get_child_count(self):
            return 1000

        def get_child_at_index(self, index):
            calls.append(index)
            return object()

    monkeypatch.setattr(helper, "GUI_MAX_ATSPI_SCAN", 3)
    monkeypatch.setattr(helper, "_apps", lambda: [App()])
    monkeypatch.setattr(helper, "_window_signature", lambda _window: "other")

    with pytest.raises(LookupError, match="no longer available"):
        helper._resolve_window("atspi:42:wanted")
    assert calls == [0, 1, 2]

def test_atspi_semantic_click_stops_at_action_budget(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    names = []

    class ActionIface:
        def get_n_actions(self):
            return 10000

        def get_action_name(self, index):
            names.append(index)
            return "unrelated"

        def do_action(self, _index):
            pytest.fail("unrelated action must not be invoked")

    class Element:
        def get_action_iface(self):
            return ActionIface()

    element = Element()
    monkeypatch.setattr(
        helper,
        "_resolve_window",
        lambda _window_id: (None, object(), 0),
    )
    monkeypatch.setattr(helper, "_resolve_path", lambda _window, _path: element)
    monkeypatch.setattr(helper, "_accessible_id", lambda _obj: "button-id")
    monkeypatch.setattr(helper, "_element_signature", lambda _obj: "button-fp")

    with pytest.raises(ValueError, match="preferred AT-SPI activation action"):
        helper._semantic_action(
            {
                "window_id": "atspi:1:sig",
                "locator": {
                    "path": [0],
                    "accessible_id": "button-id",
                    "fingerprint": "button-fp",
                },
                "action": {"type": "click"},
            }
        )
    assert names == list(range(helper.GUI_MAX_ELEMENT_ACTIONS))

def test_atspi_kscreen_monitor_fallback_parses_geometry_and_scale(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    output = """Output: 1 DP-1
 enabled
 connected
 primary
 Geometry: -1920,0 1920x1080
 Scale: 1.25
Output: 2 HDMI-A-1
 enabled
 connected
 Geometry: 0,0 2560x1440
 Scale: 1
"""
    monkeypatch.setattr(helper.shutil, "which", lambda name: "/usr/bin/kscreen-doctor")
    monkeypatch.setattr(
        helper.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=output),
    )

    assert helper._kscreen_monitors() == [
        {
            "index": 1,
            "x": -1920,
            "y": 0,
            "width": 1920,
            "height": 1080,
            "scale": 1.25,
            "primary": True,
        },
        {
            "index": 2,
            "x": 0,
            "y": 0,
            "width": 2560,
            "height": 1440,
            "scale": 1.0,
            "primary": False,
        },
    ]

def test_atspi_monitors_falls_back_when_gdk_is_unavailable(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    gi = ModuleType("gi")

    def unavailable(*_args):
        raise ValueError("Gdk typelib missing")

    gi.require_version = unavailable
    monkeypatch.setitem(sys.modules, "gi", gi)
    expected = [
        {
            "index": 0,
            "x": 0,
            "y": 0,
            "width": 1920,
            "height": 1080,
            "scale": 1.0,
            "primary": True,
        }
    ]
    monkeypatch.setattr(helper, "_kscreen_monitors", lambda: expected)
    assert helper._monitors() == expected

def test_atspi_timeout_cleanup_releases_confirmed_pressed_inputs(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    events = []

    def mouse(x, y, event):
        events.append(("mouse", x, y, event))
        return True

    def key(symbol, text, synth_type):
        events.append(("key", symbol, text, synth_type))
        return True

    helper.Atspi = SimpleNamespace(
        KeySynthType=SimpleNamespace(RELEASE="release"),
        generate_mouse_event=mouse,
        generate_keyboard_event=key,
    )

    pointer = helper._release_inputs(
        {
            "pressed": [
                {"kind": "mouse", "button": 1, "x": 50, "y": 60},
            ]
        }
    )
    keyboard = helper._release_inputs(
        {
            "pressed": [
                {"kind": "key", "symbol": helper._MODIFIERS["CTRL"]},
                {"kind": "key", "symbol": ord("a")},
            ]
        }
    )

    assert pointer == {"released": 1}
    assert keyboard == {"released": 2}
    assert events == [
        ("mouse", 50, 60, "b1r"),
        ("key", ord("a"), None, "release"),
        ("key", helper._MODIFIERS["CTRL"], None, "release"),
    ]

def test_atspi_key_chord_rechecks_deadline_after_focus(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    now = {"value": 5.0}
    generated = []

    def focus(_payload):
        now["value"] = 20.0

    helper.Atspi = SimpleNamespace(
        KeySynthType=SimpleNamespace(PRESS="press", RELEASE="release"),
        generate_keyboard_event=lambda *args: generated.append(args) or True,
    )
    monkeypatch.setattr(helper, "_focus_keyboard_target", focus)
    monkeypatch.setattr(helper.time, "monotonic", lambda: now["value"])

    with pytest.raises(LookupError, match="expired before native input"):
        helper._raw(
            {
                "kind": "key_chord",
                "keys": ["CTRL", "A"],
                "_observation_deadline": 10.0,
            }
        )
    assert generated == []

def test_atspi_semantic_click_does_not_query_provider_after_activation(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    activated = False

    class ActionIface:
        def get_n_actions(self):
            return 1

        def get_action_name(self, index):
            assert index == 0
            if activated:
                raise AssertionError("provider must not be queried after activation")
            return "press"

        def do_action(self, index):
            nonlocal activated
            assert index == 0
            activated = True
            return True

    class Element:
        def get_action_iface(self):
            return ActionIface()

    element = Element()
    monkeypatch.setattr(helper, "_resolve_window", lambda _window_id: (None, object(), 0))
    monkeypatch.setattr(helper, "_resolve_path", lambda _window, _path: element)
    monkeypatch.setattr(helper, "_accessible_id", lambda _obj: "button-id")
    monkeypatch.setattr(helper, "_element_signature", lambda _obj: "button-fp")

    result = helper._semantic_action(
        {
            "window_id": "atspi:1:sig",
            "locator": {
                "path": [0],
                "accessible_id": "button-id",
                "fingerprint": "button-fp",
            },
            "action": {"type": "click"},
        }
    )
    assert result == {"semantic": True, "method": "press"}
