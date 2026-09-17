"use strict";

const $ = (selector) => document.querySelector(selector);

/**
 * 投球回を「140 2/3」の形に整える。1/3 単位でしか刻まれない。
 * @param {number} innings
 * @returns {string}
 */
function formatInnings(innings) {
  if (!Number.isFinite(innings)) return "--";
  const whole = Math.floor(innings + 1e-9);
  const thirds = Math.round((innings - whole) * 3);
  if (thirds === 3) return String(whole + 1);
  return thirds ? `${whole} ${thirds}/3` : String(whole);
}

function formatEra(value) {
  return Number.isFinite(value) ? value.toFixed(2) : "-.--";
}

function formatTimestamp(date) {
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(date);
}

/**
 * 表示中の成績が「いつまでの試合」のものかを日付で返す。
 * 取得元は未明に前日までの試合を反映して生成される。
 * @param {string|null|undefined} sourceModified
 * @returns {string} 例 "9/16"
 */
function dataBasisLabel(sourceModified) {
  if (!sourceModified) return "";
  const date = new Date(sourceModified);
  if (Number.isNaN(date.getTime())) return "";
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", hour12: false,
  }).formatToParts(date).map((part) => [part.type, part.value]));
  const basis = new Date(Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day)));
  if (Number(parts.hour) < 12) basis.setUTCDate(basis.getUTCDate() - 1);
  return `${basis.getUTCMonth() + 1}/${basis.getUTCDate()}`;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/**
 * 姓名から英字のカウンター名を引く。増田選手の "MASUDA 443" と揃える。
 */
const COUNTER_NAMES = { "奥川 恭伸": "OKUGAWA", "山野 太一": "YAMANO" };
const ANCHORS = { "奥川 恭伸": "okugawa", "山野 太一": "yamano" };

function statRow(label, value) {
  const item = el("div", "pitcher-stat");
  item.append(el("dt", null, label), el("dd", null, value));
  return item;
}

/**
 * 投手1人ぶんのカウンターカードを作る。
 * @param {object} pitcher data.json の pitchers 要素
 * @param {number} target 規定投球回
 */
function pitcherCard(pitcher, target) {
  const key = pitcher.name.replace(/\s+/g, " ").trim();
  const card = el("article", "pitcher-card");
  card.id = ANCHORS[key] || "";

  const head = el("div", "pitcher-head");
  head.append(el("p", "eyebrow", `${pitcher.team}／規定投球回まで`));
  const title = el("h2", "pitcher-title");
  title.append(
    document.createTextNode(`${COUNTER_NAMES[key] || pitcher.name} `),
    el("span", null, String(target)),
  );
  head.append(title, el("p", "pitcher-name", `${pitcher.name} 投手`));
  card.append(head);

  const reached = pitcher.remaining_innings <= 0;
  const counter = el("div", "pitcher-counter");
  if (reached) {
    counter.append(el("strong", "pitcher-reached", "規定投球回 到達"));
  } else {
    counter.append(
      el("span", null, "あと"),
      el("strong", null, formatInnings(pitcher.remaining_innings)),
      el("span", null, "回"),
    );
  }
  card.append(counter);

  const track = el("div", "progress-track");
  track.setAttribute("role", "progressbar");
  track.setAttribute("aria-valuemin", "0");
  track.setAttribute("aria-valuemax", String(target));
  track.setAttribute("aria-valuenow", String(Math.round(pitcher.innings)));
  track.setAttribute("aria-label", `${pitcher.name} 規定投球回進捗`);
  const bar = el("span");
  bar.style.width = `${Math.min(pitcher.progress, 100)}%`;
  track.append(bar);
  card.append(track);

  const meta = el("div", "progress-meta");
  meta.append(
    el("strong", null, `${pitcher.innings_text} / ${target}`),
    el("span", null, `${pitcher.progress.toFixed(1)}%`),
  );
  card.append(meta);

  const stats = el("dl", "pitcher-stats");
  stats.append(
    statRow("防御率", formatEra(pitcher.era)),
    statRow("勝敗", `${pitcher.wins}勝${pitcher.losses}敗`),
    statRow("登板", `${pitcher.games}試合`),
    statRow("奪三振", String(pitcher.strikeouts)),
  );
  card.append(stats);

  // 現在の消化試合数に対する規定ラインも出す。ここを割っていなければ
  // 「今のところ規定ペースに乗っている」ことが分かる。
  const line = pitcher.current_regulation_innings;
  const diff = pitcher.innings - line;
  card.append(el("p", "pitcher-note",
    `${line}試合消化時点の規定ラインは${line}回。現在は${diff >= 0 ? `${formatInnings(diff)}回上回って` : `${formatInnings(-diff)}回下回って`}います。`));
  return card;
}

function render(data) {
  const target = data.target_innings;
  const container = $("#pitchers");
  container.replaceChildren();
  const pitchers = data.pitchers || [];
  if (!pitchers.length) {
    container.append(el("p", "pitcher-loading", "投手データがまだありません。"));
  } else {
    pitchers.forEach((pitcher) => container.append(pitcherCard(pitcher, target)));
  }

  const basis = dataBasisLabel(data.source?.last_modified);
  setTextIfPresent("#pitchers-basis", basis ? `${basis}終了時点の成績` : "");
  const sourceModified = data.source?.last_modified ? new Date(data.source.last_modified) : null;
  setTextIfPresent("#source-updated-at-foot",
    sourceModified ? formatTimestamp(sourceModified) : "取得元の更新時刻は不明");
  setTextIfPresent("#updated-at", formatTimestamp(new Date(data.updated)));
  highlightTab();
}

function setTextIfPresent(selector, value) {
  const node = $(selector);
  if (node) node.textContent = value;
}

/** ハッシュに合わせてタブの現在地を移す。 */
function highlightTab() {
  const hash = location.hash.replace("#", "");
  document.querySelectorAll(".counter-tabs a").forEach((tab) => {
    const isCurrent = tab.getAttribute("href") === `#${hash}`
      || (!hash && tab.getAttribute("href") === "#okugawa");
    tab.classList.toggle("is-current", isCurrent);
    if (isCurrent) {
      tab.setAttribute("aria-current", "page");
    } else {
      tab.removeAttribute("aria-current");
    }
  });
}

async function init() {
  window.addEventListener("hashchange", highlightTab);
  try {
    const response = await fetch(`data.json?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch (error) {
    console.error("Failed to load data.json", error);
    $("#load-error").hidden = false;
    $("#pitchers").replaceChildren(el("p", "pitcher-loading", "データを読み込めませんでした。"));
  }
}

init();
