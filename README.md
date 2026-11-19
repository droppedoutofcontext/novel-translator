# Novel Translator

Перевод веб-новелл через Claude Code или Codex с референсом, глоссарием и локальной читалкой.

Читалка запоминает место чтения, поддерживает темы, размер шрифта и карточки персонажей. Каждый персонаж или термин подсвечивается один раз за главу. Запас переводов пополняется по мере чтения.

## Демо

```sh
git clone https://github.com/droppedoutofcontext/novel-translator.git
cd novel-translator
python3 build_reader.py --books-dir examples --output dist/demo.html
```

Демо: `dist/demo.html`.

## Своя книга

```sh
python3 init_book.py my-novel --title "Название книги" --reference-url https://example.org/translation
```

Профиль и глоссарий появятся в `books/my-novel/`. По умолчанию перевод идёт с китайского на русский; языки меняются через `--source-language` и `--target-language`. Для локального референса вместо URL используй `--reference-path`.

В папке проекта вызови скилл и добавь запрос:

| Агент | Вызов скилла |
| --- | --- |
| Codex | `$novel-translate` |
| Claude Code | `/novel-translate` |

> Переведи главы 1–3 книги my-novel из файлов в work/my-novel. Следуй референсу и глоссарию. Добавляй главы в читалку по мере готовности.

Если скилл не найден, укажи агенту путь к [SKILL.md](.agents/skills/novel-translate/SKILL.md).

## Запас глав

После настройки источника и глоссария:

```sh
python3 serve_reader.py --agent codex
```

Для Claude Code — `--agent claude`. Используется текущая авторизация CLI. В [читалке](http://127.0.0.1:8765/) выбери текущую главу и задай «Держать глав впереди», например **30**.

Процесс переводит недостающие главы по одной и сразу обновляет оглавление. Пополнение работает, пока процесс запущен. При ошибке или исчерпании лимита оно встаёт на паузу до нажатия «Продолжить». Значение **0** выключает новые переводы.

## Источники и файлы

[Формат профиля, источников и карточек](docs/book-format.md). Оригиналы можно брать из локальных TXT/HTML или получать со статического сайта через настроенный адаптер:

```sh
python3 fetch_chapter.py my-novel 1-10 --output-dir work/my-novel
```

Готовые переводы хранятся в `books/<slug>/chapters/<номер>.md`. Для сборки офлайн-читалки:

```sh
python3 build_reader.py
```

Результат — `dist/index.html`. Личные книги, исходники, прогресс и готовые читалки исключены из Git.

## Разработка

Python 3.10+, Node.js 18+. Без внешних зависимостей.

```sh
python3 -m unittest discover -s tests -v
node --test tests/reader.test.cjs
```

В тестах агенты имитируются, запросов к моделям нет.
