# Workstream 4: Python Advisory Remediation

Goal: Remove fixed Python advisories and prove whether ECDSA is reachable.

Scope:
- Upgrade pytest to a fixed compatible version.
- Upgrade setuptools to a fixed compatible version.
- Trace all imports and runtime paths to `ecdsa`.
- Confirm production JWT signing algorithm and reject accidental ECDSA activation.
- Replace or isolate ECDSA only if reachable.

Required verification: pip audit, dependency consistency, full backend suite, authentication tests, container build, and runtime smoke.

Do not silence advisories or remove tests to obtain a green result.
