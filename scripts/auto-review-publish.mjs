#!/usr/bin/env node
import { createHash } from "node:crypto";
import { existsSync, lstatSync, readFileSync, readdirSync, realpathSync } from "node:fs";
import { basename, dirname, join, relative, resolve, sep } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { canonicalJson, proposalKnowledgeEnvelope, validateRepairProposal } from "./lib/repair-proposal.mjs";
import { reviewRunBundle } from "./review-run-bundle.mjs";

export const KNOWLEDGE_FIELDS = Object.freeze([
  "id", "scope", "app", "category", "title", "content", "verifiedBy", "needsEngineer",
  "appliesTo", "steps", "verifyMode", "lifecycle",
]);

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function parseJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function isWithin(root, path) {
  const rel = relative(root, path);
  return rel === "" || (!rel.startsWith(`..${sep}`) && rel !== "..");
}

export function discoverBundleDirs(root) {
  const lexicalRoot = resolve(root);
  const actualRoot = realpathSync(lexicalRoot);
  return readdirSync(lexicalRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() || entry.isSymbolicLink())
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((entry) => {
      const candidate = join(lexicalRoot, entry.name);
      if (lstatSync(candidate).isSymbolicLink()) throw new Error(`BUNDLE_SYMLINK_FORBIDDEN:${entry.name}`);
      const actual = realpathSync(candidate);
      if (!isWithin(actualRoot, actual)) throw new Error(`BUNDLE_ESCAPE_FORBIDDEN:${entry.name}`);
      return actual;
    });
}

export function stableReviewTimestamp(bundleDir) {
  const receiptPath = join(bundleDir, "mac-review", "mac-independent-review-receipt.json");
  const manifestPath = join(bundleDir, "manifest.json");
  const values = [];
  if (existsSync(receiptPath)) values.push(parseJson(receiptPath).reviewedAt);
  if (existsSync(manifestPath)) {
    const manifest = parseJson(manifestPath);
    values.push(manifest.endedAt, manifest.producedAt, manifest.startedAt);
  }
  const timestamp = values.find((value) => typeof value === "string" && Number.isFinite(Date.parse(value)));
  if (!timestamp) throw new Error(`STABLE_REVIEW_TIMESTAMP_REQUIRED:${basename(bundleDir)}`);
  return new Date(timestamp).toISOString();
}

export function readSkillBinding(skillPath) {
  const bytes = readFileSync(skillPath);
  const text = bytes.toString("utf8");
  const match = text.match(/^---\s*\n[\s\S]*?^version:\s*["']?([^"'\n]+)["']?\s*$[\s\S]*?^---\s*$/m);
  if (!match) throw new Error(`SKILL_VERSION_REQUIRED:${skillPath}`);
  return { path: relative(resolve(dirname(fileURLToPath(import.meta.url)), ".."), resolve(skillPath)).replaceAll("\\", "/"), version: match[1].trim(), sourceSha256: sha256(bytes) };
}

export function loadCommittedProposalCatalog(paths) {
  const catalog = new Map();
  for (const path of paths.filter(Boolean)) {
    if (!existsSync(path)) continue;
    const proposal = parseJson(path);
    const validation = validateRepairProposal(proposal);
    if (!validation.ok) throw new Error(`COMMITTED_PROPOSAL_INVALID:${path}:${validation.errors.join(";")}`);
    if (catalog.has(proposal.proposalId)) throw new Error(`DUPLICATE_COMMITTED_PROPOSAL:${proposal.proposalId}`);
    catalog.set(proposal.proposalId, proposal);
  }
  return catalog;
}

function sameImmutableSource(a, b) {
  return a.proposalId === b.proposalId
    && a.idempotencyKey === b.idempotencyKey
    && a.source.manifestSha256 === b.source.manifestSha256
    && a.source.review.receiptSha256 === b.source.review.receiptSha256;
}

export function proposalForBundle(bundleDir, { skillBinding, committed = new Map() }) {
  const reviewedAt = stableReviewTimestamp(bundleDir);
  const result = reviewRunBundle(bundleDir, { reviewedAt, targetSkillBinding: skillBinding });
  return result.repairProposals.map((generated) => {
    const frozen = committed.get(generated.proposalId);
    if (!frozen) return generated;
    if (!sameImmutableSource(frozen, generated)) throw new Error(`COMMITTED_PROPOSAL_BINDING_CONFLICT:${generated.proposalId}`);
    return frozen;
  });
}

function normalizedEnvelope(value) {
  const item = value?.knowledge ?? value;
  return Object.fromEntries(KNOWLEDGE_FIELDS.map((key) => [key, key === "content" && typeof item?.[key] !== "string" ? canonicalJson(item?.[key]) : item?.[key]]));
}

export function envelopesEqual(a, b) {
  return canonicalJson(normalizedEnvelope(a)) === canonicalJson(normalizedEnvelope(b));
}

export async function publishEnvelope(envelope, transport, { publish = false } = {}) {
  if (!publish) return { proposalId: envelope.id, status: "dry_run" };
  const existing = await transport.get(envelope.id);
  if (existing.status === 200) {
    if (!envelopesEqual(existing.body, envelope)) throw new Error(`KNOWLEDGE_CONTENT_CONFLICT:${envelope.id}`);
    return { proposalId: envelope.id, status: "already_present" };
  }
  if (existing.status !== 404) throw new Error(`KNOWLEDGE_READ_FAILED:${envelope.id}:${existing.status}`);
  const created = await transport.post(envelope);
  if (created.status === 201) {
    if (!envelopesEqual(created.body, envelope)) throw new Error(`KNOWLEDGE_POST_RESPONSE_CONFLICT:${envelope.id}`);
    return { proposalId: envelope.id, status: "published" };
  }
  if (created.status === 409) {
    const reconciled = await transport.get(envelope.id);
    if (reconciled.status === 200 && envelopesEqual(reconciled.body, envelope)) return { proposalId: envelope.id, status: "reconciled" };
    throw new Error(`KNOWLEDGE_CONTENT_CONFLICT:${envelope.id}`);
  }
  throw new Error(`KNOWLEDGE_POST_FAILED:${envelope.id}:${created.status}`);
}

export async function scanAndPublish({ bundlesRoot, skillPath, committedProposalPaths = [], transport, publish = false }) {
  const skillBinding = readSkillBinding(skillPath);
  const committed = loadCommittedProposalCatalog(committedProposalPaths);
  const proposals = [];
  const errors = [];
  for (const bundleDir of discoverBundleDirs(bundlesRoot)) {
    try {
      proposals.push(...proposalForBundle(bundleDir, { skillBinding, committed }));
    } catch (error) {
      errors.push({ bundle: basename(bundleDir), code: String(error.message) });
    }
  }
  const unique = new Map();
  for (const proposal of proposals) {
    const previous = unique.get(proposal.proposalId);
    if (previous && canonicalJson(previous) !== canonicalJson(proposal)) errors.push({ bundle: proposal.source.bundleId, code: `PROPOSAL_ID_CONFLICT:${proposal.proposalId}` });
    else unique.set(proposal.proposalId, proposal);
  }
  const results = [];
  for (const proposal of unique.values()) {
    try {
      results.push(await publishEnvelope(proposalKnowledgeEnvelope(proposal), transport, { publish }));
    } catch (error) {
      errors.push({ bundle: proposal.source.bundleId, proposalId: proposal.proposalId, code: String(error.message) });
    }
  }
  return { ok: errors.length === 0, publish, scannedBundles: discoverBundleDirs(bundlesRoot).length, proposalCount: unique.size, results, errors };
}

function powershellEncoded(script) {
  return Buffer.from(script, "utf16le").toString("base64");
}

export function createSshKnowledgeTransport({ host = "xhs-windows", endpoint = "http://127.0.0.1:17930" } = {}) {
  const invoke = (method, path, body) => {
    const body64 = body === undefined ? "" : Buffer.from(JSON.stringify(body), "utf8").toString("base64");
    const ps = [
      "$ErrorActionPreference='Stop'",
      `$u='${endpoint}${path.replaceAll("'", "''")}'`,
      body === undefined ? "$b=$null" : `$b=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${body64}'))`,
      "try {",
      body === undefined
        ? `$r=Invoke-WebRequest -UseBasicParsing -Method ${method} -Uri $u`
        : `$r=Invoke-WebRequest -UseBasicParsing -Method ${method} -Uri $u -ContentType 'application/json' -Body $b`,
      "$s=[int]$r.StatusCode; $c=$r.Content",
      "} catch { if ($_.Exception.Response) { $s=[int]$_.Exception.Response.StatusCode; $rd=New-Object IO.StreamReader($_.Exception.Response.GetResponseStream()); $c=$rd.ReadToEnd() } else { throw } }",
      "[Console]::Out.Write(($s.ToString())+'\n'+$c)",
    ].join("; ");
    const result = spawnSync("ssh", [host, "powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", powershellEncoded(ps)], { encoding: "utf8", timeout: 20000 });
    if (result.status !== 0) throw new Error(`REGISTRY_TRANSPORT_FAILED:${result.stderr.trim() || result.error?.message || result.status}`);
    const split = result.stdout.indexOf("\n");
    const status = Number(result.stdout.slice(0, split).trim());
    const raw = split >= 0 ? result.stdout.slice(split + 1).trim() : "";
    let parsed = {};
    if (raw) {
      try { parsed = JSON.parse(raw); } catch { throw new Error(`REGISTRY_RESPONSE_MALFORMED:${status}`); }
    }
    return { status, body: parsed };
  };
  return {
    get: async (id) => invoke("GET", `/api/knowledge/${encodeURIComponent(id)}`),
    post: async (envelope) => invoke("POST", "/api/knowledge", envelope),
  };
}

function flag(args, name, fallback) {
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : fallback;
}

const invoked = process.argv[1] ? resolve(process.argv[1]) : null;
if (invoked === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  const bundlesRoot = resolve(flag(args, "--bundles-root", join(repoRoot, "tmp-know", "review-bundles")));
  const skillPath = resolve(flag(args, "--skill-source", join(repoRoot, "skills", "xhs", "xhs-observe-feed", "SKILL.md")));
  const proposalPath = resolve(flag(args, "--proposal-file", join(repoRoot, "docs", "handoffs", "2026-08-02-xhs-observe-feed-repair-proposal.v1.json")));
  const publish = args.includes("--publish");
  try {
    const summary = await scanAndPublish({
      bundlesRoot,
      skillPath,
      committedProposalPaths: [proposalPath],
      transport: createSshKnowledgeTransport({ host: flag(args, "--ssh-host", "xhs-windows") }),
      publish,
    });
    console.log(JSON.stringify(summary, null, 2));
    if (!summary.ok) process.exitCode = 2;
  } catch (error) {
    console.error(JSON.stringify({ ok: false, error: error.message }));
    process.exitCode = 2;
  }
}
