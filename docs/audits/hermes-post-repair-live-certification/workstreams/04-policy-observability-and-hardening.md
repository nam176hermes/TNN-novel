# Future workstream 4: policy messaging, alert delivery, and bounded hardening

## Objective

Align TTS UI text with GPU-only policy, demonstrate one external alert path, and resolve the token-like file only after proving its purpose and reachability.

## Included issues

- `TTS-UI-004`
- `OBS-ALERT-006`
- `SEC-FILE-008`

## Excluded scope

No CPU synthesis, live GPU synthesis, provider signup, external post, file deletion, permission change, or production monitoring rollout without approval.

## Dependencies

TTS unavailable copy tests, operational alert schema, operator-selected delivery channel, and read-only file ownership analysis.

## Implementation phases

1. Add an exact policy-copy test and remove CPU guidance.
2. Select one bounded notifier and define redaction and retry contracts.
3. Send a controlled test only after explicit approval and preserve its receipt.
4. Trace the token-like file producer and consumers without reading its secret value.
5. Propose permission or cleanup action with rollback evidence.
6. Return HANDOFF before external or destructive action.

## Test gates

Frontend tests, all TTS no-fallback tests, alert redaction and retry tests, controlled delivery receipt, file reachability analysis, full verification.

## Approval gates

External alert post, paid signup, GPU synthesis, `chmod`, `chown`, deletion, restart, merge, and deploy require explicit approval.

## Rollback

Restore previous UI copy, disable the new notifier through its documented safe switch, and restore file metadata from a recorded snapshot if an approved permission change is reverted.

## Commit strategy

One UI test and copy commit, one notifier contract commit, and a separate evidence-only hardening decision.

## Definition of Done

UI never recommends CPU TTS, one alert reaches the approved channel with no private data, and the token-like file is either justified and protected or removed through an approved reversible procedure.
