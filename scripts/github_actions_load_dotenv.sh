#!/usr/bin/env bash
# Écrit le contenu multiline de JOBSPY_DOTENV dans .jobspy.env à la racine du workspace.
# Appelé depuis le workflow uniquement si la variable GitHub vars.JOBSPY_DOTENV est non vide.
set -euo pipefail
ROOT="${GITHUB_WORKSPACE:-.}"
OUT="${ROOT}/.jobspy.env"
if [ -z "${JOBSPY_DOTENV:-}" ]; then
  rm -f "$OUT"
  exit 0
fi
printf '%s\n' "$JOBSPY_DOTENV" >"$OUT"
echo "Wrote ${OUT} ($(wc -l <"$OUT") lines)"
