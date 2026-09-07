"""Rule modules. Importing this package populates the global registry."""

from __future__ import annotations

from . import artifacts, grammar, markup, register, style  # noqa: F401

__all__ = ["artifacts", "grammar", "markup", "register", "style"]
