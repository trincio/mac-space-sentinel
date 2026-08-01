# SYNODAI integration proposal

Mac Space Sentinel is ready as an external, read-only connector. The working
reference adapter is `integrations/synodai/mac_space_sentinel_connector.py`.

## Recommended SYNODAI seam

Add a dedicated host-side capability such as `external_inventory_scan`; do not
extend `dry_run` into a generic command runner. Its catalog has a named adapter,
an executable SHA-256 pinned by the host, fixed allowed scan roots, and a
per-correlation output directory under `PLAYGROUND/`.

The model emits one closed-schema request. The host validates it, invokes the
adapter, records its request/response/report hash in the Butler ledger, and
returns a bounded response. This maps naturally to the existing
`LocalToolAgent` JSON codec plus `CapabilityButler` deny-by-default flow.

## Deliberate boundary

The connector exposes `scan` only. Cleanup plans remain files for a human to
review. `apply`, trash moves, app-cache purge, package installation, and shell
access are intentionally absent; adding them needs a separately designed,
human-gated effect protocol—not a looser plugin API.

## First integration test

Use a disposable fixture directory as the only allowed root. Verify one allowed
scan, then verify denial for an out-of-grant root, an extra JSON key, `apply`,
and output traversal. Keep generated artifacts solely under `PLAYGROUND/`.
