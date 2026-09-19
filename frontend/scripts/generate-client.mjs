/**
 * Generate the API client's types from the API's own OpenAPI schema (R10.AC1).
 *
 * With --check it regenerates and fails if the committed file differs, so a backend change
 * that the frontend has not seen is a red build rather than a blank column (R10.AC2). This is
 * only possible because the schema and the client live in one repository (decision D16).
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const backend = resolve(root, "..", "backend");
const target = join(root, "src", "api", "schema.d.ts");
const check = process.argv.includes("--check");

const scratch = mkdtempSync(join(tmpdir(), "openapi-"));
const schemaPath = join(scratch, "openapi.json");

// The schema comes from the application itself, not from a running server, so generating it
// needs no database and no port.
execFileSync("uv", ["run", "python", "-m", "app.openapi", schemaPath], {
  cwd: backend,
  stdio: ["ignore", "inherit", "inherit"],
  env: { ...process.env, PYTHONPATH: "." },
});

const generated = execFileSync(
  "npx",
  ["openapi-typescript", schemaPath, "--root-types"],
  { cwd: root, encoding: "utf8", maxBuffer: 32 * 1024 * 1024 },
);

const banner = `/**
 * Generated from the API's OpenAPI schema. Do not edit by hand.
 *
 * Run \`npm run generate:client\` after changing an endpoint or a response model.
 * CI runs \`npm run check:client\`, which fails if this file and the API disagree.
 */
`;
const next = banner + generated;

if (check) {
  let current = "";
  try {
    current = readFileSync(target, "utf8");
  } catch {
    current = "";
  }
  if (current !== next) {
    console.error(
      "src/api/schema.d.ts is out of date with the API.\n" +
        "Run `npm run generate:client` and commit the result.",
    );
    process.exit(1);
  }
  console.log("API client types match the API's schema.");
} else {
  writeFileSync(target, next);
  console.log(`Wrote ${target}`);
}
