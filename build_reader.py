from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from project import DEFAULT_BOOKS, ROOT, atomic_write, book_directory, load_profile


def load_chapter(path: Path) -> dict:
    if not re.fullmatch(r"[0-9]+", path.stem) or int(path.stem) < 1:
        raise ValueError(f"{path}: имя файла должно быть положительным номером главы")
    heading, _, body = path.read_text(encoding="utf-8").strip().partition("\n")
    title = heading.removeprefix("# ").strip()
    paragraphs = re.split(r"\n[ \t]*\n", body.strip())
    paragraphs = [paragraph.strip() for paragraph in paragraphs if paragraph.strip()]
    if not heading.startswith("# ") or not title or not any(p != "* * *" for p in paragraphs):
        raise ValueError(f"{path}: нужны заголовок «# Название» и текст главы")
    return {
        "number": int(path.stem),
        "title": title,
        "paragraphs": paragraphs,
    }


def load_annotations(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    notes = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(notes, list):
        raise ValueError(f"{path}: аннотации должны быть массивом")
    for note in notes:
        if (not isinstance(note, dict) or not isinstance(note.get("title"), str)
                or note.get("kind") not in ("person", "reference")
                or not isinstance(note.get("forms"), list) or not note["forms"]
                or any(not isinstance(form, str) or not form.strip() for form in note["forms"])
                or not isinstance(note.get("senses"), list) or not note["senses"]):
            raise ValueError(f"{path}: каждой карточке нужны title, kind, forms и senses")
        for sense in note["senses"]:
            if (not isinstance(sense, dict) or not isinstance(sense.get("original"), str)
                    or not isinstance(sense.get("body"), str)):
                raise ValueError(f"{path}: каждому значению карточки нужны original и body")
            if "reading" in sense and not isinstance(sense["reading"], str):
                raise ValueError(f"{path}: reading должен быть строкой")
            if "recap" in sense:
                recap = sense["recap"]
                if (not isinstance(recap, dict) or type(recap.get("chapter")) is not int
                        or recap["chapter"] < 1 or not isinstance(recap.get("text"), str)):
                    raise ValueError(f"{path}: recap содержит положительный chapter и строку text")
            if "passages" in sense:
                passages = sense["passages"]
                if (not isinstance(passages, dict) or any(
                    not re.fullmatch(r"[1-9][0-9]*", number)
                    or not isinstance(quotes, list)
                    or any(not isinstance(quote, str) or not quote for quote in quotes)
                    for number, quotes in passages.items()
                )):
                    raise ValueError(f"{path}: passages сопоставляет номера глав с массивами цитат")
            if "source" in sense:
                source = sense["source"]
                if (not isinstance(source, dict) or not isinstance(source.get("url"), str)
                        or not isinstance(source.get("label"), str)):
                    raise ValueError(f"{path}: source содержит строки url и label")
    return notes


def load_books(books_dir: Path = DEFAULT_BOOKS) -> list[dict]:
    if not books_dir.is_dir():
        raise ValueError(f"{books_dir}: каталог книг не найден; создай книгу или укажи --books-dir examples")
    books = []
    for profile in sorted(books_dir.glob("*/book.json")):
        slug = profile.parent.name
        book_directory(slug, books_dir)
        book = load_profile(profile)
        chapters = [load_chapter(path) for path in (profile.parent / "chapters").glob("*.md")]
        chapters.sort(key=lambda chapter: chapter["number"])
        if len({chapter["number"] for chapter in chapters}) != len(chapters):
            raise ValueError(f"{profile}: номера глав повторяются")
        if chapters:
            notes = load_annotations(profile.parent / "annotations.json")
            books.append({
                "slug": slug,
                "title": book["title"],
                "originalTitle": book.get("originalTitle", ""),
                "sourceLanguage": book.get("sourceLanguage", ""),
                "targetLanguage": book.get("targetLanguage", ""),
                "annotations": notes,
                "chapters": chapters,
            })
    return books


def build(books_dir: Path = DEFAULT_BOOKS, output: Path = ROOT / "dist" / "index.html") -> Path:
    source = ROOT / "reader"
    template = (source / "template.html").read_text(encoding="utf-8")
    data = json.dumps(load_books(books_dir), ensure_ascii=False).replace("<", "\\u003c")
    html = (
        template
        .replace("/* READER_STYLES */", (source / "reader.css").read_text(encoding="utf-8"))
        .replace("/* READER_SCRIPT */", (source / "reader.js").read_text(encoding="utf-8"))
        .replace("<!-- READER_DATA -->", data)
    )
    atomic_write(output, html)
    return output


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Собрать книги в HTML-читалку, работающую без сервера")
    cli.add_argument("--books-dir", type=Path, default=DEFAULT_BOOKS)
    cli.add_argument("--output", type=Path, default=ROOT / "dist" / "index.html")
    args = cli.parse_args()
    try:
        print(build(args.books_dir, args.output))
    except (OSError, ValueError) as error:
        sys.exit(f"Читалка не обновлена. {error}")
