from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from api.models.orchestration import (
    GraphDefinition,
    GraphDefinitionKind,
    GraphRevision,
    GraphRevisionState,
)

from .graph_documents import graph_content_digest, normalize_graph_document
from .graph_schema import (
    DESIRED_GRAPH_SCHEMA_VERSION,
    desired_graph_envelope_validator,
)

GRAPH_EXPORT_FORMAT = "open-cinema.desired-audio-graph/v1"


@dataclass(frozen=True, slots=True)
class GraphImportIssue:
    path: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class GraphImportResult:
    valid: bool
    dry_run: bool
    created: bool
    definition_id: uuid.UUID | None
    revision_id: uuid.UUID | None
    issues: tuple[GraphImportIssue, ...]


class GraphImportValidationError(ValueError):
    def __init__(self, issues: tuple[GraphImportIssue, ...]):
        self.issues = issues
        super().__init__("; ".join(f"{issue.path}: {issue.message}" for issue in issues))


def export_graph_revision(revision: GraphRevision) -> dict[str, object]:
    """Export one definition/revision pair with stable database identifiers."""

    return {
        "format": GRAPH_EXPORT_FORMAT,
        "definition": {
            "id": str(revision.definition_id),
            "name": revision.definition.name,
            "kind": revision.definition.kind,
            "labels": revision.definition.labels,
        },
        "revision": {
            "id": str(revision.pk),
            "number": revision.revision_number,
            "state": revision.state,
            "schemaVersion": revision.schema_version,
            "publishedAt": (
                revision.published_at.isoformat() if revision.published_at is not None else None
            ),
            "contentDigest": revision.content_digest,
            "content": normalize_graph_document(revision.content),
        },
    }


def canonical_graph_export_json(revision: GraphRevision) -> str:
    return json.dumps(
        export_graph_revision(revision),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _issue(path: str, code: str, message: str) -> GraphImportIssue:
    return GraphImportIssue(path=path, code=code, message=message)


def _parse_uuid(value, *, path: str, issues: list[GraphImportIssue]):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        issues.append(_issue(path, "invalid_id", "Expected a UUID."))
        return None


def _validate_import_bundle(
    bundle: Mapping[str, object],
    *,
    owner,
) -> tuple[list[GraphImportIssue], dict[str, object]]:
    issues: list[GraphImportIssue] = []
    parsed: dict[str, object] = {}
    if not isinstance(bundle, Mapping):
        return [_issue("$", "invalid_type", "Import bundle must be an object.")], parsed
    if bundle.get("format") != GRAPH_EXPORT_FORMAT:
        issues.append(
            _issue(
                "$.format",
                "unsupported_format",
                f"Expected {GRAPH_EXPORT_FORMAT!r}.",
            )
        )
    unexpected = set(bundle) - {"format", "definition", "revision"}
    if unexpected:
        issues.append(
            _issue(
                "$",
                "unknown_fields",
                f"Unknown import fields: {', '.join(sorted(unexpected))}.",
            )
        )

    definition = bundle.get("definition")
    revision = bundle.get("revision")
    if not isinstance(definition, Mapping):
        issues.append(_issue("$.definition", "invalid_type", "Expected an object."))
        definition = {}
    if not isinstance(revision, Mapping):
        issues.append(_issue("$.revision", "invalid_type", "Expected an object."))
        revision = {}

    definition_id = _parse_uuid(definition.get("id"), path="$.definition.id", issues=issues)
    revision_id = _parse_uuid(revision.get("id"), path="$.revision.id", issues=issues)
    parsed["definition_id"] = definition_id
    parsed["revision_id"] = revision_id

    name = definition.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 255:
        issues.append(
            _issue(
                "$.definition.name",
                "invalid_name",
                "Name must be a non-empty string of at most 255 characters.",
            )
        )
    kind = definition.get("kind")
    if kind not in GraphDefinitionKind.values:
        issues.append(_issue("$.definition.kind", "invalid_kind", "Unknown graph kind."))
    labels = definition.get("labels")
    if not isinstance(labels, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in (labels.items() if isinstance(labels, dict) else ())
    ):
        issues.append(
            _issue(
                "$.definition.labels",
                "invalid_labels",
                "Labels must map strings to strings.",
            )
        )

    revision_number = revision.get("number")
    if (
        isinstance(revision_number, bool)
        or not isinstance(revision_number, int)
        or revision_number < 1
    ):
        issues.append(
            _issue("$.revision.number", "invalid_revision", "Expected a positive integer.")
        )
    state = revision.get("state")
    if state not in GraphRevisionState.values:
        issues.append(_issue("$.revision.state", "invalid_state", "Unknown revision state."))
    schema_version = revision.get("schemaVersion")
    if schema_version != DESIRED_GRAPH_SCHEMA_VERSION:
        issues.append(
            _issue(
                "$.revision.schemaVersion",
                "unsupported_schema_version",
                f"Only desired-graph schema {DESIRED_GRAPH_SCHEMA_VERSION} is supported.",
            )
        )

    published_at = revision.get("publishedAt")
    parsed_published_at = None
    if published_at is not None:
        parsed_published_at = (
            parse_datetime(published_at) if isinstance(published_at, str) else None
        )
        if parsed_published_at is None or not timezone.is_aware(parsed_published_at):
            issues.append(
                _issue(
                    "$.revision.publishedAt",
                    "invalid_timestamp",
                    "Expected an ISO-8601 timestamp with an offset or null.",
                )
            )
    if state == GraphRevisionState.PUBLISHED and parsed_published_at is None:
        issues.append(
            _issue(
                "$.revision.publishedAt",
                "missing_publication_time",
                "Published revisions require a publication timestamp.",
            )
        )
    if state == GraphRevisionState.DRAFT and published_at is not None:
        issues.append(
            _issue(
                "$.revision.publishedAt",
                "draft_publication_time",
                "Draft revisions cannot have a publication timestamp.",
            )
        )
    parsed["published_at"] = parsed_published_at

    content = revision.get("content")
    if isinstance(content, Mapping):
        for error in sorted(
            desired_graph_envelope_validator().iter_errors(content),
            key=lambda item: list(item.absolute_path),
        ):
            suffix = "".join(f"[{item!r}]" for item in error.absolute_path)
            issues.append(
                _issue(
                    f"$.revision.content{suffix}",
                    f"schema_{error.validator}",
                    error.message,
                )
            )
        if content.get("schemaVersion") != schema_version:
            issues.append(
                _issue(
                    "$.revision.content.schemaVersion",
                    "version_mismatch",
                    "Document and revision schema versions differ.",
                )
            )
        if content.get("kind") != kind:
            issues.append(
                _issue(
                    "$.revision.content.kind",
                    "kind_mismatch",
                    "Document and definition kinds differ.",
                )
            )
        normalized_content = normalize_graph_document(content)
        parsed["content"] = normalized_content
        digest = graph_content_digest(normalized_content)
        if revision.get("contentDigest") != digest:
            issues.append(
                _issue(
                    "$.revision.contentDigest",
                    "digest_mismatch",
                    "Content digest does not match the semantic graph document.",
                )
            )
    else:
        issues.append(_issue("$.revision.content", "invalid_type", "Expected an object."))

    if definition_id and GraphDefinition.objects.filter(pk=definition_id).exists():
        issues.append(
            _issue("$.definition.id", "id_conflict", "Graph definition ID already exists.")
        )
    if revision_id and GraphRevision.objects.filter(pk=revision_id).exists():
        issues.append(_issue("$.revision.id", "id_conflict", "Graph revision ID already exists."))
    if isinstance(name, str) and GraphDefinition.objects.filter(owner=owner, name=name).exists():
        issues.append(
            _issue(
                "$.definition.name",
                "name_conflict",
                "The owner already has a graph with this name.",
            )
        )
    return issues, parsed


def import_graph_bundle(
    bundle: Mapping[str, object],
    *,
    owner,
    dry_run: bool = False,
) -> GraphImportResult:
    """Validate and atomically create one graph; dry-run performs no writes."""

    issues, parsed = _validate_import_bundle(bundle, owner=owner)
    immutable_issues = tuple(issues)
    if issues or dry_run:
        result = GraphImportResult(
            valid=not issues,
            dry_run=dry_run,
            created=False,
            definition_id=parsed.get("definition_id"),
            revision_id=parsed.get("revision_id"),
            issues=immutable_issues,
        )
        if issues and not dry_run:
            raise GraphImportValidationError(immutable_issues)
        return result

    definition_data = bundle["definition"]
    revision_data = bundle["revision"]
    with transaction.atomic():
        definition = GraphDefinition(
            id=parsed["definition_id"],
            name=definition_data["name"],
            kind=definition_data["kind"],
            owner=owner,
            labels=definition_data["labels"],
        )
        definition.full_clean()
        definition.save(force_insert=True)
        revision = GraphRevision(
            id=parsed["revision_id"],
            definition=definition,
            schema_version=revision_data["schemaVersion"],
            revision_number=revision_data["number"],
            state=revision_data["state"],
            author=owner,
            content=parsed["content"],
            content_digest=revision_data["contentDigest"],
            validation_summary={"valid": True, "source": "import", "issues": []},
            published_at=parsed["published_at"],
        )
        revision.full_clean()
        revision.save(force_insert=True)

    return GraphImportResult(
        valid=True,
        dry_run=False,
        created=True,
        definition_id=definition.pk,
        revision_id=revision.pk,
        issues=(),
    )
