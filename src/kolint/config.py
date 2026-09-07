"""``kolint.toml`` loading.

Config is optional -- ``kolint check`` works with none. It exists so the
project-specific half (glossary terms, speaker profiles, extra adjective
stems) lives next to the project instead of inside the linter.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:  # Python 3.11+
    import tomllib as _toml

    def _load(fp):
        return _toml.load(fp)

except ImportError:  # pragma: no cover - exercised on 3.9/3.10
    try:
        import tomli as _toml  # type: ignore

        def _load(fp):
            return _toml.load(fp)

    except ImportError:
        _toml = None  # type: ignore

        def _load(fp):
            raise RuntimeError(
                "Reading kolint.toml on Python < 3.11 needs the 'tomli' package: "
                "pip install 'ko-mt-lint[toml]'"
            )


CONFIG_NAMES = ("kolint.toml", ".kolint.toml")


@dataclass
class Config:
    select: Optional[List[str]] = None
    extend_select: List[str] = field(default_factory=list)
    ignore: List[str] = field(default_factory=list)
    exit_level: str = "warning"
    #: ``{"KO006": {"terms": [...]}, ...}``
    rules: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    #: Input shape defaults, overridable per invocation.
    source_key: Optional[str] = None
    target_key: Optional[str] = None
    group_key: Optional[str] = None
    records: Optional[str] = None
    path: Optional[str] = None

    def options_for(self, code: str) -> Dict[str, Any]:
        return self.rules.get(code, {})


def find_config(start: str = ".") -> Optional[str]:
    """Walk up from *start* looking for a config file."""
    here = os.path.abspath(start)
    while True:
        for name in CONFIG_NAMES:
            candidate = os.path.join(here, name)
            if os.path.isfile(candidate):
                return candidate
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent


def load_config(path: Optional[str] = None) -> Config:
    if path is None:
        path = find_config()
    if path is None:
        return Config()
    with open(path, "rb") as fp:
        data = _load(fp)

    root = data.get("kolint", data)
    cfg = Config(path=path)
    cfg.select = list(root["select"]) if "select" in root else None
    cfg.extend_select = list(root.get("extend-select", root.get("extend_select", [])))
    cfg.ignore = list(root.get("ignore", []))
    cfg.exit_level = str(root.get("exit-level", root.get("exit_level", "warning")))
    cfg.source_key = root.get("source-key", root.get("source_key"))
    cfg.target_key = root.get("target-key", root.get("target_key"))
    cfg.group_key = root.get("group-key", root.get("group_key"))
    cfg.records = root.get("records")

    for key, value in root.items():
        if isinstance(value, dict) and key.upper().startswith("KO"):
            cfg.rules[key.upper()] = dict(value)
    return cfg
