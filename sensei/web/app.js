"use strict";

const byId = (id) => document.getElementById(id);
const historyTemplate = byId("history-template");
const viewNames = ["study", "history"];
const viewTitles = {
  study: "Study // Sensei",
  "history": "Learning history // Sensei",
};
let dashboardState = null;
let activeQuest = null;
let attemptToken = null;
let activeSessionSkillId = null;
let activeFeedback = null;
let helpExhausted = false;
let revealingHelp = false;
let checkingAnswer = false;
let generatingQuestion = false;
const generationStatuses = new Map();
const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
const CLIENT_ERROR_STORAGE_KEY = "sensei.study-client-errors.v1";
const MAX_PENDING_CLIENT_ERRORS = 25;
const reportedClientErrors = new WeakSet();
const PRACTICE_API_VERSION = 8;
const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;
const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"];
let partAnswers = {};
let currentPlan = null;
let importMode = "file";
let analyzing = false;
let activeLesson = null;
let activeLessonSkillId = null;
let lessonProgress = null;
let revealedLessonStep = 0;
let generatingLesson = false;
let checkingLesson = false;
let askingLesson = false;


function viewFromHash() {
  const requestedView = window.location.hash.slice(1);
  return viewNames.includes(requestedView) ? requestedView : "study";
}

function showView(viewName, { updateHash = true, focus = false } = {}) {
  const nextView = viewNames.includes(viewName) ? viewName : "study";
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

function renderNotation(target) {
  if (!target || typeof window.renderMathInElement !== "function") return;
  try {
    window.renderMathInElement(target, {
      delimiters: [
        { left: "\\[", right: "\\]", display: true },
        { left: "\\(", right: "\\)", display: false },
      ],
      throwOnError: false,
      strict: "ignore",
      trust: false,
    });
  } catch (error) {
    void reportClientProblem(error, "renderNotation");
  }
}

function normalizeNotationEscapes(copy) {
  return String(copy || "").replace(/\\{2,}(?=[A-Za-z()[\]])/g, "\\");
}

function isInsideNotation(copy, position) {
  const delimiters = /\\([()[\]])/g;
  let activeDelimiter = "";
  let match = delimiters.exec(copy);
  while (match && match.index < position) {
    const token = match[1];
    if (token === "(" || token === "[") {
      activeDelimiter = token;
    } else if (activeDelimiter === (token === ")" ? "(" : "[")) {
      activeDelimiter = "";
    }
    match = delimiters.exec(copy);
  }
  return Boolean(activeDelimiter);
}

function repairArrayRows(body) {
  return body.replace(/\\hline/g, (command, offset) => {
    const prefix = body.slice(0, offset);
    return /\\\\\s*$/.test(prefix) ? command : `\\\\ ${command}`;
  });
}

function normalizeNotationStructure(copy) {
  const normalized = normalizeNotationEscapes(copy);
  const environments = /\\begin\{(array|tabular|aligned|gathered|matrix|pmatrix|bmatrix|vmatrix|Vmatrix|cases)\}([\s\S]*?)\\end\{\1\}/g;
  let repaired = "";
  let cursor = 0;
  let match = environments.exec(normalized);
  while (match) {
    repaired += normalized.slice(cursor, match.index);
    const name = match[1] === "tabular" ? "array" : match[1];
    const body = name === "array" ? repairArrayRows(match[2]) : match[2];
    const environment = `\\begin{${name}}${body}\\end{${name}}`;
    repaired += isInsideNotation(normalized, match.index)
      ? environment
      : `\\[${environment}\\]`;
    cursor = match.index + match[0].length;
    match = environments.exec(normalized);
  }
  return repaired + normalized.slice(cursor);
}

function setNotationText(target, copy) {
  target.textContent = normalizeNotationStructure(copy);
  renderNotation(target);
}

function inlineOptionNotation(copy) {
  return normalizeNotationStructure(copy)
    .replaceAll("\\[", "\\(")
    .replaceAll("\\]", "\\)")
    .replace(/^\s*[A-D][.)]\s+/i, "");
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


function relativeMoment(value) {
  const target = new Date(value);
  if (Number.isNaN(target.getTime())) return "recently";
  const days = Math.floor((Date.now() - target.getTime()) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}


function trainTopic(topic, statusTarget) {
  showView("study");
  void startAdaptiveQuest(topic.id, statusTarget || byId("arena-generation-status"), { resetSession: true });
}


function renderHistory(attempts) {
  const list = byId("history-list");
  list.replaceChildren();
  if (!attempts.length) {
    const empty = document.createElement("p");
    empty.className = "empty-history";
    empty.textContent = "No practice yet. Upload a guide to get started.";
    list.append(empty);
    return;
  }
  attempts.slice(0, 8).forEach((attempt) => {
    const row = historyTemplate.content.firstElementChild.cloneNode(true);
    row.dataset.outcome = attempt.outcome;
    row.querySelector(".history-skill").textContent = `${attempt.course} · ${attempt.skill_name}`;
    setNotationText(row.querySelector(".history-problem"), attempt.problem);
    const source = attempt.effective_outcome_source === "verifier" ? "checked " : "";
    row.querySelector(".history-outcome").textContent = `${source}${attempt.outcome}`;
    const time = row.querySelector(".history-time");
    time.dateTime = attempt.created_at;
    time.textContent = relativeMoment(attempt.created_at);
    list.append(row);
  });
}

function studyTopicById(skillId) {
  return dashboardState?.study_topics.find((topic) => topic.id === skillId) || null;
}

function beginPracticeSession(topic) {
  activeSessionSkillId = topic.id;
  activeQuest = null;
  activeFeedback = null;
  attemptToken = null;
  resetArenaFeedback();
  renderGraph(null);
  byId("practice-panel").hidden = true;
  byId("chat-history").replaceChildren();

}

function resetArenaFeedback() {
  attemptToken = null;
  activeFeedback = null;
  byId("learner-answer-turn").hidden = true;
  byId("learner-answer-copy").textContent = "";
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
  byId("continue-practice").hidden = true;
  byId("practice-answer").disabled = false;
  byId("check-answer").disabled = false;
  byId("part-results").replaceChildren();
  byId("part-results").hidden = true;
  byId("likely-mistake").textContent = "";
  byId("likely-mistake").hidden = true;
  byId("part-list").querySelectorAll("input, button").forEach((control) => { control.disabled = false; });
}

function resetProgressiveHelp() {
  helpExhausted = false;
  revealingHelp = false;
  byId("help-steps").replaceChildren();
  byId("help-panel").hidden = true;
  const reward = byId("help-reward");
  reward.textContent = "";
  reward.classList.remove("final");
  const button = byId("ask-sensei-help");
  button.textContent = "Ask Sensei for help";
  button.disabled = false;
}

function renderOptions(quest) {
  const grid = byId("option-grid");
  grid.replaceChildren();
  grid.hidden = quest.answer_type !== "multiple_choice";
  grid.classList.toggle(
    "has-notation",
    quest.options.some((option) => /\\[[(]/.test(option)),
  );
  quest.options.forEach((option, index) => {
    const letter = String.fromCharCode(65 + index);
    const button = document.createElement("button");
    button.type = "button";
    const badge = document.createElement("span");
    badge.className = "option-letter";
    badge.textContent = letter;
    const copy = document.createElement("b");
    setNotationText(copy, inlineOptionNotation(option));
    button.append(badge, copy);
    button.addEventListener("click", () => {
      grid.querySelectorAll("button").forEach((item) => item.classList.remove("selected"));
      button.classList.add("selected");
      byId("practice-answer").value = letter;
    });
    grid.append(button);
  });
}

function openArena(quest) {
  byId("chat-history").replaceChildren();
  closeLesson();
  activeQuest = quest;
  showView("study");
  resetArenaFeedback();
  byId("arena-skill").textContent = `${quest.subject} · ${quest.skill_name}`;
  byId("arena-title").textContent = "Practice chat";
  byId("problem-title").textContent = quest.title;
  setNotationText(byId("arena-prompt"), quest.prompt);
  renderGraph(quest.graph);
  byId("practice-answer").value = "";
  byId("practice-answer").placeholder = quest.answer_type === "multiple_choice" ? "Choose A, B, C, or D" : "Enter only the requested value";
  const multiPart = quest.answer_type === "multi_part";
  byId("practice-answer").hidden = multiPart;
  byId("check-answer").textContent = multiPart ? "Check all parts" : "Send answer";
  const hint = byId("notation-help");
  hint.textContent = multiPart ? "Answer every part, then check them together." : (quest.answer_format_hint || "");
  hint.hidden = !hint.textContent;
  resetProgressiveHelp();
  renderOptions(quest);
  renderParts(quest);
  const arena = byId("practice-panel");
  arena.hidden = false;
  arena.scrollIntoView({ behavior: "smooth", block: "start" });
  if (multiPart) {
    byId("part-list").querySelector(".part-answer")?.focus({ preventScroll: true });
  } else if (quest.answer_type !== "multiple_choice") {
    byId("practice-answer").focus({ preventScroll: true });
  }
}

async function startAdaptiveQuest(
  skillId,
  statusTarget = byId("arena-generation-status"),
  { resetSession = false } = {},
) {
  if (!dashboardState || generatingQuestion || generatingLesson) return;
  if (dashboardState.runtime.practice_api_version !== PRACTICE_API_VERSION) {
    setGenerationStatus(
      statusTarget,
      "Sensei was updated while this dashboard was running. Restart Sensei, then try again.",
      "error",
      skillId,
    );
    return;
  }
  const topic = studyTopicById(skillId);
  if (!topic) {
    setGenerationStatus(statusTarget, "That concept is no longer available.", "error", skillId);
    return;
  }
  if (resetSession || activeSessionSkillId !== skillId) beginPracticeSession(topic);
  generatingQuestion = true;
  document.body.classList.add("generating");
  setGenerationStatus(statusTarget, "Sensei is drafting and independently checking your next question…", "working", skillId);
  byId("new-question").disabled = true;
  byId("continue-practice").disabled = true;
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
    if (!studyTopicById(skillId)) return;
    openArena({ ...response.quest, challenge_token: response.challenge_token });
    setGenerationStatus(statusTarget, "Problem validated. Your practice chat is ready.", "success", skillId);
  } catch (error) {
    void reportClientProblem(error, "startAdaptiveQuest");
    setGenerationStatus(statusTarget, error.message, "error", skillId);
  } finally {
    generatingQuestion = false;
    document.body.classList.remove("generating");
    byId("new-question").disabled = false;
    byId("continue-practice").disabled = false;
  }
}

function closeArena() {
  activeQuest = null;
  activeSessionSkillId = null;
  resetArenaFeedback();
  resetProgressiveHelp();
  renderGraph(null);
  byId("chat-history").replaceChildren();
  byId("practice-panel").hidden = true;
}

// ---------------------------------------------------------------------------
// Guided lessons (separate from practice)
// ---------------------------------------------------------------------------

function lessonMessage(roleText, { learner = false, feedback = "" } = {}) {
  const article = document.createElement("article");
  if (feedback) {
    article.className = `answer-feedback sensei-feedback-message ${feedback}`;
  } else {
    article.className = `chat-message ${learner ? "learner-message" : "sensei-chat-message"}`;
  }
  const avatar = document.createElement("span");
  avatar.className = learner ? "chat-avatar" : "chat-avatar sensei-chat-avatar";
  avatar.setAttribute("aria-hidden", "true");
  avatar.textContent = learner ? "You" : "道";
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble";
  const role = document.createElement("p");
  role.className = "chat-role";
  role.textContent = roleText;
  bubble.append(role);
  article.append(avatar, bubble);
  return { article, bubble };
}

function notationParagraph(copy, className = "") {
  const paragraph = document.createElement("p");
  if (className) paragraph.className = className;
  setNotationText(paragraph, copy);
  return paragraph;
}

function lessonStepMessage(step, index) {
  const passed = index < lessonProgress.current_step;
  const { article, bubble } = lessonMessage(`Sensei · Step ${index + 1} of ${activeLesson.step_count}`);
  bubble.classList.add("lesson-step-bubble");
  const heading = document.createElement("h3");
  setNotationText(heading, step.title);
  bubble.append(heading, notationParagraph(step.explanation));
  if (step.worked_example) {
    const example = document.createElement("div");
    example.className = "solution-copy lesson-example";
    const label = document.createElement("strong");
    label.textContent = "Worked example";
    example.append(label, notationParagraph(step.worked_example));
    bubble.append(example);
  }
  const takeaway = document.createElement("div");
  takeaway.className = "help-panel lesson-takeaway";
  const takeawayLabel = document.createElement("strong");
  takeawayLabel.textContent = "Key takeaway";
  takeaway.append(takeawayLabel, notationParagraph(step.key_takeaway));
  bubble.append(takeaway);
  const checkIn = document.createElement("div");
  checkIn.className = "lesson-check-in";
  const checkLabel = document.createElement("strong");
  checkLabel.textContent = passed ? "Check-in · passed" : "Check-in";
  if (passed) checkLabel.classList.add("lesson-passed");
  checkIn.append(checkLabel, notationParagraph(step.check_in));
  bubble.append(checkIn);
  return article;
}

function lessonCompletionMessage() {
  const { article, bubble } = lessonMessage("Sensei", { feedback: "correct lesson-complete" });
  const status = document.createElement("p");
  status.className = "feedback-status";
  status.textContent = "Lesson complete";
  const note = document.createElement("p");
  note.textContent = "Now try it yourself to see what you can apply independently.";
  const actions = document.createElement("div");
  actions.className = "feedback-actions";
  const train = document.createElement("button");
  train.type = "button";
  train.className = "primary-button";
  train.textContent = "Check understanding";
  train.addEventListener("click", () => {
    const topic = studyTopicById(activeLessonSkillId);
    if (topic) trainTopic(topic);
  });
  const restart = document.createElement("button");
  restart.type = "button";
  restart.className = "secondary-button";
  restart.textContent = "Start lesson over";
  restart.addEventListener("click", restartLesson);
  actions.append(train, restart);
  bubble.append(status, note, actions);
  return article;
}

function renderLesson() {
  const thread = byId("lesson-thread");
  thread.replaceChildren();
  if (!activeLesson || !lessonProgress) return;
  const total = activeLesson.step_count;
  const current = lessonProgress.current_step;
  const complete = lessonProgress.status === "complete";
  const overview = lessonMessage("Sensei · Lesson plan");
  overview.bubble.classList.add("lesson-step-bubble");
  const title = document.createElement("h3");
  setNotationText(title, activeLesson.title);
  overview.bubble.append(title, notationParagraph(activeLesson.overview));
  thread.append(overview.article);
  const lastVisible = complete ? total - 1 : Math.min(revealedLessonStep, total - 1);
  activeLesson.steps.slice(0, lastVisible + 1).forEach((step, index) => {
    thread.append(lessonStepMessage(step, index));
  });
  if (complete) {
    const summary = lessonMessage("Sensei · Closing summary");
    summary.bubble.classList.add("lesson-step-bubble");
    summary.article.classList.add("lesson-closing");
    summary.bubble.append(notationParagraph(activeLesson.closing_summary));
    thread.append(summary.article, lessonCompletionMessage());
  }
  renderLessonProgress();
  byId("lesson-check-composer").hidden = complete || revealedLessonStep !== current;
  byId("lesson-answer").value = "";
}

function renderLessonProgress() {
  if (!activeLesson || !lessonProgress) return;
  const total = activeLesson.step_count;
  const current = lessonProgress.current_step;
  const complete = lessonProgress.status === "complete";
  byId("lesson-progress-label").textContent = complete
    ? `All ${total} steps complete`
    : `${current} of ${total} steps passed · now on step ${Math.min(current + 1, total)}`;
  byId("lesson-progress-bar").style.width = `${clamp((current / total) * 100, 0, 100)}%`;
}

function openLesson(topic, lesson, progress) {
  closeArena();
  activeLesson = lesson;
  activeLessonSkillId = topic.id;
  lessonProgress = progress;
  revealedLessonStep = Math.min(progress.current_step, lesson.step_count - 1);
  showView("study");
  byId("lesson-skill").textContent = `${topic.course} · ${topic.name}`;
  byId("lesson-title").textContent = "Guided lesson";
  renderLesson();
  const panel = byId("lesson-panel");
  panel.hidden = false;
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
  if (!byId("lesson-check-composer").hidden) byId("lesson-answer").focus({ preventScroll: true });
}

function closeLesson() {
  activeLesson = null;
  activeLessonSkillId = null;
  lessonProgress = null;
  revealedLessonStep = 0;
  byId("lesson-thread").replaceChildren();
  byId("lesson-panel").hidden = true;
}

async function startLesson(
  skillId,
  statusTarget = byId("lesson-generation-status"),
  { restart = false } = {},
) {
  if (!dashboardState || generatingLesson || generatingQuestion) return;
  if (dashboardState.runtime.practice_api_version !== PRACTICE_API_VERSION) {
    setGenerationStatus(
      statusTarget,
      "Sensei was updated while this dashboard was running. Restart Sensei, then try again.",
      "error",
      skillId,
    );
    return;
  }
  const topic = studyTopicById(skillId);
  if (!topic) {
    setGenerationStatus(statusTarget, "That concept is no longer available.", "error", skillId);
    return;
  }
  const fresh = restart || topic.lesson_status === "none";
  generatingLesson = true;
  document.body.classList.add("generating");
  setGenerationStatus(
    statusTarget,
    fresh ? "Sensei is writing and independently checking your lesson…" : "Opening your saved lesson…",
    "working",
    skillId,
  );
  byId("lesson-restart").disabled = true;
  try {
    const response = await postJson("/api/study/learn/start", { skill_id: skillId, restart }, {
        retries: fresh ? 1 : 0,
        onRetry: () => setGenerationStatus(
          statusTarget,
          "The first draft did not finish cleanly. Sensei is trying once more…",
          "working",
          skillId,
        ),
      },
    );
    if (!studyTopicById(skillId)) return;
    openLesson(topic, response.lesson, response.progress);
    setGenerationStatus(
      statusTarget,
      response.generated ? "Lesson validated. Work through it one step at a time." : "Your saved lesson is ready.",
      "success",
      skillId,
    );
    if (response.generated) void loadDashboard();
  } catch (error) {
    void reportClientProblem(error, "startLesson");
    setGenerationStatus(statusTarget, error.message, "error", skillId);
  } finally {
    generatingLesson = false;
    document.body.classList.remove("generating");
    byId("lesson-restart").disabled = false;
  }
}

function restartLesson() {
  if (!activeLessonSkillId || generatingLesson) return;
  const confirmed = window.confirm(
    "Start this lesson over?\n\nSensei writes a new lesson for this topic and replaces your progress in the current one. You can practice again after the lesson.",
  );
  if (!confirmed) return;
  void startLesson(activeLessonSkillId, byId("lesson-generation-status"), { restart: true });
}

function lessonErrorMessage(message) {
  const { article, bubble } = lessonMessage("Sensei", { feedback: "incorrect" });
  const status = document.createElement("p");
  status.className = "feedback-status";
  status.textContent = message;
  bubble.append(status);
  return article;
}

async function checkLessonStep() {
  if (!activeLesson || !lessonProgress || checkingLesson || lessonProgress.status === "complete") return;
  const input = byId("lesson-answer");
  const answer = input.value.trim();
  if (!answer) {
    input.focus();
    return;
  }
  const skillId = activeLessonSkillId;
  const stepIndex = lessonProgress.current_step;
  checkingLesson = true;
  input.disabled = true;
  byId("lesson-check").disabled = true;
  const thread = byId("lesson-thread");
  const learner = lessonMessage("Your answer", { learner: true });
  learner.bubble.append(notationParagraph(answer));
  thread.append(learner.article);
  try {
    const response = await postJson("/api/study/learn/check", {
      skill_id: skillId,
      step_index: stepIndex,
      answer,
    });
    if (activeLessonSkillId !== skillId) return;
    lessonProgress = response.progress;
    renderLessonProgress();
    const feedback = lessonMessage("Sensei", { feedback: response.verdict });
    const verdict = document.createElement("p");
    verdict.className = "feedback-status";
    verdict.textContent = {
      correct: "Correct — step passed",
      partial: "Close enough — step passed",
      incorrect: "Not yet — try again",
    }[response.verdict] || "Checked";
    feedback.bubble.append(verdict, notationParagraph(response.feedback));
    if (response.completed) {
      renderLesson();
      const closing = thread.querySelector(".lesson-closing");
      if (closing) {
        thread.insertBefore(feedback.article, closing);
      } else {
        thread.append(feedback.article);
      }
      void loadDashboard();
    } else {
      if (response.verdict !== "incorrect") {
        const actions = document.createElement("div");
        actions.className = "feedback-actions";
        const next = document.createElement("button");
        next.type = "button";
        next.className = "primary-button";
        next.textContent = "Next step";
        next.addEventListener("click", () => {
          revealedLessonStep = lessonProgress.current_step;
          renderLesson();
          byId("lesson-answer").focus({ preventScroll: true });
          thread.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "start" });
        });
        actions.append(next);
        feedback.bubble.append(actions);
        byId("lesson-check-composer").hidden = true;
        void loadDashboard();
      }
      thread.append(feedback.article);
      input.value = "";
    }
    feedback.article.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) {
    void reportClientProblem(error, "checkLessonStep");
    thread.append(lessonErrorMessage(error.message));
  } finally {
    checkingLesson = false;
    input.disabled = false;
    byId("lesson-check").disabled = false;
  }
}

async function askLessonQuestion() {
  if (!activeLesson || !lessonProgress || askingLesson) return;
  const input = byId("lesson-question");
  const question = input.value.trim();
  if (!question) {
    input.focus();
    return;
  }
  const skillId = activeLessonSkillId;
  const stepIndex = Math.min(revealedLessonStep, activeLesson.step_count - 1);
  askingLesson = true;
  input.disabled = true;
  byId("lesson-ask").disabled = true;
  const thread = byId("lesson-thread");
  const learner = lessonMessage("Your question", { learner: true });
  learner.bubble.append(notationParagraph(question));
  thread.append(learner.article);
  try {
    const response = await postJson("/api/study/learn/ask", {
      skill_id: skillId,
      step_index: stepIndex,
      question,
    });
    if (activeLessonSkillId !== skillId) return;
    const reply = lessonMessage(`Sensei · About step ${stepIndex + 1}`);
    reply.bubble.classList.add("lesson-step-bubble");
    reply.bubble.append(notationParagraph(response.answer));
    thread.append(reply.article);
    reply.article.scrollIntoView({ behavior: "smooth", block: "nearest" });
    input.value = "";
  } catch (error) {
    void reportClientProblem(error, "askLessonQuestion");
    thread.append(lessonErrorMessage(error.message));
  } finally {
    askingLesson = false;
    input.disabled = false;
    byId("lesson-ask").disabled = false;
  }
}

async function askSenseiForHelp() {
  if (!activeQuest || activeFeedback || helpExhausted || revealingHelp) return;
  const challengeToken = activeQuest.challenge_token;
  const button = byId("ask-sensei-help");
  revealingHelp = true;
  button.disabled = true;
  byId("check-answer").disabled = true;
  try {
    const response = await postJson("/api/practice/help", { challenge_token: challengeToken });
    if (!activeQuest || activeQuest.challenge_token !== challengeToken) return;
    helpExhausted = response.final_answer;
    const step = document.createElement("li");
    setNotationText(step, response.step);
    byId("help-steps").append(step);
    byId("help-panel").hidden = false;
    const reward = byId("help-reward");
    if (response.final_answer) {
      reward.textContent = "You’ve seen the solution. A fresh question will check your independent understanding.";
      reward.classList.add("final");
      button.textContent = "Final answer revealed";
    } else {
      reward.textContent = `Step ${response.step_number} of ${response.total_steps}. Sensei will remember that you used support here.`;
      reward.classList.remove("final");
      button.textContent = "Ask Sensei for help";
    }
  } catch (error) {
    void reportClientProblem(error, "askSenseiForHelp");
    const reward = byId("help-reward");
    reward.textContent = error.message;
    reward.classList.add("final");
    byId("help-panel").hidden = false;
  } finally {
    revealingHelp = false;
    button.disabled = helpExhausted || Boolean(activeFeedback);
    byId("check-answer").disabled = Boolean(activeFeedback);
  }
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
  if (!activeQuest || revealingHelp || checkingAnswer || activeFeedback) return;
  const challengeToken = activeQuest.challenge_token;
  const multiPart = activeQuest.answer_type === "multi_part";
  let answer;
  if (multiPart) {
    answer = {};
    for (const part of activeQuest.parts || []) {
      const value = String(partAnswers[part.label] || "").trim();
      if (!value) {
        byId("part-list").querySelector(`[data-part="${part.label}"] .part-answer`)?.focus();
        byId("notation-help").textContent = `Answer part (${part.label}) before checking.`;
        byId("notation-help").hidden = false;
        return;
      }
      answer[part.label] = value;
    }
  } else {
    answer = byId("practice-answer").value.trim();
    if (!answer) { byId("practice-answer").focus(); return; }
  }
  const button = byId("check-answer");
  checkingAnswer = true;
  resetArenaFeedback();
  button.disabled = true;
  byId("ask-sensei-help").disabled = true;
  try {
    const response = await postJson("/api/practice/check", { challenge_token: challengeToken, answer });
    if (!activeQuest || activeQuest.challenge_token !== challengeToken) return;
    const result = response.result;
    attemptToken = response.attempt_token;
    const feedback = byId("answer-feedback");
    const outcome = response.outcome || (result.status === "verified_correct" ? "correct" : "incorrect");
    const correct = outcome === "correct";
    activeFeedback = { correct, outcome };
    const submittedCopy = multiPart
      ? (activeQuest.parts || []).map((part) => `(${part.label}) ${answer[part.label]}`).join("   ")
      : (activeQuest.answer_type === "expression" && result.submitted_latex
        ? `\\(${result.submitted_latex}\\)`
        : answer);
    setNotationText(byId("learner-answer-copy"), submittedCopy);
    byId("learner-answer-turn").hidden = false;
    feedback.classList.add(correct ? "correct" : outcome === "partial" ? "partial" : "incorrect");
    const parts = Array.isArray(response.parts) ? response.parts : [];
    const correctParts = parts.filter((part) => part.status === "verified_correct").length;
    byId("feedback-status").textContent = correct
      ? "That’s correct."
      : outcome === "partial"
        ? `Partial — ${correctParts} of ${parts.length} parts hold.`
        : "Not quite yet. Let’s work through it.";
    const detail = byId("feedback-detail");
    const showTechnicalDetail = activeQuest.source !== "adaptive";
    setNotationText(detail, showTechnicalDetail ? result.detail : "");
    detail.hidden = !showTechnicalDetail;
    if (multiPart) {
      renderPartResults(parts);
      byId("feedback-expected").textContent = "";
    } else {
      const expectedCopy = result.expected_latex
        ? `Validated answer: \\(${result.expected_latex}\\)`
        : `Validated answer: ${result.expected || ""}`;
      setNotationText(byId("feedback-expected"), correct ? "" : expectedCopy);
    }
    if (response.likely_mistake) {
      const mistake = byId("likely-mistake");
      setNotationText(mistake, `Sensei noticed: ${response.likely_mistake}`);
      mistake.hidden = false;
    }
    if (response.solution) {
      setNotationText(byId("solution-text"), response.solution);
      byId("solution-copy").hidden = false;
    }
    byId("record-attempt").hidden = !attemptToken;
    feedback.hidden = false;
    feedback.scrollIntoView({ behavior: "smooth", block: "nearest" });
    byId("practice-answer").disabled = true;
    byId("option-grid").querySelectorAll("button").forEach((option) => { option.disabled = true; });
    byId("part-list").querySelectorAll("input, button").forEach((control) => { control.disabled = true; });
    byId("ask-sensei-help").disabled = true;
    if (attemptToken) await recordAttempt();
  } catch (error) {
    void reportClientProblem(error, "checkAnswer");
    const feedback = byId("answer-feedback");
    feedback.classList.add("inconclusive");
    byId("feedback-status").textContent = "Sensei could not check that answer form.";
    byId("feedback-detail").textContent = error.message;
    byId("feedback-detail").hidden = false;
    feedback.hidden = false;
  } finally {
    checkingAnswer = false;
    button.disabled = Boolean(activeFeedback);
    byId("ask-sensei-help").disabled = helpExhausted || Boolean(activeFeedback);
  }
}

async function recordAttempt() {
  if (!attemptToken) return;
  const button = byId("record-attempt");
  button.disabled = true;
  try {
    const response = await postJson("/api/practice/record", { attempt_token: attemptToken });
    attemptToken = null;
    byId("feedback-detail").textContent = "Progress saved. Sensei will use this answer and any help you needed to plan your next step.";
    byId("feedback-detail").hidden = false;
    button.hidden = true;
    byId("continue-practice").hidden = false;
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

  renderStudySets();
  renderHistory(state.recent_attempts);
  const modelState = state.runtime.adaptive_generation === "ready" ? "LLM API ready" : "LLM API unavailable";
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


function renderParts(quest) {
  const list = byId("part-list");
  list.replaceChildren();
  partAnswers = {};
  const parts = Array.isArray(quest.parts) ? quest.parts : [];
  list.hidden = parts.length === 0;
  parts.forEach((part) => {
    const row = document.createElement("li");
    row.className = "part-row";
    row.dataset.part = part.label;
    const label = document.createElement("span");
    label.className = "part-label";
    label.textContent = `(${part.label})`;
    const body = document.createElement("div");
    body.className = "part-body";
    const prompt = document.createElement("p");
    prompt.className = "part-prompt";
    setNotationText(prompt, part.prompt);
    body.append(prompt);
    if (part.answer_type === "multiple_choice") {
      const options = document.createElement("div");
      options.className = "option-grid part-options";
      options.classList.toggle("has-notation", (part.options || []).some((option) => /\\[[(]/.test(option)));
      (part.options || []).forEach((option, index) => {
        const letter = String.fromCharCode(65 + index);
        const button = document.createElement("button");
        button.type = "button";
        const badge = document.createElement("span");
        badge.className = "option-letter";
        badge.textContent = letter;
        const copy = document.createElement("b");
        setNotationText(copy, inlineOptionNotation(option));
        button.append(badge, copy);
        button.addEventListener("click", () => {
          options.querySelectorAll("button").forEach((item) => item.classList.remove("selected"));
          button.classList.add("selected");
          partAnswers[part.label] = letter;
        });
        options.append(button);
      });
      body.append(options);
    } else {
      const input = document.createElement("input");
      input.type = "text";
      input.className = "part-answer";
      input.maxLength = 500;
      input.autocomplete = "off";
      input.spellcheck = false;
      input.placeholder = part.unit ? `Answer in ${part.unit}` : "Type your answer";
      input.setAttribute("aria-label", `Answer for part ${part.label}`);
      input.addEventListener("input", () => { partAnswers[part.label] = input.value; });
      input.addEventListener("keydown", (event) => { if (event.key === "Enter") checkAnswer(); });
      body.append(input);
      if (part.answer_format_hint) {
        const hint = document.createElement("p");
        hint.className = "part-hint";
        hint.textContent = part.answer_format_hint;
        body.append(hint);
      }
    }
    row.append(label, body);
    list.append(row);
  });
}

function renderPartResults(parts) {
  const list = byId("part-results");
  list.replaceChildren();
  parts.forEach((part) => {
    const row = document.createElement("li");
    const correct = part.status === "verified_correct";
    row.className = `part-result ${correct ? "correct" : "incorrect"}`;
    const label = document.createElement("strong");
    label.textContent = `(${part.label}) ${correct ? "holds" : "not yet"}`;
    row.append(label);
    if (!correct) {
      const expected = document.createElement("span");
      setNotationText(
        expected,
        part.expected_latex ? `Validated answer: \\(${part.expected_latex}\\)` : `Validated answer: ${part.expected || ""}`,
      );
      row.append(expected);
    }
    list.append(row);
  });
  list.hidden = parts.length === 0;
}


function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      resolve(result.slice(result.indexOf(",") + 1));
    };
    reader.onerror = () => reject(reader.error || new Error("The file could not be read."));
    reader.readAsDataURL(file);
  });
}


function guideForSkill(skillId) {
  return (dashboardState?.study_guides || []).find((guide) => guide.concepts.some((concept) => concept.skill_id === skillId));
}

function followGuide(guide, statusTarget) {
  if (!guide?.next) return;
  const next = guide.next;
  if (next.action === "learn") {
    void startLesson(next.skill_id, statusTarget, { restart: false });
  } else {
    void startAdaptiveQuest(next.skill_id, statusTarget, { resetSession: activeSessionSkillId !== next.skill_id });
  }
}

function renderStudySets() {
  const container = byId("study-sets");
  container.replaceChildren();
  const guides = dashboardState.study_guides || [];
  byId("empty-study-sets").hidden = guides.length > 0;
  byId("study-sets-summary").textContent = guides.length ? "Sensei chooses the next step from your answers." : "";
  guides.forEach((guide) => {
    const section = document.createElement("article");
    section.className = "panel guide-card";
    const eyebrow = notationParagraph(guide.subject || guide.course || "Study guide", "eyebrow");
    const title = document.createElement("h3");
    title.textContent = guide.name;
    const coverage = notationParagraph(`${guide.checked} of ${guide.concepts.length} concepts checked · understanding grows through practice`, "guide-coverage");
    section.append(eyebrow, title, coverage);
    if (guide.next) {
      const focus = document.createElement("h4");
      focus.textContent = `Next: ${guide.next.name}`;
      const reason = notationParagraph(guide.next.reason);
      const status = document.createElement("p");
      status.className = "generation-status";
      status.setAttribute("role", "status");
      restoreGenerationStatus(status, guide.next.skill_id);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "primary-button";
      button.textContent = guide.next.label;
      button.addEventListener("click", () => followGuide(guide, status));
      section.append(focus, reason, button, status);
    }
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "What Sensei is learning about you";
    details.append(summary);
    const list = document.createElement("ul");
    guide.concepts.forEach((concept) => {
      const row = document.createElement("li");
      row.textContent = `${concept.name} — ${concept.status}`;
      concept.mistakes.forEach((mistake) => row.append(notationParagraph(`Possible gap: ${mistake}`)));
      list.append(row);
    });
    details.append(list);
    section.append(details);
    container.append(section);
  });
}

function setImportMode(mode) {
  importMode = mode === "text" ? "text" : "file";
  byId("import-file-row").hidden = importMode !== "file";
  byId("import-text-row").hidden = importMode !== "text";
  byId("import-mode-file").classList.toggle("active", importMode === "file");
  byId("import-mode-file").setAttribute("aria-pressed", String(importMode === "file"));
  byId("import-mode-text").classList.toggle("active", importMode === "text");
  byId("import-mode-text").setAttribute("aria-pressed", String(importMode === "text"));
}

function utf8ToBase64(text) {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(index, index + chunk));
  }
  return btoa(binary);
}

async function importPayload() {
  if (importMode === "text") {
    const text = byId("import-text").value.trim();
    if (!text) {
      byId("import-text").focus();
      throw new Error("Paste the study guide text first.");
    }
    return { filename: "study-guide.txt", media_base64: utf8ToBase64(text), media_type: "text/plain" };
  }
  const file = byId("import-file").files?.[0];
  if (!file) throw new Error("Choose a PDF or photo of your study guide first.");
  const isPdf = file.type === "application/pdf";
  if (!isPdf && !IMAGE_TYPES.includes(file.type)) {
    throw new Error("Upload a PDF or a PNG, JPEG, or WebP image.");
  }
  if (file.size > (isPdf ? MAX_UPLOAD_BYTES : MAX_IMAGE_BYTES)) {
    throw new Error(isPdf ? "PDF files must be 20 MB or smaller." : "Images must be 8 MB or smaller.");
  }
  return { filename: file.name, media_base64: await fileToBase64(file), media_type: file.type };
}

async function analyzeStudyGuide(event) {
  event.preventDefault();
  if (analyzing || !dashboardState) return;
  const status = byId("import-status");
  const button = byId("import-button");
  analyzing = true;
  button.disabled = true;
  try {
    const payload = await importPayload();
    payload.subject_hint = byId("import-subject").value.trim();
    payload.set_name_hint = byId("import-set-name").value.trim();
    setGenerationStatus(status, "Sensei is reading the document and mapping the skills it expects. This can take a minute or two…", "working");
    const response = await postJson("/api/study/plan/scan", payload);
    renderPlanReview(response.plan);
    setGenerationStatus(status, "Review the plan below, then create it.", "success");
  } catch (error) {
    void reportClientProblem(error, "analyzeStudyGuide");
    setGenerationStatus(status, error.message, "error");
  } finally {
    analyzing = false;
    button.disabled = false;
  }
}

function renderPlanReview(plan) {
  currentPlan = plan;
  byId("plan-subject").value = plan.subject || "";
  byId("plan-set-name").value = plan.set_name || "";
  byId("plan-profile").value = plan.course_profile || "";
  const list = byId("plan-topics");
  list.replaceChildren();
  (plan.topics || []).forEach((topic, index) => {
    const row = document.createElement("li");
    row.className = "plan-topic";
    row.dataset.index = String(index);
    const head = document.createElement("div");
    head.className = "plan-topic-head";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = true;
    checkbox.setAttribute("aria-label", `Include ${topic.name}`);
    const name = document.createElement("input");
    name.type = "text";
    name.maxLength = 120;
    name.value = topic.name || "";
    name.dataset.field = "name";
    name.setAttribute("aria-label", "Concept name");
    const section = document.createElement("span");
    section.className = "plan-topic-section";
    section.textContent = topic.section ? `§ ${topic.section}` : "";
    const materials = Array.isArray(topic.materials) ? topic.materials : [];
    const count = document.createElement("span");
    count.className = "plan-topic-count";
    count.textContent = `${materials.length} example${materials.length === 1 ? "" : "s"}`;
    head.append(checkbox, name, section, count);
    const details = document.createElement("details");
    details.className = "plan-topic-details";
    const summary = document.createElement("summary");
    summary.textContent = "Practice brief and examples";
    const brief = document.createElement("textarea");
    brief.rows = 3;
    brief.maxLength = 2000;
    brief.value = topic.description || "";
    brief.dataset.field = "description";
    brief.setAttribute("aria-label", "Practice brief");
    details.append(summary, brief);
    materials.forEach((material) => {
      const example = document.createElement("p");
      example.className = "plan-example";
      const label = material.source_label ? `${material.source_label}: ` : "";
      const solution = material.solution ? `  —  ${material.solution}` : "";
      setNotationText(example, `${label}${material.body}${solution}`);
      details.append(example);
    });
    row.append(head, details);
    list.append(row);
  });
  const topicCount = (plan.topics || []).length;
  byId("plan-summary").textContent = `${topicCount} concept${topicCount === 1 ? "" : "s"} · ${plan.material_count || 0} example problem${plan.material_count === 1 ? "" : "s"}`;
  byId("plan-status").textContent = "Check that this matches your guide. Sensei will choose where to start.";
  byId("plan-review").hidden = false;
  byId("plan-review").scrollIntoView({ behavior: "smooth", block: "start" });
}

function collectPlan() {
  const rows = Array.from(byId("plan-topics").querySelectorAll(".plan-topic"));
  const topics = rows
    .filter((row) => row.querySelector('input[type="checkbox"]').checked)
    .map((row) => {
      const source = (currentPlan?.topics || [])[Number(row.dataset.index)] || {};
      return {
        name: row.querySelector('[data-field="name"]').value.trim(),
        section: source.section || "",
        description: row.querySelector('[data-field="description"]').value.trim(),
        materials: Array.isArray(source.materials) ? source.materials : [],
      };
    })
    .filter((topic) => topic.name);
  return {
    subject: byId("plan-subject").value.trim(),
    set_name: byId("plan-set-name").value.trim(),
    course_profile: byId("plan-profile").value.trim(),
    topics,
  };
}

function discardPlan() {
  currentPlan = null;
  byId("plan-topics").replaceChildren();
  byId("plan-review").hidden = true;
}

async function createStudyPlan() {
  if (!currentPlan) return;
  const status = byId("plan-status");
  const plan = collectPlan();
  if (!plan.subject || !plan.set_name) {
    status.textContent = "Give the plan a subject and a study set name.";
    return;
  }
  if (!plan.topics.length) {
    status.textContent = "Keep at least one topic checked.";
    return;
  }
  const button = byId("plan-create");
  button.disabled = true;
  status.textContent = "Creating your study set…";
  try {
    const response = await postJson("/api/study/plan/create", plan);
    discardPlan();
    byId("import-file").value = "";
    byId("import-text").value = "";
    await loadDashboard();
    setGenerationStatus(
      byId("import-status"),
      `Created “${response.folder.name}” with ${response.topics.length} concept${response.topics.length === 1 ? "" : "s"} and ${response.added_materials} example problem${response.added_materials === 1 ? "" : "s"}. Sensei has chosen your first check-in below.`,
      "success",
    );
    byId("study-sets-section").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    void reportClientProblem(error, "createStudyPlan");
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

byId("import-form").addEventListener("submit", analyzeStudyGuide);
byId("import-mode-file").addEventListener("click", () => setImportMode("file"));
byId("import-mode-text").addEventListener("click", () => setImportMode("text"));
byId("plan-create").addEventListener("click", createStudyPlan);
byId("plan-discard").addEventListener("click", discardPlan);
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
  showView("study");
});
window.addEventListener("hashchange", () => showView(viewFromHash(), { updateHash: false }));
byId("new-question").addEventListener("click", () => {
  if (activeQuest) startAdaptiveQuest(activeQuest.skill_id, byId("arena-generation-status"));
});
byId("continue-practice").addEventListener("click", () => {
  if (activeQuest) followGuide(guideForSkill(activeQuest.skill_id), byId("arena-generation-status"));
});
byId("close-arena").addEventListener("click", closeArena);
byId("close-lesson").addEventListener("click", closeLesson);
byId("lesson-restart").addEventListener("click", restartLesson);
byId("lesson-check").addEventListener("click", checkLessonStep);
byId("lesson-answer").addEventListener("keydown", (event) => { if (event.key === "Enter") checkLessonStep(); });
byId("lesson-ask").addEventListener("click", askLessonQuestion);
byId("lesson-question").addEventListener("keydown", (event) => { if (event.key === "Enter") askLessonQuestion(); });
byId("ask-sensei-help").addEventListener("click", askSenseiForHelp);
byId("check-answer").addEventListener("click", checkAnswer);
byId("record-attempt").addEventListener("click", recordAttempt);
byId("practice-answer").addEventListener("keydown", (event) => { if (event.key === "Enter") checkAnswer(); });
byId("refresh-button").addEventListener("click", loadDashboard);
showView(viewFromHash());
loadDashboard();
setInterval(() => { if (!document.hidden && !generatingQuestion && !generatingLesson) loadDashboard(); }, 30000);
