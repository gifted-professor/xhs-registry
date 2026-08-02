import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";
import {
  KNOWLEDGE_FIELDS,
  discoverBundleDirs,
  envelopesEqual,
  loadCommittedProposalCatalog,
  proposalForBundle,
  publishEnvelope,
  readSkillBinding,
  scanAndPublish,
} from "../scripts/auto-review-publish.mjs";
import { proposalKnowledgeEnvelope } from "../scripts/lib/repair-proposal.mjs";

const root = resolve(new URL("..", import.meta.url).pathname);
const bundle = join(root, "tmp-know/review-bundles/p78-feed-loop-20260802");
const bundlesRoot = join(root, "tmp-know/review-bundles");
const skillPath = join(root, "skills/xhs/xhs-observe-feed/SKILL.md");
const committedPath = join(root, "docs/handoffs/2026-08-02-xhs-observe-feed-repair-proposal.v1.json");
const expected = JSON.parse(readFileSync(committedPath, "utf8"));

function fakeTransport(initial = null, postStatus = 201) {
  let stored = initial;
  let posts = 0;
  return {
    get posts() { return posts; },
    get: async () => stored ? { status: 200, body: { ok: true, knowledge: stored } } : { status: 404, body: { ok: false } },
    post: async (envelope) => {
      posts += 1;
      if (postStatus === 201) stored = envelope;
      return postStatus === 201
        ? { status: 201, body: { ok: true, knowledge: envelope } }
        : { status: postStatus, body: { ok: false } };
    },
  };
}

test("sealed aggregate bundle resolves to the exact committed proposal", () => {
  const skillBinding = readSkillBinding(skillPath);
  const committed = loadCommittedProposalCatalog([committedPath]);
  assert.deepEqual(proposalForBundle(bundle, { skillBinding, committed }), [expected]);
  assert.equal(skillBinding.version, "0.1");
  assert.equal(skillBinding.sourceSha256, "2baba76b8c9c877c1f63e2a824096c2065f90031db119238a6e33bf864e9720d");
});

test("dry run reviews but never posts", async () => {
  const transport = fakeTransport();
  const summary = await scanAndPublish({ bundlesRoot, skillPath, committedProposalPaths: [committedPath], transport, publish: false });
  assert.equal(summary.ok, true);
  assert.equal(summary.proposalCount, 1);
  assert.equal(summary.results[0].status, "dry_run");
  assert.equal(transport.posts, 0);
});

test("first publication is created and the next scan is idempotent", async () => {
  const envelope = proposalKnowledgeEnvelope(expected);
  const transport = fakeTransport();
  assert.equal((await publishEnvelope(envelope, transport, { publish: true })).status, "published");
  assert.equal((await publishEnvelope(envelope, transport, { publish: true })).status, "already_present");
  assert.equal(transport.posts, 1);
});

test("409 after another writer committed reconciles only exact content", async () => {
  const envelope = proposalKnowledgeEnvelope(expected);
  let calls = 0;
  const transport = {
    get: async () => (++calls === 1 ? { status: 404, body: {} } : { status: 200, body: { knowledge: envelope } }),
    post: async () => ({ status: 409, body: {} }),
  };
  assert.equal((await publishEnvelope(envelope, transport, { publish: true })).status, "reconciled");
});

test("existing knowledge mismatch in every transport field fails closed", async () => {
  const envelope = proposalKnowledgeEnvelope(expected);
  for (const field of KNOWLEDGE_FIELDS) {
    const altered = structuredClone(envelope);
    altered[field] = Array.isArray(altered[field]) ? [...altered[field], "changed"]
      : typeof altered[field] === "boolean" ? !altered[field]
        : `${altered[field]}-changed`;
    assert.equal(envelopesEqual(altered, envelope), false, field);
    await assert.rejects(
      publishEnvelope(envelope, fakeTransport(altered), { publish: true }),
      new RegExp(`KNOWLEDGE_CONTENT_CONFLICT:${expected.proposalId}`),
    );
  }
});

test("registry failure is reported as publication debt without changing proposal", async () => {
  const before = JSON.stringify(expected);
  const summary = await scanAndPublish({
    bundlesRoot,
    skillPath,
    committedProposalPaths: [committedPath],
    publish: true,
    transport: { get: async () => ({ status: 503, body: {} }), post: async () => assert.fail("must not post") },
  });
  assert.equal(summary.ok, false);
  assert.match(summary.errors[0].code, /KNOWLEDGE_READ_FAILED/);
  assert.equal(JSON.stringify(expected), before);
});

test("bundle discovery rejects symlinks", () => {
  const temp = mkdtempSync(join(tmpdir(), "repair-review-"));
  mkdirSync(join(temp, "real"));
  symlinkSync(join(temp, "real"), join(temp, "alias"));
  assert.throws(() => discoverBundleDirs(temp), /BUNDLE_SYMLINK_FORBIDDEN/);
});

test("bundle without an immutable timestamp is rejected before review", async () => {
  const temp = mkdtempSync(join(tmpdir(), "repair-review-"));
  const bad = join(temp, "bad-bundle");
  mkdirSync(bad);
  writeFileSync(join(bad, "manifest.json"), JSON.stringify({ bundleId: "bad" }));
  const summary = await scanAndPublish({
    bundlesRoot: temp,
    skillPath,
    committedProposalPaths: [],
    transport: fakeTransport(),
    publish: true,
  });
  assert.equal(summary.ok, false);
  assert.match(summary.errors[0].code, /STABLE_REVIEW_TIMESTAMP_REQUIRED/);
  assert.equal(summary.results.length, 0);
});
