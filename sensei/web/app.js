"use strict";

const byId = (id) => document.getElementById(id);
const skillTemplate = byId("skill-template");
const historyTemplate = byId("history-template");
const viewNames = ["dojo", "profile", "past-quest"];
const viewTitles = {
  dojo: "Sensei // Adaptive Dojo",
  profile: "Profile // Sensei",
  "past-quest": "Past Quest // Sensei",
};
let dashboardState = null;
let activeQuest = null;
let attemptToken = null;
let generatingQuestion = false;
const generationStatuses = new Map();
const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
const CLIENT_ERROR_STORAGE_KEY = "sensei.pending-client-errors.v1";
const MAX_PENDING_CLIENT_ERRORS = 25;
const reportedClientErrors = new WeakSet();

function viewFromHash() {
  const requestedView = window.location.hash.slice(1);
  return viewNames.includes(requestedView) ? requestedView : "dojo";
}

function showView(viewName, { updateHash = true, focus = false } = {}) {
  const nextView = viewNames.includes(viewName) ? viewName : "dojo";
  document.querySelectorAll(".app-view").forEach((view) => {
    view.hidden = view.id !== `${nextView}-view`;
  });
  document.querySelectorAll(".nav-tab").forEach((tab) => {
    const selected = tab.dataset.view === nextView;
    tab.classList.toggle("active", selected);
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    if (selected && focus) tab.focus();
  });
  document.title = viewTitles[nextView];
  if (updateHash && window.location.hash !== `#${nextView}`) {
    window.history.replaceState(null, "", `#${nextView}`);
  }
}

window.addEventListener("error", (event) => {
  void reportClientProblem(
    event.error || new Error(event.message || "Unknown browser error"),
    `window.error ${event.filename || "app"}:${event.lineno || 0}:${event.colno || 0}`,
  );
});
window.addEventListener("unhandledrejection", (event) => {
  const error = event.reason instanceof Error ? event.reason : new Error(String(event.reason));
  void reportClientProblem(error, "window.unhandledrejection");
});

function clientProblemDocument(error, source) {
  const message = error instanceof Error ? error.message : String(error);
  return {
    message: (message || "Unknown browser error").slice(0, 1000),
    stack: (error instanceof Error ? error.stack || "" : "").slice(0, 2000),
    source: String(source || "dashboard browser").slice(0, 120),
  };
}

function readPendingClientProblems() {
  try {
    const pending = JSON.parse(localStorage.getItem(CLIENT_ERROR_STORAGE_KEY) || "[]");
    return Array.isArray(pending) ? pending.slice(-MAX_PENDING_CLIENT_ERRORS) : [];
  } catch {
    return [];
  }
}

function writePendingClientProblems(problems) {
  try {
    if (problems.length) {
      localStorage.setItem(
        CLIENT_ERROR_STORAGE_KEY,
        JSON.stringify(problems.slice(-MAX_PENDING_CLIENT_ERRORS)),
      );
    } else {
      localStorage.removeItem(CLIENT_ERROR_STORAGE_KEY);
    }
  } catch {
    // Error reporting must never interrupt the learner's current action.
  }
}

async function sendClientProblem(document) {
  if (!dashboardState?.csrf_token) throw new Error("Dashboard is not connected yet.");
  const response = await fetch("/api/errors", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Sensei-CSRF": dashboardState.csrf_token },
    body: JSON.stringify(document),
  });
  if (!response.ok) throw new Error(`Error-log request failed: ${response.status}`);
}

async function reportClientProblem(error, source) {
  if (error?.errorId) return;
  const trackable = error && typeof error === "object";
  if (trackable && reportedClientErrors.has(error)) return;
  if (trackable) reportedClientErrors.add(error);
  const document = clientProblemDocument(error, source);
  try {
    await sendClientProblem(document);
  } catch {
    const pending = readPendingClientProblems();
    pending.push(document);
    writePendingClientProblems(pending);
  }
}

async function flushPendingClientProblems() {
  const pending = readPendingClientProblems();
  if (!pending.length || !dashboardState?.csrf_token) return;
  writePendingClientProblems([]);
  for (let index = 0; index < pending.length; index += 1) {
    try {
      await sendClientProblem(pending[index]);
    } catch {
      writePendingClientProblems([
        ...pending.slice(index),
        ...readPendingClientProblems(),
      ]);
      return;
    }
  }
}

function setGenerationStatus(target, message, kind = "", statusKey = "") {
  if (statusKey) generationStatuses.set(statusKey, { message, kind });
  if (!target) return;
  target.textContent = message;
  target.dataset.kind = kind;
}

function restoreGenerationStatus(target, statusKey) {
  const status = generationStatuses.get(statusKey);
  if (status) {
    setGenerationStatus(target, status.message, status.kind);
  } else if (target) {
    target.textContent = "";
    target.dataset.kind = "";
  }
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, Number(value) || 0));
}

function svgElement(name, attributes = {}, copy = "") {
  const element = document.createElementNS(SVG_NAMESPACE, name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
  if (copy) element.textContent = copy;
  return element;
}

function graphTicks(minimum, maximum, targetCount = 9) {
  const roughStep = (maximum - minimum) / targetCount;
  const magnitude = 10 ** Math.floor(Math.log10(roughStep));
  const normalized = roughStep / magnitude;
  const step = (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10) * magnitude;
  const ticks = [];
  for (let value = Math.ceil(minimum / step) * step; value <= maximum + step * 0.001; value += step) {
    ticks.push(Math.abs(value) < step * 0.001 ? 0 : Number(value.toPrecision(12)));
  }
  return ticks;
}

function formatGraphTick(value) {
  return Number(value.toPrecision(4)).toString();
}

function renderGraph(graph) {
  const figure = byId("arena-graph");
  const svg = byId("arena-graph-svg");
  svg.replaceChildren();
  figure.hidden = !graph;
  if (!graph) {
    byId("arena-graph-description").textContent = "";
    return;
  }

  const width = 720;
  const height = 400;
  const margin = { top: 24, right: 28, bottom: 48, left: 60 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const xPosition = (value) => margin.left + ((value - graph.x_min) / (graph.x_max - graph.x_min)) * plotWidth;
  const yPosition = (value) => margin.top + ((graph.y_max - value) / (graph.y_max - graph.y_min)) * plotHeight;

  graphTicks(graph.x_min, graph.x_max).forEach((tick) => {
    const x = xPosition(tick);
    svg.append(
      svgElement("line", { x1: x, y1: margin.top, x2: x, y2: height - margin.bottom, class: tick === 0 ? "graph-axis" : "graph-grid" }),
      svgElement("text", { x, y: height - margin.bottom + 22, class: "graph-tick", "text-anchor": "middle" }, formatGraphTick(tick)),
    );
  });
  graphTicks(graph.y_min, graph.y_max).forEach((tick) => {
    const y = yPosition(tick);
    svg.append(
      svgElement("line", { x1: margin.left, y1: y, x2: width - margin.right, y2: y, class: tick === 0 ? "graph-axis" : "graph-grid" }),
      svgElement("text", { x: margin.left - 12, y: y + 4, class: "graph-tick", "text-anchor": "end" }, formatGraphTick(tick)),
    );
  });
  svg.append(
    svgElement("text", { x: width - margin.right, y: height - 13, class: "graph-axis-label", "text-anchor": "end" }, "x"),
    svgElement("text", { x: 23, y: margin.top + 3, class: "graph-axis-label" }, "y"),
  );

  graph.curves.forEach((curve) => {
    const coordinates = curve.map(([x, y]) => `${xPosition(x)},${yPosition(y)}`).join(" ");
    svg.append(svgElement("polyline", { points: coordinates, class: "graph-curve" }));
  });
  graph.points.forEach((point) => {
    svg.append(svgElement("circle", {
      cx: xPosition(point.x),
      cy: yPosition(point.y),
      r: 6,
      class: `graph-point ${point.type}`,
    }));
  });
  byId("arena-graph-description").textContent = graph.description;
}

function relativeDate(value) {
  if (!value) return "new topic";
  const target = new Date(value);
  if (Number.isNaN(target.getTime())) return "review scheduled";
  const days = Math.round((target.getTime() - Date.now()) / 86400000);
  if (days < -1) return `${Math.abs(days)} days overdue`;
  if (days === -1) return "1 day overdue";
  if (days === 0) return "due today";
  if (days === 1) return "review tomorrow";
  return `review in ${days} days`;
}

function relativeMoment(value) {
  const target = new Date(value);
  if (Number.isNaN(target.getTime())) return "recently";
  const days = Math.floor((Date.now() - target.getTime()) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

function renderProfile(profile) {
  const progress = clamp(profile.xp_into_level / profile.xp_for_next_level, 0, 1);
  byId("level").textContent = profile.level;
  byId("rank-name").textContent = profile.rank_name;
  byId("xp-summary").textContent = `${profile.xp_into_level} / ${profile.xp_for_next_level} XP`;
  byId("total-xp").textContent = `${profile.total_xp} total`;
  byId("attempts").textContent = profile.attempts;
  byId("practiced").textContent = profile.skills_practiced;
  byId("mastered").textContent = profile.skills_mastered;
  byId("xp-progress").style.width = `${progress * 100}%`;
  byId("rank-ring").style.setProperty("--xp-angle", `${progress * 360}deg`);
}

function renderTopics(topics) {
  const grid = byId("skill-grid");
  grid.replaceChildren();
  byId("empty-atlas").hidden = topics.length > 0;
  byId("atlas-summary").textContent = topics.length
    ? `${topics.length} self-directed topic${topics.length === 1 ? "" : "s"} in your atlas.`
    : "No fixed curriculum. Add only what matters to you.";
  topics.forEach((topic) => {
    const card = skillTemplate.content.firstElementChild.cloneNode(true);
    card.querySelector(".skill-subject").textContent = topic.course;
    card.querySelector(".skill-score").textContent = `${Math.round(topic.mastery_score)} / 100`;
    card.querySelector(".skill-name").textContent = topic.name;
    card.querySelector(".skill-label").textContent = topic.mastery_label;
    card.querySelector(".skill-track i").style.width = `${clamp(topic.mastery_score, 0, 100)}%`;
    card.querySelector(".skill-attempts").textContent = `${topic.attempts_count} encounter${topic.attempts_count === 1 ? "" : "s"}`;
    card.querySelector(".skill-review").textContent = relativeDate(topic.next_review_at);
    const generationStatus = card.querySelector(".card-generation-status");
    restoreGenerationStatus(generationStatus, topic.id);
    card.querySelector(".practice-button").addEventListener("click", () => startAdaptiveQuest(topic.id, generationStatus));
    grid.append(card);
  });
}

function renderHistory(attempts) {
  const list = byId("history-list");
  list.replaceChildren();
  if (!attempts.length) {
    const empty = document.createElement("p");
    empty.className = "empty-history";
    empty.textContent = "No encounters yet. Visit the Dojo to forge your first quest.";
    list.append(empty);
    return;
  }
  attempts.slice(0, 8).forEach((attempt) => {
    const row = historyTemplate.content.firstElementChild.cloneNode(true);
    row.dataset.outcome = attempt.outcome;
    row.querySelector(".history-skill").textContent = `${attempt.course} · ${attempt.skill_name}`;
    row.querySelector(".history-problem").textContent = attempt.problem;
    const source = attempt.effective_outcome_source === "verifier" ? "checked " : "";
    row.querySelector(".history-outcome").textContent = `${source}${attempt.outcome}`;
    const time = row.querySelector(".history-time");
    time.dateTime = attempt.created_at;
    time.textContent = relativeMoment(attempt.created_at);
    list.append(row);
  });
}

function resetArenaFeedback() {
  attemptToken = null;
  const feedback = byId("answer-feedback");
  feedback.hidden = true;
  feedback.className = "answer-feedback";
  byId("feedback-status").textContent = "";
  byId("feedback-detail").textContent = "";
  byId("feedback-detail").hidden = false;
  byId("feedback-expected").textContent = "";
  byId("solution-copy").hidden = true;
  byId("solution-text").textContent = "";
  byId("record-attempt").hidden = true;
}

function renderOptions(quest) {
  const grid = byId("option-grid");
  grid.replaceChildren();
  grid.hidden = quest.answer_type !== "multiple_choice";
  quest.options.forEach((option, index) => {
    const letter = String.fromCharCode(65 + index);
    const button = document.createElement("button");
    button.type = "button";
    const badge = document.createElement("span");
    badge.textContent = letter;
    const copy = document.createElement("b");
    copy.textContent = option;
    button.append(badge, copy);
    button.addEventListener("click", () => {
      grid.querySelectorAll("button").forEach((item) => item.classList.remove("selected"));
      button.classList.add("selected");
      byId("quest-answer").value = letter;
    });
    grid.append(button);
  });
}

function openArena(quest) {
  activeQuest = quest;
  showView("dojo");
  resetArenaFeedback();
  byId("arena-skill").textContent = `${quest.subject} · ${quest.skill_name}`;
  byId("arena-title").textContent = quest.title;
  byId("arena-prompt").textContent = quest.prompt;
  renderGraph(quest.graph);
  byId("quest-answer").value = "";
  byId("quest-answer").placeholder = quest.answer_type === "multiple_choice" ? "Choose A, B, C, or D" : "Enter only the requested value";
  byId("notation-help").hidden = quest.answer_type !== "expression";
  byId("hint-copy").textContent = quest.hint;
  byId("hint-copy").hidden = true;
  byId("show-hint").textContent = "Ask Sensei for a hint";
  renderOptions(quest);
  const arena = byId("quest-arena");
  arena.hidden = false;
  arena.scrollIntoView({ behavior: "smooth", block: "start" });
  if (quest.answer_type === "expression") byId("quest-answer").focus({ preventScroll: true });
}

async function startAdaptiveQuest(skillId, statusTarget = byId("form-status")) {
  if (!dashboardState || generatingQuestion) return;
  if (dashboardState.runtime.practice_api_version !== 4) {
    setGenerationStatus(
      statusTarget,
      "Sensei was updated while this dashboard was running. Restart Sensei, then try again.",
      "error",
      skillId,
    );
    return;
  }
  generatingQuestion = true;
  document.body.classList.add("generating");
  setGenerationStatus(statusTarget, "Sensei is drafting and independently checking your encounter…", "working", skillId);
  byId("forge-button").disabled = true;
  byId("new-question").disabled = true;
  try {
    const response = await postJson(
      "/api/study/generate",
      { skill_id: skillId },
      {
        retries: 1,
        onRetry: () => setGenerationStatus(
          statusTarget,
          "The first draft did not finish cleanly. Sensei is trying once more…",
          "working",
          skillId,
        ),
      },
    );
    openArena({ ...response.quest, challenge_token: response.challenge_token });
    setGenerationStatus(statusTarget, "Quest validated. Enter the arena.", "success", skillId);
  } catch (error) {
    void reportClientProblem(error, "startAdaptiveQuest");
    setGenerationStatus(statusTarget, error.message, "error", skillId);
  } finally {
    generatingQuestion = false;
    document.body.classList.remove("generating");
    byId("forge-button").disabled = false;
    byId("new-question").disabled = false;
  }
}

async function createFocus(event) {
  event.preventDefault();
  if (generatingQuestion) return;
  const subject = byId("subject-input").value.trim();
  const topic = byId("topic-input").value.trim();
  if (!subject || !topic) return;
  byId("form-status").textContent = "Adding this focus to your atlas…";
  byId("forge-button").disabled = true;
  try {
    const response = await postJson("/api/study/focus", {
      subject,
      topic,
      context: byId("context-input").value.trim(),
    });
    await loadDashboard();
    await startAdaptiveQuest(response.study_topic.id);
  } catch (error) {
    void reportClientProblem(error, "createFocus");
    byId("form-status").textContent = error.message;
  } finally {
    if (!generatingQuestion) byId("forge-button").disabled = false;
  }
}

function closeArena() {
  activeQuest = null;
  resetArenaFeedback();
  renderGraph(null);
  byId("quest-arena").hidden = true;
}

async function postJson(path, document, { retries = 0, onRetry = null } = {}) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      const response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Sensei-CSRF": dashboardState.csrf_token },
        body: JSON.stringify(document),
      });
      let result = {};
      try {
        result = await response.json();
      } catch {
        // Preserve the HTTP status below when a local connection returns no JSON.
      }
      if (!response.ok) {
        const message = result.error || `Request failed: ${response.status}`;
        const suffix = result.error_id ? ` (Error ID: ${result.error_id})` : "";
        const error = new Error(`${message}${suffix}`);
        error.errorId = result.error_id || "";
        error.retryable = response.status >= 500;
        throw error;
      }
      return result;
    } catch (error) {
      void reportClientProblem(error, `postJson ${path} attempt ${attempt + 1}`);
      const retryable = error.retryable || error instanceof TypeError;
      if (!retryable || attempt >= retries) throw error;
      if (onRetry) onRetry(attempt + 1);
    }
  }
}

async function checkAnswer() {
  if (!activeQuest) return;
  const challengeToken = activeQuest.challenge_token;
  const answer = byId("quest-answer").value.trim();
  if (!answer) { byId("quest-answer").focus(); return; }
  const button = byId("check-answer");
  button.disabled = true;
  resetArenaFeedback();
  try {
    const response = await postJson("/api/quest/check", { challenge_token: challengeToken, answer });
    if (!activeQuest || activeQuest.challenge_token !== challengeToken) return;
    const result = response.result;
    attemptToken = response.attempt_token;
    const feedback = byId("answer-feedback");
    const correct = result.status === "verified_correct";
    feedback.classList.add(correct ? "correct" : "incorrect");
    byId("feedback-status").textContent = correct ? "Victory — your answer holds." : "Not yet — this encounter has another opening.";
    const detail = byId("feedback-detail");
    const showTechnicalDetail = activeQuest.source !== "adaptive";
    detail.textContent = showTechnicalDetail ? result.detail : "";
    detail.hidden = !showTechnicalDetail;
    byId("feedback-expected").textContent = correct ? "" : `Validated answer: ${result.expected}`;
    if (response.solution) {
      byId("solution-text").textContent = response.solution;
      byId("solution-copy").hidden = false;
    }
    byId("record-attempt").hidden = !attemptToken;
    feedback.hidden = false;
  } catch (error) {
    void reportClientProblem(error, "checkAnswer");
    const feedback = byId("answer-feedback");
    feedback.classList.add("inconclusive");
    byId("feedback-status").textContent = "Sensei could not check that answer form.";
    byId("feedback-detail").textContent = error.message;
    byId("feedback-detail").hidden = false;
    feedback.hidden = false;
  } finally {
    button.disabled = false;
  }
}

async function recordAttempt() {
  if (!attemptToken) return;
  const button = byId("record-attempt");
  button.disabled = true;
  try {
    const response = await postJson("/api/quest/record", { attempt_token: attemptToken });
    attemptToken = null;
    byId("feedback-expected").textContent = `Recorded: +${response.progress.xp_awarded} XP · ${Math.round(response.progress.mastery_score)}/100 mastery.`;
    button.hidden = true;
    await loadDashboard();
  } catch (error) {
    void reportClientProblem(error, "recordAttempt");
    byId("feedback-detail").textContent = error.message;
    byId("feedback-detail").hidden = false;
  } finally {
    button.disabled = false;
  }
}

function render(state) {
  dashboardState = state;
  renderProfile(state.profile);
  byId("practiced").textContent = state.study_topics.length;
  renderTopics(state.study_topics);
  renderHistory(state.recent_attempts);
  const modelState = state.runtime.adaptive_generation === "ready" ? "Local practice architect ready" : "Adaptive model unavailable";
  byId("updated-at").textContent = `${modelState} · synced ${new Date(state.generated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  void flushPendingClientProblems();
}

async function loadDashboard() {
  const button = byId("refresh-button");
  button.disabled = true;
  try {
    const response = await fetch("/api/dashboard", { cache: "no-store" });
    const result = await response.json();
    if (!response.ok) {
      const suffix = result.error_id ? ` (Error ID: ${result.error_id})` : "";
      const error = new Error(`${result.error || `Dashboard request failed: ${response.status}`}${suffix}`);
      error.errorId = result.error_id || "";
      throw error;
    }
    render(result);
  } catch (error) {
    void reportClientProblem(error, "loadDashboard");
    byId("updated-at").textContent = "Local memory unavailable — try syncing again";
  } finally {
    button.disabled = false;
  }
}

byId("focus-form").addEventListener("submit", createFocus);
document.querySelectorAll(".nav-tab").forEach((tab, index, tabs) => {
  tab.addEventListener("click", () => showView(tab.dataset.view));
  tab.addEventListener("keydown", (event) => {
    if (!(["ArrowLeft", "ArrowRight"].includes(event.key))) return;
    event.preventDefault();
    const direction = event.key === "ArrowRight" ? 1 : -1;
    const nextTab = tabs[(index + direction + tabs.length) % tabs.length];
    showView(nextTab.dataset.view, { focus: true });
  });
});
document.querySelector(".brand").addEventListener("click", (event) => {
  event.preventDefault();
  showView("dojo");
});
window.addEventListener("hashchange", () => showView(viewFromHash(), { updateHash: false }));
document.querySelectorAll(".prompt-examples button").forEach((button) => {
  button.addEventListener("click", () => {
    byId("subject-input").value = button.dataset.subject;
    byId("topic-input").value = button.dataset.topic;
    byId("topic-input").focus();
  });
});
byId("new-question").addEventListener("click", () => {
  if (activeQuest) startAdaptiveQuest(activeQuest.skill_id, byId("arena-generation-status"));
});
byId("close-arena").addEventListener("click", closeArena);
byId("show-hint").addEventListener("click", () => {
  const hint = byId("hint-copy");
  hint.hidden = !hint.hidden;
  byId("show-hint").textContent = hint.hidden ? "Ask Sensei for a hint" : "Hide Sensei’s hint";
});
byId("check-answer").addEventListener("click", checkAnswer);
byId("record-attempt").addEventListener("click", recordAttempt);
byId("quest-answer").addEventListener("keydown", (event) => { if (event.key === "Enter") checkAnswer(); });
byId("refresh-button").addEventListener("click", loadDashboard);
showView(viewFromHash());
loadDashboard();
setInterval(() => { if (!document.hidden && !generatingQuestion) loadDashboard(); }, 30000);
