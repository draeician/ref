#!/usr/bin/env bash
# Build an unsigned Firefox / LibreWolf .xpi from extension/
#
# Usage:
#   ./scripts/build-firefox.sh
#   ./scripts/build-firefox.sh /path/to/out.xpi
#
# Install (temporary):
#   about:debugging#/runtime/this-firefox → Load Temporary Add-on → .xpi
#
# Permanent (unsigned, local only):
#   about:config → xpinstall.signatures.required = false
#   about:addons → gear → Install Add-on From File → .xpi

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EXT_DIR="${ROOT}/extension"
VERSION="$(python3 -c "import json; print(json.load(open('${EXT_DIR}/manifest.json'))['version'])")"
NAME="ref-copy-tab-urls-firefox-v${VERSION}"
OUT_XPI="${1:-${ROOT}/dist/${NAME}.xpi}"
TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ref-xpi.XXXXXX")"

cleanup() {
  rm -rf "${TEMP_DIR}"
}
trap cleanup EXIT

echo "Building Firefox/LibreWolf XPI from ${EXT_DIR}..."

mkdir -p "$(dirname "${OUT_XPI}")"
rm -f "${OUT_XPI}"

# Flat package: required files only (no README / large screenshots)
cp "${EXT_DIR}/manifest.json" "${TEMP_DIR}/"
cp "${EXT_DIR}/background.js" "${TEMP_DIR}/"
cp -r "${EXT_DIR}/icons" "${TEMP_DIR}/"
# popup.html is optional leftover; include if present for completeness
if [[ -f "${EXT_DIR}/popup.html" ]]; then
  cp "${EXT_DIR}/popup.html" "${TEMP_DIR}/"
fi

# Gecko requires uncompressed (store) zip for reliable unsigned install
(
  cd "${TEMP_DIR}"
  zip -0 -q -r "${OUT_XPI}" .
)

if [[ ! -f "${OUT_XPI}" ]]; then
  echo "Failed to create ${OUT_XPI}" >&2
  exit 1
fi

echo "Created: ${OUT_XPI} ($(du -h "${OUT_XPI}" | cut -f1))"

echo "Integrity..."
unzip -t "${OUT_XPI}" >/dev/null

echo "Manifest..."
unzip -p "${OUT_XPI}" manifest.json | python3 -c "
import json, sys
m = json.load(sys.stdin)
gecko = m.get('browser_specific_settings', {}).get('gecko', {})
bg = m.get('background', {})
assert 'scripts' in bg, 'Firefox needs background.scripts (not service_worker)'
assert gecko.get('id'), 'missing browser_specific_settings.gecko.id'
print(f\"  name:    {m.get('name')}\")
print(f\"  version: {m.get('version')}\")
print(f\"  gecko id: {gecko.get('id')}\")
print(f\"  background: {bg}\")
"

echo ""
echo "LibreWolf / Firefox install:"
echo "  Temporary: about:debugging#/runtime/this-firefox → Load Temporary Add-on →"
echo "             ${OUT_XPI}"
echo "  Permanent: about:config xpinstall.signatures.required=false, then"
echo "             about:addons → Install Add-on From File → same .xpi"
echo "Done."
