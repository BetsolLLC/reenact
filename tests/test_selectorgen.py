"""Unit tests for selectorgen — no browser required."""

from __future__ import annotations

import pytest

from reenact.recorder.selectorgen import (
    _build_css,
    _build_xpath,
    build_intent,
    build_selector_bundle,
)


@pytest.fixture()
def button_el() -> dict[str, object]:
    return {
        "tagName": "BUTTON",
        "id": None,
        "name": None,
        "type": "submit",
        "value": None,
        "textContent": "Sign in",
        "placeholder": None,
        "ariaLabel": None,
        "ariaLabelledby": None,
        "role": None,
        "dataTestId": None,
        "className": "btn-primary",
        "href": None,
        "implicitRole": "button",
        "accessibleName": "Sign in",
    }


@pytest.fixture()
def input_el() -> dict[str, object]:
    return {
        "tagName": "INPUT",
        "id": "username",
        "name": "username",
        "type": "text",
        "value": "alice",
        "textContent": None,
        "placeholder": "Enter username",
        "ariaLabel": None,
        "ariaLabelledby": None,
        "role": None,
        "dataTestId": "login-username",
        "className": "form-control",
        "href": None,
        "implicitRole": "textbox",
        "accessibleName": "Username",
    }


@pytest.fixture()
def link_el() -> dict[str, object]:
    return {
        "tagName": "A",
        "id": None,
        "name": None,
        "type": None,
        "value": None,
        "textContent": "Home",
        "placeholder": None,
        "ariaLabel": None,
        "ariaLabelledby": None,
        "role": None,
        "dataTestId": None,
        "className": None,
        "href": "https://example.com",
        "implicitRole": "link",
        "accessibleName": "Home",
    }


# ── SelectorBundle construction ───────────────────────────────────────────────


class TestBuildSelectorBundle:
    def test_input_with_testid(self, input_el: dict[str, object]) -> None:
        bundle = build_selector_bundle(input_el)
        assert bundle.testid == "login-username"

    def test_input_role_computed(self, input_el: dict[str, object]) -> None:
        bundle = build_selector_bundle(input_el)
        assert bundle.role is not None
        assert bundle.role.role == "textbox"
        assert bundle.role.name == "Username"

    def test_input_css_uses_id(self, input_el: dict[str, object]) -> None:
        bundle = build_selector_bundle(input_el)
        assert bundle.css == "#username"

    def test_input_xpath_uses_id(self, input_el: dict[str, object]) -> None:
        bundle = build_selector_bundle(input_el)
        assert bundle.xpath == '//input[@id="username"]'

    def test_bundle_has_at_least_two_strategies(self, input_el: dict[str, object]) -> None:
        bundle = build_selector_bundle(input_el)
        strategies = sum(
            1
            for v in [bundle.testid, bundle.role, bundle.text, bundle.css, bundle.xpath]
            if v is not None
        )
        assert strategies >= 2

    def test_button_text_selector_set(self, button_el: dict[str, object]) -> None:
        bundle = build_selector_bundle(button_el)
        assert bundle.text == "Sign in"

    def test_button_role_computed_without_testid(self, button_el: dict[str, object]) -> None:
        bundle = build_selector_bundle(button_el)
        assert bundle.role is not None
        assert bundle.role.role == "button"
        assert bundle.role.name == "Sign in"
        # No testid on this element
        assert bundle.testid is None

    def test_link_text_selector(self, link_el: dict[str, object]) -> None:
        bundle = build_selector_bundle(link_el)
        assert bundle.text == "Home"
        assert bundle.role is not None
        assert bundle.role.role == "link"

    def test_no_testid_still_has_role(self, button_el: dict[str, object]) -> None:
        # The most important invariant: role is always present when role/name known.
        bundle = build_selector_bundle(button_el)
        assert bundle.role is not None, "role must never be None when implicitRole is present"

    def test_has_any_on_full_bundle(self, input_el: dict[str, object]) -> None:
        bundle = build_selector_bundle(input_el)
        assert bundle.has_any() is True

    def test_element_with_no_id_uses_testid_for_css(self) -> None:
        el: dict[str, object] = {
            "tagName": "BUTTON",
            "id": None,
            "name": None,
            "type": "button",
            "dataTestId": "submit-btn",
            "implicitRole": "button",
            "accessibleName": "Submit",
        }
        bundle = build_selector_bundle(el)
        assert bundle.css == '[data-testid="submit-btn"]'
        assert bundle.xpath == '//button[@data-testid="submit-btn"]'


# ── CSS selector ──────────────────────────────────────────────────────────────


class TestBuildCss:
    def test_id_takes_priority(self) -> None:
        assert _build_css({"tagName": "INPUT", "id": "foo"}) == "#foo"

    def test_testid_fallback(self) -> None:
        result = _build_css({"tagName": "BUTTON", "id": None, "dataTestId": "btn"})
        assert result == '[data-testid="btn"]'

    def test_tag_with_type_and_name(self) -> None:
        css = _build_css(
            {"tagName": "INPUT", "id": None, "dataTestId": None, "type": "text", "name": "q"}
        )
        assert css is not None
        assert "input" in css
        assert 'type="text"' in css
        assert 'name="q"' in css

    def test_empty_tag_returns_none(self) -> None:
        assert _build_css({}) is None


# ── XPath selector ────────────────────────────────────────────────────────────


class TestBuildXpath:
    def test_id_takes_priority(self) -> None:
        assert _build_xpath({"tagName": "INPUT", "id": "user"}) == '//input[@id="user"]'

    def test_testid_fallback(self) -> None:
        assert (
            _build_xpath({"tagName": "BUTTON", "id": None, "dataTestId": "go-btn"})
            == '//button[@data-testid="go-btn"]'
        )

    def test_accessible_name_fallback(self) -> None:
        xpath = _build_xpath(
            {"tagName": "BUTTON", "id": None, "dataTestId": None, "accessibleName": "Sign in"}
        )
        assert xpath == '//button[normalize-space()="Sign in"]'

    def test_name_attr_fallback(self) -> None:
        xpath = _build_xpath(
            {
                "tagName": "INPUT",
                "id": None,
                "dataTestId": None,
                "accessibleName": None,
                "name": "email",
            }
        )
        assert xpath == '//input[@name="email"]'

    def test_empty_tag_returns_none(self) -> None:
        assert _build_xpath({}) is None


# ── Intent strings ─────────────────────────────────────────────────────────────


class TestBuildIntent:
    def test_click_button_with_name(self, button_el: dict[str, object]) -> None:
        intent = build_intent("click", button_el)
        assert "Sign in" in intent
        assert "button" in intent

    def test_input_with_name(self, input_el: dict[str, object]) -> None:
        intent = build_intent("input", input_el)
        assert "Username" in intent
        assert "text field" in intent

    def test_navigate(self) -> None:
        intent = build_intent("navigate", {"url": "https://example.com"})
        assert "Navigate" in intent
        assert "example.com" in intent

    def test_select_includes_value(self) -> None:
        el: dict[str, object] = {
            "implicitRole": "combobox",
            "accessibleName": "Country",
            "value": "Canada",
        }
        intent = build_intent("select", el)
        assert "Canada" in intent
        assert "Country" in intent

    def test_key_intent(self) -> None:
        el: dict[str, object] = {"key": "Enter", "implicitRole": "button", "accessibleName": "OK"}
        intent = build_intent("key", el)
        assert "Enter" in intent

    def test_fallback_for_unknown_action(self, button_el: dict[str, object]) -> None:
        intent = build_intent("frobnicate", button_el)
        assert "Sign in" in intent
