import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const schemaRoot = path.join(repoRoot, "contracts", "desktop-v2", "schemas");
const fixtureRoot = path.join(repoRoot, "fixtures", "desktop-v2", "contracts");
const tsContracts = await import(pathToFileURL(path.join(repoRoot, "desktop", "src", "contracts", "desktopV2.ts")).href);

async function readJson(filePath) {
  return JSON.parse(await readFile(filePath, "utf8"));
}

function schemaRef(root, reference) {
  assert.ok(reference.startsWith("#/$defs/"), "only local schema refs are expected: " + reference);
  const name = reference.slice("#/$defs/".length);
  assert.ok(root.$defs?.[name], "schema definition is missing: " + name);
  return root.$defs[name];
}

function typeMatches(value, type) {
  switch (type) {
    case "object":
      return typeof value === "object" && value !== null && !Array.isArray(value);
    case "array":
      return Array.isArray(value);
    case "string":
      return typeof value === "string";
    case "integer":
      return typeof value === "number" && Number.isInteger(value);
    case "boolean":
      return typeof value === "boolean";
    case "number":
      return typeof value === "number";
    default:
      return true;
  }
}

function evaluateSchema(value, schema, root, location = "$") {
  if (schema.$ref) return evaluateSchema(value, schemaRef(root, schema.$ref), root, location);

  const errors = [];
  if (schema.type && !typeMatches(value, schema.type)) {
    errors.push(location + " must be " + schema.type);
    return errors;
  }
  if ("const" in schema && value !== schema.const) errors.push(location + " must equal " + JSON.stringify(schema.const));
  if (schema.enum && !schema.enum.includes(value)) errors.push(location + " must be one of " + schema.enum.join(", "));
  if (typeof value === "string") {
    if (schema.minLength !== undefined && value.length < schema.minLength) errors.push(location + " is shorter than minLength");
    if (schema.pattern && !(new RegExp(schema.pattern).test(value))) errors.push(location + " does not match pattern");
    if (schema.format === "uri" && !/^https?:\/\//.test(value)) errors.push(location + " is not a URI");
    if (schema.format === "date-time" && (Number.isNaN(Date.parse(value)) || !value.includes("T"))) errors.push(location + " is not a date-time");
  }
  if (typeof value === "number") {
    if (schema.minimum !== undefined && value < schema.minimum) errors.push(location + " is below minimum");
    if (schema.maximum !== undefined && value > schema.maximum) errors.push(location + " is above maximum");
  }
  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems) errors.push(location + " has too few items");
    if (schema.uniqueItems) {
      const serialized = value.map((item) => JSON.stringify(item));
      if (new Set(serialized).size !== serialized.length) errors.push(location + " has duplicate items");
    }
    if (schema.items) value.forEach((item, index) => errors.push(...evaluateSchema(item, schema.items, root, location + "[" + index + "]")));
  }
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const properties = schema.properties ?? {};
    if (schema.required) {
      for (const key of schema.required) if (!(key in value)) errors.push(location + "." + key + " is required");
    }
    if (schema.additionalProperties === false) {
      for (const key of Object.keys(value)) if (!(key in properties)) errors.push(location + "." + key + " is not allowed");
    }
    for (const [key, childSchema] of Object.entries(properties)) {
      if (key in value) errors.push(...evaluateSchema(value[key], childSchema, root, location + "." + key));
    }
  }
  for (const child of schema.allOf ?? []) errors.push(...evaluateSchema(value, child, root, location));
  if (schema.if) {
    const conditionErrors = evaluateSchema(value, schema.if, root, location);
    if (conditionErrors.length === 0 && schema.then) errors.push(...evaluateSchema(value, schema.then, root, location));
  }
  if (schema.not && evaluateSchema(value, schema.not, root, location).length === 0) errors.push(location + " matches a forbidden schema");
  return errors;
}

function expectValid(label, schema, value) {
  const errors = evaluateSchema(value, schema, schema);
  assert.deepEqual(errors, [], label + " should satisfy its JSON Schema:\n" + errors.join("\n"));
}

function expectInvalid(label, schema, value) {
  const errors = evaluateSchema(value, schema, schema);
  assert.ok(errors.length > 0, label + " should be rejected by its JSON Schema");
}

const cases = [
  {
    schema: "component-manifest.v1.schema.json",
    version: "desktop.component-manifest.v1",
    valid: ["valid-component-manifest.json"],
    invalid: ["invalid-component-manifest-missing-signature.json"],
    validate: tsContracts.validateComponentManifest,
  },
  {
    schema: "engine-control.v1.schema.json",
    version: "desktop.engine-control.v1",
    valid: ["valid-engine-control-start.json"],
    invalid: ["invalid-engine-control-no-token.json"],
    validate: tsContracts.validateEngineControl,
  },
  {
    schema: "health-readiness.v1.schema.json",
    version: "desktop.health-readiness.v1",
    valid: ["valid-health-degraded.json"],
    invalid: ["invalid-health-fatal-without-error.json"],
    validate: tsContracts.validateHealthReadiness,
  },
  {
    schema: "capabilities.v1.schema.json",
    version: "desktop.capabilities.v1",
    valid: ["valid-capabilities.json"],
    invalid: [],
    validate: tsContracts.validateCapabilities,
  },
  {
    schema: "storage-layout.v1.schema.json",
    version: "desktop.storage-layout.v1",
    valid: ["valid-storage-layout.json"],
    invalid: ["invalid-storage-program-files-writable.json"],
    validate: tsContracts.validateStorageLayout,
  },
  {
    schema: "update-state.v1.schema.json",
    version: "desktop.update-state.v1",
    valid: ["valid-update-interrupted.json"],
    invalid: ["invalid-update-non-atomic.json"],
    validate: tsContracts.validateUpdateState,
  },
];

for (const testCase of cases) {
  const schema = await readJson(path.join(schemaRoot, testCase.schema));
  assert.equal(schema.$schema, "https://json-schema.org/draft/2020-12/schema", testCase.schema + " draft");
  assert.equal(schema.$id, "https://schemas.aive.dev/desktop-v2/" + testCase.schema, testCase.schema + " id");
  assert.equal(schema.additionalProperties, false, testCase.schema + " must close its root object");
  assert.ok(schema.required?.includes("schemaVersion"), testCase.schema + " must require schemaVersion");
  for (const fixture of testCase.valid) {
    const value = await readJson(path.join(fixtureRoot, fixture));
    expectValid(fixture, schema, value);
    assert.equal(value.schemaVersion, testCase.version, fixture + " version");
    testCase.validate(value);
    testCase.validate(JSON.parse(JSON.stringify(value)));
  }
  for (const fixture of testCase.invalid) {
    const value = await readJson(path.join(fixtureRoot, fixture));
    expectInvalid(fixture, schema, value);
    assert.throws(() => testCase.validate(value), tsContracts.ContractValidationError, fixture + " should fail TypeScript validation");
  }
}

const storageFixture = await readJson(path.join(fixtureRoot, "valid-storage-layout.json"));
assert.deepEqual(tsContracts.canonicalWindowsStorageLayout(), storageFixture, "TypeScript canonical storage layout must match fixture");

console.log("Desktop V2 contract tests passed: " + cases.length + " schemas, " + cases.reduce((sum, item) => sum + item.valid.length + item.invalid.length, 0) + " fixtures");
