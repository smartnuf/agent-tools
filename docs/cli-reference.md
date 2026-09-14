# CLI reference

Generated from the public argparse definitions; do not edit by hand.
This describes the current source/next release, not necessarily the published version.

Regenerate from a development checkout with `bin/agent-python -m agent_tools.cli_reference --write docs/cli-reference.md` (Windows: use `bin\agent-python.cmd`).

## agent-tools

```text
usage: agent-tools [-h] [--version] {install,doctor,tools,integrations} ...

Discover workstation capabilities, install named native tools, and manage desired
configuration and supported agent integrations. Read-only commands need no
authorization; mutations require their dedicated flag.

positional arguments:
  {install,doctor,tools,integrations}
    install             Install only named native capabilities with explicit
                        authorization.
    doctor              Inspect optional document libraries and default native tools
                        without changing the host.
    tools               Inspect capabilities or configure optional desired capabilities.
    integrations        Inspect or manage explicitly supported agent integrations.

options:
  -h, --help            show this help message and exit
  --version             show the installed application version and exit

Use COMMAND --help for its purpose, safety requirements and exit statuses. Help and
version return 0 without operational work; invalid syntax returns 2. Application
installation, upgrade and removal are managed by uv tool.
```

## agent-tools install

```text
usage: agent-tools install [-h] [--allow-provider-mutation | --dry-run]
                           {poppler,ghostscript,bash} [{poppler,ghostscript,bash} ...]

Discover and plan only the named capabilities, honoring their exact stored provider
preferences. Other enabled capabilities are not added. Print the plan before execution;
configuration is never changed. Already-satisfied capabilities are verified no-ops.

positional arguments:
  {poppler,ghostscript,bash}
                        built-in capability identities; repeated names are requested
                        once

options:
  -h, --help            show this help message and exit
  --allow-provider-mutation
                        authorize the displayed native package-manager plan and managed
                        provenance write; without this flag, a nonempty plan is refused
                        (default: no authorization)
  --dry-run             display a read-only discovery/plan without execution or
                        provenance writes

Exit status: 0 = verified success/no-op (or a produced dry-run plan); 1 = planning,
authorization, execution, verification or provenance failure; 2 = invalid arguments; 130
= interrupted. Partial or uncertain results include recovery guidance; do not blindly
retry.
```

## agent-tools doctor

```text
usage: agent-tools doctor [-h] [--documents]

Inspect optional document libraries and default native tools without changing the host.

options:
  -h, --help   show this help message and exit
  --documents  require the full optional document-library stack (default: False)

Document availability is reported separately and does not affect the default exit
status. --documents requires all seven document libraries. Both modes check default
native capabilities (Poppler and Ghostscript); no packages or configuration are changed.
Exit status: 0 = all required checks pass; 1 = a required check needs attention; 2 =
invalid syntax.
```

## agent-tools tools

```text
usage: agent-tools tools [-h] {list,status,enable,disable} ...

Inspect capabilities or configure optional desired capabilities.

positional arguments:
  {list,status,enable,disable}
    list                List the built-in capability catalogue without probing or
                        changing the host.
    status              Inspect detected capability availability, desired state and
                        mutation provenance without writes.
    enable              Enable an optional desired capability without installing a
                        provider.
    disable             Disable an optional desired capability without removing any
                        provider package.

options:
  -h, --help            show this help message and exit
```

## agent-tools tools list

```text
usage: agent-tools tools list [-h]

List the built-in capability catalogue without probing or changing the host.

options:
  -h, --help  show this help message and exit

Exit status: 0 = catalogue displayed.
```

## agent-tools tools status

```text
usage: agent-tools tools status [-h] [capability]

Inspect detected capability availability, desired state and mutation provenance without
writes.

positional arguments:
  capability  built-in capability identity (default: inspect all capabilities)

options:
  -h, --help  show this help message and exit

Exit status for one capability: 0 = available; 1 = absent; 2 = unknown or unsupported.
Without a capability: 0 = all default required capabilities available; 1 = a default
capability is unavailable. Configuration/provenance read errors are reported separately
and do not change the availability status.
```

## agent-tools tools enable

```text
usage: agent-tools tools enable [-h] [--provider PROVIDER] [--allow-config-mutation]
                                capability

Enable an optional desired capability without installing a provider.

positional arguments:
  capability            optional built-in capability identity (see tools list)

options:
  -h, --help            show this help message and exit
  --provider PROVIDER   exact built-in provider preference; no fallback (default:
                        catalogue order)
  --allow-config-mutation
                        authorize desired-state configuration writes (default: False)

Changes require --allow-config-mutation and back up existing configuration. Unrelated
valid entries are preserved. Exit status: 0 = changed or already enabled; 1 = refused or
failed (including invalid capability/provider). Ctrl+C: after the supported
cancellation/recovery path, an uncaught KeyboardInterrupt terminates CPython via SIGINT
on POSIX (shell status 130; Python subprocess returncode -2). On Windows CPython it
returns 0xC000013A (3221225786 unsigned or -1073741510 signed). A reported recovery
failure instead returns 1. A second Ctrl+C may force-abort recovery.
```

## agent-tools tools disable

```text
usage: agent-tools tools disable [-h] [--allow-config-mutation] capability

Disable an optional desired capability without removing any provider package.

positional arguments:
  capability            optional built-in capability identity (see tools list)

options:
  -h, --help            show this help message and exit
  --allow-config-mutation
                        authorize desired-state configuration writes (default: False)

Changes require --allow-config-mutation and back up existing configuration. Unrelated
valid entries are preserved. Exit status: 0 = changed or already disabled; 1 = refused
or failed (including invalid capability). Ctrl+C: after the supported
cancellation/recovery path, an uncaught KeyboardInterrupt terminates CPython via SIGINT
on POSIX (shell status 130; Python subprocess returncode -2). On Windows CPython it
returns 0xC000013A (3221225786 unsigned or -1073741510 signed). A reported recovery
failure instead returns 1. A second Ctrl+C may force-abort recovery.
```

## agent-tools integrations

```text
usage: agent-tools integrations [-h] {claude-code} ...

Inspect or manage explicitly supported agent integrations.

positional arguments:
  {claude-code}
    claude-code  Manage Claude Code Git Bash selection on a native Windows host.

options:
  -h, --help     show this help message and exit
```

## agent-tools integrations claude-code

```text
usage: agent-tools integrations claude-code [-h] {status,apply,remove} ...

Manage Claude Code Git Bash selection on a native Windows host.

positional arguments:
  {status,apply,remove}
    status              Read Claude Code settings and separate integration state without
                        writes.
    apply               Apply the verified Git Bash path to Claude Code settings on
                        native Windows.
    remove              Restore the prior Claude Code setting for an Agent Tools-managed
                        integration.

options:
  -h, --help            show this help message and exit
```

## agent-tools integrations claude-code status

```text
usage: agent-tools integrations claude-code status [-h]

Read Claude Code settings and separate integration state without writes.

options:
  -h, --help  show this help message and exit

Exit status: 0 = state inspected; 1 = unsupported context or unreadable/invalid
integration state.
```

## agent-tools integrations claude-code apply

```text
usage: agent-tools integrations claude-code apply [-h] [--allow-config-mutation]

Apply the verified Git Bash path to Claude Code settings on native Windows.

options:
  -h, --help            show this help message and exit
  --allow-config-mutation
                        authorize Claude Code settings and integration-state writes
                        (default: False)

Changes require --allow-config-mutation. Back up existing settings, preserve unrelated
entries and report recovery evidence. Never install or remove provider packages; an
unowned setting is not claimed. Exit status: 0 = completed or no changes; 1 = refused or
failed, including unsupported context or unresolved recovery. Ctrl+C: after the
supported cancellation/recovery path, an uncaught KeyboardInterrupt terminates CPython
via SIGINT on POSIX (shell status 130; Python subprocess returncode -2). On Windows
CPython it returns 0xC000013A (3221225786 unsigned or -1073741510 signed). A reported
recovery failure instead returns 1. A second Ctrl+C may force-abort recovery.
```

## agent-tools integrations claude-code remove

```text
usage: agent-tools integrations claude-code remove [-h] [--allow-config-mutation]

Restore the prior Claude Code setting for an Agent Tools-managed integration.

options:
  -h, --help            show this help message and exit
  --allow-config-mutation
                        authorize Claude Code settings and integration-state writes
                        (default: False)

Changes require --allow-config-mutation. Back up existing settings, preserve unrelated
entries and report recovery evidence. Never install or remove provider packages; an
unowned setting is not claimed. Exit status: 0 = completed or no changes; 1 = refused or
failed, including unsupported context or unresolved recovery. Ctrl+C: after the
supported cancellation/recovery path, an uncaught KeyboardInterrupt terminates CPython
via SIGINT on POSIX (shell status 130; Python subprocess returncode -2). On Windows
CPython it returns 0xC000013A (3221225786 unsigned or -1073741510 signed). A reported
recovery failure instead returns 1. A second Ctrl+C may force-abort recovery.
```
