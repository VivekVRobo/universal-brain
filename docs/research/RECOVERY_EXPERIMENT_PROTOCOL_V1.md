# Recovery Reliability Experiment Protocol V1

## Purpose

This package turns the recovery claims in Universal Brain into controlled experiments.

The central question is simple:

Can the runtime distinguish what it remembers from what actually happened in the workspace after an interruption?

The package is designed to produce evidence for a technical publication. It is not a production certification and it is not an LLM quality benchmark.

## Evidence rule

Every result must be classified as one of these:

1. Source evidence

The implementation exists in the repository.

2. Harness evidence

A controlled experiment executed and produced a recorded result.

3. Target machine evidence

The experiment ran on the intended Windows environment or another explicitly named deployment environment.

4. Publication evidence

The exact report used in an article is preserved with the repository commit that produced it.

A source implementation is not automatically treated as target machine proof.

## Experiment 1

### Question

How does the available recovery information change behavior after a crash?

### Compared strategies

Strategy A uses conversation state only.

Strategy B uses a Task DAG without workspace identity verification.

Strategy C uses the EngineeringCheckpointStore with the Task DAG and workspace fingerprint verification.

### Interruption points

10 percent

25 percent

50 percent

75 percent

90 percent

### Crash windows

Clean

The durable state matches the workspace at restart.

Effect before state

The next external effect reaches the workspace after the last durable state was recorded. The process is assumed to stop before that state can be updated.

### Measures

Duplicate action count

Missing action count

Mission completion

Safe automatic recovery

Blocked recovery that requires replanning

### Interpretation

A blocked recovery is not counted as automatic completion.

A blocked recovery can still be safer than continuing when the runtime cannot prove whether the workspace matches the recorded mission state.

This experiment is a deterministic control lab. Repeated trials measure consistency of the implementation. They do not create statistical independence by themselves.

## Experiment 2

### Question

Does workspace drift detection reject changes to canonical project state while ignoring known generated state?

### Conditions

Clean workspace

Source file change

Test file change

Dependency file change

Multiple source changes

Generated .brain state change

Python cache change

### Expected behavior

Source, test, dependency, and multiple source mutations should block recovery.

Generated .brain state and cache mutations should not block recovery because those paths are excluded from the canonical workspace fingerprint.

The report records whether every mutation is classified according to that policy.

## Experiment 3

### Question

What happens when the Python process terminates at different phases of an engineering task?

### Phases

Planning

Cognitive work

Tool proposal

Preflight

Execution

Verification

Commit

Integration

### Process boundary

Each trial starts a separate Python process.

The child process creates a real EngineeringCheckpointStore checkpoint, flushes it to disk, and terminates with a known nonzero exit code.

A fresh parent process then attempts recovery.

### Two recovery windows

After checkpoint

The workspace still matches the checkpoint.

Expected result: transient task state becomes REPLAN_REQUIRED.

Effect before state

Used for execution, commit, and integration.

The child changes the workspace after the last checkpoint and then terminates.

Expected result: recovery refuses to continue because workspace drift is detected.

This experiment is the highest priority together with Experiment 1 because it exercises a real operating system process boundary.

## Experiment 4

### Question

What happens if a ToolGateway action changes the external world but the process fails before EVIDENCE_PRODUCED is durably recorded?

### Method

A disposable A1 research tool appends an operation identifier to a temporary file.

The real ToolGateway executes that tool.

A research EventStore injects a failure on the first EVIDENCE_PRODUCED append.

The side effect has already occurred at that point.

The same authorized invocation is then retried.

### Measures

Effect count immediately after the injected failure

Effect count after retry

Duplicate action count

TOOL_CALLED event count

EVIDENCE_PRODUCED event count

### Important interpretation rule

The trial field named passed means that the experiment successfully created and measured the intended crash window.

It does not mean the runtime achieved exactly once execution.

The duplicate_actions field is the product result that matters.

If a duplicate is observed, it must remain in the research record. The experiment package must not conceal it or silently repair the runtime before recording the baseline.

## Smoke run

Run all four experiments with one trial per condition:

```text
python scripts/recovery_experiments.py run --experiment all --trials 1 --output .brain/research/recovery_experiments_smoke.json
```

## Publication run

Run the priority experiments with twenty trials per condition:

```text
python scripts/recovery_experiments.py run --experiment 1 --trials 20 --output .brain/research/experiment_1.json
python scripts/recovery_experiments.py run --experiment 3 --trials 20 --output .brain/research/experiment_3.json
```

Then run the supporting experiments:

```text
python scripts/recovery_experiments.py run --experiment 2 --trials 20 --output .brain/research/experiment_2.json
python scripts/recovery_experiments.py run --experiment 4 --trials 20 --output .brain/research/experiment_4.json
```

## Minimum evidence required before article drafting

1. The experiment harness tests pass on the selected repository commit.

2. Experiments 1 and 3 have complete JSON reports.

3. Experiment 2 has a complete drift classification report.

4. Experiment 4 has a baseline result that is preserved even if it exposes a defect.

5. The repository commit SHA is recorded with the reports.

6. Any Windows specific claim is supported by a Windows run rather than a Linux result.

7. Any statement about long duration reliability is excluded until a separate real endurance campaign exists.

## Planned article connection

The first article should use these experiments to answer a narrower question than whether an agent is intelligent.

The question is whether an autonomous runtime can tell the difference between remembered progress and verified external state after failure.

That is the claim this package is designed to measure.
