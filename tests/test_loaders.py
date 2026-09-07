# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import json

import pytest

from kolint.cli import main
from kolint.loaders import iter_records, load


def write(tmp_path, name, content, encoding="utf-8"):
    p = tmp_path / name
    p.write_text(content, encoding=encoding)
    return str(p)


# --- record selectors --------------------------------------------------------

def test_iter_records_flat_list():
    data = [{"a": 1}, {"a": 2}]
    assert [r for r, _ in iter_records(data, "[]")] == data


def test_iter_records_nested_with_inherited_scalars():
    data = [
        {"story_name": "NPC_Archivist", "strings": [{"translated": "가"}, {"translated": "나"}]},
        {"story_name": "EP_Scout", "strings": [{"translated": "다"}]},
    ]
    got = list(iter_records(data, "[].strings[]"))
    assert [r["translated"] for r, _ in got] == ["가", "나", "다"]
    assert [inh["story_name"] for _, inh in got] == ["NPC_Archivist", "NPC_Archivist", "EP_Scout"]


def test_iter_records_dict_root():
    data = {"items": [{"target": "가"}]}
    assert [r["target"] for r, _ in iter_records(data, "items[]")] == ["가"]


# --- JSON --------------------------------------------------------------------

GAME_SHAPE = [
    {
        "story_name": "NPC_Archivist",
        "strings": [
            {"original": "He sits.", "translated": "그는 앉는다."},
            {"original": "It is true.", "translated": "그것은 사실이입니다."},
            {"original": "skip", "skipped": True},
        ],
    }
]


def test_json_autodetects_shape_and_group(tmp_path):
    path = write(tmp_path, "loc.json", json.dumps(GAME_SHAPE, ensure_ascii=False))
    doc = load(path)
    assert len(doc.segments) == 2
    assert doc.segments[0].source == "He sits."
    assert doc.segments[0].group == "NPC_Archivist"


def test_json_fix_writes_back(tmp_path):
    path = write(tmp_path, "loc.json", json.dumps(GAME_SHAPE, ensure_ascii=False))
    assert main(["check", path, "--select", "KO004", "--fix", "--format", "quiet"]) == 0
    data = json.loads(open(path, encoding="utf-8").read())
    assert data[0]["strings"][1]["translated"] == "그것은 사실입니다."
    # Untouched records keep their shape, including the skipped one.
    assert data[0]["strings"][2] == {"original": "skip", "skipped": True}


def test_explicit_keys_override_autodetection(tmp_path):
    data = [{"en": "Hello", "ko": "안녕이입니다."}]
    path = write(tmp_path, "x.json", json.dumps(data, ensure_ascii=False))
    doc = load(path, source_key="en", target_key="ko")
    assert doc.segments[0].source == "Hello"
    assert doc.segments[0].target == "안녕이입니다."


# --- JSONL -------------------------------------------------------------------

def test_jsonl_roundtrip(tmp_path):
    lines = [
        json.dumps({"source": "a", "target": "그것은 사실이입니다."}, ensure_ascii=False),
        json.dumps({"source": "b", "target": "정상입니다."}, ensure_ascii=False),
    ]
    path = write(tmp_path, "x.jsonl", "\n".join(lines) + "\n")
    assert main(["check", path, "--select", "KO004", "--fix", "--format", "quiet"]) == 0
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    assert rows[0]["target"] == "그것은 사실입니다."
    assert rows[1]["target"] == "정상입니다."


# --- CSV ---------------------------------------------------------------------

def test_csv_roundtrip(tmp_path):
    path = write(
        tmp_path,
        "x.csv",
        "key,source,target\n" "greet,Hello,안녕이입니다.\n" "bye,Bye,잘 가.\n",
    )
    assert main(["check", path, "--select", "KO004", "--fix", "--format", "quiet"]) == 0
    body = open(path, encoding="utf-8").read()
    assert "안녕입니다." in body
    assert "잘 가." in body


def test_tsv_delimiter(tmp_path):
    path = write(tmp_path, "x.tsv", "source\ttarget\nHello\t안녕하세요.\n")
    doc = load(path)
    assert doc.segments[0].target == "안녕하세요."


# --- PO ----------------------------------------------------------------------

PO = '''msgid ""
msgstr "Content-Type: text/plain; charset=UTF-8\\n"

#: game.c:12
msgid "You got {item}."
msgstr "아이템을 얻었다."

msgid "He sits."
msgstr "그는 앉는다."
'''


def test_po_reads_entries(tmp_path):
    path = write(tmp_path, "ko.po", PO)
    doc = load(path)
    assert [s.source for s in doc.segments] == ["You got {item}.", "He sits."]
    assert doc.writable is False


def test_po_placeholder_check_fires(tmp_path):
    path = write(tmp_path, "ko.po", PO)
    buf = io.StringIO()
    import sys

    old, sys.stdout = sys.stdout, buf
    try:
        rc = main(["check", path, "--select", "KO202", "--no-color"])
    finally:
        sys.stdout = old
    assert rc == 1
    assert "KO202" in buf.getvalue()


def test_po_rejects_fix(tmp_path, capsys):
    path = write(tmp_path, "ko.po", PO.replace("그는 앉는다.", "그것은 사실이입니다."))
    main(["check", path, "--select", "KO004", "--fix", "--format", "quiet"])
    assert "--fix" in capsys.readouterr().err
    assert "그것은 사실이입니다." in open(path, encoding="utf-8").read()


# --- plain text --------------------------------------------------------------

def test_text_file(tmp_path):
    path = write(tmp_path, "x.txt", "그것은 사실이입니다.\n\n정상입니다.\n")
    assert main(["check", path, "--select", "KO004", "--fix", "--format", "quiet"]) == 0
    assert open(path, encoding="utf-8").read() == "그것은 사실입니다.\n\n정상입니다.\n"


# --- BOM ---------------------------------------------------------------------

def test_csv_with_bom(tmp_path):
    path = write(tmp_path, "bom.csv", "source,target\nHello,안녕하세요.\n", encoding="utf-8-sig")
    doc = load(path)
    assert doc.segments and doc.segments[0].source == "Hello"
