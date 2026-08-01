# Mac Space Sentinel

Conservative macOS disk inventory designed for humans and LLM agents. It emits a
machine-readable JSON report, records report history in SQLite, and creates an
empty review plan. The scanner is read-only.

## Quick start

```zsh
./mac-space-sentinel.sh doctor
./mac-space-sentinel.sh scan --root /System/Volumes/Data --output ./reports
```

`--yolo` is deliberately **not** permission to delete. It is an agent-friendly
scan-and-plan mode only:

```zsh
./mac-space-sentinel.sh scan --yolo --output ./reports
```

`--profile auto` switches to **low-space** below 15 GiB or 15% free: it caps the file
walk at 100,000 entries, caps ranked entries at 100, omits SQLite history, and
limits every JSON artifact (default 5 MiB). Use `--profile low-space` to force
that conservative mode.

The output JSON contains filesystem/APFS facts, ranked large files, categories,
errors/incompleteness, and cautious recommendations. `history.sqlite3` supports
diffing or SQL queries across runs. `review-plan-*.json` has no actions by
design; its candidates must be reviewed before a plan is written.

Mounted external and network volumes are not traversed by default, so a scan of
`/System/Volumes/Data` stays on the internal Data filesystem. Add
`--cross-filesystems` only when that broader scope is intentional.

## Safe execution contract

The only implemented action is `move_to_trash`. It requires all of the following:

1. A hand-authored/reviewed `trash-plan` with explicit paths and fingerprints.
2. `--yes-i-understand`.
3. A first `--dry-run` receipt, valid for 30 minutes and bound to the plan hash.
4. Every target must be a regular file from the source report's large-file
   candidates, with the same size and modification timestamp.
5. Every target must resolve inside the current user's home, must not be a
   protected path (`.ssh`, `.gnupg`, Keychains, iCloud Drive, Trash), and must
   exist. Symlink escape is rejected.

The executor never uses `rm`, never empties the Trash, and leaves a JSON journal.
It preflights all actions before moving anything and rolls back prior moves if a
later move fails.

```json
{
  "schema": "mac-space-sentinel.trash-plan/v1",
  "kind": "trash-plan",
  "source_report": "/absolute/path/report-....json",
  "source_report_sha256": "...",
  "actions": [
    {"operation": "move_to_trash", "path": "Downloads/old-installer.dmg", "expected_bytes": 123, "expected_modified_ns": 456}
  ]
}
```

```zsh
./mac-space-sentinel.sh apply --apply-plan reviewed-plan.json --dry-run --yes-i-understand
./mac-space-sentinel.sh apply --apply-plan reviewed-plan.json --receipt dry-run-receipt-....json --yes-i-understand
```

## Optional tools

Core analysis needs only macOS/Python standard tools. `gdu`, `ncdu`, `tree`,
`jq`, and `sqlite3` are detected as optional aids. To install missing optional
tools, the command must be attached to an interactive TTY and asks before it
runs Homebrew:

```zsh
./mac-space-sentinel.sh doctor --install-tools
```

An agent must never send the confirmation automatically.

## LLM assessment and TUI

Generate an evidence-bound assessment packet for an LLM to explain or enrich:

```zsh
./mac-space-sentinel.sh assessment-template --report reports/report-....json --output reports/assessment.json
```

Show it in the current terminal, or explicitly open a separate macOS Terminal
window for the user:

```zsh
./mac-space-sentinel.sh tui --report reports/report-....json --assessment reports/assessment.json
./mac-space-sentinel.sh tui --report reports/report-....json --open-terminal
```

The terminal UI records only a human decision JSON. Its Photos/iCloud choice
opens Photos for guided review; it does not alter Photos settings or touch the
photo-library package.

## Scope and limitations

APFS uses shared capacity: do not add volume numbers together. “Purgeable” space
is not treated as guaranteed free space. This tool intentionally does not clean
system caches, snapshots, Time Machine data, iCloud contents, or developer
projects autonomously—those need owning-app/project semantics.

License: MIT.
