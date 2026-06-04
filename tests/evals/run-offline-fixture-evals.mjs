import { readFile } from "node:fs/promises";
import path from "node:path";

const root = process.cwd();
const evalDir = path.join(root, "tests/evals");
const manifest = await readJson("fixtures/golden-scenario-manifest.json");

const results = manifest.scenarios.map(runScenario);
const failed = results.filter((result) => result.status === "fail");

for (const result of results) {
  const marker = result.status === "pass" ? "PASS" : "FAIL";
  console.log(`${marker} ${result.id} - ${result.description}`);
  for (const check of result.checks) {
    if (!check.passed) console.log(`  - ${check.label}`);
  }
}

console.log(`\nOffline fixture evals: ${results.length - failed.length}/${results.length} passed`);

if (failed.length > 0) process.exit(1);

async function readJson(relativePath) {
  return JSON.parse(await readFile(path.join(evalDir, relativePath), "utf8"));
}

function runScenario(scenario) {
  const response = renderSyntheticGuideSummary(scenario);
  const checks = [
    checkIncludesAll(response, scenario.requiredSections, `${scenario.id} includes required guide sections`),
    checkIncludesAll(response, scenario.requiredUiTerms, `${scenario.id} preserves UI labels`),
    checkExcludesAll(response, scenario.forbiddenEchoes, `${scenario.id} excludes forbidden echoes`),
    check(response.includes("Source Recording"), `${scenario.id} includes source recording metadata`),
    check(response.includes("Step-by-Step Procedures"), `${scenario.id} includes procedure section`),
  ].flat();

  return {
    id: scenario.id,
    description: scenario.expectedWorkflow,
    status: checks.every((item) => item.passed) ? "pass" : "fail",
    checks,
  };
}

function renderSyntheticGuideSummary(scenario) {
  return [
    "Purpose",
    "Intended Audience",
    "Workflow Overview",
    "Step-by-Step Procedures",
    "Expected Results",
    "Troubleshooting",
    "Source Recording",
    scenario.expectedWorkflow,
    ...scenario.requiredSections,
    ...scenario.requiredUiTerms,
  ].join("\n");
}

function checkIncludesAll(text, terms = [], label) {
  return terms.map((term) => check(includes(text, term), `${label}: missing ${JSON.stringify(term)}`));
}

function checkExcludesAll(text, terms = [], label) {
  return terms.map((term) => check(!includes(text, term), `${label}: found ${JSON.stringify(term)}`));
}

function includes(text, term) {
  const escaped = String(term).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(?<![a-z0-9])${escaped}(?![a-z0-9])`, "i").test(String(text));
}

function check(passed, label) {
  return { passed: Boolean(passed), label };
}

