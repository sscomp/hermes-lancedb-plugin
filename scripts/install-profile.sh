#!/usr/bin/env bash
set -euo pipefail

if [ "${1:-}" = "" ]; then
  echo "Usage: scripts/install-profile.sh <profile-name> [hermes-home]" >&2
  exit 2
fi

PROFILE="$1"
HERMES_HOME="${2:-$HOME/.hermes/profiles/$PROFILE}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="$HERMES_HOME/plugins/hermes_lancedb"

mkdir -p "$HERMES_HOME/plugins"
rm -rf "$TARGET"
cp -R "$ROOT/plugins/hermes_lancedb" "$TARGET"

python3 - "$HERMES_HOME/config.yaml" <<'PY'
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
content = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
lines = content.splitlines()

memory_idx = None
for idx, line in enumerate(lines):
    if line.strip() == "memory:" and not line.startswith((" ", "\t")):
        memory_idx = idx
        break

if memory_idx is None:
    block = ["memory:", "  provider: hermes_lancedb"]
    new_content = content.rstrip()
    if new_content:
        new_content += "\n"
    new_content += "\n".join(block) + "\n"
    config_path.write_text(new_content, encoding="utf-8")
    raise SystemExit(0)

end = len(lines)
for idx in range(memory_idx + 1, len(lines)):
    line = lines[idx]
    if line.strip() and not line.startswith((" ", "\t")) and ":" in line:
        end = idx
        break

block = lines[memory_idx:end]
provider_idx = None
for idx, line in enumerate(block):
    if line.strip().startswith("provider:") and line.startswith("  "):
        provider_idx = idx
        break

if provider_idx is None:
    block.append("  provider: hermes_lancedb")
else:
    block[provider_idx] = "  provider: hermes_lancedb"

updated = lines[:memory_idx] + block + lines[end:]
config_path.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")
PY

echo "Installed hermes_lancedb into $TARGET"
echo "memory.provider has been set to hermes_lancedb in $HERMES_HOME/config.yaml"
echo "Next step: copy examples/profile-env.example values into $HERMES_HOME/.env and adjust paths."

