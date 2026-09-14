# 0009: Installed capability installation

- Status: accepted
- Date: 2026-09-14
- Scope: issue #103 public install request and compatibility boundary
- Authority: [human decision on #103](https://github.com/smartnuf/agent-tools/issues/103#issuecomment-5662820905), Decisions 0002–0005 and 0007

## Contract

`agent-tools install CAPABILITY [CAPABILITY ...]` requests only the named
built-in capabilities. Repeated names are deduplicated in first-occurrence
order. Names are catalogue identities, not package-manager names or arbitrary
packages; unknown names and invalid syntax return 2 before discovery.

Load desired configuration through its existing bounded, integrity-checking
reader. Malformed documents, unsupported schemas, and unsafe paths fail closed.
Interpret only entries for named capabilities: honor their exact stored
provider preferences and fail visibly on an invalid or unsupported preference.
Unrelated enabled or unknown entries that have valid schema v1 structure are
outside this request and neither add mutations nor prevent its planning.
Installing does not enable capabilities or write desired configuration.

Clone native bootstrap retains its existing explicit-plus-enabled union and
whole-document semantic validation under Decision 0005. Both consumers share
manager discovery, canonical provider planning, managed execution and reports;
only their request membership differs.

## Authorization, output and statuses

The parser definition is authoritative for syntax and help. The public command
uses `--allow-provider-mutation`, the existing dedicated noninteractive authority
for its displayed provider plan. Confirmation alone is not authority and no
interactive prompt is introduced. Without the flag a nonempty plan is displayed
and refused with status 1; already-satisfied requests are verified no-ops.

`--dry-run` performs discovery and planning, displays the requested capabilities,
exact preferences and manager actions, and returns 0 when a plan can be
produced. It does not enter managed execution, verify a post-install result, or
write provenance/configuration. It cannot be combined with the mutation flag.
A plan is an observation, not a saved executable authorization token.

Normal execution displays and flushes the complete plan before passing it to
`managed_state.execute_provider_plan`. Status 0 requires both verified host
success/no-op and successful or unnecessary provenance persistence. Status 1
means planning, authorization, execution, verification or persistence did not
complete successfully; reports distinguish those facts and preserve recovery
guidance. Interruption returns 130 with any available managed result. These
statuses reuse the existing bootstrap adapter and M3 result predicates.

## Preserved safety and compatibility

Decisions 0002–0004 remain authoritative for machine/manager identity, privilege,
bounded process lifetime, per-action revalidation, mandatory rediscovery and
final verification, append-only request provenance (not ownership), state
preservation, cancellation and partial/uncertain outcomes. Never automatically
retry an uncertain result or infer provider removal/rollback authority.
Already-satisfied requests require no manager or mutation/provenance write;
execution still verifies that the plan's observations remain valid.

No new package mapping, provider, persistent schema, config-path option,
translated-provider override, cross-process lock, self-updater, uninstall,
file-driven install or other future-research interface is introduced.

The wheel and sdist exclude repository `bin/` and `scripts/` entry points.
The sdist is a minimal rebuildable application source payload; checkout-only
tests and maintenance infrastructure stay in Git. Useful checkout entry points
remain available there, outside the ordinary-user compatibility surface.

## Evidence required

Tests cover named-only scope with unrelated enabled/unknown entries, exact
preferences, malformed config, duplicate/unknown names, no-op without a manager,
dry-run and unauthorized nonmutation, failure/persistence/interruption reports,
managed executor delegation, and installed-artifact operation outside a checkout.
Existing M3 fixtures continue to supply process, provenance and failure evidence.
Real-provider CI expansion belongs to #104. Generated reference/help drift
prevention belongs to #106 and must consume the existing argparse model.
