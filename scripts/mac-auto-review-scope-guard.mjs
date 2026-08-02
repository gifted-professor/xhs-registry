#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const scope = JSON.parse(readFileSync(resolve(repoRoot, "docs/plans/2026-08-02-mac-auto-review-publisher.files.json"), "utf8"));
const repoScope = scope.repositories.A;

function git(...args) {
  const result = spawnSync("git", args, { cwd: repoRoot, encoding: "utf8" });
  if (result.status !== 0) throw new Error(result.stderr.trim() || `git ${args.join(" ")} failed`);
  return result.stdout.split(/\r?\n/).filter(Boolean);
}

function main() {
  if (!/^[0-9a-f]{40}$/.test(repoScope.baseline)) throw new Error("invalid scope baseline");
  git("cat-file", "-e", `${repoScope.baseline}^{commit}`);
  const allowed = new Set(repoScope.allowedFiles);
  if (allowed.size !== repoScope.allowedFiles.length) throw new Error("duplicate allowed file");
  const changed = new Set([
    ...git("diff", "--name-only", repoScope.baseline, "--"),
    ...git("diff", "--name-only", "--cached", "--"),
    ...git("diff", "--name-only", "--"),
    ...git("ls-files", "--others", "--exclude-standard"),
  ]);
  const outside = [...changed].filter((path) => !allowed.has(path)).sort();
  if (outside.length) throw new Error(`scope violation: ${outside.join(", ")}`);
  for (const forbidden of repoScope.forbiddenFiles) if (allowed.has(forbidden)) throw new Error(`forbidden file allowlisted: ${forbidden}`);
  console.log(JSON.stringify({ ok: true, baseline: repoScope.baseline, files: [...changed].sort() }));
}

try { main(); } catch (error) { console.error(error.message); process.exitCode = 2; }
