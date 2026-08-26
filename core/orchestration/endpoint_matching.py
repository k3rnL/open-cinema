from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from .endpoint_identity import (
    IdentityEvidence,
    IdentityEvidenceTier,
    rank_stable_identity_evidence,
)
from .endpoint_inventory import RuntimeEndpointCandidate
from .endpoint_selectors import (
    EndpointSelector,
    EndpointSelectorPredicate,
    SelectorMatchMode,
    SelectorOperator,
)


class EndpointMatchStatus(StrEnum):
    MATCHED = "matched"
    NO_MATCH = "no_match"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class PredicateMatchEvidence:
    path: str
    operator: str
    matched: bool


@dataclass(frozen=True, slots=True)
class CandidateMatchDiagnostic:
    runtime_key: str
    name: str | None
    matched_selector: bool
    score: int
    predicates: tuple[PredicateMatchEvidence, ...]
    identity: tuple[IdentityEvidence, ...]
    accepted_evidence: tuple[str, ...]
    rejected_evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EndpointMatchResult:
    status: EndpointMatchStatus
    selected: RuntimeEndpointCandidate | None
    tied: tuple[RuntimeEndpointCandidate, ...]
    diagnostics: tuple[CandidateMatchDiagnostic, ...]


_IDENTITY_WEIGHTS = {
    IdentityEvidenceTier.MANAGED_ID: 1_000_000_000,
    IdentityEvidenceTier.HARDWARE: 1_000_000,
    IdentityEvidenceTier.ROUTE_PROFILE: 1_000,
    IdentityEvidenceTier.STABLE_NAME: 10,
    IdentityEvidenceTier.DESCRIPTIVE: 1,
}


def _predicate_weight(predicate: EndpointSelectorPredicate) -> int:
    if predicate.operator == SelectorOperator.EXACT:
        return 100_000
    if predicate.operator == SelectorOperator.ONE_OF:
        return 80_000 - min(len(predicate.value), 32) * 100
    wildcard_count = predicate.value.count("*") + predicate.value.count("?")
    return 50_000 - wildcard_count * 1_000


def _candidate_diagnostic(
    selector: EndpointSelector,
    candidate: RuntimeEndpointCandidate,
) -> CandidateMatchDiagnostic:
    predicate_results = tuple(
        PredicateMatchEvidence(
            path=predicate.path,
            operator=predicate.operator.value,
            matched=predicate.matches(candidate),
        )
        for predicate in selector.predicates
    )
    matched = (
        all(item.matched for item in predicate_results)
        if selector.mode == SelectorMatchMode.ALL
        else any(item.matched for item in predicate_results)
    )
    identity = rank_stable_identity_evidence(candidate)
    selector_score = sum(
        _predicate_weight(predicate)
        for predicate, evidence in zip(selector.predicates, predicate_results)
        if evidence.matched
    )
    identity_score = sum(_IDENTITY_WEIGHTS[item.tier] for item in identity)
    accepted = [
        f"selector:{evidence.path}:{evidence.operator}"
        for evidence in predicate_results
        if evidence.matched
    ]
    accepted.extend(f"identity:{item.kind.value}:{item.path}" for item in identity)
    rejected = [
        f"selector:{evidence.path}:{evidence.operator}:not-matched"
        for evidence in predicate_results
        if not evidence.matched
    ]
    return CandidateMatchDiagnostic(
        runtime_key=candidate.runtime_key,
        name=candidate.name,
        matched_selector=matched,
        score=selector_score + identity_score if matched else 0,
        predicates=predicate_results,
        identity=identity,
        accepted_evidence=tuple(accepted),
        rejected_evidence=tuple(rejected),
    )


def match_endpoint_candidates(
    selector: EndpointSelector,
    candidates: tuple[RuntimeEndpointCandidate, ...] | list[RuntimeEndpointCandidate],
) -> EndpointMatchResult:
    diagnostics_by_key = {
        candidate.runtime_key: _candidate_diagnostic(selector, candidate)
        for candidate in candidates
    }
    candidate_by_key = {candidate.runtime_key: candidate for candidate in candidates}
    matching = [
        diagnostic for diagnostic in diagnostics_by_key.values() if diagnostic.matched_selector
    ]
    status = EndpointMatchStatus.NO_MATCH
    selected = None
    tied = ()
    if matching:
        best_score = max(diagnostic.score for diagnostic in matching)
        best = [diagnostic for diagnostic in matching if diagnostic.score == best_score]
        if len(best) == 1:
            status = EndpointMatchStatus.MATCHED
            selected = candidate_by_key[best[0].runtime_key]
        else:
            status = EndpointMatchStatus.AMBIGUOUS
            tied = tuple(
                candidate_by_key[diagnostic.runtime_key]
                for diagnostic in sorted(
                    best,
                    key=lambda item: (item.name or "", item.runtime_key),
                )
            )
        for diagnostic in matching:
            rejection = list(diagnostic.rejected_evidence)
            if diagnostic.score < best_score:
                rejection.append(f"candidate:lower-score-than:{best_score}")
            elif len(best) > 1:
                rejection.append(f"candidate:equal-best-score:{best_score}")
            diagnostics_by_key[diagnostic.runtime_key] = replace(
                diagnostic,
                rejected_evidence=tuple(rejection),
            )
    diagnostics = tuple(
        sorted(
            diagnostics_by_key.values(),
            key=lambda item: (
                not item.matched_selector,
                -item.score,
                item.name or "",
                item.runtime_key,
            ),
        )
    )
    return EndpointMatchResult(
        status=status,
        selected=selected,
        tied=tied,
        diagnostics=diagnostics,
    )
