"use strict";

const $ = (selector) => document.querySelector(selector);
let currentData = null;

function formatAverage(value) {
  if (!Number.isFinite(value)) return ".---";
  return value.toFixed(3).replace(/^0/, "");
}

function formatGap(value) {
  return formatAverage(Math.abs(value));
}

function setText(selector, value) {
  const element = $(selector);
  if (element) element.textContent = value;
}

function specialMessage(data) {
  const { masuda, leader, recent, derived } = data;
  if (masuda.avg >= leader.avg) return "首位。増田珠選手。";
  if (derived.remaining_pa === 0) return "到達。増田珠選手、規定打席。";
  if (derived.remaining_pa <= 5) return "あと少し。歴史の扉が開く。";
  if (derived.remaining_pa <= 10) return `規定打席443まで、あと${derived.remaining_pa}打席。`;
  if (recent.latest_game?.multi_hit_3) return "猛打賞。打てば道は開かれる。";
  if (recent.latest_game?.hr > 0) return "一閃。増田珠選手、放物線を描く。";
  if (recent.hit_streak >= 5) return `${recent.hit_streak}試合連続安打。止まらない増田選手。`;
  return {
    god: "覚醒中。マスダスゴイミート発動。",
    hot: "好調。首位打者へ前進中。",
    normal: "一本ずつ積め。道はまだ続いている。",
    cold: "信じよう。増田選手はまた打つ。",
  }[derived.status] || "増田選手を信じて応燕します。";
}

function withHonorific(name) {
  return /選手$/.test(name) ? name : `${name} 選手`;
}

function formLabel(avg) {
  if (!Number.isFinite(avg)) return { label: "データなし", className: "form-neutral" };
  if (avg >= 0.400) return { label: "絶好調", className: "form-god" };
  if (avg >= 0.300) return { label: "好調", className: "form-hot" };
  if (avg >= 0.220) return { label: "まずまず", className: "form-normal" };
  return { label: "やや低調", className: "form-cold" };
}

function renderQuickSim(masuda) {
  const quick = $("#quick-sim");
  quick.replaceChildren();
  setText("#quick-sim-context", `現在：${masuda.ab}打数 ${masuda.hits}安打（${formatAverage(masuda.avg)}）`);
  for (let hits = 0; hits <= 4; hits += 1) {
    const cell = document.createElement("div");
    cell.className = "sim-cell";
    const label = document.createElement("span");
    label.textContent = `4打数 ${hits}安打`;
    const value = document.createElement("strong");
    value.textContent = formatAverage((masuda.hits + hits) / (masuda.ab + 4));
    cell.append(label, value);
    quick.append(cell);
  }
}

function raceProjection(data) {
  const { masuda, leader, derived } = data;
  const remainingPA = derived.remaining_pa;
  const projectedAB = remainingPA > 0 ? Math.max(1, Math.round(remainingPA * masuda.ab / masuda.pa)) : 0;
  if (projectedAB === 0) return { remainingPA, projectedAB, scenarios: [] };

  const finalAB = masuda.ab + projectedAB;
  const lowerHits = Math.min(projectedAB, Math.round(projectedAB * 0.250));
  const nearHits = Math.max(0, Math.min(projectedAB, Math.floor(leader.avg * finalAB - masuda.hits)));
  const overHits = Math.max(0, Math.min(projectedAB, nearHits + 1));
  const makeScenario = (tone, title, hits) => {
    const finalAvg = (masuda.hits + hits) / finalAB;
    const futureAvg = hits / projectedAB;
    const gap = finalAvg - leader.avg;
    return { tone, title, hits, finalAvg, futureAvg, gap };
  };
  return {
    remainingPA,
    projectedAB,
    scenarios: [
      makeScenario("low", "下振れ", lowerHits),
      makeScenario("near", "首位に迫る", nearHits),
      makeScenario("over", "首位を上回る", overHits),
    ],
  };
}

function renderRace(data) {
  const projection = raceProjection(data);
  const container = $("#race-scenarios");
  container.replaceChildren();
  if (!projection.projectedAB) {
    setText("#race-assumption", "規定打席に到達しています。");
    return;
  }
  setText("#race-assumption", `残り${projection.remainingPA}打席を、現在の打数割合から約${projection.projectedAB}打数として試算`);
  projection.scenarios.forEach((scenario) => {
    const article = document.createElement("article");
    article.className = `scenario-card scenario-${scenario.tone}`;
    const comparison = scenario.gap > 0
      ? `首位を ${formatGap(scenario.gap)} 上回る`
      : scenario.gap < 0
        ? `首位まで ${formatGap(scenario.gap)}`
        : "首位と同率";
    article.innerHTML = `<p class="scenario-label">${scenario.title}</p><strong>${scenario.hits}安打</strong><p>${projection.projectedAB}打数 ${scenario.hits}安打（${formatAverage(scenario.futureAvg)}）</p><div>最終打率 <b>${formatAverage(scenario.finalAvg)}</b></div><small>${comparison}</small>`;
    container.append(article);
  });
}

function render(data) {
  currentData = data;
  const { masuda, leader, recent, derived, target_pa: target } = data;
  document.body.className = `mode-${derived.status}`;
  setText("#header-status", derived.status === "god" ? "覚醒中" : derived.status === "hot" ? "好調" : derived.status === "cold" ? "復活待機" : "追跡中");
  setText("#remaining-pa", derived.remaining_pa);
  setText("#pa-progress", `${masuda.pa} / ${target}`);
  setText("#progress-percent", `${derived.progress.toFixed(1)}%`);
  if (Number.isFinite(data.team?.current_regulation_pa) && Number.isFinite(derived.current_regulation_remaining_pa)) {
    const currentResult = derived.current_regulation_remaining_pa === 0
      ? "現時点で到達"
      : `あと${derived.current_regulation_remaining_pa}打席`;
    setText("#current-qualification", `${data.team.games_played}試合消化時点の規定打席：${data.team.current_regulation_pa}（増田選手 ${masuda.pa}打席／${currentResult}）`);
  }
  if (derived.remaining_pa === 0) {
    setText("#required-pace", "規定打席に到達しています");
  } else if (data.team?.remaining_games > 0 && Number.isFinite(derived.required_pa_per_game)) {
    setText("#required-pace", `チーム残り${data.team.remaining_games}試合で${derived.remaining_pa}打席 → 1試合平均 約${derived.required_pa_per_game.toFixed(2)}打席が必要`);
  } else {
    setText("#required-pace", "レギュラーシーズン終了時点で規定打席未到達");
  }
  $("#progress-bar").style.width = `${derived.progress}%`;
  const progress = $(".progress-track");
  progress.setAttribute("aria-valuemax", target);
  progress.setAttribute("aria-valuenow", Math.min(masuda.pa, target));
  if (derived.remaining_pa === 0) {
    $("#remaining-block").hidden = true;
    $("#reached-label").hidden = false;
  }

  setText("#masuda-avg", formatAverage(masuda.avg));
  setText("#masuda-detail", `${masuda.hits}安打 / ${masuda.ab}打数`);
  setText("#leader-name", withHonorific(leader.name));
  setText("#leader-avg", formatAverage(leader.avg));
  setText("#leader-gap", masuda.avg >= leader.avg ? "増田選手が首位" : `増田選手との差 ${formatGap(leader.avg - masuda.avg)}`);
  setText("#leader-recent5", formatAverage(leader.recent5_avg));
  const leaderForm = formLabel(leader.recent5_avg);
  const leaderFormLabel = $("#leader-form-label");
  leaderFormLabel.textContent = leaderForm.label;
  leaderFormLabel.className = leaderForm.className;
  const projection = raceProjection(data);
  if (projection.scenarios.length) {
    const over = projection.scenarios[2];
    setText("#leader-race-line", `残り${projection.remainingPA}打席（約${projection.projectedAB}打数）`);
    setText("#leader-race-sub", `${over.hits}安打なら最終打率 ${formatAverage(over.finalAvg)} となり、現在の首位打率 ${formatAverage(leader.avg)} を上回ります`);
  } else {
    setText("#leader-race-line", "規定打席に到達");
    setText("#leader-race-sub", "現在の打率で首位と比較します");
  }
  setText("#main-message", specialMessage(data));

  setText("#adjusted-avg", formatAverage(derived.adjusted_avg));
  if (derived.adjusted_gap <= 0) {
    setText("#adjusted-state", "特例首位打者圏内");
    setText("#adjusted-gap", `+${formatGap(derived.adjusted_gap)}`);
  } else {
    setText("#adjusted-state", "首位との差");
    setText("#adjusted-gap", formatGap(derived.adjusted_gap));
  }
  setText("#last5-avg", formatAverage(recent.last5.avg));
  setText("#last5-hits", recent.last5.hits);
  setText("#last5-hr", recent.last5.hr);
  setText("#hit-streak", recent.hit_streak);
  setText("#last10-avg", formatAverage(recent.last10.avg));
  setText("#last10-hits", `${recent.last10.hits}安打`);
  setText("#season-ops", formatAverage(masuda.ops));
  setText("#season-hr", masuda.hr);
  setText("#season-rbi", masuda.rbi);
  setText("#season-hits", masuda.hits);

  const updated = new Date(data.updated);
  setText("#updated-at", new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(updated));
  setText("#updated-at-top", new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(updated));
  renderQuickSim(masuda);
  renderRace(data);
}

function initCheer() {
  $("#cheer-button").addEventListener("click", () => {
    const layer = $("#cheer-layer");
    while (layer.children.length >= 50) layer.firstElementChild.remove();
    const pop = document.createElement("span");
    pop.className = "cheer-pop";
    pop.textContent = "マスダスゴイパワー";
    pop.style.left = `${12 + Math.random() * 76}%`;
    pop.style.top = `${35 + Math.random() * 50}%`;
    pop.style.fontSize = `${.8 + Math.random() * 1.2}rem`;
    layer.append(pop);
    pop.addEventListener("animationend", () => pop.remove(), { once: true });
  });
}

async function loadFetchStatus() {
  try {
    const response = await fetch(`fetch-status.json?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) return;
    const status = await response.json();
    if (status.source_status === "error") {
      const banner = $("#load-error");
      banner.textContent = "最新取得に失敗しています。表示は前回正常取得時点のデータです";
      banner.hidden = false;
    } else if (status.source_status === "disabled") {
      const banner = $("#load-error");
      banner.textContent = "自動取得は停止中です。表示は前回正常取得時点のデータです";
      banner.hidden = false;
    }
  } catch (error) {
    console.info("fetch-status.json is not available", error);
  }
}

async function init() {
  initCheer();
  try {
    const response = await fetch(`data.json?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
    await loadFetchStatus();
  } catch (error) {
    console.error("Failed to load data.json", error);
    $("#load-error").hidden = false;
    setText("#header-status", "データ更新待ち");
  }
}

init();
