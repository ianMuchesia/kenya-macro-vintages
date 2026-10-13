# Runbook: operating the clocks

Two Azure Container Apps **jobs** run the capturer image once a day and exit.
Run every command below from a **laptop terminal** with `az login` done, not from the
dev container.

| | Clock 1 | Clock 2 |
|---|---|---|
| Job | `job-clock1` | `job-clock2` |
| Schedule (UTC) | `0 3 * * *` (06:00 EAT) | `30 3 * * *` (06:30 EAT) |
| Sources | `sources.yaml` (default) | `SOURCES_FILE=sources-regulatory.yaml` |
| Healthchecks | clock1-macro-capture | clock2-regulatory-capture |

Shared resources:

```bash
RG=rg-clocks                 # resource group
SA=kmvintages2716            # storage account
C=raw                        # blob container: raw/<source>/<stamp>/..., raw/<source>/manifest.json, logs/
ENV=cae-clocks2              # Container Apps environment
IMAGE=ghcr.io/ianmuchesia/kenya-macro-vintages
```

---

## Check recent runs

```bash
az containerapp job execution list -n job-clock1 -g $RG \
  --query "[].{name:name, status:properties.status, start:properties.startTime}" -o table
```

Use `-n job-clock2` for clock 2. Expect `Succeeded`. Typical durations: clock 1 takes
22-36 min, and clock 2 is slower per request because Kenya Law has a 5 s crawl delay.

Console output isn't kept (the environment saves no logs, to protect the budget).
The lasting record of every run is its **log blob** in storage (next section).

## Read the latest log

Each run writes one log, `logs/<UTC start time>-<random>.jsonl`, with one line per source.
Both clocks write into `logs/`, so pick a log by its start time. Clock 1 starts at
`T03-0…` and clock 2 at `T03-3…` (manual runs have other times).

```bash
DAY=$(date -u +%F)
PREFIX="logs/${DAY}T03-0"     # clock 1; use T03-3 for clock 2

LOG=$(az storage blob list --account-name $SA -c $C --auth-mode key --prefix "$PREFIX" \
  --query "sort_by(@, &properties.lastModified)[-1].name" -o tsv)
az storage blob download --account-name $SA -c $C --auth-mode key -n "$LOG" -f /tmp/run.jsonl -o none
python3 -c "
import json
for line in open('/tmp/run.jsonl'):
    r = json.loads(line)
    print(r['source'], r['status'], r['http'], r['error'])
"
```

**Check the source names** to confirm you have the right clock's log: `cbk_cbr` and
`knbs_cpi` belong to clock 1, while `cbk_legislation_guidelines` and `kenyalaw_…` belong to clock 2.

How to read a line:

| `status` | `http` | Meaning |
|---|---|---|
| `ok` | 200 | Page saved. `error` lists any linked files that failed; those are retried next run. |
| `failed` | 404, 403, 5xx | The website answered with an error. |
| `failed` | `None` | No answer at all (network/TLS), or a storage error. Read `error`. |

## Start a run by hand

```bash
az containerapp job start -n job-clock2 -g $RG
```

Then use [Check recent runs](#check-recent-runs). A manual run captures under its own
timestamp and never overwrites an earlier capture, so it is always safe to run.

## Update the image tag

Images are built by `.github/workflows/image.yml` when a `v*` tag is pushed. That workflow runs the tests first.

1. Merge the change to `main`, then tag it:
   ```bash
   git switch main && git pull
   git tag v0.3.1 && git push origin v0.3.1
   ```
2. Wait for the **Image** workflow to go green on GitHub.
3. Point **both** jobs at the new tag:
   ```bash
   az containerapp job update -n job-clock1 -g $RG --image $IMAGE:v0.3.1
   az containerapp job update -n job-clock2 -g $RG --image $IMAGE:v0.3.1
   ```
4. Check what each job runs:
   ```bash
   az containerapp job show -n job-clock1 -g $RG \
     --query "properties.template.containers[0].image" -o tsv
   ```
5. Start one run by hand and read its log.

A run that is already in progress finishes on the old image.

## Add a source

1. Add an entry to `sources.yaml` (clock 1) or `sources-regulatory.yaml` (clock 2):
   `id`, `publisher`, `what`, `kind` (`page_table` or `listing_page`), `url`,
   `latest_seen`, `updates`, `robots_ok`. Check the site's `/robots.txt` first. If it
   sets a `Crawl-delay`, add `crawl_delay: <seconds>`.
   The `id` becomes the storage folder name, so get the spelling right first time.
2. Try it locally (saves into `./data`):
   ```bash
   uv run python -m capture --only <id>
   SOURCES_FILE=sources-regulatory.yaml uv run python -m capture --only <id>
   ```
3. `make lint test`, then open a PR, merge, and [update the image tag](#update-the-image-tag).

A new `listing_page` downloads at most 50 files per run, so a large backlog takes a few days.

## Rotate the KNBS certificate chain

Background: `docs/notes/knbs-tls.md`. KNBS sends only its own certificate, so
`certs/knbs-chain.pem` supplies the missing intermediate (YE2) and Root YE cross-signed
by ISRG Root X2. Verification is never turned off.

When to act: KNBS sources fail with `CERTIFICATE_VERIFY_FAILED`.

1. See what KNBS sends and who issued it:
   ```bash
   openssl s_client -connect www.knbs.or.ke:443 -servername www.knbs.or.ke </dev/null 2>/dev/null \
     | openssl x509 -noout -issuer -enddate
   ```
2. Download the matching intermediate, and its cross-signed root if needed, from
   <https://letsencrypt.org/certificates/>. Put them in one PEM file, intermediate first.
3. Check the chain verifies against a public root before shipping it:
   ```bash
   openssl s_client -connect www.knbs.or.ke:443 -servername www.knbs.or.ke \
     -CAfile <(cat "$(python3 -m certifi)" certs/knbs-chain.pem) </dev/null 2>/dev/null \
     | grep "Verify return code"      # want: 0 (ok)
   ```
4. Replace `certs/knbs-chain.pem`, run `make lint test` (`tests/unit/test_capture_tls.py`
   loads it), try `uv run python -m capture --only knbs_cpi`, then PR, merge and update the image tag.

Once Root YE is in public trust stores, the extra chain is no longer needed.

## When an alert arrives

There are two senders:

| Message | From | Meaning |
|---|---|---|
| "… is now **up**" | Healthchecks | A run finished with every source ok. Nothing to do. |
| "kenya-macro-vintages: N source(s) failed: …" | the capturer | The run finished but those sources failed. Healthchecks goes **down** at the same time. |
| "… is **down**" with no capturer message | Healthchecks | The run never pinged: it crashed (e.g. storage permission), or never started. |

What to do:

1. [Check recent runs](#check-recent-runs). If there's no execution at the expected time,
   the schedule or the job is broken. If it shows `Failed`, the process crashed.
2. [Read the latest log](#read-the-latest-log) and look at `http` and `error` for the
   failed sources.
3. Common causes:
   - **One site down or slow** (`http` 5xx or `None` with a timeout): wait for tomorrow's
     run. It retries by itself.
   - **403 from a site's firewall**: the site is refusing us. Don't try to get around it.
     Record it in that source's `notes`. Known case: CBK Banking Circular No. 11 of 2023
     (Unlicensed MVTS), which is blocked by CBK's Sucuri firewall for everyone.
   - **`CERTIFICATE_VERIFY_FAILED` on KNBS**: see
     [Rotate the KNBS certificate chain](#rotate-the-knbs-certificate-chain).
   - **Storage authorization errors** (`AuthorizationPermissionMismatch`): the job's
     managed identity lost its role on the `raw` container. Restore it, then start a run by hand.
   - **404 on a page**: the site moved the page. Find the new URL, update the sources
     file, and release a new image.
4. After fixing, [start a run by hand](#start-a-run-by-hand). The check turns **up** again
   when the run succeeds.
