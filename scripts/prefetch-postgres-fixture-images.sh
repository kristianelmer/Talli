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
printf '{"auths":{"public.ecr.aws":{}}}\n' > "$fixture_docker_config/config.json"

for fixture_tag in 17 17-alpine 16-alpine; do
  fixture_source="public.ecr.aws/docker/library/postgres:${fixture_tag}"
  # This CI helper uses the runner's default daemon for both operations.
  env -u DOCKER_AUTH_CONFIG -u DOCKER_CONTEXT -u DOCKER_HOST DOCKER_CONFIG="$fixture_docker_config" \
    docker --context default pull "$fixture_source"
  env -u DOCKER_AUTH_CONFIG -u DOCKER_CONTEXT -u DOCKER_HOST DOCKER_CONFIG="$fixture_docker_config" \
    docker --context default tag "$fixture_source" "postgres:${fixture_tag}"
done
