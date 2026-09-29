from universal_brain.engineering.recovery_experiments import (
    ExperimentReport,
    run_experiment_1,
    run_experiment_2,
    run_experiment_3,
    run_experiment_4,
    run_experiment_5,
    write_report,
)


def test_exp1_clean_recovery_completes_without_duplicates():
    trials = run_experiment_1(
        trials_per_condition=1,
        total_steps=10,
        interruption_points=(50,),
    )
    clean = [trial for trial in trials if trial.condition == "clean"]
    assert len(clean) == 3
    assert all(trial.passed for trial in clean)
    assert all(trial.metrics["duplicate_actions"] == 0 for trial in clean)
    assert all(trial.metrics["mission_complete"] for trial in clean)


def test_exp1_ambiguous_effect_is_visible_to_checkpoint_strategy():
    trials = run_experiment_1(
        trials_per_condition=1,
        total_steps=10,
        interruption_points=(50,),
    )
    ambiguous = {
        trial.strategy: trial
        for trial in trials
        if trial.condition == "effect_before_state"
    }

    assert ambiguous["conversation"].metrics["duplicate_actions"] == 1
    assert ambiguous["dag"].metrics["duplicate_actions"] == 1

    checkpoint = ambiguous["checkpoint"]
    assert checkpoint.passed
    assert checkpoint.metrics["duplicate_actions"] == 0
    assert checkpoint.metrics["blocked_for_replan"] is True
    assert checkpoint.metrics["mission_complete"] is False


def test_exp2_workspace_drift_classification_matches_policy():
    trials = run_experiment_2(trials_per_condition=1)
    assert trials
    assert all(trial.passed for trial in trials)

    by_condition = {trial.condition: trial for trial in trials}
    assert by_condition["source_change"].metrics["blocked"] is True
    assert by_condition["test_change"].metrics["blocked"] is True
    assert by_condition["dependency_change"].metrics["blocked"] is True
    assert by_condition["multiple_source_changes"].metrics["blocked"] is True
    assert by_condition["generated_brain_change"].metrics["blocked"] is False
    assert by_condition["cache_change"].metrics["blocked"] is False


def test_exp3_real_process_crashes_recover_or_fail_closed():
    trials = run_experiment_3(trials_per_condition=1)
    assert trials
    assert all(trial.passed for trial in trials)

    effect_windows = [trial for trial in trials if trial.condition == "effect_before_state"]
    assert {trial.interruption_point for trial in effect_windows} == {
        "execution",
        "commit",
        "integration",
    }
    assert all(trial.metrics["blocked_on_workspace_drift"] for trial in effect_windows)

    clean_windows = [trial for trial in trials if trial.condition == "after_checkpoint"]
    assert all(trial.metrics["reset_to_replan"] for trial in clean_windows)


def test_exp4_measures_effect_receipt_crash_window_without_hiding_result():
    trials = run_experiment_4(trials_per_condition=1)
    assert len(trials) == 1
    trial = trials[0]
    assert trial.passed
    assert trial.metrics["effect_count_after_injected_crash"] == 1
    assert trial.metrics["effect_count_after_retry"] >= 1
    assert trial.metrics["retry_succeeded"] is True
    assert trial.details["tool_call_events"] >= 2


def test_experiment_report_is_bound_to_source_and_self_verifying(tmp_path):
    report = ExperimentReport(summary={"probe": {"trials": 0}})
    path = tmp_path / "report.json"
    write_report(report, path)

    loaded = ExperimentReport.model_validate_json(path.read_text(encoding="utf-8"))
    assert loaded.source_commit
    assert loaded.payload_sha256
    assert loaded.verify_digest()



def test_exp5_v2_recovers_all_crash_windows_without_duplicates():
    trials = run_experiment_5(trials_per_condition=1)
    assert len(trials) == 3
    assert all(trial.passed for trial in trials)
    assert all(trial.metrics["duplicate_actions"] == 0 for trial in trials)
    assert all(trial.metrics["effect_count_after_retry"] == 1 for trial in trials)

    by_condition = {trial.condition: trial for trial in trials}
    unfinished = by_condition["hard_crash_before_effect"]
    assert unfinished.metrics["effect_count_after_crash"] == 0
    assert unfinished.metrics["recovered_legitimate_unfinished_work"] is True

    after_effect = by_condition["hard_crash_after_effect"]
    assert after_effect.metrics["effect_count_after_crash"] == 1
    assert after_effect.details["initial_ledger_state"] == "EXECUTING"
    assert after_effect.details["final_ledger_state"] == "EVIDENCE_COMMITTED"

    receipt = by_condition["evidence_receipt_crash"]
    assert receipt.details["initial_ledger_state"] == "EFFECT_CONFIRMED"
    assert receipt.details["final_ledger_state"] == "EVIDENCE_COMMITTED"
