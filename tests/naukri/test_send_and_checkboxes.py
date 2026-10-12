"""The two failures from the run of 7 October 16:21.

Four of four jobs needing a long answer failed with "no success confirmation":
the answer was inserted in one step, the send control was checked instantly,
found still carrying its disabled class, and the answer was never sent. Short
answers typed key by key took seconds, by which time the button had enabled,
which is why only long answers were affected.

A city question stalled for thirty seconds with every handler reporting
nothing to do. Naukri's multi-select hides its checkbox inputs and styles the
labels, so filtering for displayed inputs discarded all of them.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from naukri_bot import chatbot


class _Element:
    def __init__(self, classes="", displayed=True, enabled=True, elem_id="",
                 text="", selected=False, for_attr=None):
        self._classes = classes
        self._displayed = displayed
        self._enabled = enabled
        self._id = elem_id
        self.text = text
        self._selected = selected
        self._for = for_attr
        self.clicks = 0

    def get_attribute(self, name):
        return {"class": self._classes, "id": self._id,
                "for": self._for or "", "aria-disabled": "",
                "value": self.text}.get(name, "")

    def is_displayed(self):
        return self._displayed

    def is_enabled(self):
        return self._enabled

    def is_selected(self):
        return self._selected

    def click(self):
        self.clicks += 1
        self._selected = True

    def find_elements(self, by, selector):
        return []


class _Send(_Element):
    """A send button that enables itself after a couple of polls, like Naukri's."""

    def __init__(self, enable_after=2):
        super().__init__(classes="sendMsg disabled")
        self.polls = 0
        self.enable_after = enable_after

    def get_attribute(self, name):
        if name == "class":
            self.polls += 1
            if self.polls > self.enable_after:
                self._classes = "sendMsg"
        return super().get_attribute(name)


class _Driver:
    def __init__(self, send):
        self._send = send

    def find_elements(self, by, selector):
        return [self._send] if "sendMsg" in selector else []


def test_send_waits_for_the_button_to_enable():
    """The 7 October failure: checked once, found disabled, gave up."""
    send = _Send(enable_after=2)
    assert chatbot.click_send(_Driver(send), wait_s=3.0) is True
    assert send.clicks == 1


def test_send_gives_up_on_a_button_that_never_enables():
    """It must still refuse to force a genuinely disabled control."""
    send = _Element(classes="sendMsg disabled")
    assert chatbot.click_send(_Driver(send), wait_s=0.5) is False
    assert send.clicks == 0


def test_send_clicks_an_already_enabled_button_immediately():
    send = _Element(classes="sendMsg")
    assert chatbot.click_send(_Driver(send), wait_s=5.0) is True
    assert send.clicks == 1


# ---------- hidden, label-driven checkboxes ----------

class _Drawer:
    """Naukri's multi-select: hidden inputs, visible labels keyed by `for`."""

    def __init__(self, values, inputs_displayed=False):
        self.inputs = [
            _Element(elem_id=v, displayed=inputs_displayed, text=v) for v in values
        ]
        self.labels = [
            _Element(for_attr=v, displayed=True, text=v) for v in values
        ]

    def find_elements(self, by, selector):
        if "checkbox" in selector:
            return list(self.inputs)
        if selector.startswith("label[for="):
            wanted = selector.split("'")[1]
            return [l for l in self.labels if l.get_attribute("for") == wanted]
        return []


def test_hidden_checkboxes_are_still_selectable():
    """The city question: inputs never displayed, so a visibility filter saw none."""
    drawer = _Drawer(["Bengaluru, Karnataka", "Pune, Maharashtra"])
    usable = chatbot._selectable_checkboxes(drawer)
    assert len(usable) == 2, "hidden-but-labelled checkboxes were discarded"


def test_the_label_is_clicked_when_the_input_is_hidden():
    drawer = _Drawer(["Bengaluru, Karnataka"])
    target = chatbot._checkbox_target(drawer, drawer.inputs[0])
    assert target is drawer.labels[0], "clicking a hidden input does nothing"


def test_a_visible_checkbox_is_clicked_directly():
    drawer = _Drawer(["Yes"], inputs_displayed=True)
    drawer.labels = []
    target = chatbot._checkbox_target(drawer, drawer.inputs[0])
    assert target is drawer.inputs[0]


def test_checkboxes_with_neither_a_label_nor_visibility_are_skipped():
    drawer = _Drawer(["Ghost"])
    drawer.labels = []
    assert chatbot._selectable_checkboxes(drawer) == []
