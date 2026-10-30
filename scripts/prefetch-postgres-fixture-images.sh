#!/usr/bin/env bash
set -euo pipefail

# Docker publishes its Official Images here; this is not a private AWS cache.
# https://www.docker.com/press-release/docker-official-images-available-amazon-elastic-container-registry/
# Anonymous transfer is free and IP-limited; do not authenticate an AWS account.
# https://aws.amazon.com/ecr/pricing/
if [[ "$#" -ne 0 ]]; then
  printf 'PostgreSQL fixture prefetch accepts no image overrides.\n' >&2
  exit 2
fi

umask 077
fixture_docker_config="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/talli-postgres-prefetch.XXXXXX")"
trap 'rm -rf -- "$fixture_docker_config"' EXIT
# An explicit empty registry entry also prevents Docker from selecting an
# installed default credential helper. Never read or alter the caller's auth.
printf '{"auths":{"public.ecr.aws":{},"https://index.docker.io/v1/":{}}}\n' > "$fixture_docker_config/config.json"

fixture_pull_is_fatal() {
  LC_ALL=C grep -Eiq 'unauthorized|authentication required|no basic auth credentials|denied|forbidden|manifest unknown|manifest invalid|invalid manifest|no matching manifest|invalid reference format|x509:|certificate|no such host|no space left on device|read-only file system|cannot connect to the Docker daemon' <<< "$1"
}

fixture_pull_is_transient() {
  # A permanent error takes precedence over any earlier transient diagnostic.
  if fixture_pull_is_fatal "$1"; then
    return 1
  fi
  LC_ALL=C grep -Eiq 'toomanyrequests.*rate exceeded|too many requests|TLS handshake timeout|context deadline exceeded|i/o timeout|connection reset by peer|temporary failure in name resolution|unexpected EOF' <<< "$1"
}

fixture_pull_is_data_limit() {
  if fixture_pull_is_fatal "$1"; then
    return 1
  fi
  LC_ALL=C grep -Eiq 'toomanyrequests:[[:space:]]*Data limit exceeded[[:space:]]*$' <<< "$1"
}

for fixture_tag in 17 17-alpine 16-alpine; do
  fixture_source="public.ecr.aws/docker/library/postgres:${fixture_tag}"
  # Three anonymous attempts at most, with only 5s + 10s of added delay per image.
  # Only ECR's explicit data allowance failure permits one additional anonymous
  # pull from Docker's same fixed Official Image. No fallback retries or login;
  # unknown failures and all tag failures remain fatal on the default daemon.
  for fixture_attempt in 1 2 3; do
    if fixture_pull_output="$(env -u DOCKER_AUTH_CONFIG -u DOCKER_CONTEXT -u DOCKER_HOST DOCKER_CONFIG="$fixture_docker_config" \
      docker --context default pull "$fixture_source" 2>&1)"; then
      printf '%s\n' "$fixture_pull_output"
      break
    else
      fixture_pull_status="$?"
      printf '%s\n' "$fixture_pull_output" >&2
    fi
    if [[ "$fixture_pull_status" -ge 128 ]]; then
      exit "$fixture_pull_status"
    fi
    if fixture_pull_is_data_limit "$fixture_pull_output"; then
      fixture_fallback="docker.io/library/postgres:${fixture_tag}"
      printf 'ECR anonymous data allowance exhausted; trying fixed official Docker Hub image %s once.\n' \
        "$fixture_fallback" >&2
      if fixture_pull_output="$(env -u DOCKER_AUTH_CONFIG -u DOCKER_CONTEXT -u DOCKER_HOST DOCKER_CONFIG="$fixture_docker_config" \
        docker --context default pull "$fixture_fallback" 2>&1)"; then
        printf '%s\n' "$fixture_pull_output"
        fixture_source="$fixture_fallback"
        break
      else
        fixture_pull_status="$?"
        printf '%s\n' "$fixture_pull_output" >&2
        exit "$fixture_pull_status"
      fi
    fi
    if [[ "$fixture_attempt" -eq 3 ]] || ! fixture_pull_is_transient "$fixture_pull_output"; then
      exit "$fixture_pull_status"
    fi
    fixture_retry_delay="$((fixture_attempt * 5))"
    printf 'Transient PostgreSQL pull failure; retrying %s in %ss (attempt %s/3).\n' \
      "$fixture_source" "$fixture_retry_delay" "$((fixture_attempt + 1))" >&2
    sleep "$fixture_retry_delay"
  done
  env -u DOCKER_AUTH_CONFIG -u DOCKER_CONTEXT -u DOCKER_HOST DOCKER_CONFIG="$fixture_docker_config" \
    docker --context default tag "$fixture_source" "postgres:${fixture_tag}"
done
