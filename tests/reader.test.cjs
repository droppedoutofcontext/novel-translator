"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");
const script = fs.readFileSync(path.join(root, "reader/reader.js"), "utf8");

class Element {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.dataset = {};
    this.attributes = new Map();
    this.listeners = new Map();
    this.hidden = false;
    this.style = { setProperty() {} };
    const classes = new Set();
    this.classList = {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
      toggle(name, force) {
        const enabled = force ?? !classes.has(name);
        if (enabled) classes.add(name); else classes.delete(name);
        return enabled;
      },
    };
  }
  get textContent() { return this.children.map(child => typeof child === "string" ? child : child.textContent).join(""); }
  set textContent(value) { this.children = [String(value)]; }
  get firstElementChild() { return this.children.find(child => child instanceof Element); }
  append(...children) {
    for (const child of children) {
      if (child?.tag === "fragment") this.append(...child.children);
      else {
        if (child instanceof Element) child.parent = this;
        this.children.push(child);
      }
    }
  }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  add(child) { this.append(child); }
  addEventListener(name, handler) {
    if (!this.listeners.has(name)) this.listeners.set(name, []);
    this.listeners.get(name).push(handler);
  }
  emit(name, event = {}) {
    for (const handler of this.listeners.get(name) || []) handler({ target: this, ...event });
  }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  contains(target) { return this === target || this.children.some(child => child instanceof Element && child.contains(target)); }
  closest(tag) { return this.tag === tag ? this : this.parent?.closest(tag); }
  querySelector(selector) {
    return this.descendants().find(el => selector === '[aria-current="page"]'
      ? el.getAttribute("aria-current") === "page" : el.tag === selector);
  }
  descendants() { return this.children.flatMap(child => child instanceof Element ? [child, ...child.descendants()] : []); }
  focus() { this.focused = true; }
  scrollIntoView() { this.scrolledIntoView = true; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  getBoundingClientRect() { return { left: 0, right: 100, top: 0, bottom: 100 }; }
}

function demoBook() {
  return {
    slug: "lighthouse", title: "Маяк", originalTitle: "The Lighthouse", sourceLanguage: "en", targetLanguage: "ru",
    chapters: [
      { number: 1, title: "Огонь", paragraphs: ["Мара зажгла фонарь.", "* * *", "<script>literal text</script>"] },
      { number: 2, title: "Ответ", paragraphs: ["Мара нашла записку."] },
    ],
    annotations: JSON.parse(fs.readFileSync(path.join(root, "examples/lighthouse/annotations.json"), "utf8")),
  };
}

function start(books = [demoBook()], { mobile = false, storage = new Map(), unavailableStorage = false, protocol = "file:", fetcher, hash = "" } = {}) {
  const ids = new Map();
  for (const match of fs.readFileSync(path.join(root, "reader/template.html"), "utf8").matchAll(/<([a-z]+)[^>]*\bid="([^"]+)"/g)) {
    ids.set(match[2], new Element(match[1]));
  }
  const get = id => { assert.ok(ids.has(id), `Unknown DOM id ${id}`); return ids.get(id); };
  get("theme").append(new Element("span"));
  get("appearance").append(new Element("summary"));
  get("contents").append(get("chapters"));
  get("library").textContent = JSON.stringify(books);
  get("chapter").hidden = true;
  get("buffer-settings").hidden = true;
  const document = new Element("document");
  Object.assign(document, {
    getElementById: get, documentElement: new Element("html"), body: new Element("body"),
    createElement: tag => new Element(tag), createDocumentFragment: () => new Element("fragment"),
  });
  const skip = new Element("a");
  document.querySelector = selector => { assert.equal(selector, ".skip"); return skip; };
  const window = new Element("window");
  const media = new Element("media");
  media.matches = mobile;
  Object.assign(window, {
    matchMedia: () => media, scrollY: 0, innerHeight: 800,
    scrollTo(x, y) { this.scrollY = y; },
  });
  document.documentElement.scrollHeight = 1800;
  const frames = [];
  const timers = [];
  window.setInterval = handler => { timers.push(handler); return timers.length; };
  const location = { hash, protocol };
  vm.runInNewContext(script, {
    document, window, location, history: { scrollRestoration: "auto" },
    fetch: fetcher || (() => { throw Error("Unexpected network request"); }),
    localStorage: {
      getItem(key) { if (unavailableStorage) throw Error("Denied"); return storage.get(key) ?? null; },
      setItem(key, value) { if (unavailableStorage) throw Error("Denied"); storage.set(key, value); },
    },
    requestAnimationFrame(handler) { frames.push(handler); return frames.length; },
    Option: function (text, value) { const option = new Element("option"); option.textContent = text; option.value = value; return option; },
  });
  return {
    get, window, document, media, storage,
    async poll() { for (const timer of timers) await timer(); },
    navigate(hash) { location.hash = hash; window.emit("hashchange"); },
    scroll(y) { window.scrollY = y; window.emit("scroll"); while (frames.length) frames.shift()(); },
  };
}

test("renders paragraphs as text, scene breaks and adjacent chapter links", () => {
  const app = start();
  assert.equal(app.get("chapter-title").textContent, "Огонь");
  assert.equal(app.get("chapters").children.length, 2);
  assert.equal(app.get("chapter-text").children[1].tag, "hr");
  assert.equal(app.get("chapter-text").children[2].textContent, "<script>literal text</script>");
  assert.equal(app.get("chapter-text").children[2].descendants().length, 0);
  assert.equal(app.get("chapter-footer").children[0].href, "#lighthouse/2");
  app.navigate("#lighthouse/2");
  assert.equal(app.get("chapter-title").textContent, "Ответ");
  assert.equal(app.get("chapter-footer").children[0].href, "#lighthouse/1");
  assert.equal(app.get("chapter-footer").children.length, 1);
});

test("remembers theme, bounded font size and per-chapter reading position", () => {
  const app = start();
  app.get("theme").emit("click");
  assert.equal(app.document.documentElement.dataset.theme, "dark");
  for (let i = 0; i < 20; i++) app.get("font-up").emit("click");
  assert.equal(app.get("font-size").textContent, "30");
  assert.equal(app.get("font-up").disabled, true);
  app.scroll(420);
  app.navigate("#lighthouse/2");
  app.navigate("#lighthouse/1");
  assert.equal(app.window.scrollY, 420);
  const reopened = start(undefined, { storage: app.storage });
  assert.equal(reopened.get("font-size").textContent, "30");
  assert.equal(reopened.document.documentElement.dataset.theme, "dark");
  assert.equal(reopened.window.scrollY, 420);
});

test("reader remains usable when local storage is unavailable", () => {
  const app = start(undefined, { unavailableStorage: true });
  app.get("theme").emit("click");
  app.navigate("#lighthouse/2");
  assert.equal(app.get("chapter-title").textContent, "Ответ");
});

test("annotation cards show recaps only after their source chapter", () => {
  const app = start();
  const mark = app.get("chapter-text").descendants().find(el => el.className?.startsWith("annotation"));
  mark.emit("click");
  assert.equal(app.get("note-dialog").open, true);
  assert.equal(app.get("note-title").textContent, "Мара");
  assert.ok(!app.get("note-body").textContent.includes("ответного огня"));
  app.navigate("#lighthouse/2");
  assert.equal(app.get("note-dialog").open, false);
  app.get("chapter-text").descendants().find(el => el.className?.startsWith("annotation")).emit("click");
  assert.ok(app.get("note-body").textContent.includes("ответного огня"));
});

test("a passage resolves ambiguous names while keeping other senses accessible", () => {
  const book = demoBook();
  book.annotations[0].senses[0].passages = { "1": ["Мара зажгла фонарь"] };
  book.annotations[0].senses.push({ original: "Other Mara", body: "Другая героиня." });
  const app = start([book]);
  app.get("chapter-text").descendants().find(el => el.className?.startsWith("annotation")).emit("click");
  assert.equal(app.get("note-body").children[0].tag, "section");
  assert.equal(app.get("note-body").children[1].tag, "details");
  assert.ok(app.get("note-body").children[1].textContent.includes("Другая героиня"));
});

test("repeated names and references stay plain without losing any chapter text", () => {
  const book = demoBook();
  book.annotations.push({ title: "Северная коса", kind: "reference", forms: ["Северная коса", "Северной косы"],
    senses: [{ original: "North Spit", body: "Участок берега." }] });
  book.chapters[0].paragraphs = [
    "Мара у Северной косы. Мара ждёт лодку, а Марат идёт домой.",
    "У Мары горит фонарь. МАРА видит огонь: Северная коса уже близко.",
    "* * *", "Маре принесли записку. Мара улыбается.",
  ];
  const app = start([book]);
  const marks = () => app.get("chapter-text").descendants().filter(el => el.className?.startsWith("annotation"));
  assert.deepEqual(marks().map(el => el.textContent), ["Мара", "Северной косы"]);
  assert.deepEqual(app.get("chapter-text").children.map(el => el.tag === "hr" ? "* * *" : el.textContent), book.chapters[0].paragraphs);
  app.navigate("#lighthouse/2");
  assert.deepEqual(marks().map(el => el.textContent), ["Мара"]);
  app.navigate("#lighthouse/1");
  assert.equal(marks().length, 2);
});

test("different people sharing a name each retain their own first contextual card", () => {
  const book = demoBook();
  book.chapters[0].paragraphs = ["Мара зажгла фонарь. Мара ждёт лодку.", "Мара приехала в гости.", "Мара приехала в гости."];
  book.annotations[0].senses[0].passages = { "1": ["Мара зажгла фонарь", "Мара ждёт лодку"] };
  book.annotations[0].senses.push({ original: "Another Mara", body: "Гостья смотрительницы.", passages: { "1": ["Мара приехала в гости"] } });
  const app = start([book]);
  const marks = app.get("chapter-text").descendants().filter(el => el.className?.startsWith("annotation"));
  assert.equal(marks.length, 2);
  marks[0].emit("click");
  assert.ok(app.get("note-body").children[0].textContent.includes("Смотрительница маяка"));
  app.get("note-close").emit("click");
  marks[1].emit("click");
  assert.ok(app.get("note-body").children[0].textContent.includes("Гостья смотрительницы"));
});

test("mobile contents closes on Escape and resizing restores desktop layout", () => {
  const app = start(undefined, { mobile: true });
  assert.equal(app.get("contents-button").getAttribute("aria-expanded"), "false");
  app.get("contents-button").emit("click");
  assert.ok(app.get("contents").classList.contains("is-open"));
  app.document.emit("keydown", { key: "Escape" });
  assert.ok(!app.get("contents").classList.contains("is-open"));
  app.media.matches = false;
  app.media.emit("change");
  assert.equal(app.get("contents-button").getAttribute("aria-expanded"), "true");
});

test("supports multiple books, unknown links, empty libraries and invalid locales", () => {
  const other = demoBook();
  other.slug = "second";
  other.targetLanguage = "invalid locale";
  const app = start([demoBook(), other]);
  assert.equal(app.get("book-picker").hidden, false);
  app.navigate("#second/2");
  assert.equal(app.get("book-select").value, "second");
  app.navigate("#second/999");
  assert.equal(app.get("chapter-title").textContent, "Ответ");
  const empty = start([]);
  assert.equal(empty.get("empty").hidden, false);
  assert.equal(empty.get("contents").hidden, true);
  assert.equal(empty.get("chapter").hidden, true);
});

const settle = () => new Promise(resolve => setImmediate(resolve));

function bufferServer(book = demoBook(), state = {}) {
  const calls = [];
  const current = { apiVersion: 1, chapter: 1, ahead: 30, error: "", active: null, ...state };
  const status = () => {
    const ready = book.chapters.map(chapter => chapter.number);
    let available = 0;
    while (available < current.ahead && ready.includes(current.chapter + available + 1)) available++;
    return { ...current, ready, available, missing: current.ahead - available };
  };
  const fetcher = async (url, options = {}) => {
    calls.push({ url, options });
    if (options.method === "POST") {
      const data = JSON.parse(options.body);
      current.chapter = data.chapter;
      if (data.ahead !== undefined) current.ahead = data.ahead;
      if (data.resume || data.ahead !== undefined) current.error = "";
    }
    return { ok: true, json: async () => JSON.parse(JSON.stringify(url.startsWith("/api/book?") ? book : status())) };
  };
  return { calls, current, book, fetcher };
}

test("offline reader never contacts a translator or displays live-only controls", async () => {
  let requests = 0;
  const app = start(undefined, { fetcher: () => { requests++; } });
  await settle();
  assert.equal(requests, 0);
  assert.equal(app.get("buffer-settings").hidden, true);
});

test("live reader saves the requested buffer size and reports chapter changes", async () => {
  const server = bufferServer();
  const app = start(undefined, { protocol: "http:", fetcher: server.fetcher });
  await settle();
  assert.equal(app.get("buffer-settings").hidden, false);
  assert.equal(app.get("buffer-count").value, "30");
  app.get("buffer-count").value = "5";
  app.get("buffer-save").emit("click");
  await settle();
  assert.equal(server.current.ahead, 5);
  assert.equal(app.get("buffer-save").disabled, false);
  app.navigate("#lighthouse/2");
  await settle();
  assert.equal(server.current.chapter, 2);
  assert.equal(server.current.ahead, 5);
  assert.ok(server.calls.some(call => call.options.headers?.["X-Reader-Request"] === "1"));
});

test("newly translated chapters appear without resetting the current text or scroll", async () => {
  const server = bufferServer();
  const app = start(undefined, { protocol: "http:", fetcher: server.fetcher });
  app.navigate("#lighthouse/2");
  await settle();
  app.scroll(420);
  const paragraph = app.get("chapter-text").children[0];
  server.book.chapters.push({ number: 3, title: "Новый вечер", paragraphs: ["Продолжение."] });
  await app.poll();
  assert.equal(app.get("chapter-text").children[0], paragraph);
  assert.equal(app.window.scrollY, 420);
  assert.ok(app.get("chapters").children.some(link => link.href === "#lighthouse/3"));
  assert.ok(app.get("chapter-footer").children.some(link => link.href === "#lighthouse/3"));
});

test("quota errors show a pause and resume is an explicit action", async () => {
  const server = bufferServer(undefined, { error: "Лимит исчерпан" });
  const app = start(undefined, { protocol: "http:", fetcher: server.fetcher });
  await settle();
  assert.ok(app.get("buffer-status").textContent.startsWith("Пауза:"));
  assert.equal(app.get("buffer-retry").hidden, false);
  app.get("buffer-retry").emit("click");
  await settle();
  assert.equal(server.current.error, "");
  assert.ok(server.calls.some(call => call.options.body && JSON.parse(call.options.body).resume));
});

test("stale progress responses cannot move the reading pointer backwards", async () => {
  const server = bufferServer();
  let release;
  let first = true;
  const fetcher = (url, options) => {
    if (first) {
      first = false;
      return new Promise(resolve => { release = () => resolve({ ok: true, json: async () => ({ apiVersion: 1, chapter: 1 }) }); });
    }
    return server.fetcher(url, options);
  };
  const app = start(undefined, { protocol: "http:", fetcher });
  app.navigate("#lighthouse/2");
  await settle();
  release();
  await settle();
  assert.equal(server.current.chapter, 2);
  assert.ok(server.calls.filter(call => call.options.method === "POST").every(call => JSON.parse(call.options.body).chapter === 2));
});

test("a new browser restores the server's reading chapter before reporting progress", async () => {
  const server = bufferServer(undefined, { chapter: 2 });
  const app = start(undefined, { protocol: "http:", fetcher: server.fetcher });
  await settle();
  assert.equal(app.get("chapter-title").textContent, "Ответ");
  assert.equal(server.current.chapter, 2);
  assert.ok(server.calls.filter(call => call.options.method === "POST").every(call => JSON.parse(call.options.body).chapter === 2));
});

test("ordinary HTTP hosting without the buffer API remains a working reader", async () => {
  const app = start(undefined, { protocol: "http:", fetcher: async () => ({ ok: false, json: async () => ({ error: "Not found" }) }) });
  await settle();
  assert.equal(app.get("buffer-settings").hidden, true);
  assert.equal(app.get("chapter-title").textContent, "Огонь");
});
