"use strict";

const PROGRESSION_DEFAULT_REASON = "RIR > 3 and hit rep ceiling";
const REGRESSION_REASONS = ["Lack of form", "Lack of strength"];
const REL_COLORS = { alternatives: "#1565c0", progression: "#2e7d32", regression: "#e65100" };

let state = { exercises: [], relationships: [] };
let saveTimer = null;
let openRelId = null;
let editingId = null;

const $ = (sel) => document.querySelector(sel);

/* ============================ persistence ============================ */

async function loadState() {
  const res = await fetch("/api/state");
  state = await res.json();
}

function scheduleSave() {
  $("#save-status").textContent = "Saving…";
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    try {
      await fetch("/api/state", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(state),
      });
      $("#save-status").textContent = "Saved ✓";
    } catch {
      $("#save-status").textContent = "Save failed — is the server running?";
    }
  }, 350);
}

function nextId(items) {
  return items.reduce((max, item) => Math.max(max, item.id || 0), 0) + 1;
}

function getExercise(id) {
  return state.exercises.find((ex) => ex.id === id);
}

/* ============================ tabs ============================ */

function showTab(which) {
  const boardActive = which === "board";
  $("#tab-exercises").classList.toggle("active", !boardActive);
  $("#tab-board").classList.toggle("active", boardActive);
  $("#screen-exercises").classList.toggle("hidden", boardActive);
  $("#screen-board").classList.toggle("hidden", !boardActive);
  if (boardActive) renderBoard(); // node sizes are only measurable when visible
}

/* ============================ screen 1: creator ============================ */

function hasOrientation(movementType) {
  return movementType === "push" || movementType === "pull";
}

function syncOrientationField() {
  const form = $("#exercise-form");
  const show = hasOrientation(form.movement_type.value);
  $("#orientation-fieldset").classList.toggle("hidden", !show);
  if (!show) {
    form.querySelectorAll('input[name="orientation"]').forEach((r) => (r.checked = false));
  }
}

function handleFormSubmit(event) {
  event.preventDefault();
  const form = event.target;

  const minReps = parseInt(form.min_reps.value, 10);
  const maxReps = parseInt(form.max_reps.value, 10);
  if (minReps > maxReps) {
    alert("Min reps cannot be greater than max reps.");
    return;
  }

  let orientation = "";
  if (hasOrientation(form.movement_type.value)) {
    const checked = form.querySelector('input[name="orientation"]:checked');
    if (!checked) {
      alert("Select an orientation (horizontal or vertical) for this push/pull exercise.");
      return;
    }
    orientation = checked.value;
  }

  const equipment = [];
  if (form.eq_bodyweight.checked) equipment.push("bodyweight");
  if (form.eq_bands.checked) equipment.push("resistance bands");
  if (form.eq_other.checked && form.eq_other_text.value.trim()) {
    equipment.push(form.eq_other_text.value.trim());
  }

  const loadedJoints = [...$("#joint-grid").querySelectorAll("input:checked")].map((cb) => cb.value);

  const fields = {
    name: form.name.value.trim(),
    movement_type: form.movement_type.value,
    orientation,
    dominant: form.dominant.checked,
    equipment,
    loaded_joints: loadedJoints,
    min_reps: minReps,
    max_reps: maxReps,
    avoid_if: form.avoid_if.value.trim(),
  };

  if (editingId !== null) {
    const existing = getExercise(editingId);
    if (existing) Object.assign(existing, fields); // keep id, on_board, board_x, board_y
  } else {
    state.exercises.push({
      id: nextId(state.exercises),
      ...fields,
      on_board: false,
      board_x: 0,
      board_y: 0,
    });
  }

  scheduleSave();
  renderExerciseTable();
  renderPalette();
  renderBoard();
  resetExerciseForm();
}

function resetExerciseForm() {
  const form = $("#exercise-form");
  editingId = null;
  form.reset();
  form.eq_bodyweight.checked = true;
  $("#eq-other-text").disabled = true;
  syncOrientationField();
  $("#exercise-form-heading").textContent = "New exercise";
  $("#exercise-submit-btn").textContent = "Add exercise";
  $("#exercise-cancel-btn").classList.add("hidden");
  form.name.focus();
}

function startEditExercise(id) {
  const ex = getExercise(id);
  if (!ex) return;
  const form = $("#exercise-form");
  editingId = id;

  form.name.value = ex.name;
  form.movement_type.value = ex.movement_type;
  syncOrientationField();
  if (ex.orientation) {
    const radio = form.querySelector(`input[name="orientation"][value="${ex.orientation}"]`);
    if (radio) radio.checked = true;
  }
  form.dominant.checked = ex.dominant;

  const standardEquipment = new Set(["bodyweight", "resistance bands"]);
  form.eq_bodyweight.checked = ex.equipment.includes("bodyweight");
  form.eq_bands.checked = ex.equipment.includes("resistance bands");
  const otherEquipment = ex.equipment.filter((item) => !standardEquipment.has(item));
  form.eq_other.checked = otherEquipment.length > 0;
  form.eq_other_text.value = otherEquipment.join(", ");
  form.eq_other_text.disabled = !form.eq_other.checked;

  $("#joint-grid").querySelectorAll("input").forEach((cb) => {
    cb.checked = ex.loaded_joints.includes(cb.value);
  });

  form.min_reps.value = ex.min_reps;
  form.max_reps.value = ex.max_reps;
  form.avoid_if.value = ex.avoid_if;

  $("#exercise-form-heading").textContent = `Edit "${ex.name}"`;
  $("#exercise-submit-btn").textContent = "Save changes";
  $("#exercise-cancel-btn").classList.remove("hidden");
  renderExerciseTable();
  form.scrollIntoView({ behavior: "smooth", block: "start" });
  form.name.focus();
}

function deleteExercise(id) {
  const ex = getExercise(id);
  if (!ex) return;
  if (!confirm(`Delete "${ex.name}" and all its connections?`)) return;
  state.exercises = state.exercises.filter((e) => e.id !== id);
  state.relationships = state.relationships.filter(
    (rel) => rel.from_exercise_id !== id && rel.to_exercise_id !== id
  );
  if (editingId === id) resetExerciseForm();
  scheduleSave();
  renderExerciseTable();
  renderPalette();
  renderBoard();
}

function renderExerciseTable() {
  const wrap = $("#exercise-table");
  $("#exercise-count").textContent = state.exercises.length ? `(${state.exercises.length})` : "";
  if (!state.exercises.length) {
    wrap.innerHTML = '<p class="empty-note">Nothing yet — add your first exercise on the left.</p>';
    return;
  }
  const rows = state.exercises.map((ex) => `
    <tr class="${ex.id === editingId ? "editing" : ""}">
      <td><strong>${escapeHtml(ex.name)}</strong></td>
      <td><span class="badge move">${ex.movement_type}${ex.orientation ? " · " + ex.orientation : ""}</span></td>
      <td><span class="badge ${ex.dominant ? "dominant" : "light"}">${ex.dominant ? "Dominant" : "Light"}</span></td>
      <td>${escapeHtml(ex.equipment.join(", ")) || "—"}</td>
      <td>${escapeHtml(ex.loaded_joints.join(", ")) || "—"}</td>
      <td>${ex.min_reps}–${ex.max_reps}</td>
      <td>${escapeHtml(ex.avoid_if) || "—"}</td>
      <td>
        <button class="row-edit" data-id="${ex.id}" title="Edit">✎</button>
        <button class="row-delete" data-id="${ex.id}" title="Delete">✕</button>
      </td>
    </tr>`).join("");
  wrap.innerHTML = `
    <table>
      <thead><tr>
        <th>Name</th><th>Movement</th><th>Dom/Light</th><th>Equipment</th>
        <th>Loaded joints</th><th>Reps</th><th>Avoid if</th><th></th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  wrap.querySelectorAll(".row-delete").forEach((btn) =>
    btn.addEventListener("click", () => deleteExercise(parseInt(btn.dataset.id, 10)))
  );
  wrap.querySelectorAll(".row-edit").forEach((btn) =>
    btn.addEventListener("click", () => startEditExercise(parseInt(btn.dataset.id, 10)))
  );
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text || "";
  return div.innerHTML;
}

/* ============================ screen 2: palette ============================ */

function renderPalette() {
  const moveFilter = $("#filter-movement").value;
  const domFilter = $("#filter-dominance").value;
  const orientationFilter = [...document.querySelectorAll(".filter-orientation:checked")].map((cb) => cb.value);
  const list = $("#palette-list");

  const matches = state.exercises.filter((ex) => {
    if (moveFilter && ex.movement_type !== moveFilter) return false;
    if (domFilter === "dominant" && !ex.dominant) return false;
    if (domFilter === "light" && ex.dominant) return false;
    if (orientationFilter.length) {
      if (!hasOrientation(ex.movement_type)) return false;
      if (!orientationFilter.includes(ex.orientation)) return false;
    }
    return true;
  });

  if (!matches.length) {
    list.innerHTML = '<p class="empty-note">No exercises match.</p>';
    return;
  }

  list.innerHTML = matches.map((ex) => `
    <div class="palette-item ${ex.dominant ? "" : "light-accent"} ${ex.on_board ? "used" : ""}"
         draggable="${!ex.on_board}" data-id="${ex.id}">
      <div>${escapeHtml(ex.name)}</div>
      <div class="meta">${ex.movement_type}${ex.orientation ? " (" + ex.orientation + ")" : ""} · ${ex.dominant ? "dominant" : "light"}</div>
    </div>`).join("");

  list.querySelectorAll('.palette-item[draggable="true"]').forEach((item) => {
    item.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/plain", item.dataset.id);
      e.dataTransfer.effectAllowed = "copy";
    });
  });
}

/* ============================ screen 2: board ============================ */

/* ---------- infinite-scroll canvas: grows on demand, never shrinks ---------- */

const CANVAS_EDGE_MARGIN = 400; // start growing once a node is within this many px of the edge
const CANVAS_GROWTH = 1000; // px added past the node each time the canvas grows
let canvasSize = { width: 3000, height: 2000 };

function applyCanvasSize() {
  const canvas = $("#canvas");
  canvas.style.width = `${canvasSize.width}px`;
  canvas.style.height = `${canvasSize.height}px`;
  const svg = $("#wires");
  svg.setAttribute("width", canvasSize.width);
  svg.setAttribute("height", canvasSize.height);
}

function ensureCanvasSize(requiredRight, requiredBottom) {
  let changed = false;
  if (requiredRight + CANVAS_EDGE_MARGIN > canvasSize.width) {
    canvasSize.width = requiredRight + CANVAS_GROWTH;
    changed = true;
  }
  if (requiredBottom + CANVAS_EDGE_MARGIN > canvasSize.height) {
    canvasSize.height = requiredBottom + CANVAS_GROWTH;
    changed = true;
  }
  if (changed) applyCanvasSize();
}

function renderBoard() {
  const canvas = $("#canvas");
  canvas.querySelectorAll(".node").forEach((node) => node.remove());
  state.exercises.filter((ex) => ex.on_board).forEach((ex) => canvas.appendChild(buildNode(ex)));
  canvas.querySelectorAll(".node").forEach((node) => {
    ensureCanvasSize(node.offsetLeft + node.offsetWidth, node.offsetTop + node.offsetHeight);
  });
  renderWires();
}

function buildNode(ex) {
  const node = document.createElement("div");
  node.className = `node ${ex.dominant ? "" : "light-accent"}`;
  node.dataset.id = ex.id;
  node.style.left = `${ex.board_x}px`;
  node.style.top = `${ex.board_y}px`;
  node.title = [
    ex.orientation ? `Orientation: ${ex.orientation}` : "",
    `Equipment: ${ex.equipment.join(", ") || "—"}`,
    `Loaded joints: ${ex.loaded_joints.join(", ") || "—"}`,
    `Reps: ${ex.min_reps}–${ex.max_reps}`,
    ex.avoid_if ? `Avoid if: ${ex.avoid_if}` : "",
  ].filter(Boolean).join("\n");
  node.innerHTML = `
    <button class="node-remove" title="Remove from board">×</button>
    <div class="node-name">${escapeHtml(ex.name)}</div>
    <div class="meta">${ex.movement_type}${ex.orientation ? " (" + ex.orientation + ")" : ""} · ${ex.dominant ? "dominant" : "light"}</div>
    <div class="handle" title="Drag to another exercise to connect"></div>`;

  node.querySelector(".node-remove").addEventListener("click", (e) => {
    e.stopPropagation();
    removeFromBoard(ex.id);
  });
  node.querySelector(".handle").addEventListener("mousedown", (e) => {
    e.stopPropagation();
    e.preventDefault();
    startConnection(ex.id, e);
  });
  node.addEventListener("mousedown", (e) => startNodeDrag(ex, node, e));
  return node;
}

function removeFromBoard(id) {
  const ex = getExercise(id);
  if (!ex) return;
  ex.on_board = false;
  state.relationships = state.relationships.filter(
    (rel) => rel.from_exercise_id !== id && rel.to_exercise_id !== id
  );
  closePopup();
  scheduleSave();
  renderPalette();
  renderBoard();
}

function canvasPoint(event) {
  const rect = $("#canvas").getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}

function startNodeDrag(ex, node, event) {
  if (event.button !== 0) return;
  event.preventDefault();
  const start = canvasPoint(event);
  const origin = { x: ex.board_x, y: ex.board_y };
  let moved = false;

  const onMove = (e) => {
    const pt = canvasPoint(e);
    ex.board_x = Math.max(0, origin.x + pt.x - start.x);
    ex.board_y = Math.max(0, origin.y + pt.y - start.y);
    node.style.left = `${ex.board_x}px`;
    node.style.top = `${ex.board_y}px`;
    ensureCanvasSize(ex.board_x + node.offsetWidth, ex.board_y + node.offsetHeight);
    if (!moved) node.classList.add("dragging");
    moved = true;
    renderWires();
  };
  const onUp = () => {
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
    node.classList.remove("dragging");
    if (moved) scheduleSave();
  };
  document.addEventListener("mousemove", onMove);
  document.addEventListener("mouseup", onUp);
}

/* ---------- drag from palette onto canvas ---------- */

function setUpCanvasDrop() {
  const canvas = $("#canvas");
  canvas.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  });
  canvas.addEventListener("drop", (e) => {
    e.preventDefault();
    const id = parseInt(e.dataTransfer.getData("text/plain"), 10);
    const ex = getExercise(id);
    if (!ex || ex.on_board) return;
    const pt = canvasPoint(e);
    ex.on_board = true;
    ex.board_x = Math.max(0, pt.x - 85);
    ex.board_y = Math.max(0, pt.y - 25);
    scheduleSave();
    renderPalette();
    renderBoard();
  });
}

/* ---------- connections ---------- */

function startConnection(fromId, event) {
  const svg = $("#wires");
  const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
  line.setAttribute("stroke", "#7a8699");
  line.setAttribute("stroke-width", "2");
  line.setAttribute("stroke-dasharray", "6 4");
  svg.appendChild(line);

  const fromNode = document.querySelector(`.node[data-id="${fromId}"]`);
  const fromCenter = {
    x: fromNode.offsetLeft + fromNode.offsetWidth / 2,
    y: fromNode.offsetTop + fromNode.offsetHeight / 2,
  };
  line.setAttribute("x1", fromCenter.x);
  line.setAttribute("y1", fromCenter.y);
  line.setAttribute("x2", fromCenter.x);
  line.setAttribute("y2", fromCenter.y);

  const onMove = (e) => {
    const pt = canvasPoint(e);
    line.setAttribute("x2", pt.x);
    line.setAttribute("y2", pt.y);
  };
  const onUp = (e) => {
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
    line.remove();
    const target = document
      .elementsFromPoint(e.clientX, e.clientY)
      .map((el) => el.closest && el.closest(".node"))
      .find(Boolean);
    if (!target) return;
    const toId = parseInt(target.dataset.id, 10);
    if (toId === fromId) return;
    createRelationship(fromId, toId, e);
  };
  document.addEventListener("mousemove", onMove);
  document.addEventListener("mouseup", onUp);
}

function createRelationship(fromId, toId, event) {
  const rel = {
    id: nextId(state.relationships),
    from_exercise_id: fromId,
    to_exercise_id: toId,
    type: "progression",
    reason: [PROGRESSION_DEFAULT_REASON],
  };
  state.relationships.push(rel);
  scheduleSave();
  renderWires();
  openPopup(rel.id, event.clientX, event.clientY);
}

/* ---------- wires (SVG arrows) ---------- */

// Anchor point on `rect`'s edge facing `otherCenter`, shifted `offset` px
// along that edge. Distinct offsets land on genuinely different points on
// the node's border, so several relationships to/from the same node stay
// visibly apart along their whole length — not just bowed apart in the middle.
function facingAnchor(rect, otherCenter, offset) {
  const cx = rect.x + rect.w / 2;
  const cy = rect.y + rect.h / 2;
  const dx = otherCenter.x - cx;
  const dy = otherCenter.y - cy;
  const margin = 10;
  if (Math.abs(dx) >= Math.abs(dy)) {
    const x = dx >= 0 ? rect.x + rect.w : rect.x;
    const maxOffset = Math.max(0, rect.h / 2 - margin);
    return { x, y: cy + Math.max(-maxOffset, Math.min(maxOffset, offset)) };
  }
  const y = dy >= 0 ? rect.y + rect.h : rect.y;
  const maxOffset = Math.max(0, rect.w / 2 - margin);
  return { x: cx + Math.max(-maxOffset, Math.min(maxOffset, offset)), y };
}

function nodeRect(id) {
  const el = document.querySelector(`.node[data-id="${id}"]`);
  if (!el) return null;
  return { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight };
}

function renderWires() {
  const svg = $("#wires");
  const defs = `
    <defs>
      ${Object.entries(REL_COLORS).map(([type, color]) => `
        <marker id="arrow-${type}" viewBox="0 0 10 10" refX="9" refY="5"
                markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="${color}"></path>
        </marker>`).join("")}
    </defs>`;

  // Multiple relationships can exist between the same pair of exercises —
  // group them so each one gets its own offset curve instead of overlapping.
  const pairGroups = new Map();
  state.relationships.forEach((rel) => {
    const key = [rel.from_exercise_id, rel.to_exercise_id].sort((a, b) => a - b).join("-");
    if (!pairGroups.has(key)) pairGroups.set(key, []);
    pairGroups.get(key).push(rel);
  });

  const PORT_SPACING = 16;
  const markup = [];
  pairGroups.forEach((rels) => {
    rels.forEach((rel, i) => {
      const rectA = nodeRect(rel.from_exercise_id);
      const rectB = nodeRect(rel.to_exercise_id);
      if (!rectA || !rectB) return;
      const centerA = { x: rectA.x + rectA.w / 2, y: rectA.y + rectA.h / 2 };
      const centerB = { x: rectB.x + rectB.w / 2, y: rectB.y + rectB.h / 2 };
      const offset = (i - (rels.length - 1) / 2) * PORT_SPACING;
      const p1 = facingAnchor(rectA, centerB, offset);
      const p2 = facingAnchor(rectB, centerA, offset);
      const midX = (p1.x + p2.x) / 2;
      const midY = (p1.y + p2.y) / 2;
      const color = REL_COLORS[rel.type] || "#7a8699";
      const dash = rel.type === "alternatives" ? 'stroke-dasharray="7 5"' : "";
      const markerStart = rel.type === "alternatives" ? `marker-start="url(#arrow-${rel.type})"` : "";
      const d = `M ${p1.x} ${p1.y} L ${p2.x} ${p2.y}`;
      markup.push(`
        <g class="rel" data-id="${rel.id}">
          <path d="${d}" fill="none" stroke="transparent" stroke-width="14"></path>
          <path d="${d}" fill="none" stroke="${color}" stroke-width="2.5" ${dash}
                marker-end="url(#arrow-${rel.type})" ${markerStart}></path>
          <text x="${midX}" y="${midY - 7}" text-anchor="middle" fill="${color}">${rel.type}</text>
        </g>`);
    });
  });

  svg.innerHTML = defs + markup.join("");
  svg.querySelectorAll("g.rel").forEach((g) =>
    g.addEventListener("click", (e) => {
      e.stopPropagation();
      openPopup(parseInt(g.dataset.id, 10), e.clientX, e.clientY);
    })
  );
}

/* ---------- arrow popup ---------- */

function openPopup(relId, clientX, clientY) {
  const rel = state.relationships.find((r) => r.id === relId);
  if (!rel) return;
  openRelId = relId;

  const popup = $("#arrow-popup");
  popup.classList.remove("hidden");
  popup.style.left = `${Math.min(clientX + 10, window.innerWidth - 270)}px`;
  popup.style.top = `${Math.min(clientY + 10, window.innerHeight - 300)}px`;

  const from = getExercise(rel.from_exercise_id);
  const to = getExercise(rel.to_exercise_id);
  $("#popup-endpoints").textContent = `${from ? from.name : "?"} → ${to ? to.name : "?"}`;

  popup.querySelectorAll('input[name="rel-type"]').forEach((radio) => {
    radio.checked = radio.value === rel.type;
  });
  renderPopupReason(rel);
}

function renderPopupReason(rel) {
  const wrap = $("#popup-reason");
  if (rel.type === "regression") {
    wrap.innerHTML = `
      <div class="reason-title">Reason</div>
      ${REGRESSION_REASONS.map((reason) => `
        <label class="check-row">
          <input type="checkbox" value="${reason}" ${rel.reason.includes(reason) ? "checked" : ""}>
          ${reason}
        </label>`).join("")}`;
    wrap.querySelectorAll("input").forEach((cb) =>
      cb.addEventListener("change", () => {
        rel.reason = [...wrap.querySelectorAll("input:checked")].map((c) => c.value);
        scheduleSave();
      })
    );
  } else if (rel.type === "progression") {
    wrap.innerHTML = `
      <div class="reason-title">Reason (default)</div>
      <div class="default-reason">${escapeHtml(PROGRESSION_DEFAULT_REASON)}</div>`;
  } else {
    wrap.innerHTML = "";
  }
}

function closePopup() {
  openRelId = null;
  $("#arrow-popup").classList.add("hidden");
}

function setUpPopup() {
  const popup = $("#arrow-popup");

  popup.querySelectorAll('input[name="rel-type"]').forEach((radio) =>
    radio.addEventListener("change", () => {
      const rel = state.relationships.find((r) => r.id === openRelId);
      if (!rel) return;
      rel.type = radio.value;
      rel.reason = rel.type === "progression" ? [PROGRESSION_DEFAULT_REASON] : [];
      renderPopupReason(rel);
      scheduleSave();
      renderWires();
    })
  );

  $("#popup-delete").addEventListener("click", () => {
    state.relationships = state.relationships.filter((r) => r.id !== openRelId);
    closePopup();
    scheduleSave();
    renderWires();
  });

  $("#popup-close").addEventListener("click", closePopup);

  document.addEventListener("mousedown", (e) => {
    if (openRelId === null) return;
    if (popup.contains(e.target) || e.target.closest("g.rel")) return;
    closePopup();
  });
}

/* ============================ init ============================ */

async function init() {
  await loadState();
  applyCanvasSize();
  renderExerciseTable();
  renderPalette();

  $("#tab-exercises").addEventListener("click", () => showTab("exercises"));
  $("#tab-board").addEventListener("click", () => showTab("board"));
  $("#exercise-form").addEventListener("submit", handleFormSubmit);
  $("#exercise-cancel-btn").addEventListener("click", resetExerciseForm);
  $("#eq-other-check").addEventListener("change", (e) => {
    $("#eq-other-text").disabled = !e.target.checked;
    if (e.target.checked) $("#eq-other-text").focus();
  });
  $("#movement-type-select").addEventListener("change", syncOrientationField);
  syncOrientationField();

  $("#filter-movement").addEventListener("change", renderPalette);
  $("#filter-dominance").addEventListener("change", renderPalette);
  document.querySelectorAll(".filter-orientation").forEach((cb) =>
    cb.addEventListener("change", renderPalette)
  );

  setUpCanvasDrop();
  setUpPopup();
}

init();
