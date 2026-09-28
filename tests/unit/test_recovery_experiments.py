from universal_brain.engineering.recovery_experiments import (
    run_experiment_1,
    run_experiment_2,
    run_experiment_3,
    run_experiment_4,
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
