#!/usr/bin/env python3
"""Écrit .jobspy.env depuis JOBSPY_DOTENV avec des valeurs correctement quotées pour bash."""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path


def main() -> int:
    raw = os.environ.get("JOBSPY_DOTENV", "")
    root = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    out = root / ".jobspy.env"
    if not raw.strip():
        out.unlink(missing_ok=True)
        return 0
    lines_out: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            print(f"github_jobspy_write_dotenv: ignoré (pas de =): {stripped!r}", file=sys.stderr)
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        # une couche de guillemets optionnelle si l'utilisateur a collé "foo bar"
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        lines_out.append(f"{key}={shlex.quote(value)}")
    text = "\n".join(lines_out) + ("\n" if lines_out else "")
    out.write_text(text, encoding="utf-8")
    print(f"Wrote {out} ({len(lines_out)} variable(s))", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
