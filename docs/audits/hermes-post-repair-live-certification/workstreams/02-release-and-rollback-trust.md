# Future workstream 2: release and rollback trust

## Objective

Make the canonical runbook, overlays, runtime version payload, and release record identify the same current and previous releases.

## Included issues

- `OPS-RUNBOOK-002`
- `OPS-PROV-005`

## Excluded scope

No image rebuild, registry push, service restart, rollback execution, merge, tag, or release publication.

## Dependencies

Current API and worker image IDs, release SHA, current overlay, immediate previous overlay, and canonical runbook.

## Implementation phases

1. Add a consistency test for runbook overlay variables and release record.
2. Update current and rollback examples to Upgrade B identities.
3. Decide whether immutable local image ID or registry digest is the supported version-payload field.
4. Add identity tests without leaking registry credentials.
5. Render Compose with `config --quiet` and `config --images` only.
6. Return HANDOFF before any deployment action.

## Test gates

Documentation contract, runtime identity tests, Compose render, source-image comparison, `git diff --check`, full verification.

## Approval gates

Protected Compose edits, image rebuild, restart, rollback, push, merge, and release publication require explicit approval.

## Rollback

Revert the documentation and identity commits. No running service changes occur in this workstream.

## Commit strategy

One contract-test commit and one documentation or bounded identity commit.

## Definition of Done

Canonical commands select the current release and immediate previous rollback, rendering is deterministic, version identity is complete or explicitly documented, and no runtime action was performed.
