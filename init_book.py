from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from project import DEFAULT_BOOKS, book_directory


def create_book(
    slug: str,
    title: str,
    *,
    books_dir: Path = DEFAULT_BOOKS,
    original_title: str = "",
    author: str = "",
    source_language: str = "zh-Hans",
    target_language: str = "ru",
    reference_url: str | None = None,
    reference_path: str | None = None,
) -> Path:
    if not title.strip():
        raise ValueError("Название книги не может быть пустым")
    if reference_url and reference_path:
        raise ValueError("Укажи ссылку или локальный путь к референсу")
    directory = book_directory(slug, books_dir)
    directory.mkdir(parents=True, exist_ok=False)
    profile = {
        "title": title.strip(),
        "originalTitle": original_title,
        "author": author,
        "sourceLanguage": source_language,
        "targetLanguage": target_language,
        "original": {},
        "reference": ({"url": reference_url} if reference_url else
                      {"path": reference_path} if reference_path else {}),
        "chapterSources": {},
    }
    (directory / "book.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (directory / "chapters").mkdir()
    (directory / "glossary.md").write_text(
        "# Глоссарий\n\n| Оригинал | Перевод | Источник / статус |\n| --- | --- | --- |\n",
        encoding="utf-8",
    )
    return directory


def main() -> None:
    cli = argparse.ArgumentParser(description="Создать локальную книгу с профилем и глоссарием")
    cli.add_argument("slug", help="имя каталога книги, например my-novel")
    cli.add_argument("--title", required=True, help="название на языке перевода")
    cli.add_argument("--books-dir", type=Path, default=DEFAULT_BOOKS)
    cli.add_argument("--original-title", default="")
    cli.add_argument("--author", default="")
    cli.add_argument("--source-language", default="zh-Hans")
    cli.add_argument("--target-language", default="ru")
    reference = cli.add_mutually_exclusive_group()
    reference.add_argument("--reference-url")
    reference.add_argument("--reference-path", help="путь относительно каталога будущего book.json")
    args = cli.parse_args()
    try:
        print(create_book(
            args.slug, args.title, books_dir=args.books_dir,
            original_title=args.original_title, author=args.author,
            source_language=args.source_language, target_language=args.target_language,
            reference_url=args.reference_url, reference_path=args.reference_path,
        ))
    except (OSError, ValueError) as error:
        sys.exit(f"Книга не создана. {error}")


if __name__ == "__main__":
    main()
