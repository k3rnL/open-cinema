## Context

Open Cinema currently discovers `ApplicationPlugin` and `ProcessingPlugin` Python entry points
inside the main application environment. The registry already validates IDs and contract ranges,
isolates discovery and lifecycle failures, publishes a catalogue, and prevents audio-backend
ownership. Application URLs are appended during Django startup, processing schemas are registered
with the graph catalogue, and neither contract can presently contribute admin navigation or pages.

The administration client is a separately built Refine/React application whose routes and menu are
currently static. The appliance deployment uses a locked `uv` environment and allowlisted systemd
control helpers. Mutating that live environment from a Gunicorn request would undermine both
release reproducibility and rollback. Python entry points and Django application structure also
mean that newly installed backend code cannot safely become active in an already running process.

See `proposal.md` for motivation and the delta specifications for observable behavior.

## Goals / Non-Goals

**Goals:**

- Evolve the existing registry, diagnostics, entry-point, and typed-schema work into one public
  plugin distribution contract.
- Let one plugin package contribute several bounded capabilities under one identity.
- Make first-party and explicitly trusted Git plugins installable without modifying the checked-out
  Open Cinema source or rebuilding the frontend.
- Keep the base Open Cinema Python environment locked while making plugin generations atomic and
  recoverable.
- Give declarative plugin pages enough composition primitives to look intentional rather than like
  an automatically dumped JSON schema.
- Preserve core authentication, host control, presentation, PipeWire observation, endpoint
  ownership, and final reconciliation authority.

**Non-Goals:**

- A public, remotely administered marketplace, payments, ratings, or publisher accounts.
- Sandboxing arbitrary in-process Python code. Installing a third-party plugin is a trust decision.
- Runtime-loaded JavaScript, plugin CSS, arbitrary HTML, or a stable React component ABI.
- Arbitrary apt packages, systemd units, root scripts, or host mutation from Git plugins.
- A general dependency solver that permits plugins to replace core runtime packages.
- Preserving the version-1 plugin entry-point contract or existing counter data.
- Supporting plugin-owned Django model packages in contract version 2. Plugins use the core
  namespaced configuration, secret, document, instance, and operation storage contracts; a future
  isolated plugin-host design can revisit private relational stores.

## Decisions

### 1. Use one version-2 distribution manifest with capability contributions

Every plugin distribution contains a static `open-cinema-plugin.toml` and one
`open_cinema.plugins` Python entry point. The static manifest is available in a source checkout or
built wheel before runtime activation. The loaded object returns typed capability contributions;
its identity and version must match the static manifest.

The manifest contains:

- plugin ID, distribution name, vendor, version, license, source, documentation, and release data;
- plugin-contract, Open Cinema, Python, OS, architecture, and capability-version ranges;
- permissions and external requirements;
- configuration version and migration declarations;
- lifecycle impact for install, enable, disable, update, and uninstall;
- capability summaries and a digest of declarative contribution files.

Initially supported runtime capabilities are namespaced API routes, automations, processing node
types and drivers, managed-resource providers, managed-audio-source providers, and declarative
admin UI contributions. Capability IDs are globally namespaced beneath the plugin ID. The registry
stores health per capability and derives the distribution's aggregate health.

This replaces the two mutually exclusive version-1 record kinds, which currently prevent one
plugin ID from naturally combining application and processing behavior. The existing dataclasses,
schema validation, compatibility checks, failure diagnostics, typed processing hooks, and core
audio prohibitions are retained and moved beneath the common distribution record. A compatibility
loader was rejected because there are no third-party consumers and it would make the first public
contract harder to reason about.

### 2. Use core-owned generic persistence instead of dynamically registered Django models

Core migrations add records for installed distributions, desired/observed plugin state, manifest
snapshots, source provenance, active generation, operations, namespaced configuration documents,
repeatable resource instances, secret references, and diagnostics. Plugins access these through a
bounded context/API rather than importing arbitrary core models.

This avoids changing `INSTALLED_APPS`, running unreviewed schema migrations during marketplace
installation, or retaining model classes after hot disable. The bundled counter example is
rewritten against namespaced plugin storage and its old development data is intentionally dropped.
Configuration migrations execute as pure version-to-version document transforms and are validated
before the active document changes.

Secrets are stored separately from ordinary JSON. Read APIs return only presence and replacement
metadata; runtime contexts can resolve a secret only for the owning enabled plugin. Values and
command arguments are redacted from operations, diagnostics, and logs.

### 3. Install plugins into immutable overlay generations

The locked base Open Cinema virtual environment remains untouched. An allowlisted plugin-control
helper builds a clean overlay generation beneath a dedicated application-owned data directory. A
generation contains all installed plugin wheels and their resolved non-core dependencies, a
manifest index, provenance records, and an environment fingerprint.

Resolution uses exported core constraints and rejects any plugin that requires replacement of a
core package. The runtime appends the selected overlay site-packages after core site-packages before
plugin discovery. A `current` pointer is switched atomically only after the candidate generation
passes static manifest, import, contract, and catalogue checks. Old generations are retained within
a bounded rollback policy.

Why not install directly into the main venv: it would make Ansible, plugin installation, and
rollback compete for the same files. Why not use one venv per plugin: in-process contributions
cannot import isolated dependencies reliably, and an RPC plugin-host protocol would multiply the
scope. Why not rebuild the complete base venv: it is safer than mutation but slower and duplicates
the deployment release; the constrained overlay provides the needed atomic boundary for this
version.

All installed plugin code is present after an application restart, including disabled plugins, so
an eligible capability can later be enabled hot. Import itself executes Python, which is why
installation—not enablement—is the trust boundary. Runtime start hooks and routes remain gated by
desired enabled state.

### 4. Separate persistent operations from the process that may restart

Plugin mutations use a serialized operation state machine:

```
requested -> acquiring -> validating -> resolving -> staging
          -> restart-pending -> activating -> verifying -> succeeded
                                      \-> rolling-back -> failed
```

The Django API creates and observes operation records. A bounded background worker performs
ordinary acquisition and validation. Only a fixed privileged helper can create/switch generations
or request allowlisted service/host transitions. Arguments are structured identifiers and paths
resolved from server-owned state; URLs, plugin commands, and service names are never passed through
to a shell.

Every stage is idempotent and records its input generation and expected output generation. Startup
recovery finalizes an operation after the expected application restart, verifies registry and
capability health, and requests rollback when verification fails. One appliance-wide environment
mutation runs at a time, while read operations and plugin-owned resource actions remain available.

### 5. Model lifecycle impact per operation, not as one plugin-wide flag

Each of install, enable, disable, update, and uninstall declares one of:

- `hot`: safe in the current processes;
- `application-restart`: restart the Open Cinema API, worker, and orchestrator set;
- `host-reboot`: require an explicitly confirmed appliance reboot after staged activation.

Core raises the effective impact when the actual change needs more. A new Python distribution
always needs at least `application-restart`. Plugins with processing, managed-source, active
operation, or route state must implement bounded stop/observe semantics before declaring hot
disable. Host reboot is reserved for allowlisted first-party integrations; a Git plugin cannot
turn its own declaration into privileged host access.

The operation API never automatically performs a host reboot. It reaches `restart-pending`, exposes
the existing guarded appliance action, and resumes verification after the administrator confirms
it. The UI labels application restart and Raspberry Pi reboot separately.

### 6. Serve a core-owned first-party catalogue and inspect Git sources in staging

The initial catalogue is a reviewed data file released with Open Cinema. Records contain plugin ID,
publisher, repository, pinned release/source reference and digest when available, compatible
versions, summary, icon key, and documentation links. The API joins this with installed state and
the candidate's verified manifest. Catalogue records never override artifact identity.

Git installation accepts HTTPS repository URLs and an optional revision. Acquisition resolves and
records the exact commit. Mutable refs remain allowed for development but receive a stronger
non-reproducibility warning. Source builds happen in a staging directory as the unprivileged Open
Cinema service account; because Python builds can execute code, the explicit trust confirmation
occurs before build, not merely before activation.

The install contract permits only Python/plugin-overlay contents. External executables can be
included in a platform wheel and declared as plugin assets. Generic Git plugins cannot install host
packages or units. First-party host prerequisites require a separately reviewed core/deployment
installer identifier.

### 7. Render declarative pages from semantic templates

The authenticated plugin catalogue API returns validated UI descriptors only for enabled plugins.
The admin app loads them after session initialization and registers navigation/resources in Refine
while a stable catch-all plugin route resolves `/plugins/:pluginId/:pageId`. Descriptor responses
use schema versions, ETags, and bounded sizes so unchanged navigation does not delay every page.

The UI contract has two layers:

1. Data: Draft 2020-12 JSON schemas, endpoint bindings, collection fields, actions, operation
   status, permissions, freshness, and secret-presence semantics.
2. Presentation: page template, section/card/tab hierarchy, field widgets, order, emphasis, help,
   conditional visibility, and semantic width hints.

Product-owned templates include settings, resource list/detail, overview/status, and guided flow.
Product-owned fields cover normal scalar, enum, multiselect, duration, path, URL, secret,
repeatable, and nested-group cases. The UI owns exact Ant Design components, overlays, typography,
spacing, responsive breakpoints, accessibility, loading placeholders, error boundaries, and
reserved feedback regions. Unknown templates or widgets fail closed for that page. There is no raw
JSON fallback for a field the contract cannot safely represent.

This is intentionally richer than a generic schema form but narrower than arbitrary React. If a
future plugin proves the templates insufficient, the contract is extended semantically before a
remote-code mechanism is considered.

### 8. Keep plugin API and action boundaries core-enforced

Plugin APIs mount beneath `/api/plugins/<plugin-id>/...` through a core wrapper that checks session,
CSRF/method policy, installed/enabled state, capability health, and namespace before dispatch. The
wrapper also converts uncaught failures and timeouts to correlated plugin diagnostics. Plugin
actions return the same server-advertised action descriptors and persistent operation references
used by core managed resources.

Permission declarations are disclosure and compatibility metadata, not a claimed Python sandbox.
In-process code runs as the Open Cinema service user and can access whatever that Unix identity can
access. The deployment therefore keeps the service unprivileged, exposes only fixed host-control
helpers, and makes the Git confirmation explicit. A future out-of-process host can turn permissions
into enforcement without changing the administration descriptors.

### 9. Treat managed audio sources as typed contributions, not audio backends

The platform defines a managed-audio-source capability for long-lived plugin-owned sources. The
plugin owns only its declared process/resource instances and produces stable correlation facts for
PipeWire nodes. Core remains responsible for observing PipeWire through WyrePlumber, validating
signal contracts, choosing routes, applying target metadata or owned links, and explaining the
resolved graph.

The capability declares instance schema, source signal contract, lifecycle hooks, correlation
keys, health, and supported actions. It cannot enumerate arbitrary devices or select a global audio
backend. This contract is introduced here so the librespot plugin does not need a private core
integration, while librespot-specific behavior remains in its separate change.

### 10. Publish a small SDK and contract-test package

Core exports manifest/capability dataclasses, JSON schemas, validation helpers, frozen runtime
contexts, action/result types, and pytest contract suites. Documentation defines the package
layout, manifest and entry point, namespace rules, UI templates, storage APIs, lifecycle/retry
semantics, source and processing boundaries, security model, CI matrix, and release metadata.

The SDK version follows the plugin contract rather than Open Cinema's application version.
Contract tests can validate a source checkout and built wheel without a running appliance; an
integration fixture loads the wheel against supported Open Cinema versions.

## Risks / Trade-offs

- [Trusted Git code can access data available to the service user] -> State the trust boundary
  before acquisition, keep the service account unprivileged, deny arbitrary host integration, and
  show source/revision/provenance persistently.
- [Overlay dependencies can still conflict at import time] -> Resolve against immutable core
  constraints, put core packages first, test-import the complete generation, and retain atomic
  rollback.
- [A bad import can delay startup] -> Bound discovery and validation where possible, retain a
  startup recovery mode that disables the candidate generation, and never let one capability
  suppress core diagnostics.
- [Hot disable cannot unload Python modules] -> Define hot as behavior deactivation, gate all core
  dispatch, and require restart for plugins that cannot prove bounded stop semantics.
- [Declarative pages may initially be less expressive than custom React] -> Start with richer
  product-owned templates and evolve semantic primitives from real plugin needs; do not expose CSS
  or frontend ABI as a shortcut.
- [Plugin storage without private relational models is less flexible] -> Provide namespaced
  documents, instances, indexes, operations, and secrets adequate for appliance integrations;
  revisit isolated storage only with a concrete plugin need.
- [Restarting during an installation can obscure success] -> Persist operation stages and expected
  generations, finalize after fresh startup, and display reconnect progress.
- [Old overlay generations consume storage] -> Keep a bounded count and never delete the active or
  last-known-good generation during cleanup.

## Migration Plan

1. Add version-2 schemas, generic plugin storage, registry records, and contract tests alongside
   tests for the current behavior, then convert the bundled counter and processing registrations.
2. Remove the version-1 entry-point groups and model-package contract after all bundled callers use
   `open_cinema.plugins`; discard counter development data.
3. Add read-only installed/catalogue APIs and generation inspection before enabling mutations.
4. Deploy the overlay bootstrap and privileged helper with no third-party plugins installed, then
   validate base startup and rollback on the Raspberry Pi.
5. Enable staged install/update/remove operations, startup finalization, and guarded lifecycle
   actions.
6. Add the dynamic Refine navigation, product-owned page templates, form widgets, Plugins pages,
   and error/operation boundaries.
7. Publish the SDK, author guide, example plugin, CI fixture, and first-party catalogue format.
8. Use the separate librespot plugin as the acceptance implementation before declaring contract
   version 2 stable.

Rollback keeps the prior Open Cinema release and last-known-good plugin overlay generation. Before
switching generations, the operation records its previous pointer and configuration versions. A
failed startup or health gate restores that pointer and restarts the affected application services.
Core schema migrations remain backward-safe until release closure; plugin configuration migrations
write a new document only after successful validation.
