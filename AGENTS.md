# Работа с проектом

Python 3.10+, стандартная библиотека. Читалка — обычные HTML, CSS и JavaScript без сборщика npm.

- `python3 -m unittest discover -s tests -v` проверяет создание книги, источники и сборку.
- `node --test tests/reader.test.cjs` проверяет поведение читалки.
- Для демо: `python3 build_reader.py --books-dir examples --output dist/demo.html`.
- Для личной библиотеки: `python3 build_reader.py`.

`books/`, `work/`, `dist/` содержат личные или сгенерированные данные и не входят в Git. Не добавляй их принудительно. Общие примеры находятся в `examples/` и написаны для проекта. При проверке кода выбирай отдельный файл вывода, чтобы не заменить личную читалку.

Профиль и формат карточек описаны в `docs/book-format.md`. Сохраняй совместимость CLI и профилей существующих книг. Для литературного перевода используй общий скилл `.agents/skills/novel-translate/SKILL.md`. Правь этот основной файл: `.claude/skills/novel-translate` — ссылка на тот же каталог для Claude Code. `CLAUDE.md` подключает правила из этого файла.
