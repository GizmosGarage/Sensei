"use strict";

const byId = (id) => document.getElementById(id);
const skillTemplate = byId("skill-template");
const historyTemplate = byId("history-template");
let dashboardState = null;
let activeUnit = "All";

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, Number(value) || 0));
}

function shortUnit(unit) {
  const names = {
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
  byId("quest-title").textContent = quest.title;
  byId("quest-prompt").textContent = quest.prompt;
  byId("quest-reason").textContent = `${quest.reason} ${Math.round(quest.mastery_score)}/100 mastery.`;
}

function filterSkills() {
  document.querySelectorAll(".skill-card").forEach((card) => {
    card.classList.toggle("hidden", activeUnit !== "All" && card.dataset.unit !== activeUnit);
  });
  document.querySelectorAll("#unit-filters button").forEach((button) => {
    button.classList.toggle("active", button.dataset.unit === activeUnit);
    button.setAttribute("aria-pressed", String(button.dataset.unit === activeUnit));
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
    grid.append(card);
  });
  renderFilters(skills);
  filterSkills();
}

function renderHistory(attempts) {
  const list = byId("history-list");
  list.replaceChildren();
  if (!attempts.length) {
    const empty = document.createElement("p");
    empty.className = "empty-history";
    empty.textContent = "No attempts yet. Enter /quest in the tutor to begin your training log.";
    list.append(empty);
    return;
  }
  attempts.forEach((attempt) => {
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

function render(state) {
  dashboardState = state;
  renderProfile(state.profile);
  renderQuest(state.next_quest);
  renderSkills(state.skills);
  renderHistory(state.recent_attempts);
  byId("catalog-quests").textContent = state.catalog.quest_count;
  byId("catalog-skills").textContent = state.catalog.quest_skill_count;
  byId("updated-at").textContent = `Local memory synced ${new Date(state.generated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
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

byId("refresh-button").addEventListener("click", loadDashboard);
loadDashboard();
setInterval(() => {
  if (!document.hidden) loadDashboard();
}, 20000);
