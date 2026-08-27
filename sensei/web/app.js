"use strict";

const byId = (id) => document.getElementById(id);
const skillTemplate = byId("skill-template");
const historyTemplate = byId("history-template");
let dashboardState = null;
let activeQuest = null;
let recommendedTopic = null;
let attemptToken = null;
let generatingQuestion = false;

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, Number(value) || 0));
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

function topicPriority(topic) {
  if (!topic.next_review_at) return -2;
  return new Date(topic.next_review_at).getTime() - Date.now();
}

function renderRecommendation(topics) {
  const button = byId("start-next-quest");
  if (!topics.length) {
    recommendedTopic = null;
    byId("quest-timing").textContent = "Atlas empty";
    byId("quest-skill").textContent = "Choose your first focus";
    byId("quest-title").textContent = "Your next chapter starts above";
    byId("quest-prompt").textContent = "Add any math or chemistry topic and Sensei will begin building your personal practice path.";
    byId("quest-reason").textContent = "No premade curriculum stands between you and the thing you want to learn.";
    byId("quest-action-label").textContent = "Ready when you are";
    button.disabled = true;
    return;
  }
  recommendedTopic = [...topics].sort((left, right) => {
    const dateDifference = topicPriority(left) - topicPriority(right);
    return dateDifference || left.mastery_score - right.mastery_score;
  })[0];
  const due = !recommendedTopic.next_review_at || topicPriority(recommendedTopic) <= 0;
  byId("quest-timing").textContent = due ? "Review ready" : "Suggested next";
  byId("quest-skill").textContent = `${recommendedTopic.course} · ${recommendedTopic.difficulty}`;
  byId("quest-title").textContent = recommendedTopic.name;
  byId("quest-prompt").textContent = `Forge a fresh ${recommendedTopic.name.toLowerCase()} encounter at your ${recommendedTopic.difficulty} intensity.`;
  byId("quest-reason").textContent = recommendedTopic.attempts_count
    ? `${Math.round(recommendedTopic.mastery_score)}/100 mastery · ${relativeDate(recommendedTopic.next_review_at)}.`
    : "This newly mapped topic is ready for its first encounter.";
  byId("quest-action-label").textContent = due ? "Your review is ready" : "Keep your edge";
  button.disabled = generatingQuestion;
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
    card.querySelector(".skill-difficulty").textContent = `${topic.difficulty} questline`;
    card.querySelector(".skill-name").textContent = topic.name;
    card.querySelector(".skill-label").textContent = topic.mastery_label;
    card.querySelector(".skill-track i").style.width = `${clamp(topic.mastery_score, 0, 100)}%`;
    card.querySelector(".skill-attempts").textContent = `${topic.attempts_count} encounter${topic.attempts_count === 1 ? "" : "s"}`;
    card.querySelector(".skill-review").textContent = relativeDate(topic.next_review_at);
    card.querySelector(".practice-button").addEventListener("click", () => startAdaptiveQuest(topic.id));
    grid.append(card);
  });
}

function renderHistory(attempts) {
  const list = byId("history-list");
  list.replaceChildren();
  if (!attempts.length) {
    const empty = document.createElement("p");
    empty.className = "empty-history";
    empty.textContent = "No encounters yet. Forge your first quest above to begin the adventure log.";
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
  resetArenaFeedback();
  byId("arena-skill").textContent = quest.skill_name;
  byId("arena-title").textContent = quest.title;
  byId("arena-subject").textContent = quest.subject;
  byId("arena-difficulty").textContent = quest.difficulty;
  byId("arena-prompt").textContent = quest.prompt;
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

async function startAdaptiveQuest(skillId) {
  if (!dashboardState || generatingQuestion) return;
  generatingQuestion = true;
  document.body.classList.add("generating");
  byId("form-status").textContent = "Sensei is drafting and independently checking your encounter…";
  byId("forge-button").disabled = true;
  byId("start-next-quest").disabled = true;
  byId("new-question").disabled = true;
  try {
    const response = await postJson("/api/study/generate", { skill_id: skillId });
    openArena({ ...response.quest, challenge_token: response.challenge_token });
    byId("form-status").textContent = "Quest validated. Enter the arena.";
  } catch (error) {
    byId("form-status").textContent = error.message;
  } finally {
    generatingQuestion = false;
    document.body.classList.remove("generating");
    byId("forge-button").disabled = false;
    byId("new-question").disabled = false;
    renderRecommendation(dashboardState.study_topics);
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
      difficulty: byId("difficulty-input").value,
    });
    await loadDashboard();
    await startAdaptiveQuest(response.study_topic.id);
  } catch (error) {
    byId("form-status").textContent = error.message;
  } finally {
    if (!generatingQuestion) byId("forge-button").disabled = false;
  }
}

function closeArena() {
  activeQuest = null;
  resetArenaFeedback();
  byId("quest-arena").hidden = true;
}

async function postJson(path, document) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Sensei-CSRF": dashboardState.csrf_token },
    body: JSON.stringify(document),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Request failed: ${response.status}`);
  return result;
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
    byId("feedback-detail").textContent = result.detail;
    byId("feedback-expected").textContent = correct ? "" : `Validated answer: ${result.expected}`;
    if (response.solution) {
      byId("solution-text").textContent = response.solution;
      byId("solution-copy").hidden = false;
    }
    byId("record-attempt").hidden = !attemptToken;
    feedback.hidden = false;
  } catch (error) {
    const feedback = byId("answer-feedback");
    feedback.classList.add("inconclusive");
    byId("feedback-status").textContent = "Sensei could not check that answer form.";
    byId("feedback-detail").textContent = error.message;
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
    byId("feedback-detail").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function render(state) {
  dashboardState = state;
  renderProfile(state.profile);
  byId("practiced").textContent = state.study_topics.length;
  renderRecommendation(state.study_topics);
  renderTopics(state.study_topics);
  renderHistory(state.recent_attempts);
  const modelState = state.runtime.adaptive_generation === "ready" ? "Local practice architect ready" : "Adaptive model unavailable";
  byId("updated-at").textContent = `${modelState} · synced ${new Date(state.generated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

async function loadDashboard() {
  const button = byId("refresh-button");
  button.disabled = true;
  try {
    const response = await fetch("/api/dashboard", { cache: "no-store" });
    if (!response.ok) throw new Error(`Dashboard request failed: ${response.status}`);
    render(await response.json());
  } catch (error) {
    byId("updated-at").textContent = "Local memory unavailable — try syncing again";
  } finally {
    button.disabled = false;
  }
}

byId("focus-form").addEventListener("submit", createFocus);
document.querySelectorAll(".prompt-examples button").forEach((button) => {
  button.addEventListener("click", () => {
    byId("subject-input").value = button.dataset.subject;
    byId("topic-input").value = button.dataset.topic;
    byId("topic-input").focus();
  });
});
byId("start-next-quest").addEventListener("click", () => {
  if (recommendedTopic) startAdaptiveQuest(recommendedTopic.id);
});
byId("new-question").addEventListener("click", () => {
  if (activeQuest) startAdaptiveQuest(activeQuest.skill_id);
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
loadDashboard();
setInterval(() => { if (!document.hidden && !generatingQuestion) loadDashboard(); }, 30000);
