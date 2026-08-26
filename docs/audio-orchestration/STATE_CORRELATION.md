# Orchestration state correlation

Desired, resolved, applied, and observed runtime state are separate and must
never be presented as one implicit “current graph.” A correlation document
therefore records, for one graph:

- activated revision ID/digest and desired-state version;
- immutable resolution-world version and PipeWire generation/sequence;
- resolved plan ID/digest and correlation ID;
- transition generation/status and applied plan ID/digest;
- latest observed runtime-world version and PipeWire generation/sequence.

`appliedMatchesResolved`, `newerRuntimeObserved`, and `converged` are derived
facts. In particular, a plan cannot be called converged merely because it was
resolved: the applied plan must match it, the transition must be converged, and
the latest runtime position must still equal the resolution position.
