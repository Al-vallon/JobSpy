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

JOB_TYPE_FR = {
    "fulltime": "CDI / Temps plein",
    "temporary": "CDD / Intérim",
    "contract": "Contrat / Freelance",
    "parttime": "Temps partiel",
    "internship": "Stage / Alternance",
    "perdiem": "Per diem",
    "volunteer": "Bénévolat",
    "other": "Autre",
}


def load_records(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _format_job_type(raw: object) -> str:
    if not raw:
        return ""
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    translated = [JOB_TYPE_FR.get(p.lower(), p) for p in parts]
    return ", ".join(dict.fromkeys(translated))


def format_line(rec: dict[str, object], index: int) -> str:
    title = str(rec.get("title") or "?")
    company = str(rec.get("company") or "?")
    site = str(rec.get("site") or "")
    url = str(rec.get("job_url") or "")
    date_posted = str(rec.get("date_posted") or "")
    detected_at = str(rec.get("detected_at") or "")
    job_type_str = _format_job_type(rec.get("job_type"))
    location = str(rec.get("location") or "")

    header = f"{index}. **{title}** — {company}"
    meta_parts: list[str] = []
    if site:
        meta_parts.append(site)
    if job_type_str:
        meta_parts.append(job_type_str)
    if location:
        meta_parts.append(location)
    if date_posted and detected_at:
        meta_parts.append(f"Publié : {date_posted} (détecté : {detected_at})")
    elif date_posted:
        meta_parts.append(f"Publié : {date_posted}")
    elif detected_at:
        meta_parts.append(f"Détecté : {detected_at}")

    lines = [header]
    if meta_parts:
        lines.append("   " + " • ".join(meta_parts))
    if url:
        lines.append(f"   {url}")
    return "\n".join(lines)


def build_payloads(
    records: list[dict[str, object]],
    title: str,
    max_jobs: int,
    max_desc_chars: int = 3900,
) -> list[dict[str, object]]:
    """Découpe les annonces en plusieurs embeds / payloads pour afficher les `max_jobs` sans tronquer."""
    total = len(records)
    shown = records[:max_jobs]
    if not shown:
        return [
            {
                "embeds": [
                    {
                        "title": title,
                        "description": "_Aucune annonce dans ce fichier._",
                        "color": 9807270,
                    }
                ]
            }
        ]

    formatted_items = [format_line(rec, i + 1) for i, rec in enumerate(shown)]
    if total > len(shown):
        formatted_items.append(
            f"_… et {total - len(shown)} autre(s) annonce(s) au-delà de MAX_JOBS={max_jobs}._"
        )

    # Limite Discord : 4096 caractères par description d'embed, et ~6000 caractères cumulés par requête webhook.
    per_embed_limit = min(max(max_desc_chars, 1000), 4000)
    embeds: list[dict[str, object]] = []
    current_lines: list[str] = []
    current_len = 0

    for item in formatted_items:
        sep_len = 2 if current_lines else 0
        if current_lines and current_len + sep_len + len(item) > per_embed_limit:
            embeds.append(
                {
                    "description": "\n\n".join(current_lines),
                    "color": 5763719,
                }
            )
            current_lines = [item]
            current_len = len(item)
        else:
            current_lines.append(item)
            current_len += sep_len + len(item)

    if current_lines:
        embeds.append(
            {
                "description": "\n\n".join(current_lines),
                "color": 5763719,
            }
        )

    total_embeds = len(embeds)
    for idx, emb in enumerate(embeds):
        if total_embeds == 1:
            emb["title"] = title
        else:
            emb["title"] = f"{title} ({idx + 1}/{total_embeds})"

    # Regrouper les embeds par requête webhook sans dépasser ~5500 caractères ni 10 embeds par POST
    payloads: list[dict[str, object]] = []
    batch: list[dict[str, object]] = []
    batch_chars = 0
    for emb in embeds:
        emb_chars = len(str(emb.get("title", ""))) + len(str(emb.get("description", "")))
        if batch and (len(batch) >= 10 or batch_chars + emb_chars > 5500):
            payloads.append({"embeds": batch})
            batch = [emb]
            batch_chars = emb_chars
        else:
            batch.append(emb)
            batch_chars += emb_chars
    if batch:
        payloads.append({"embeds": batch})

    return payloads


def _webhook_url_ok(url: str) -> bool:
    return bool(
        url.startswith("https://discord.com/api/webhooks/")
        or url.startswith("https://discordapp.com/api/webhooks/")
    )


def post_webhook_urllib(url: str, payload: dict[str, object]) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
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
    max_jobs = int(os.environ.get("MAX_JOBS") or "50")
    max_chars = int(os.environ.get("MAX_EMBED_CHARS") or "3900")

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

    run_title = os.environ.get("DISCORD_EMBED_TITLE", "").strip() or (
        f"JobSpy — nouvelles offres ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})"
    )
    if not records:
        payloads: list[dict[str, object]] = [
            {
                "embeds": [
                    {
                        "title": run_title,
                        "description": "Aucune nouvelle offre depuis le dernier run.",
                        "color": 9807270,
                    }
                ]
            }
        ]
    else:
        payloads = build_payloads(records, run_title, max_jobs, max_chars)

    if payload_out is not None:
        payload_out.parent.mkdir(parents=True, exist_ok=True)
        # Écrit le 1er payload dans payload_out et aussi une liste paginée dans payload_out.jsonl
        payload_out.write_text(
            json.dumps(payloads[0], ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        batches_path = payload_out.with_suffix(".jsonl")
        with batches_path.open("w", encoding="utf-8") as bf:
            for p in payloads:
                bf.write(json.dumps(p, ensure_ascii=False, separators=(",", ":")) + "\n")
        print(
            f"github_discord_job_alert: {len(payloads)} requête(s) préparée(s) dans {batches_path} "
            f"({min(len(records), max_jobs)}/{len(records)} annonce(s) affichée(s))",
            file=sys.stderr,
        )
        return 0

    for p in payloads:
        try:
            post_webhook(webhook, p)
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
                    post_webhook_curl(webhook, p)
                except (RuntimeError, OSError, subprocess.TimeoutExpired) as retry:
                    print(f"Secours curl: {retry}", file=sys.stderr)
                    return 1
            else:
                return 1
        except (urllib.error.URLError, OSError) as e:
            print(f"Discord: {e}", file=sys.stderr)
            return 1

    print(
        f"github_discord_job_alert: envoyé ({min(len(records), max_jobs)}/{len(records)} annonce(s) en {len(payloads)} message(s))",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
