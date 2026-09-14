# Native outcome reporting on encoded streams — #120

- Base: `6ae3bec9b40602cdba844faa6fc26f61fe371794` (merged #119).
- Milestone 8 open, 4/8 gates. Focused prerequisite for #115/#104.
- Estimate: 0.25–0.5 person-day, excluding review/CI wait; actual effort untracked.
- One merge owner; PR #117 stays unmerged until end-to-end Windows proof passes.

## Evidence, scope and contract

[Run 34872132255](https://github.com/smartnuf/agent-tools/actions/runs/34872132255),
PR #117 head `85136fd03c4e71dee26bc8e8669b9a13c9593c68`, demonstrates real WinGet
Poppler installation, final verification and persisted success provenance. The
installed CLI then raises UnicodeEncodeError in `report_result` when its cp1252
stdout pipe cannot encode WinGet progress blocks. This is a reporting defect,
not an installer failure or successful end-to-end test. Do not retry or force
UTF-8 only in the fixture to hide it.

Complete the existing native plan/result/error reporting contract using a local
text-output helper: retain characters representable by the selected stream,
escape unencodable characters with the standard backslash replacement codec,
and leave UTF-8 and encoding-free StringIO text unchanged. Apply the same rule
to output tails, executable paths, errors and recovery guidance so the complete
mutation/provenance report and existing exit status survive. Do not reconfigure
process-global streams, catch unrelated write failures, change persisted command
evidence, introduce retry behavior or change provider/authorization policy.

This is a bounded rendering correction, not a public product-policy expansion.
The observed cp1252 failure and strict in-memory text-stream experiment determine
the implementation; no new platform abstraction or dependency is needed.

## Plan and validation

1. Add the shared native reporting helper and use it for stdout/stderr reports.
2. Test strict ASCII/cp1252 streams with Unicode output, paths and recovery facts;
   verify success/partial-result exit statuses and unchanged in-memory evidence.
   Verify UTF-8 behavior and that unrelated I/O errors still propagate.
3. Run the full baseline, workflow/POSIX checks, build/installed CLI validation,
   ranged diff check, hosted Windows evidence and exact-head review. Keep this
   prerequisite separate from the already review-sized mutation fixture PR.
4. Merge only after exact-head convergence, then rebase #117 and require actual
   mutation, provenance, fresh rediscovery and byte-preserving no-op repetition.

No native package is installed on this workstation. The existing Windows probe
qualifies read-only identity; #117 supplies actual mutation proof afterward.
