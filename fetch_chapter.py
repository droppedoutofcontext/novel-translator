from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
from urllib.request import HTTPRedirectHandler, Request, build_opener

from project import DEFAULT_BOOKS, atomic_write, book_directory, load_profile
from source_adapters import SourceConfig, catalogue_sources, extract_chapter


MAX_HTML_BYTES = 4 * 1024 * 1024


class ChapterRedirectHandler(HTTPRedirectHandler):
    def __init__(self, config: SourceConfig) -> None:
        super().__init__()
        self.config = config

    def redirect_request(self, request, response, code, message, headers, new_url):
        self.config.check_url(new_url)
        return super().redirect_request(request, response, code, message, headers, new_url)


def download(url: str, config: SourceConfig) -> str:
    config.check_url(url)
    request = Request(url, headers={"User-Agent": "novel-translator/1.0", "Accept": "text/html"})
    with build_opener(ChapterRedirectHandler(config)).open(request, timeout=20) as response:
        if response.headers.get_content_type() != "text/html":
            raise ValueError("Источник вернул ответ в формате, отличном от HTML")
        data = response.read(MAX_HTML_BYTES + 1)
        if len(data) > MAX_HTML_BYTES:
            raise ValueError("HTML страницы превышает 4 МБ")
        return data.decode(response.headers.get_content_charset() or "utf-8-sig")


def parse_chapter_range(value: str) -> range:
    match = re.fullmatch(r"([0-9]+)(?:-([0-9]+))?", value)
    if not match:
        raise argparse.ArgumentTypeError("Укажи номер главы или диапазон через дефис, например 1-10")
    first, last = int(match[1]), int(match[2] or match[1])
    if first < 1 or last < first:
        raise argparse.ArgumentTypeError("Номера глав должны быть положительными, в порядке возрастания")
    return range(first, last + 1)


def load_sources(profile: dict, directory: Path, chapters: range, config: SourceConfig, *, local: bool = False) -> list[tuple[int, str, str]]:
    chapter_sources = {number: dict(source) for number, source in profile.get("chapterSources", {}).items()}
    missing = {str(number) for number in chapters if not chapter_sources.get(str(number), {}).get("url")}
    catalogue = profile.get("original", {}).get("catalogue")
    if missing and catalogue and not local:
        if not isinstance(catalogue.get("path"), str) or not isinstance(catalogue.get("url"), str):
            raise ValueError("Для original.catalogue нужны path к сохранённому HTML и базовый url")
        html = (directory / catalogue["path"]).read_text(encoding="utf-8-sig")
        for number, source in catalogue_sources(html, catalogue["url"], missing, config).items():
            existing_title = chapter_sources.get(number, {}).get("title", "")
            if existing_title and existing_title != source["title"]:
                raise ValueError(f"Название главы {number} в профиле и оглавлении различается")
            chapter_sources[number] = {**chapter_sources.get(number, {}), **source}
    sources = []
    for number in chapters:
        source = chapter_sources.get(str(number), {})
        url = source.get("url", "")
        if not local:
            if not url:
                raise ValueError(f"В профиле нет ссылки на главу {number}; добавь chapterSources или original.catalogue")
            config.check_url(url)
        sources.append((number, url, source.get("title", "")))
    return sources


def existing_source(path: Path, number: int, title: str, config: SourceConfig) -> bool:
    if not path.exists():
        return False
    heading, _, body = path.read_text(encoding="utf-8-sig").partition("\n")
    try:
        config.heading(heading.strip(), number, title)
        if not body.strip():
            raise ValueError("В файле нет текста главы")
    except ValueError as error:
        raise ValueError(f"Проверь существующий файл {path}. {error}") from error
    return True


def download_range(sources: list[tuple[int, str, str]], directory: Path, config: SourceConfig) -> None:
    for number, url, title in sources:
        path = directory / f"chapter-{number}.txt"
        if existing_source(path, number, title, config):
            print(f"Глава {number} уже есть: {path}", flush=True)
            continue
        atomic_write(path, extract_chapter(download(url, config), number, title, config))
        print(f"Глава {number} сохранена в {path}", flush=True)


def main() -> None:
    cli = argparse.ArgumentParser(description="Извлечь оригиналы глав по профилю книги")
    cli.add_argument("book", help="имя каталога книги")
    cli.add_argument("chapters", type=parse_chapter_range, help="номер главы или диапазон, например 1-10")
    cli.add_argument("--books-dir", type=Path, default=DEFAULT_BOOKS)
    output = cli.add_mutually_exclusive_group()
    output.add_argument("--output", type=Path, help="сохранить одну главу в файл")
    output.add_argument("--output-dir", type=Path, help="сохранить главы отдельными файлами в каталог")
    cli.add_argument("--html", type=Path, help="извлечь одну главу из сохранённой полной HTML-страницы")
    args = cli.parse_args()
    if len(args.chapters) > 1 and (not args.output_dir or args.html):
        cli.error("Для диапазона укажи --output-dir; --html работает с одной главой")
    try:
        directory = book_directory(args.book, args.books_dir)
        profile = load_profile(directory / "book.json")
        config = SourceConfig.from_profile(profile)
        sources = load_sources(profile, directory, args.chapters, config, local=args.html is not None)
        if args.output_dir and not args.html:
            download_range(sources, args.output_dir, config)
            return
        number, url, title = sources[0]
        destination = args.output_dir / f"chapter-{number}.txt" if args.output_dir else args.output
        if destination and existing_source(destination, number, title, config):
            print(f"Глава {number} уже есть: {destination}")
            return
        if args.html:
            if args.html.stat().st_size > MAX_HTML_BYTES:
                raise ValueError("HTML страницы превышает 4 МБ")
            html = args.html.read_text(encoding="utf-8-sig")
        else:
            html = download(url, config)
        chapter = extract_chapter(html, number, title, config)
        if destination:
            atomic_write(destination, chapter)
            print(f"Глава {number} сохранена в {destination}")
        else:
            sys.stdout.write(chapter)
    except (OSError, ValueError, LookupError) as error:
        sys.exit(f"Оригинал не получен. {error}")


if __name__ == "__main__":
    main()
