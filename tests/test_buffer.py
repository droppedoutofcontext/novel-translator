from __future__ import annotations

import http.client
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_reader import build
from project import ROOT, load_profile
from serve_reader import create_server
from translation_buffer import AgentTranslator, BufferManager, missing_chapters, read_state, source_paragraphs, validate_translation


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for the translation buffer")


class BufferTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.books = self.root / "books"
        self.directory = self.books / "lighthouse"
        shutil.copytree(ROOT / "examples/lighthouse", self.directory)
        (self.directory / "chapters/2.md").unlink()
        profile = load_profile(self.directory / "book.json")
        profile["chapterSources"]["2"] = {"path": "sources/chapter-2.html", "title": "An Answer from the Sea"}
        profile["chapterSources"]["3"] = {"path": "sources/chapter-3.txt", "title": "One More Evening"}
        (self.directory / "sources/chapter-3.txt").write_text("Chapter 3: One More Evening\n\nThe lantern shone again.\n", encoding="utf-8")
        (self.directory / "book.json").write_text(json.dumps(profile), encoding="utf-8")
        self.output = build(self.books, self.root / "reader.html")
        self.managers = []

    def tearDown(self):
        for manager in self.managers:
            manager.close()
        self.temp.cleanup()

    def manager(self, translator):
        manager = BufferManager(self.books, self.output, self.root / "work", translator)
        self.managers.append(manager)
        return manager

    @staticmethod
    def translate(directory, number, heading, paragraphs, stop):
        return {"status": "translated", "title": f"Глава {number}",
                "paragraphs": ["* * *" if p == "* * *" else "Перевод: " + p for p in paragraphs], "newTerms": []}

    def test_automatically_refills_after_reading_advances_without_retranslating(self):
        calls = []
        def translator(*args):
            calls.append(args[1])
            return self.translate(*args)
        manager = self.manager(translator)
        manager.start()
        manager.update("lighthouse", 1, ahead=1)
        wait_for(lambda: manager.status("lighthouse")["available"] == 1 and manager.active is None)
        self.assertEqual(calls, [2])
        self.assertIn("Глава 2", self.output.read_text())
        manager.update("lighthouse", 1)
        manager.update("lighthouse", 2)
        wait_for(lambda: manager.status("lighthouse")["available"] == 1 and manager.active is None)
        self.assertEqual(calls, [2, 3])
        self.assertEqual(read_state(self.directory)["chapter"], 2)
        self.assertIn("Глава 3", self.output.read_text())

    def test_error_pauses_until_explicit_resume_and_survives_restart(self):
        calls = []
        def failing(*args):
            calls.append(args[1])
            raise ValueError("Лимит исчерпан")
        manager = self.manager(failing)
        manager.start()
        manager.update("lighthouse", 1, ahead=1)
        wait_for(lambda: bool(manager.status("lighthouse")["error"]))
        manager.update("lighthouse", 1)
        self.assertEqual(calls, [2])
        manager.close()
        resumed = self.manager(self.translate)
        resumed.start()
        self.assertEqual(resumed.status("lighthouse")["error"], "Лимит исчерпан")
        self.assertFalse((self.directory / "chapters/2.md").exists())
        resumed.update("lighthouse", 1, resume=True)
        wait_for(lambda: resumed.status("lighthouse")["available"] == 1)

    def test_zero_stops_new_jobs_after_current_chapter(self):
        started, finish = threading.Event(), threading.Event()
        calls = []
        def translator(*args):
            calls.append(args[1])
            started.set()
            finish.wait(timeout=2)
            return self.translate(*args)
        manager = self.manager(translator)
        manager.start()
        manager.update("lighthouse", 1, ahead=2)
        self.assertTrue(started.wait(timeout=2))
        manager.update("lighthouse", 1, ahead=0)
        finish.set()
        wait_for(lambda: manager.active is None)
        self.assertEqual(calls, [2])
        self.assertTrue((self.directory / "chapters/2.md").exists())
        self.assertFalse((self.directory / "chapters/3.md").exists())

    def test_normal_shutdown_does_not_persist_an_error_and_restart_refills(self):
        started = threading.Event()
        def translator(directory, number, heading, paragraphs, stop):
            started.set()
            stop.wait(timeout=2)
            raise ValueError("Остановлен локальный процесс")
        manager = self.manager(translator)
        manager.start()
        manager.update("lighthouse", 1, ahead=1)
        self.assertTrue(started.wait(timeout=2))
        manager.close()
        self.assertEqual(read_state(self.directory)["error"], "")
        restarted = self.manager(self.translate)
        restarted.start()
        wait_for(lambda: restarted.status("lighthouse")["available"] == 1)

    def test_fills_gaps_and_counts_only_contiguous_ready_chapters(self):
        (self.directory / "chapters/3.md").write_text("# Третья\n\nУже готова.\n", encoding="utf-8")
        manager = self.manager(self.translate)
        status = manager.update("lighthouse", 1, ahead=2)
        self.assertEqual(status["available"], 0)
        self.assertEqual(status["missing"], 1)
        self.assertEqual(missing_chapters({"chapter": 1, "ahead": 2}, [1, 3]), [2])
        manager.start()
        wait_for(lambda: manager.status("lighthouse")["available"] == 2)
        self.assertEqual((self.directory / "chapters/3.md").read_text(), "# Третья\n\nУже готова.\n")

    def test_no_parallel_jobs_and_does_not_overwrite_manual_translation(self):
        started, finish = threading.Event(), threading.Event()
        calls = []
        def translator(*args):
            calls.append(args[1])
            started.set()
            finish.wait(timeout=2)
            return self.translate(*args)
        manager = self.manager(translator)
        manager.start()
        manager.update("lighthouse", 1, ahead=1)
        self.assertTrue(started.wait(timeout=2))
        for _ in range(5):
            manager.update("lighthouse", 1)
        path = self.directory / "chapters/2.md"
        path.write_text("# Ручной перевод\n\nСохранить этот текст.\n", encoding="utf-8")
        finish.set()
        wait_for(lambda: manager.active is None)
        self.assertEqual(calls, [2])
        self.assertIn("Сохранить этот текст", path.read_text())

    def test_rejects_incomplete_or_unavailable_translation_without_publishing(self):
        before = self.output.read_bytes()
        def translator(*args):
            return {"status": "translated", "title": "Обрезано", "paragraphs": ["Кусочек"], "newTerms": []}
        manager = self.manager(translator)
        manager.start()
        manager.update("lighthouse", 1, ahead=1)
        wait_for(lambda: bool(manager.status("lighthouse")["error"]))
        self.assertFalse((self.directory / "chapters/2.md").exists())
        self.assertEqual(self.output.read_bytes(), before)
        with self.assertRaises(ValueError):
            validate_translation({"status": "unavailable", "title": "", "paragraphs": [], "newTerms": []}, ["Original"])

    def test_scene_breaks_and_new_terms_are_preserved(self):
        self.assertEqual(source_paragraphs("Chapter 1: T\n\nA\n\n……\n\n……\n\nB\n"), ["A", "* * *", "B"])
        with self.assertRaises(ValueError):
            validate_translation({"status": "translated", "title": "T", "paragraphs": ["A", "B"], "newTerms": []}, ["A", "* * *"])
        def translator(*args):
            result = self.translate(*args)
            result["newTerms"] = [{"original": "lantern glass", "translation": "стекло фонаря"}]
            return result
        manager = self.manager(translator)
        manager.start()
        manager.update("lighthouse", 1, ahead=1)
        wait_for(lambda: manager.status("lighthouse")["available"] == 1)
        self.assertIn("| lantern glass | стекло фонаря | Рабочая форма", (self.directory / "glossary.md").read_text())

    def test_invalid_settings_do_not_change_state(self):
        manager = self.manager(self.translate)
        manager.update("lighthouse", 1, ahead=0)
        before = (self.directory / "reading.json").read_bytes()
        for ahead in (-1, True, 1.5, 1001):
            with self.subTest(ahead=ahead), self.assertRaises(ValueError):
                manager.update("lighthouse", 1, ahead=ahead)
        with self.assertRaises(ValueError):
            manager.update("lighthouse", 999)
        self.assertEqual((self.directory / "reading.json").read_bytes(), before)

    def test_http_api_updates_settings_and_exposes_only_reader_routes(self):
        manager = self.manager(self.translate)
        with create_server(manager, 0) as server:
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
            thread.start()
            port = server.server_address[1]
            def request(method, path, data=None, headers=None):
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                connection.request(method, path, json.dumps(data) if data is not None else None, headers or {})
                response = connection.getresponse()
                body = response.read()
                connection.close()
                return response.status, body
            try:
                self.assertEqual(request("GET", "/")[0], 200)
                self.assertEqual(request("GET", "/books/lighthouse/book.json")[0], 404)
                status, _ = request("POST", "/api/buffer", {"book": "lighthouse", "chapter": 1, "ahead": 1})
                self.assertEqual(status, 403)
                headers = {"Content-Type": "application/json", "X-Reader-Request": "1", "Origin": "https://other.example"}
                self.assertEqual(request("POST", "/api/buffer", {"book": "lighthouse", "chapter": 1}, headers)[0], 403)
                headers["Origin"] = f"http://127.0.0.1:{port}"
                status, body = request("POST", "/api/buffer", {"book": "lighthouse", "chapter": 1, "ahead": 1}, headers)
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["ahead"], 1)
                self.assertEqual(request("GET", "/api/buffer?book=../escape")[0], 400)
                self.assertEqual(request("GET", "/", headers={"Host": "other.example"})[0], 403)
                manager.start()
                wait_for(lambda: manager.status("lighthouse")["available"] == 1)
                _, body = request("GET", "/api/book?book=lighthouse")
                self.assertEqual([c["number"] for c in json.loads(body)["chapters"]], [1, 2])
            finally:
                server.shutdown()
                thread.join(timeout=2)

    def test_both_agent_adapters_use_structured_output_without_permission_bypass(self):
        expected = {"status": "translated", "title": "Перевод", "paragraphs": ["Абзац"], "newTerms": []}
        for agent in ("codex", "claude"):
            with self.subTest(agent=agent):
                commands = []
                def popen(command, **kwargs):
                    commands.append(command)
                    self.assertIn("originalParagraphs", kwargs["stdin"].read())
                    if agent == "codex":
                        Path(command[command.index("--output-last-message") + 1]).write_text(json.dumps(expected))
                    else:
                        kwargs["stdout"].write(json.dumps({"structured_output": expected}))
                        kwargs["stdout"].flush()
                    class Process:
                        returncode = 0
                        def poll(self):
                            return 0
                    return Process()
                runner = AgentTranslator(agent, self.root / "work")
                with patch("translation_buffer.shutil.which", return_value=agent), patch("translation_buffer.subprocess.Popen", side_effect=popen):
                    self.assertEqual(runner(self.directory, 2, "Chapter 2: Test", ["Original"], threading.Event()), expected)
                self.assertNotIn("--dangerously-skip-permissions", commands[0])
                self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", commands[0])
                if agent == "codex":
                    self.assertIn("read-only", commands[0])
                else:
                    self.assertEqual(commands[0][commands[0].index("--tools") + 1], "")


if __name__ == "__main__":
    unittest.main()
