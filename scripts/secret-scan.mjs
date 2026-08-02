#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const scope = JSON.parse(readFileSync(resolve(root, "docs/plans/2026-08-02-mac-auto-review-publisher.files.json"), "utf8"));
const changed = spawnSync("git", ["diff", "--name-only", scope.repositories.A.baseline, "--"], { cwd: root, encoding: "utf8" });
if (changed.status !== 0) throw new Error(changed.stderr);
const untracked = spawnSync("git", ["ls-files", "--others", "--exclude-standard"], { cwd: root, encoding: "utf8" });
if (untracked.status !== 0) throw new Error(untracked.stderr);
const patterns = [
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/,
  /\b(?:ghp|github_pat|sk)-[A-Za-z0-9_-]{20,}\b/,
  /\b(?:api[_-]?key|token|secret)\s*[:=]\s*["'][^"']{16,}["']/i,
];
const findings = [];
const files = new Set(`${changed.stdout}\n${untracked.stdout}`.split(/\r?\n/).filter(Boolean));
for (const path of files) {
  let text;
  try { text = readFileSync(resolve(root, path), "utf8"); } catch { continue; }
  text.split(/\r?\n/).forEach((line, index) => {
    if (patterns.some((pattern) => pattern.test(line))) findings.push(`${path}:${index + 1}`);
  });
}
if (findings.length) {
  console.error(`secret scan failed: ${findings.join(", ")}`);
  process.exitCode = 2;
} else console.log("secret-scan passed");
