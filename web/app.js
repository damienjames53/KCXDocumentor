const state = {
  recordings: [],
  sessions: [],
  selectedSessionId: "",
  session: null,
  activeTab: "trace",
  busy: false,
  lastDraft: "deterministic",
};

const els = {
  apiStatus: document.querySelector("#apiStatus"),
  refreshAll: document.querySelector("#refreshAll"),
  pipelineForm: document.querySelector("#pipelineForm"),
  recordingSelect: document.querySelector("#recordingSelect"),
  targetApplication: document.querySelector("#targetApplication"),
  sessionIdInput: document.querySelector("#sessionIdInput"),
  forceProcess: document.querySelector("#forceProcess"),
  noMediaTools: document.querySelector("#noMediaTools"),
  processButton: document.querySelector("#processButton"),
  deterministicDraftButton: document.querySelector("#deterministicDraftButton"),
  anthropicDraftButton: document.querySelector("#anthropicDraftButton"),
  buildDocxButton: document.querySelector("#buildDocxButton"),
  qaDocxButton: document.querySelector("#qaDocxButton"),
  selectedSessionPill: document.querySelector("#selectedSessionPill"),
  recordingCount: document.querySelector("#recordingCount"),
  sessionCount: document.querySelector("#sessionCount"),
  recordingList: document.querySelector("#recordingList"),
  sessionList: document.querySelector("#sessionList"),
  reloadSession: document.querySelector("#reloadSession"),
  durationMetric: document.querySelector("#durationMetric"),
  segmentMetric: document.querySelector("#segmentMetric"),
  reviewMetric: document.querySelector("#reviewMetric"),
  imageMetric: document.querySelector("#imageMetric"),
  segmentList: document.querySelector("#segmentList"),
  frameGrid: document.querySelector("#frameGrid"),
  artifactList: document.querySelector("#artifactList"),
  jsonPreview: document.querySelector("#jsonPreview"),
  readinessPill: document.querySelector("#readinessPill"),
  readinessList: document.querySelector("#readinessList"),
  activityLog: document.querySelector("#activityLog"),
  activityTemplate: document.querySelector("#activityTemplate"),
};

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  refreshAll();
});

function bindEvents() {
  els.refreshAll.addEventListener("click", refreshAll);
  els.pipelineForm.addEventListener("submit", processRecording);
  els.deterministicDraftButton.addEventListener("click", () => generateDraft(false));
  els.anthropicDraftButton.addEventListener("click", () => generateDraft(true));
  els.buildDocxButton.addEventListener("click", buildDocx);
  els.qaDocxButton.addEventListener("click", runDocxQa);
  els.reloadSession.addEventListener("click", () => loadSelectedSession());
  els.recordingSelect.addEventListener("change", syncSessionIdPlaceholder);

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      state.activeTab = tab.dataset.tab;
      renderTabs();
    });
  });
}

async function refreshAll() {
  setBusy(true);
  try {
    const [recordings, sessions] = await Promise.all([
      apiGet("/api/recordings"),
      apiGet("/api/sessions"),
    ]);
    state.recordings = normalizeCollection(recordings, "recordings");
    state.sessions = normalizeCollection(sessions, "sessions");
    setApiStatus("API ready", "good");
    logActivity("Loaded recordings and sessions.");
    renderRecordings();
    renderSessions();
    syncSessionIdPlaceholder();

    if (!state.selectedSessionId && state.sessions.length > 0) {
      selectSession(getSessionId(state.sessions[0]), { load: true });
    } else {
      renderAll();
    }
  } catch (error) {
    setApiStatus("API unavailable", "bad");
    logActivity(error.message, "error");
    renderRecordings();
    renderSessions();
    renderAll();
  } finally {
    setBusy(false);
  }
}

async function processRecording(event) {
  event.preventDefault();
  const recording = els.recordingSelect.value;
  if (!recording) {
    logActivity("Choose a recording before processing.", "warn");
    return;
  }

  const payload = {
    recording,
    targetApplication: els.targetApplication.value.trim() || "Unknown Application",
    sessionId: els.sessionIdInput.value.trim() || undefined,
    force: els.forceProcess.checked,
    noMediaTools: els.noMediaTools.checked,
  };

  setBusy(true);
  try {
    const result = await apiPost("/api/process", payload);
    const sessionId = result.sessionId || result.session?.sessionId || payload.sessionId;
    logActivity(`Processing complete${sessionId ? ` for ${sessionId}` : ""}.`);
    await refreshSessions();
    if (sessionId) {
      selectSession(sessionId, { load: true });
    }
  } catch (error) {
    logActivity(`Processing failed: ${error.message}`, "error");
  } finally {
    setBusy(false);
  }
}

async function generateDraft(useAnthropic) {
  const sessionId = requireSessionId();
  if (!sessionId) return;

  setBusy(true);
  try {
    const result = await apiPost("/api/generate-draft", {
      sessionId,
      useAnthropic,
      provider: useAnthropic ? "anthropic" : "deterministic",
    });
    state.lastDraft = useAnthropic ? "anthropic" : "deterministic";
    logActivity(`${useAnthropic ? "Anthropic" : "Deterministic"} draft generated.`);
    state.session = mergeSessionResult(state.session, result);
    await loadSession(sessionId);
  } catch (error) {
    logActivity(`Draft generation failed: ${error.message}`, "error");
  } finally {
    setBusy(false);
  }
}

async function buildDocx() {
  const sessionId = requireSessionId();
  if (!sessionId) return;

  setBusy(true);
  try {
    const result = await apiPost("/api/build-docx", { sessionId, draft: state.lastDraft || "deterministic" });
    logActivity(`${state.lastDraft === "anthropic" ? "Anthropic" : "Deterministic"} DOCX build completed.`);
    state.session = mergeSessionResult(state.session, result);
    await loadSession(sessionId);
  } catch (error) {
    logActivity(`DOCX build failed: ${error.message}`, "error");
  } finally {
    setBusy(false);
  }
}

async function runDocxQa() {
  const sessionId = requireSessionId();
  if (!sessionId) return;

  setBusy(true);
  try {
    const normal = await apiPost("/api/qa-docx", { sessionId, draft: state.lastDraft || "deterministic" });
    let strict = null;
    try {
      strict = await apiPost("/api/qa-docx", { sessionId, draft: state.lastDraft || "deterministic", strict: true });
    } catch (error) {
      strict = { passed: false, error: error.message };
    }
    state.session = mergeSessionResult(state.session, {
      qa: {
        normal,
        strict,
        status: normal.passed && strict?.passed ? "publish-ready" : normal.passed ? "review-only" : "failed",
      },
    });
    logActivity(`QA complete: ${state.session.qa.status}.`, state.session.qa.status === "failed" ? "error" : "info");
    renderAll();
  } catch (error) {
    logActivity(`QA failed: ${error.message}`, "error");
  } finally {
    setBusy(false);
  }
}

async function refreshSessions() {
  const sessions = await apiGet("/api/sessions");
  state.sessions = normalizeCollection(sessions, "sessions");
  renderSessions();
}

async function loadSelectedSession() {
  const sessionId = requireSessionId();
  if (sessionId) {
    await loadSession(sessionId);
  }
}

async function loadSession(sessionId) {
  setBusy(true);
  try {
    const session = await apiGet(`/api/session?sessionId=${encodeURIComponent(sessionId)}`);
    state.session = unwrapSession(session);
    state.selectedSessionId = getSessionId(state.session) || sessionId;
    setApiStatus("API ready", "good");
    logActivity(`Loaded session ${state.selectedSessionId}.`);
    renderAll();
  } catch (error) {
    logActivity(`Session load failed: ${error.message}`, "error");
    renderAll();
  } finally {
    setBusy(false);
  }
}

function selectSession(sessionId, options = {}) {
  state.selectedSessionId = sessionId || "";
  els.sessionIdInput.value = state.selectedSessionId;
  renderSessions();
  renderSelectedSessionPill();
  if (options.load && sessionId) {
    loadSession(sessionId);
  }
}

function requireSessionId() {
  const sessionId = state.selectedSessionId || els.sessionIdInput.value.trim();
  if (!sessionId) {
    logActivity("Select or enter a session id first.", "warn");
    return "";
  }
  state.selectedSessionId = sessionId;
  return sessionId;
}

async function apiGet(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  return parseApiResponse(response);
}

async function apiPost(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return parseApiResponse(response);
}

async function parseApiResponse(response) {
  const text = await response.text();
  const data = text ? safeJson(text) : {};
  if (!response.ok) {
    const message = data.error || data.message || `${response.status} ${response.statusText}`;
    throw new Error(message);
  }
  return data;
}

function safeJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text };
  }
}

function normalizeCollection(payload, key) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.[key])) return payload[key];
  if (Array.isArray(payload?.items)) return payload.items;
  return [];
}

function unwrapSession(payload) {
  return payload?.session || payload;
}

function mergeSessionResult(current, result) {
  if (!result || typeof result !== "object") return current;
  const next = result.session || result;
  return { ...(current || {}), ...next };
}

function renderAll() {
  renderSelectedSessionPill();
  renderSummary();
  renderTabs();
  renderReadiness();
}

function renderRecordings() {
  els.recordingSelect.innerHTML = "";
  if (state.recordings.length === 0) {
    els.recordingSelect.append(new Option("No recordings found", ""));
    els.recordingList.innerHTML = `<li class="muted">Place video files in samples/raw and refresh.</li>`;
    els.recordingCount.textContent = "0";
    return;
  }

  els.recordingSelect.append(new Option("Select a recording", ""));
  state.recordings.forEach((recording) => {
    const label = getRecordingLabel(recording);
    const value = getRecordingValue(recording);
    els.recordingSelect.append(new Option(label, value));
  });

  els.recordingList.innerHTML = "";
  state.recordings.forEach((recording) => {
    const item = document.createElement("li");
    item.textContent = getRecordingLabel(recording);
    item.title = getRecordingValue(recording);
    item.addEventListener("click", () => {
      els.recordingSelect.value = getRecordingValue(recording);
      syncSessionIdPlaceholder();
    });
    els.recordingList.append(item);
  });
  els.recordingCount.textContent = String(state.recordings.length);
}

function renderSessions() {
  els.sessionList.innerHTML = "";
  els.sessionCount.textContent = String(state.sessions.length);
  if (state.sessions.length === 0) {
    els.sessionList.innerHTML = `<li class="muted">No processed sessions yet.</li>`;
    return;
  }

  state.sessions.forEach((session) => {
    const sessionId = getSessionId(session);
    const item = document.createElement("li");
    item.className = sessionId === state.selectedSessionId ? "selected" : "";
    item.innerHTML = `
      <strong>${escapeHtml(sessionId || "unknown-session")}</strong>
      <span>${escapeHtml(session.targetApplication || session.recording?.targetApplication || session.sourceName || "")}</span>
    `;
    item.addEventListener("click", () => selectSession(sessionId, { load: true }));
    els.sessionList.append(item);
  });
}

function renderSelectedSessionPill() {
  if (state.selectedSessionId) {
    els.selectedSessionPill.textContent = state.selectedSessionId;
    els.selectedSessionPill.className = "status-pill good";
  } else {
    els.selectedSessionPill.textContent = "No session selected";
    els.selectedSessionPill.className = "status-pill neutral";
  }
}

function renderSummary() {
  const trace = getTrace();
  const segments = getSegments();
  const images = segments.flatMap((segment) => segment.candidateImages || []);
  const reviewCount = segments.filter((segment) => segment.confidence?.needsHumanReview).length;

  els.durationMetric.textContent = formatDuration(trace?.recording?.durationSeconds);
  els.segmentMetric.textContent = segments.length ? String(segments.length) : "--";
  els.reviewMetric.textContent = segments.length ? String(reviewCount) : "--";
  els.imageMetric.textContent = images.length ? String(images.length) : "--";
}

function renderTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === state.activeTab);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("active"));
  document.querySelector(`#${state.activeTab}Tab`)?.classList.add("active");
  renderTrace();
  renderFrames();
  renderArtifacts();
  renderJson();
}

function renderTrace() {
  const segments = getSegments();
  if (segments.length === 0) {
    els.segmentList.className = "segment-list empty-state";
    els.segmentList.textContent = "Select or process a session to inspect trace segments.";
    return;
  }

  els.segmentList.className = "segment-list";
  els.segmentList.innerHTML = "";
  segments.forEach((segment, index) => {
    const confidence = segment.confidence || {};
    const card = document.createElement("article");
    card.className = confidence.needsHumanReview ? "segment-card needs-review" : "segment-card";
    card.innerHTML = `
      <header>
        <strong>${escapeHtml(segment.id || `Segment ${index + 1}`)}</strong>
        <span>${escapeHtml(segment.start || "")} - ${escapeHtml(segment.end || "")}</span>
        <b>${formatPercent(confidence.overall)}</b>
      </header>
      <p>${escapeHtml(segment.speakerText || "No transcript text available.")}</p>
      <div class="tag-row">${renderTags(segment.actionHints || [])}${renderTags(segment.visibleUiText || [], "ui")}</div>
      ${renderReasons(confidence.reasons)}
    `;
    els.segmentList.append(card);
  });
}

function renderFrames() {
  const frames = getSegments().flatMap((segment) =>
    (segment.candidateImages || []).map((image) => ({ ...image, segmentId: segment.id }))
  );
  if (frames.length === 0) {
    els.frameGrid.className = "frame-grid empty-state";
    els.frameGrid.textContent = "Candidate frames will appear after processing.";
    return;
  }

  els.frameGrid.className = "frame-grid";
  els.frameGrid.innerHTML = "";
  frames.slice(0, 48).forEach((frame) => {
    const card = document.createElement("article");
    card.className = "frame-card";
    const path = frame.path || "";
    card.innerHTML = `
      <div class="frame-preview">${path ? `<img src="${escapeAttribute(frameUrl(path))}" alt="Candidate frame ${escapeAttribute(frame.frameId || "")}">` : `<span>No image</span>`}</div>
      <strong>${escapeHtml(frame.frameId || "frame")}</strong>
      <span>${escapeHtml(frame.segmentId || "")} at ${escapeHtml(frame.timestamp || "")}</span>
      <small>${escapeHtml(frame.reviewStatus || "pending")} · ${formatPercent(frame.confidence)}</small>
    `;
    els.frameGrid.append(card);
  });
}

function renderArtifacts() {
  const artifacts = getArtifacts();
  if (artifacts.length === 0) {
    els.artifactList.className = "artifact-list empty-state";
    els.artifactList.textContent = "Generated draft, DOCX, and QA artifacts will appear here.";
    return;
  }

  els.artifactList.className = "artifact-list";
  els.artifactList.innerHTML = "";
  artifacts.forEach((artifact) => {
    const item = document.createElement("article");
    item.innerHTML = `
      <strong>${escapeHtml(artifact.label)}</strong>
      <span>${escapeHtml(artifact.path || artifact.status || "")}</span>
    `;
    els.artifactList.append(item);
  });
}

function renderJson() {
  els.jsonPreview.textContent = JSON.stringify(state.session || {}, null, 2);
}

function renderReadiness() {
  const trace = getTrace();
  const segments = getSegments();
  if (!trace || segments.length === 0) {
    els.readinessPill.textContent = "Pending";
    els.readinessPill.className = "status-pill neutral";
    els.readinessList.innerHTML = `<div class="empty-state">No session loaded.</div>`;
    return;
  }

  const checks = buildReadinessChecks(trace, segments);
  const blockers = checks.filter((check) => check.state === "bad").length;
  const warnings = checks.filter((check) => check.state === "warn").length;
  els.readinessPill.textContent = blockers ? "Blocked" : warnings ? "Review" : "Ready";
  els.readinessPill.className = `status-pill ${blockers ? "bad" : warnings ? "warn" : "good"}`;

  els.readinessList.innerHTML = "";
  checks.forEach((check) => {
    const row = document.createElement("div");
    row.className = `readiness-item ${check.state}`;
    row.innerHTML = `
      <strong>${escapeHtml(check.label)}</strong>
      <span>${escapeHtml(check.detail)}</span>
    `;
    els.readinessList.append(row);
  });
}

function buildReadinessChecks(trace, segments) {
  const reviewCount = segments.filter((segment) => segment.confidence?.needsHumanReview).length;
  const placeholderCount = segments.filter((segment) => /prototype narration|placeholder/i.test(segment.speakerText || "")).length;
  const imageCount = segments.flatMap((segment) => segment.candidateImages || []).length;
  const createdImages = segments.flatMap((segment) => segment.candidateImages || []).filter((image) => image.created).length;
  const lowConfidence = segments.filter((segment) => Number(segment.confidence?.overall || 0) < 0.75).length;

  return [
    {
      label: "Trace loaded",
      state: trace.schemaVersion === 1 ? "good" : "bad",
      detail: trace.schemaVersion === 1 ? "Procedure trace schema version 1." : "Trace is missing or unsupported.",
    },
    {
      label: "Transcript quality",
      state: placeholderCount ? "bad" : lowConfidence ? "warn" : "good",
      detail: placeholderCount ? `${placeholderCount} placeholder segments require real STT or transcript.` : `${lowConfidence} low-confidence segments.`,
    },
    {
      label: "Human review",
      state: reviewCount ? "warn" : "good",
      detail: reviewCount ? `${reviewCount} segments are flagged for review.` : "No segment review flags detected.",
    },
    {
      label: "Candidate images",
      state: imageCount === 0 ? "bad" : createdImages === 0 ? "warn" : "good",
      detail: `${imageCount} candidates, ${createdImages} extracted image files.`,
    },
  ];
}

function getTrace() {
  return state.session?.procedureTrace || state.session?.trace || (state.session?.segments ? state.session : null);
}

function getSegments() {
  return getTrace()?.segments || [];
}

function getArtifacts() {
  const session = state.session || {};
  const artifacts = [];
  const outputs = session.outputs || session.artifacts || {};
  if (session.guideDraft || outputs.guideDraft) artifacts.push({ label: "Guide Draft", path: outputs.guideDraft || "Loaded in session payload" });
  if (session.docx || outputs.docx || outputs.userGuide) artifacts.push({ label: "DOCX", path: outputs.docx || outputs.userGuide || session.docx });
  if (session.qa || outputs.qa) artifacts.push({ label: "QA", path: outputs.qa || session.qa?.status || "QA result available" });
  if (session.manifest?.outputs) {
    Object.entries(session.manifest.outputs).forEach(([label, path]) => artifacts.push({ label, path }));
  }
  if (Array.isArray(session.generated)) {
    session.generated.forEach((file) => artifacts.push({ label: file.name || "Generated file", path: file.relativePath || "" }));
  }
  return artifacts;
}

function getRecordingLabel(recording) {
  if (typeof recording === "string") return recording;
  return recording.name || recording.sourceName || recording.fileName || recording.path || "recording";
}

function getRecordingValue(recording) {
  if (typeof recording === "string") return recording;
  return recording.path || recording.name || recording.sourceFile || recording.fileName || "";
}

function getSessionId(session) {
  if (typeof session === "string") return session;
  return session?.sessionId || session?.id || session?.name || "";
}

function syncSessionIdPlaceholder() {
  const recording = els.recordingSelect.value;
  const base = recording.split("/").pop()?.replace(/\.[^.]+$/, "") || "recording";
  els.sessionIdInput.placeholder = `${slugify(base)}-test`;
}

function frameUrl(path) {
  const sessionId = state.selectedSessionId || getSessionId(state.session);
  return `/api/session?sessionId=${encodeURIComponent(sessionId)}&asset=${encodeURIComponent(path)}`;
}

function formatDuration(seconds) {
  if (!Number.isFinite(Number(seconds))) return "--";
  const total = Math.round(Number(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return hours ? `${hours}h ${minutes}m` : `${minutes}m ${secs}s`;
}

function formatPercent(value) {
  if (!Number.isFinite(Number(value))) return "--";
  return `${Math.round(Number(value) * 100)}%`;
}

function renderTags(values, className = "") {
  return values.slice(0, 8).map((value) => `<span class="tag ${className}">${escapeHtml(value)}</span>`).join("");
}

function renderReasons(reasons = []) {
  if (!reasons.length) return "";
  return `<ul class="reason-list">${reasons.map((reason) => `<li>${escapeHtml(reason)}</li>`).join("")}</ul>`;
}

function setApiStatus(text, stateName) {
  els.apiStatus.textContent = text;
  els.apiStatus.className = `status-pill ${stateName}`;
}

function setBusy(isBusy) {
  state.busy = isBusy;
  [
    els.refreshAll,
    els.processButton,
    els.deterministicDraftButton,
    els.anthropicDraftButton,
    els.buildDocxButton,
    els.qaDocxButton,
    els.reloadSession,
  ].forEach((button) => {
    button.disabled = isBusy;
  });
  document.body.classList.toggle("busy", isBusy);
}

function logActivity(message, level = "info") {
  const item = els.activityTemplate.content.firstElementChild.cloneNode(true);
  item.className = level;
  item.querySelector(".activity-time").textContent = new Date().toLocaleTimeString();
  item.querySelector(".activity-message").textContent = message;
  els.activityLog.prepend(item);
  while (els.activityLog.children.length > 12) {
    els.activityLog.lastElementChild.remove();
  }
}

function slugify(value) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 48);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}
