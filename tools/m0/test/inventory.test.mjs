import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { BUILTIN_RULES, buildInventory, runDiscovery, walkFiles } from "../inventory.mjs";

function makeFix() {
  const d = mkdtempSync(join(tmpdir(), "m0inv-"));
  mkdirSync(join(d, "ops"), { recursive: true });
  writeFileSync(join(d, "package.json"), JSON.stringify({ scripts: { test: "node --test", check: "node --check a.mjs" } }));
  writeFileSync(join(d, "run.sh"), "#!/bin/sh\necho hi\n");
  writeFileSync(join(d, "registry.mjs"), "const port = 17930;\nconst ADB = null;\n");
  writeFileSync(join(d, "ops", "x.mjs"), "export function f(){ return 22222; }\n");
  return d;
}

test("walkFiles lists files, excludes .git and node_modules", () => {
  const d = makeFix();
  try {
    mkdirSync(join(d, ".git"), { recursive: true });
    mkdirSync(join(d, "node_modules"), { recursive: true });
    writeFileSync(join(d, ".git", "HEAD"), "x");
    writeFileSync(join(d, "node_modules", "pkg.json"), "{}");
    const paths = [...walkFiles(d)];
    assert.ok(!paths.some((p) => p.startsWith(".git/")), "excludes .git");
    assert.ok(!paths.some((p) => p.startsWith("node_modules/")), "excludes node_modules");
    assert.ok(paths.some((p) => p === "package.json"));
  } finally {
    rmSync(d, { recursive: true, force: true });
  }
});

test("runDiscovery finds ports, package scripts, shebangs, ops, deviceControl refs", () => {
  const d = makeFix();
  try {
    const rules = ["ports", "packageScripts", "shebangs", "launcherScripts", "opsDir", "deviceControlEntry"];
    const { dimensions, fileCount } = runDiscovery(d, rules);
    assert.ok(fileCount >= 4);
    const byDim = new Map(dimensions.map((x) => [x.dimension, x.items]));
    // ports: registry.mjs has port 17930
    assert.ok(byDim.get("ports").some((h) => h.note.includes("17930")));
    // package scripts
    assert.ok(byDim.get("packageScripts").some((h) => h.locator.includes("scripts.test")));
    // shebang on run.sh
    assert.ok(byDim.get("shebangs").some((h) => h.locator === "run.sh"));
    // launcher script run.sh
    assert.ok(byDim.get("launcherScripts").some((h) => h.locator === "run.sh"));
    // ops dir
    assert.ok(byDim.get("opsDir").some((h) => h.locator === "ops/x.mjs"));
    // device control refs: ADB in registry.mjs, 22222 in ops/x.mjs
    const dc = byDim.get("deviceControlEntry");
    assert.ok(dc.some((h) => h.note === "ADB"));
    assert.ok(dc.some((h) => h.note === "22222"));
  } finally {
    rmSync(d, { recursive: true, force: true });
  }
});

test("buildInventory produces an inventory.v1-shaped object with unclassifiedCount 0", () => {
  const d = makeFix();
  try {
    const inv = buildInventory(d, ["ports", "opsDir"], { baselineId: "xw-m0-20260817-r0", name: "registry", capturedAt: "2026-08-17T00:00:00Z" });
    assert.equal(inv.schemaId, "xhs.m0.inventory.v1");
    assert.equal(inv.schemaVersion, 1);
    assert.equal(inv.unclassifiedCount, 0);
    assert.ok(Array.isArray(inv.repos));
    assert.equal(inv.repos[0].name, "registry");
  } finally {
    rmSync(d, { recursive: true, force: true });
  }
});

test("dimensions absent from a fixture are simply not present (honest absence)", () => {
  const d = mkdtempSync(join(tmpdir(), "m0inv2-"));
  try {
    writeFileSync(join(d, "a.txt"), "nothing interesting");
    const inv = buildInventory(d, ["ports", "deviceControlEntry"], { name: "registry" });
    const dims = inv.repos[0].dimensions.map((x) => x.dimension);
    assert.deepEqual(dims.sort(), ["deviceControlEntry", "ports"].sort());
    // both empty
    assert.equal(inv.repos[0].dimensions.find((x) => x.dimension === "ports").items.length, 0);
  } finally {
    rmSync(d, { recursive: true, force: true });
  }
});