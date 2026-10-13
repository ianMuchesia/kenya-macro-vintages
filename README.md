# kenya-macro-vintages

Daily captures of Kenyan macro and regulatory publications (CBK, KNBS, Kenya Law),
kept as write-once "vintages" so that later revisions and corrections can be seen.

## Status

Both clocks run daily in Azure Container Apps and save to Blob storage:

- **Clock 1** (`job-clock1`): macro data from `sources.yaml`, 06:00 EAT.
- **Clock 2** (`job-clock2`): regulatory documents from `sources-regulatory.yaml`, 06:30 EAT.

Each run pings Healthchecks and sends a Telegram alert if any source fails.
How to operate them: [docs/runbook.md](docs/runbook.md).
