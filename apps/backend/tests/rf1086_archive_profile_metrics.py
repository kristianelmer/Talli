"""Keep load-profile metrics separate from import warnings on child stderr."""
import json

METRICS_PREFIX = "TALLI_RF1086_ARCHIVE_PROFILE_METRICS="


def encode_profile_metrics(value):
    return METRICS_PREFIX + json.dumps(value)


def profile_diagnostics(stderr):
    return "".join(line for line in stderr.splitlines(keepends=True)
                   if not line.startswith(METRICS_PREFIX))


def parse_profile_metrics(stderr):
    records = [line[len(METRICS_PREFIX):] for line in stderr.splitlines()
               if line.startswith(METRICS_PREFIX)]
    if len(records) != 1:
        raise ValueError("archive profile requires exactly one framed metrics record")
    value = json.loads(records[0])
    if not isinstance(value, dict):
        raise ValueError("archive profile metrics must be an object")
    return value
