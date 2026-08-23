"use strict";

const byId = (id) => document.getElementById(id);
const skillTemplate = byId("skill-template");
const historyTemplate = byId("history-template");
let dashboardState = null;
let activeCourse = "precalculus";
let activeUnit = "All";
let activeQuest = null;
let attemptToken = null;
let generatingQuestion = false;

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, Number(value) || 0));
}

function shortUnit(unit) {
  const names = {
    "Precalculus algebra": "Algebra",
    "Exponential and logarithmic functions": "Exp & logs",
    "Limits and continuity": "Limits",
    "Applications of derivatives": "Applications",
    "Integration techniques": "Techniques",
  };
  return names[unit] || unit;
}

function relativeDate(value) {
  if (!value) return "not scheduled";
  const target = new Date(value);
  if (Number.isNaN(target.getTime())) return "scheduled";
  const delta = target.getTime() - Date.now();
  const days = Math.round(delta / 86400000);
  if (days < -1) return `${Math.abs(days)} days overdue`;
  if (days === -1) return "1 day overdue";
  if (days === 0) return "due today";
  if (days === 1) return "tomorrow";
  return `in ${days} days`;
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

function renderQuest(quest) {
  byId("quest-timing").textContent = quest.due ? "Due now" : "Up next";
  byId("quest-skill").textContent = quest.skill_name;
  byId("quest-title").textContent = `Fresh ${quest.skill_name} quest`;
  byId("quest-prompt").textContent = `Generate a new ${quest.skill_name.toLowerCase()} challenge. Sensei will keep it inside this subject and verify its hidden answer before you see it.`;
  byId("quest-reason").textContent = `${quest.reason} ${Math.round(quest.mastery_score)}/100 mastery.`;
}

function filterSkills() {
  document.querySelectorAll(".skill-card").forEach((card) => {
    card.classList.toggle("hidden", activeUnit !== "All" && card.dataset.unit !== activeUnit);
  });
  document.querySelectorAll("#unit-filters button").forEach((button) => {
    const selected = button.dataset.unit === activeUnit;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}

function renderFilters(skills) {
  const units = ["All", ...new Set(skills.map((skill) => skill.unit))];
  const container = byId("unit-filters");
  container.replaceChildren();
  units.forEach((unit) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.unit = unit;
    button.textContent = unit === "All" ? "All disciplines" : shortUnit(unit);
    button.addEventListener("click", () => {
      activeUnit = unit;
      filterSkills();
    });
    container.append(button);
  });
}

function renderSkills(skills) {
  const grid = byId("skill-grid");
  grid.replaceChildren();
  skills.forEach((skill) => {
    const card = skillTemplate.content.firstElementChild.cloneNode(true);
    card.dataset.unit = skill.unit;
    card.querySelector(".skill-unit").textContent = shortUnit(skill.unit);
    card.querySelector(".skill-score").textContent = `${Math.round(skill.mastery_score)} / 100`;
    card.querySelector(".skill-name").textContent = skill.name;
    card.querySelector(".skill-label").textContent = skill.mastery_label;
    card.querySelector(".skill-track i").style.width = `${clamp(skill.mastery_score, 0, 100)}%`;
    card.querySelector(".skill-attempts").textContent = `${skill.attempts_count} attempt${skill.attempts_count === 1 ? "" : "s"}`;
    card.querySelector(".skill-review").textContent = relativeDate(skill.next_review_at);
    const practiceButton = card.querySelector(".practice-button");
    const supported = dashboardState.catalog.generated_skill_ids.includes(skill.id);
    practiceButton.disabled = !supported;
    practiceButton.addEventListener("click", () => startQuest(skill.id));
    grid.append(card);
  });
  renderFilters(skills);
  filterSkills();
}

function renderHistory(attempts) {
  const relevant = attempts
    .filter((attempt) => attempt.course === activeCourse)
    .slice(0, 6);
  const list = byId("history-list");
  list.replaceChildren();
  if (!relevant.length) {
    const empty = document.createElement("p");
    empty.className = "empty-history";
    empty.textContent = `No ${activeCourse} attempts yet. Start a quest above to begin your training log.`;
    list.append(empty);
    return;
  }
  relevant.forEach((attempt) => {
    const row = historyTemplate.content.firstElementChild.cloneNode(true);
    row.dataset.outcome = attempt.outcome;
    row.querySelector(".history-skill").textContent = attempt.quest_id
      ? `${attempt.skill_name} · Quest`
      : attempt.skill_name;
    row.querySelector(".history-problem").textContent = attempt.problem;
    const source = attempt.effective_outcome_source === "verifier" ? "verified " : "";
    row.querySelector(".history-outcome").textContent = `${source}${attempt.outcome}`;
    const time = row.querySelector(".history-time");
    time.dateTime = attempt.created_at;
    time.textContent = relativeDate(attempt.created_at);
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
  byId("record-attempt").hidden = true;
}

function openArena(quest) {
  if (!quest) return;
  activeQuest = quest;
  resetArenaFeedback();
  byId("arena-skill").textContent = quest.skill_name;
  byId("arena-title").textContent = quest.title;
  byId("arena-prompt").textContent = quest.prompt;
  byId("quest-answer").value = "";
  const arena = byId("quest-arena");
  arena.hidden = false;
  arena.scrollIntoView({ behavior: "smooth", block: "center" });
  byId("quest-answer").focus({ preventScroll: true });
}

async function startQuest(skillId) {
  if (!dashboardState || generatingQuestion) return;
  generatingQuestion = true;
  byId("start-next-quest").disabled = true;
  byId("new-question").disabled = true;
  try {
    const response = await postJson("/api/quest/generate", { skill_id: skillId });
    openArena({
      ...response.quest,
      challenge_token: response.challenge_token,
    });
  } catch (error) {
    byId("updated-at").textContent = `Question generation failed: ${error.message}`;
  } finally {
    generatingQuestion = false;
    byId("start-next-quest").disabled = false;
    byId("new-question").disabled = generatingQuestion;
  }
}

function closeArena() {
  activeQuest = null;
  resetArenaFeedback();
  byId("quest-arena").hidden = true;
}

function renderCourse() {
  activeUnit = "All";
  document.querySelectorAll(".course-switch button").forEach((button) => {
    const selected = button.dataset.course === activeCourse;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  const courseName = activeCourse === "precalculus" ? "Precalculus" : "Calculus";
  const skills = dashboardState.skills.filter((skill) => skill.course === activeCourse);
  renderQuest(dashboardState.next_quests[activeCourse]);
  renderSkills(skills);
  renderHistory(dashboardState.recent_attempts);
  byId("course-label").textContent = `${courseName} path`;
  byId("mastery-heading").textContent = `${courseName} subjects`;
  byId("catalog-quests").textContent = "Fresh";
  byId("catalog-skills").textContent = dashboardState.catalog.courses[activeCourse];
}

function render(state) {
  dashboardState = state;
  renderProfile(state.profile);
  renderCourse();
  byId("updated-at").textContent = `Local memory synced ${new Date(state.generated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

async function postJson(path, document) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Sensei-CSRF": dashboardState.csrf_token,
    },
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
  if (!answer) {
    byId("quest-answer").focus();
    return;
  }
  const button = byId("check-answer");
  button.disabled = true;
  byId("new-question").disabled = true;
  resetArenaFeedback();
  try {
    const response = await postJson("/api/quest/check", {
      challenge_token: challengeToken,
      answer,
    });
    if (!activeQuest || activeQuest.challenge_token !== challengeToken) return;
    const result = response.result;
    attemptToken = response.attempt_token;
    const feedback = byId("answer-feedback");
    const statusNames = {
      verified_correct: "Correct — well struck.",
      verified_incorrect: "Not quite — study the comparison.",
      inconclusive: "Sensei could not verify that form.",
    };
    const statusClass = result.status === "verified_correct"
      ? "correct"
      : result.status === "verified_incorrect" ? "incorrect" : "inconclusive";
    feedback.classList.add(statusClass);
    byId("feedback-status").textContent = statusNames[result.status] || result.status;
    byId("feedback-detail").textContent = result.detail;
    byId("feedback-expected").textContent = result.status === "verified_incorrect"
      ? `Reference form: ${result.expected}`
      : "";
    byId("record-attempt").hidden = !attemptToken;
    feedback.hidden = false;
  } catch (error) {
    const feedback = byId("answer-feedback");
    feedback.classList.add("inconclusive");
    byId("feedback-status").textContent = "The local verifier could not check this answer.";
    byId("feedback-detail").textContent = error.message;
    feedback.hidden = false;
  } finally {
    button.disabled = false;
    byId("new-question").disabled = generatingQuestion;
  }
}

async function recordAttempt() {
  if (!attemptToken) return;
  const button = byId("record-attempt");
  button.disabled = true;
  byId("new-question").disabled = true;
  try {
    const response = await postJson("/api/quest/record", {
      attempt_token: attemptToken,
    });
    attemptToken = null;
    byId("feedback-expected").textContent = `Recorded: +${response.progress.xp_awarded} XP · ${Math.round(response.progress.mastery_score)}/100 mastery.`;
    button.hidden = true;
    await loadDashboard();
  } catch (error) {
    byId("feedback-detail").textContent = error.message;
  } finally {
    button.disabled = false;
    byId("new-question").disabled = generatingQuestion;
  }
}

async function loadDashboard() {
  const button = byId("refresh-button");
  button.disabled = true;
  try {
    const response = await fetch("/api/dashboard", { cache: "no-store" });
    if (!response.ok) throw new Error(`Dashboard request failed: ${response.status}`);
    render(await response.json());
  } catch (error) {
    console.error(error);
    byId("updated-at").textContent = "Local memory unavailable — retrying soon";
  } finally {
    button.disabled = false;
  }
}

document.querySelectorAll(".course-switch button").forEach((button) => {
  button.addEventListener("click", () => {
    activeCourse = button.dataset.course;
    closeArena();
    if (dashboardState) renderCourse();
  });
});
byId("start-next-quest").addEventListener("click", () => {
  if (dashboardState) startQuest(dashboardState.next_quests[activeCourse].skill_id);
});
byId("new-question").addEventListener("click", () => {
  if (activeQuest) startQuest(activeQuest.skill_id);
});
byId("close-arena").addEventListener("click", closeArena);
byId("check-answer").addEventListener("click", checkAnswer);
byId("record-attempt").addEventListener("click", recordAttempt);
byId("quest-answer").addEventListener("keydown", (event) => {
  if (event.key === "Enter") checkAnswer();
});
byId("refresh-button").addEventListener("click", loadDashboard);
loadDashboard();
setInterval(() => {
  if (!document.hidden) loadDashboard();
}, 20000);
