# Contributing to Universal Brain

Universal Brain is a systems-engineering project with explicit authority, evidence, and verification boundaries. Contributions are welcome, but they should preserve those boundaries rather than bypass them for convenience.

## Good contribution areas

- tests and deterministic reproduction cases
- documentation and architecture clarification
- local-model adapters and diagnostics
- failure recovery and persistence
- semantic code intelligence
- safe tooling and Tool Gateway integrations
- benchmark/evidence tooling
- Windows, WSL2, and cross-platform validation
- observability and operator-console improvements

## Before implementing

1. Open or reference an issue.
2. Keep the change scoped to one clear problem.
3. Identify any affected requirements, invariants, ADRs, or authority boundaries.
4. Do not silently broaden action authority.
5. Do not convert mock/simulation/software evidence into a real-environment claim.

## Pull request expectations

- explain the problem and design choice;
- list the validation performed;
- add or update tests where practical;
- identify migrations or compatibility effects;
- identify security/authority effects explicitly;
- update documentation when contracts change;
- preserve reproducible evidence for new benchmark or environment claims.

## Evidence language

Use precise labels:

- **implemented** — code exists;
- **unit/integration verified** — automated software tests pass;
- **mock verified** — external behavior is simulated;
- **target-machine verified** — executed on the documented real environment;
- **physical verified** — measured on actual physical hardware where applicable.

Do not collapse these categories into a broader claim.

## First-time contributors

Documentation, tests, diagnostics, reproducibility helpers, and narrowly scoped reliability improvements are good entry points. Look for issues labeled `good first issue` or `help wanted`.

## Security

Do not include credentials, private data, access tokens, or secrets in issues, logs, fixtures, or evidence bundles. Security-sensitive reports should avoid publishing an immediately exploitable secret or private credential.
