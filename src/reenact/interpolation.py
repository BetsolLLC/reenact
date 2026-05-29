"""Variable interpolation for workflow values.

Substitutes {{var_name}} placeholders with runtime values.
Secret values are masked in any string representation.
"""

from __future__ import annotations

import os
import re

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


class InterpolationError(Exception):
    pass


def interpolate(template: str, variables: dict[str, str]) -> str:
    """Replace all {{name}} placeholders. Raises InterpolationError for missing vars."""

    def _sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in variables:
            raise InterpolationError(
                f"Variable '{{{{name}}}}' referenced in workflow but no value provided. "
                f"Pass --var {name}=<value> or set REENACT_VAR_{name}."
            )
        return variables[name]

    return _PLACEHOLDER.sub(_sub, template)


def has_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER.search(value))


def placeholders_in(value: str) -> list[str]:
    return _PLACEHOLDER.findall(value)


def collect_env_vars(variable_names: set[str]) -> dict[str, str]:
    """Read REENACT_VAR_<name> from environment for each declared variable."""
    found: dict[str, str] = {}
    for name in variable_names:
        env_key = f"REENACT_VAR_{name}"
        val = os.environ.get(env_key)
        if val is not None:
            found[name] = val
    return found


def mask_secrets(text: str, secret_values: set[str]) -> str:
    """Replace any secret value with *** in terminal output."""
    for secret in secret_values:
        if secret:
            text = text.replace(secret, "***")
    return text
