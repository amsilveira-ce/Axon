"""
pa/tools/file_reader.py — Lê PDF, TXT, CSV e MD do filesystem.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path


def read_file(path: str, max_chars: int = 8000) -> dict:
    """
    Lê o conteúdo de um arquivo e retorna como string.

    Suporta: .txt, .md, .csv, .pdf

    Args:
        path:      caminho absoluto ou relativo ao arquivo
        max_chars: limite de caracteres retornados (default 8000)

    Returns:
        dict com keys: path, type, content, truncated (bool)

    Raises:
        FileNotFoundError: arquivo não encontrado
        ValueError:        tipo de arquivo não suportado
    """
    p = Path(path).expanduser().resolve()

    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = p.suffix.lower()

    if suffix in (".txt", ".md"):
        content = p.read_text(encoding="utf-8", errors="replace")
        file_type = "markdown" if suffix == ".md" else "text"

    elif suffix == ".csv":
        raw = p.read_text(encoding="utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(raw))
        rows = list(reader)
        lines = []
        if reader.fieldnames:
            lines.append(", ".join(reader.fieldnames))
        for row in rows[:100]:   # limita a 100 linhas no preview
            lines.append(", ".join(str(v) for v in row.values()))
        if len(rows) > 100:
            lines.append(f"... ({len(rows) - 100} more rows)")
        content   = "\n".join(lines)
        file_type = "csv"

    elif suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ImportError(
                "pypdf is required to read PDF files. "
                "Install with: pip install pypdf"
            )
        reader  = PdfReader(str(p))
        pages   = [page.extract_text() or "" for page in reader.pages]
        content   = "\n\n".join(pages)
        file_type = "pdf"

    else:
        raise ValueError(
            f"Unsupported file type: {suffix}. "
            f"Supported: .txt, .md, .csv, .pdf"
        )

    truncated = len(content) > max_chars
    return {
        "path":      str(p),
        "type":      file_type,
        "content":   content[:max_chars],
        "truncated": truncated,
    }