# Daily JobSpy search (GitHub Actions)

The workflow [`.github/workflows/daily-job-search.yml`](../.github/workflows/daily-job-search.yml) runs every day at **10:00 UTC** and on manual dispatch (`workflow_dispatch`).

## What it does

1. Builds and installs `python-jobspy` from the checked-out repository (same pattern as CI).
2. Runs the `jobspy` CLI with repository **variables** (see below), saving full results to `data/last_scrape.jsonl` (ignored by git).
3. Merges results into **`data/jobspy_seen.sqlite`** via [`scripts/github_jobspy_sqlite.py`](../scripts/github_jobspy_sqlite.py): duplicate detection uses normalized `job_url` when present, otherwise a hash of `site`, `title`, `company`, `date_posted`, and `location`.
4. Writes only **new** jobs to `data/new_jobs.jsonl`.
5. Builds a JSON body with [`scripts/github_discord_job_alert.py`](../scripts/github_discord_job_alert.py) (`--payload-out`), then posts it with **`curl`** (avoids Python + Discord edge cases on GitHub runners).
6. Saves the SQLite file in the **Actions cache** so the next run can deduplicate across days.

If the cache is missing or expired, the database starts empty and the first run may list many “new” jobs.

## Required secret

| Name | Description |
|------|-------------|
| `DISCORD_WEBHOOK_URL` | [Incoming webhook](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks) URL for the target channel — must start with `https://discord.com/api/webhooks/` |

## One paste: multiline `JOBSPY_DOTENV` (optional)

Instead of many separate repository variables, create **one** variable:

- **Name:** `JOBSPY_DOTENV`
- **Value:** several lines `KEY=value` (same keys as in bash below). Lines starting with `#` are ignored. **Spaces in values are OK** (e.g. `DISCORD_EMBED_TITLE=Offres web — Nantes`): the workflow rewrites the file with proper shell quoting.

Keys read by the workflow (after you push the version of the workflow that supports this):

```
SEARCH_TERM=développeur web
SITE=indeed,linkedin,hellowork,glassdoor
LOCATION=Nantes
COUNTRY_INDEED=france
JOB_TYPE=cdi,cdd
HOURS_OLD=72
RESULTS=50
REMOTE_FLAG=
SKIP_DISCORD_IF_EMPTY=1
MAX_JOBS=50
MAX_EMBED_CHARS=3900
DISCORD_EMBED_TITLE=Offres web — Nantes
```

Leave a key empty (e.g. `REMOTE_FLAG=`) to mean “not set”. If `JOBSPY_DOTENV` is **non-empty**, it **overrides** the individual `JOBSPY_*` variables for search + Discord payload (individual vars act as fallback when a key is missing from the block).

`DISCORD_WEBHOOK_URL` stays a **secret**, not part of this block.

## Optional repository variables (`Settings → Secrets and variables → Actions → Variables`)

| Variable | Default (if unset) | Description |
|----------|---------------------|-------------|
| `JOBSPY_SEARCH_TERM` | `software engineer` | Query passed to `jobspy` |
| `JOBSPY_SITE` | `indeed,linkedin,zip_recruiter,glassdoor` | Comma-separated boards |
| `JOBSPY_LOCATION` | *(empty)* | e.g. `Chicago` — omit for broader search |
| `JOBSPY_COUNTRY_INDEED` | `usa` | Indeed / Glassdoor country |
| `JOBSPY_JOB_TYPE` | *(empty)* | Job type filter: `fulltime`, `temporary`, `contract`, `parttime`, `internship` (aliases `cdi`, `cdd` and comma-separated lists like `cdi,cdd` or `fulltime,temporary` are supported) |
| `JOBSPY_HOURS_OLD` | `72` | Only jobs posted in the last N hours |
| `JOBSPY_RESULTS` | `50` | `-n` per board (upto ~50 per site per README; daily run default is 50) |
| `JOBSPY_REMOTE_FLAG` | *(empty)* | Set to `1` or `true` to add `--remote` |
| `JOBSPY_SKIP_DISCORD_IF_EMPTY` | *(empty)* | Set to `1` to skip Discord when there are no new jobs |
| `JOBSPY_DISCORD_MAX_JOBS` | `50` | Max jobs listed across Discord embeds (automatically split into multiple embeds/messages so listings are never cut off mid-list) |
| `JOBSPY_DISCORD_MAX_EMBED_CHARS` | `3900` | Max length per embed description before starting a new embed (Discord hard limit is 4096) |
| `JOBSPY_DISCORD_TITLE` | auto timestamp | Custom embed title |

The workflow sets defaults `MAX_JOBS=50` and `MAX_EMBED_CHARS=4000` when those variables are unset. `SKIP_DISCORD_IF_EMPTY` is still read only by the script.

**Note:** `-n` / `JOBSPY_RESULTS` is **per job board** (per site). With four default boards and `50`, you can get up to **200** rows in one scrape before deduplication; only **new** rows go to Discord, up to `MAX_JOBS`.

## Manual test

Use **Actions → Daily JobSpy search → Run workflow** after configuring the secret and variables.

## Troubleshooting: Discord `403 Forbidden`

1. **Révoquer et recréer le webhook** : Salon → Paramètres → Intégrations → Webhooks → ton webhook → *Réinitialiser l’URL du webhook* ou supprimer et en créer un nouveau, puis remplacer le secret `DISCORD_WEBHOOK_URL` sur GitHub par la **nouvelle** URL complète.
2. **Vérifier le secret** : il doit être exactement `https://discord.com/api/webhooks/…` ou `https://discordapp.com/api/webhooks/…` (pas seulement l’ID, pas d’espace ni retour à la ligne en trop).
3. **Droits du salon** : le webhook ne peut pas poster si le canal ou le serveur interdit les intégrations pour ton rôle (rare sur un salon classique).
4. En cas d’échec, l’étape **Post to Discord (curl)** affiche le **code HTTP** (ex. `403`) et les **2000 premiers caractères** du corps renvoyé par Discord (sans exposer l’URL du webhook).
