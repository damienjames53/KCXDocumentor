import { app } from "@azure/functions";
import { CosmosClient } from "@azure/cosmos";
import { DefaultAzureCredential } from "@azure/identity";
import { QueueClient } from "@azure/storage-queue";
import { createRemoteJWKSet, decodeProtectedHeader, jwtVerify } from "jose";
import { createHash, randomUUID } from "node:crypto";

const DEFAULT_MODEL = "claude-sonnet-4-6";
const INPUT_COST_PER_MILLION = 3.0;
const OUTPUT_COST_PER_MILLION = 15.0;
const ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages";
const FOUNDRY_MESSAGES_PATH = "/anthropic/v1/messages";

let cosmosContainerPromise;
let queueClientPromise;
let jwks;

app.http("generateDraft", {
  methods: ["POST"],
  authLevel: "anonymous",
  route: "generate-draft",
  handler: async (request, context) => {
    const userOrResponse = await authenticatedUserOrResponse(request);
    if (userOrResponse.response) {
      return userOrResponse.response;
    }
    const user = userOrResponse.user;
    const body = await request.json();
    const anthropicPayload = body?.anthropic;
    if (!anthropicPayload || typeof anthropicPayload !== "object") {
      return jsonResponse({ error: "Request body must include anthropic payload." }, 400);
    }

    const metadata = body?.metadata && typeof body.metadata === "object" ? body.metadata : {};
    const model = String(anthropicPayload.model || metadata.model || DEFAULT_MODEL);
    const generatedAt = utcTimestamp();
    let result = {};

    try {
      result = await callClaude({ ...anthropicPayload, model });
      const report = generationReport({
        status: "succeeded",
        generatedAt,
        metadata,
        model,
        usage: normalizeUsage(result.usage, model),
        provider: aiProviderName(),
        user,
      });
      await upsertUsageRecord(report);
      return jsonResponse({ anthropicResult: result, generationReport: report });
    } catch (error) {
      const usage = normalizeUsage(result?.usage, model);
      const report = generationReport({
        status: "failed",
        generatedAt,
        metadata,
        model,
        usage,
        provider: aiProviderName(),
        user,
        errorMessage: error.message || "Anthropic proxy request failed.",
      });
      await upsertUsageRecord(report);
      context.error(error);
      return jsonResponse({ error: report.errorMessage, generationReport: report }, error.statusCode || 502);
    }
  },
});

app.http("generationJobs", {
  methods: ["POST"],
  authLevel: "anonymous",
  route: "generation-jobs",
  handler: async (request, context) => {
    const userOrResponse = await authenticatedUserOrResponse(request);
    if (userOrResponse.response) {
      return userOrResponse.response;
    }
    const user = userOrResponse.user;
    const body = await request.json();
    const anthropicPayload = body?.anthropic;
    if (!anthropicPayload || typeof anthropicPayload !== "object") {
      return jsonResponse({ error: "Request body must include anthropic payload." }, 400);
    }

    const metadata = body?.metadata && typeof body.metadata === "object" ? body.metadata : {};
    const model = String(anthropicPayload.model || metadata.model || DEFAULT_MODEL);
    const now = utcTimestamp();
    const tokenEstimate = estimatePayloadTokens(anthropicPayload);
    const job = generationJob({
      status: "queued",
      message: "Queued for AI capacity.",
      user,
      metadata,
      model,
      tokenEstimate,
      anthropicPayload: { ...anthropicPayload, model },
      createdAt: now,
      updatedAt: now,
    });

    await upsertGenerationJob(job);
    const queue = await generationQueueClient();
    await queue.sendMessage(JSON.stringify({
      jobId: job.jobId,
      partitionKey: job.partitionKey,
    }));
    context.log(`Queued generation job ${job.jobId} for session ${job.sessionId || "(unknown)"}.`);
    return jsonResponse({ job: publicGenerationJob(job) }, 202);
  },
});

app.http("generationJobStatus", {
  methods: ["GET"],
  authLevel: "anonymous",
  route: "generation-jobs/{jobId}",
  handler: async (request) => {
    const userOrResponse = await authenticatedUserOrResponse(request);
    if (userOrResponse.response) {
      return userOrResponse.response;
    }
    const jobId = request.params.jobId;
    const job = await readGenerationJob(jobId);
    if (!job) {
      return jsonResponse({ error: "Generation job not found." }, 404);
    }
    if (!canReadJob(job, userOrResponse.user)) {
      return jsonResponse({ error: "Generation job is not available to the signed-in user." }, 403);
    }
    return jsonResponse({ job: publicGenerationJob(job) });
  },
});

app.storageQueue("processGenerationJob", {
  queueName: process.env.KCXDOC_GENERATION_QUEUE_NAME || "kcxdocumentor-generation-jobs",
  connection: "AzureWebJobsStorage",
  handler: async (message, context) => {
    const pointer = typeof message === "string" ? safeJsonParse(message) : message;
    const jobId = pointer?.jobId;
    if (!jobId) {
      context.error("Generation queue message did not include a jobId.");
      return;
    }
    let job = await readGenerationJob(jobId);
    if (!job) {
      context.error(`Generation job ${jobId} was not found.`);
      return;
    }
    if (["succeeded", "failed", "cancelled"].includes(job.status)) {
      context.log(`Generation job ${jobId} is already ${job.status}; skipping.`);
      return;
    }

    const generatedAt = utcTimestamp();
    job = await patchGenerationJob(job, {
      status: "generating",
      message: "AI guide generation is running.",
      startedAt: job.startedAt || generatedAt,
      updatedAt: generatedAt,
    });

    try {
      const model = String(job.model || DEFAULT_MODEL);
      const result = await callClaude(job.anthropicPayload || {});
      const report = generationReport({
        status: "succeeded",
        generatedAt,
        metadata: job.metadata || {},
        model,
        usage: normalizeUsage(result.usage, model),
        provider: aiProviderName(),
        user: job.generatedBy || job.user || {},
      });
      await upsertUsageRecord(report);
      await patchGenerationJob(job, {
        status: "succeeded",
        message: "AI guide draft is ready.",
        completedAt: utcTimestamp(),
        updatedAt: utcTimestamp(),
        anthropicResult: result,
        generationReport: report,
        usage: report.usage,
      });
    } catch (error) {
      const model = String(job.model || DEFAULT_MODEL);
      const report = generationReport({
        status: "failed",
        generatedAt,
        metadata: job.metadata || {},
        model,
        usage: normalizeUsage(error?.anthropicResult?.usage, model),
        provider: aiProviderName(),
        user: job.generatedBy || job.user || {},
        errorMessage: error.message || "AI generation job failed.",
      });
      await upsertUsageRecord(report);
      await patchGenerationJob(job, {
        status: "failed",
        message: report.errorMessage,
        completedAt: utcTimestamp(),
        updatedAt: utcTimestamp(),
        errorMessage: report.errorMessage,
        generationReport: report,
        usage: report.usage,
      });
      context.error(error);
    }
  },
});

app.http("usageSummary", {
  methods: ["GET"],
  authLevel: "anonymous",
  route: "usage-summary",
  handler: async (request) => {
    const userOrResponse = await authenticatedUserOrResponse(request);
    if (userOrResponse.response) {
      return userOrResponse.response;
    }
    const range = normalizeRange(new URL(request.url).searchParams.get("range"));
    const records = await readUsageRecords();
    return jsonResponse(buildUsageSummary(records, range));
  },
});

app.http("usageRecords", {
  methods: ["POST"],
  authLevel: "anonymous",
  route: "usage-records",
  handler: async (request) => {
    const userOrResponse = await authenticatedUserOrResponse(request);
    if (userOrResponse.response) {
      return userOrResponse.response;
    }
    const user = userOrResponse.user;
    const body = await request.json();
    const records = Array.isArray(body?.records) ? body.records : [];
    if (!records.length) {
      return jsonResponse({ error: "Request body must include records array." }, 400);
    }
    const results = [];
    for (const record of records) {
      const normalized = normalizeImportedUsageRecord(record, user);
      await upsertUsageRecord(normalized);
      results.push({ generationRunId: normalized.generationRunId, status: normalized.status });
    }
    return jsonResponse({ imported: results.length, records: results });
  },
});

async function callClaude(payload) {
  const provider = aiProviderName();
  const apiKey = apiKeyForProvider(provider);
  if (!apiKey || apiKey === "__SET_ME__") {
    const error = new Error(`${apiKeySettingName(provider)} is not configured on the Function App.`);
    error.statusCode = 500;
    throw error;
  }
  const response = await fetch(messagesUrlForProvider(provider), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify(payload),
  });
  const text = await response.text();
  const data = text ? safeJsonParse(text) : {};
  if (!response.ok) {
    const message = data?.error?.message || data?.message || text || `HTTP ${response.status}`;
    const errorType = data?.error?.type || data?.type || `${provider}_error`;
    const error = new Error(`Claude API request failed through ${provider}: HTTP ${response.status} (${errorType}): ${message}`);
    error.statusCode = response.status;
    error.anthropicResult = data;
    throw error;
  }
  return data;
}

function aiProviderName() {
  return String(process.env.KCXDOC_AI_PROVIDER || "anthropic").trim().toLowerCase();
}

function apiKeyForProvider(provider) {
  if (provider === "azure-foundry") {
    return process.env.KCXDOC_FOUNDRY_API_KEY
      || process.env.ANTHROPIC_FOUNDRY_API_KEY
      || process.env.ANTHROPIC_API_KEY
      || process.env.KCXDOC_ANTHROPIC_API_KEY;
  }
  return process.env.ANTHROPIC_API_KEY || process.env.KCXDOC_ANTHROPIC_API_KEY;
}

function apiKeySettingName(provider) {
  return provider === "azure-foundry" ? "KCXDOC_FOUNDRY_API_KEY" : "ANTHROPIC_API_KEY";
}

function messagesUrlForProvider(provider) {
  if (provider === "azure-foundry") {
    const explicitUrl = process.env.KCXDOC_FOUNDRY_MESSAGES_URL || process.env.ANTHROPIC_FOUNDRY_MESSAGES_URL;
    if (explicitUrl) return explicitUrl;
    const baseUrl = process.env.KCXDOC_FOUNDRY_BASE_URL || process.env.ANTHROPIC_FOUNDRY_BASE_URL;
    if (baseUrl) return `${baseUrl.replace(/\/+$/, "")}${FOUNDRY_MESSAGES_PATH}`;
    const resourceName = process.env.KCXDOC_FOUNDRY_RESOURCE_NAME || process.env.ANTHROPIC_FOUNDRY_RESOURCE;
    if (resourceName) return `https://${resourceName}.services.ai.azure.com${FOUNDRY_MESSAGES_PATH}`;
    throw Object.assign(new Error("KCXDOC_FOUNDRY_MESSAGES_URL or KCXDOC_FOUNDRY_RESOURCE_NAME is required for Azure Foundry Claude."), { statusCode: 500 });
  }
  return process.env.KCXDOC_ANTHROPIC_MESSAGES_URL || ANTHROPIC_MESSAGES_URL;
}

async function authenticatedUserOrResponse(request) {
  try {
    return { user: await requireAuthenticatedUser(request) };
  } catch (error) {
    return { response: jsonResponse({ error: error.message || "Authentication failed." }, error.statusCode || 401) };
  }
}

function safeJsonParse(text) {
  try {
    return JSON.parse(text);
  } catch {
    return { message: text };
  }
}

async function requireAuthenticatedUser(request) {
  const authorization = request.headers.get("authorization") || "";
  if (!authorization.startsWith("Bearer ")) {
    const error = new Error("Authentication is required.");
    error.statusCode = 401;
    throw error;
  }
  try {
    const token = authorization.slice("Bearer ".length).trim();
    const tokenParts = token.split(".");
    if (tokenParts.length !== 3) {
      throw new Error("Bearer token is not a JWT.");
    }
    const protectedHeader = decodeProtectedHeader(token);
    if (!protectedHeader.alg || !protectedHeader.kid) {
      throw new Error("Bearer token is missing required JWT header fields.");
    }
    const tenantId = requiredEnv("KCXDOC_AUTH_TENANT_ID");
    const audience = requiredEnv("KCXDOC_ALLOWED_AUDIENCE");
    const issuer = process.env.KCXDOC_AUTH_ISSUER || `https://login.microsoftonline.com/${tenantId}/v2.0`;
    if (!jwks) {
      jwks = createRemoteJWKSet(new URL(`https://login.microsoftonline.com/${tenantId}/discovery/v2.0/keys`), {
        timeoutDuration: 5000,
      });
    }
    const { payload } = await jwtVerify(token, jwks, {
      audience,
      issuer,
    });
    return {
      oid: payload.oid || payload.sub || "",
      name: payload.name || payload.preferred_username || "",
      username: payload.preferred_username || payload.upn || "",
    };
  } catch (error) {
    const authError = new Error("Authentication token is invalid or expired.");
    authError.statusCode = 401;
    authError.cause = error;
    throw authError;
  }
}

async function upsertUsageRecord(report) {
  const container = await cosmosContainer();
  await container.items.upsert({
    ...report,
    id: report.generationRunId,
    partitionKey: usagePartitionKey(report.generatedAt),
    recordedAt: report.recordedAt || utcTimestamp(),
  });
}

async function upsertGenerationJob(job) {
  const container = await cosmosContainer();
  await container.items.upsert({
    ...job,
    id: job.jobId,
    partitionKey: job.partitionKey,
    documentType: "generationJob",
  });
}

async function readGenerationJob(jobId) {
  const container = await cosmosContainer();
  const { resources } = await container.items
    .query({
      query: "SELECT * FROM c WHERE c.documentType = 'generationJob' AND c.jobId = @jobId",
      parameters: [{ name: "@jobId", value: String(jobId || "") }],
    })
    .fetchAll();
  return resources[0] || null;
}

async function patchGenerationJob(job, updates) {
  const updated = {
    ...job,
    ...updates,
    id: job.jobId,
    partitionKey: job.partitionKey,
    documentType: "generationJob",
  };
  await upsertGenerationJob(updated);
  return updated;
}

async function generationQueueClient() {
  if (!queueClientPromise) {
    queueClientPromise = (async () => {
      const queueName = process.env.KCXDOC_GENERATION_QUEUE_NAME || "kcxdocumentor-generation-jobs";
      const connectionString = process.env.KCXDOC_GENERATION_QUEUE_CONNECTION || process.env.AzureWebJobsStorage;
      if (!connectionString) {
        throw new Error("AzureWebJobsStorage or KCXDOC_GENERATION_QUEUE_CONNECTION is required for generation queueing.");
      }
      const client = QueueClient.fromConnectionString(connectionString, queueName);
      await client.createIfNotExists();
      return client;
    })();
  }
  return queueClientPromise;
}

async function readUsageRecords() {
  const container = await cosmosContainer();
  const { resources } = await container.items
    .query("SELECT * FROM c WHERE IS_DEFINED(c.generationRunId)")
    .fetchAll();
  return resources;
}

async function cosmosContainer() {
  if (!cosmosContainerPromise) {
    cosmosContainerPromise = (async () => {
      const endpoint = requiredEnv("KCXDOC_COSMOS_ENDPOINT");
      const databaseName = process.env.KCXDOC_COSMOS_DATABASE || "kcxdocumentor";
      const containerName = process.env.KCXDOC_COSMOS_CONTAINER || "aiUsage";
      const client = new CosmosClient({
        endpoint,
        aadCredentials: new DefaultAzureCredential(),
      });
  return client.database(databaseName).container(containerName);
    })();
  }
  return cosmosContainerPromise;
}

function generationJob({ status, message, user, metadata, model, tokenEstimate, anthropicPayload, createdAt, updatedAt }) {
  const generatedBy = normalizedGeneratedBy(user);
  const sessionId = String(metadata.sessionId || "");
  const jobId = String(metadata.generationJobId || randomUUID());
  const partitionKey = usagePartitionKey(createdAt);
  return {
    schemaVersion: 1,
    documentType: "generationJob",
    id: jobId,
    jobId,
    partitionKey,
    status,
    message,
    createdAt,
    updatedAt,
    sessionId,
    title: String(metadata.title || ""),
    model,
    provider: aiProviderName(),
    promptVersion: String(metadata.promptVersion || ""),
    metadata,
    tokenEstimate,
    generatedBy,
    user: generatedBy,
    anthropicPayload,
  };
}

function publicGenerationJob(job) {
  const publicJob = {
    jobId: job.jobId,
    status: job.status,
    message: job.message || "",
    createdAt: job.createdAt,
    updatedAt: job.updatedAt,
    startedAt: job.startedAt,
    completedAt: job.completedAt,
    sessionId: job.sessionId || "",
    title: job.title || "",
    model: job.model || "",
    provider: job.provider || "",
    promptVersion: job.promptVersion || "",
    tokenEstimate: job.tokenEstimate || {},
    usage: job.usage || job.generationReport?.usage || {},
    errorMessage: job.errorMessage || "",
    generationReport: job.generationReport || null,
  };
  if (job.status === "succeeded") {
    publicJob.anthropicResult = job.anthropicResult || {};
  }
  return publicJob;
}

function canReadJob(job, user) {
  const owner = normalizedGeneratedBy(job.generatedBy || job.user || {});
  const current = normalizedGeneratedBy(user);
  if (!owner.oid && !owner.username) return true;
  return Boolean(
    (owner.oid && current.oid && owner.oid === current.oid)
      || (owner.username && current.username && owner.username.toLowerCase() === current.username.toLowerCase()),
  );
}

function estimatePayloadTokens(payload) {
  const serialized = JSON.stringify(payload || {});
  const estimatedInputTokens = Math.ceil(serialized.length / 4);
  const expectedOutputTokens = Number(payload?.max_tokens || process.env.KCXDOC_EXPECTED_OUTPUT_TOKENS || 12000) || 12000;
  return {
    method: "chars_per_4",
    estimatedInputTokens,
    expectedOutputTokens,
    estimatedTotalTokens: estimatedInputTokens + expectedOutputTokens,
    characterCount: serialized.length,
    tpmLimit: Number(process.env.KCXDOC_FOUNDRY_TPM_LIMIT || 80000) || 80000,
    schedulingTargetTokens: Number(process.env.KCXDOC_FOUNDRY_TPM_TARGET || 70000) || 70000,
  };
}

function generationReport({ status, generatedAt, metadata, model, usage, user, provider = "anthropic", errorMessage = "" }) {
  const generatedBy = normalizedGeneratedBy(user);
  const report = {
    schemaVersion: 1,
    status,
    generatedAt,
    sessionId: String(metadata.sessionId || ""),
    title: String(metadata.title || (status === "failed" ? "Failed guide generation" : "")),
    provider,
    model,
    promptVersion: String(metadata.promptVersion || ""),
    usage,
    errorMessage,
    generatedBy,
    user: generatedBy,
  };
  report.generationRunId = String(metadata.generationRunId || generationRunId(report));
  return report;
}

function normalizeImportedUsageRecord(record, user) {
  const usage = record.usage && typeof record.usage === "object" ? record.usage : {};
  const generatedBy = normalizedGeneratedBy(record.generatedBy || record.user || {});
  const normalized = {
    schemaVersion: 1,
    status: String(record.status || "succeeded"),
    generatedAt: String(record.generatedAt || utcTimestamp()),
    sessionId: String(record.sessionId || ""),
    title: String(record.title || ""),
    provider: String(record.provider || "anthropic"),
    model: String(record.model || DEFAULT_MODEL),
    promptVersion: String(record.promptVersion || ""),
    usage: normalizeUsage(
      {
        input_tokens: usage.inputTokens ?? usage.input_tokens ?? record.inputTokens,
        output_tokens: usage.outputTokens ?? usage.output_tokens ?? record.outputTokens,
      },
      String(record.model || DEFAULT_MODEL),
    ),
    pageCount: Number(record.pageCount || 0),
    errorMessage: String(record.errorMessage || ""),
    generatedBy,
    user: generatedBy,
    migratedBy: {
      oid: user.oid || "",
      name: user.name || "",
      username: user.username || "",
    },
  };
  normalized.generationRunId = String(record.generationRunId || generationRunId(normalized));
  return normalized;
}

function normalizeUsage(usage, model) {
  const inputTokens = Number(usage?.input_tokens ?? usage?.inputTokens ?? 0) || 0;
  const outputTokens = Number(usage?.output_tokens ?? usage?.outputTokens ?? 0) || 0;
  const totalTokens = inputTokens + outputTokens;
  return {
    inputTokens,
    outputTokens,
    totalTokens,
    estimatedCostUSD: estimateCost(inputTokens, outputTokens, model),
  };
}

function estimateCost(inputTokens, outputTokens) {
  return Number(((inputTokens / 1_000_000) * INPUT_COST_PER_MILLION + (outputTokens / 1_000_000) * OUTPUT_COST_PER_MILLION).toFixed(6));
}

function buildUsageSummary(records, range) {
  const buckets = new Map();
  for (const record of records) {
    const key = usageBucketKey(record.generatedAt, range);
    const bucket = buckets.get(key) || emptyBucket(key);
    addRecordToBucket(bucket, record);
    buckets.set(key, bucket);
  }
  const orderedBuckets = [...buckets.values()].sort((left, right) => left.label.localeCompare(right.label));
  const totals = emptyTotals();
  for (const bucket of orderedBuckets) {
    addTotals(totals, bucket.totals);
  }
  totals.costPerPageUSD = costPerPage(totals.estimatedCostUSD, totals.pageCount);
  return {
    range,
    generatedAt: utcTimestamp(),
    totals,
    buckets: orderedBuckets,
    days: range === "day" ? orderedBuckets : [],
  };
}

function addRecordToBucket(bucket, record) {
  const usage = record.usage && typeof record.usage === "object" ? record.usage : {};
  const status = String(record.status || "succeeded");
  const pageCount = Number(record.pageCount || usage.pageCount || 0) || 0;
  const cost = Number(usage.estimatedCostUSD || 0) || 0;
  const generatedBy = normalizedGeneratedBy(record.generatedBy || record.user || {});
  const document = {
    generationRunId: record.generationRunId,
    generatedAt: record.generatedAt,
    sessionId: record.sessionId || "",
    title: record.title || "",
    model: record.model || "",
    status,
    errorMessage: record.errorMessage || "",
    generatedBy,
    usage: {
      inputTokens: Number(usage.inputTokens || 0),
      outputTokens: Number(usage.outputTokens || 0),
      totalTokens: Number(usage.totalTokens || 0),
      estimatedCostUSD: cost,
      pageCount,
      costPerPageUSD: costPerPage(cost, pageCount),
    },
  };
  bucket.documents.push(document);
  bucket.totals.attempts += 1;
  if (status === "failed") {
    bucket.totals.failedAttempts += 1;
  } else {
    bucket.totals.documents += 1;
    bucket.totals.pageCount += pageCount;
  }
  bucket.totals.inputTokens += document.usage.inputTokens;
  bucket.totals.outputTokens += document.usage.outputTokens;
  bucket.totals.totalTokens += document.usage.totalTokens;
  bucket.totals.estimatedCostUSD = Number((bucket.totals.estimatedCostUSD + cost).toFixed(6));
  bucket.totals.costPerPageUSD = costPerPage(bucket.totals.estimatedCostUSD, bucket.totals.pageCount);
}

function normalizedGeneratedBy(value) {
  const source = value && typeof value === "object" ? value : {};
  const username = String(source.username || source.upn || source.email || "").trim();
  const name = String(source.name || source.displayName || username || "").trim();
  return {
    oid: String(source.oid || source.id || source.sub || "").trim(),
    name,
    username,
  };
}

function addTotals(target, source) {
  target.documents += source.documents;
  target.attempts += source.attempts;
  target.failedAttempts += source.failedAttempts;
  target.inputTokens += source.inputTokens;
  target.outputTokens += source.outputTokens;
  target.totalTokens += source.totalTokens;
  target.pageCount += source.pageCount;
  target.estimatedCostUSD = Number((target.estimatedCostUSD + source.estimatedCostUSD).toFixed(6));
}

function emptyBucket(label) {
  return { label, totals: emptyTotals(), documents: [] };
}

function emptyTotals() {
  return {
    documents: 0,
    attempts: 0,
    failedAttempts: 0,
    inputTokens: 0,
    outputTokens: 0,
    totalTokens: 0,
    pageCount: 0,
    estimatedCostUSD: 0,
    costPerPageUSD: 0,
  };
}

function usageBucketKey(value, range) {
  const date = new Date(value || Date.now());
  if (Number.isNaN(date.getTime())) return "Unknown";
  if (range === "year") return String(date.getUTCFullYear());
  if (range === "month") return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
  if (range === "week") {
    const weekDate = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
    weekDate.setUTCDate(weekDate.getUTCDate() + 4 - (weekDate.getUTCDay() || 7));
    const yearStart = new Date(Date.UTC(weekDate.getUTCFullYear(), 0, 1));
    const week = Math.ceil((((weekDate - yearStart) / 86400000) + 1) / 7);
    return `${weekDate.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
  }
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}-${String(date.getUTCDate()).padStart(2, "0")}`;
}

function usagePartitionKey(value) {
  return usageBucketKey(value, "month");
}

function normalizeRange(range) {
  return ["day", "week", "month", "year"].includes(range) ? range : "day";
}

function costPerPage(cost, pages) {
  const pageCount = Number(pages || 0);
  return pageCount > 0 ? Number((Number(cost || 0) / pageCount).toFixed(6)) : 0;
}

function generationRunId(report) {
  const usage = report.usage || {};
  const fingerprint = [
    report.sessionId || "",
    report.generatedAt || "",
    report.model || "",
    report.promptVersion || "",
    usage.inputTokens || 0,
    usage.outputTokens || 0,
  ].join("|");
  return createHash("sha256").update(fingerprint).digest("hex").slice(0, 16);
}

function jsonResponse(payload, status = 200) {
  return {
    status,
    jsonBody: payload,
    headers: {
      "Cache-Control": "no-store",
    },
  };
}

function requiredEnv(name) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not configured.`);
  return value;
}

function utcTimestamp() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}
