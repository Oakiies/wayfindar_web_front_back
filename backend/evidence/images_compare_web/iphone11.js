let curFrame = 0;

function fmtXY(r) {
  if (!r || !r.success || !r.xy) return '<span class="fail">หาตำแหน่งไม่ได้</span>';
  return `(${r.xy[0].toFixed(1)}, ${r.xy[1].toFixed(1)}) px · inliers ${r.num_inliers}`;
}

function fmtDrift(d) {
  if (d === null || d === undefined) return "";
  return ` · ห่างกัน ${d.toFixed(1)} px`;
}

function placeMarker(el, r) {
  if (!r || !r.success || !r.xy) { el.style.display = "none"; return; }
  el.style.display = "block";
  el.style.left = (r.xy[0] / 500 * 100) + "%";
  el.style.top = (r.xy[1] / 500 * 100) + "%";
}

function renderAll() {
  const f = IDATA.frames[curFrame];

  document.getElementById("frameImg").src = f.img;
  document.getElementById("frameTag").textContent = `frame ${f.idx} · t=${f.t.toFixed(1)}s`;
  document.getElementById("frameCounter").textContent = `เฟรม ${curFrame + 1} / ${IDATA.frames.length}`;

  document.getElementById("naiveMeta").innerHTML =
    `<b>K แผนที่ (ไม่ปรับ):</b> ${fmtXY(f.naive)}`;
  document.getElementById("selfcalMeta").innerHTML =
    `<b>self-calibration:</b> ${fmtXY(f.selfcal)} · focal ตอนนั้น ${f.focal_used.toFixed(0)} px` +
    fmtDrift(f.drift_px);

  document.getElementById("mapImg").src = "../map/" + IDATA.floor_id + ".jpg";
  placeMarker(document.getElementById("mNaive"), f.naive);
  placeMarker(document.getElementById("mSelfcal"), f.selfcal);
}

document.addEventListener("DOMContentLoaded", () => {
  const naiveOk = IDATA.frames.filter(f => f.naive.success).length;
  const selfcalOk = IDATA.frames.filter(f => f.selfcal.success).length;
  document.getElementById("summary").innerHTML =
    `<b>${IDATA.video}</b> (iPhone 11) · สุ่ม ${IDATA.frames.length} เฟรมจากทั้งหมด ${IDATA.total_frames} เฟรม ` +
    `(${(IDATA.total_frames / IDATA.fps).toFixed(0)} วิ @ ${IDATA.fps.toFixed(1)} fps) บน ${IDATA.floor_id} ` +
    `(K แผนที่ = ${IDATA.map_K.f.toFixed(0)} px) · localize ได้: K แผนที่ตรง ๆ ${naiveOk}/${IDATA.frames.length}, ` +
    `self-calibration ${selfcalOk}/${IDATA.frames.length}`;
  renderAll();
});
