# Resolved plan status and current-plan policy

Every resolver run is persisted as diagnostic history, but only a safe result
may replace the plan referenced by `AppliedPlanState.current_plan`. The resolver
emits `currentPlanPolicy` so the orchestrator does not need to infer that choice
from warning text.

| Status | Meaning | Current/applied-plan behavior |
| --- | --- | --- |
| `resolved` | The desired revision produced a complete deterministic result without diagnostics. | It may become or remain current and its action intent may be executed. |
| `waiting` | A required endpoint, fact, selector result, or dependency is not available yet and no complete route was selected. | Store it as the latest resolution result, retain the last safe applied plan, and execute no actions from the waiting result. Re-resolve when the dependency changes. |
| `degraded` | Resolution has warnings, but it may still contain a complete safe fallback. | It may become or remain current only when `mayExecuteActions` is true. If the selected path still lacks a required resource, retain the last safe applied plan instead. |
| `conflicted` | Inputs admit no unique deterministic choice, for example an endpoint ambiguity or unresolved equal-priority tie. | Store the diagnostics, retain the last safe applied plan, and execute no actions until the conflict is resolved. |
| `invalid` | Desired structure, subgraph expansion, parameters, conditions, resource declarations, or signal contracts are invalid. | Store the diagnostics, retain the last safe applied plan, and execute no actions. A new valid desired revision or compatible dependency is required. |

`mayBecomeCurrent` and `mayRemainCurrent` concern the applied-plan reference;
they do not suppress the newest resolver result in plan history or the API.
`retainLastSafePlan` means the orchestrator keeps the existing applied-plan
record if it has one. It does not claim that disconnected hardware can continue
playing; runtime availability remains a separate observed state.
