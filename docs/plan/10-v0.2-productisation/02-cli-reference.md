# #106: One command definition for help and reference

Base: `c436c92fa6eb49819bd4a7ebb39723f089fcf532`.
Milestone: [v0.2 productisation](https://github.com/smartnuf/agent-tools/milestone/8).
Acceptance: generated CLI reference and help/example drift prevention (gate 8).
Estimate: 0.25–0.75 person-day excluding CI/review; actual effort is untracked.

## Discovery and contract

The existing argparse tree defines all public commands. `install` has descriptive
safety/exit help; most nested commands have only parent-menu labels. No reference
is generated. Installed checks cover several help pages but do not traverse the
tree or compare source help. README and platform guides contain concrete fenced
invocations and inline syntax/command fragments.

This is a read-only documentation/public-help change with low mutation risk.
Do not change parser acceptance, defaults, dispatch, authorization or exit
behavior. Document actual semantics, including tools status availability-based
statuses and separate state-read diagnostics. Python's
[argparse formatting API](https://docs.python.org/3.11/library/argparse.html#formatter-class)
supports direct help generation; no new dependency/framework is required.

Use `build_parser()` as the single authoritative command model. Enrich its
purpose, argument/default/safety and exit-status descriptions; reuse each
purpose in the parent menu and child help. Render every root/nested parser's
`format_help()` into committed Markdown in deterministic traversal order with
fixed-width formatting. Isolate argparse tree introspection in one helper.
Runtime help and generated reference therefore consume identical descriptions,
options, choices and defaults. Keep the reference free of machine paths,
terminal width and application-version-dependent text.

Check concrete fenced `agent-tools` invocations (including README launcher
variables) in README/platform/packaging guides with the parser only. Never
execute mutation examples. Inline syntax fragments with placeholders remain
conceptual prose and are not shell commands. Test the extractor's scope and
reject invalid/renamed commands. Do not invent a second command/example list.

Traverse every root/nested `-h` and `--help`, proving success without invoking
operational handlers or touching config/provider state. Compare installed help
to source projections outside a checkout. Validate the generated reference and
guide examples in required CI and before release artifact publication. Test
that changes to command/default/help metadata invalidate an old reference.

## Execution plan

1. Commit this plan and mark the selected milestone gate in progress.
2. Improve the parser descriptions and add the small help-tree renderer/checker.
3. Generate the reference; add source, example and installed-wheel drift tests;
   wire release checks and document regeneration. Add the short owner-requested
   AGENTS.md invariant once checks prove it.
4. Run unit tests, available platform syntax/PATH checks, doctor, artifact build
   and installed checks; obtain exact-head CI and automated review. Use at most
   six correction waves with focused commits and one push per complete wave.
5. Merge through the protected exact-head gate and reconcile milestone evidence.

This stream owns integration. No concurrent implementation stream is active.
Dependency changes (#57), platform/provider expansion (#104), publication and
future research remain outside scope. Recommend #57 next; estimate that task
from its own discovery rather than extrapolating this documentation slice.
