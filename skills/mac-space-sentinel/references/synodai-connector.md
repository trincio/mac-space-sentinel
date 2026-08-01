# SYNODAI connector contract

The connector is a host-side adapter, not a model tool. It accepts one exact
JSON request and launches the Sentinel with a fixed argument vector:

```json
{
  "schema": "mac-space-sentinel.connector-request/v1",
  "operation": "scan",
  "root": "/Users/example/.cache",
  "output_name": "cache-pass",
  "min_file_mib": 64,
  "top": 100,
  "max_files": 200000
}
```

The host supplies `--allowed-root` one or more times and an `--output-base`.
Both are policy, never model-selected. The connector rejects unknown fields,
symlink/parent traversal outside a root, non-`scan` operations, and output names
that are not simple slugs. It emits one response with paths and the report's
`scan_id`/`incomplete` facts.

For SYNODAI, add this as a new *host-owned read-only capability*, not as a
generic `dry_run` command. The capability should:

1. bind the request to the resolved caller identity and correlation id;
2. store output only below a per-run `PLAYGROUND/` directory;
3. pass fixed allowed roots configured by the host;
4. append request, executable digest, response, and report hash to the Butler
   ledger; and
5. expose only a bounded response to the model.

Do not modify `CapabilityButler` to run arbitrary commands. The narrow adapter
must validate the Sentinel’s executable path/digest and use a fixed `python3`
argument vector. Effects remain outside this connector.
