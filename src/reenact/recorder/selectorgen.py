"""Build SelectorBundle and intent strings from raw element data."""

from __future__ import annotations

from typing import Any

from reenact.schema import RoleSelector, SelectorBundle

# Maps ARIA roles to human-readable labels used in intent strings.
_ROLE_LABELS: dict[str, str] = {
    "button": "button",
    "link": "link",
    "textbox": "text field",
    "combobox": "dropdown",
    "checkbox": "checkbox",
    "radio": "radio button",
    "slider": "slider",
    "spinbutton": "number field",
    "img": "image",
    "heading": "heading",
    "navigation": "navigation",
    "form": "form",
    "listitem": "list item",
}


def _str(d: dict[str, Any], key: str) -> str | None:
    """Return a non-empty string value or None."""
    v = d.get(key)
    return str(v).strip() if v and str(v).strip() else None


def build_selector_bundle(el: dict[str, Any]) -> SelectorBundle:
    """Convert a raw element dict (from injected.js) into a SelectorBundle."""
    testid = _str(el, "dataTestId")

    # Role + accessible name — always compute, never leave bundle css/xpath-only.
    role_str = _str(el, "role") or _str(el, "implicitRole")
    accessible_name = _str(el, "accessibleName")
    role: RoleSelector | None = None
    if role_str:
        role = RoleSelector(role=role_str, name=accessible_name or "")

    # Text selector — only meaningful for buttons and links.
    text: str | None = None
    implicit = _str(el, "implicitRole")
    if implicit in ("button", "link"):
        text = _str(el, "accessibleName") or _str(el, "textContent")

    css = _build_css(el)
    xpath = _build_xpath(el)

    return SelectorBundle(
        testid=testid,
        role=role,
        text=text,
        css=css,
        xpath=xpath,
    )


def build_intent(action: str, el: dict[str, Any]) -> str:
    """Generate a plain-English intent string from an action + element."""
    role_str = _str(el, "role") or _str(el, "implicitRole") or ""
    label = _ROLE_LABELS.get(role_str, role_str or "element")
    name = _str(el, "accessibleName") or _str(el, "placeholder") or _str(el, "name") or ""

    if action == "navigate":
        url = _str(el, "url") or ""
        return f"Navigate to {url}"

    if action == "click":
        if name:
            return f"Click the '{name}' {label}"
        return f"Click the {label}"

    if action == "input":
        if name:
            return f"Type into the '{name}' {label}"
        return f"Type into the {label}"

    if action == "select":
        value = _str(el, "value") or ""
        if name:
            return f"Select '{value}' from the '{name}' {label}"
        return f"Select '{value}' from the {label}"

    if action == "key":
        key = _str(el, "key") or ""
        if name:
            return f"Press {key} on the '{name}' {label}"
        return f"Press {key}"

    if action == "hover":
        if name:
            return f"Hover over the '{name}' {label}"
        return f"Hover over the {label}"

    if action == "extract":
        value = _str(el, "value") or ""
        snippet = (value[:40] + "…") if len(value) > 40 else value
        suffix = f" ('{snippet}')" if snippet else ""
        if name:
            return f"Extract text from the '{name}' {label}{suffix}"
        return f"Extract text from the {label}{suffix}"

    if name:
        return f"{action.capitalize()} the '{name}' {label}"
    return f"{action.capitalize()} the {label}"


# ── Private helpers ───────────────────────────────────────────────────────────


def _build_css(el: dict[str, Any]) -> str | None:
    tag = (_str(el, "tagName") or "").lower()
    if not tag:
        return None

    el_id = _str(el, "id")
    if el_id:
        # Escape special CSS chars in ID
        safe_id = el_id.replace(":", r"\:").replace(".", r"\.")
        return f"#{safe_id}"

    testid = _str(el, "dataTestId")
    if testid:
        return f'[data-testid="{testid}"]'

    parts: list[str] = [tag]
    el_type = _str(el, "type")
    if el_type:
        parts.append(f'[type="{el_type}"]')
    name = _str(el, "name")
    if name:
        parts.append(f'[name="{name}"]')

    selector = "".join(parts)
    # A bare tag name (e.g. "a", "div") matches too many elements — drop it.
    return selector if selector != tag else None


def _build_xpath(el: dict[str, Any]) -> str | None:
    tag = (_str(el, "tagName") or "").lower()
    if not tag:
        return None

    el_id = _str(el, "id")
    if el_id:
        return f'//{tag}[@id="{el_id}"]'

    testid = _str(el, "dataTestId")
    if testid:
        return f'//{tag}[@data-testid="{testid}"]'

    accessible_name = _str(el, "accessibleName")
    if accessible_name:
        safe = accessible_name.replace('"', '\\"')
        return f'//{tag}[normalize-space()="{safe}"]'

    name = _str(el, "name")
    if name:
        return f'//{tag}[@name="{name}"]'

    return f"//{tag}"
