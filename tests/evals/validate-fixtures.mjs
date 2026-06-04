import { readdir, readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const evalDir = path.join(root, "tests/evals");
const scenarioDir = path.join(evalDir, "scenarios");
const fixtureDir = path.join(evalDir, "fixtures");

const manifest = await readJson("fixtures/golden-scenario-manifest.json");
const liveScenarioFiles = existsSync(scenarioDir)
  ? (await readdir(scenarioDir)).filter((file) => file.endsWith(".json")).sort()
  : [];
const liveScenarios = await Promise.all(liveScenarioFiles.map(async (file) => ({
  file: `scenarios/${file}`,
  scenario: await readJson(`scenarios/${file}`),
})));

const errors = [];

validateManifest();
validateLiveScenarios();

if (errors.length > 0) {
  for (const error of errors) console.error(`Error: ${error}`);
  process.exit(1);
}

console.log(`Validated ${manifest.scenarios.length} golden scenario entries and ${liveScenarios.length} scenario files.`);

async function readJson(relativePath) {
  const absolutePath = path.join(evalDir, relativePath);
  return JSON.parse(await readFile(absolutePath, "utf8"));
}

function validateManifest() {
  requireEqual(manifest.schemaVersion, 1, "manifest schemaVersion");
  requireArray(manifest.scenarios, "manifest.scenarios");
  requireTrue(manifest.scenarios.length >= 5, "manifest should define at least five MVP golden scenarios");
  requireUnique(manifest.scenarios.map((scenario) => scenario.id), "manifest scenario id");

  for (const scenario of manifest.scenarios) {
    requireString(scenario.id, `${scenario.id ?? "unknown"}.id`);
    requireString(scenario.status, `${scenario.id}.status`);
    requireString(scenario.recordingProfile, `${scenario.id}.recordingProfile`);
    requireString(scenario.expectedWorkflow, `${scenario.id}.expectedWorkflow`);
    requireArray(scenario.requiredSections, `${scenario.id}.requiredSections`);
    requireArray(scenario.requiredUiTerms, `${scenario.id}.requiredUiTerms`);
    requireArray(scenario.forbiddenEchoes, `${scenario.id}.forbiddenEchoes`);
    requireArray(scenario.qualityChecks, `${scenario.id}.qualityChecks`);

    if (scenario.status === "implemented") {
      requireString(scenario.backingScenarioFile, `${scenario.id}.backingScenarioFile`);
      requireFileExists(path.join(evalDir, scenario.backingScenarioFile), `${scenario.id}.backingScenarioFile`);
    }
  }
}

function validateLiveScenarios() {
  for (const { file, scenario } of liveScenarios) {
    requireString(scenario.id, `${file}.id`);
    requireString(scenario.input?.procedureTraceFixture, `${scenario.id}.input.procedureTraceFixture`);
    requireArray(scenario.expected?.requiredSections, `${scenario.id}.expected.requiredSections`);
    requireArray(scenario.expected?.requiredUiTerms, `${scenario.id}.expected.requiredUiTerms`);

    const manifestEntry = manifest.scenarios.find((entry) => entry.id === scenario.id);
    requireTrue(Boolean(manifestEntry), `${scenario.id} exists in golden manifest`);
    if (manifestEntry) {
      requireEqual(manifestEntry.backingScenarioFile, file, `${scenario.id}.manifest.backingScenarioFile`);
    }
  }
}

function requireString(value, label) {
  if (typeof value !== "string" || value.trim() === "") errors.push(`${label} must be a non-empty string`);
}

function requireArray(value, label) {
  if (!Array.isArray(value) || value.length === 0) errors.push(`${label} must be a non-empty array`);
}

function requireEqual(actual, expected, label) {
  if (actual !== expected) errors.push(`${label} expected ${JSON.stringify(expected)} but found ${JSON.stringify(actual)}`);
}

function requireTrue(condition, label) {
  if (!condition) errors.push(`${label} failed`);
}

function requireUnique(values, label) {
  const seen = new Set();
  for (const value of values) {
    if (!value) continue;
    if (seen.has(value)) errors.push(`${label} ${JSON.stringify(value)} is duplicated`);
    seen.add(value);
  }
}

function requireFileExists(absolutePath, label) {
  if (!existsSync(absolutePath)) errors.push(`${label} file does not exist at ${absolutePath}`);
}

