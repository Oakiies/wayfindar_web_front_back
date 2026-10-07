// Shared logic for crop.html / resize.html / zoom.html.
// Each page sets `const MODE = "crop" | "resize" | "zoom";` before including this file.
const LEVEL_COLORS = ["#e6484b", "#f5a623", "#f4d03f", "#2ecc71", "#0d6efd", "#9b59b6"];

let curPoint = 0, curShot = 0, curLens = "normal", curLevel = 0;
let visible = null;   // per-level checkbox state, rebuilt per shot/lens
let refVisible = true; // show/hide the baseline (reference) marker

function fmtXY(r) {
  if (!r || !r.success || !r.xy) return '<span class="fail">หาตำแหน่งไม่ได้</span>';
  return `(${r.xy[0].toFixed(1)}, ${r.xy[1].toFixed(1)}) px · inliers ${r.num_inliers}`;
}

function fmtDrift(d) {
  if (d === null || d === undefined) return "";
  return ` · เพี้ยนจากต้นฉบับ ${d.toFixed(1)} px`;
}

function curPointId() {
  return [...new Set(TDATA.shots.map(s => s.point))][curPoint];
}
function currentShotObj() {
  return TDATA.shots.find(s => s.point === curPointId() && s.shot === curShot);
}
function currentLensObj() {
  return currentShotObj().lenses[curLens];
}

function placeMarker(el, r) {
  if (!r || !r.success || !r.xy) { el.style.display = "none"; return; }
  el.style.display = "block";
  el.style.left = (r.xy[0] / 500 * 100) + "%";
  el.style.top = (r.xy[1] / 500 * 100) + "%";
}

function buildPointButtons() {
  const pointIds = [...new Set(TDATA.shots.map(s => s.point))];
  const ptsEl = document.getElementById("points");
  ptsEl.innerHTML = "";
  pointIds.forEach((pid, i) => {
    const b = document.createElement("button");
    b.className = "pt-btn" + (i === curPoint ? " active" : "");
    b.textContent = "จุด " + pid;
    b.onclick = () => { curPoint = i; curShot = 0; curLevel = 0; visible = null; renderAll(); };
    ptsEl.appendChild(b);
  });

  const shotsForPoint = TDATA.shots.filter(s => s.point === pointIds[curPoint]);
  const shotsEl = document.getElementById("shots");
  shotsEl.innerHTML = "";
  shotsForPoint.forEach((s, i) => {
    const b = document.createElement("button");
    b.className = "shot-btn" + (i === curShot ? " active" : "");
    b.textContent = "ช็อต " + (i + 1);
    b.onclick = () => { curShot = i; curLevel = 0; visible = null; renderAll(); };
    shotsEl.appendChild(b);
  });
}

function buildLensButtons() {
  const el = document.getElementById("lensSwitch");
  el.innerHTML = "";
  [["normal", "normal (K แผนที่)"], ["wide", "wide / ultrawide (K ที่ประมาณ)"]].forEach(([key, label]) => {
    const b = document.createElement("button");
    b.className = "shot-btn" + (curLens === key ? " active" : "");
    b.textContent = label;
    b.onclick = () => { curLens = key; curLevel = 0; visible = null; renderAll(); };
    el.appendChild(b);
  });
}

function buildRefToggle() {
  const el = document.getElementById("refToggle");
  el.innerHTML = "";
  const label = document.createElement("label");
  label.style.display = "inline-flex";
  label.style.alignItems = "center";
  label.style.gap = "6px";
  label.style.cursor = "pointer";
  label.style.fontSize = "13px";
  label.style.color = "var(--muted)";
  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.checked = refVisible;
  cb.onclick = () => { refVisible = cb.checked; renderMap(currentShotObj(), currentLensObj()); };
  label.appendChild(cb);
  label.append(" แสดงตำแหน่งอ้างอิง (ก่อนแปลงภาพ)");
  el.appendChild(label);
}

function buildLevelList(lensObj) {
  const levels = lensObj.modes[MODE];
  if (visible === null) visible = levels.map(() => true);

  const listEl = document.getElementById("levelList");
  listEl.innerHTML = "";
  levels.forEach((lvl, i) => {
    const row = document.createElement("div");
    row.className = "level-row" + (i === curLevel ? " selected" : "");

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = visible[i];
    cb.onclick = (e) => { e.stopPropagation(); visible[i] = cb.checked; renderMap(currentShotObj(), lensObj); };
    row.appendChild(cb);

    const sw = document.createElement("span");
    sw.className = "sw";
    sw.style.background = LEVEL_COLORS[i % LEVEL_COLORS.length];
    row.appendChild(sw);

    const lbl = document.createElement("span");
    lbl.className = "lbl";
    lbl.textContent = lvl.label;
    row.appendChild(lbl);

    const stat = document.createElement("span");
    stat.className = "stat" + (lvl.result.success ? "" : " fail");
    stat.innerHTML = lvl.result.success
      ? `OK, inliers ${lvl.result.num_inliers}${fmtDrift(lvl.drift_px)}`
      : "หาตำแหน่งไม่ได้";
    row.appendChild(stat);

    row.onclick = () => { curLevel = i; renderAll(); };
    listEl.appendChild(row);
  });
}

function renderMap(shot, lensObj) {
  document.getElementById("mapImg").src = "../map/" + TDATA.floor_id + ".jpg";
  const refEl = document.getElementById("mRef");
  if (refVisible) placeMarker(refEl, lensObj.baseline);
  else refEl.style.display = "none";

  const dyn = document.getElementById("dynMarkers");
  dyn.innerHTML = "";
  const levels = lensObj.modes[MODE];
  levels.forEach((lvl, i) => {
    if (!visible[i]) return;
    const el = document.createElement("div");
    el.className = "marker";
    el.style.background = LEVEL_COLORS[i % LEVEL_COLORS.length];
    el.style.zIndex = i === curLevel ? 4 : 2;
    el.style.opacity = i === curLevel ? "1" : "0.55";
    el.style.width = i === curLevel ? "16px" : "12px";
    el.style.height = i === curLevel ? "16px" : "12px";
    dyn.appendChild(el);
    placeMarker(el, lvl.result);
  });
}

function renderAll() {
  buildPointButtons();
  buildLensButtons();
  buildRefToggle();

  const shot = currentShotObj();
  const lensObj = currentLensObj();
  const levels = lensObj.modes[MODE];
  if (visible === null || visible.length !== levels.length) visible = levels.map(() => true);
  const lvl = levels[curLevel];

  document.getElementById("baseImg").src = lensObj.base_img;
  document.getElementById("baseTag").textContent = "original · " + curLens;
  document.getElementById("baseMeta").innerHTML =
    `<b>ต้นฉบับ (${curLens}):</b> ${lensObj.base_w}x${lensObj.base_h} · ${fmtXY(lensObj.baseline)}`;

  document.getElementById("transformImg").src = lvl.img;
  document.getElementById("transformTag").textContent = lvl.label;
  document.getElementById("transformMeta").innerHTML =
    `<b>${lvl.label}:</b> ${fmtXY(lvl.result)}${fmtDrift(lvl.drift_px)}`;

  buildLevelList(lensObj);
  renderMap(shot, lensObj);
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("floorLabel").textContent = TDATA.floor_id;
  renderAll();
});
