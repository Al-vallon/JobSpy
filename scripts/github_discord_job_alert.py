#!/usr/bin/env python3
"""Envoie un résumé des annonces JobSpy (JSONL) vers un webhook Discord."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def load_records(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def format_line(rec: dict[str, object], index: int) -> str:
    title = str(rec.get("title") or "?")
    company = str(rec.get("company") or "?")
    site = str(rec.get("site") or "")
    url = str(rec.get("job_url") or "")
    parts = [f"{index}. **{title}** — {company}"]
    if site:
        parts.append(f"   ({site})")
    if url:
        parts.append(f"   {url}")
    return "\n".join(parts)


def build_body(
    records: list[dict[str, object]],
    title: str,
    max_jobs: int,
    max_desc_chars: int,
) -> dict[str, object]:
    total = len(records)
    shown = records[:max_jobs]
    lines = [format_line(rec, i + 1) for i, rec in enumerate(shown)]
    body = "\n\n".join(lines) if lines else "_Aucune annonce dans ce fichier._"
    footer = ""
    if total > len(shown):
        footer = f"\n\n… et {total - len(shown)} autre(s) annonce(s)."
    description = (body + footer).strip()
    if len(description) > max_desc_chars:
        description = description[: max_desc_chars - 20] + "\n\n… _(tronqué)_"
    return {
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": 5763719,
            }
        ]
    }


def _webhook_url_ok(url: str) -> bool:
    return bool(
        url.startswith("https://discord.com/api/webhooks/")
        or url.startswith("https://discordapp.com/api/webhooks/")
    )


def post_webhook_urllib(url: str, payload: dict[str, object]) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    # User-Agent évite parfois un 403 côté pare-feu / WAF sur les IP datacenter (ex. GitHub Actions).
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "DiscordBot (https://github.com/speedyapply/JobSpy, 1.0)",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status not in (200, 204):
            raise RuntimeError(f"Discord HTTP {resp.status}")


def post_webhook_curl(url: str, payload: dict[str, object]) -> None:
    """Secours : curl utilise une autre pile TLS ; contourne parfois un 403 sur Actions."""
    data = json.dumps(payload, ensure_ascii=False)
    r = subprocess.run(
        [
            "curl",
            "-sS",
            "-f",
            "-X",
            "POST",
            url,
            "-H",
            "Content-Type: application/json",
            "-d",
            data,
        ],
        capture_output=True,
        text=True,
        timeout=45,
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()[:2000]
        raise RuntimeError(f"curl exit {r.returncode}: {err or 'no output'}")


def post_webhook(url: str, payload: dict[str, object]) -> None:
    if os.environ.get("DISCORD_USE_CURL", "").lower() in ("1", "true", "yes"):
        post_webhook_curl(url, payload)
        return
    post_webhook_urllib(url, payload)


def main() -> int:
    argv = list(sys.argv[1:])
    payload_out: Path | None = None
    if argv and argv[0] == "--payload-out":
        if len(argv) < 2:
            print("usage: github_discord_job_alert.py --payload-out FILE <nouvelles.jsonl>", file=sys.stderr)
            return 2
        payload_out = Path(argv[1])
        argv = argv[2:]
    elif "--payload-out" in argv:
        i = argv.index("--payload-out")
        if i + 1 >= len(argv):
            print("usage: … --payload-out FILE … <nouvelles.jsonl>", file=sys.stderr)
            return 2
        payload_out = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2 :]

    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    webhook = webhook.strip('"').strip("'").split()[0] if webhook else ""

    if not payload_out:
        if not webhook:
            print("DISCORD_WEBHOOK_URL manquant", file=sys.stderr)
            return 1
        if not _webhook_url_ok(webhook):
            print(
                "DISCORD_WEBHOOK_URL doit être l’URL complète du webhook (https://discord.com/api/webhooks/…), "
                "pas un token seul ni une autre API.",
                file=sys.stderr,
            )
            return 1

    if not argv:
        print(
            "usage: github_discord_job_alert.py [--payload-out FILE] <nouvelles.jsonl>",
            file=sys.stderr,
        )
        return 2

    path = Path(argv[0])
    skip_if_empty = os.environ.get("SKIP_DISCORD_IF_EMPTY", "").lower() in (
        "1",
        "true",
        "yes",
    )
    max_jobs = int(os.environ.get("MAX_JOBS") or "15")
    max_chars = int(os.environ.get("MAX_EMBED_CHARS") or "3800")

    records = load_records(path) if path.is_file() else []

    if not records and skip_if_empty:
        marker = os.environ.get("DISCORD_SKIP_MARKER", "").strip()
        if payload_out is not None and marker:
            Path(marker).parent.mkdir(parents=True, exist_ok=True)
            Path(marker).write_text("skip\n", encoding="utf-8")
        print(
            "github_discord_job_alert: 0 annonce, webhook ignoré (SKIP_DISCORD_IF_EMPTY)",
            file=sys.stderr,
        )
        return 0

    run_title = os.environ.get(
        "DISCORD_EMBED_TITLE",
        f"JobSpy — nouvelles offres ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})",
    )
    if not records:
        payload = {
            "embeds": [
                {
                    "title": run_title,
                    "description": "Aucune nouvelle offre depuis le dernier run.",
                    "color": 9807270,
                }
            ]
        }
    else:
        payload = build_body(records, run_title, max_jobs, max_chars)

    if payload_out is not None:
        payload_out.parent.mkdir(parents=True, exist_ok=True)
        payload_out.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(
            f"github_discord_job_alert: payload écrit dans {payload_out} ({len(records)} annonce(s))",
            file=sys.stderr,
        )
        return 0

    try:
        post_webhook(webhook, payload)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:2000]
        except OSError:
            pass
        print(
            f"Discord HTTP {e.code} {e.reason} — vérifie DISCORD_WEBHOOK_URL (webhook salon → Intégrations).",
            file=sys.stderr,
        )
        if body:
            print(f"Réponse Discord: {body}", file=sys.stderr)
        if e.code == 403:
            print(
                "Tentative de secours avec curl (parfois nécessaire sur GitHub Actions)…",
                file=sys.stderr,
            )
            try:
                post_webhook_curl(webhook, payload)
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as retry:
                print(f"Secours curl: {retry}", file=sys.stderr)
                print(
                    "Si les deux échouent : régénère l’URL du webhook dans Discord et mets à jour le secret.",
                    file=sys.stderr,
                )
                return 1
        else:
            return 1
    except urllib.error.URLError as e:
        print(f"Discord URLError: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"Discord: {e}", file=sys.stderr)
        return 1

    print(
        f"github_discord_job_alert: envoyé ({len(records)} annonce(s))",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
