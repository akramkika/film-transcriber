import { activeSegmentIndex, sourceTimeForSegment, formatTime, followScrollPosition } from "./sync.mjs";

const byId = (id) => document.getElementById(id);
const ui = Object.fromEntries([
  "transcription-form", "video-file", "drop-zone", "selected-file", "file-hint", "start-seconds", "end-seconds",
  "language", "vad-filter", "beam-size", "transcribe", "history", "new-job", "notice", "video", "video-heading",
  "video-placeholder", "video-warning", "video-duration", "video-context", "job-status", "transcript-meta",
  "transcript-scroll", "transcript-placeholder", "processing-state", "processing-title", "processing-description",
  "segments", "auto-follow", "sync-note", "delete-job", "announcement",
].map((id) => [id, byId(id)]));
const maxUpload = Number(document.body.dataset.maxUploadBytes);
const maxScene = Number(document.body.dataset.maxSceneSeconds);
const statusLabels = { PENDING: "En file d’attente", PROCESSING: "En cours", COMPLETED: "Terminée", FAILED: "Échec" };
const stageLabels = {
  validating: ["Vérification de la vidéo", "Lecture du format et des pistes audio de votre fichier."],
  queued: ["Votre scène est dans la file", "Elle sera traitée dès que le moteur sera disponible."],
  pending: ["Votre scène est dans la file", "Elle sera traitée dès que le moteur sera disponible."],
  inspecting: ["Vérification de la vidéo", "Lecture du format et des pistes audio de votre fichier."],
  inspection: ["Vérification de la vidéo", "Lecture du format et des pistes audio de votre fichier."],
  extracting: ["Préparation de l’audio", "Extraction du son de la scène sélectionnée."],
  extraction: ["Préparation de l’audio", "Extraction du son de la scène sélectionnée."],
  transcribing: ["À l’écoute de votre scène", "Le moteur local transforme les paroles en texte."],
  transcription: ["À l’écoute de votre scène", "Le moteur local transforme les paroles en texte."],
  exporting: ["Préparation des résultats", "Création des dialogues horodatés et des fichiers à télécharger."],
  exports: ["Préparation des résultats", "Création des dialogues horodatés et des fichiers à télécharger."],
};
let selectedFile = null;
let blobUrl = null;
let currentJob = null;
let result = null;
let renderedResultId = null;
let activeIndex = -1;
let pollTimer = null;
let animationFrame = null;
let viewVersion = 0;
let busy = false;
let mediaReadable = false;
let lastAnnouncement = "";
let jobs = [];

byId("upload-limit").textContent = `${new Intl.NumberFormat("fr-FR").format(maxUpload / 1000000)} Mo max.`;
byId("scene-limit").textContent = `Scène de ${new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 }).format(maxScene / 60)} minutes maximum.`;

function announce(message) {
  if (message !== lastAnnouncement) {
    ui.announcement.textContent = message;
    lastAnnouncement = message;
  }
}

function showNotice(message = "") {
  ui.notice.textContent = message;
  ui.notice.hidden = !message;
}

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { cache: "no-store", ...options });
  } catch {
    throw new Error("Connexion au serveur local interrompue. Vérifiez que l’application est toujours lancée.");
  }
  const payload = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    const message = payload?.error?.message || (typeof payload?.detail === "string" ? payload.detail : null);
    throw new Error(message || `La demande n’a pas abouti (erreur ${response.status}).`);
  }
  return payload;
}

function updateSubmit() {
  const running = currentJob && ["PENDING", "PROCESSING"].includes(currentJob.status);
  ui.transcribe.disabled = busy || !selectedFile || running;
  ui.transcribe.firstChild.textContent = busy ? "Import de la vidéo… " : "Transcrire la scène ";
  ui["video-file"].disabled = busy;
  ui.history.disabled = busy;
  ui["new-job"].disabled = busy;
  ui["transcription-form"].setAttribute("aria-busy", String(busy));
}

function setExports(jobId = null) {
  for (const format of ["txt", "srt", "json"]) {
    const link = byId(`export-${format}`);
    link.setAttribute("aria-disabled", String(!jobId));
    if (jobId) {
      link.href = `/api/jobs/${encodeURIComponent(jobId)}/exports/${format}`;
      link.setAttribute("download", `transcription.${format}`);
      link.removeAttribute("tabindex");
    } else {
      link.removeAttribute("href");
      link.removeAttribute("download");
      link.tabIndex = -1;
    }
  }
}

function stopTracking() {
  window.clearTimeout(pollTimer);
  window.cancelAnimationFrame(animationFrame);
  pollTimer = null;
  animationFrame = null;
}

function setVideo(source = null) {
  ui.video.pause();
  if (blobUrl && blobUrl !== source) {
    URL.revokeObjectURL(blobUrl);
    blobUrl = null;
  }
  mediaReadable = false;
  ui["video-warning"].hidden = true;
  ui["video-duration"].textContent = "—";
  ui["video-placeholder"].hidden = Boolean(source);
  ui.video.hidden = !source;
  if (source) ui.video.src = source;
  else ui.video.removeAttribute("src");
  ui.video.load();
}

function showEmpty(title = "Chaque réplique à sa place.", description = "Lancez une transcription pour retrouver ici les dialogues et leurs repères temporels.") {
  ui["processing-state"].hidden = true;
  ui.segments.hidden = true;
  ui["transcript-placeholder"].hidden = false;
  ui["transcript-placeholder"].querySelector("h3").textContent = title;
  ui["transcript-placeholder"].querySelector("p").textContent = description;
  ui["transcript-placeholder"].querySelector(".empty-tip").hidden = Boolean(currentJob);
  ui["transcript-placeholder"].querySelector(".empty-rule").hidden = Boolean(currentJob);
}

function showProcessing(stage, pending = false) {
  const [title, description] = stageLabels[stage] || (pending ? stageLabels.queued : ["Traitement de votre scène", "Le traitement est en cours sur votre ordinateur."]);
  ui["transcript-placeholder"].hidden = true;
  ui.segments.hidden = true;
  ui["processing-state"].hidden = false;
  ui["processing-title"].textContent = title;
  ui["processing-description"].textContent = description;
  announce(title);
}

function resetDraft() {
  viewVersion += 1;
  stopTracking();
  selectedFile = null;
  currentJob = null;
  result = null;
  renderedResultId = null;
  activeIndex = -1;
  ui["transcription-form"].reset();
  ui["end-seconds"].setCustomValidity("");
  ui["selected-file"].textContent = "Choisir une vidéo";
  ui["video-heading"].textContent = "Aperçu vidéo";
  ui["video-context"].textContent = "Sélectionnez une vidéo pour préparer votre transcription.";
  ui["job-status"].textContent = "En attente";
  ui["job-status"].removeAttribute("data-status");
  ui["transcript-meta"].textContent = "Le texte suivra votre vidéo";
  ui["sync-note"].textContent = "Les repères du texte sont relatifs au début de la scène.";
  ui["delete-job"].hidden = true;
  ui.history.value = "";
  ui.segments.replaceChildren();
  ui["transcript-scroll"].scrollTop = 0;
  setVideo();
  setExports();
  showEmpty();
  showNotice();
  updateSubmit();
}

function chooseFile(file) {
  if (busy || !file) return;
  if (!/\.(mp4|mkv|mov|avi)$/i.test(file.name)) {
    showNotice("Sélectionnez une vidéo MP4, MKV, MOV ou AVI.");
    return;
  }
  if (file.size === 0 || file.size > maxUpload) {
    showNotice(file.size === 0 ? "Ce fichier est vide. Choisissez une autre vidéo." : `Le fichier dépasse la limite de ${maxUpload / 1000000} Mo.`);
    return;
  }
  resetDraft();
  selectedFile = file;
  ui["selected-file"].textContent = file.name;
  ui["video-heading"].textContent = file.name;
  ui["video-context"].textContent = "Définissez éventuellement une plage, puis lancez la transcription.";
  blobUrl = URL.createObjectURL(file);
  setVideo(blobUrl);
  updateSubmit();
  announce(`Vidéo sélectionnée : ${file.name}`);
}

function renderHistory() {
  const initial = new Option("Nouvelle transcription", "");
  const options = jobs.map((job) => new Option(`${job.original_filename} · ${statusLabels[job.status] || job.status}`, job.id));
  ui.history.replaceChildren(initial, ...options);
  ui.history.value = currentJob?.id || "";
}

async function refreshHistory() {
  jobs = await api("/api/jobs");
  renderHistory();
}

function rememberJob(job) {
  jobs = [job, ...jobs.filter((item) => item.id !== job.id)];
  renderHistory();
}

function setSeekAvailability() {
  for (const button of ui.segments.querySelectorAll("button")) button.disabled = !mediaReadable;
}

function updateSync(force = false) {
  const nextIndex = result && mediaReadable ? activeSegmentIndex(result.segments, ui.video.currentTime, result.scene_start_seconds, result.scene_duration_seconds) : -1;
  if (nextIndex === activeIndex && !force) return;
  const oldRow = ui.segments.children[activeIndex];
  if (oldRow) {
    oldRow.classList.remove("active");
    oldRow.removeAttribute("aria-current");
  }
  activeIndex = nextIndex;
  const row = ui.segments.children[activeIndex];
  if (!row) return;
  row.classList.add("active");
  row.setAttribute("aria-current", "true");
  if (ui["auto-follow"].checked) {
    const pane = ui["transcript-scroll"];
    const paneBounds = pane.getBoundingClientRect();
    const rowBounds = row.getBoundingClientRect();
    const rowTop = rowBounds.top - paneBounds.top + pane.scrollTop;
    const target = followScrollPosition(rowTop, rowTop + rowBounds.height, pane.scrollTop, pane.clientHeight);
    if (target !== null) pane.scrollTo({ top: target, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
  }
}

function playbackTick() {
  updateSync();
  if (!ui.video.paused && !ui.video.ended) animationFrame = window.requestAnimationFrame(playbackTick);
}

function renderResult(job) {
  result = job.result;
  if (!result) return;
  if (renderedResultId !== job.id) {
    renderedResultId = job.id;
    activeIndex = -1;
    const fragment = document.createDocumentFragment();
    result.segments.forEach((segment, index) => {
      const item = document.createElement("li");
      item.className = "segment";
      const time = document.createElement("button");
      time.className = "segment-time";
      time.type = "button";
      time.textContent = formatTime(segment.start);
      const sourcePosition = sourceTimeForSegment(segment, result.scene_start_seconds);
      time.title = `Scène ${formatTime(segment.start, true)} · Vidéo ${formatTime(sourcePosition, true)}`;
      time.setAttribute("aria-label", `Aller au dialogue ${index + 1}, ${formatTime(sourcePosition, true)} dans la vidéo`);
      time.addEventListener("click", () => {
        if (!mediaReadable) return;
        ui.video.currentTime = sourcePosition;
        updateSync(true);
      });
      const text = document.createElement("p");
      text.textContent = segment.text;
      item.append(time, text);
      fragment.append(item);
    });
    ui.segments.replaceChildren(fragment);
    ui["transcript-scroll"].scrollTop = 0;
    setSeekAvailability();
  }
  ui["processing-state"].hidden = true;
  ui["transcript-placeholder"].hidden = true;
  ui.segments.hidden = false;
  if (result.segments.length === 0) showEmpty("Aucun dialogue détecté.", "La scène ne contient peut-être pas de parole audible. Vous pouvez essayer une autre plage ou désactiver la détection des passages parlés.");
  const language = { fr: "Français", en: "Anglais" }[result.language] || result.language;
  ui["transcript-meta"].textContent = `${result.segments.length} segment${result.segments.length === 1 ? "" : "s"} · ${language}`;
  ui["video-context"].textContent = `Scène transcrite : ${formatTime(result.scene_start_seconds)} → ${formatTime(result.scene_start_seconds + result.scene_duration_seconds)} dans la vidéo.`;
  ui["sync-note"].textContent = `Les repères du texte commencent à 00:00 de la scène. Décalage dans la vidéo : ${formatTime(result.scene_start_seconds, true)}.`;
  setExports(job.id);
  updateSync(true);
  announce(`Transcription terminée. ${result.segments.length} segments disponibles.`);
}

function applyJob(job) {
  currentJob = job;
  rememberJob(job);
  ui["job-status"].textContent = statusLabels[job.status] || job.status;
  ui["job-status"].dataset.status = job.status;
  ui["delete-job"].hidden = !["COMPLETED", "FAILED"].includes(job.status);
  if (job.status === "COMPLETED") {
    if (!ui.video.getAttribute("src")) setVideo(`/api/jobs/${encodeURIComponent(job.id)}/media`);
    renderResult(job);
  }
  else if (job.status === "FAILED") {
    result = null;
    showEmpty("La transcription s’est interrompue.", job.error?.message || "Une erreur est survenue pendant le traitement.");
    ui["transcript-meta"].textContent = "Consultez le message ci-dessous";
    setExports();
    announce(job.error?.message || "La transcription a échoué.");
  } else {
    result = null;
    ui["transcript-meta"].textContent = "Traitement sur cet ordinateur";
    showProcessing(job.stage, job.status === "PENDING");
    setExports();
  }
  updateSubmit();
}

function schedulePoll(jobId, version) {
  window.clearTimeout(pollTimer);
  pollTimer = window.setTimeout(async () => {
    if (version !== viewVersion) return;
    try {
      const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
      if (version !== viewVersion) return;
      showNotice();
      applyJob(job);
      if (["PENDING", "PROCESSING"].includes(job.status)) schedulePoll(jobId, version);
    } catch (error) {
      if (version !== viewVersion) return;
      showNotice(`${error.message} Nouvelle tentative automatique dans quelques secondes.`);
      schedulePoll(jobId, version);
    }
  }, 1500);
}

async function openJob(jobId) {
  resetDraft();
  const version = viewVersion;
  ui.history.value = jobId;
  try {
    const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    if (version !== viewVersion) return;
    ui["selected-file"].textContent = job.original_filename;
    ui["video-heading"].textContent = job.original_filename;
    ui["start-seconds"].value = job.options.start_seconds;
    ui["end-seconds"].value = job.options.end_seconds ?? "";
    ui.language.value = job.options.language || "auto";
    ui["vad-filter"].checked = job.options.vad_filter;
    ui["beam-size"].value = job.options.beam_size;
    if (job.status === "COMPLETED") setVideo(`/api/jobs/${encodeURIComponent(job.id)}/media`);
    applyJob(job);
    if (["PENDING", "PROCESSING"].includes(job.status)) schedulePoll(job.id, version);
  } catch (error) {
    if (version === viewVersion) showNotice(error.message);
  }
}

ui["transcription-form"].addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedFile || busy) return;
  const start = Number(ui["start-seconds"].value || 0);
  const end = ui["end-seconds"].value === "" ? null : Number(ui["end-seconds"].value);
  ui["end-seconds"].setCustomValidity(end !== null && end <= start ? "La fin doit être supérieure au début de la scène." : "");
  if (!ui["transcription-form"].reportValidity()) return;
  const knownEnd = end ?? (Number.isFinite(ui.video.duration) ? ui.video.duration : null);
  if (knownEnd !== null && knownEnd - start > maxScene) {
    showNotice(`Choisissez une plage de ${maxScene / 60} minutes maximum à l’aide des champs Début et Fin.`);
    return;
  }
  const form = new FormData();
  form.append("file", selectedFile);
  form.append("start_seconds", String(start));
  if (end !== null) form.append("end_seconds", String(end));
  form.append("language", ui.language.value);
  form.append("vad_filter", String(ui["vad-filter"].checked));
  form.append("beam_size", ui["beam-size"].value);
  stopTracking();
  const version = ++viewVersion;
  busy = true;
  currentJob = null;
  result = null;
  renderedResultId = null;
  ui.segments.replaceChildren();
  activeIndex = -1;
  setExports();
  showNotice();
  ui["delete-job"].hidden = true;
  ui["job-status"].textContent = "Import en cours";
  ui["job-status"].dataset.status = "PENDING";
  showProcessing("uploading");
  ui["processing-title"].textContent = "Import de votre vidéo";
  ui["processing-description"].textContent = "Copie du fichier vers le serveur de cet ordinateur.";
  updateSubmit();
  try {
    const job = await api("/api/jobs", { method: "POST", body: form });
    if (version !== viewVersion) return;
    applyJob(job);
    if (["PENDING", "PROCESSING"].includes(job.status)) schedulePoll(job.id, version);
  } catch (error) {
    if (version !== viewVersion) return;
    showNotice(error.message);
    showEmpty("L’import n’a pas abouti.", "Corrigez le problème indiqué, puis relancez la transcription.");
    ui["job-status"].textContent = "Import interrompu";
    ui["job-status"].dataset.status = "FAILED";
  } finally {
    busy = false;
    updateSubmit();
    if (!ui.video.paused) playbackTick();
  }
});

ui["video-file"].addEventListener("change", (event) => chooseFile(event.target.files[0]));
ui["new-job"].addEventListener("click", () => { resetDraft(); ui["video-file"].focus(); });
ui.history.addEventListener("change", () => ui.history.value ? openJob(ui.history.value) : resetDraft());
ui["end-seconds"].addEventListener("input", () => ui["end-seconds"].setCustomValidity(""));
ui["start-seconds"].addEventListener("input", () => ui["end-seconds"].setCustomValidity(""));
for (const name of ["dragenter", "dragover"]) {
  ui["drop-zone"].addEventListener(name, (event) => { event.preventDefault(); if (!busy) ui["drop-zone"].classList.add("dragging"); });
}
for (const name of ["dragleave", "drop"]) {
  ui["drop-zone"].addEventListener(name, (event) => { event.preventDefault(); ui["drop-zone"].classList.remove("dragging"); });
}
ui["drop-zone"].addEventListener("drop", (event) => {
  if (event.dataTransfer.files.length > 1) showNotice("Sélectionnez une seule vidéo à la fois.");
  else chooseFile(event.dataTransfer.files[0]);
});
ui.video.addEventListener("loadedmetadata", () => {
  mediaReadable = true;
  ui["video-warning"].hidden = true;
  ui["video-duration"].textContent = formatTime(ui.video.duration);
  setSeekAvailability();
  updateSync(true);
});
ui.video.addEventListener("error", () => {
  if (!ui.video.getAttribute("src")) return;
  mediaReadable = false;
  ui["video-warning"].hidden = false;
  setSeekAvailability();
  updateSync(true);
});
for (const name of ["timeupdate", "seeked", "seeking", "ratechange", "ended"]) ui.video.addEventListener(name, () => updateSync());
ui.video.addEventListener("play", () => { window.cancelAnimationFrame(animationFrame); playbackTick(); });
ui.video.addEventListener("pause", () => { window.cancelAnimationFrame(animationFrame); updateSync(); });
ui["auto-follow"].addEventListener("change", () => updateSync(true));
ui["delete-job"].addEventListener("click", async () => {
  if (!currentJob || !window.confirm("Supprimer cette transcription et ses fichiers locaux ? Cette action est définitive.")) return;
  const deletingId = currentJob.id;
  ui["delete-job"].disabled = true;
  try {
    await api(`/api/jobs/${encodeURIComponent(deletingId)}`, { method: "DELETE" });
    jobs = jobs.filter((job) => job.id !== deletingId);
    if (currentJob?.id === deletingId) resetDraft();
    renderHistory();
    announce("La transcription et ses fichiers ont été supprimés.");
  } catch (error) {
    showNotice(error.message);
  } finally {
    ui["delete-job"].disabled = false;
  }
});
window.addEventListener("beforeunload", () => { stopTracking(); if (blobUrl) URL.revokeObjectURL(blobUrl); });
refreshHistory().catch((error) => showNotice(error.message));
