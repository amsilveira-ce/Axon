"""
tests/pa/context/test_memory.py

Testes determinísticos do MemoryBank.
Sem LLM, sem filesystem real (usa tmp_path do pytest).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axon.pa.context.memory import MemoryBank, MemoryEntry


# ---------------------------------------------------------------------------
#   set / get
# ---------------------------------------------------------------------------

def test_set_and_get_value():
    m = MemoryBank()
    m.set("preferred_format", "PDF")
    assert m.get("preferred_format") == "PDF"


def test_get_returns_default_when_missing():
    m = MemoryBank()
    assert m.get("nonexistent") is None
    assert m.get("nonexistent", "fallback") == "fallback"


def test_set_overwrites_existing_key():
    m = MemoryBank()
    m.set("format", "PDF")
    m.set("format", "DOCX")
    assert m.get("format") == "DOCX"
    assert len(m.entries) == 1


def test_set_multiple_keys():
    m = MemoryBank()
    m.set("format", "PDF")
    m.set("language", "Portuguese")
    assert m.get("format") == "PDF"
    assert m.get("language") == "Portuguese"
    assert len(m.entries) == 2


def test_set_updates_timestamp_on_overwrite():
    m = MemoryBank()
    m.set("key", "v1")
    t1 = m.entries[0].updated_at
    m.set("key", "v2")
    t2 = m.entries[0].updated_at
    assert t2 >= t1


def test_set_updates_bank_timestamp():
    m = MemoryBank()
    t1 = m.updated_at
    m.set("key", "value")
    assert m.updated_at >= t1


def test_set_preserves_source():
    m = MemoryBank()
    m.set("key", "value", source="learned")
    assert m.entries[0].source == "learned"


def test_set_default_source_is_operator():
    m = MemoryBank()
    m.set("key", "value")
    assert m.entries[0].source == "operator"


def test_set_supports_bool_value():
    m = MemoryBank()
    m.set("patient_data_available", True)
    assert m.get("patient_data_available") is True


def test_set_supports_int_value():
    m = MemoryBank()
    m.set("max_results", 10)
    assert m.get("max_results") == 10


def test_set_supports_list_value():
    m = MemoryBank()
    m.set("allowed_formats", ["PDF", "DOCX"])
    assert m.get("allowed_formats") == ["PDF", "DOCX"]


# ---------------------------------------------------------------------------
#   delete / clear / keys / is_empty
# ---------------------------------------------------------------------------

def test_delete_existing_key():
    m = MemoryBank()
    m.set("key", "value")
    result = m.delete("key")
    assert result is True
    assert m.get("key") is None


def test_delete_nonexistent_key_returns_false():
    m = MemoryBank()
    result = m.delete("nonexistent")
    assert result is False


def test_delete_updates_timestamp():
    m = MemoryBank()
    m.set("key", "value")
    t1 = m.updated_at
    m.delete("key")
    assert m.updated_at >= t1


def test_clear_removes_all_entries():
    m = MemoryBank()
    m.set("a", 1)
    m.set("b", 2)
    m.clear()
    assert m.is_empty()
    assert len(m.entries) == 0


def test_keys_returns_all_keys():
    m = MemoryBank()
    m.set("format", "PDF")
    m.set("language", "PT")
    assert set(m.keys()) == {"format", "language"}


def test_is_empty_true_when_new():
    m = MemoryBank()
    assert m.is_empty() is True


def test_is_empty_false_after_set():
    m = MemoryBank()
    m.set("key", "value")
    assert m.is_empty() is False


def test_is_empty_true_after_clear():
    m = MemoryBank()
    m.set("key", "value")
    m.clear()
    assert m.is_empty() is True


# ---------------------------------------------------------------------------
#   get_summary
# ---------------------------------------------------------------------------

def test_get_summary_formats_correctly():
    m = MemoryBank()
    m.set("preferred_format", "PDF")
    m.set("language", "Portuguese (Brazil)")
    summary = m.get_summary()
    assert "preferred_format: PDF" in summary
    assert "language: Portuguese (Brazil)" in summary


def test_get_summary_each_entry_on_own_line():
    m = MemoryBank()
    m.set("a", "1")
    m.set("b", "2")
    lines = m.get_summary().splitlines()
    assert len(lines) == 2


def test_get_summary_prefixes_with_dash():
    m = MemoryBank()
    m.set("key", "value")
    assert m.get_summary().startswith("- ")


def test_empty_memory_returns_no_memory_message():
    m = MemoryBank()
    summary = m.get_summary()
    assert summary == "No user memory available."


def test_get_summary_after_clear_returns_empty_message():
    m = MemoryBank()
    m.set("key", "value")
    m.clear()
    assert m.get_summary() == "No user memory available."


def test_get_summary_includes_bool_value():
    m = MemoryBank()
    m.set("patient_data_available", True)
    assert "True" in m.get_summary()


# ---------------------------------------------------------------------------
#   persist / load
# ---------------------------------------------------------------------------

def test_persist_creates_file(tmp_path):
    m = MemoryBank()
    m.set("format", "PDF")
    path = tmp_path / "memory_bank.json"
    m.persist(path)
    assert path.exists()


def test_persist_creates_parent_directories(tmp_path):
    m = MemoryBank()
    nested = tmp_path / "pa" / "memory_bank.json"
    m.persist(nested)
    assert nested.exists()


def test_persist_file_contains_valid_json(tmp_path):
    m = MemoryBank()
    m.set("format", "PDF")
    path = tmp_path / "memory_bank.json"
    m.persist(path)
    data = json.loads(path.read_text())
    assert "entries" in data
    assert data["entries"][0]["key"] == "format"


def test_load_returns_same_data(tmp_path):
    m = MemoryBank()
    m.set("format", "PDF")
    m.set("language", "PT")
    path = tmp_path / "memory_bank.json"
    m.persist(path)

    loaded = MemoryBank.load(path)
    assert loaded.get("format") == "PDF"
    assert loaded.get("language") == "PT"
    assert len(loaded.entries) == 2


def test_load_returns_empty_when_file_missing(tmp_path):
    path = tmp_path / "nonexistent.json"
    m = MemoryBank.load(path)
    assert m.is_empty()


def test_load_or_create_alias_works(tmp_path):
    path = tmp_path / "memory_bank.json"
    m = MemoryBank.load_or_create(path)
    assert m.is_empty()


def test_persist_and_reload_roundtrip(tmp_path):
    original = MemoryBank()
    original.set("preferred_format", "PDF")
    original.set("patient_data_available", True)
    original.set("max_results", 10)
    original.set("allowed_formats", ["PDF", "DOCX"])

    path = tmp_path / "memory_bank.json"
    original.persist(path)

    loaded = MemoryBank.load(path)
    assert loaded.get("preferred_format") == "PDF"
    assert loaded.get("patient_data_available") is True
    assert loaded.get("max_results") == 10
    assert loaded.get("allowed_formats") == ["PDF", "DOCX"]


def test_persist_preserves_entry_source(tmp_path):
    m = MemoryBank()
    m.set("key", "value", source="learned")
    path = tmp_path / "memory_bank.json"
    m.persist(path)

    loaded = MemoryBank.load(path)
    assert loaded.entries[0].source == "learned"


def test_version_preserved_on_load(tmp_path):
    m = MemoryBank()
    path = tmp_path / "memory_bank.json"
    m.persist(path)

    loaded = MemoryBank.load(path)
    assert loaded.version == "0.1.0"