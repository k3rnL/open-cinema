# Coordinated upgrade and rollback acceptance

Date: 2026-08-26 (appliance local time)

Host: Raspberry Pi 5 Model B Rev 1.1, 8 GB, Debian 13 `trixie`, aarch64

Release stage: experimental `limited-live`, exact graph allowlist

## Recovery boundary

A changed local candidate created the private, ready-marked transition bundle:

```text
/var/lib/open-cinema/rollback/transition-20260826T002452-ebd7b2b6d014
size: 108 MB
checksummed artifacts: 9
owner/mode: opencinema:opencinema, directories 0750, files 0600
previous candidate digest: d28911c2f9d7959d650c4b4a3234cd228de67c80e51e7cc05ba5a8977cac26f3
candidate digest: ebd7b2b6d014478de99f262215b030491cc8696c211d8662d50932384972bc85
```

The manifest correlates the database, application and virtual environment,
WyrePlumber binding, both web builds, processor binaries, generated processor
configuration, managed static files, installed release evidence, and controller
inventory inputs. All nine manifest checksums passed before restore.

## Exact rollback rehearsal

The selected bundle was restored with the explicit command:

```bash
ansible-playbook -i inventories/local.yml playbooks/rollback.yml \
  -e open_cinema_rollback_bundle_id=transition-20260826T002452-ebd7b2b6d014
```

The first final readiness pass exposed a permission defect in the newly added
candidate-database safety checkpoint: SQLite created it as `0644`. No recovery
data was lost, the restored generation remained operational, and readiness
retained a correlated failure result. The rollback role now immediately
normalizes every such checkpoint to `0600`; both existing rehearsal checkpoints
were also corrected.

The complete corrected rollback then passed:

```text
PLAY RECAP: ok=104 changed=11 failed=0
rollback status: passed
readiness status: passed; failedChecks=[]
core services: redis, Django, Celery worker/beat, orchestrator, nginx all active
restored previous source generation: confirmed
```

## Dynamic state preservation

The deployment-state document hashes every concrete field of graph definitions,
graph revisions, graph activations, logical endpoint bindings, CamillaDSP
profiles, managed adapters, and manual overrides. Runtime projections are
excluded. Audit history is reported separately because normal reconciliation
may append permitted events.

Before upgrade, after rollback, and after forward redeployment the result was:

```text
intent digest: bb39f864e6e33338b992a01bd9b2169bab4421ae7cc8ef209fa7851853d09d33
audit count/latest sequence: 435/435
graph definitions/revisions: 2/2
graph activations: 2
logical endpoints: 3
CamillaDSP profiles: 1
managed adapters/manual overrides: 1/0
```

The rollback play asserted the digest before declaring success; it did not rely
on a manual comparison.

## Forward recovery and idempotency

The current candidate was deployed again after the rollback. It created a fresh
recovery boundary for the restored generation, passed the installed contract
gate, and passed end-of-play readiness:

```text
forward deployment: ok=331 changed=31 failed=0
contract gate: passed; failures=[]
readiness: passed; failedChecks=[]
candidate digest: ebd7b2b6d014478de99f262215b030491cc8696c211d8662d50932384972bc85
```

An immediate complete rerun neither stopped audio nor created a transition
bundle:

```text
PLAY RECAP: ok=293 changed=0 failed=0
```

Local validation after the rehearsal passed all 801 backend/deployment tests
and syntax checks for `site.yml`, `rollback.yml`, and `preflight.yml`.

## Candidate failure boundary

The application/processor/UI install, service-handler, contract-gate, and
readiness roles now run inside one outer failure boundary. Their specialized
diagnostics remain intact, and any propagated failure also records the candidate
identity, recovery boundary, service states, related diagnostic paths, and
service journal in a private aggregate result.

An injected candidate contract incompatibility exercised this boundary:

```text
PLAY RECAP: ok=53 changed=2 failed=1 rescued=1
failed task: Reject every incompatible component before deployment mutation
aggregate result: candidate-20260826T005449.json, mode 0600
aggregate log: candidate-20260826T005449.log, mode 0600
rollback bundle: transition-20260826T003349-ebd7b2b6d014, READY present
all eight probed services: active
processor management/live reconciliation: false/false
```

A clean contract-gate run passed and restored the accepted mutation flags. The
next complete readiness run passed; its only change was refreshing the runtime
facts after the deliberate controller restart. One final complete run then
reported `ok=294 changed=0 failed=0`.

## Scope and remaining limitation

This accepts one real coordinated rollback at the `limited-live` stage, the
state-preservation mechanism, and fail-closed candidate diagnostics. It does
not complete the matrix requiring rollback
from every rollout stage, a separate schema-changing release, and an injected
processor-protocol incompatibility. Experimental rollback windows therefore
remain open and all retained bundles remain untouched.
