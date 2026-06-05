const state = {
  recordings: [],
  transcripts: [],
  sessions: [],
  selectedSessionId: "",
  session: null,
  generationMetadata: null,
  frameReview: {
    endpointAvailable: null,
    items: {},
  },
  frameCapturePicker: {
    open: false,
    sessionId: "",
  },
  frameInspect: {
    open: false,
    frameId: "",
  },
  usage: {
    range: "month",
    sort: "date-desc",
    summary: null,
    currentMonthSummary: null,
    currentMonthLoading: false,
    loading: false,
    error: "",
  },
  activePage: "workspace",
  activeTab: "trace",
  auth: {
    config: null,
    client: null,
    account: null,
    initialized: false,
    loading: true,
    error: "",
  },
  busy: false,
  operationMessage: "",
  operationMessages: [],
  operationMessageIndex: 0,
  operationTimer: null,
};

const AI_CREATE_MESSAGES = [
  "Reading the walkthrough...",
  "Finding the workflow structure...",
  "Choosing the clearest screenshots...",
  "Drafting trainer-ready steps...",
  "Checking for reviewer concerns...",
  "Building the Word guide...",
  "Running local QA checks...",
];

const RECORDING_PROCESS_MESSAGES = [
  "Preparing the local recording pipeline...",
  "Reading recording details...",
  "Extracting audio and transcript evidence...",
  "Running local transcription when no transcript is selected...",
  "Sampling candidate screenshots...",
  "Checking frame quality and visual changes...",
  "Building the review session...",
  "Almost ready for frame review...",
];

const els = {
  workspacePage: document.querySelector("#workspacePage"),
  usagePage: document.querySelector("#usagePage"),
  authGate: document.querySelector("#authGate"),
  authStatusText: document.querySelector("#authStatusText"),
  loginButton: document.querySelector("#loginButton"),
  authUserPanel: document.querySelector("#authUserPanel"),
  authUserName: document.querySelector("#authUserName"),
  logoutButton: document.querySelector("#logoutButton"),
  helpButton: document.querySelector("#helpButton"),
  helpDrawerShell: document.querySelector("#helpDrawerShell"),
  helpScrim: document.querySelector("#helpScrim"),
  closeHelpDrawer: document.querySelector("#closeHelpDrawer"),
  helpSearch: document.querySelector("#helpSearch"),
  helpChips: document.querySelector("#helpChips"),
  helpResults: document.querySelector("#helpResults"),
  helpResponse: document.querySelector("#helpResponse"),
  globalUsageButton: document.querySelector("#globalUsageButton"),
  globalUsageMetric: document.querySelector("#globalUsageMetric"),
  refreshAll: document.querySelector("#refreshAll"),
  pipelineForm: document.querySelector("#pipelineForm"),
  recordingFile: document.querySelector("#recordingFile"),
  importRecordingButton: document.querySelector("#importRecordingButton"),
  transcriptFile: document.querySelector("#transcriptFile"),
  importTranscriptButton: document.querySelector("#importTranscriptButton"),
  recordingSelect: document.querySelector("#recordingSelect"),
  transcriptSelect: document.querySelector("#transcriptSelect"),
  targetApplication: document.querySelector("#targetApplication"),
  sourceProfile: document.querySelector("#sourceProfile"),
  sessionIdInput: document.querySelector("#sessionIdInput"),
  forceProcess: document.querySelector("#forceProcess"),
  noMediaTools: document.querySelector("#noMediaTools"),
  processButton: document.querySelector("#processButton"),
  generateDraftButton: document.querySelector("#generateDraftButton"),
  buildDocxButton: document.querySelector("#buildDocxButton"),
  qaDocxButton: document.querySelector("#qaDocxButton"),
  qaStatusTitle: document.querySelector("#qaStatusTitle"),
  qaStatusText: document.querySelector("#qaStatusText"),
  operationStatus: document.querySelector("#operationStatus"),
  operationStatusText: document.querySelector("#operationStatusText"),
  selectedSessionPill: document.querySelector("#selectedSessionPill"),
  recordingCount: document.querySelector("#recordingCount"),
  sessionCount: document.querySelector("#sessionCount"),
  recordingList: document.querySelector("#recordingList"),
  sessionList: document.querySelector("#sessionList"),
  reloadSession: document.querySelector("#reloadSession"),
  clearSession: document.querySelector("#clearSession"),
  durationMetric: document.querySelector("#durationMetric"),
  segmentMetric: document.querySelector("#segmentMetric"),
  reviewMetric: document.querySelector("#reviewMetric"),
  imageMetric: document.querySelector("#imageMetric"),
  segmentList: document.querySelector("#segmentList"),
  frameReviewStatus: document.querySelector("#frameReviewStatus"),
  addFrameForm: document.querySelector("#addFrameForm"),
  addFrameTimestamp: document.querySelector("#addFrameTimestamp"),
  addFrameSegment: document.querySelector("#addFrameSegment"),
  addFrameButton: document.querySelector("#addFrameButton"),
  addFrameTimestampButton: document.querySelector("#addFrameTimestampButton"),
  frameCapturePicker: document.querySelector("#frameCapturePicker"),
  frameCaptureStatus: document.querySelector("#frameCaptureStatus"),
  sessionVideo: document.querySelector("#sessionVideo"),
  sessionVideoTime: document.querySelector("#sessionVideoTime"),
  useVideoTimeButton: document.querySelector("#useVideoTimeButton"),
  closeFrameCapture: document.querySelector("#closeFrameCapture"),
  frameInspectModal: document.querySelector("#frameInspectModal"),
  frameInspectTitle: document.querySelector("#frameInspectTitle"),
  frameInspectMeta: document.querySelector("#frameInspectMeta"),
  frameInspectImage: document.querySelector("#frameInspectImage"),
  frameInspectDetails: document.querySelector("#frameInspectDetails"),
  closeFrameInspect: document.querySelector("#closeFrameInspect"),
  frameGrid: document.querySelector("#frameGrid"),
  artifactList: document.querySelector("#artifactList"),
  generationMetadata: document.querySelector("#generationMetadata"),
  usageStatus: document.querySelector("#usageStatus"),
  usageDocumentMetric: document.querySelector("#usageDocumentMetric"),
  usageTokenMetric: document.querySelector("#usageTokenMetric"),
  usageInOutMetric: document.querySelector("#usageInOutMetric"),
  usagePageMetric: document.querySelector("#usagePageMetric"),
  usageCostMetric: document.querySelector("#usageCostMetric"),
  usageCostPerPageMetric: document.querySelector("#usageCostPerPageMetric"),
  usageSort: document.querySelector("#usageSort"),
  usageBreakdown: document.querySelector("#usageBreakdown"),
  jsonPreview: document.querySelector("#jsonPreview"),
  readinessPill: document.querySelector("#readinessPill"),
  readinessList: document.querySelector("#readinessList"),
  activityLog: document.querySelector("#activityLog"),
  activityTemplate: document.querySelector("#activityTemplate"),
};

const HELP_TOPICS = [
  {
    id: "quick-start",
    title: "Create a guide from a recording",
    chips: ["Quick start", "Create guide"],
    keywords: ["recording", "process", "guide", "docx", "workflow"],
    body: [
      "Use this path when you already have a screen recording ready for documentation.",
      "Select the recording, choose a transcript if one is available, set the target application, then choose Process Recording.",
      "Review frames before creating the guide. Rejected frames are excluded from the AI context.",
      "Choose Create Guide to generate the AI draft, build the DOCX, and run local QA in one workflow.",
    ],
    action: { label: "Open Workspace", type: "page", target: "workspace" },
  },
  {
    id: "transcripts",
    title: "Use transcripts and local Whisper",
    chips: ["Transcripts", "Whisper"],
    keywords: ["transcript", "teams", "vtt", "whisper", "stt", "audio"],
    body: [
      "Use a Teams transcript when one is available. It usually improves step wording and reduces ambiguity.",
      "Leave Transcript blank when no transcript exists. KCXDocumentor will use local Whisper transcription during processing when the local tools and model are available.",
      "Transcript import copies the file into the local sample area, then makes it selectable in the Transcript dropdown.",
    ],
  },
  {
    id: "frame-review",
    title: "Approve and reject screenshots",
    chips: ["Frame review", "Screenshots"],
    keywords: ["frame", "frames", "screenshot", "screenshots", "approve", "reject", "teams overlay", "candidate", "image"],
    body: [
      "Open the Frames tab after processing a recording.",
      "Approve screenshots that clearly show the application state needed by the guide.",
      "Reject Teams overlays, participant tiles, title cards, transitions, or confusing application states.",
      "Use Add Candidate to open the video picker, pause on the desired moment, and capture the frame manually.",
      "Reviewer notes are preserved as guidance. Rejected images are not sent into guide generation.",
    ],
    action: { label: "Open Frames Tab", type: "tab", target: "frames" },
  },
  {
    id: "qa",
    title: "Understand QA status",
    chips: ["QA", "Review"],
    keywords: ["qa", "quality", "comments", "publish", "review", "warnings"],
    body: [
      "Create Guide runs local QA automatically after the DOCX is built. QA does not use AI tokens.",
      "Use Re-run QA after regenerating the guide or changing screenshot approvals.",
      "A review-only result usually means the guide exists but needs a human check, often because reviewer comments or warnings are present.",
      "Before sharing externally, open the DOCX and confirm the body reads like a finished user guide with no internal pipeline language.",
    ],
  },
  {
    id: "download",
    title: "Download or save the DOCX",
    chips: ["Download DOCX", "Save As"],
    keywords: ["download", "save", "docx", "filename", "export"],
    body: [
      "Download DOCX becomes available after Create Guide successfully builds the Word file.",
      "Supported browsers open a system Save dialog so you can choose the folder and filename.",
      "If the browser cannot open a native Save dialog, KCXDocumentor falls back to a normal browser download with a guide-specific filename.",
      "The Artifacts tab also includes a DOCX download link for the selected session.",
    ],
    action: { label: "Open Artifacts Tab", type: "tab", target: "artifacts" },
  },
  {
    id: "ai-spend",
    title: "Track AI spend",
    chips: ["AI spend", "Tokens"],
    keywords: ["tokens", "cost", "spend", "usage", "month", "anthropic"],
    body: [
      "AI Spend shows documents, token totals, input/output split, and estimated cost by day, week, month, or year.",
      "The header shows Current Month Spend for the calendar month.",
      "Usage persists even when sessions or generated artifacts are deleted, so reporting remains auditable.",
      "Failed AI attempts are counted when usage is available from the provider response.",
    ],
    action: { label: "Open AI Spend", type: "page", target: "usage" },
  },
  {
    id: "full-guide",
    title: "Open the full user guide",
    chips: ["Full guide"],
    keywords: ["manual", "documentation", "user guide", "help docx"],
    body: [
      "Download the full KCXDocumentor user guide when you need step-by-step workflow instructions, screenshots, troubleshooting notes, or first-test recommendations.",
    ],
    action: { label: "Download User Guide", type: "download", target: "/api/user-guide" },
  },
];

document.addEventListener("DOMContentLoaded", async () => {
  bindEvents();
  await initializeAuth();
  refreshAll();
});

function bindEvents() {
  els.loginButton.addEventListener("click", login);
  els.logoutButton.addEventListener("click", logout);
  els.refreshAll.addEventListener("click", refreshAll);
  els.helpButton.addEventListener("click", openHelpDrawer);
  els.helpScrim.addEventListener("click", closeHelpDrawer);
  els.closeHelpDrawer.addEventListener("click", closeHelpDrawer);
  els.helpSearch.addEventListener("input", renderHelpDrawer);
  els.helpChips.addEventListener("click", handleHelpChipClick);
  els.helpResults.addEventListener("click", handleHelpResultClick);
  els.helpResponse.addEventListener("click", handleHelpActionClick);
  els.globalUsageButton.addEventListener("click", () => {
    setActivePage("usage");
  });
  els.importRecordingButton.addEventListener("click", importRecording);
  els.importTranscriptButton.addEventListener("click", importTranscript);
  els.pipelineForm.addEventListener("submit", processRecording);
  els.addFrameForm.addEventListener("submit", addFrameCandidate);
  els.addFrameButton.addEventListener("click", openFrameCapturePicker);
  els.useVideoTimeButton.addEventListener("click", addFrameCandidateFromVideo);
  els.closeFrameCapture.addEventListener("click", closeFrameCapturePicker);
  els.sessionVideo.addEventListener("loadedmetadata", updateSessionVideoTime);
  els.sessionVideo.addEventListener("timeupdate", updateSessionVideoTime);
  els.sessionVideo.addEventListener("seeked", updateSessionVideoTime);
  els.sessionVideo.addEventListener("error", handleSessionVideoError);
  els.closeFrameInspect.addEventListener("click", closeFrameInspect);
  els.frameInspectModal.addEventListener("click", handleFrameInspectBackdrop);
  document.addEventListener("keydown", handleGlobalKeydown);
  els.frameGrid.addEventListener("click", handleFrameAction);
  els.frameGrid.addEventListener("change", handleFrameFieldChange);
  els.frameGrid.addEventListener("input", handleFrameNoteInput);
  els.sessionList.addEventListener("click", handleSessionListClick);
  els.artifactList.addEventListener("click", handleArtifactDownloadClick);
  els.generateDraftButton.addEventListener("click", generateDraft);
  els.buildDocxButton.addEventListener("click", downloadDocx);
  els.qaDocxButton.addEventListener("click", runDocxQa);
  els.reloadSession.addEventListener("click", () => loadSelectedSession());
  els.clearSession.addEventListener("click", clearSelectedSession);
  els.recordingSelect.addEventListener("change", handleRecordingSelectionChange);
  els.sessionIdInput.addEventListener("input", updateActionAvailability);

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      state.activeTab = tab.dataset.tab;
      renderTabs();
    });
  });

  document.querySelectorAll("[data-page]").forEach((button) => {
    button.addEventListener("click", () => setActivePage(button.dataset.page));
  });

  document.querySelectorAll("[data-usage-range]").forEach((button) => {
    button.addEventListener("click", () => {
      state.usage.range = button.dataset.usageRange;
      loadUsageSummary();
    });
  });
  els.usageSort?.addEventListener("change", () => {
    state.usage.sort = els.usageSort.value || "date-desc";
    renderUsage();
  });
}

async function initializeAuth() {
  state.auth.loading = true;
  renderAuth();
  try {
    const payload = await fetchJsonWithoutAuth("/api/auth-config");
    state.auth.config = payload.auth || { enabled: false };
    if (!state.auth.config.enabled) {
      state.auth.initialized = true;
      state.auth.loading = false;
      renderAuth();
      return;
    }
    if (!window.msal?.PublicClientApplication) {
      throw new Error("MSAL browser library is not available.");
    }
    state.auth.client = new window.msal.PublicClientApplication({
      auth: {
        clientId: state.auth.config.clientId,
        authority: state.auth.config.authority,
        redirectUri: state.auth.config.redirectUri || window.location.origin + "/",
        postLogoutRedirectUri: state.auth.config.postLogoutRedirectUri || window.location.origin + "/",
        navigateToLoginRequestUrl: false,
      },
      cache: {
        cacheLocation: "localStorage",
        storeAuthStateInCookie: false,
      },
      system: {
        loggerOptions: {
          piiLoggingEnabled: false,
          logLevel: window.msal.LogLevel.Warning,
        },
      },
    });
    await state.auth.client.initialize?.();
    const redirectResult = await state.auth.client.handleRedirectPromise();
    const account = redirectResult?.account || state.auth.client.getActiveAccount() || state.auth.client.getAllAccounts()[0] || null;
    if (account) {
      state.auth.client.setActiveAccount(account);
      state.auth.account = account;
      await establishLocalAuthSession();
    }
    state.auth.initialized = true;
    state.auth.error = "";
  } catch (error) {
    state.auth.error = error.message || "Authentication failed to initialize.";
    logActivity(`Authentication setup failed: ${state.auth.error}`, "error");
  } finally {
    state.auth.loading = false;
    renderAll();
  }
}

async function login() {
  if (!state.auth.client || !state.auth.config?.enabled) return;
  await state.auth.client.loginRedirect({
    scopes: authScopes(),
    prompt: "select_account",
  });
}

async function logout() {
  if (!state.auth.client || !state.auth.account) return;
  try {
    await fetch("/api/logout", { method: "POST" });
  } catch {
    // Logout should continue even if the local session cookie is already gone.
  }
  await state.auth.client.logoutRedirect({
    account: state.auth.account,
    postLogoutRedirectUri: state.auth.config?.postLogoutRedirectUri || window.location.origin + "/",
  });
}

async function establishLocalAuthSession() {
  const token = await authToken();
  if (!token) return;
  await fetchJsonWithBearer("/api/auth-session", token);
}

function authScopes() {
  return Array.isArray(state.auth.config?.scopes) && state.auth.config.scopes.length
    ? state.auth.config.scopes
    : ["openid", "profile"];
}

function isAuthenticated() {
  return state.auth.config?.enabled === false || Boolean(state.auth.account);
}

async function authToken() {
  if (state.auth.config?.enabled === false) return "";
  if (!state.auth.client || !state.auth.account) {
    throw new Error("Sign in is required.");
  }
  try {
    const result = await state.auth.client.acquireTokenSilent({
      account: state.auth.account,
      scopes: authScopes(),
    });
    const idToken = result.idToken || state.auth.account.idToken || "";
    if (!idToken) {
      throw new Error("Could not acquire an ID token for the KCXDocumentor API proxy. Sign out and sign in again.");
    }
    return idToken;
  } catch (error) {
    if (isInteractionRequired(error)) {
      await state.auth.client.loginRedirect({ scopes: authScopes() });
      return "";
    }
    throw error;
  }
}

function isInteractionRequired(error) {
  const code = String(error?.errorCode || error?.error || "");
  return error instanceof window.msal.InteractionRequiredAuthError
    || ["interaction_required", "login_required", "consent_required"].includes(code);
}

async function authHeaders(baseHeaders = {}) {
  const headers = { ...baseHeaders };
  const token = await authToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

async function fetchJsonWithoutAuth(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  return parseApiResponse(response);
}

async function fetchJsonWithBearer(path, token) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
    },
  });
  return parseApiResponse(response);
}

async function refreshAll() {
  setBusy(true);
  try {
    const [recordings, sessions, transcripts] = await Promise.all([
      apiGet("/api/recordings"),
      apiGet("/api/sessions"),
      loadTranscripts(),
    ]);
    state.recordings = normalizeCollection(recordings, "recordings");
    state.sessions = sortSessions(normalizeCollection(sessions, "sessions"));
    state.transcripts = normalizeCollection(transcripts, "transcripts");
    logActivity("Loaded recordings and sessions.");
    renderRecordings();
    renderTranscripts();
    renderSessions();
    syncSessionIdPlaceholder();
    loadCurrentMonthSpend({ silent: true });

    renderAll();
  } catch (error) {
    logActivity(error.message, "error");
    renderRecordings();
    renderTranscripts();
    renderSessions();
    renderAll();
  } finally {
    setBusy(false);
  }
}

async function loadTranscripts() {
  try {
    return await apiGet("/api/transcripts");
  } catch {
    return { transcripts: [] };
  }
}

async function loadUsageSummary(options = {}) {
  const range = state.usage.range || "day";
  state.usage.loading = true;
  state.usage.error = "";
  renderUsage();
  try {
    const summary = await cloudApiGet(`/api/usage-summary?range=${encodeURIComponent(range)}`);
    state.usage.summary = normalizeUsageSummary(summary, range);
  } catch (error) {
    state.usage.summary = null;
    state.usage.error = error.message;
    if (!options.silent) {
      logActivity(`Usage summary unavailable: ${error.message}`, "warn");
    }
  } finally {
    state.usage.loading = false;
    renderUsage();
  }
}

async function loadCurrentMonthSpend(options = {}) {
  state.usage.currentMonthLoading = true;
  renderGlobalUsage();
  try {
    const summary = await cloudApiGet("/api/usage-summary?range=month");
    state.usage.currentMonthSummary = normalizeUsageSummary(summary, "month");
  } catch (error) {
    state.usage.currentMonthSummary = null;
    if (!options.silent) {
      logActivity(`Current month spend unavailable: ${error.message}`, "warn");
    }
  } finally {
    state.usage.currentMonthLoading = false;
    renderGlobalUsage();
  }
}

async function importRecording() {
  const file = els.recordingFile.files?.[0];
  if (!file) {
    logActivity("Choose a recording file to import.", "warn");
    return;
  }

  const formData = new FormData();
  formData.append("recording", file);

  setBusy(true);
  try {
    const result = await apiPostForm("/api/import-recording", formData);
    const imported = getRecordingValue(result.recording || result.fileName || result.name || file.name);
    logActivity(`Imported recording ${imported}.`);
    els.recordingFile.value = "";
    await refreshAll();
    selectRecording(imported);
  } catch (error) {
    logActivity(`Recording import failed: ${error.message}`, "error");
  } finally {
    setBusy(false);
  }
}

async function importTranscript() {
  const file = els.transcriptFile.files?.[0];
  if (!file) {
    logActivity("Choose a transcript file to import.", "warn");
    return;
  }

  const formData = new FormData();
  formData.append("transcript", file);

  setBusy(true);
  try {
    const result = await apiPostForm("/api/import-transcript", formData);
    const imported = getTranscriptValue(result.transcript || result.path || result.fileName || result.name || file.name);
    logActivity(`Imported transcript ${imported}.`);
    els.transcriptFile.value = "";
    upsertTranscript(imported);
    renderTranscripts();
    els.transcriptSelect.value = imported;
  } catch (error) {
    logActivity(`Transcript import failed: ${error.message}`, "error");
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
    sourceProfile: els.sourceProfile.value || "standard",
    sessionId: els.sessionIdInput.value.trim() || undefined,
    transcript: getSelectedTranscript() || undefined,
    force: els.forceProcess.checked,
    noMediaTools: els.noMediaTools.checked,
  };

  const transcriptMessage = payload.transcript
    ? "Processing recording with the selected transcript..."
    : "Processing recording locally. Whisper transcription may take a few minutes...";
  setOperation(transcriptMessage, RECORDING_PROCESS_MESSAGES);
  setBusy(true);
  try {
    const result = await apiPost("/api/process", payload);
    const sessionId = result.sessionId || result.session?.sessionId || payload.sessionId;
    setOperation("Processing complete. Review frames, then choose Create Guide.");
    logActivity(`Processing complete${sessionId ? ` for ${sessionId}` : ""}. Review frames before creating the guide.`);
    await refreshSessions();
    if (sessionId) {
      selectSession(sessionId, { load: true });
    }
  } catch (error) {
    setOperation(`Recording processing failed: ${error.message}`);
    logActivity(`Processing failed: ${error.message}`, "error");
  } finally {
    setBusy(false);
    window.setTimeout(() => {
      if (!state.busy) setOperation("");
    }, 9000);
  }
}

async function generateDraft() {
  const sessionId = requireSessionId();
  if (!sessionId) return;

  setOperation("Starting AI guide creation...", AI_CREATE_MESSAGES);
  setBusy(true);
  try {
    setOperation("Reading the walkthrough and building the guide structure...", AI_CREATE_MESSAGES);
    const draftResult = await cloudApiPost("/api/generate-draft", { sessionId });
    assertCommandSucceeded(draftResult, "AI draft generation");
    logActivity("Anthropic draft generated.");
    state.session = mergeSessionResult(state.session, draftResult);
    await refreshSessionState(sessionId);

    setOperation("Building the Word guide from the AI draft...", AI_CREATE_MESSAGES);
    await buildDocxForSession(sessionId);

    setOperation("Running local QA checks on the Word guide...", AI_CREATE_MESSAGES);
    await runDocxQaForSession(sessionId);

    await loadUsageSummary({ silent: true });
    await loadCurrentMonthSpend({ silent: true });
    setOperation("Guide ready. Download the DOCX when you are ready to review.");
    logActivity("Guide created, DOCX built, and QA completed.");
  } catch (error) {
    await loadUsageSummary({ silent: true });
    await loadCurrentMonthSpend({ silent: true });
    setOperation("Guide creation stopped. Failed AI usage is recorded when Anthropic returned token data.");
    logActivity(`Guide creation failed: ${error.message}`, "error");
  } finally {
    setBusy(false);
    window.setTimeout(() => {
      if (!state.busy) setOperation("");
    }, 2500);
  }
}

async function buildDocxForSession(sessionId) {
  const result = await apiPost("/api/build-docx", { sessionId });
  assertCommandSucceeded(result, "DOCX build");
  logActivity("DOCX built.");
  state.session = mergeSessionResult(state.session, result);
  await refreshSessionState(sessionId);
  return result;
}

async function runDocxQa() {
  const sessionId = requireSessionId();
  if (!sessionId) return;

  setBusy(true);
  try {
    await runDocxQaForSession(sessionId);
  } catch (error) {
    logActivity(`QA failed: ${error.message}`, "error");
  } finally {
    setBusy(false);
  }
}

async function runDocxQaForSession(sessionId) {
  const normal = await apiPost("/api/qa-docx", { sessionId });
  let strict = null;
  try {
    strict = await apiPost("/api/qa-docx", { sessionId, strict: true });
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
  return state.session.qa;
}

async function downloadDocx() {
  const artifact = getArtifacts().find((item) => /user_guide.*\.docx$/i.test(item.name || item.path || ""));
  if (!artifact) {
    logActivity("Build a guide before downloading the DOCX.", "warn");
    return;
  }
  await saveDocxArtifact(artifact);
}

async function handleArtifactDownloadClick(event) {
  const link = event.target.closest(".artifact-download");
  if (!link || !/\.docx$/i.test(link.getAttribute("download") || "")) {
    return;
  }
  event.preventDefault();
  const artifact = getArtifacts().find((item) => artifactDownloadUrl(item) === link.getAttribute("href"));
  if (!artifact) {
    return;
  }
  await saveDocxArtifact(artifact);
}

async function saveDocxArtifact(artifact) {
  const downloadUrl = artifactDownloadUrl(artifact);
  if (!downloadUrl) {
    logActivity("Build a guide before downloading the DOCX.", "warn");
    return;
  }
  const suggestedName = downloadNameForArtifact(artifact);
  if (window.showSaveFilePicker) {
    try {
      const response = await fetch(downloadUrl);
      if (!response.ok) {
        throw new Error(`Download failed with HTTP ${response.status}`);
      }
      const handle = await window.showSaveFilePicker({
        suggestedName,
        types: [
          {
            description: "Word document",
            accept: {
              "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
            },
          },
        ],
      });
      const writable = await handle.createWritable();
      await writable.write(await response.blob());
      await writable.close();
      logActivity(`Saved ${handle.name || suggestedName}.`);
      return;
    } catch (error) {
      if (error?.name === "AbortError") {
        logActivity("DOCX save canceled.", "warn");
        return;
      }
      logActivity(`Native save failed; using browser download. ${error.message}`, "warn");
    }
  }
  const link = document.createElement("a");
  link.href = downloadUrl;
  link.download = suggestedName;
  document.body.append(link);
  link.click();
  link.remove();
}

async function refreshSessions() {
  const sessions = await apiGet("/api/sessions");
  state.sessions = sortSessions(normalizeCollection(sessions, "sessions"));
  renderSessions();
}

async function loadSelectedSession() {
  const sessionId = requireSessionId();
  if (sessionId) {
    await loadSession(sessionId);
  }
}

async function clearSelectedSession() {
  const sessionId = requireSessionId();
  if (!sessionId) return;
  await deleteSession(sessionId);
}

async function deleteSession(sessionId) {
  if (!window.confirm(`Delete processed session "${sessionId}" and its generated guide artifacts?`)) {
    return;
  }

  setBusy(true);
  try {
    const result = await apiPost("/api/delete-session", { sessionId });
    const deleted = Array.isArray(result.deleted) ? result.deleted.length : 0;
    logActivity(`Deleted ${sessionId}; removed ${deleted} folder${deleted === 1 ? "" : "s"}.`);
    if (state.selectedSessionId === sessionId || els.sessionIdInput.value.trim() === sessionId) {
      state.selectedSessionId = "";
      state.session = null;
      state.generationMetadata = null;
      state.frameReview = { endpointAvailable: null, items: {} };
      resetFrameCapturePicker();
      closeFrameInspect();
      els.sessionIdInput.value = "";
    }
    await refreshAll();
  } catch (error) {
    logActivity(`Session cleanup failed: ${error.message}`, "error");
    renderAll();
  } finally {
    setBusy(false);
  }
}

function handleSessionListClick(event) {
  const deleteButton = event.target.closest("[data-session-delete]");
  if (deleteButton) {
    event.stopPropagation();
    deleteSession(deleteButton.dataset.sessionDelete);
    return;
  }

  const sessionButton = event.target.closest("[data-session-select]");
  if (sessionButton) {
    selectSession(sessionButton.dataset.sessionSelect, { load: true });
  }
}

async function loadSession(sessionId) {
  setBusy(true);
  try {
    const session = await apiGet(`/api/session?sessionId=${encodeURIComponent(sessionId)}`);
    state.session = unwrapSession(session);
    state.selectedSessionId = getSessionId(state.session) || sessionId;
    state.generationMetadata = normalizeGenerationMetadata(state.session?.generation);
    await loadFrameReview(state.selectedSessionId);
    if (!state.generationMetadata?.title) {
      await hydrateGenerationMetadata();
    }
    logActivity(`Loaded session ${state.selectedSessionId}.`);
    renderAll();
  } catch (error) {
    logActivity(`Session load failed: ${error.message}`, "error");
    renderAll();
  } finally {
    setBusy(false);
  }
}

async function refreshSessionState(sessionId) {
  const session = await apiGet(`/api/session?sessionId=${encodeURIComponent(sessionId)}`);
  state.session = unwrapSession(session);
  state.selectedSessionId = getSessionId(state.session) || sessionId;
  state.generationMetadata = normalizeGenerationMetadata(state.session?.generation);
  await loadFrameReview(state.selectedSessionId);
  if (!state.generationMetadata?.title) {
    await hydrateGenerationMetadata();
  }
  renderAll();
}

function selectSession(sessionId, options = {}) {
  state.selectedSessionId = sessionId || "";
  state.generationMetadata = null;
  state.frameReview = { endpointAvailable: null, items: {} };
  resetFrameCapturePicker();
  closeFrameInspect();
  els.sessionIdInput.value = state.selectedSessionId;
  renderSessions();
  renderSelectedSessionPill();
  updateActionAvailability();
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

async function cloudApiGet(path) {
  const response = await fetch(path, { headers: await authHeaders({ Accept: "application/json" }) });
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

async function cloudApiPost(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: await authHeaders({
      Accept: "application/json",
      "Content-Type": "application/json",
    }),
    body: JSON.stringify(payload),
  });
  return parseApiResponse(response);
}

async function apiPostForm(path, formData) {
  const response = await fetch(path, {
    method: "POST",
    headers: { Accept: "application/json" },
    body: formData,
  });
  return parseApiResponse(response);
}

function assertCommandSucceeded(response, label) {
  const rawCode = response?.result?.returnCode;
  if (rawCode === undefined || rawCode === null || Number(rawCode) === 0) return;

  const failure = response.failureSummary || response.failure || {};
  const metadata = normalizeGenerationMetadata(failure);
  const stderr = String(response?.result?.stderr || "").trim();
  const stdout = String(response?.result?.stdout || "").trim();
  const detail = cleanCommandFailureText(failure.errorMessage || stderr || stdout || `${label} exited with code ${rawCode}.`);
  const usageText = formatFailureUsage(metadata);
  throw new Error(`${label} failed: ${detail}${usageText ? ` ${usageText}` : ""}`);
}

function cleanCommandFailureText(value) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= 360) return text;
  return `${text.slice(0, 357)}...`;
}

function formatFailureUsage(metadata) {
  if (!metadata) return "";
  const tokens = formatNumber(metadata.totalTokens);
  const cost = formatCost(metadata.estimatedCostUSD);
  if (tokens && cost) return `Tokens used: ${tokens}; estimated cost: ${cost}.`;
  if (tokens) return `Tokens used: ${tokens}.`;
  if (cost) return `Estimated cost: ${cost}.`;
  return "";
}

async function loadFrameReview(sessionId) {
  state.frameReview = { endpointAvailable: null, items: {} };
  if (!sessionId) return;

  try {
    const review = await apiGet(`/api/frame-review?sessionId=${encodeURIComponent(sessionId)}`);
    state.frameReview = {
      endpointAvailable: true,
      items: normalizeFrameReviewItems(review),
    };
  } catch (error) {
    state.frameReview.endpointAvailable = false;
    state.frameReview.items = {};
    if (!/404|not found/i.test(error.message)) {
      logActivity(`Frame review state unavailable: ${error.message}`, "warn");
    }
  }
}

async function saveFrameReview(frameId) {
  const sessionId = requireSessionId();
  if (!sessionId || !frameId) return;

  const review = state.frameReview.items[frameId] || {};
  try {
    const result = await apiPost("/api/frame-review", {
      sessionId,
      frameId,
      reviewStatus: review.reviewStatus || "pending",
      note: review.reviewNote || "",
      assignedSegmentId: review.assignedSegmentId || "",
    });
    state.frameReview.endpointAvailable = true;
    const savedItems = normalizeFrameReviewItems(result);
    state.frameReview.items = {
      ...state.frameReview.items,
      ...savedItems,
      [frameId]: {
        ...review,
        ...(savedItems[frameId] || {}),
      },
    };
    updateFrameReviewStatus();
  } catch (error) {
    state.frameReview.endpointAvailable = false;
    updateFrameReviewStatus("Review endpoint not available; changes are local until backend support lands.");
  }
}

async function addFrameCandidate(event) {
  event.preventDefault();
  const sessionId = requireSessionId();
  if (!sessionId) return;

  const timestamp = els.addFrameTimestamp.value.trim();
  if (!timestamp) {
    openFrameCapturePicker();
    logActivity("Use the video picker or enter a timestamp before adding a manual candidate.", "warn");
    return;
  }

  await submitFrameCandidate(sessionId, timestamp);
}

async function addFrameCandidateFromVideo() {
  const sessionId = requireSessionId();
  if (!sessionId) return;

  const timestamp = formatVideoTimestamp(els.sessionVideo.currentTime || 0);
  els.addFrameTimestamp.value = timestamp;
  await submitFrameCandidate(sessionId, timestamp);
}

async function submitFrameCandidate(sessionId, timestamp) {
  setBusy(true);
  try {
    const result = await apiPost("/api/extract-frame", {
      sessionId,
      timestamp,
      assignedSegmentId: els.addFrameSegment.value,
    });
    logActivity(`Added frame candidate at ${timestamp}.`);
    els.addFrameTimestamp.value = "";
    state.session = mergeSessionResult(state.session, result);
    await loadSession(sessionId);
  } catch (error) {
    logActivity(`Add candidate unavailable: ${error.message}`, "warn");
  } finally {
    setBusy(false);
  }
}

function openFrameCapturePicker() {
  const sessionId = requireSessionId();
  if (!sessionId) return;

  state.frameCapturePicker.open = true;
  state.frameCapturePicker.sessionId = sessionId;
  renderFrameCapturePicker();
  els.sessionVideo.focus({ preventScroll: true });
  els.sessionVideo.scrollIntoView({ block: "nearest", behavior: "smooth" });
  logActivity("Frame capture picker opened. Scrub the recording and use the current time.", "info");
}

function closeFrameCapturePicker() {
  state.frameCapturePicker.open = false;
  els.sessionVideo.pause();
  renderFrameCapturePicker();
}

function resetFrameCapturePicker() {
  state.frameCapturePicker = { open: false, sessionId: "" };
  els.sessionVideo.pause();
  els.sessionVideo.removeAttribute("src");
  els.sessionVideo.load();
  els.sessionVideoTime.textContent = "Current time 0:00.000";
}

function renderFrameCapturePicker() {
  const sessionId = state.selectedSessionId || els.sessionIdInput.value.trim();
  const isOpen = state.frameCapturePicker.open && Boolean(sessionId);
  els.frameCapturePicker.hidden = !isOpen;
  if (!isOpen) return;

  const src = sessionVideoUrl(sessionId);
  if (state.frameCapturePicker.sessionId !== sessionId || els.sessionVideo.getAttribute("src") !== src) {
    state.frameCapturePicker.sessionId = sessionId;
    els.sessionVideo.src = src;
    els.sessionVideo.load();
  }

  els.frameCaptureStatus.textContent = `Source recording for ${sessionId}.`;
  updateSessionVideoTime();
}

function updateSessionVideoTime() {
  const current = Number.isFinite(els.sessionVideo.currentTime) ? els.sessionVideo.currentTime : 0;
  const duration = Number.isFinite(els.sessionVideo.duration) ? els.sessionVideo.duration : null;
  const durationText = duration == null ? "" : ` of ${formatDuration(duration)}`;
  els.sessionVideoTime.textContent = `Current time ${formatVideoTimestamp(current)}${durationText}`;
}

function handleSessionVideoError() {
  if (!state.frameCapturePicker.open) return;
  els.frameCaptureStatus.textContent = "Source recording could not be loaded. Enter a timestamp manually as a fallback.";
  logActivity("Session video unavailable; manual timestamp entry is still available.", "warn");
}

async function parseApiResponse(response) {
  const text = await response.text();
  const data = text ? safeJson(text) : {};
  if (!response.ok) {
    if (response.status === 401) {
      handleAuthRejected();
    }
    const message = data.error || data.message || `${response.status} ${response.statusText}`;
    throw new Error(message);
  }
  return data;
}

function handleAuthRejected() {
  if (state.auth.config?.enabled === false) return;
  state.auth.account = null;
  state.auth.client?.setActiveAccount?.(null);
  state.recordings = [];
  state.transcripts = [];
  state.sessions = [];
  state.session = null;
  state.selectedSessionId = "";
  state.auth.error = "Your sign-in session expired or could not be validated. Sign in again to continue.";
  renderAll();
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

function sortSessions(sessions) {
  return [...sessions].sort((left, right) => {
    const rightTime = Date.parse(right.modifiedUtc || right.createdUtc || "") || 0;
    const leftTime = Date.parse(left.modifiedUtc || left.createdUtc || "") || 0;
    return rightTime - leftTime || getSessionId(left).localeCompare(getSessionId(right));
  });
}

function normalizeFrameReviewItems(payload) {
  if (payload?.frameId || payload?.id) {
    const frameId = payload.frameId || payload.id;
    return { [frameId]: normalizeFrameReviewItem(payload) };
  }
  if (payload?.frame && typeof payload.frame === "object") {
    const frameId = payload.frame.frameId || payload.frame.id || payload.frame.path;
    return frameId ? { [frameId]: normalizeFrameReviewItem(payload.frame) } : {};
  }

  const source =
    payload?.frameReview?.frames
    || payload?.frames
    || payload?.items
    || payload?.review
    || payload?.frameReview
    || payload;
  if (!source || typeof source !== "object") return {};

  if (Array.isArray(source)) {
    return source.reduce((items, item) => {
      const frameId = item.frameId || item.id || item.path;
      if (frameId) items[frameId] = normalizeFrameReviewItem(item);
      return items;
    }, {});
  }

  return Object.entries(source).reduce((items, [frameId, item]) => {
    if (item && typeof item === "object") {
      items[frameId] = normalizeFrameReviewItem({ frameId, ...item });
    }
    return items;
  }, {});
}

function normalizeFrameReviewItem(item) {
  const status = item.reviewStatus || item.status || "pending";
  return {
    frameId: item.frameId || item.id || "",
    reviewStatus: ["approved", "rejected", "pending"].includes(status) ? status : "pending",
    reviewNote: item.reviewNote || item.note || "",
    assignedSegmentId: item.assignedSegmentId || item.segmentId || "",
  };
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
  renderAuth();
  renderPages();
  renderSelectedSessionPill();
  renderSummary();
  renderQaStatus();
  renderTabs();
  renderReadiness();
  renderGlobalUsage();
}

function renderAuth() {
  const enabled = state.auth.config?.enabled !== false;
  const authenticated = isAuthenticated();
  const loading = state.auth.loading;
  document.body.classList.toggle("auth-required", false);
  els.authGate.hidden = !enabled || authenticated || state.activePage !== "usage";
  els.authUserPanel.hidden = !enabled || !authenticated;
  els.loginButton.disabled = loading || state.busy;
  els.logoutButton.disabled = loading || state.busy;

  if (loading) {
    els.authStatusText.textContent = "Checking Microsoft sign-in status...";
  } else if (state.auth.error) {
    els.authStatusText.textContent = state.auth.error;
  } else {
    els.authStatusText.textContent = "Local processing is available on this workstation. Sign in is required for AI guide creation and AI Spend reporting.";
  }

  const account = state.auth.account;
  els.authUserName.textContent = account?.name || account?.username || "Signed in";
}

function setActivePage(page) {
  state.activePage = page === "usage" ? "usage" : "workspace";
  renderAuth();
  renderPages();
  if (state.activePage === "usage" && isAuthenticated() && !state.usage.loading) {
    loadUsageSummary();
  }
}

function renderPages() {
  const usageActive = state.activePage === "usage";
  els.workspacePage.hidden = usageActive;
  els.usagePage.hidden = !usageActive || !isAuthenticated();
  document.querySelectorAll("[data-page]").forEach((button) => {
    button.classList.toggle("active", button.dataset.page === state.activePage);
  });
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

function renderTranscripts() {
  const selected = els.transcriptSelect.value;
  els.transcriptSelect.innerHTML = "";
  els.transcriptSelect.append(new Option("No transcript selected", ""));
  state.transcripts.forEach((transcript) => {
    const label = getTranscriptLabel(transcript);
    const value = getTranscriptValue(transcript);
    els.transcriptSelect.append(new Option(label, value));
  });
  if (selected && Array.from(els.transcriptSelect.options).some((option) => option.value === selected)) {
    els.transcriptSelect.value = selected;
  }
}

function renderSessions() {
  els.sessionList.innerHTML = "";
  const sessions = filteredSessionsForSelectedRecording();
  els.sessionCount.textContent = String(sessions.length);
  if (!els.recordingSelect.value) {
    els.sessionList.innerHTML = `<li class="muted">Select a recording to view its sessions.</li>`;
    return;
  }
  if (sessions.length === 0) {
    els.sessionList.innerHTML = `<li class="muted">No sessions found for the selected recording.</li>`;
    return;
  }

  sessions.forEach((session) => {
    const sessionId = getSessionId(session);
    const item = document.createElement("li");
    item.className = sessionId === state.selectedSessionId ? "selected" : "";
    item.innerHTML = `
      <button class="session-select" type="button" data-session-select="${escapeAttribute(sessionId)}">
        <strong>${escapeHtml(sessionId || "unknown-session")}</strong>
        <span>${escapeHtml(sessionSubtitle(session))}</span>
      </button>
      <button class="session-delete" type="button" data-session-delete="${escapeAttribute(sessionId)}" title="Delete this processed session and generated artifacts">Delete</button>
    `;
    els.sessionList.append(item);
  });
}

function filteredSessionsForSelectedRecording() {
  const selectedRecording = els.recordingSelect.value;
  if (!selectedRecording) return [];
  const selectedName = basename(selectedRecording).toLowerCase();
  return state.sessions.filter((session) => {
    const source = session.sourceFile || session.sourceName || session.recording?.sourceFile || session.recording?.sourceName || "";
    return basename(source).toLowerCase() === selectedName;
  });
}

function selectRecording(recordingValue) {
  const value = getRecordingValue(recordingValue);
  if (Array.from(els.recordingSelect.options).some((option) => option.value === value)) {
    els.recordingSelect.value = value;
    handleRecordingSelectionChange();
  }
}

function handleRecordingSelectionChange() {
  syncSessionIdPlaceholder();
  if (state.selectedSessionId && !filteredSessionsForSelectedRecording().some((session) => getSessionId(session) === state.selectedSessionId)) {
    state.selectedSessionId = "";
    state.session = null;
    state.generationMetadata = null;
    state.frameReview = { endpointAvailable: null, items: {} };
    resetFrameCapturePicker();
    closeFrameInspect();
    els.sessionIdInput.value = "";
  }
  renderSessions();
  renderAll();
}

function renderSelectedSessionPill() {
  if (state.selectedSessionId) {
    els.selectedSessionPill.textContent = getSelectedSessionLabel();
    els.selectedSessionPill.className = "status-pill good";
  } else {
    els.selectedSessionPill.textContent = "No session selected";
    els.selectedSessionPill.className = "status-pill neutral";
  }
}

function getSelectedSessionLabel() {
  const session = state.session || filteredSessionsForSelectedRecording().find((item) => getSessionId(item) === state.selectedSessionId);
  if (!session) {
    return state.selectedSessionId || "Session selected";
  }
  return session.title || session.sessionName || session.name || session.sessionId || session.id || state.selectedSessionId || "Session selected";
}

function renderSummary() {
  const trace = getTrace();
  const segments = getSegments();
  const images = getFrameCandidates();
  const reviewCount = segments.filter((segment) => segment.confidence?.needsHumanReview).length;

  els.durationMetric.textContent = formatDuration(trace?.recording?.durationSeconds);
  els.segmentMetric.textContent = segments.length ? String(segments.length) : "--";
  els.reviewMetric.textContent = segments.length ? String(reviewCount) : "--";
  els.imageMetric.textContent = images.length ? String(images.length) : "--";
}

function renderQaStatus() {
  const status = state.session?.qa?.status || "";
  if (status === "publish-ready") {
    els.qaStatusTitle.textContent = "QA Passed";
    els.qaStatusText.textContent = "Local checks passed. Download is ready for reviewer handoff.";
    return;
  }
  if (status === "review-only") {
    els.qaStatusTitle.textContent = "QA Needs Review";
    els.qaStatusText.textContent = "The guide built successfully, but reviewer comments or warnings need attention.";
    return;
  }
  if (status === "failed") {
    els.qaStatusTitle.textContent = "QA Failed";
    els.qaStatusText.textContent = "Local checks found blockers. Review Latest Activity before sharing.";
    return;
  }
  if (getArtifacts().some((artifact) => /user_guide.*\.docx$/i.test(artifact.name || artifact.path || ""))) {
    els.qaStatusTitle.textContent = "QA Not Run";
    els.qaStatusText.textContent = "Create Guide runs QA automatically. Re-run QA after manual guide or screenshot changes.";
    return;
  }
  els.qaStatusTitle.textContent = "QA Status";
  els.qaStatusText.textContent = "Create Guide will run local QA after the DOCX is built.";
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
  renderUsage();
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
  const frames = getFrameCandidates();
  renderAddFrameSegments();
  renderFrameCapturePicker();
  renderFrameInspect();
  updateFrameReviewStatus();
  if (frames.length === 0) {
    els.frameGrid.className = "frame-grid empty-state";
    els.frameGrid.textContent = "Candidate frames will appear after processing.";
    return;
  }

  els.frameGrid.className = "frame-grid";
  els.frameGrid.innerHTML = "";
  frames.slice(0, 48).forEach((frame) => {
    const review = getFrameReview(frame);
    const frameId = getFrameId(frame);
    const card = document.createElement("article");
    card.className = `frame-card ${review.reviewStatus}`;
    card.dataset.frameId = frameId;
    const path = frame.path || "";
    const confidence = frame.confidence ?? frame.score;
    card.innerHTML = `
      <button class="frame-preview" type="button" data-frame-inspect="${escapeAttribute(frameId)}" aria-label="Inspect candidate frame ${escapeAttribute(frame.frameId || frame.id || frameId || "")}">
        ${path ? `<img src="${escapeAttribute(frameUrl(path))}" alt="Candidate frame ${escapeAttribute(frame.frameId || frame.id || "")}">` : `<span>No image</span>`}
      </button>
      <header class="frame-card-header">
        <strong>${escapeHtml(frame.frameId || frame.id || frameId || "frame")}</strong>
        <small>${escapeHtml(review.reviewStatus)} · ${formatPercent(confidence)}</small>
      </header>
      <span>${escapeHtml(frame.segmentId || "")} at ${escapeHtml(frame.timestamp || "")}</span>
      <div class="frame-actions" aria-label="Review ${escapeAttribute(frameId)}">
        <button class="secondary ${review.reviewStatus === "approved" ? "active" : ""}" type="button" data-frame-action="approved">Approve</button>
        <button class="secondary ${review.reviewStatus === "rejected" ? "active danger" : "danger"}" type="button" data-frame-action="rejected">Reject</button>
        <button class="secondary ${review.reviewStatus === "pending" ? "active" : ""}" type="button" data-frame-action="pending">Pending</button>
      </div>
      <label class="frame-field">
        <span>Assigned segment</span>
        ${renderSegmentSelect(review.assignedSegmentId || frame.segmentId || "", "frame-assign")}
      </label>
      <label class="frame-field">
        <span>Review note</span>
        <textarea class="frame-note" rows="2" placeholder="Concern, crop issue, or reviewer guidance">${escapeHtml(review.reviewNote || "")}</textarea>
      </label>
    `;
    els.frameGrid.append(card);
  });
}

function handleFrameAction(event) {
  const inspectButton = event.target.closest("[data-frame-inspect]");
  if (inspectButton) {
    openFrameInspect(inspectButton.dataset.frameInspect);
    return;
  }

  const button = event.target.closest("[data-frame-action]");
  if (!button) {
    const card = event.target.closest(".frame-card");
    if (card && !isInteractiveFrameTarget(event.target)) {
      openFrameInspect(card.dataset.frameId);
    }
    return;
  }
  const card = button.closest(".frame-card");
  const frameId = card?.dataset.frameId;
  if (!frameId) return;

  updateLocalFrameReview(frameId, { reviewStatus: button.dataset.frameAction });
  renderFrames();
  saveFrameReview(frameId);
}

function isInteractiveFrameTarget(target) {
  return Boolean(target.closest("button, a, input, select, textarea, label"));
}

function openFrameInspect(frameId) {
  const frame = getFrameCandidates().find((candidate) => getFrameId(candidate) === frameId);
  if (!frame) return;
  state.frameInspect = { open: true, frameId };
  renderFrameInspect();
}

function closeFrameInspect() {
  state.frameInspect = { open: false, frameId: "" };
  renderFrameInspect();
}

function handleFrameInspectBackdrop(event) {
  if (event.target === els.frameInspectModal) {
    closeFrameInspect();
  }
}

function handleGlobalKeydown(event) {
  if (event.key === "Escape" && !els.helpDrawerShell.hidden) {
    closeHelpDrawer();
    return;
  }
  if (event.key === "Escape" && state.frameInspect.open) {
    closeFrameInspect();
  }
}

function openHelpDrawer() {
  els.helpDrawerShell.hidden = false;
  document.body.classList.add("modal-open");
  renderHelpDrawer();
  window.requestAnimationFrame(() => els.helpSearch.focus({ preventScroll: true }));
}

function closeHelpDrawer() {
  els.helpDrawerShell.hidden = true;
  updateBodyModalState();
  els.helpButton.focus({ preventScroll: true });
}

function handleHelpChipClick(event) {
  const button = event.target.closest("[data-help-query]");
  if (!button) return;
  els.helpSearch.value = button.dataset.helpQuery || "";
  renderHelpDrawer();
}

function handleHelpResultClick(event) {
  const button = event.target.closest("[data-help-topic]");
  if (!button) return;
  const topic = HELP_TOPICS.find((item) => item.id === button.dataset.helpTopic);
  if (!topic) return;
  els.helpSearch.value = topic.title;
  renderHelpDrawer();
}

function handleHelpActionClick(event) {
  const button = event.target.closest("[data-help-action]");
  if (!button) return;
  const topic = HELP_TOPICS.find((item) => item.id === button.dataset.helpAction);
  if (!topic?.action) return;

  if (topic.action.type === "page") {
    setActivePage(topic.action.target);
    closeHelpDrawer();
    return;
  }
  if (topic.action.type === "tab") {
    state.activeTab = topic.action.target;
    renderTabs();
    closeHelpDrawer();
    return;
  }
  if (topic.action.type === "download") {
    const link = document.createElement("a");
    link.href = topic.action.target;
    link.download = "KCXDocumentor User Guide.docx";
    document.body.append(link);
    link.click();
    link.remove();
  }
}

function renderHelpDrawer() {
  const query = els.helpSearch.value.trim().toLowerCase();
  const matches = query
    ? HELP_TOPICS
        .map((topic) => ({ topic, score: helpTopicScore(topic, query) }))
        .filter((item) => item.score > 0)
        .sort((left, right) => right.score - left.score)
        .map((item) => item.topic)
    : HELP_TOPICS.slice(0, 5);
  const activeTopic = matches[0] || HELP_TOPICS[0];

  els.helpChips.innerHTML = HELP_TOPICS.slice(0, 6)
    .map((topic) => `<button class="help-chip" type="button" data-help-query="${escapeAttribute(topic.chips[0] || topic.title)}">${escapeHtml(topic.chips[0] || topic.title)}</button>`)
    .join("");

  els.helpResults.innerHTML = matches.length
    ? matches.map((topic) => `
        <button class="help-result ${topic.id === activeTopic.id ? "help-result--active" : ""}" type="button" data-help-topic="${escapeAttribute(topic.id)}">
          ${escapeHtml(topic.title)}
        </button>
      `).join("")
    : `<div class="status-pill warn">No help topics matched that search.</div>`;

  els.helpResponse.innerHTML = activeTopic
    ? `
      <div class="help-answer">
        <h3>${escapeHtml(activeTopic.title)}</h3>
        ${activeTopic.body.map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`).join("")}
      </div>
      ${activeTopic.action ? `<button class="secondary help-action" type="button" data-help-action="${escapeAttribute(activeTopic.id)}">${escapeHtml(activeTopic.action.label)}</button>` : ""}
    `
    : `<p class="muted">Try another search or contact KCX support.</p>`;
}

function helpSearchText(topic) {
  return [
    topic.title,
    ...(topic.chips || []),
    ...(topic.keywords || []),
    ...(topic.body || []),
  ].join(" ").toLowerCase();
}

function helpTopicScore(topic, query) {
  const title = String(topic.title || "").toLowerCase();
  const chips = (topic.chips || []).join(" ").toLowerCase();
  const keywords = (topic.keywords || []).join(" ").toLowerCase();
  const body = (topic.body || []).join(" ").toLowerCase();
  let score = 0;
  if (title.includes(query)) score += 12;
  if (chips.includes(query)) score += 10;
  if (keywords.includes(query)) score += 8;
  if (body.includes(query)) score += 2;
  if (helpSearchText(topic).includes(query)) score += 1;
  return score;
}

function renderFrameInspect() {
  const frame = getFrameCandidates().find((candidate) => getFrameId(candidate) === state.frameInspect.frameId);
  const isOpen = state.frameInspect.open && Boolean(frame);
  els.frameInspectModal.hidden = !isOpen;
  updateBodyModalState();
  if (!isOpen || !frame) {
    els.frameInspectImage.removeAttribute("src");
    els.frameInspectImage.alt = "";
    return;
  }

  const review = getFrameReview(frame);
  const frameId = getFrameId(frame);
  const path = frame.path || "";
  const confidence = frame.confidence ?? frame.score;
  els.frameInspectTitle.textContent = frame.frameId || frame.id || frameId || "Frame Preview";
  els.frameInspectMeta.textContent = `${review.reviewStatus || "pending"} · ${frame.timestamp || "unknown time"} · ${formatPercent(confidence)}`;
  if (path) {
    els.frameInspectImage.src = frameUrl(path);
    els.frameInspectImage.alt = `Candidate frame ${frame.frameId || frame.id || frameId}`;
  } else {
    els.frameInspectImage.removeAttribute("src");
    els.frameInspectImage.alt = "No frame image available.";
  }
  els.frameInspectDetails.innerHTML = `
    <dl>
      <div><dt>Frame</dt><dd>${escapeHtml(frameId)}</dd></div>
      <div><dt>Timestamp</dt><dd>${escapeHtml(frame.timestamp || "--")}</dd></div>
      <div><dt>Status</dt><dd>${escapeHtml(review.reviewStatus || "pending")}</dd></div>
      <div><dt>Assigned Segment</dt><dd>${escapeHtml(review.assignedSegmentId || frame.segmentId || "No assignment")}</dd></div>
      <div><dt>Selection Reason</dt><dd>${escapeHtml(frame.reason || frame.selectionReason || "--")}</dd></div>
      <div><dt>Review Note</dt><dd>${escapeHtml(review.reviewNote || "No reviewer note.")}</dd></div>
    </dl>
  `;
  els.closeFrameInspect.focus({ preventScroll: true });
}

function updateBodyModalState() {
  const helpOpen = els.helpDrawerShell && !els.helpDrawerShell.hidden;
  const frameOpen = state.frameInspect.open && !els.frameInspectModal.hidden;
  document.body.classList.toggle("modal-open", Boolean(helpOpen || frameOpen));
}

function handleFrameFieldChange(event) {
  if (!event.target.classList.contains("frame-assign")) return;
  const frameId = event.target.closest(".frame-card")?.dataset.frameId;
  if (!frameId) return;
  updateLocalFrameReview(frameId, { assignedSegmentId: event.target.value });
  saveFrameReview(frameId);
}

function handleFrameNoteInput(event) {
  if (!event.target.classList.contains("frame-note")) return;
  const frameId = event.target.closest(".frame-card")?.dataset.frameId;
  if (!frameId) return;
  updateLocalFrameReview(frameId, { reviewNote: event.target.value });
  window.clearTimeout(event.target.saveTimer);
  event.target.saveTimer = window.setTimeout(() => saveFrameReview(frameId), 600);
}

function updateLocalFrameReview(frameId, patch) {
  state.frameReview.items[frameId] = {
    frameId,
    reviewStatus: "pending",
    reviewNote: "",
    assignedSegmentId: "",
    ...(state.frameReview.items[frameId] || {}),
    ...patch,
  };
  if (state.frameInspect.open && state.frameInspect.frameId === frameId) {
    renderFrameInspect();
  }
}

function getFrameCandidates() {
  const byId = new Map();
  getSegments().forEach((segment) => {
    (segment.candidateImages || []).forEach((image) => {
      const frame = { ...image, segmentId: image.assignedSegmentId || segment.id };
      byId.set(getFrameId(frame), frame);
    });
  });
  (state.session?.frameReview?.frames || []).forEach((image) => {
    const frame = { ...image, segmentId: image.assignedSegmentId || image.segmentId || "" };
    byId.set(getFrameId(frame), { ...(byId.get(getFrameId(frame)) || {}), ...frame });
  });
  return Array.from(byId.values());
}

function getFrameId(frame) {
  return frame.frameId || frame.id || frame.path || `${frame.segmentId || "frame"}-${frame.timestamp || "unknown"}`;
}

function getFrameReview(frame) {
  const frameId = getFrameId(frame);
  return {
    frameId,
    reviewStatus: frame.reviewStatus || "pending",
    reviewNote: frame.reviewNote || "",
    assignedSegmentId: frame.assignedSegmentId || frame.segmentId || "",
    ...(state.frameReview.items[frameId] || {}),
  };
}

function renderAddFrameSegments() {
  const selected = els.addFrameSegment.value;
  els.addFrameSegment.innerHTML = `<option value="">No segment</option>`;
  getSegments().forEach((segment, index) => {
    const label = `${segment.id || `Segment ${index + 1}`} ${segment.start ? `(${segment.start})` : ""}`;
    els.addFrameSegment.append(new Option(label, segment.id || `segment-${index + 1}`));
  });
  if (selected && Array.from(els.addFrameSegment.options).some((option) => option.value === selected)) {
    els.addFrameSegment.value = selected;
  }
}

function renderSegmentSelect(selectedValue, className) {
  const options = [`<option value="">No assignment</option>`]
    .concat(getSegments().map((segment, index) => {
      const value = segment.id || `segment-${index + 1}`;
      const label = `${value}${segment.start ? ` (${segment.start})` : ""}`;
      return `<option value="${escapeAttribute(value)}"${value === selectedValue ? " selected" : ""}>${escapeHtml(label)}</option>`;
    }))
    .join("");
  return `<select class="${escapeAttribute(className)}">${options}</select>`;
}

function updateFrameReviewStatus(message = "") {
  const frames = getFrameCandidates();
  if (frames.length === 0) {
    els.frameReviewStatus.textContent = "Load a processed session to curate screenshots.";
    return;
  }

  const reviewed = frames.map(getFrameReview);
  const approved = reviewed.filter((frame) => frame.reviewStatus === "approved").length;
  const rejected = reviewed.filter((frame) => frame.reviewStatus === "rejected").length;
  const pending = reviewed.length - approved - rejected;
  const persistence = state.frameReview.endpointAvailable === false ? " Review API unavailable; local changes are temporary." : "";
  els.frameReviewStatus.textContent = message || `${approved} approved, ${rejected} rejected, ${pending} pending.${persistence}`;
}

function renderArtifacts() {
  const artifacts = getArtifacts();
  renderGenerationMetadata();
  if (artifacts.length === 0) {
    els.artifactList.className = "artifact-list empty-state";
    els.artifactList.textContent = "Generated draft, DOCX, and QA artifacts will appear here.";
    return;
  }

  els.artifactList.className = "artifact-list";
  els.artifactList.innerHTML = "";
  artifacts.forEach((artifact) => {
    const item = document.createElement("article");
    const downloadUrl = artifactDownloadUrl(artifact);
    const downloadName = downloadNameForArtifact(artifact);
    const downloadLink = downloadUrl
      ? `<a class="artifact-download" href="${escapeAttribute(downloadUrl)}" download="${escapeAttribute(downloadName)}">Download</a>`
      : "";
    item.innerHTML = `
      <div class="artifact-row">
        <strong>${escapeHtml(artifact.label)}</strong>
        ${downloadLink}
      </div>
      <span>${escapeHtml(artifact.path || artifact.status || "")}</span>
    `;
    els.artifactList.append(item);
  });
}

function renderGenerationMetadata() {
  const metadata = state.generationMetadata;
  if (!metadata) {
    els.generationMetadata.className = "generation-metadata empty-state";
    els.generationMetadata.textContent = "Generation usage will appear after the Anthropic draft is available.";
    return;
  }

  els.generationMetadata.className = "generation-metadata";
  els.generationMetadata.innerHTML = `
    <div>
      <span class="metric-label">Model</span>
      <strong>${escapeHtml(metadata.model || "Unknown")}</strong>
    </div>
    <div>
      <span class="metric-label">Generated</span>
      <strong>${escapeHtml(formatDateTime(metadata.generatedAt) || metadata.generatedAt || "--")}</strong>
    </div>
    <div>
      <span class="metric-label">Tokens</span>
      <strong>${escapeHtml(formatNumber(metadata.totalTokens) || "--")}</strong>
      <small>${escapeHtml(formatNumber(metadata.inputTokens) || "--")} in / ${escapeHtml(formatNumber(metadata.outputTokens) || "--")} out</small>
    </div>
    <div>
      <span class="metric-label">Estimated Cost</span>
      <strong>${escapeHtml(formatCost(metadata.estimatedCostUSD) || "--")}</strong>
    </div>
  `;
}

function renderUsage() {
  if (!els.usageBreakdown) return;
  renderGlobalUsage();

  document.querySelectorAll("[data-usage-range]").forEach((button) => {
    button.classList.toggle("active", button.dataset.usageRange === state.usage.range);
    button.disabled = state.usage.loading;
  });
  if (els.usageSort) {
    els.usageSort.value = state.usage.sort || "date-desc";
    els.usageSort.disabled = state.usage.loading;
  }

  const summary = state.usage.summary;
  const totals = summary?.totals || {};
  els.usageDocumentMetric.textContent = formatNumber(totals.documents) || "--";
  els.usageTokenMetric.textContent = formatNumber(totals.totalTokens) || "--";
  els.usageInOutMetric.textContent = `${formatNumber(totals.inputTokens) || "--"} / ${formatNumber(totals.outputTokens) || "--"}`;
  els.usagePageMetric.textContent = formatNumber(totals.pageCount) || "--";
  els.usageCostMetric.textContent = formatCost(totals.estimatedCostUSD) || "--";
  els.usageCostPerPageMetric.textContent = formatCost(totals.costPerPageUSD) || "--";

  if (state.usage.loading) {
    els.usageStatus.textContent = `Loading ${state.usage.range} usage...`;
    els.usageBreakdown.className = "usage-breakdown empty-state";
    els.usageBreakdown.textContent = "Loading generation usage totals.";
    return;
  }

  if (state.usage.error) {
    els.usageStatus.textContent = "Usage API unavailable.";
    els.usageBreakdown.className = "usage-breakdown empty-state";
    els.usageBreakdown.textContent = "Usage totals will appear after /api/usage-summary is available.";
    return;
  }

  if (!summary) {
    els.usageStatus.textContent = "Token usage totals load from the local API.";
    els.usageBreakdown.className = "usage-breakdown empty-state";
    els.usageBreakdown.textContent = "Select a range to load usage totals.";
    return;
  }

  const failedText = Number(totals.failedAttempts)
    ? ` Includes ${formatNumber(totals.failedAttempts)} failed AI attempt${Number(totals.failedAttempts) === 1 ? "" : "s"}.`
    : "";
  els.usageStatus.textContent = `${rangeLabel(summary.range)} totals generated ${formatDateTime(summary.generatedAt) || "now"}.${failedText}`;
  const rows = usageDocumentRows(summary);
  const rowTotals = rows.reduce(
    (acc, row) => {
      acc.totalTokens += Number(row.totalTokens || 0);
      acc.pageCount += Number(row.pageCount || 0);
      acc.estimatedCostUSD += Number(row.estimatedCostUSD || 0);
      return acc;
    },
    { totalTokens: 0, pageCount: 0, estimatedCostUSD: 0 }
  );
  rowTotals.costPerPageUSD = costPerPage(rowTotals.estimatedCostUSD, rowTotals.pageCount);
  if (rows.length === 0) {
    els.usageBreakdown.className = "usage-breakdown empty-state";
    els.usageBreakdown.textContent = "No generated documents found for this range.";
    return;
  }

  els.usageBreakdown.className = "usage-breakdown";
  els.usageBreakdown.innerHTML = `
    <table class="usage-table" aria-label="Individual generated document usage">
      <thead>
        <tr>
          <th scope="col">Document</th>
          <th scope="col">User</th>
          <th scope="col">Generated</th>
          <th scope="col">Model</th>
          <th scope="col">Status</th>
          <th scope="col" class="numeric">Tokens</th>
          <th scope="col" class="numeric">Pages</th>
          <th scope="col" class="numeric">Cost</th>
          <th scope="col" class="numeric">Cost / Page</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map((row) => `
          <tr>
            <td>
              <strong>${escapeHtml(row.documentLabel)}</strong>
              <span>${escapeHtml(row.sessionLabel)}</span>
            </td>
            <td>
              <strong>${escapeHtml(row.userLabel)}</strong>
              <span>${escapeHtml(row.userDetail)}</span>
            </td>
            <td>${escapeHtml(row.generatedAtLabel)}</td>
            <td>${escapeHtml(row.modelLabel)}</td>
            <td>${escapeHtml(row.statusLabel)}</td>
            <td class="numeric">${escapeHtml(formatNumber(row.totalTokens) || "0")}</td>
            <td class="numeric">${escapeHtml(formatPageCount(row.pageCount))}</td>
            <td class="numeric">${escapeHtml(formatCost(row.estimatedCostUSD) || "$0.0000")}</td>
            <td class="numeric">${escapeHtml(formatCostPerPage(row.costPerPageUSD, row.pageCount))}</td>
          </tr>
        `).join("")}
      </tbody>
      <tfoot>
        <tr>
          <th scope="row">Tally</th>
          <td colspan="4">${escapeHtml(formatNumber(rows.length) || "0")} documents</td>
          <td class="numeric">${escapeHtml(formatNumber(rowTotals.totalTokens) || "0")}</td>
          <td class="numeric">${escapeHtml(formatNumber(rowTotals.pageCount) || "--")}</td>
          <td class="numeric">${escapeHtml(formatCost(rowTotals.estimatedCostUSD) || "$0.0000")}</td>
          <td class="numeric">${escapeHtml(formatCost(rowTotals.costPerPageUSD) || "--")}</td>
        </tr>
      </tfoot>
    </table>
  `;
}

function usageDocumentRows(summary) {
  const buckets = Array.isArray(summary?.buckets) ? summary.buckets : [];
  const rows = [];
  buckets.forEach((bucket) => {
    const documents = Array.isArray(bucket?.documents) ? bucket.documents : [];
    documents.forEach((document) => {
      if (String(document?.status || "succeeded").toLowerCase() === "failed") {
        return;
      }
      const usage = firstObject(document?.usage);
      const generatedBy = firstObject(document?.generatedBy, document?.user);
      const pageCount = numberValue(document?.pageCount ?? document?.page_count ?? usage?.pageCount ?? usage?.page_count ?? usage?.pages) || 0;
      const estimatedCostUSD = numberValue(usage?.estimatedCostUSD ?? usage?.estimated_cost_usd ?? usage?.costUSD ?? usage?.cost_usd) || 0;
      const userName = String(generatedBy?.name || generatedBy?.username || "").trim();
      const userDetail = String(generatedBy?.username || generatedBy?.oid || "").trim();
      rows.push({
        generatedAtRaw: document?.generatedAt || "",
        generatedAtLabel: formatDateTime(document?.generatedAt) || "--",
        documentLabel: document?.title || "Untitled document",
        sessionLabel: document?.sessionId || "No session id",
        userLabel: userName || "Unknown user",
        userDetail: userDetail && userDetail !== userName ? userDetail : "",
        modelLabel: modelName(document?.model) || "--",
        statusLabel: String(document?.status || "succeeded"),
        totalTokens: numberValue(usage?.totalTokens ?? usage?.total_tokens) || 0,
        pageCount,
        estimatedCostUSD,
        costPerPageUSD: costPerPage(estimatedCostUSD, pageCount),
      });
    });
  });
  rows.sort(compareUsageRows);
  return rows;
}

function compareUsageRows(a, b) {
  const sort = state.usage.sort || "date-desc";
  if (sort === "user-asc" || sort === "user-desc") {
    const userCompare = String(a.userLabel || "").localeCompare(String(b.userLabel || ""), undefined, { sensitivity: "base" });
    if (userCompare !== 0) {
      return sort === "user-asc" ? userCompare : -userCompare;
    }
  }
  return String(b.generatedAtRaw || "").localeCompare(String(a.generatedAtRaw || ""));
}

function renderGlobalUsage() {
  const totals = state.usage.currentMonthSummary?.totals || {};
  const documents = formatNumber(totals.documents);
  const cost = formatCost(totals.estimatedCostUSD);
  if (state.usage.currentMonthLoading && !state.usage.currentMonthSummary) {
    els.globalUsageMetric.textContent = "Loading";
    return;
  }
  if (documents || cost) {
    const failed = Number(totals.failedAttempts) ? ` · ${formatNumber(totals.failedAttempts)} failed` : "";
    els.globalUsageMetric.textContent = `${documents || "0"} docs · ${cost || "$0.0000"}${failed}`;
    return;
  }
  els.globalUsageMetric.textContent = "No spend";
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
  const frames = getFrameCandidates();
  const imageCount = frames.length;
  const reviewedFrames = frames.map(getFrameReview);
  const approvedImages = reviewedFrames.filter((image) => image.reviewStatus === "approved").length;
  const rejectedImages = reviewedFrames.filter((image) => image.reviewStatus === "rejected").length;
  const pendingImages = Math.max(0, imageCount - approvedImages - rejectedImages);
  const createdImages = frames.filter((image) => image.created).length;
  const lowConfidence = segments.filter((segment) => Number(segment.confidence?.overall || 0) < 0.75).length;
  const generation = state.generationMetadata;

  const checks = [
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
      label: "Screenshot review",
      state: imageCount === 0 ? "bad" : pendingImages ? "warn" : approvedImages ? "good" : "warn",
      detail: `${approvedImages} approved, ${rejectedImages} rejected, ${pendingImages} pending from ${imageCount} candidates.`,
    },
    {
      label: "Extracted images",
      state: imageCount === 0 ? "bad" : createdImages === 0 ? "warn" : "good",
      detail: `${createdImages} extracted image files available for review.`,
    },
  ];
  if (generation) {
    checks.push({
      label: "Generation usage",
      state: "good",
      detail: `${formatNumber(generation.totalTokens) || "--"} tokens, ${formatCost(generation.estimatedCostUSD) || "cost unavailable"}, ${generation.model || "model unavailable"}.`,
    });
  }
  return checks;
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

async function hydrateGenerationMetadata() {
  if (state.generationMetadata?.title) return;
  const draftArtifact = getArtifacts().find((artifact) => /guide_draft.*\.json$/i.test(artifact.name || artifact.path || ""));
  const sessionId = state.selectedSessionId || getSessionId(state.session);
  if (!draftArtifact || !sessionId) return;

  const url = artifactDownloadUrl(draftArtifact);
  if (!url) return;
  try {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) return;
    const draft = await response.json();
    state.generationMetadata = normalizeGenerationMetadata(draft) || state.generationMetadata;
  } catch {
    state.generationMetadata = null;
  }
}

function normalizeGenerationMetadata(draft) {
  const guideDraft = draft?.guideDraft && typeof draft.guideDraft === "object" ? draft.guideDraft : {};
  const usage = firstObject(draft?.usage, guideDraft.usage);
  const generation = firstObject(draft?.generation, guideDraft.generation);
  const model = modelName(draft?.model) || modelName(generation?.model) || modelName(guideDraft?.model);
  const inputTokens = numberValue(
    usage?.inputTokens
      ?? usage?.input_tokens
      ?? usage?.cacheReadInputTokens
      ?? usage?.cache_read_input_tokens
      ?? draft?.inputTokens
      ?? draft?.input_tokens
  );
  const outputTokens = numberValue(usage?.outputTokens ?? usage?.output_tokens ?? draft?.outputTokens ?? draft?.output_tokens);
  const totalTokens = numberValue(usage?.totalTokens ?? usage?.total_tokens ?? draft?.totalTokens ?? draft?.total_tokens) ?? (
    Number.isFinite(inputTokens) || Number.isFinite(outputTokens)
      ? Number(inputTokens || 0) + Number(outputTokens || 0)
      : null
  );
  const estimatedCostUSD = numberValue(
    usage?.estimatedCostUSD
      ?? usage?.estimated_cost_usd
      ?? usage?.costUSD
      ?? usage?.cost_usd
      ?? generation?.estimatedCostUSD
      ?? generation?.estimated_cost_usd
      ?? generation?.costUSD
      ?? generation?.cost_usd
      ?? draft?.estimatedCostUSD
      ?? draft?.estimated_cost_usd
      ?? draft?.costUSD
      ?? draft?.cost_usd
  );
  const generatedAt = draft?.generatedAt || draft?.generated_at || draft?.createdUtc || draft?.createdAt
    || generation?.generatedAt || generation?.generated_at || generation?.createdUtc || generation?.createdAt
    || guideDraft?.generatedAt || guideDraft?.generated_at || "";
  const title = draft?.title || draft?.document?.title || generation?.title || guideDraft?.title || guideDraft?.document?.title || "";

  if (!title && !model && !generatedAt && !Number.isFinite(totalTokens) && !Number.isFinite(estimatedCostUSD)) {
    return null;
  }
  return { title, model, generatedAt, inputTokens, outputTokens, totalTokens, estimatedCostUSD };
}

function normalizeUsageSummary(payload, fallbackRange) {
  const totals = normalizeUsageTotals(payload?.totals || {});
  const bucketSource = Array.isArray(payload?.buckets) ? payload.buckets : Array.isArray(payload?.days) ? payload.days : [];
  const buckets = bucketSource.map((bucket) => ({
    ...bucket,
    totals: normalizeUsageTotals(bucket.totals || bucket),
  }));
  return {
    range: payload?.range || fallbackRange,
    generatedAt: payload?.generatedAt || payload?.generated_at || payload?.createdUtc || payload?.createdAt || "",
    totals,
    buckets,
    days: buckets,
  };
}

function normalizeUsageTotals(totals) {
  const inputTokens = numberValue(totals?.inputTokens ?? totals?.input_tokens);
  const outputTokens = numberValue(totals?.outputTokens ?? totals?.output_tokens);
  const totalTokens = numberValue(totals?.totalTokens ?? totals?.total_tokens) ?? (
    Number.isFinite(inputTokens) || Number.isFinite(outputTokens)
      ? Number(inputTokens || 0) + Number(outputTokens || 0)
      : null
  );
  const pageCount = numberValue(totals?.pageCount ?? totals?.page_count ?? totals?.pages);
  const estimatedCostUSD = numberValue(totals?.estimatedCostUSD ?? totals?.estimated_cost_usd ?? totals?.costUSD ?? totals?.cost_usd);
  return {
    documents: numberValue(totals?.documents ?? totals?.documentCount ?? totals?.generatedDocuments ?? totals?.count),
    attempts: numberValue(totals?.attempts ?? totals?.attemptCount),
    failedAttempts: numberValue(totals?.failedAttempts ?? totals?.failed_attempts ?? totals?.failedAttemptCount),
    inputTokens,
    outputTokens,
    totalTokens,
    pageCount,
    estimatedCostUSD,
    costPerPageUSD: numberValue(totals?.costPerPageUSD ?? totals?.cost_per_page_usd) ?? costPerPage(estimatedCostUSD, pageCount),
  };
}

function costPerPage(cost, pageCount) {
  const pages = Number(pageCount || 0);
  if (!Number.isFinite(pages) || pages <= 0) {
    return 0;
  }
  return Number(cost || 0) / pages;
}

function formatUsageBucketAttempts(totals) {
  const documents = Number(totals.documents || 0);
  const attempts = Number(totals.attempts || documents || 0);
  const failed = Number(totals.failedAttempts || 0);
  const parts = [
    `${formatNumber(documents) || "0"} document${documents === 1 ? "" : "s"}`,
    `${formatNumber(attempts) || "0"} AI attempt${attempts === 1 ? "" : "s"}`,
  ];
  if (failed) {
    parts.push(`${formatNumber(failed)} failed`);
  }
  return parts.join(" · ");
}

function firstObject(...values) {
  return values.find((value) => value && typeof value === "object" && !Array.isArray(value)) || {};
}

function modelName(value) {
  if (!value) return "";
  if (typeof value === "string") return value;
  if (typeof value === "object") return value.id || value.name || value.model || value.modelId || value.provider || "";
  return String(value);
}

function numberValue(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(String(value).replace(/[$,]/g, ""));
  return Number.isFinite(number) ? number : null;
}

function artifactDownloadUrl(artifact) {
  const sessionId = state.selectedSessionId || getSessionId(state.session);
  if (!sessionId) return "";
  const path = artifact.path || artifact.relativePath || "";
  const name = artifact.name || path.split("/").pop() || "";
  if (!name || !/\.(docx|json)$/i.test(name)) return "";
  return `/api/session?sessionId=${encodeURIComponent(sessionId)}&asset=${encodeURIComponent(name)}`;
}

function downloadNameForArtifact(artifact) {
  const path = artifact?.path || artifact?.relativePath || "";
  const name = artifact?.name || path.split("/").pop() || "";
  if (/user_guide.*\.docx$/i.test(name)) {
    return guideDocxDownloadName();
  }
  return safeDownloadName(name || "kcxdocumentor-artifact.json");
}

function guideDocxDownloadName() {
  const title = state.generationMetadata?.title
    || state.session?.generation?.title
    || state.session?.draftSummary?.title
    || state.session?.guideDraft?.title
    || state.session?.title
    || sessionTitleFromSource();
  const sessionId = state.selectedSessionId || getSessionId(state.session);
  const parts = [title, sessionId].filter(Boolean).map((part) => fileSlug(part, 72)).filter(Boolean);
  const base = parts.length ? parts.join("-") : "kcxdocumentor-guide";
  return `${base}.docx`;
}

function sessionTitleFromSource() {
  const source = basename(state.session?.sourceFile || state.session?.recording?.sourceFile || els.recordingSelect.value || "");
  const withoutExtension = source.replace(/\.[^.]+$/, "");
  return withoutExtension || "kcxdocumentor-guide";
}

function safeDownloadName(name) {
  const extension = name.includes(".") ? `.${name.split(".").pop()}` : "";
  const base = extension ? name.slice(0, -extension.length) : name;
  return `${fileSlug(base, 100) || "kcxdocumentor-artifact"}${extension.toLowerCase()}`;
}

function fileSlug(value, maxLength = 90) {
  return String(value || "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, maxLength)
    .replace(/-+$/g, "");
}

function getRecordingLabel(recording) {
  if (typeof recording === "string") return recording;
  return recording.name || recording.sourceName || recording.fileName || recording.path || "recording";
}

function getRecordingValue(recording) {
  if (typeof recording === "string") return recording;
  return recording.relativePath || recording.path || recording.name || recording.sourceFile || recording.fileName || "";
}

function getTranscriptLabel(transcript) {
  if (typeof transcript === "string") return transcript;
  return transcript.name || transcript.fileName || transcript.path || "transcript";
}

function getTranscriptValue(transcript) {
  if (typeof transcript === "string") return transcript;
  return transcript.relativePath || transcript.path || transcript.name || transcript.fileName || "";
}

function getSelectedTranscript() {
  return els.transcriptSelect.value;
}

function upsertTranscript(transcript) {
  const value = getTranscriptValue(transcript);
  if (!value) return;
  if (!state.transcripts.some((item) => getTranscriptValue(item) === value)) {
    state.transcripts = [...state.transcripts, transcript];
  }
}

function getSessionId(session) {
  if (typeof session === "string") return session;
  return session?.sessionId || session?.id || session?.name || "";
}

function sessionSubtitle(session) {
  const app = session.targetApplication || session.recording?.targetApplication || session.sourceName || "Unknown application";
  const source = session.sourceName || basename(session.sourceFile || session.recording?.sourceFile || "");
  const modified = formatDateTime(session.modifiedUtc || session.createdUtc);
  const parts = [app, source, modified].filter(Boolean);
  return parts.join(" · ");
}

function syncSessionIdPlaceholder() {
  const recording = els.recordingSelect.value;
  const base = recording.split("/").pop()?.replace(/\.[^.]+$/, "") || "recording";
  els.sessionIdInput.placeholder = `${slugify(base)}-test`;
  if (/teams|meeting recording/i.test(recording)) {
    els.sourceProfile.value = "teams-recording";
  }
  updateActionAvailability();
}

function basename(value) {
  return String(value || "").split(/[\\/]/).pop() || "";
}

function frameUrl(path) {
  const sessionId = state.selectedSessionId || getSessionId(state.session);
  return `/api/session?sessionId=${encodeURIComponent(sessionId)}&asset=${encodeURIComponent(path)}`;
}

function sessionVideoUrl(sessionId) {
  return `/api/session-video?sessionId=${encodeURIComponent(sessionId)}`;
}

function formatVideoTimestamp(seconds) {
  const safeSeconds = Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(safeSeconds / 60);
  const remainingSeconds = safeSeconds - minutes * 60;
  return `${minutes}:${remainingSeconds.toFixed(3).padStart(6, "0")}`;
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

function formatDateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function formatUsageBucket(bucket) {
  const value = bucket.day || bucket.date || bucket.generatedAt || bucket.generated_at || bucket.start || bucket.label;
  if (!value) return "Unknown date";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}

function rangeLabel(range) {
  return ({ day: "Daily", week: "Weekly", month: "Monthly", year: "Yearly" })[range] || "Usage";
}

function formatNumber(value) {
  if (!Number.isFinite(Number(value))) return "";
  return Number(value).toLocaleString();
}

function formatCost(value) {
  if (!Number.isFinite(Number(value))) return "";
  return `$${Number(value).toFixed(4)}`;
}

function formatPageCount(value) {
  const pages = Number(value || 0);
  return Number.isFinite(pages) && pages > 0 ? formatNumber(pages) : "--";
}

function formatCostPerPage(value, pageCount) {
  const pages = Number(pageCount || 0);
  return Number.isFinite(pages) && pages > 0 ? formatCost(value) || "--" : "--";
}

function renderTags(values, className = "") {
  return values.slice(0, 8).map((value) => `<span class="tag ${className}">${escapeHtml(value)}</span>`).join("");
}

function renderReasons(reasons = []) {
  if (!reasons.length) return "";
  return `<ul class="reason-list">${reasons.map((reason) => `<li>${escapeHtml(reason)}</li>`).join("")}</ul>`;
}

function setBusy(isBusy) {
  state.busy = isBusy;
  document.body.classList.toggle("busy", isBusy);
  renderAuth();
  renderOperationStatus();
  updateActionAvailability();
}

function setOperation(message, messages = []) {
  stopOperationMessageRotation();
  state.operationMessage = message || "";
  state.operationMessages = Array.isArray(messages) ? messages.filter(Boolean) : [];
  state.operationMessageIndex = 0;
  renderOperationStatus();
  if (state.operationMessages.length > 0) {
    state.operationTimer = window.setInterval(() => {
      if (!state.operationMessages.length) return;
      state.operationMessageIndex = (state.operationMessageIndex + 1) % state.operationMessages.length;
      state.operationMessage = state.operationMessages[state.operationMessageIndex];
      renderOperationStatus();
    }, 4500);
  }
}

function stopOperationMessageRotation() {
  if (state.operationTimer) {
    window.clearInterval(state.operationTimer);
    state.operationTimer = null;
  }
}

function renderOperationStatus() {
  const visible = Boolean(state.operationMessage);
  els.operationStatus.hidden = !visible;
  els.operationStatusText.textContent = state.operationMessage || "";
}

function updateActionAvailability() {
  const hasRecording = Boolean(els.recordingSelect.value);
  const hasSession = Boolean(state.selectedSessionId || els.sessionIdInput.value.trim());
  const hasLoadedSession = Boolean(state.session);
  const cloudReady = isAuthenticated();
  const artifacts = getArtifacts();
  const hasDocx = artifacts.some((artifact) => /user_guide.*\.docx$/i.test(artifact.name || artifact.path || ""));

  els.refreshAll.disabled = state.busy;
  els.importRecordingButton.disabled = state.busy;
  els.importTranscriptButton.disabled = state.busy;
  els.processButton.disabled = state.busy || !hasRecording;
  els.generateDraftButton.disabled = state.busy || !hasSession || !cloudReady;
  els.buildDocxButton.disabled = state.busy || !hasDocx;
  els.qaDocxButton.disabled = state.busy || !hasSession || !hasDocx;
  els.reloadSession.disabled = state.busy || !hasSession;
  els.clearSession.disabled = state.busy || !hasSession;
  els.sessionList.querySelectorAll("[data-session-delete]").forEach((button) => {
    button.disabled = state.busy;
  });
  els.addFrameButton.disabled = state.busy || !hasLoadedSession;
  els.addFrameTimestampButton.disabled = state.busy || !hasLoadedSession;
  els.useVideoTimeButton.disabled = state.busy || !hasLoadedSession;

  els.processButton.title = hasRecording ? "Process the selected recording into a local trace." : "Select a recording first.";
  els.generateDraftButton.title = !cloudReady
    ? "Sign in with Microsoft to create an AI guide."
    : hasSession ? "Create the AI guide, build the DOCX, and run local QA." : "Select or process a session first.";
  els.buildDocxButton.title = hasDocx ? "Download the latest generated DOCX." : "Create a guide first.";
  els.qaDocxButton.title = hasDocx ? "Re-run local QA checks without using AI tokens." : "Create a guide first.";
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
