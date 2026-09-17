#!/usr/bin/env bash
# Validate the gear manifest with Flywheel's own CLI.
#
# Everything else here tests the gear by invoking the container directly, which
# is how stale CLI instructions shipped unnoticed. This runs the tool Flywheel
# actually uses, so the manifest is checked against their schema rather than our
# reading of it -- including checks we would not think to write, such as the
# manifest version agreeing with its docker image tag.
#
#   tests/test_manifest_cli.sh [path/to/manifest.json]
set -euo pipefail

MANIFEST="${1:-v0/manifest.json}"
INSTALL_DIR="${FW_CLI_INSTALL_DIR:-$HOME/.fw}"
FLYW="${INSTALL_DIR}/flyw"

if [ ! -x "$FLYW" ]; then
  echo "Installing the Flywheel CLI to ${INSTALL_DIR}..."
  # FW_CLI_UPDATE_PROFILE=false: don't edit the caller's shell profile.
  FW_CLI_INSTALL_DIR="$INSTALL_DIR" FW_CLI_UPDATE_PROFILE=false \
    sh -c "$(curl -fsSL https://storage.googleapis.com/flywheel-dist/fw-cli/stable/install.sh)"
fi

echo "Using $("$FLYW" --version)"
echo

echo "Validating ${MANIFEST}:"
"$FLYW" gear --validate "$MANIFEST"

# A validator that cannot fail is not a check. Feed it a manifest we have broken
# on purpose and require it to object.
echo
echo "Checking the validator rejects a broken manifest:"
broken=$(mktemp -d)/manifest.json
python3 - "$MANIFEST" "$broken" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1]))
manifest.pop("license", None)
manifest["custom"]["flywheel"]["classification"]["function"] = ["Not A Real Category"]
json.dump(manifest, open(sys.argv[2], "w"), indent=2)
PY
if "$FLYW" gear --validate "$broken" >/dev/null 2>&1; then
  echo "  FAIL  the validator accepted a manifest with no license and a bogus classification"
  exit 1
fi
echo "  ok    rejected, as it should"
echo
echo "Manifest validates against the Flywheel CLI"
