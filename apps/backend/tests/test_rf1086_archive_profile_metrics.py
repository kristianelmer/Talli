"""Profile stderr framing fails closed without suppressing diagnostics."""
import pytest

from rf1086_archive_profile_metrics import (
    METRICS_PREFIX, encode_profile_metrics, parse_profile_metrics, profile_diagnostics,
)


def test_warning_prefixed_metrics_preserve_values_and_diagnostics():
    metrics = {"wireBytes": 14007024, "pythonAllocationBytes": [120835, 56075920]}
    warning = "/runtime/fastapi/testclient.py:1: StarletteDeprecationWarning: httpx is deprecated\n"
    stderr = warning + encode_profile_metrics(metrics) + "\n"
    assert parse_profile_metrics(stderr) == metrics
    assert profile_diagnostics(stderr) == warning


@pytest.mark.parametrize("stderr", [
    "", "warning only\n", '{"unframed": true}\n',
    METRICS_PREFIX + "{}\n" + METRICS_PREFIX + "{}\n",
    METRICS_PREFIX + "not-json\n", METRICS_PREFIX + "[]\n",
])
def test_missing_duplicate_or_invalid_metrics_cannot_report_success(stderr):
    with pytest.raises(ValueError):
        parse_profile_metrics(stderr)


def test_prefix_mentioned_inside_a_warning_is_not_a_metrics_record():
    warning = "warning: expected " + METRICS_PREFIX + " somewhere else\n"
    stderr = warning + encode_profile_metrics({"wireBytes": 1}) + "\n"
    assert parse_profile_metrics(stderr) == {"wireBytes": 1}
    assert profile_diagnostics(stderr) == warning
