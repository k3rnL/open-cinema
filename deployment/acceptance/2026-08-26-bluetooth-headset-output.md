# Bluetooth headset output acceptance — 2026-08-26

Status: **accepted for deployment task 3.7 on the experimental Raspberry Pi
appliance**.

This acceptance proves that the headless Open Cinema audio session can discover,
connect, inventory, select, and play audio through a supported Bluetooth headset.
It does not accept automatic headset takeover, disconnect fallback, Bluetooth
programme input, or the complete adaptive-processing scenario.

## Fixture

- Raspberry Pi 5 8 GB appliance using its onboard Bluetooth adapter.
- Debian 13, PipeWire 1.4.2, WirePlumber 0.5.8, and BlueZ 5.82.
- Dedicated lingering `opencinema` audio account; no graphical login session.
- Plantronics `PLT BB PRO 2` headset; Bluetooth address deliberately redacted.
- Negotiated active profile: `a2dp-sink`, with the aptX codec selected by the
  runtime.

The headset was paired, bonded, trusted, and connected while the service-owned
PipeWire/WirePlumber session was running. It remained connected after the
temporary interactive pairing agent and discoverable mode were disabled.

## Headless BlueZ correction

The first A2DP connection attempt failed with
`br-connection-profile-unavailable`. BlueZ had no media endpoint because
WirePlumber's default seat monitoring excludes a lingering, non-seat service
user.

The owned `90-open-cinema-bluetooth.conf` fragment now disables BlueZ seat
monitoring for WirePlumber's `main` profile. It continues to declare the A2DP
sink/source and HFP roles, and marks BlueZ media-source nodes as programme
inputs. Distribution configuration is not replaced.

After the fragment was deployed, the same headset connected successfully and
produced a current `Audio/Device` plus an `Audio/Sink` endpoint candidate in the
Open Cinema inventory.

## Runtime inventory and selector proof

The current output inventory contained two candidates: the Bluetooth headset
and the Wondom USB 7.1 output. The headset candidate reported:

- direction `output` and media class `Audio/Sink`;
- durable device fact `device.bus=bluetooth`;
- active, available profile `a2dp-sink`;
- active, available route `headset-output`;
- stereo `FL`/`FR` audio at 48 kHz; and
- current PipeWire default-output status.

The deployed selector parser and matcher were run against the current Redis-
projected inventory using this durable rule:

```json
{
  "version": 1,
  "match": "all",
  "predicates": [
    {"path": "direction", "operator": "exact", "value": "output"},
    {"path": "mediaClass", "operator": "exact", "value": "Audio/Sink"},
    {"path": "device.properties.device.bus", "operator": "exact", "value": "bluetooth"},
    {"path": "profile.name", "operator": "exact", "value": "a2dp-sink"},
    {"path": "profile.availability", "operator": "exact", "value": "yes"},
    {"path": "profile.active", "operator": "exact", "value": true},
    {"path": "route.name", "operator": "exact", "value": "headset-output"},
    {"path": "route.availability", "operator": "exact", "value": "yes"},
    {"path": "route.active", "operator": "exact", "value": true}
  ]
}
```

The selector validated successfully. All nine predicates matched the headset,
the result was uniquely `matched`, and the USB Wondom candidate was rejected by
the Bluetooth, A2DP-profile, and headset-route predicates. No volatile runtime
identifier or Bluetooth address is required by the rule.

## Audible proof and recovery

A low-volume, three-second 440 Hz stereo tone was sent directly to the selected
PipeWire headset sink without changing the saved desired graph. The user
explicitly confirmed hearing the tone on 2026-08-26.

Connecting BlueZ also exercised previously unseen native SPA profile payloads.
WyrePlumber now accepts both counted and uncounted profile-class structs and
normalizes fallback POD bytes into the immutable JSON contract. Its focused SPA
and runtime suite passed **158 tests**. The coordinated application deployment
then completed with `ok=206`, `changed=32`, and `failed=0`; production contract
classification and aggregate readiness both passed.

The existing limited-live graph recovered after redeployment with all 18 owned
links: two source-to-decoder, eight decoder-to-CamillaDSP, and eight
CamillaDSP-to-Wondom links. The direct headset probe therefore did not modify or
replace the user's accepted graph.

## Acceptance boundary

This closes task 3.7. The supported phone source was accepted separately, and
automatic headset takeover plus removal fallback were subsequently accepted in
`2026-08-26-adaptive-bluetooth-routing.md`. Tasks 8.2 and 9.6 remain open for the
physical TV-input portion and the final complete supported-tier run.
