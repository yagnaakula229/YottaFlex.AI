from dataclasses import replace
from datetime import timedelta

import pytest

from app.services.recovery.policy import RecoveryPolicy

pytestmark = pytest.mark.unit


def test_policy_configuration_is_versioned_and_hashes_all_decision_inputs() -> None:
    default_policy = RecoveryPolicy()
    changed_threshold = replace(
        default_policy,
        inactivity_threshold=timedelta(minutes=90),
    )

    assert default_policy.version == "recovery-v1-provisional"
    assert default_policy.as_dict()["rolling_window_boundary"] == "(lower, upper]"
    assert default_policy.configuration_hash != changed_threshold.configuration_hash


def test_policy_rejects_unsupported_or_invalid_values() -> None:
    with pytest.raises(ValueError, match="Frequency caps"):
        RecoveryPolicy(frequency_cap_24h=-1)

    with pytest.raises(ValueError, match="selection policy"):
        RecoveryPolicy(selection_policy="random")
