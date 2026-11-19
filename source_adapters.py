from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit


MANGO_HOSTS = {"mangguoshufang.com", "www.mangguoshufang.com"}
CHINESE_HEADING = r"第\s*(?P<number>[0-9]+)\s*章\s*(?P<title>.+)"
ENGLISH_HEADING = r"Chapter\s+(?P<number>[0-9]+)\b\s*[:.\-–—]?\s*(?P<title>.+)"
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
IGNORED_TAGS = {"script", "style", "noscript", "template"}


@dataclass(frozen=True)
class SourceConfig:
    adapter: str
    allowed_hosts: frozenset[str]
    title_selector: str
    content_selector: str
    paragraph_selector: str
    heading_pattern: re.Pattern

    @classmethod
    def from_profile(cls, profile: dict) -> SourceConfig:
        original = profile.get("original", {})
        catalogue = original.get("catalogue", {})
        if not isinstance(catalogue, dict):
            raise ValueError("original.catalogue должен быть объектом")
        configured_urls = [source.get("url", "") for source in profile.get("chapterSources", {}).values()]
        configured_urls += [original.get("url", ""), catalogue.get("url", "")]
        hosts = {urlsplit(url).hostname for url in configured_urls if isinstance(url, str) and url}
        adapter = original.get("adapter", "mangguo" if hosts & MANGO_HOSTS else "html")
        if adapter not in {"html", "mangguo"}:
            raise ValueError(f"Неизвестный адаптер {adapter!r}; доступны html и mangguo")
        allowed = original.get("allowedHosts", sorted(host for host in hosts if host))
        if (not isinstance(allowed, list)
                or any(not isinstance(host, str) or not re.fullmatch(r"[a-zA-Z0-9.-]+", host) for host in allowed)):
            raise ValueError("original.allowedHosts должен быть массивом имён хостов без схемы и пути")
        defaults = ("h3.j_chapterName", "div.j_readContent", "span.content-wrap", CHINESE_HEADING) if adapter == "mangguo" else (
            "h1", "#chapter", "p", ENGLISH_HEADING,
        )
        selectors = [original.get(key, default) for key, default in zip(
            ("titleSelector", "contentSelector", "paragraphSelector"), defaults[:3],
        )]
        for selector in selectors:
            compile_selector(selector)
        try:
            pattern = re.compile(original.get("headingPattern", defaults[3]), re.IGNORECASE)
        except (TypeError, re.error) as error:
            raise ValueError(f"Неверный original.headingPattern: {error}") from error
        if not {"number", "title"}.issubset(pattern.groupindex):
            raise ValueError("headingPattern должен содержать именованные группы number и title")
        return cls(adapter, frozenset(host.lower() for host in allowed), *selectors, pattern)

    def check_url(self, url: str) -> None:
        address = urlsplit(url)
        try:
            valid_port = address.port in {None, 443}
        except ValueError:
            valid_port = False
        if (address.scheme != "https" or address.hostname not in self.allowed_hosts
                or address.username is not None or address.password is not None or not valid_port):
            raise ValueError(f"Источник должен быть HTTPS-ссылкой на один из original.allowedHosts: {', '.join(sorted(self.allowed_hosts))}")
        if self.adapter == "mangguo" and (
            address.hostname not in MANGO_HOSTS
            or not re.fullmatch(r"/[0-9]+/[0-9]+/read/[0-9]+\.html", address.path)
        ):
            raise ValueError("Адаптер mangguo ожидает ссылку на главу Mangguo Shufang")

    def heading(self, text: str, number: int | None = None, expected_title: str = "") -> tuple[int, str]:
        match = self.heading_pattern.fullmatch(text)
        if not match or not re.fullmatch(r"[0-9]+", match["number"] or ""):
            raise ValueError(f"Заголовок не соответствует headingPattern: {text or 'нет заголовка'}")
        found, title = int(match["number"]), (match["title"] or "").strip()
        if found < 1 or not title:
            raise ValueError("В заголовке нужны положительный номер и название главы")
        if number is not None and found != number:
            raise ValueError(f"Ожидалась глава {number}. Найдено: {text}")
        if expected_title and title != expected_title:
            raise ValueError(f"Ожидалось название «{expected_title}». Найдено: {title}")
        return found, title


def compile_selector(selector: str) -> re.Match:
    match = re.fullmatch(r"(?P<tag>[a-zA-Z][a-zA-Z0-9-]*)?(?:(?P<kind>[.#])(?P<value>[a-zA-Z_][a-zA-Z0-9_-]*))?", selector) if isinstance(selector, str) else None
    if not match or not selector:
        raise ValueError(f"Неподдерживаемый селектор {selector!r}; используй tag, .class, #id, tag.class или tag#id")
    return match


@dataclass
class Element:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    children: list[Element | str] = field(default_factory=list)
    closed: bool = False

    def text(self) -> str:
        if self.tag in IGNORED_TAGS:
            return ""
        if self.tag == "br":
            return "\n"
        return "".join(child if isinstance(child, str) else child.text() for child in self.children)

    def select(self, selector: str) -> list[Element]:
        pattern = compile_selector(selector)
        found = []
        for child in self.children:
            if not isinstance(child, Element) or child.tag in IGNORED_TAGS:
                continue
            tag, kind, value = pattern["tag"], pattern["kind"], pattern["value"]
            if (not tag or child.tag == tag.lower()) and (
                not kind or (kind == "#" and child.attrs.get("id") == value)
                or (kind == "." and value in (child.attrs.get("class") or "").split())
            ):
                found.append(child)
            found.extend(child.select(selector))
        return found


class HtmlDocument(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("document")
        self.stack = [self.root]
        self.feed(html)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element = Element(tag, dict(attrs), closed=tag in VOID_TAGS)
        self.stack[-1].children.append(element)
        if tag not in VOID_TAGS:
            self.stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack[-1].children.append(Element(tag, dict(attrs), closed=True))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack[index].closed = True
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def extract_chapter(html: str, number: int, expected_title: str, config: SourceConfig) -> str:
    document = HtmlDocument(html).root
    titles, bodies = document.select(config.title_selector), document.select(config.content_selector)
    if len(titles) != 1 or len(bodies) != 1:
        raise ValueError("Селекторы должны находить ровно один заголовок и один блок главы")
    title = " ".join(titles[0].text().split())
    config.heading(title, number, expected_title)
    if not titles[0].closed or not bodies[0].closed:
        raise ValueError("На странице нет полного закрытого блока главы и заголовка")
    paragraphs = []
    for element in bodies[0].select(config.paragraph_selector):
        text = "\n".join(" ".join(line.split()) for line in element.text().splitlines()).strip()
        if text:
            paragraphs.append(text)
    if not paragraphs:
        raise ValueError("В блоке главы не найдены абзацы; проверь paragraphSelector")
    return "\n\n".join([title, *paragraphs]) + "\n"


def catalogue_sources(html: str, base_url: str, numbers: set[str], config: SourceConfig) -> dict[str, dict[str, str]]:
    sources: dict[str, dict[str, str]] = {}
    for link in HtmlDocument(html).root.select("a"):
        try:
            number, title = config.heading(" ".join(link.text().split()))
        except ValueError:
            continue
        key = str(number)
        if key not in numbers or not link.attrs.get("href"):
            continue
        url = urljoin(base_url, link.attrs["href"])
        config.check_url(url)
        source = {"title": title, "url": url}
        if key in sources and sources[key] != source:
            raise ValueError(f"В оглавлении разные ссылки или названия для главы {number}")
        sources[key] = source
    return sources
