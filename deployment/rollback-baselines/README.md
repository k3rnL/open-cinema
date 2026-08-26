# Private replacement rollback baseline

The first coordinated native-audio release has no compatible historical public
manifest: the previous backend artifact reports the wrong version, the previous
binding targets WirePlumber 0.4, and the previous decoder uses the retired
sound-server transport.
The accepted replacement is therefore the already exercised full-generation Pi
transition bundle recorded by the receipt in this directory.

Only the privacy-safe receipt belongs in Git. The capsule remains in two private
locations: its original protected appliance directory and a controller-only
off-appliance store. Never commit or upload the capsule, its storage paths, the
database, inventory, dynamic state, configuration, or diagnostic contents.

Verify the private controller copy before promotion or rollback:

```console
python deployment/scripts/verify_private_rollback_capsule.py PRIVATE_CAPSULE \
  --receipt deployment/rollback-baselines/open-cinema-replacement-baseline-v1.yml \
  --receipt-id open-cinema-replacement-baseline-v1 \
  --receipt-sha256 899dd08618efafb86bcec1e6b9942535bcd417cadeced2035bef3bb0a14ae05a
```

For appliance mode, set `private_rollback_capsule_path` only in the ignored
private inventory. Before the first appliance-mutating role, the site playbook
verifies the manifest-bound receipt, capsule digest and size, nested restore
archives, SQLite integrity, and private file permissions on the controller. It
also checks on the Pi that the receipt-bound baseline exists, its manifest and
READY hashes and file count agree, and every retained entry remains immutable.
Mutable development mode performs the target check and protects that identity
without opening or requiring the controller capsule. Missing or drifted target
state blocks for manual recovery; deployment never exports the baseline or
rehydrates it automatically. The identity is protected from permission rewrites
and rollback pruning, and the private storage location is never written to
deployment evidence.

The retained bundle may contain historical contract-gate and readiness
snapshots, but they are supplemental diagnostics outside the nine-artifact
restore contract. Rollback does not restore or trust those snapshots. It derives
the minimal previous gate identity from the verified transition manifest and
generates new readiness evidence after the restored services pass their probes.

This exception is valid only for the first `0.3.1` coordinated release. Once
that release is accepted, subsequent releases must retain and identify the
immediately previous finalized coordinated manifest and its published bytes.
