# Azure Container Apps: "Express" environment can't run the clocks

Problem: an environment created as **Express** doesn't support **jobs**, and doesn't
support a **system-assigned managed identity**. The clocks need both: a scheduled job,
and an identity to write to Blob storage without a key.

Fix: create the environment in Consumption-only mode instead:

```bash
az containerapp env create -n cae-clocks2 -g rg-clocks --environment-mode ConsumptionOnly
```

That needed the `containerapp` CLI extension at version 1.3.0b5.

Result: `cae-clocks2` hosts `job-clock1` and `job-clock2`, each with a system-assigned
identity that has access to the `raw` container.
