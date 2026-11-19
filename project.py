from __future__ import annotations

import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile


ROOT = Path(__file__).resolve().parent
DEFAULT_BOOKS = ROOT / "books"
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def book_directory(slug: str, books_dir: Path = DEFAULT_BOOKS) -> Path:
    if not SLUG_PATTERN.fullmatch(slug):
        raise ValueError("Имя книги: строчные латинские буквы, цифры и одиночные дефисы")
    return books_dir / slug


def load_profile(path: Path) -> dict:
    profile = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(profile, dict):
        raise ValueError(f"{path}: профиль должен быть JSON-объектом")
    if not isinstance(profile.get("title"), str) or not profile["title"].strip():
        raise ValueError(f"{path}: у книги должно быть название")
    for field in ("originalTitle", "author", "sourceLanguage", "targetLanguage"):
        if field in profile and not isinstance(profile[field], str):
            raise ValueError(f"{path}: {field} должен быть строкой")
    for field in ("original", "reference", "chapterSources"):
        if field in profile and not isinstance(profile[field], dict):
            raise ValueError(f"{path}: {field} должен быть объектом")
    for number, source in profile.get("chapterSources", {}).items():
        if not re.fullmatch(r"[1-9][0-9]*", number) or not isinstance(source, dict):
            raise ValueError(f"{path}: chapterSources сопоставляет положительные номера с объектами")
        for field in ("url", "title", "input", "numbering", "path"):
            if field in source and not isinstance(source[field], str):
                raise ValueError(f"{path}: chapterSources.{number}.{field} должен быть строкой")
    return profile


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        try:
            temporary.write(text)
            temporary.close()
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)
