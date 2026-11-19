from __future__ import annotations

import argparse
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

from build_reader import build
from project import DEFAULT_BOOKS, ROOT
from translation_buffer import AgentTranslator, BufferManager


class ReaderHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, manager: BufferManager, **kwargs):
        self.manager = manager
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        return

    def _allowed(self, write: bool = False) -> bool:
        port = self.server.server_address[1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if host not in hosts or (origin is not None and origin != f"http://{host}"):
            self._json(403, {"error": "Запрос должен исходить из локальной читалки"})
            return False
        if write and (self.headers.get("X-Reader-Request") != "1" or self.headers.get_content_type() != "application/json"):
            self._json(403, {"error": "Открой настройки в локальной читалке"})
            return False
        return True

    def _json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._allowed():
            return
        address = urlsplit(self.path)
        try:
            if address.path in {"/", "/index.html"}:
                body = self.manager.output.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)
            elif address.path in {"/api/buffer", "/api/book"}:
                slug = parse_qs(address.query).get("book", [""])[0]
                data = self.manager.status(slug) if address.path == "/api/buffer" else self.manager.book(slug)
                self._json(200, data)
            else:
                self._json(404, {"error": "Страница не найдена"})
        except (OSError, ValueError) as error:
            self._json(400, {"error": str(error)})

    def do_POST(self) -> None:
        if not self._allowed(write=True):
            return
        if self.path != "/api/buffer":
            self._json(404, {"error": "Страница не найдена"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("Некорректный размер запроса")
            data = json.loads(self.rfile.read(length))
            if (not isinstance(data, dict) or not isinstance(data.get("book"), str)
                    or type(data.get("resume", False)) is not bool):
                raise ValueError("Некорректный запрос")
            status = self.manager.update(data["book"], data.get("chapter"), data.get("ahead"), data.get("resume", False))
            self._json(200, status)
        except (OSError, ValueError) as error:
            self._json(400, {"error": str(error)})


def create_server(manager: BufferManager, port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), partial(ReaderHandler, manager=manager))


def main() -> None:
    cli = argparse.ArgumentParser(description="Локальная читалка с автоматическим пополнением запаса глав")
    cli.add_argument("--agent", choices=("codex", "claude"), default="codex")
    cli.add_argument("--books-dir", type=Path, default=DEFAULT_BOOKS)
    cli.add_argument("--output", type=Path, default=ROOT / "dist/index.html")
    cli.add_argument("--work-dir", type=Path, default=ROOT / "work")
    cli.add_argument("--port", type=int, default=8765)
    cli.add_argument("--agent-timeout", type=float, default=900, help="максимум секунд на перевод одной главы")
    args = cli.parse_args()
    if not 0 <= args.port <= 65535 or args.agent_timeout <= 0:
        cli.error("Порт: 0–65535; время на главу должно быть положительным")
    try:
        books, output, work = args.books_dir.resolve(), args.output.resolve(), args.work_dir.resolve()
        build(books, output)
        manager = BufferManager(books, output, work, AgentTranslator(args.agent, work, args.agent_timeout))
        with create_server(manager, args.port) as server:
            try:
                manager.start()
                print(f"Читалка: http://127.0.0.1:{server.server_address[1]}/ · агент: {args.agent}", flush=True)
                print("Задай запас в настройках чтения. 0 — пополнение выключено. Ctrl+C — остановить процесс.", flush=True)
                server.serve_forever(poll_interval=0.2)
            except KeyboardInterrupt:
                pass
            finally:
                manager.close()
    except (OSError, ValueError) as error:
        sys.exit(f"Читалка не запущена. {error}")


if __name__ == "__main__":
    main()
