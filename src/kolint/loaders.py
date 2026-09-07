"""Input adapters.

Translation data arrives in whatever shape the project already uses, so the
linter meets it there: nested JSON, JSONL, CSV/TSV, gettext PO, or one
segment per line. Records are yielded as live mutable dicts wherever the
format allows, which is what makes ``--fix`` write back in place without a
second serialisation pass.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from .core import Segment

#: Field names tried when the caller does not name one explicitly.
SOURCE_KEYS = ("source", "original", "msgid", "src", "en", "english", "source_text")
TARGET_KEYS = ("target", "translated", "msgstr", "translation", "ko", "korean", "text", "value")
GROUP_KEYS = ("group", "story_name", "speaker", "character", "context", "namespace", "file", "key")


class LoaderError(Exception):
    pass


# ---------------------------------------------------------------------------
# Record selector: "" | "[]" | "items[]" | "[].strings[]"
# ---------------------------------------------------------------------------

_PART = re.compile(r"^([^\[\].]*)((?:\[\])*)$")


def _parse_selector(selector: str) -> List[Tuple[str, bool]]:
    if not selector or selector.strip() in ("", "."):
        return [("", True)]
    parts: List[Tuple[str, bool]] = []
    for raw in selector.split("."):
        m = _PART.match(raw.strip())
        if not m:
            raise LoaderError("cannot parse records selector %r" % selector)
        parts.append((m.group(1), bool(m.group(2))))
    return parts


def _scalars(obj: Any) -> Dict[str, str]:
    if not isinstance(obj, dict):
        return {}
    return {k: v for k, v in obj.items() if isinstance(v, (str, int, float, bool))}


def iter_records(
    data: Any, selector: str
) -> Iterator[Tuple[Dict[str, Any], Dict[str, str]]]:
    """Yield ``(record, inherited_scalars)`` pairs described by *selector*."""
    parts = _parse_selector(selector)

    def walk(node: Any, depth: int, inherited: Dict[str, str]):
        if node is None:
            return
        if depth >= len(parts):
            if isinstance(node, dict):
                yield node, inherited
            return
        key, iterate = parts[depth]
        if key:
            if not isinstance(node, dict):
                return
            inherited = dict(inherited)
            inherited.update(_scalars(node))
            node = node.get(key)
            if node is None:
                return
        if iterate:
            if not isinstance(node, list):
                return
            for item in node:
                nxt = dict(inherited)
                nxt.update(_scalars(item))
                if depth + 1 >= len(parts):
                    if isinstance(item, dict):
                        yield item, inherited
                else:
                    for r in walk(item, depth + 1, nxt):
                        yield r
        else:
            for r in walk(node, depth + 1, inherited):
                yield r

    for rec in walk(data, 0, {}):
        yield rec


def _pick(record: Dict[str, Any], inherited: Dict[str, str], explicit: Optional[str],
          candidates: Sequence[str]) -> Optional[str]:
    if explicit:
        if explicit in record:
            value = record[explicit]
        elif explicit in inherited:
            value = inherited[explicit]
        else:
            return None
        return value if isinstance(value, str) else None
    for name in candidates:
        if name in record and isinstance(record[name], str):
            return record[name]
    for name in candidates:
        if name in inherited and isinstance(inherited[name], str):
            return inherited[name]
    return None


def _pick_key(record: Dict[str, Any], explicit: Optional[str],
              candidates: Sequence[str]) -> Optional[str]:
    """Which field name actually holds the target text (needed for --fix)."""
    if explicit:
        return explicit if explicit in record else None
    for name in candidates:
        if name in record and isinstance(record[name], str):
            return name
    return None


class Document:
    """A loaded file plus the machinery to write fixes back into it."""

    def __init__(self, path: str, segments: List[Segment], writable: bool = True):
        self.path = path
        self.segments = segments
        self.writable = writable
        self._setters: List[Any] = []

    def save(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


class _JsonDocument(Document):
    def __init__(self, path, segments, data, setters, jsonl=False):
        Document.__init__(self, path, segments, writable=True)
        self._data = data
        self._setters = setters
        self._jsonl = jsonl

    def save(self) -> None:
        with io.open(self.path, "w", encoding="utf-8", newline="\n") as fp:
            if self._jsonl:
                for row in self._data:
                    fp.write(json.dumps(row, ensure_ascii=False))
                    fp.write("\n")
            else:
                json.dump(self._data, fp, ensure_ascii=False, indent=2)
                fp.write("\n")


class _CsvDocument(Document):
    def __init__(self, path, segments, rows, fieldnames, delimiter, setters):
        Document.__init__(self, path, segments, writable=True)
        self._rows = rows
        self._fieldnames = fieldnames
        self._delimiter = delimiter
        self._setters = setters

    def save(self) -> None:
        with io.open(self.path, "w", encoding="utf-8", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=self._fieldnames, delimiter=self._delimiter)
            writer.writeheader()
            writer.writerows(self._rows)


class _TextDocument(Document):
    def __init__(self, path, segments, lines):
        Document.__init__(self, path, segments, writable=True)
        self._lines = lines

    def save(self) -> None:
        with io.open(self.path, "w", encoding="utf-8", newline="\n") as fp:
            fp.write("\n".join(self._lines))
            fp.write("\n")


class _ReadOnlyDocument(Document):
    def __init__(self, path, segments):
        Document.__init__(self, path, segments, writable=False)

    def save(self) -> None:
        raise LoaderError("%s: --fix is not supported for this format" % self.path)


def _apply_setters(document: Document) -> None:
    """Push each segment's (possibly modified) target back into the record."""
    for seg, setter in zip(document.segments, document._setters):
        setter(seg.target)


def load(
    path: str,
    records: Optional[str] = None,
    source_key: Optional[str] = None,
    target_key: Optional[str] = None,
    group_key: Optional[str] = None,
    delimiter: Optional[str] = None,
) -> Document:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".json",):
        return _load_json(path, records, source_key, target_key, group_key)
    if ext in (".jsonl", ".ndjson"):
        return _load_jsonl(path, source_key, target_key, group_key)
    if ext in (".csv", ".tsv"):
        return _load_csv(path, source_key, target_key, group_key,
                         delimiter or ("\t" if ext == ".tsv" else ","))
    if ext in (".po", ".pot"):
        return _load_po(path)
    return _load_text(path)


def _make_segment(record, inherited, path, index, source_key, target_key, group_key):
    target = _pick(record, inherited, target_key, TARGET_KEYS)
    if target is None:
        return None, None
    field = _pick_key(record, target_key, TARGET_KEYS)
    source = _pick(record, inherited, source_key, SOURCE_KEYS)
    group = _pick(record, inherited, group_key, GROUP_KEYS)
    seg = Segment(
        target=target,
        source=source,
        group=group,
        key=str(record.get("id") or record.get("key") or index),
        location=path,
        line=index + 1,
    )

    def setter(value, _rec=record, _field=field):
        if _field is not None:
            _rec[_field] = value

    return seg, setter


def _load_json(path, records, source_key, target_key, group_key) -> Document:
    with io.open(path, encoding="utf-8") as fp:
        data = json.load(fp)
    selector = records if records is not None else _guess_selector(data)
    segments: List[Segment] = []
    setters: List[Any] = []
    for i, (rec, inherited) in enumerate(iter_records(data, selector)):
        seg, setter = _make_segment(rec, inherited, path, i, source_key, target_key, group_key)
        if seg is not None:
            segments.append(seg)
            setters.append(setter)
    return _JsonDocument(path, segments, data, setters)


def _guess_selector(data: Any) -> str:
    """Find the shallowest path that yields dicts carrying a target field."""
    candidates = ["", "[]"]
    if isinstance(data, list) and data and isinstance(data[0], dict):
        for key, value in data[0].items():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                candidates.append("[].%s[]" % key)
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                candidates.append("%s[]" % key)
    for selector in candidates:
        try:
            for rec, _ in iter_records(data, selector):
                if any(k in rec and isinstance(rec[k], str) for k in TARGET_KEYS):
                    return selector
                break
        except LoaderError:
            continue
    return "[]"


def _load_jsonl(path, source_key, target_key, group_key) -> Document:
    rows: List[Any] = []
    with io.open(path, encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    segments, setters = [], []
    for i, rec in enumerate(rows):
        if not isinstance(rec, dict):
            continue
        seg, setter = _make_segment(rec, {}, path, i, source_key, target_key, group_key)
        if seg is not None:
            segments.append(seg)
            setters.append(setter)
    return _JsonDocument(path, segments, rows, setters, jsonl=True)


def _load_csv(path, source_key, target_key, group_key, delimiter) -> Document:
    with io.open(path, encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp, delimiter=delimiter)
        fieldnames = reader.fieldnames or []
        rows = [dict(r) for r in reader]
    segments, setters = [], []
    for i, rec in enumerate(rows):
        seg, setter = _make_segment(rec, {}, path, i, source_key, target_key, group_key)
        if seg is not None:
            segments.append(seg)
            setters.append(setter)
    return _CsvDocument(path, segments, rows, fieldnames, delimiter, setters)


_PO_ENTRY = re.compile(
    r'^msgid\s+"(?P<id>(?:[^"\\]|\\.)*)"\s*\n(?P<idcont>(?:^"(?:[^"\\]|\\.)*"\s*\n)*)'
    r'^msgstr\s+"(?P<str>(?:[^"\\]|\\.)*)"\s*\n(?P<strcont>(?:^"(?:[^"\\]|\\.)*"\s*\n)*)',
    re.MULTILINE,
)
_PO_CONT = re.compile(r'^"((?:[^"\\]|\\.)*)"', re.MULTILINE)


def _po_unescape(text: str) -> str:
    return (
        text.replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace('\\"', '"')
        .replace("\\\\", "\\")
    )


def _load_po(path) -> Document:
    with io.open(path, encoding="utf-8") as fp:
        body = fp.read()
    if not body.endswith("\n"):
        body += "\n"
    segments = []
    for i, m in enumerate(_PO_ENTRY.finditer(body)):
        msgid = m.group("id") + "".join(_PO_CONT.findall(m.group("idcont")))
        msgstr = m.group("str") + "".join(_PO_CONT.findall(m.group("strcont")))
        if not msgid or not msgstr:
            continue
        line = body.count("\n", 0, m.start()) + 1
        segments.append(
            Segment(
                target=_po_unescape(msgstr),
                source=_po_unescape(msgid),
                group=None,
                key=msgid[:60],
                location=path,
                line=line,
            )
        )
    return _ReadOnlyDocument(path, segments)


def _load_text(path) -> Document:
    with io.open(path, encoding="utf-8") as fp:
        lines = fp.read().split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    segments = [
        Segment(target=line, source=None, group=None, key=str(i + 1), location=path, line=i + 1)
        for i, line in enumerate(lines)
        if line.strip()
    ]
    doc = _TextDocument(path, segments, lines)

    def make_setter(line_index):
        def setter(value, _i=line_index):
            lines[_i] = value

        return setter

    doc._setters = [make_setter(seg.line - 1) for seg in segments]
    return doc


def apply_fixes(document: Document) -> None:
    """Write each segment's current target back into the underlying records."""
    _apply_setters(document)
