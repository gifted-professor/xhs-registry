// M0 inventory discoverer (M0-A). Read-only: walks files, applies dimension rules,
// classifies findings. Does not run anything. A dimension rule is a function
// (fileRelPath, text) => Finding[] or a declarative {dimension, test} spec.
//
// The discovery SCOPE (which dimensions, which inputs, which exclusions) is fixed
// in inventory-coverage.v1.json (A3). This engine is dimension-agnostic; the A3
// coverage config supplies the rules. Dimensions absent from a repo are recorded
// honestly as empty arrays, not omitted (e.g. ADB/22222 entrypoints don't exist in
// registry executable code).

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const DEFAULT_EXCLUDE_DIRS = new Set([
  ".git", "node_modules", ".cache", "tmp", "temp",
]);

/** Walk a root, yielding posix relative paths of files (excluding default dirs). */
export function* walkFiles(root, excludeDirs = DEFAULT_EXCLUDE_DIRS) {
  const stack = [""];
  while (stack.length) {
    const rel = stack.pop();
    const abs = join(root, rel);
    let st;
    try { st = statSync(abs); } catch { continue; }
    if (st.isDirectory()) {
      const name = rel ? rel.replace(/.*\//, "") : "";
      if (rel && excludeDirs.has(name)) continue;
      for (const e of readdirSync(abs)) {
        stack.push(rel ? `${rel}/${e}` : e);
      }
    } else if (st.isFile()) {
      yield rel.replace(/\\/g, "/");
    }
  }
}

/** Built-in dimension rules: each returns {dimension, locator, classification, note?}. */
export const BUILTIN_RULES = {
  ports: (rel, text) => {
    const hits = [];
    const re = /\b(?:port|PORT|listen|bind|--port)\b[^0-9]*(\d{4,5})\b/g;
    let m;
    while ((m = re.exec(text))) {
      hits.push({ dimension: "ports", locator: `${rel}:${m.index}`, classification: "listenOrPortRef", note: `port ${m[1]}` });
    }
    return hits;
  },
  packageScripts: (rel, text) => {
    if (!rel.endsWith("package.json")) return [];
    try {
      const p = JSON.parse(text);
      const out = [];
      for (const k of Object.keys(p.scripts || {})) {
        out.push({ dimension: "packageScripts", locator: `${rel}:scripts.${k}`, classification: "npmScript", note: p.scripts[k] });
      }
      return out;
    } catch { return []; }
  },
  shebangs: (rel, text) => {
    if (text.startsWith("#!")) {
      return [{ dimension: "shebangs", locator: rel, classification: "shebangScript", note: text.split(/\r?\n/)[0] }];
    }
    return [];
  },
  launcherScripts: (rel) => {
    if (/\.(cmd|ps1|sh|bat)$/i.test(rel)) {
      return [{ dimension: "launcherScripts", locator: rel, classification: "launcherScript", note: "" }];
    }
    return [];
  },
  opsDir: (rel) => {
    if (rel.startsWith("ops/") && rel.endsWith(".mjs")) {
      return [{ dimension: "opsDir", locator: rel, classification: "opsModule", note: "" }];
    }
    return [];
  },
  // ADB / 22222 / FastOperator / GatewayOperator static entrypoints — these are
  // ABSENT in registry executable code (they live in device-agent). The rule surfaces
  // any textual reference so the inventory can honestly record presence/absence.
  deviceControlEntry: (rel, text) => {
    const re = /\b(?:22222|ADB|adb|FastOperator|GatewayOperator)\b/g;
    const hits = [];
    let m;
    while ((m = re.exec(text))) {
      hits.push({ dimension: "deviceControlEntry", locator: `${rel}:${m.index}`, classification: "deviceControlRef", note: m[0] });
    }
    return hits;
  },
};

/**
 * Run discovery over a root with a set of dimension rules (names of BUILTIN_RULES
 * or custom functions). Returns findings grouped by dimension, plus the file count
 * scanned. read-only.
 * @param {string} root
 * @param {(string|Function)[]} rules
 * @param {{excludeDirs?:Set<string>, maxBytes?:number}} [opts]
 */
export function runDiscovery(root, rules, opts = {}) {
  const maxBytes = opts.maxBytes ?? 2_000_000;
  const exclude = opts.excludeDirs ?? DEFAULT_EXCLUDE_DIRS;
  const byDim = new Map();
  // Pre-seed every named builtin dimension so honest absence is recorded as an
  // empty array, not omitted (plan: "Dimensions absent from a repo are recorded
  // honestly as empty, not omitted").
  for (const rule of rules) {
    if (typeof rule === "string" && BUILTIN_RULES[rule]) byDim.set(rule, []);
  }
  let fileCount = 0;
  for (const rel of walkFiles(root, exclude)) {
    fileCount++;
    let text = "";
    try {
      const abs = join(root, rel);
      if (statSync(abs).size > maxBytes) continue;
      text = readFileSync(abs, "utf8");
    } catch { continue; }
    for (const rule of rules) {
      const fn = typeof rule === "function" ? rule : BUILTIN_RULES[rule];
      if (!fn) continue;
      let hits;
      try { hits = fn(rel, text) || []; } catch { hits = []; }
      for (const h of hits) {
        if (!byDim.has(h.dimension)) byDim.set(h.dimension, []);
        byDim.get(h.dimension).push(h);
      }
    }
  }
  const dimensions = [...byDim.entries()]
    .map(([dimension, items]) => ({ dimension, items }))
    .sort((a, b) => (a.dimension < b.dimension ? -1 : 1));
  return { fileCount, dimensions };
}

/**
 * Build an inventory.v1 object from discovery, classifying all findings.
 * unclassifiedCount is the count of findings whose classification === "unclassified".
 * The A3 validator checks discoverySet - classifiedSet = 0.
 */
export function buildInventory(root, rules, meta = {}) {
  const { fileCount, dimensions } = runDiscovery(root, rules, meta.opts);
  const unclassifiedCount = dimensions
    .flatMap((d) => d.items)
    .filter((i) => i.classification === "unclassified").length;
  return {
    schemaId: "xhs.m0.inventory.v1",
    schemaVersion: 1,
    baselineId: meta.baselineId || "",
    capturedAt: meta.capturedAt || new Date(0).toISOString(),
    coverageRef: meta.coverageRef || "inventory-coverage.v1.json",
    repos: [{ name: meta.name || "registry", dimensions }],
    unclassifiedCount,
    _fileCount: fileCount, // diagnostic, stripped before validation if needed
  };
}