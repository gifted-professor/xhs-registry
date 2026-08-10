/**
 * Static job support and advisory-safe eligibility from the public registry
 * catalog. Authorization fields are deliberately excluded: since runtime
 * policy v1 they are null in the catalog and only Control Plane may decide.
 */

export function supportsTypedJob(capability) {
  const policy = capability?.policy || {};
  return policy.implementationSupport?.job === true || policy.runnableAsJob === true;
}

export function isAdvisorySafeTypedJob(capability) {
  const policy = capability?.policy || {};
  return policy.availability === "implemented"
    && supportsTypedJob(capability)
    && policy.externalEffect === false
    && policy.disabled !== true
    && policy.labOnly !== true
    && policy.canaryRequired !== true
    && ["read_only", "replay_safe"].includes(capability?.idempotency);
}
