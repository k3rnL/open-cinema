## REMOVED Requirements

### Requirement: PulseAudio compatibility is transitional only

**Reason**: CamillaDSP and the adaptive decoder now both use native PipeWire
I/O, so retaining a selectable compatibility-server path adds an untested
second transport and contradicts the accepted appliance architecture.

**Migration**: Remove the compatibility service, variables, manifest fields,
environment, readiness probes, and current documentation. Managed processors
must expose their capture and playback resources directly in the one
WirePlumber-owned PipeWire graph.
