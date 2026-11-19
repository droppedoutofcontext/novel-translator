from __future__ import annotations

import argparse
import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_reader import build, load_books
from fetch_chapter import ChapterRedirectHandler, download_range, load_sources, parse_chapter_range
from init_book import create_book
from project import ROOT, load_profile
from source_adapters import SourceConfig, catalogue_sources, extract_chapter


EXAMPLE = ROOT / "examples" / "lighthouse"


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile(EXAMPLE / "book.json")
        self.config = SourceConfig.from_profile(self.profile)
        self.html = (EXAMPLE / "sources" / "chapter-1.html").read_text(encoding="utf-8")

    def test_extracts_only_chapter_and_preserves_inline_text_and_line_breaks(self):
        html = '<h1>Chapter 3: A &amp; B</h1><nav>Advertisement</nav><article id="chapter"><p>Hello <b>Mara</b>.<br>Good night.<script>bad()</script></p></article>'
        self.assertEqual(extract_chapter(html, 3, "A & B", self.config), "Chapter 3: A & B\n\nHello Mara.\nGood night.\n")

    def test_rejects_wrong_number_title_or_truncated_container(self):
        for html, number, title in ((self.html, 2, ""), (self.html, 1, "Wrong"),
                                     (self.html.replace("</article>", ""), 1, ""),
                                     (self.html.replace("</h1>", ""), 1, "")):
            with self.subTest(number=number, title=title), self.assertRaises(ValueError):
                extract_chapter(html, number, title, self.config)

    def test_rejects_ambiguous_title_or_missing_paragraphs(self):
        for html in (self.html + '<h1>Chapter 1: Other</h1>', '<h1>Chapter 1: Empty</h1><div id="chapter"></div>'):
            with self.subTest(html=html), self.assertRaises(ValueError):
                extract_chapter(html, 1, "", self.config)

    def test_heading_does_not_split_a_number_to_invent_a_title(self):
        with self.assertRaises(ValueError):
            self.config.heading("Chapter 12")

    def test_mangguo_compatibility_without_explicit_adapter(self):
        profile = {"chapterSources": {"12": {"url": "https://www.mangguoshufang.com/1/2/read/3.html"}}}
        config = SourceConfig.from_profile(profile)
        html = '<h3 class="j_chapterName">第12章 灯塔</h3><div class="j_readContent"><div><span class="content-wrap">灯亮了。<br>船回来了。</span></div></div>'
        self.assertEqual(config.adapter, "mangguo")
        config.check_url(profile["chapterSources"]["12"]["url"])
        self.assertEqual(extract_chapter(html, 12, "灯塔", config), "第12章 灯塔\n\n灯亮了。\n船回来了。\n")

    def test_catalogue_uses_relative_links_and_rejects_conflicts(self):
        html = (EXAMPLE / "sources" / "catalogue.html").read_text()
        sources = catalogue_sources(html, "https://example.org/lighthouse/", {"2"}, self.config)
        self.assertEqual(sources["2"]["url"], "https://example.org/lighthouse/2.html")
        html += '<a href="other.html">Chapter 2: Something else</a>'
        with self.assertRaises(ValueError):
            catalogue_sources(html, "https://example.org/lighthouse/", {"2"}, self.config)

    def test_resolution_does_not_mutate_profile_and_checks_title_conflicts(self):
        original = deepcopy(self.profile)
        sources = load_sources(self.profile, EXAMPLE, range(1, 3), self.config)
        self.assertEqual([source[0] for source in sources], [1, 2])
        self.assertEqual(self.profile, original)
        self.profile["chapterSources"]["2"] = {"title": "Wrong"}
        with self.assertRaises(ValueError):
            load_sources(self.profile, EXAMPLE, range(1, 3), self.config)

    def test_rejects_redirects_outside_allowed_hosts(self):
        handler = ChapterRedirectHandler(self.config)
        for url in ("http://example.org/1", "https://other.example/1", "https://user@example.org/1", "https://example.org:8443/1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                handler.redirect_request(None, None, 302, "Found", {}, url)

    def test_rejects_unsupported_configuration(self):
        for original in ({"adapter": "unknown"}, {"contentSelector": "article p"},
                         {"headingPattern": "(.*)"}, {"allowedHosts": [None]}):
            with self.subTest(original=original), self.assertRaises(ValueError):
                SourceConfig.from_profile({"original": original})

    def test_resume_fetches_only_missing_chapters_and_keeps_existing_bytes(self):
        sources = load_sources(self.profile, EXAMPLE, range(1, 3), self.config)
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            first = directory / "chapter-1.txt"
            first.write_text("Chapter 1: The Light in the Fog\n\nKeep this exact original.\n")
            original = first.read_bytes()
            with patch("fetch_chapter.download", return_value=(EXAMPLE / "sources/chapter-2.html").read_text()) as download, contextlib.redirect_stdout(io.StringIO()):
                download_range(sources, directory, self.config)
                download_range(sources, directory, self.config)
            self.assertEqual(download.call_count, 1)
            self.assertEqual(first.read_bytes(), original)
            self.assertIn("An Answer from the Sea", (directory / "chapter-2.txt").read_text())

    def test_invalid_existing_file_is_never_overwritten(self):
        sources = load_sources(self.profile, EXAMPLE, range(1, 2), self.config)
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "chapter-1.txt"
            path.write_text("Chapter 2: Wrong\n\nDo not replace.\n")
            with patch("fetch_chapter.download") as download, self.assertRaises(ValueError):
                download_range(sources, path.parent, self.config)
            download.assert_not_called()
            self.assertIn("Do not replace", path.read_text())

    def test_local_cli_works_outside_project_without_source_url(self):
        with TemporaryDirectory() as temporary:
            directory = create_book("test-book", "Книга", books_dir=Path(temporary) / "books")
            output = Path(temporary) / "original.txt"
            result = subprocess.run([
                sys.executable, str(ROOT / "fetch_chapter.py"), "test-book", "1",
                "--books-dir", str(directory.parent), "--html", str(EXAMPLE / "sources/chapter-1.html"),
                "--output", str(output),
            ], cwd=temporary, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Mara lit the lantern", output.read_text())

    def test_ranges(self):
        self.assertEqual(list(parse_chapter_range("3-5")), [3, 4, 5])
        for value in ("0", "3-1", "one", "1,2"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                parse_chapter_range(value)


class LibraryTests(unittest.TestCase):
    def test_creates_book_without_overwriting_existing_library(self):
        with TemporaryDirectory() as temporary:
            books = Path(temporary) / "books"
            directory = create_book("my-book", "Моя книга", books_dir=books, reference_path="reference.txt")
            self.assertTrue((directory / "chapters").is_dir())
            profile = load_profile(directory / "book.json")
            self.assertEqual(profile["reference"], {"path": "reference.txt"})
            before = (directory / "book.json").read_bytes()
            with self.assertRaises(FileExistsError):
                create_book("my-book", "Another", books_dir=books)
            self.assertEqual((directory / "book.json").read_bytes(), before)
            for slug in ("../escape", "Bad-Name", "a/b", ""):
                with self.subTest(slug=slug), self.assertRaises(ValueError):
                    create_book(slug, "Title", books_dir=books)

    def test_build_sorts_chapters_and_escapes_script_termination(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            book = create_book("test-book", "</script><script>injected()</script>", books_dir=root / "books")
            for number in (10, 2):
                (book / "chapters" / f"{number}.md").write_text(f"# Глава {number}\n\nТекст </script> и <button>.\n\n* * *\n\nКонец.\n")
            output = build(root / "books", root / "reader.html")
            html = output.read_text()
            data = re.search(r'<script type="application/json" id="library">(.*?)</script>', html, re.S)[1]
            self.assertNotIn("</script>", data)
            self.assertEqual([c["number"] for c in json.loads(data)[0]["chapters"]], [2, 10])
            self.assertIn("<button>", json.loads(data)[0]["chapters"][0]["paragraphs"][0])

    def test_invalid_chapter_or_annotation_preserves_previous_build(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(EXAMPLE, root / "books/lighthouse")
            output = build(root / "books", root / "reader.html")
            original = output.read_bytes()
            chapter = root / "books/lighthouse/chapters/2.md"
            good = chapter.read_bytes()
            chapter.write_text("# Empty\n\n* * *\n")
            with self.assertRaises(ValueError):
                build(root / "books", output)
            self.assertEqual(output.read_bytes(), original)
            chapter.write_bytes(good)
            (root / "books/lighthouse/annotations.json").write_text('[{"kind": []}]')
            with self.assertRaises(ValueError):
                build(root / "books", output)
            self.assertEqual(output.read_bytes(), original)

    def test_duplicate_numbers_and_missing_books_directory_are_errors(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = create_book("test-book", "Test", books_dir=root)
            for name in ("1.md", "01.md"):
                (directory / "chapters" / name).write_text("# Title\n\nBody\n")
            with self.assertRaises(ValueError):
                load_books(root)
            with self.assertRaises(ValueError):
                load_books(root / "missing")

    def test_empty_library_and_demo_have_no_personal_book_dependency(self):
        with TemporaryDirectory() as temporary:
            self.assertEqual(load_books(Path(temporary)), [])
        books = load_books(ROOT / "examples")
        self.assertEqual([book["slug"] for book in books], ["lighthouse"])
        self.assertEqual([c["number"] for c in books[0]["chapters"]], [1, 2])
        self.assertEqual(books[0]["annotations"][0]["title"], "Мара")


if __name__ == "__main__":
    unittest.main()
