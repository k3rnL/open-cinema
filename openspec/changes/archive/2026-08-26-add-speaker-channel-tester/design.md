## Context

Open Cinema already projects WirePlumber endpoint candidates into the database for the management UI. A physical sink projection contains an opaque generation-scoped runtime key, a durable `node.name`, physical playback ports, and PCM format capabilities including the ordered channel positions. The active movie path currently ends at a multichannel physical sink through CamillaDSP, but ordinary playback cannot prove which amplifier terminal corresponds to each PipeWire channel.

The diagnostic must work through two Gunicorn workers, must not enter the desired graph or reconciliation ownership model, and must remain safe if PipeWire nodes are recreated between discovery and start. The backend currently runs as the same `opencinema` identity that owns the headless PipeWire session, but its service unit does not yet expose that session environment or the shared `/run/open-cinema` state directory.

## Goals / Non-Goals

**Goals:**

- Let an administrator identify physical speaker wiring one observed PipeWire channel at a time.
- Use the runtime projection as the sole source of selectable targets and channel order.
- Guarantee a finite, quiet, single-channel signal and at most one active test across web workers.
- Keep the diagnostic visible and stoppable while leaving desired/applied graph records untouched.
- Add a small Refine/Ant Design page matching the existing management UI without custom CSS.

**Non-Goals:**

- Calibrate speaker level, delay, equalization, polarity, or room response.
- Persist a speaker-to-channel remapping or change CamillaDSP configuration.
- Interrupt, mute, or reconfigure existing graph playback automatically.
- Test encoded passthrough outputs or infer an undocumented channel order.
- Introduce a long-running diagnostic daemon.

## Decisions

### Use a dedicated administrative diagnostic endpoint

`GET`, `POST`, and `DELETE /api/audio/v1/speaker-test` respectively discover/status, start, and stop the diagnostic. All methods require a staff administrator. A dedicated DTO keeps ephemeral diagnostic state out of generic endpoint projections and makes it explicit that this is not an adapter or graph operation.

Alternatives considered:

- Treating the tone generator as a debug-file adapter would persist desired state and require graph editing for a wiring check.
- Adding controls to the Devices page would mix durable endpoint binding with a disruptive runtime diagnostic.

### Derive outputs and maps from current endpoint projections

An output is eligible when its current projection is an unmanaged runtime-device `Audio/Sink`, it exposes physical input ports, and a PCM capability provides a usable ordered position list matching the channel count. The service uses the format position list as canonical order and verifies that each position also exists on a physical playback port. The submitted generation-scoped runtime key is re-resolved on every start; the numeric node ID is never accepted independently.

This intentionally excludes ambiguous devices. Guessing `5.1` or `7.1` ordering would undermine the purpose of diagnosing a suspected mapping problem.

### Run a finite helper process that feeds `pw-cat`

The API starts `python -m core.orchestration.speaker_test_worker`, which creates interleaved 48 kHz float samples for the complete observed channel map and writes a windowed sine only in the selected index to `pw-cat --playback --raw --target <node.name>`. The tone is fixed at a conservative server-side amplitude and two-second duration. The stream is labelled with Open Cinema diagnostic properties.

The helper owns `pw-cat` in one process group, forwards termination, and necessarily exits when its finite sample stream ends. This avoids retaining a Python thread or PipeWire handle in a Gunicorn worker after the response is returned.

Alternatives considered:

- Waiting synchronously in the request would make the Stop action unreliable and consume a web worker for the whole test.
- Calling ALSA directly would bypass the PipeWire channel model being diagnosed and contend with the running sink.
- Generating or committing one multichannel file per layout would be less flexible and make channel-order validation implicit.

### Coordinate web workers with a locked runtime state file

The controller serializes start/status/stop through `flock` on `/run/open-cinema/speaker-test.lock` and records the helper PID, Linux process start ticks, token, selection, and deadline in an atomic JSON state file. It validates both PID and start ticks before signalling a process group, preventing PID reuse from targeting an unrelated process. Starting a test stops a verified preceding helper first. Status removes expired or stale state.

The Gunicorn unit receives the same PipeWire environment as the orchestrator and write access to `/run/open-cinema`. The existing systemd-managed runtime directory remains owned by `opencinema`; no additional daemon or durable schema is introduced.

### Keep the UI intentionally small

The new `Speaker test` resource/page uses `Space`, `Card`, `Alert`, `Select`, `Button`, `Tag`, `Typography`, and existing notification behavior. Known abbreviations are expanded (`FL` to `Front left`, `FC` to `Front center`, etc.) while the exact PipeWire abbreviation remains visible. Refresh also polls current test state. No CSS file or new visual system is added.

## Risks / Trade-offs

- **Existing playback can mix with the test tone.** The page warns the user to pause playback first; automatically muting graph streams would make the diagnostic invasive and require restoration logic.
- **Sink volume and downstream amplification vary.** A conservative fixed digital amplitude reduces surprise but can still depend on the amplifier volume. The UI includes a volume warning and does not expose an unsafe amplitude control.
- **Projection freshness is finite.** Start revalidates against the current projection and `pw-cat` can still fail if the node disappears immediately afterward; the helper failure becomes inactive status and an actionable API/UI error on startup failures that can be detected.
- **Linux process metadata is platform-specific.** The appliance target is Linux. Unit tests isolate process inspection and spawning so API behavior remains deterministic.
- **A web-service restart can leave a short test running.** The signal is intrinsically finite and exits within two seconds; stale state is cleaned on the next operation.

## Migration Plan

1. Deploy backend code and the amended Gunicorn unit environment/runtime access.
2. Restart the backend and verify the authenticated API lists the live multichannel sink.
3. Build and deploy the admin application with the new route.
4. Test a low-volume channel on the Raspberry Pi, then test the user's connected FL and center speakers.
5. Roll back by removing the UI route/API and restarting the backend; no data migration or cleanup is needed beyond stopping a currently verified helper.

## Open Questions

- Whether the eventual calibration workflow should save a user-confirmed physical-channel remapping belongs in a separate change after the actual amplifier wiring is measured.
