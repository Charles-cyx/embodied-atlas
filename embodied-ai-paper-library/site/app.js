"use strict";

const byId = (id) => document.getElementById(id);
const domainLabels = { driving: "自动驾驶", robotics: "机器人" };
const methodLabels = { VLA: "VLA", WAM: "WAM", WM: "WM", MAS: "协同控制" };
const storageKey = "paper-tracker-bookmarks-v1";
const pageSize = 6;
const snapshot = window.PAPER_TRACKER_DATA;
const hasData = Array.isArray(snapshot?.papers);
const papers = hasData ? snapshot.papers : [];
const newestPapers = new Map();
for (const paper of papers) {
  newestPapers.set(paper.id, paper);
  if (paper.doi) newestPapers.set(`doi:${paper.doi.toLowerCase()}`, paper);
}
const awardLinks = new Map();
for (const card of document.querySelectorAll("[data-award-id], [data-award-doi]")) {
  const award = card.querySelector(".award-chip");
  if (card.dataset.awardId) awardLinks.set(card.dataset.awardId, award);
  if (card.dataset.awardDoi) awardLinks.set(`doi:${card.dataset.awardDoi}`, award);
}
const bookmarks = loadBookmarks();
const search = byId("search");
const sort = byId("sort");
const paperList = byId("paper-list");
const more = byId("more");
let view = "feed";
let matchingPapers = [];
let shown = 0;

function loadBookmarks() {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) ?? "[]");
    if (Array.isArray(saved)) {
      return new Map(saved.filter((paper) => paper?.id && paper?.title).map((paper) => {
        const current = newestPapers.get(paper.id) ?? newestPapers.get(`doi:${paper.doi?.toLowerCase()}`) ?? paper;
        return [current.id, current];
      }));
    }
  } catch {
    // Browsers may block localStorage, including for local files.
  }
  return new Map();
}

function updateBookmarkButton(button, paper) {
  const saved = bookmarks.has(paper.id);
  button.setAttribute("aria-pressed", String(saved));
  button.setAttribute("aria-label", `收藏《${paper.title}》`);
  button.textContent = saved ? "★ 已收藏" : "☆ 收藏";
}

function toggleBookmark(button, paper) {
  const removing = bookmarks.delete(paper.id);
  if (!removing) bookmarks.set(paper.id, paper);
  let status = removing ? "已移除收藏" : "已加入收藏";
  try {
    localStorage.setItem(storageKey, JSON.stringify([...bookmarks.values()]));
  } catch {
    status += "。当前浏览器仅支持在本次页面会话中保留收藏。";
  }
  byId("saved-count").textContent = bookmarks.size;
  byId("save-status").textContent = status;
  if (view === "saved") {
    const index = [...paperList.querySelectorAll(".bookmark")].indexOf(button);
    render();
    const buttons = paperList.querySelectorAll(".bookmark");
    (buttons[Math.min(index, buttons.length - 1)] ?? byId("list-title")).focus();
    return;
  }
  updateBookmarkButton(button, paper);
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function scholarlyUrl(value) {
  try {
    const url = new URL(value);
    if (url.protocol === "https:" && !url.username && !url.password &&
        (url.hostname === "arxiv.org" || url.hostname === "doi.org")) return url.href;
  } catch {
    // An older bookmark or a source record may omit a URL.
  }
  return "";
}

function paperLink(text, url, className = "") {
  const link = element("a", className, text);
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function awardFor(paper) {
  return awardLinks.get(paper.id) ?? awardLinks.get(`doi:${paper.doi?.toLowerCase()}`);
}

function timelineDate(paper) {
  return paper.publishedDate || paper.date;
}

function displayDate(paper) {
  const date = timelineDate(paper);
  const precision = paper.publishedDate ? paper.publishedDatePrecision : paper.datePrecision;
  if (precision === "year") return date.slice(0, 4);
  if (precision === "month") return date.slice(0, 7);
  return date;
}

function makeCard(paper) {
  const card = element("article", "paper");
  const meta = element("div", "paper-meta");
  const badges = element("div", "badges");
  for (const method of paper.methods) {
    badges.append(element("span", `badge badge-method badge-${method.toLowerCase()}`, methodLabels[method] ?? method));
  }
  for (const domain of paper.domains) {
    badges.append(element("span", "badge badge-domain", domainLabels[domain]));
  }
  const bookmark = element("button", "bookmark");
  bookmark.type = "button";
  updateBookmarkButton(bookmark, paper);
  bookmark.addEventListener("click", () => toggleBookmark(bookmark, paper));
  meta.append(badges, bookmark);

  const doiPath = paper.doi?.split("/").map(encodeURIComponent).join("/");
  const doiUrl = doiPath ? scholarlyUrl(`https://doi.org/${doiPath}`) : "";
  const arxivId = /^(?:\d{4}\.\d{4,5}|[a-z][a-z0-9.-]*\/\d{7})(?:v\d+)?$/i.test(paper.id) ? paper.id : "";
  const sourceUrl = scholarlyUrl(paper.url) || (arxivId ? `https://arxiv.org/abs/${arxivId}` : "");
  const permanentUrl = doiUrl || sourceUrl;
  const pdfUrl = scholarlyUrl(paper.pdfUrl) || (arxivId ? `https://arxiv.org/pdf/${arxivId}` : "");
  const title = element("h3");
  if (permanentUrl) title.append(paperLink(paper.title, permanentUrl));
  else title.textContent = paper.title;
  const authors = element("p", "authors", paper.authors);
  authors.title = paper.authors;

  const footer = element("div", "paper-footer");
  const date = element("time", "", displayDate(paper));
  date.dateTime = displayDate(paper);
  date.title = paper.venueKind ? "发表日期" : "arXiv 首次提交日期（UTC）";
  footer.append(date);
  if (paper.venue) {
    const type = paper.venueKind === "journal" ? "期刊" : "会议";
    const label = `${paper.venueHighlight ? "重点" : ""}${type} · ${paper.venue}`;
    const style = `badge ${paper.venueHighlight ? "venue-highlight" : "venue-chip"}`;
    footer.append(permanentUrl ? paperLink(label, permanentUrl, style) : element("span", style, label));
  } else if (sourceUrl) {
    footer.append(paperLink("arXiv 预印本", sourceUrl, "badge venue-chip"));
  }
  if (doiUrl) footer.append(paperLink("DOI", doiUrl));
  if (doiUrl && sourceUrl && sourceUrl !== doiUrl) footer.append(paperLink("arXiv", sourceUrl));
  if (pdfUrl) footer.append(paperLink("PDF", pdfUrl));
  card.append(meta, title, authors, footer);

  const award = awardFor(paper);
  if (award) card.append(paperLink(award.textContent, award.href, "badge award-chip"));

  if (paper.abstract) {
    const details = element("details");
    const summary = element("summary", "", "查看摘要");
    const text = element("p", "", paper.abstract);
    text.lang = "en";
    details.append(summary, text);
    details.addEventListener("toggle", () => authors.classList.toggle("full", details.open));
    card.append(details);
  }
  return card;
}

function currentFilters() {
  const selected = (name) => document.querySelector(`input[name="${name}"]:checked`).value;
  return {
    domain: selected("domain"),
    method: selected("method"),
    featuredOnly: byId("featured-only").checked,
    awardsOnly: byId("awards-only").checked,
    terms: search.value.trim().toLowerCase().split(/\s+/).filter(Boolean),
  };
}

function render() {
  const { domain, method, terms, featuredOnly, awardsOnly } = currentFilters();
  const pool = view === "saved" ? [...bookmarks.values()] : papers;
  matchingPapers = pool.filter((paper) => {
    if (domain !== "all" && !paper.domains.includes(domain)) return false;
    if (method !== "all" && !paper.methods.includes(method)) return false;
    if (featuredOnly && !paper.venueHighlight) return false;
    if (awardsOnly && !awardFor(paper)) return false;
    const text = [paper.title, paper.authors, paper.abstract, paper.id, paper.doi, paper.venue, ...paper.categories].join(" ").toLowerCase();
    return terms.every((term) => text.includes(term));
  }).sort((a, b) => sort.value === "asc"
    ? timelineDate(a).localeCompare(timelineDate(b))
    : timelineDate(b).localeCompare(timelineDate(a)));
  paperList.replaceChildren();
  shown = 0;
  byId("empty-state").hidden = matchingPapers.length > 0;
  if (!matchingPapers.length) showEmptyState(pool.length);
  appendCards(false);
}

function showEmptyState(poolSize) {
  let title = "没有符合条件的论文";
  let description = "可以换一个关键词，或重置筛选条件。";
  if (!poolSize && view === "saved") {
    title = "还没有收藏";
    description = "在最新论文列表中点击「收藏」，即可在这里继续阅读。";
  } else if (!poolSize && !hasData) {
    title = "暂时无法加载论文";
    description = "请检查站点是否已生成论文数据。";
  } else if (!poolSize) {
    title = "本次更新没有匹配的论文";
    description = "GitHub Actions 下次更新时会重新查询。";
  }
  byId("empty-title").textContent = title;
  byId("empty-body").textContent = description;
  byId("empty-awards").hidden = !byId("awards-only").checked;
}

function appendCards(focusFirst) {
  const cards = matchingPapers.slice(shown, shown + pageSize).map(makeCard);
  paperList.append(...cards);
  shown += cards.length;
  const text = shown < matchingPapers.length
    ? `显示 ${shown} / ${matchingPapers.length} 篇`
    : `${matchingPapers.length} 篇论文`;
  byId("match-count").textContent = text;
  more.hidden = shown >= matchingPapers.length;
  if (focusFirst) cards[0]?.querySelector("h3 a")?.focus();
}

function changeView(next, filters) {
  if (view === next && !filters) return;
  view = next;
  byId("show-feed").setAttribute("aria-pressed", String(next === "feed"));
  byId("show-saved").setAttribute("aria-pressed", String(next === "saved"));
  byId("list-title").textContent = next === "feed" ? "最新论文" : "我的收藏";
  resetFilters(filters);
}

function resetFilters({ domain = "all", method = "all" } = {}) {
  search.value = "";
  sort.value = "desc";
  byId("featured-only").checked = false;
  byId("awards-only").checked = false;
  document.querySelector(`input[name="domain"][value="${domain}"]`).checked = true;
  document.querySelector(`input[name="method"][value="${method}"]`).checked = true;
  render();
}

function configureMetadata() {
  byId("stat-all").textContent = hasData ? papers.length : "—";
  for (const domain of Object.keys(domainLabels)) {
    byId(`stat-${domain}`).textContent = hasData ? papers.filter((paper) => paper.domains.includes(domain)).length : "—";
  }
  byId("stat-mas").textContent = hasData ? papers.filter((paper) => paper.methods.includes("MAS")).length : "—";
  byId("saved-count").textContent = bookmarks.size;
  const sync = byId("sync-status");
  if (snapshot?.fetchedAt) {
    const timestamp = new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai",
      dateStyle: "short",
      timeStyle: "short",
    }).format(new Date(snapshot.fetchedAt));
    const publishedCount = papers.filter((paper) => paper.venueKind).length;
    sync.textContent = `更新于 ${timestamp}（北京时间） · ${publishedCount} 篇会刊论文`;
    if (Date.now() - Date.parse(snapshot.fetchedAt) > 48 * 60 * 60 * 1000) {
      sync.textContent += " · 超过两天未更新";
    }
  } else {
    sync.textContent = "论文数据暂不可用";
  }
}

search.addEventListener("input", render);
sort.addEventListener("change", render);
document.querySelectorAll(".filters input").forEach((input) => input.addEventListener("change", render));
byId("reset").addEventListener("click", () => resetFilters());
byId("show-feed").addEventListener("click", () => changeView("feed"));
byId("show-saved").addEventListener("click", () => changeView("saved"));
document.querySelectorAll("[data-track-method], [data-track-domain]").forEach((link) => {
  link.addEventListener("click", () => {
    changeView("feed", { method: link.dataset.trackMethod, domain: link.dataset.trackDomain });
  });
});
more.addEventListener("click", () => appendCards(true));
configureMetadata();
render();
