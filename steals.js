"use strict";

const $ = (selector) => document.querySelector(selector);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
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

/**
 * 選手1人ぶんの盗塁数カード。
 * @param {object} runner
 * @param {string} label 「現在の1位」など
 * @param {boolean} highlight 応援対象を強調するか
 */
function runnerCard(runner, label, highlight) {
  const card = el("article", highlight ? "steal-card steal-card-chaser" : "steal-card");
  card.append(el("p", "eyebrow", label));
  card.append(el("p", "steal-name", `${runner.name} 選手`));
  card.append(el("p", "steal-team", runner.team));
  const count = el("p", "steal-count");
  count.append(el("strong", null, String(runner.steals)), el("span", null, "盗塁"));
  card.append(count);
  const stats = el("dl", "pitcher-stats steal-stats");
  for (const [dt, dd] of [["企図", `${runner.attempts}回`], ["成功率", runner.success_rate], ["出場", `${runner.games}試合`]]) {
    const item = el("div", "pitcher-stat");
    item.append(el("dt", null, dt), el("dd", null, dd));
    stats.append(item);
  }
  card.append(stats);
  return card;
}

function render(data) {
  const container = $("#steals");
  container.replaceChildren();
  const steals = data.steals;
  if (!steals || !steals.runner) {
    container.append(el("p", "pitcher-loading", "盗塁データがまだありません。"));
  } else {
    const { runner, rival } = steals;
    const margin = -steals.gap; // 首位側から見た2位との差

    const headline = el("div", "steal-headline");
    if (steals.is_shared_lead) {
      headline.append(el("strong", "steal-lead", "盗塁王争い 首位タイ"));
    } else if (steals.is_leading) {
      headline.append(
        el("span", null, "2位との差"),
        el("strong", null, String(margin)),
        el("span", null, "個"),
      );
    } else {
      headline.append(
        el("span", null, "1位との差"),
        el("strong", null, String(steals.gap)),
        el("span", null, "個"),
      );
    }
    container.append(headline);

    if (steals.is_shared_lead) {
      container.append(el("p", "steal-note-lead",
        `あと1個で単独首位。${rival.name}選手と並んでいます。`));
    } else if (steals.is_leading) {
      container.append(el("p", "steal-note-lead",
        `単独首位。${rival ? `${rival.name}選手に${margin}個差をつけています。` : ""}`));
    } else {
      container.append(el("p", "steal-note-lead",
        `並ぶまであと${steals.gap}個、単独で上回るにはあと${steals.to_lead}個。`));
    }

    const pair = el("div", "steal-pair");
    pair.append(runnerCard(runner, steals.is_leading ? "現在の1位" : "追う", true));
    if (rival) {
      pair.append(runnerCard(rival, steals.is_leading ? "2位" : "現在の1位", false));
    }
    container.append(pair);

    const remaining = data.team?.remaining_games;
    if (Number.isFinite(remaining) && rival) {
      container.append(el("p", "pitcher-note",
        `ヤクルトの残り試合は${remaining}試合。${runner.name}選手の成功率${runner.success_rate}、${rival.name}選手は${rival.success_rate}です。`));
    }
    container.append(el("p", "pitcher-note",
      steals.is_leading
        ? "※相手も盗塁を重ねるため、差は日々変わります。"
        : "※1位の選手も盗塁を重ねるため、必要な数は日々変わります。"));
  }

  const basis = dataBasisLabel(data.source?.last_modified);
  setTextIfPresent("#steals-basis", basis ? `${basis}終了時点の成績` : "");
  const sourceModified = data.source?.last_modified ? new Date(data.source.last_modified) : null;
  setTextIfPresent("#source-updated-at-foot",
    sourceModified ? formatTimestamp(sourceModified) : "取得元の更新時刻は不明");
  setTextIfPresent("#updated-at", formatTimestamp(new Date(data.updated)));
}

function setTextIfPresent(selector, value) {
  const node = $(selector);
  if (node) node.textContent = value;
}

async function init() {
  try {
    const response = await fetch(`data.json?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch (error) {
    console.error("Failed to load data.json", error);
    $("#load-error").hidden = false;
    $("#steals").replaceChildren(el("p", "pitcher-loading", "データを読み込めませんでした。"));
  }
}

init();
