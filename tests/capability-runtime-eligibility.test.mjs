import assert from "node:assert/strict";
import test from "node:test";

import {
  isAdvisorySafeTypedJob,
  supportsTypedJob,
} from "../scripts/lib/capability-runtime-eligibility.mjs";

test("deployed-runtime catalog null authorization hints do not hide safe typed jobs", () => {
  const capability = {
    id: "xhs.publish.edit_dry_run",
    idempotency: "replay_safe",
    policy: {
      availability: "implemented",
      externalEffect: false,
      approvalRequired: null,
      runnableAsJob: null,
      implementationSupport: { job: true, canarySession: false },
    },
  };

  assert.equal(supportsTypedJob(capability), true);
  assert.equal(isAdvisorySafeTypedJob(capability), true);
});

test("advisory eligibility still rejects external, lab, canary, and unsafe jobs", () => {
  const base = {
    idempotency: "replay_safe",
    policy: {
      availability: "implemented",
      externalEffect: false,
      implementationSupport: { job: true },
    },
  };

  assert.equal(isAdvisorySafeTypedJob({ ...base, policy: { ...base.policy, externalEffect: true } }), false);
  assert.equal(isAdvisorySafeTypedJob({ ...base, policy: { ...base.policy, labOnly: true } }), false);
  assert.equal(isAdvisorySafeTypedJob({ ...base, policy: { ...base.policy, canaryRequired: true } }), false);
  assert.equal(isAdvisorySafeTypedJob({ ...base, idempotency: "ambiguous_on_timeout" }), false);
  assert.equal(isAdvisorySafeTypedJob({ ...base, policy: { ...base.policy, implementationSupport: { job: false } } }), false);
});
