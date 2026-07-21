const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

const el = (id) => document.getElementById(id);
const input = el("raw-input");
const generateBtn = el("generate");
const statusSection = el("status-section");
const statusText = el("status-text");
const resultsSection = el("results-section");

async function loadExample() {
  const res = await fetch("/api/sample");
  const data = await res.json();
  input.value = data.text;
  input.focus();
}
el("use-example").addEventListener("click", loadExample);
el("nav-example").addEventListener("click", loadExample);

function setStatus(message) {
  statusSection.hidden = false;
  statusText.textContent = message;
}

function clearStatus() {
  statusSection.hidden = true;
}

// A slot's name/sets/reps are scalars for a single exercise, or parallel
// arrays for a superset pair. Normalize to a list of {name, sets, reps}.
function slotExercises(slot) {
  const names = Array.isArray(slot.name) ? slot.name : [slot.name];
  const asList = (v) => (Array.isArray(v) ? v : names.map(() => v));
  const sets = asList(slot.sets);
  const reps = asList(slot.reps);
  return names
    .map((name, i) => ({ name, sets: sets[i], reps: reps[i] }))
    .filter((e) => e.name != null);
}

function formatLoad(sets, reps) {
  if (sets == null && reps == null) return "";
  if (reps == null) return `${sets} sets`;
  if (sets == null) return `${reps} reps`;
  return `${sets} × ${reps}`;
}

function text(tag, className, content) {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = content;
  return node;
}

function renderSlot(slot) {
  const wrap = text("div", "exercise", "");
  const exercises = slotExercises(slot);

  if (exercises.length === 0) {
    wrap.appendChild(text("div", "exercise-none", slot.note || "No safe match for this slot."));
    return wrap;
  }
  if (exercises.length > 1) {
    wrap.appendChild(text("span", "superset-badge", "Superset"));
  }
  for (const ex of exercises) {
    wrap.appendChild(text("div", "exercise-name", ex.name));
    wrap.appendChild(text("div", "exercise-load", formatLoad(ex.sets, ex.reps)));
  }
  return wrap;
}

function renderDay(day, index) {
  const card = document.createElement("div");
  const weekday = WEEKDAYS[index] || day.day_label || "";

  if (day.is_rest_day) {
    card.className = "day-card rest";
    card.appendChild(text("div", "day-weekday", weekday));
    card.appendChild(text("div", "day-split", "Rest"));
    card.appendChild(text("div", "day-rest-body", "Recovery"));
    return card;
  }

  card.className = "day-card";
  card.appendChild(text("div", "day-weekday", weekday));
  card.appendChild(text("div", "day-split", day.split_name || "Workout"));

  const slots = [...(day.primary || []), ...(day.secondary || [])];
  if (slots.length === 0) {
    card.appendChild(text("div", "exercise-none", "No exercises generated."));
  }
  for (const slot of slots) card.appendChild(renderSlot(slot));
  return card;
}

function renderPlan(plan) {
  el("plan-type").textContent = plan.plan_type
    ? `${plan.plan_type.replace("_", "-")} plan`
    : "Weekly plan";
  el("coach-notes").textContent = plan.coach_notes || "";

  const warning = el("clearance-warning");
  warning.hidden = !plan.medical_clearance_warning;
  warning.textContent = plan.medical_clearance_warning || "";

  const grid = el("week-grid");
  grid.replaceChildren();
  (plan.schedule || []).slice(0, 7).forEach((day, i) => grid.appendChild(renderDay(day, i)));

  resultsSection.hidden = false;
  resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `Request failed (${res.status}).`;
    try {
      detail = (await res.json()).detail || detail;
    } catch (_) { /* non-JSON error body */ }
    throw new Error(detail);
  }
  return res.json();
}

async function generate() {
  if (!input.value.trim()) {
    setStatus("Describe the client to get started.");
    return;
  }
  generateBtn.disabled = true;
  resultsSection.hidden = true;
  el("spinner").hidden = false;

  try {
    setStatus("Reading the client profile…");
    const { profile } = await postJSON("/api/profile", { text: input.value });

    setStatus("Building the week… this usually takes a minute.");
    const plan = await postJSON("/api/plan", { profile });

    clearStatus();
    renderPlan(plan);
  } catch (err) {
    el("spinner").hidden = true;
    setStatus(err.message);
  } finally {
    generateBtn.disabled = false;
  }
}

generateBtn.addEventListener("click", generate);
