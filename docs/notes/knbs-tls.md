# KNBS TLS failure — 2026-10-09
Symptom: CERTIFICATE_VERIFY_FAILED on all knbs.or.ke sources; browser fine.
Diagnosis: server sends only the leaf (openssl s_client: one cert, code 21).
Chain is Let's Encrypt Gen Y: leaf → YE2 → ISRG Root YE, which isn't in
trust stores yet. Root YE is cross-signed by ISRG Root X2, which is trusted.
Fix: ship certs/knbs-chain.pem (YE2 + Root YE by X2), add it to certifi's
roots. Verification stays on. Rejected: verify=False (would accept forged data).
Expiry: unnecessary once Root YE reaches trust stores; re-check if KNBS fails again.