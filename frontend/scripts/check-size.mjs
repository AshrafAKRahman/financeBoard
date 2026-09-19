/**
 * Keep the first load inside its budget (NFR2).
 *
 * Only what the browser must fetch before it can show anything counts: the entry chunk, the
 * chunks it statically imports, and its CSS. The report screens are loaded lazily and are
 * deliberately excluded — that is what makes the budget affordable while using Ant Design.
 */
import { gzipSync } from "node:zlib";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";

const BUDGET_KB = 400;

const dist = resolve(import.meta.dirname, "..", "dist");
const manifest = JSON.parse(readFileSync(join(dist, ".vite", "manifest.json"), "utf8"));

const entry = Object.values(manifest).find((chunk) => chunk.isEntry);
if (!entry) {
  console.error("No entry chunk in the build manifest.");
  process.exit(1);
}

/** The entry, everything it imports statically, and their stylesheets. */
const initial = new Set();
const walk = (key) => {
  const chunk = manifest[key];
  if (!chunk || initial.has(chunk.file)) {
    return;
  }
  initial.add(chunk.file);
  for (const css of chunk.css ?? []) {
    initial.add(css);
  }
  for (const imported of chunk.imports ?? []) {
    walk(imported);
  }
};
walk(Object.keys(manifest).find((key) => manifest[key].isEntry));

let total = 0;
const rows = [];
for (const file of initial) {
  const bytes = gzipSync(readFileSync(join(dist, file))).length;
  total += bytes;
  rows.push([file, bytes]);
}

rows.sort((a, b) => b[1] - a[1]);
for (const [file, bytes] of rows) {
  console.log(`  ${(bytes / 1024).toFixed(1).padStart(7)} kB  ${file}`);
}

const kb = total / 1024;
console.log(`\nFirst load: ${kb.toFixed(1)} kB gzipped (budget ${BUDGET_KB} kB)`);

if (kb > BUDGET_KB) {
  console.error(
    `\nOver budget by ${(kb - BUDGET_KB).toFixed(1)} kB.\n` +
      "Load more of the screen lazily, or import less of Ant Design.",
  );
  process.exit(1);
}
