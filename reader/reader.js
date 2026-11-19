"use strict";

const byId = (id) => document.getElementById(id);
const books = JSON.parse(byId("library").textContent);
const settingsKey = "novel-reader:settings";
const contentsButton = byId("contents-button");
const contents = byId("contents");
const bookSelect = byId("book-select");
const minSize = 16;
const maxSize = 30;

function readStorage(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? fallback;
  } catch {
    return fallback;
  }
}

function writeStorage(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // File URLs and private browsing can restrict local storage.
  }
}

const saved = readStorage(settingsKey, {});
const settings = {
  theme: saved.theme === "dark" ? "dark" : "light",
  size: Number.isFinite(saved.size) ? Math.max(minSize, Math.min(maxSize, saved.size)) : 20,
  book: saved.book,
};
let current;
let canSavePosition = false;
let scrollFrame = 0;

const noteDialog = byId("note-dialog");
const appearance = byId("appearance");
const mobileLayout = window.matchMedia("(max-width: 760px)");
let noteIndex;
let indexedBook;

function foldForm(text, language) {
  try {
    return text.toLocaleLowerCase(language || undefined);
  } catch {
    return text.toLowerCase();
  }
}

function indexNotes(book) {
  if (indexedBook === book) return;
  indexedBook = book;
  const forms = new Map();
  for (const note of book.annotations || []) {
    for (const form of note.forms) forms.set(foldForm(form, book.targetLanguage), note);
  }
  const words = Array.from(forms.keys()).sort((a, b) => b.length - a.length);
  const escape = word => word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const boundary = "[^\\p{L}\\p{M}\\p{N}_-]";
  const pattern = words.length ? new RegExp("(^|" + boundary + ")(" + words.map(escape).join("|") + ")(?=$|" + boundary + ")", "giu") : null;
  noteIndex = { forms, pattern };
}

function noteSenses(note, paragraph, offset, chapterNumber) {
  const confirmed = note.senses.filter(sense => (sense.passages?.[chapterNumber] || []).some(quote => {
    const start = paragraph.indexOf(quote);
    return start >= 0 && start <= offset && offset < start + quote.length;
  }));
  return confirmed.length === 1 ? confirmed : note.senses;
}

function markParagraph(element, paragraph, chapterNumber, markedNotes) {
  if (!noteIndex.pattern) {
    element.textContent = paragraph;
    return;
  }
  let end = 0;
  for (const match of paragraph.matchAll(noteIndex.pattern)) {
    const start = match.index + match[1].length;
    const note = noteIndex.forms.get(foldForm(match[2], indexedBook.targetLanguage));
    if (!note) continue;
    const senses = noteSenses(note, paragraph, start, chapterNumber);
    const key = senses.length === 1 ? senses[0] : note;
    if (markedNotes.has(key)) continue;
    markedNotes.add(key);
    markedNotes.add(note);
    const mark = document.createElement("button");
    mark.type = "button";
    mark.className = "annotation " + note.kind;
    mark.setAttribute("aria-haspopup", "dialog");
    mark.textContent = match[2];
    mark.setAttribute("aria-label", match[2] + (note.kind === "person" ? " — карточка персонажа" : " — пояснение"));
    mark.addEventListener("click", () => showNote(note, paragraph, start, chapterNumber));
    element.append(paragraph.slice(end, start), mark);
    end = start + match[2].length;
  }
  element.append(paragraph.slice(end));
}

function senseElement(sense, language, chapterNumber) {
  const section = document.createElement("section");
  const original = document.createElement("span");
  original.className = "note-original";
  original.lang = language || "zh";
  original.textContent = sense.original;
  section.append(original);
  if (sense.reading) {
    const reading = document.createElement("span");
    reading.className = "note-reading";
    reading.textContent = sense.reading;
    section.append(reading);
  }
  const body = document.createElement("p");
  body.textContent = sense.body;
  section.append(body);
  if (sense.recap && sense.recap.chapter < chapterNumber) {
    const recap = document.createElement("p");
    recap.textContent = sense.recap.text;
    section.append(recap);
  }
  if (sense.source && /^https?:\/\//i.test(sense.source.url)) {
    const source = document.createElement("a");
    source.href = sense.source.url;
    source.target = "_blank";
    source.rel = "noopener noreferrer";
    source.textContent = sense.source.label + " ↗";
    section.append(source);
  }
  return section;
}

function showNote(note, paragraph, offset, chapterNumber) {
  const primary = noteSenses(note, paragraph, offset, chapterNumber);
  const body = byId("note-body");
  byId("note-title").textContent = note.title;
  byId("note-type").textContent = note.kind === "reference" ? "Культурная отсылка" :
    (primary.length > 1 ? "Персонажи с этим именем" : "Персонаж");
  noteDialog.dataset.kind = note.kind;
  const renderSense = sense => senseElement(sense, indexedBook.sourceLanguage, chapterNumber);
  body.replaceChildren(...primary.map(renderSense));
  if (primary.length < note.senses.length) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Другие персонажи с этим именем";
    details.append(summary, ...note.senses.filter(sense => !primary.includes(sense)).map(renderSense));
    body.append(details);
  }
  appearance.open = false;
  noteDialog.showModal();
}
byId("note-close").addEventListener("click", () => noteDialog.close());
noteDialog.addEventListener("click", event => {
  if (event.target !== noteDialog) return;
  const rect = noteDialog.getBoundingClientRect();
  if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) noteDialog.close();
});
document.addEventListener("click", event => {
  if (!appearance.contains(event.target)) appearance.open = false;
});
appearance.addEventListener("keydown", event => {
  if (event.key !== "Escape" || !appearance.open) return;
  event.stopPropagation();
  appearance.open = false;
  appearance.querySelector("summary").focus();
});


function applySettings() {
  document.documentElement.dataset.theme = settings.theme;
  document.documentElement.style.setProperty("--reading-size", `${settings.size}px`);
  byId("font-down").disabled = settings.size <= minSize;
  byId("font-up").disabled = settings.size >= maxSize;
  const themeLabel = settings.theme === "dark" ? "Светлая тема" : "Тёмная тема";
  const themeButton = byId("theme");
  themeButton.setAttribute("aria-label", themeLabel);
  themeButton.title = themeLabel;
  byId("theme-label").textContent = themeLabel;
  byId("font-size").textContent = String(settings.size);
  themeButton.firstElementChild.textContent = settings.theme === "dark" ? "☀" : "☾";
}

function setContents(open) {
  contents.classList.toggle("is-open", open && mobileLayout.matches);
  if (!mobileLayout.matches) document.body.classList.toggle("toc-hidden", !open);
  contentsButton.setAttribute("aria-expanded", String(open));
}

function chapterUrl(book, number) {
  return `#${book.slug}/${number}`;
}

function updateProgress() {
  const limit = document.documentElement.scrollHeight - window.innerHeight;
  byId("progress").value = limit > 0 ? Math.min(100, Math.max(0, window.scrollY / limit * 100)) : 0;
}

function positionKey(book, chapter) {
  return `novel-reader:position:${book.slug}/${chapter.number}`;
}

function savePosition() {
  if (canSavePosition && current) {
    writeStorage(positionKey(current.book, current.chapter), window.scrollY);
  }
}

function makeChapterLink(book, chapter, selected) {
  const link = document.createElement("a");
  const number = document.createElement("span");
  const title = document.createElement("span");
  link.href = chapterUrl(book, chapter.number);
  link.className = "chapter-link";
  if (selected) link.setAttribute("aria-current", "page");
  number.textContent = chapter.number;
  title.textContent = chapter.title;
  link.append(number, title);
  return link;
}

function renderNavigation(book, chapter) {
  byId("chapters").replaceChildren(...book.chapters.map((item) => makeChapterLink(book, item, item === chapter)));
  const footer = byId("chapter-footer");
  const index = book.chapters.findIndex(item => item.number === chapter.number);
  const previous = book.chapters[index - 1];
  const next = book.chapters[index + 1];
  footer.replaceChildren();
  for (const [adjacent, label] of [[previous, "← Глава"], [next, "Глава"]]) {
    if (!adjacent) continue;
    const link = document.createElement("a");
    link.href = chapterUrl(book, adjacent.number);
    if (adjacent === next) link.dataset.next = "";
    link.textContent = `${label} ${adjacent.number}${adjacent === next ? " →" : ""}`;
    footer.append(link);
  }
  footer.hidden = !previous && !next;
}

function renderChapter(book, chapter) {
  const lastBeforeRender = readStorage(`novel-reader:last:${book.slug}`, null);
  const explicitChapter = location.hash.slice(1).split("/")[1];
  if (noteDialog.open) noteDialog.close();
  indexNotes(book);
  current = { book, chapter };
  canSavePosition = false;
  settings.book = book.slug;
  writeStorage(settingsKey, settings);
  writeStorage(`novel-reader:last:${book.slug}`, chapter.number);
  bookSelect.value = book.slug;
  byId("toolbar-title").textContent = book.title;
  byId("toolbar-chapter").textContent = `Глава ${chapter.number} · ${chapter.title}`;
  byId("chapter-number").textContent = `Глава ${chapter.number}`;
  byId("chapter-title").textContent = chapter.title;
  byId("original-title").textContent = book.originalTitle;
  byId("original-title").lang = book.sourceLanguage;
  byId("original-title").hidden = !book.originalTitle;
  document.title = `${book.title} · Глава ${chapter.number}`;

  const article = byId("chapter");
  article.hidden = false;
  article.lang = book.targetLanguage || "ru";
  renderNavigation(book, chapter);
  const body = document.createDocumentFragment();
  const markedNotes = new Set();
  for (const paragraph of chapter.paragraphs) {
    const isBreak = paragraph === "* * *";
    const element = document.createElement(isBreak ? "hr" : "p");
    if (!isBreak) markParagraph(element, paragraph, chapter.number, markedNotes);
    body.append(element);
  }
  byId("chapter-text").replaceChildren(body);

  const position = readStorage(positionKey(book, chapter), 0);
  window.scrollTo(0, Number.isFinite(position) ? position : 0);
  updateProgress();
  canSavePosition = true;
  syncBuffer({ reportPosition: true, restore: lastBeforeRender === null && !explicitChapter });
}

let bufferRequest = 0;
let bufferConnected = false;
const liveReader = location.protocol === "http:" || location.protocol === "https:";

async function bufferApi(path, data) {
  const options = data ? {
    method: "POST", mode: "same-origin",
    headers: { "Content-Type": "application/json", "X-Reader-Request": "1" },
    body: JSON.stringify(data),
  } : { cache: "no-store", mode: "same-origin" };
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Не удалось обновить запас");
  return result;
}

function showBuffer(state, replaceCount = false) {
  bufferConnected = true;
  byId("buffer-settings").hidden = false;
  const input = byId("buffer-count");
  if (replaceCount || document.activeElement !== input) input.value = String(state.ahead);
  byId("buffer-retry").hidden = !state.error || state.ahead === 0;
  byId("buffer-status").textContent = state.error ? `Пауза: ${state.error}` :
    state.active ? (state.ahead === 0 ? `Завершается глава ${state.active}` : `${state.available} из ${state.ahead} · переводится глава ${state.active}`) :
    state.ahead === 0 ? "Автопополнение выключено" :
    state.missing ? `${state.available} из ${state.ahead} · ожидает перевода` :
    `Запас готов: ${state.available} из ${state.ahead}`;
}

async function refreshBook(book, state, request) {
  if (!state.ready.some(number => !book.chapters.some(chapter => chapter.number === number))) return;
  const updated = await bufferApi(`/api/book?book=${encodeURIComponent(book.slug)}`);
  if (request !== bufferRequest || current?.book !== book) return;
  book.chapters = updated.chapters;
  current.chapter = book.chapters.find(chapter => chapter.number === current.chapter.number);
  renderNavigation(book, current.chapter);
}

async function syncBuffer({ reportPosition = false, restore = false, ahead, resume = false } = {}) {
  if (!liveReader || !current) return;
  const { book, chapter } = current;
  const request = ++bufferRequest;
  try {
    let state = await bufferApi(`/api/buffer?book=${encodeURIComponent(book.slug)}`);
    if (request !== bufferRequest || current.book !== book || current.chapter.number !== chapter.number) return;
    if (state.apiVersion !== 1) return;
    if (restore && state.chapter && state.chapter !== chapter.number && book.chapters.some(item => item.number === state.chapter)) {
      location.hash = chapterUrl(book, state.chapter);
      navigate();
      return;
    }
    if (reportPosition || ahead !== undefined || resume) {
      state = await bufferApi("/api/buffer", {
        book: book.slug, chapter: chapter.number, ...(ahead !== undefined ? { ahead } : {}), ...(resume ? { resume } : {}),
      });
      if (request !== bufferRequest || current.book !== book || current.chapter.number !== chapter.number) return;
    }
    showBuffer(state, ahead !== undefined);
    await refreshBook(book, state, request);
  } catch (error) {
    if (request === bufferRequest && bufferConnected) {
      byId("buffer-status").textContent = `Нет связи с автопополнением: ${error.message}`;
    }
  }
}

byId("buffer-save").addEventListener("click", async () => {
  const input = byId("buffer-count");
  const ahead = Number(input.value);
  if (input.value.trim() === "" || !Number.isInteger(ahead) || ahead < 0 || ahead > 1000) {
    byId("buffer-status").textContent = "Укажи целое число от 0 до 1000";
    return;
  }
  const button = byId("buffer-save");
  button.disabled = true;
  try {
    await syncBuffer({ ahead });
  } finally {
    button.disabled = false;
  }
});
byId("buffer-retry").addEventListener("click", () => syncBuffer({ resume: true }));
if (liveReader) window.setInterval(() => syncBuffer(), 5000);

function navigate() {
  if (books.length === 0) {
    byId("empty").hidden = false;
    contents.hidden = true;
    contentsButton.hidden = true;
    return;
  }
  const [slug, number] = location.hash.slice(1).split("/");
  const linkedBook = books.find((book) => book.slug === slug);
  const book = linkedBook || books.find((item) => item.slug === settings.book) || books[0];
  const last = readStorage(`novel-reader:last:${book.slug}`, null);
  const linkedChapter = linkedBook && book.chapters.find((chapter) => chapter.number === Number(number));
  const chapter = linkedChapter || book.chapters.find((item) => item.number === last) || book.chapters[0];
  if (current?.book === book && current.chapter === chapter) return;
  savePosition();
  renderChapter(book, chapter);
}

if ("scrollRestoration" in history) history.scrollRestoration = "manual";
for (const book of books) bookSelect.add(new Option(book.title, book.slug));
byId("book-picker").hidden = books.length < 2;
bookSelect.addEventListener("change", () => {
  if (mobileLayout.matches) setContents(false);
  location.hash = bookSelect.value;
});

function resetContentsLayout() {
  document.body.classList.remove("toc-hidden");
  setContents(!mobileLayout.matches);
}
mobileLayout.addEventListener("change", resetContentsLayout);
resetContentsLayout();
contentsButton.addEventListener("click", () => {
  appearance.open = false;
  const open = contentsButton.getAttribute("aria-expanded") !== "true";
  setContents(open);
  if (open) contents.querySelector('[aria-current="page"]')?.scrollIntoView({block: "nearest"});
});
byId("chapters").addEventListener("click", (event) => {
  if (!event.target.closest("a")) return;
  if (mobileLayout.matches) setContents(false);
  if (mobileLayout.matches) byId("main").focus({ preventScroll: true });
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || !contents.classList.contains("is-open")) return;
  setContents(false);
  contentsButton.focus();
});
document.querySelector(".skip").addEventListener("click", (event) => {
  event.preventDefault();
  byId("main").focus({ preventScroll: true });
  byId("main").scrollIntoView();
});

function resizeText(delta) {
  settings.size = Math.max(minSize, Math.min(maxSize, settings.size + delta));
  applySettings();
  writeStorage(settingsKey, settings);
  updateProgress();
}

byId("font-down").addEventListener("click", () => resizeText(-2));
byId("font-up").addEventListener("click", () => resizeText(2));
byId("theme").addEventListener("click", () => {
  settings.theme = settings.theme === "dark" ? "light" : "dark";
  applySettings();
  writeStorage(settingsKey, settings);
});

window.addEventListener("scroll", () => {
  if (scrollFrame) return;
  scrollFrame = requestAnimationFrame(() => {
    scrollFrame = 0;
    updateProgress();
    savePosition();
  });
}, { passive: true });
window.addEventListener("resize", updateProgress);
window.addEventListener("hashchange", navigate);
window.addEventListener("pagehide", savePosition);
applySettings();
navigate();
