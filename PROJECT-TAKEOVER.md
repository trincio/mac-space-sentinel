# Mac Space Sentinel — Project Takeover

**Status:** active prototype; do not describe the current terminal menu as the
target UI.  
**Repository:** the public Mac Space Sentinel repository
**Local root:** the active repository checkout
**Baseline before the next substantial redesign:** commit `1343127`  
**Safety snapshot:** a sibling backup created by the canonical project-snapshot workflow

## 1. Why this project exists

The startup APFS container is only about 10% physically free. macOS aggregates
storage in ways that are hard to interpret: System/Data/snapshots share APFS
capacity, “purgeable” is not guaranteed free space, and the largest bytes are
not automatically safe to remove.

Mac Space Sentinel must make storage work understandable and safe when driven
by Codex, Claude, Antigravity, or SYNODAI. It is not a generic disk cleaner.
It is an evidence system plus a human-gated decision system.

## 2. Product objective

The intended experience is:

```text
LLM asks Sentinel for bounded evidence
  -> Sentinel measures and returns aggregate/detail artifacts
  -> LLM explains facts, inferences, uncertainty, alternatives, and risks
  -> UI shows a concise but complete decision cockpit
  -> user selects/clarifies/approves
  -> Sentinel performs only the separately authorized reversible action
  -> LLM reads the receipt, verifies outcome, and continues
```

The LLM is the analytical guide and narrator. The UI is the trustworthy human
display and consent boundary; it must not be the “brain”.

## 3. User requirements and non-negotiables

- Let an LLM launch the application, investigate at aggregate and detailed
  levels, explain what is happening, and communicate a grounded evaluation.
- Let the LLM send an assessment packet to the UI; the user must be able to
  choose amongst well-explained actions there.
- Work with generic agents and SYNODAI, not only one provider.
- Support aggressive/YOLO analysis, but never turn YOLO into unreviewed
  deletion, broad shell access, package installation, or hidden cloud changes.
- Make low-space behavior self-protecting: bounded reports, bounded logs, no
  large duplicate artifacts, and refusal of risky work when space is critical.
- Treat iCloud/Photos as guided settings workflows. Never edit the contents of
  a `.photoslibrary` package or claim immediate guaranteed reclaimed bytes.
- Before substantial changes, create a non-destructive `project-snapshot` and
  declare its use in the shared-skill usage log.

## 4. What exists now

### Core CLI

`mac-space-sentinel.py` is standard-library Python with a zsh launcher.

- `doctor`: detects native and optional tools; installation requires a real TTY
  confirmation.
- `scan`: inventories a root, provides APFS/filesystem facts, ranked top-level
  folders and large files, JSON reports, review plans, and optional SQLite
  history.
- `apply`: can only move explicitly verified regular-file candidates to Trash;
  it requires a report-bound plan, dry-run receipt and confirmation.
- `assessment-template`: emits `mac-space-sentinel.assessment/v1` evidence
  packet derived from a report.
- `tui`: a minimal terminal menu that can open a new macOS Terminal window and
  write a user-decision JSON.

### Existing safety work

- Scans do not follow symlinks and do not cross mounted filesystems by default.
- `--profile auto` becomes `low-space` below 15 GiB **or** 15% free. That mode
  caps the walk at 100,000 files, caps rankings at 100, omits SQLite history,
  and caps JSON artifact size (default 5 MiB).
- Cleanup is not exposed through the SYNODAI connector.
- Existing reports are ignored by Git.

### Agent integrations

- Codex skill: `skills/mac-space-sentinel/`; install or link it below the local
  Codex skills directory when needed.
- SYNODAI reference adapter:
  `integrations/synodai/mac_space_sentinel_connector.py`.
  It allows only fixed-argv, host-granted `scan`, with constrained roots/output
  and report/executable hashes.
- SYNODAI proposal: `SYNODAI-INTEGRATION.md`.

## 5. Private-run findings

Machine-specific paths, directory names, sizes, report IDs, backup locations,
and active-process observations belong only in `LOCAL-CLAUDE-HANDOFF.md` or
another ignored local note. Re-scan before making any action. A representative
private run found large media, application-library, model-cache and browser-
automation-cache areas; this informed the fixture scenarios below but must not
be treated as public or current project data.

## 6. Honest assessment of the current TUI

The current `tui` command is only a **smoke-test terminal menu**, not the
desired product. It successfully proved:

1. a separate Terminal can be opened (`--open-terminal`);
2. a user can select and confirm a card;
3. the app writes `mac-space-sentinel.tui-decision/v1` for the LLM to read;
4. no selected action performs deletion or Photos configuration.

It is not adequate because it does not render the LLM’s diagnosis, evidence,
risk/benefit comparison, follow-up questions, or detailed action cards. Do not
polish that menu incrementally; replace it with the decision cockpit below.

## 7. Target architecture

### A. Sentinel data plane

Expose bounded, cursor/pagination-friendly operations rather than one enormous
report:

- snapshot: APFS, physical free space, thresholds, profile, scan state;
- usage(path, depth): aggregate subdirectory sizes;
- large-files(path, cursor, min-size): ranked file evidence;
- classify(path): cache/media/project/backup/system/application ownership hints;
- estimate(action): potential bytes, reversibility, preconditions and risk;
- evidence(id): immutable fact with source report, timestamp and limitations.

Every result needs an ID, byte budget, truncation/incomplete flag, and
provenance. The LLM must not invent an estimate not grounded in evidence.

### B. LLM assessment plane

Define a strict `assessment/v2` packet. It should have:

- `headline` and short status;
- findings split into `measured_fact`, `inference`, and `uncertainty`;
- evidence IDs per claim;
- action cards with potential/recoverable bytes, risk, reversibility,
  prerequisites, and user-facing explanation;
- questions the user can answer to refine the plan;
- no executable shell text or arbitrary effect instructions.

The UI validates report hash and evidence IDs before displaying the packet.
LLM prose should be length-bounded and shown as untrusted presentation data.

### C. Human decision cockpit (replace current TUI)

Choose a genuinely usable terminal UI framework or a local-only web UI. The
product requirement is interaction quality, not loyalty to ANSI menus.

It must show:

- current capacity, severity, low-space state and scan completeness;
- LLM diagnosis plus explicit uncertainty;
- grouped cards such as “inspect Puppeteer versions”, “review Suno incomplete
  download”, “guided Photos/iCloud review”; 
- estimated impact, risk, reversibility and reason for every card;
- drill-down and back navigation;
- explicit approve/reject/defer and a free-text question to the LLM;
- a visible receipt after selection.

The UI writes a structured decision event. It never executes free-form LLM text.

### D. Effect plane

Keep effects separate from analysis:

- read-only scans need no approval;
- planning creates immutable plan hash;
- TUI approval creates a single-use, expiring receipt bound to the plan and
  target fingerprints;
- initial effects may only move verified regular files to Trash;
- any cloud, system-setting, external-drive or package-manager action needs a
  dedicated capability and human gate.

## 8. Photos and iCloud guidance

Use a guided card, never an automatic setting change:

1. Explain measured library size and that it is user media.
2. Ask whether it is the System Photo Library, whether iCloud Photos is active,
   whether originals are downloaded, whether iCloud capacity and a backup exist.
3. Offer to open Photos only after user approval.
4. Explain that iCloud Photos + Optimize Mac Storage can retain optimized local
   versions and free space progressively; it is not a guaranteed immediate GB
   recovery and must not be started blindly in a severe-space emergency.
5. Record a guided-settings decision; the human changes the Photos setting.

## 9. SYNODAI integration direction

Do not add an arbitrary “run CLI” capability to `CapabilityButler`.

Add a host-owned, declarative external capability registry. Each adapter has
fixed argv, executable digest, timeout, output cap, exact request/result schema,
host-selected roots, correlation ID and append-only ledger entries. Sentinel’s
first operations should be read-only `scan`, `usage`, `large-files`, and
`assessment-template`.

For CLI agents, expose the same policy through a narrow stdio MCP server. For
local models, map the same fixed operations through `LocalToolAgent`’s closed
JSON codec and Butler mediation. Effects remain out of this connector.

## 10. Validation and known limitations

- Last implementation commit: `1343127`.
- Automated suite at that commit: 8 tests green (`python3 -m unittest discover
  -s tests -v`).
- The official `skill-creator` validator could not run because the active Python
  lacks PyYAML; manual structure checks and an independent forward-run passed.
- The shared SYNODAI audit previously ran a focused 43-test suite without edits.
- Reports created by live scans are Git-ignored; inspect them manually when
  debugging a handover.
- The current assessment validator is intentionally conservative and action
  cards are template-derived. Replace it with the v2 evidence/action registry
  while retaining hash binding and strict field validation.

## 11. Recommended implementation sequence

1. Snapshot before work; verify clean Git state.
2. Design and implement the bounded data-plane query API plus `assessment/v2`.
3. Build the decision cockpit against fixture reports first; do not use the live
   disk as the primary test fixture.
4. Add rich fixture scenarios for Puppeteer accumulation, Suno models plus an
   incomplete download, Photos, protected paths, low-space and malformed LLM
   packets.
5. Add the UI decision → LLM follow-up loop and receipt validation.
6. Add no more than one new reversible effect after a focused security review.
7. Promote the generic connector into SYNODAI only with host-side tests for
   identity, schema, path boundary, output cap, timeout, audit and deny cases.
8. Run an actual user test; record confusion, missing explanations and unsafe
   assumptions as product bugs, not as user error.

## 12. Useful commands

```zsh
cd <repository-checkout>
./mac-space-sentinel.sh doctor
./mac-space-sentinel.sh scan --root "$HOME/.cache" --output ./reports/cache-drilldown
./mac-space-sentinel.sh assessment-template --report ./reports/<report>.json --output ./reports/assessment.json
./mac-space-sentinel.sh tui --report ./reports/<report>.json --assessment ./reports/assessment.json --open-terminal
python3 -m unittest discover -s tests -v
```

Before a substantial change, use the canonical shared snapshot workflow:

```zsh
python3 <shared-skills-root>/tools/skill_usage_log.py use project-snapshot ...
python3 <shared-skills-root>/tools/project_snapshot.py <label> --project-root <repository-checkout>
```
