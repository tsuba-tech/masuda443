"use strict";

const $ = (selector) => document.querySelector(selector);
let currentData = null;
let currentLive = null;

function formatAverage(value) {
  if (!Number.isFinite(value)) return ".---";
  return value.toFixed(3).replace(/^0/, "");
}

function formatGap(value) {
  return formatAverage(Math.abs(value));
}

/**
 * 日時を「2026/09/16 03:49」の形（JST固定）に整える。
 * @param {Date} date
 * @returns {string}
 */
function formatTimestamp(date) {
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(date);
}

/**
 * 表示中の成績が「いつまでの試合」のものかを表すラベルを作る。
 * 取得元は未明（3〜7時台）に前日までの試合を反映して生成されるため、
 * 生成日の前日が対象日になる。閲覧者のタイムゾーンに影響されないよう
 * 日付の判定は日本時間で行う。
 * @param {string|null|undefined} sourceModified 取得元の Last-Modified（ISO文字列）
 * @returns {string} 例 "9/16"。判定できないときは空文字。
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
 * 手入力の速報を確定データに上乗せした data を返す。
 *
 * 動かすのは増田選手の打席・打数・安打・本塁打だけ。首位打者の成績、打点、
 * OPS、直近5試合は観戦中に確定できないため確定値のまま据え置く。
 * 確定データが速報の試合日に追いついている場合は、速報を破棄する。
 *
 * @param {object} data data.json の中身
 * @param {object|null} live live.json の中身
 * @returns {{data: object, live: ?object}} 合成後のデータと、採用した速報
 */
function mergeLiveOverlay(data, live) {
  const totals = live?.totals;
  if (!live?.date || !totals?.pa) return { data, live: null };
  // 確定データが既にその日を含んでいるなら速報は用済み
  const basis = confirmedBasisDate(data.source?.last_modified);
  if (basis && basis >= live.date) return { data, live: null };

  const merged = structuredClone(data);
  const masuda = merged.masuda;
  masuda.pa += totals.pa;
  masuda.ab += totals.ab;
  masuda.hits += totals.hits;
  masuda.hr += totals.hr;
  masuda.avg = masuda.ab > 0 ? masuda.hits / masuda.ab : 0;

  const remaining = Math.max(merged.target_pa - masuda.pa, 0);
  merged.derived.remaining_pa = remaining;
  merged.derived.progress = Math.min((masuda.pa / merged.target_pa) * 100, 100);
  merged.derived.current_regulation_remaining_pa =
    Math.max(merged.team.current_regulation_pa - masuda.pa, 0);
  merged.derived.avg_gap = Math.max(merged.leader.avg - masuda.avg, 0);
  merged.derived.adjusted_avg = remaining > 0
    ? masuda.hits / (masuda.ab + remaining)
    : masuda.avg;
  merged.derived.adjusted_gap = merged.leader.avg - merged.derived.adjusted_avg;
  const remainingGames = merged.team.remaining_games;
  merged.derived.required_pa_per_game = remainingGames ? remaining / remainingGames : null;

  // 本日1本でも打っていれば連続安打は確実に1試合伸びる。
  // 逆に無安打でもまだ打席が残っている可能性があるため、途切れた判定はしない。
  if (totals.hits > 0) merged.recent.hit_streak += 1;
  return { data: merged, live };
}

/**
 * 確定データが対象にしている最終試合日を YYYY-MM-DD で返す。
 * @param {string|null|undefined} sourceModified
 * @returns {string}
 */
function confirmedBasisDate(sourceModified) {
  if (!sourceModified) return "";
  const date = new Date(sourceModified);
  if (Number.isNaN(date.getTime())) return "";
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", hour12: false,
  }).formatToParts(date).map((part) => [part.type, part.value]));
  const basis = new Date(Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day)));
  if (Number(parts.hour) < 12) basis.setUTCDate(basis.getUTCDate() - 1);
  return basis.toISOString().slice(0, 10);
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

function compactHonorific(name) {
  const compactName = name.replace(/\s+/g, "");
  return /選手$/.test(compactName) ? compactName : `${compactName}選手`;
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

/**
 * 小さなDOM生成ヘルパー。選手名などのデータ由来の文字列を
 * textContent 経由で入れるため、innerHTML は使わない。
 * @param {string} tag
 * @param {string|null} className
 * @param {string} [text]
 * @returns {HTMLElement}
 */
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/**
 * 「ラベル ---- 数値」の1行を作る。
 * @param {string} label
 * @param {string} value
 * @param {boolean} [lead] 大きめに見せる主役の行かどうか
 * @returns {HTMLParagraphElement}
 */
function compareRow(label, value, lead) {
  const row = el("p", lead ? "compare-row compare-row-lead" : "compare-row");
  row.append(el("span", null, label), el("strong", null, value));
  return row;
}

/**
 * 首位打者との比較に使う数値をまとめて計算する。
 *
 * - 増田選手の残り打席は「現在の打数化率（打数÷打席）」で打数に換算する。
 * - 比較1：首位打者の打率が現在のままだと仮定したときに必要な安打数。
 * - 比較2：首位打者が直近5試合の打率ペースで残りを消化したと仮定したときに必要な安打数。
 *   首位打者の残り試合数は、今季試合数と出場試合数の差で仮定する（他球団の消化試合数は持たないため）。
 *
 * @param {object} data data.json の中身
 * @returns {{remainingPA:number, projectedAB:number, currentNeed:?object, paceLeaderAvg:number, paceProjectedAB:number, paceNeed:?object}}
 */
function raceProjection(data) {
  const { masuda, leader, derived, team } = data;
  const remainingPA = derived.remaining_pa;
  const projectedAB = remainingPA > 0 ? Math.max(1, Math.round(remainingPA * masuda.ab / masuda.pa)) : 0;
  if (projectedAB === 0) return { remainingPA, projectedAB: 0 };

  const finalAB = masuda.ab + projectedAB;
  // 表示は小数3桁なので、丸めた結果まで上回る安打数を最小から探す
  // （わずかに上回るだけだと画面上は同じ数字に見えてしまうため）。
  const hitsToExceed = (targetAvg) => {
    if (!Number.isFinite(targetAvg)) return null;
    for (let hits = 0; hits <= projectedAB; hits += 1) {
      const finalAvg = (masuda.hits + hits) / finalAB;
      if (finalAvg > targetAvg && formatAverage(finalAvg) !== formatAverage(targetAvg)) {
        return { hits, finalAvg };
      }
    }
    return null;
  };

  // 首位打者の残り試合数は、所属球団の消化試合数（順位表由来）から出す。
  // 取得できていない古いデータでは、出場試合数で代用する。
  const leaderTeamGames = Number.isFinite(leader.team_games_played)
    ? leader.team_games_played
    : leader.games;
  const leaderRemainingGames = Number.isFinite(leader.team_remaining_games)
    ? leader.team_remaining_games
    : Math.max(0, team.season_games - leaderTeamGames);
  // 1試合あたりの打数は「球団の消化試合数」で割る（欠場分も込みのペースにする）
  const leaderProjectedAB = leaderTeamGames > 0
    ? Math.round(leaderRemainingGames * (leader.ab / leaderTeamGames))
    : 0;
  const paceLeaderAvg = Number.isFinite(leader.recent5_avg) && leaderProjectedAB > 0
    ? (leader.hits + leaderProjectedAB * leader.recent5_avg) / (leader.ab + leaderProjectedAB)
    : leader.avg;

  return {
    remainingPA,
    projectedAB,
    currentNeed: hitsToExceed(leader.avg),
    paceLeaderAvg,
    paceProjectedAB: leaderProjectedAB,
    paceRemainingGames: leaderRemainingGames,
    paceNeed: hitsToExceed(paceLeaderAvg),
  };
}

/**
 * 「増田選手が上回るには 残り約N打数で X安打／最終 .XXX」のブロックを作る。
 * 届かない場合はその旨を出す。
 * @param {?{hits:number, finalAvg:number}} need
 * @param {number} projectedAB
 * @returns {HTMLDivElement}
 */
function compareMasudaBlock(need, projectedAB) {
  const block = el("div", "compare-block compare-block-masuda");
  block.append(el("p", "compare-who", "増田選手が上回るには"));
  if (!need) {
    block.append(el("p", "compare-need compare-need-miss", `残り約${projectedAB}打数すべて安打でも届きません`));
    return block;
  }
  const line = el("p", "compare-need");
  line.append(
    document.createTextNode(`残り約${projectedAB}打数で `),
    el("strong", null, String(need.hits)),
    document.createTextNode("安打"),
  );
  block.append(line, compareRow("最終", formatAverage(need.finalAvg), true));
  return block;
}

/**
 * 本日の手入力速報を専用の帯に出す。速報が無い日は帯ごと隠す。
 * メインの数字にも speculation が乗っているため、暫定である旨を必ず添える。
 * @param {?object} live
 */
function renderLivePanel(live) {
  const section = $("#live-strip");
  if (!section) return;
  if (!live) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  const { pa, ab, hits, hr } = live.totals;
  setText("#live-line", `${pa}打席 ${ab}打数 ${hits}安打${hr ? ` ${hr}本塁打` : ""}`);
  // 試合名は任意。入力が無くても文脈がわかるよう、日付は常に自分で出す。
  const day = live.date ? live.date.slice(5).replace("-", "/").replace(/^0/, "") : "";
  setText("#live-note", [day, live.note].filter(Boolean).join("・"));
  const list = $("#live-entries");
  list.replaceChildren();
  live.entries.forEach((entry, index) => {
    const item = el("li", null, `${index + 1}打席目 ${entry.result}`);
    list.append(item);
  });
}

/**
 * 打率ランキングの盤面と、すぐ上の選手を抜くのに必要な安打数を出す。
 *
 * 必要安打数は「これから連続で安打を重ねた場合」の最小本数。打つたびに
 * 打数も1増えるため、単純な引き算では出せない。表示は小数3桁なので、
 * 丸めた結果まで上回るところまで積む。
 *
 * @param {object} data 速報を合成したあとの data
 */
function renderAverageBoard(data) {
  const race = data.average_race;
  const list = $("#race-board");
  if (!list) return;
  list.replaceChildren();
  const board = race?.board || [];
  if (!board.length) {
    setText("#race-board-lead", "規定到達者のランキングを取得できていません。");
    setText("#race-board-next", "");
    return;
  }

  const { hits, ab, avg } = data.masuda;
  // 速報を足すと順位が動くので、確定の順位表に自分の現在値を当てて並べ直す
  const others = board.filter((entry) => normalizeName(entry.name) !== normalizeName(data.masuda.name));
  const ranked = [...others, { name: data.masuda.name, team: "ヤクルト", hits, ab, avg, self: true }]
    .sort((a, b) => b.avg - a.avg)
    .map((entry, index) => ({ ...entry, rank: index + 1 }));
  const me = ranked.find((entry) => entry.self);
  const target = me.rank > 1 ? ranked[me.rank - 2] : null;

  setText("#race-board-lead", `規定到達者${ranked.length}人中 ${me.rank}位（${formatAverage(me.avg)}）`);

  const nextNode = $("#race-board-next");
  if (!target) {
    nextNode.textContent = "セ・リーグ打率 1位。";
  } else {
    const need = hitsToPass(hits, ab, target.avg);
    nextNode.replaceChildren(
      document.createTextNode(`${me.rank - 1}位の${withHonorific(target.name)}（${formatAverage(target.avg)}）まで `),
      el("strong", null, need === null ? "－" : String(need)),
      document.createTextNode(need === null ? "安打では届きません" : "安打で逆転"),
    );
  }

  // 自分の前後が見える範囲だけ出す。全員並べるとスマホで縦に伸びすぎる。
  const from = Math.max(0, Math.min(me.rank - 3, ranked.length - 5));
  ranked.slice(from, from + 5).forEach((entry) => {
    const row = el("li", "board-row");
    if (entry.self) row.classList.add("board-row-self");
    else if (target && entry.rank === target.rank) row.classList.add("board-row-target");
    row.append(el("span", "board-rank", String(entry.rank)));
    const name = el("span", "board-name", entry.name);
    name.append(el("span", "board-team", entry.team));
    row.append(name, el("span", "board-avg", formatAverage(entry.avg)));
    list.append(row);
  });
}

/** 姓名の空白ゆれを無視して比べる。 */
function normalizeName(name) {
  return (name || "").replace(/[\s　]/g, "");
}

/**
 * 連続で安打を重ねて targetAvg を上回るのに要する最小本数。
 * 表示は小数3桁なので、丸めた値まで上回るところまで数える。
 * @returns {?number} 現実的な範囲で届かなければ null
 */
function hitsToPass(hits, ab, targetAvg) {
  for (let n = 1; n <= 60; n += 1) {
    const avg = (hits + n) / (ab + n);
    if (avg > targetAvg && formatAverage(avg) !== formatAverage(targetAvg)) return n;
  }
  return null;
}

function renderRace(data) {
  const { leader } = data;
  const projection = raceProjection(data);
  const container = $("#race-compare");
  const note = $("#race-assumption-note");
  container.replaceChildren();

  if (!projection.projectedAB) {
    setText("#race-assumption", "規定打席に到達しています。");
    note.hidden = true;
    return;
  }
  note.hidden = false;
  setText("#race-assumption", `残り${projection.remainingPA}打席 → 現在の打数化率から約${projection.projectedAB}打数と仮定して試算`);

  // 比較1：首位打者の打率が現在のままの場合
  const currentCard = el("article", "compare-card");
  currentCard.append(el("p", "compare-index", "比較1"));
  currentCard.append(el("h3", "compare-title", "現在の首位打率を上回るには"));
  const currentLeader = el("div", "compare-block");
  currentLeader.append(el("p", "compare-who", withHonorific(leader.name)));
  currentLeader.append(compareRow("現在", formatAverage(leader.avg), true));
  currentCard.append(currentLeader, compareMasudaBlock(projection.currentNeed, projection.projectedAB));
  currentCard.append(el("p", "compare-note", "※首位打者の打率が現在のままだと仮定した場合の目安です。"));

  // 比較2：首位打者が直近5試合のペースで推移した場合
  const paceCard = el("article", "compare-card compare-card-pace");
  paceCard.append(el("p", "compare-index", "比較2"));
  paceCard.append(el("h3", "compare-title", "直近5試合ペースで推移した場合"));
  const paceLeader = el("div", "compare-block");
  const who = el("p", "compare-who", withHonorific(leader.name));
  const form = formLabel(leader.recent5_avg);
  who.append(el("span", form.className, form.label));
  paceLeader.append(who);
  paceLeader.append(compareRow("直近5試合", formatAverage(leader.recent5_avg)));
  paceLeader.append(compareRow(`最終想定（残り約${projection.paceProjectedAB}打数）`, formatAverage(projection.paceLeaderAvg), true));
  paceCard.append(paceLeader, compareMasudaBlock(projection.paceNeed, projection.projectedAB));
  const leaderTeam = leader.team || "所属球団";
  // 「残りN試合」は増田選手側の残り試合数と取り違えられやすいので、
  // 誰がどの球団の残り試合を消化する話なのかを主語ごと明示する。
  paceCard.append(el("p", "compare-note", `※予測ではなく、${compactHonorific(leader.name)}が${leaderTeam}の残り${projection.paceRemainingGames}試合を直近5試合の打撃ペースで消化した場合の仮定シナリオです。`));

  container.append(currentCard, paceCard);
}

// 今季のチーム1試合あたり打席数を一定とするポアソンモデル。
// 上側確率を直接合計し、小さな確率での桁落ちを避ける。
function qualificationOutlook(data) {
  const pa = data.masuda?.pa;
  const target = data.target_pa;
  const played = data.team?.games_played;
  const remaining = data.team?.remaining_games;
  if (![pa, target, played, remaining].every(Number.isInteger)
      || pa < 0 || target <= 0 || played <= 0 || remaining < 0) return null;
  const needed = Math.max(0, target - pa);
  const average = pa / played;
  const mean = average * remaining;
  if (!needed) return { probability: 1, average, mean, reached: true };
  if (!mean) return { probability: 0, average, mean, reached: false };
  let logProbability = -mean;
  let probability = 0;
  const limit = Math.ceil(Math.max(needed, mean) + 12 * Math.sqrt(mean) + 100);
  for (let k = 0; k <= limit; k += 1) {
    if (k >= needed) probability += Math.exp(logProbability);
    logProbability += Math.log(mean) - Math.log(k + 1);
  }
  return { probability: Math.min(1, probability), average, mean, reached: false };
}

function renderQualificationOutlook(data) {
  const result = qualificationOutlook(data);
  if (!result) {
    setText("#qualification-chance", "算出できません");
    setText("#qualification-conditions", "打席数・チーム消化試合数・残り試合数がそろうと表示します。");
    return;
  }
  const percent = result.probability * 100;
  const label = result.reached ? "到達済み"
    : data.team.remaining_games === 0 ? "シーズン終了・未到達"
    : percent < 1 ? "1％未満" : percent > 99 ? "99％超" : `約${Math.round(percent)}％`;
  setText("#qualification-chance", label);
  setText("#qualification-conditions", `今季${data.masuda.pa}打席 ÷ チーム${data.team.games_played}試合 = 1試合平均${result.average.toFixed(2)}打席（欠場込み）。残り${data.team.remaining_games}試合で平均${result.mean.toFixed(1)}打席を積み上げると仮定し、合計${data.target_pa}打席に届く割合をポアソン分布で計算しています。今後も同じペースが続き、各試合の打席数は独立に変動する簡易モデルです。直近の起用・けが・打順変更は反映しておらず、実際の到達確率を保証するものではありません。`);
}

function render(data, live = null) {
  currentData = data;
  currentLive = live;
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
    setText("#current-qualification", `${data.team.games_played}試合消化時点：規定打席${data.team.current_regulation_pa}／増田選手${masuda.pa}打席（${currentResult}）`);
  }
  if (derived.remaining_pa === 0) {
    setText("#required-pace", "規定打席に到達しています");
  } else if (data.team?.remaining_games > 0 && Number.isFinite(derived.required_pa_per_game)) {
    setText("#required-pace", `残り${data.team.remaining_games}試合：必要${derived.remaining_pa}打席／1試合平均 約${derived.required_pa_per_game.toFixed(2)}打席`);
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
  setText("#main-message", specialMessage(data));

  setText("#adjusted-avg", formatAverage(derived.adjusted_avg));
  // 特例打率は「不足分を全打席凡退」で計算するため、通算打率より低く見える。
  // その理由を数字の直下で補足する（規定到達後は不足0なので注記を隠す）。
  const adjustedNote = $("#adjusted-note");
  if (derived.remaining_pa > 0) {
    adjustedNote.hidden = false;
    adjustedNote.textContent = `不足${derived.remaining_pa}打席をすべて凡退扱いした場合`;
  } else {
    adjustedNote.hidden = true;
  }
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

  // 取得元の更新時刻と、当サイトが取りに行った時刻は別物なので分けて出す。
  // これを混同すると「更新済みなのに今日の試合が無い」と誤解される。
  const sourceModified = data.source?.last_modified ? new Date(data.source.last_modified) : null;
  const sourceLabel = sourceModified ? formatTimestamp(sourceModified) : "取得元の更新時刻は不明";
  setText("#source-updated-at-foot", sourceLabel);
  const basisNode = $("#data-basis");
  const basisLabel = dataBasisLabel(data.source?.last_modified);
  if (live) {
    basisNode.hidden = false;
    basisNode.textContent = basisLabel
      ? `${basisLabel}終了時点の確定成績 ＋ 本日${live.totals.pa}打席（速報）`
      : `本日${live.totals.pa}打席の速報を含む`;
  } else {
    basisNode.hidden = !basisLabel;
    basisNode.textContent = basisLabel ? `${basisLabel}終了時点の成績` : "";
  }
  // 速報から導けない指標は確定値のままなので、どこまでの成績かを日付で明示する。
  // 日付は取得元の更新に追従して自動で動く。
  setText("#recent-basis-note", basisLabel ? `※${basisLabel}までの成績` : "");
  setText("#season-basis-note", basisLabel
    ? (live ? `※OPS・打点は${basisLabel}までの成績` : `※${basisLabel}までの成績`)
    : "");
  renderLivePanel(live);

  const updated = new Date(data.updated);
  setText("#updated-at", formatTimestamp(updated));
  renderQuickSim(masuda);
  renderQualificationOutlook(data);
  renderRace(data);
  renderAverageBoard(data);
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
    if (currentData?.source?.stale) {
      const banner = $("#load-error");
      banner.textContent = "取得元の更新が停止している可能性があります。表示は最後に取得できた時点のデータです";
      banner.hidden = false;
      return;
    }
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
    const confirmed = await response.json();
    // 速報は無くても成立するので、読めなくても確定データだけで描画する
    let live = null;
    try {
      const liveResponse = await fetch(`live.json?t=${Date.now()}`, { cache: "no-store" });
      if (liveResponse.ok) live = await liveResponse.json();
    } catch (error) {
      console.info("live.json is not available", error);
    }
    const merged = mergeLiveOverlay(confirmed, live);
    render(merged.data, merged.live);
    await loadFetchStatus();
  } catch (error) {
    console.error("Failed to load data.json", error);
    $("#load-error").hidden = false;
    setText("#header-status", "データ更新待ち");
  }
}

init();
