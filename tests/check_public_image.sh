#!/usr/bin/env bash
# Check that each image reference is readable by an ANONYMOUS user.
#
# The release workflow is logged in to both registries, so a `docker pull` there
# proves nothing about what anyone else can reach — GHCR in particular makes a
# newly pushed package private regardless of the repository's visibility. This
# asks each registry for an anonymous pull token and fetches the manifest with
# it, which is exactly what a stranger's `docker pull` does first.
#
#   tests/check_public_image.sh ghcr.io/org/name:tag org/name:tag
set -uo pipefail

ACCEPT='application/vnd.oci.image.index.v1+json,application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.list.v2+json,application/vnd.docker.distribution.manifest.v2+json'

status=0
for ref in "$@"; do
  repo="${ref%:*}"
  tag="${ref##*:}"

  case "$repo" in
    ghcr.io/*)
      path="${repo#ghcr.io/}"
      token_url="https://ghcr.io/token?service=ghcr.io&scope=repository:${path}:pull"
      manifest_url="https://ghcr.io/v2/${path}/manifests/${tag}"
      ;;
    *.*/*)
      echo "  SKIP  ${ref} (unsupported registry)"
      continue
      ;;
    *)
      path="$repo"
      token_url="https://auth.docker.io/token?service=registry.docker.io&scope=repository:${path}:pull"
      manifest_url="https://registry-1.docker.io/v2/${path}/manifests/${tag}"
      ;;
  esac

  # Deliberately unauthenticated: no -u, no netrc, no docker credentials.
  token=$(curl -fsSL --retry 3 --retry-delay 5 "$token_url" 2>/dev/null \
          | python3 -c 'import json,sys; print(json.load(sys.stdin).get("token",""))' 2>/dev/null)
  if [ -z "$token" ]; then
    echo "  FAIL  ${ref} — no anonymous pull token; the package is probably private"
    status=1
    continue
  fi

  code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer ${token}" \
         -H "Accept: ${ACCEPT}" "$manifest_url" 2>/dev/null)
  if [ "$code" = "200" ]; then
    echo "  ok    ${ref} — anonymously pullable"
  else
    echo "  FAIL  ${ref} — manifest returned HTTP ${code} to an anonymous client"
    status=1
  fi
done

if [ "$status" -ne 0 ]; then
  echo
  echo "An image that was pushed but is not publicly readable cannot be pulled by"
  echo "Flywheel or by anyone else. For GHCR, make the package public at"
  echo "https://github.com/orgs/<org>/packages/container/package/<name> -> Package settings."
fi
exit "$status"
