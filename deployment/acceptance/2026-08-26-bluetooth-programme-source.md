# Bluetooth programme-source acceptance — 2026-08-26

Status: **accepted for deployment task 3.6 on the experimental Raspberry Pi
appliance**.

This acceptance proves that the headless Open Cinema audio session can pair a
supported phone, expose its A2DP programme audio as an input candidate, select
that candidate using durable runtime facts, and receive real PCM. It does not
accept automatic source priority, routing through the desired processing graph,
or the complete TV/Bluetooth/headset scenario.

## Fixture and pairing

- Raspberry Pi 5 8 GB appliance using its onboard Bluetooth adapter.
- Debian 13, PipeWire 1.4.2, WirePlumber 0.5.8, and BlueZ 5.82.
- Dedicated lingering `opencinema` audio account; no graphical login session.
- Xiaomi `Mi 10T Pro` phone; Bluetooth address deliberately redacted.

The phone and appliance displayed the same numeric confirmation code before the
pairing request was accepted. The resulting device was paired, bonded, trusted,
and connected, and advertised the standard Bluetooth Audio Source service.
Scanning, discoverability, pairability, and the temporary interactive agent
were disabled after pairing; the saved trust remains.

The owned WirePlumber fragment declares `a2dp_source` and applies
`bluez5.media-source-role = "input"` to BlueZ input nodes. The connected phone
therefore produced a PipeWire `Audio/Source` node and an Open Cinema endpoint
candidate with active, available profile `audio-gateway`.

## Durable selector proof

Open Cinema's current input inventory was evaluated using this selector while
the phone transport was active:

```json
{
  "version": 1,
  "match": "all",
  "predicates": [
    {"path": "direction", "operator": "exact", "value": "input"},
    {"path": "mediaClass", "operator": "exact", "value": "Audio/Source"},
    {"path": "device.properties.device.bus", "operator": "exact", "value": "bluetooth"},
    {"path": "profile.name", "operator": "exact", "value": "audio-gateway"},
    {"path": "profile.availability", "operator": "exact", "value": "yes"},
    {"path": "profile.active", "operator": "exact", "value": true}
  ]
}
```

The selector validated successfully and returned one `matched` candidate: the
running `Mi 10T Pro` source. All six predicates matched. The Bluetooth headset's
microphone candidate was rejected by the profile predicate, and the managed
debug-file source was rejected by the Bluetooth and profile predicates. No
Bluetooth address, PipeWire object ID, or other volatile runtime identifier is
part of the rule.

## PCM proof

A temporary PipeWire recorder held the demand-driven source active for eight
seconds without changing any desired graph. The resulting raw stereo S16LE,
48 kHz capture contained:

| Measurement | Result |
| --- | ---: |
| Bytes | 1,536,000 |
| Samples | 768,000 |
| Non-zero samples | 761,883 |
| Peak | 19,498 / 32,767 |
| RMS | 5,779.35 |

This proves real programme PCM reached the Pi rather than merely proving BlueZ
service discovery. The temporary capture was removed immediately after the
measurement.

The A2DP source transport is demand-driven: it suspends, and its PipeWire node
may be recreated with a different runtime ID, when no consumer holds it. The
selector remained independent of that ID. Automatic resolution must still be
tested across this idle/active lifecycle before the full scenario is accepted.

## Recovery and acceptance boundary

The orchestrator was restarted during a held-open phone capture to force a new
authoritative inventory. The accepted limited-live graph recovered with all 18
Open Cinema-tagged links, and its applied state returned to `converged` with no
last error.

This closes task 3.6. Automatic Bluetooth priority, routing through the decoder
and CamillaDSP, headset takeover, and removal fallback were subsequently accepted
in `2026-08-26-adaptive-bluetooth-routing.md`. Tasks 8.2 and 9.6 remain open for
the physical TV-input portion and the final complete supported-tier run.
