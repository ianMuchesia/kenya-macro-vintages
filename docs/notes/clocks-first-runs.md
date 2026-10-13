# Clocks: first Azure runs

## Clock 1 (`job-clock1`, `sources.yaml`)
- 2026-10-10, manual: Succeeded (~28 min)
- 2026-10-11, 06:00 EAT scheduled: Succeeded (~22 min)
- 2026-10-12, 06:00 EAT scheduled: Succeeded (~36 min), 12/12 sources ok

Runs take ~22-36 min.

## Clock 2 (`job-clock2`, `sources-regulatory.yaml`)
- 2026-10-13, first run: 7/7 sources ok.
- One file failed: CBK Banking Circular No. 11 of 2023 (Request for Information on
  Unlicensed or Unauthorized MVTS) got HTTP 403. The block comes from CBK's Sucuri
  firewall and happens from any network, not just Azure. The file is retried and
  logged on every run, which is expected.

## Cost
Cost to date (Oct 2026): < USD 0.01, per Azure Cost Management.
