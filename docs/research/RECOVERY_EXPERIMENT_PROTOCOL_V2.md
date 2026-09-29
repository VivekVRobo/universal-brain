# Recovery Reliability Experiment Protocol V2

## Purpose

V1 established a reproducible failure window in which an external tool effect can succeed while the evidence receipt is not recorded. Retrying the same authorized operation then produced a duplicate effect in every V1 trial.

V2 tests a narrower question:

Can the runtime avoid duplicate replay while still completing legitimate unfinished work when the previous execution outcome can be observed?

This protocol does not claim universal exactly once execution. Exactly once behavior across arbitrary external systems cannot be guaranteed by a local agent runtime alone. V2 instead introduces durable operation intent, explicit execution state, tool supplied reconciliation, and fail closed behavior when the outcome cannot be determined.

## Frozen V1 baseline

The V1 evidence remains unchanged.

Experiment 4 records this sequence:

1. ToolGateway records TOOL_CALLED.
2. The tool performs the external effect.
3. EVIDENCE_PRODUCED fails before it is committed.
4. The same authorized invocation is retried.
5. The effect is executed again.

The publication baseline is twenty duplicate actions in twenty trials.

V2 is measured separately as Experiment 5.

## V2 architecture

Each idempotent operation receives a durable identity derived from:

project ID

task ID

tool name

idempotency key

The durable SQLite operation ledger records these states:

PREPARED

EXECUTING

EFFECT_CONFIRMED

EVIDENCE_COMMITTED

IN_DOUBT

The canonical request digest and target resource are bound to the same operation identity. Reusing an idempotency key for a different request is rejected.

## Execution protocol

Before a tool effect begins:

1. Authority checks complete.
2. Reversibility preflight completes.
3. The operation intent is persisted as PREPARED.
4. TOOL_CALLED is recorded.
5. The ledger moves to EXECUTING.
6. The tool runs.

When the tool returns a deterministic result:

7. The result is persisted as EFFECT_CONFIRMED.
8. EVIDENCE_PRODUCED is written.
9. The ledger moves to EVIDENCE_COMMITTED.

If step 8 fails, the effect is already durably known and a retry must record the missing evidence without invoking the tool again.

## Ambiguous execution protocol

A harder failure can occur between the external effect and step 7.

After restart the ledger then contains EXECUTING or IN_DOUBT.

The gateway does not automatically replay the operation.

Instead the tool receives a read only reconciliation request.

The tool may return:

CONFIRMED

The effect is observable and its result can be reconstructed. The gateway records the result and completes evidence without executing the effect again.

ABSENT

The tool can prove that the effect did not occur. The gateway may execute the authorized operation once.

UNKNOWN

The tool cannot determine whether the effect occurred. The gateway marks the operation IN_DOUBT and blocks replay.

UNKNOWN is intentionally conservative. It prevents a lack of observability from being converted into a duplicate side effect.

## Experiment 5

Experiment 5 uses the same append effect used by the V1 baseline because the operation identifier can be observed directly in the target file.

Three crash conditions are executed.

### Condition A

Evidence receipt crash

The append succeeds.

The operation ledger reaches EFFECT_CONFIRMED.

The first EVIDENCE_PRODUCED write is forced to fail.

A fresh gateway instance then retries the same operation.

Expected result:

one effect

zero duplicates

final state EVIDENCE_COMMITTED

### Condition B

Hard process crash after effect

A separate Python process receives the operation.

The ledger reaches EXECUTING.

The tool appends the effect and immediately terminates the process before returning to ToolGateway.

A fresh Python process retries the operation.

The reconciliation method observes the operation identifier in the file and returns CONFIRMED.

Expected result:

one effect

zero duplicates

final state EVIDENCE_COMMITTED

### Condition C

Hard process crash before effect

A separate Python process receives the operation.

The ledger reaches EXECUTING.

The process terminates inside the tool before the external effect occurs.

A fresh Python process retries the operation.

The reconciliation method proves the operation identifier is absent and returns ABSENT.

Expected result:

the previously unfinished effect executes once

one final effect

zero duplicates

final state EVIDENCE_COMMITTED

This condition is required to demonstrate that V2 does not obtain safety by refusing all interrupted work.

## Fail closed control

A separate unit test uses a tool that cannot reconcile its interrupted outcome.

The first execution enters IN_DOUBT.

On retry the tool returns UNKNOWN through the default BaseTool reconciliation implementation.

Expected result:

the tool is not invoked again

OperationOutcomeUncertainError is raised

the operation remains IN_DOUBT

## Primary measurements

For each condition:

effect count after interruption

effect count after retry

duplicate action count

retry completion

initial durable operation state

final durable operation state

recovery of legitimate unfinished work

## Publication comparison

The core comparison is:

V1 receipt crash

twenty trials

duplicate count measured directly

V2 receipt crash

twenty trials

duplicate count measured directly

V2 hard crash after effect

twenty trials

duplicate count measured directly

V2 hard crash before effect

twenty trials

completion of legitimate unfinished work measured directly

The article must report both favorable and unfavorable results.

If V2 fails any condition, that failure remains part of the evidence record.

## Remaining limitation

Even if Experiment 5 succeeds, the result applies only where the external effect is observable or the external system supports idempotency.

For an external service where the runtime cannot determine whether a request took effect, V2 deliberately returns an indeterminate state rather than claiming exactly once execution.

That limitation should be stated explicitly in any public article or research manuscript.
