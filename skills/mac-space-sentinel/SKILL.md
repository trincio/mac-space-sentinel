---
name: mac-space-sentinel
description: Analyze and safely plan macOS storage recovery with Mac Space Sentinel. Use when Codex must inspect APFS capacity, find large folders/files, interpret Sentinel JSON or SQLite reports, create a review-only cleanup plan, or operate the Sentinel through a bounded SYNODAI connector. Never use this skill to delete or purge storage without an explicit reviewed plan and a separate user confirmation.
---

# Mac Space Sentinel

Use the Sentinel CLI as the source of disk facts. Treat its scanner as read-only.
Resolve the project root from `MAC_SPACE_SENTINEL_ROOT`, or use the current Git
repository root when it contains `mac-space-sentinel.sh`.

## Analyze

1. Run `./mac-space-sentinel.sh doctor`. Do not run `doctor --install-tools`
   unless a human is present to answer its TTY prompt.
2. Start with the target user's home directory. Use `/System/Volumes/Data` only
   for a system-level view, and keep mounted external/network volumes excluded.
3. Read the emitted `report-*.json`, not just terminal text. State whether
   `inventory.incomplete` is true.
4. Rank `top_level_directories_recursive` before individual large files. Then
   scan one high-value directory at a time (for example `.cache` or `Library`).
5. Separate user media/archives from rebuildable data. Never infer that an APFS
   snapshot or “purgeable” capacity is deletable user data.

If free physical capacity is below 15 GiB, use `--profile low-space` (or leave
the default `auto`). Do not create broad repeated reports or SQLite history.

## Explain through the TUI

Generate `assessment-template` from the chosen report. Use its evidence IDs in
your findings and distinguish measured fact, inference, uncertainty, and action.
Pass a concise packet to `tui`; the user owns the numbered selection and its
confirmation. Read the emitted `tui-decision-*.json` before continuing.

For Photos, offer only `photos-icloud-guidance`: it opens Photos for the user to
review iCloud Photos and Optimize Mac Storage. Never modify a `.photoslibrary`
package or claim that cloud optimization frees a precise immediate amount.

Example:

```zsh
./mac-space-sentinel.sh scan --root "$HOME/.cache" --output ./reports/cache --min-file-mib 64
```

## Plan and act

`--yolo` means scan and plan only. It never applies a change.

The generated `review-plan-*.json` intentionally has no actions. Explain the
candidate evidence and ask the human to select precise files first. For an
approved plan, run the executor with `--dry-run` before a real run. The only
supported effect is `move_to_trash`; it refuses system paths, iCloud, keys, and
paths outside the current home directory. Do not invent shell deletion commands.

## SYNODAI mode

Use the generic connector at `integrations/synodai/` instead of exposing shell
access to the model. The SYNODAI host owns an allowlist of roots and a dedicated
output sandbox; the model may request only `scan`. Read
`references/synodai-connector.md` before wiring or changing that adapter.

Do not grant `apply`, `move_to_trash`, Homebrew installation, or arbitrary
subprocess execution to a SYNODAI model. Require a separate host-owned,
human-approved effect capability if those are ever introduced.
