# Plugin administration

The product Plugins menu has two deliberately separate views. Marketplace lists
maintained first-party releases, compatibility, publisher trust, capabilities,
version, and whether an artifact is published. Installed lists desired/runtime
state, health, provenance, permissions, update status, and current actions.

First-party installation shows the verified identity, permissions, lifecycle
impact, operation progress, and expected restart. Git installation is an
advanced trusted-code path: enter a credential-free HTTPS repository and an
optional tag or full commit, inspect it, review the resolved commit and mutable
reference warning, then acknowledge service-account code execution before
installing.

Marketplace availability is platform-specific. A published release is
installable only when the catalogue contains an immutable wheel and matching
digest for the appliance operating system and architecture. The Plugins page
identifies an unsupported platform; it does not fall back to a source build.
The downloaded wheel digest, release version, source commit, and platform are
recorded in installation provenance before the new generation is activated.

Lifecycle actions are serialized and idempotent. A hot action stays on the
current page. Application restart progress survives the expected connection
loss and is finalized after readiness. Host reboot always needs a separate
confirmation. Stale concurrency tokens are rejected rather than replayed.

Disable preserves the installed generation and plugin data but removes its
runtime/UI capabilities. Uninstall defaults to retained settings and secrets so
a later reinstall can validate and reuse them. “Delete plugin data” is
destructive; desired graph nodes are still preserved as unavailable references.
Rollback switches to the last-known-good complete overlay. Cleanup never
removes the current or last-known-good generation.

When an operation fails, keep the correlated operation ID and inspect its stage,
bounded diagnostics, input/output generation, source/revision/digest, and
application logs. Readiness evidence records current and last-good generation,
integrity, pending operations, incompatible plugins, and bounded disk use.

The first composite managed-source example is `open-cinema-librespot`. Each of
its instances appears both as a long-lived managed resource and a durable input
device, while its declarative Spotify Connect page owns configuration and
authentication. Its graph node selects one stable instance; core remains solely
responsible for live PipeWire correlation, input trim/mute, and physical output
routing.
