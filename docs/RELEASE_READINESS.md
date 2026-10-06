# First Public Release Readiness

This checklist defines the minimum bar for the first tagged public release of Universal Brain.

The first release must be framed as a **software/architecture checkpoint**. It must not imply that Windows, WSL2/Hyper-V isolation, Ollama pressure handling, long-duration endurance, or general autonomous engineering capability has been production-proven unless exact target-machine evidence exists on the release commit.

## Required before tagging

- [ ] CI / regression gates required by the repository are green on the exact release commit.
- [ ] Python compilation/package validation succeeds on the exact release commit.
- [ ] README maturity statements match the current code and evidence.
- [ ] No local-only `file:///` links or machine-specific private paths remain in public documentation.
- [ ] Public architecture/security links resolve inside the repository.
- [ ] `LICENSE` is present and matches the intended source-visible, all-rights-reserved status.
- [ ] Release notes distinguish implemented checkpoints from target-machine proof.
- [ ] Any target-machine evidence cited by the release is committed or otherwise reproducibly referenced with provenance.
- [ ] Unverified Windows/WSL2/Ollama/endurance claims remain explicitly excluded.

## Allowed first-release claims

The release may describe, when supported by the exact release commit and its test records:

- deterministic executive/control-plane architecture;
- authority-gated Tool Gateway contracts;
- durable mission/checkpoint mechanics;
- multi-model routing and council abstractions;
- engineering-agency planning/recovery infrastructure;
- semantic/LSP integration contracts and environment-dependent adapters;
- worker/service durability mechanisms;
- target-machine validation tooling and evidence-sealing workflow.

## Claims that remain blocked without target evidence

Do not claim any of the following solely from software tests or harness availability:

- production-proven Windows sandboxing;
- production-proven WSL2/Hyper-V isolation;
- multi-hour autonomous reliability;
- universal exactly-once external action execution;
- validated performance across arbitrary local models;
- production-scale autonomous completion of large software systems;
- physical-world autonomy or safety certification.

## Promotion rule

Create the tag only from a clean commit whose required verification gates are green. The release body must link to the exact verification record and preserve all evidence boundaries.