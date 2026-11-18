"""GENERATED FILE — do not edit by hand.

Regenerate with `python scripts/generate_types.py`; CI runs the same script with
`--check` and fails on any difference, so an edit here is reverted by the next gate.

These are STRUCTURAL bindings, not validators. They say what a consumer programs
against; they do not enforce a pattern, an interval, a scope conditional or any
released cross-field rule. Validation is `research_contracts.canonical.validate_instance`
in Python and the canonical package in TypeScript. A value that type-checks here has
not been validated.
"""

from typing import Literal, NewType, NotRequired, TypedDict

__all__ = [
    "ActorSubject",
    "AnySelector",
    "Approvals",
    "ArtifactOutput",
    "ArtifactRef",
    "BboxFractions",
    "Bcp47Locale",
    "BoundedContext",
    "BoundedInteger",
    "CandidateFields",
    "CanonicalTypeToken",
    "CapabilityStatus",
    "CharacterSpan",
    "CodeSelector",
    "ColumnRange",
    "ContentHash",
    "ContextFields",
    "Cursor",
    "DataClassToken",
    "DecimalString",
    "DocumentSelector",
    "DocumentVersionRef",
    "EntitlementToken",
    "Environment",
    "EvidenceLocationCandidate",
    "EvidenceLocationFields",
    "EvidenceLocationRef",
    "EvidenceLocationVersion",
    "Extraction",
    "FieldIssue",
    "FrameRange",
    "FreeText",
    "HttpStatus",
    "IdempotencyKey",
    "IdentityFields",
    "IdentityRefFields",
    "Inputs",
    "IssueSeverity",
    "LineRange",
    "ManifestFields",
    "MediaSelector",
    "Method",
    "NotebookSelector",
    "Outputs",
    "PackReleaseStatus",
    "PageRequest",
    "PageRequestFields",
    "PageResponse",
    "Parameter",
    "PayloadDigest",
    "PinFields",
    "PinnedVersionRef",
    "ProblemCode",
    "ProblemDetails",
    "ProblemFields",
    "ProfileReleaseDescriptor",
    "ProfileReleaseStatus",
    "Purpose",
    "ReleaseId",
    "ReleaseRef",
    "ReleaseRefList",
    "ResearchAccessContext",
    "ResourceScope",
    "ResourceTenantId",
    "Rights",
    "RightsDecisionRef",
    "RoleToken",
    "RunManifest",
    "SchemaRef",
    "SelectorFields",
    "SelectorKind",
    "Semver",
    "SetOfPins",
    "SortDirection",
    "SortField",
    "SortKey",
    "SortRequest",
    "Source",
    "StableIdentity",
    "StatusFields",
    "TableCell",
    "TabularSelector",
    "Timestamp",
    "TranscriptSelector",
    "UnavailableReason",
    "UseMode",
    "Uuid",
    "VersionNumber",
    "Versions",
]


class CapabilityStatus(TypedDict):
    """urn:datacompany:capability-status:1 — generated."""

    available: bool
    capability_id: CanonicalTypeToken
    data_classes: NotRequired[list[CanonicalTypeToken]]
    enabled: bool
    installed: bool
    method_id: NotRequired[CanonicalTypeToken]
    provider_health: NotRequired[Literal["absent", "degraded", "healthy", "unhealthy"]]
    qualification_report_ref: NotRequired[PinnedVersionRef]
    qualified: bool
    required_for_publication: bool
    unavailable_reason: NotRequired[UnavailableReason]
    use_modes: NotRequired[list[UseMode]]


class EvidenceLocationCandidate(TypedDict):
    """urn:datacompany:evidence-location-candidate:1 — generated."""

    artifact_ref: NotRequired[ArtifactRef]
    coordinate_manifest_ref: NotRequired[PinnedVersionRef]
    derivation_provenance_refs: SetOfPins
    document_version_ref: NotRequired[DocumentVersionRef]
    language: Bcp47Locale
    quoted_text_digest: NotRequired[PayloadDigest]
    selector: AnySelector
    selector_schema_ref: SchemaRef
    selector_type: SelectorKind


class EvidenceLocationVersion(TypedDict):
    """urn:datacompany:evidence-location-version:1 — generated."""

    artifact_ref: NotRequired[ArtifactRef]
    content_hash: ContentHash
    coordinate_manifest_ref: NotRequired[PinnedVersionRef]
    document_version_ref: NotRequired[DocumentVersionRef]
    entity_id: Uuid
    entity_type: CanonicalTypeToken
    evidence_location_id: Uuid
    language: Bcp47Locale
    owner_context: BoundedContext
    quoted_text_digest: NotRequired[PayloadDigest]
    resolved_at: Timestamp
    resource_scope: ResourceScope
    resource_tenant_id: NotRequired[ResourceTenantId]
    schema_ref: SchemaRef
    selector: AnySelector
    selector_schema_ref: SchemaRef
    selector_type: SelectorKind
    version_id: Uuid
    version_number: VersionNumber


class ProblemDetails(TypedDict):
    """urn:datacompany:problem-details:1 — generated."""

    code: ProblemCode
    correlation_id: Uuid
    issues: NotRequired[list[FieldIssue]]
    message: str
    retryable: bool
    status: HttpStatus


class ResearchAccessContext(TypedDict):
    """urn:datacompany:research-access-context:1 — generated."""

    actor_id: ActorSubject
    actor_tenant_id: Uuid
    causation_id: Uuid
    correlation_id: Uuid
    data_classes: list[DataClassToken]
    delegation_id: NotRequired[Uuid]
    entitlements: list[EntitlementToken]
    expires_at: Timestamp
    idempotency_key: NotRequired[IdempotencyKey]
    initiated_by: NotRequired[ActorSubject]
    pack_refs: NotRequired[ReleaseRefList]
    policy_version: Uuid
    profile_ref: NotRequired[ReleaseRef]
    project_id: NotRequired[Uuid]
    protocol_version_id: NotRequired[Uuid]
    purpose: Purpose
    requested_at: Timestamp
    resource_scope: ResourceScope
    resource_tenant_id: NotRequired[ResourceTenantId]
    roles: list[RoleToken]
    workspace_id: NotRequired[Uuid]


class RunManifest(TypedDict):
    """urn:datacompany:run-manifest:1 — generated."""

    aggregate_version: int
    approvals: NotRequired[Approvals]
    content_hash: ContentHash
    created_at: Timestamp
    created_by: ActorSubject
    entity_id: Uuid
    entity_type: CanonicalTypeToken
    environment: Environment
    extraction: NotRequired[Extraction]
    inputs: Inputs
    method: Method
    outputs: Outputs
    resource_scope: ResourceScope
    resource_tenant_id: NotRequired[ResourceTenantId]
    rights: NotRequired[Rights]
    run_manifest_id: Uuid
    run_ref: PinnedVersionRef
    schema_ref: SchemaRef
    sources: NotRequired[list[Source]]
    versions: Versions


class StatusFields(TypedDict):
    """urn:datacompany:capability-status:1 — generated."""

    available: bool
    capability_id: CanonicalTypeToken
    data_classes: NotRequired[list[CanonicalTypeToken]]
    enabled: bool
    installed: bool
    method_id: NotRequired[CanonicalTypeToken]
    provider_health: NotRequired[Literal["absent", "degraded", "healthy", "unhealthy"]]
    qualification_report_ref: NotRequired[PinnedVersionRef]
    qualified: bool
    required_for_publication: bool
    unavailable_reason: NotRequired[UnavailableReason]
    use_modes: NotRequired[list[UseMode]]


CanonicalTypeToken = NewType("CanonicalTypeToken", str)


class PinnedVersionRef(TypedDict):
    """urn:datacompany:pinned-version-ref:1 — generated."""

    content_hash: ContentHash
    entity_id: Uuid
    entity_type: CanonicalTypeToken
    owner_context: BoundedContext
    resolved_at: Timestamp
    resource_scope: ResourceScope
    resource_tenant_id: NotRequired[ResourceTenantId]
    schema_ref: SchemaRef
    version_id: Uuid
    version_number: VersionNumber


UnavailableReason = Literal[
    "degraded",
    "disabled",
    "not_installed",
    "optional_provider_absent",
    "rights_unavailable",
    "stale_projection",
    "temporarily_unavailable",
    "unentitled",
    "unhealthy",
    "unqualified",
]


UseMode = Literal["exploratory", "publication"]


class CandidateFields(TypedDict):
    """urn:datacompany:evidence-location-candidate:1 — generated."""

    artifact_ref: NotRequired[ArtifactRef]
    coordinate_manifest_ref: NotRequired[PinnedVersionRef]
    derivation_provenance_refs: SetOfPins
    document_version_ref: NotRequired[DocumentVersionRef]
    language: Bcp47Locale
    quoted_text_digest: NotRequired[PayloadDigest]
    selector_schema_ref: SchemaRef


class SelectorFields(TypedDict):
    """urn:datacompany:locator-selector:1 — generated."""

    selector: AnySelector
    selector_type: SelectorKind


class ArtifactRef(TypedDict):
    """urn:datacompany:typed-refs:1 — generated."""

    content_hash: ContentHash
    entity_id: Uuid
    entity_type: CanonicalTypeToken
    owner_context: BoundedContext
    resolved_at: Timestamp
    resource_scope: ResourceScope
    resource_tenant_id: NotRequired[ResourceTenantId]
    schema_ref: Literal["urn:datacompany:artifact-version:1"]
    version_id: Uuid
    version_number: VersionNumber


class DocumentVersionRef(TypedDict):
    """urn:datacompany:typed-refs:1 — generated."""

    content_hash: ContentHash
    entity_id: Uuid
    entity_type: CanonicalTypeToken
    owner_context: BoundedContext
    resolved_at: Timestamp
    resource_scope: ResourceScope
    resource_tenant_id: NotRequired[ResourceTenantId]
    schema_ref: Literal["urn:datacompany:document-version:1"]
    version_id: Uuid
    version_number: VersionNumber


Bcp47Locale = NewType("Bcp47Locale", str)


PayloadDigest = NewType("PayloadDigest", str)


SchemaRef = NewType("SchemaRef", str)


SelectorKind = Literal["code", "document", "media", "notebook", "tabular", "transcript"]


class IdentityRefFields(TypedDict):
    """urn:datacompany:identity-ref:1 — generated."""

    entity_id: Uuid
    entity_type: CanonicalTypeToken
    owner_context: BoundedContext
    resource_scope: ResourceScope
    resource_tenant_id: NotRequired[ResourceTenantId]


class PinFields(TypedDict):
    """urn:datacompany:pinned-version-ref:1 — generated."""

    content_hash: ContentHash
    resolved_at: Timestamp
    schema_ref: SchemaRef
    version_id: Uuid
    version_number: VersionNumber


class EvidenceLocationFields(TypedDict):
    """urn:datacompany:evidence-location-version:1 — generated."""

    artifact_ref: NotRequired[ArtifactRef]
    content_hash: NotRequired[ContentHash]
    coordinate_manifest_ref: NotRequired[PinnedVersionRef]
    document_version_ref: NotRequired[DocumentVersionRef]
    evidence_location_id: Uuid
    language: Bcp47Locale
    quoted_text_digest: NotRequired[PayloadDigest]
    selector_schema_ref: SchemaRef


ContentHash = NewType("ContentHash", str)


Uuid = NewType("Uuid", str)


BoundedContext = NewType("BoundedContext", str)


Timestamp = NewType("Timestamp", str)


ResourceScope = Literal["global", "tenant"]


VersionNumber = NewType("VersionNumber", int)


Cursor = NewType("Cursor", str)


class PageRequest(TypedDict):
    """urn:datacompany:page:1 — generated."""

    cursor: NotRequired[Cursor]
    page_size: NotRequired[int]
    sort: SortRequest


class PageRequestFields(TypedDict):
    """urn:datacompany:page:1 — generated."""

    cursor: NotRequired[Cursor]
    page_size: NotRequired[int]
    sort: SortRequest


class PageResponse(TypedDict):
    """urn:datacompany:page:1 — generated."""

    items: list[object]
    next_cursor: NotRequired[Cursor]
    sort: SortRequest


SortDirection = Literal["ascending", "descending"]


class SortKey(TypedDict):
    """urn:datacompany:page:1 — generated."""

    direction: SortDirection
    field: SortField


class ProblemFields(TypedDict):
    """urn:datacompany:problem-details:1 — generated."""

    code: ProblemCode
    correlation_id: Uuid
    issues: NotRequired[list[FieldIssue]]
    message: str
    retryable: bool
    status: HttpStatus


class FieldIssue(TypedDict):
    """urn:datacompany:problem-details:1 — generated."""

    code: ProblemCode
    pointer: str
    severity: IssueSeverity


HttpStatus = NewType("HttpStatus", int)


PackReleaseStatus = Literal["deprecated", "discovered", "installed", "verified", "withdrawn"]


class ProfileReleaseDescriptor(TypedDict):
    """urn:datacompany:release-ref:1 — generated."""

    default_locale: Bcp47Locale
    id: ReleaseId
    kernel_compatibility: str
    pack_refs: ReleaseRefList
    policy_bundle_ref: NotRequired[ReleaseRef]
    qualification_suite_ref: NotRequired[ReleaseRef]
    status: ProfileReleaseStatus
    supported_locales: list[Bcp47Locale]
    version: Semver
    workflow_bundle_ref: NotRequired[ReleaseRef]


ProfileReleaseStatus = Literal["candidate", "deprecated", "published", "verified", "withdrawn"]


ReleaseId = NewType("ReleaseId", str)


ReleaseRef = NewType("ReleaseRef", str)


Semver = NewType("Semver", str)


class ContextFields(TypedDict):
    """urn:datacompany:research-access-context:1 — generated."""

    actor_id: ActorSubject
    actor_tenant_id: Uuid
    causation_id: Uuid
    correlation_id: Uuid
    data_classes: list[DataClassToken]
    delegation_id: NotRequired[Uuid]
    entitlements: list[EntitlementToken]
    expires_at: Timestamp
    idempotency_key: NotRequired[IdempotencyKey]
    initiated_by: NotRequired[ActorSubject]
    pack_refs: NotRequired[ReleaseRefList]
    policy_version: Uuid
    profile_ref: NotRequired[ReleaseRef]
    project_id: NotRequired[Uuid]
    protocol_version_id: NotRequired[Uuid]
    purpose: Purpose
    requested_at: Timestamp
    resource_scope: ResourceScope
    resource_tenant_id: NotRequired[ResourceTenantId]
    roles: list[RoleToken]
    workspace_id: NotRequired[Uuid]


ActorSubject = NewType("ActorSubject", str)


IdempotencyKey = NewType("IdempotencyKey", str)


Purpose = Literal["administration", "publication", "research", "review"]


class StableIdentity(TypedDict):
    """urn:datacompany:stable-identity:1 — generated."""

    aggregate_version: int
    created_at: Timestamp
    created_by: ActorSubject
    entity_id: Uuid
    entity_type: CanonicalTypeToken
    resource_scope: ResourceScope
    resource_tenant_id: NotRequired[ResourceTenantId]


class IdentityFields(TypedDict):
    """urn:datacompany:stable-identity:1 — generated."""

    aggregate_version: int
    created_at: Timestamp
    created_by: ActorSubject
    entity_id: Uuid
    entity_type: CanonicalTypeToken
    resource_scope: ResourceScope
    resource_tenant_id: NotRequired[ResourceTenantId]


class ManifestFields(TypedDict):
    """urn:datacompany:run-manifest:1 — generated."""

    approvals: NotRequired[Approvals]
    content_hash: ContentHash
    environment: Environment
    extraction: NotRequired[Extraction]
    inputs: Inputs
    method: Method
    outputs: Outputs
    rights: NotRequired[Rights]
    run_manifest_id: Uuid
    run_ref: PinnedVersionRef
    schema_ref: SchemaRef
    sources: NotRequired[list[Source]]
    versions: Versions


class Approvals(TypedDict):
    """urn:datacompany:run-manifest:1 — generated."""

    approval_refs: SetOfPins
    supersedes_ref: NotRequired[PinnedVersionRef]


class Environment(TypedDict):
    """urn:datacompany:run-manifest:1 — generated."""

    application_commit: str
    hardware_class: NotRequired[FreeText]
    image_digest: PayloadDigest
    numerical_library_versions: NotRequired[list[FreeText]]
    operating_system: NotRequired[FreeText]
    validation_suite_version: FreeText


class Extraction(TypedDict):
    """urn:datacompany:run-manifest:1 — generated."""

    extraction_model_ref: NotRequired[PinnedVersionRef]
    parser_version: NotRequired[FreeText]
    prompt_ref: NotRequired[PinnedVersionRef]
    proposal_ref: NotRequired[PinnedVersionRef]


class Inputs(TypedDict):
    """urn:datacompany:run-manifest:1 — generated."""

    input_hash: ContentHash
    input_refs: SetOfPins
    parameters: list[Parameter]


class Method(TypedDict):
    """urn:datacompany:run-manifest:1 — generated."""

    convergence_policy: NotRequired[FreeText]
    engine_provider: BoundedContext
    engine_version: FreeText
    method_id: CanonicalTypeToken
    packages: list[FreeText]
    seed: NotRequired[BoundedInteger]
    tolerance_policy: NotRequired[DecimalString]


class Outputs(TypedDict):
    """urn:datacompany:run-manifest:1 — generated."""

    artifact_refs: list[ArtifactOutput]


class Rights(TypedDict):
    """urn:datacompany:run-manifest:1 — generated."""

    rights_status: CanonicalTypeToken
    translation_status: NotRequired[CanonicalTypeToken]


class Source(TypedDict):
    """urn:datacompany:run-manifest:1 — generated."""

    document_hash: PayloadDigest
    edition: NotRequired[FreeText]
    etag: NotRequired[FreeText]
    last_modified: NotRequired[Timestamp]
    retrieved_at: Timestamp
    source_url: str


class Versions(TypedDict):
    """urn:datacompany:run-manifest:1 — generated."""

    mapping_refs: NotRequired[SetOfPins]
    pack_refs: NotRequired[ReleaseRefList]
    profile_ref: NotRequired[ReleaseRef]
    protocol_version_ref: PinnedVersionRef
    schema_refs: list[SchemaRef]
    template_refs: NotRequired[SetOfPins]
    terminology_release_refs: NotRequired[SetOfPins]


class EvidenceLocationRef(TypedDict):
    """urn:datacompany:typed-refs:1 — generated."""

    content_hash: ContentHash
    entity_id: Uuid
    entity_type: CanonicalTypeToken
    owner_context: BoundedContext
    resolved_at: Timestamp
    resource_scope: ResourceScope
    resource_tenant_id: NotRequired[ResourceTenantId]
    schema_ref: Literal["urn:datacompany:evidence-location-version:1"]
    version_id: Uuid
    version_number: VersionNumber


class RightsDecisionRef(TypedDict):
    """urn:datacompany:typed-refs:1 — generated."""

    content_hash: ContentHash
    entity_id: Uuid
    entity_type: CanonicalTypeToken
    owner_context: BoundedContext
    resolved_at: Timestamp
    resource_scope: ResourceScope
    resource_tenant_id: NotRequired[ResourceTenantId]
    schema_ref: Literal["urn:datacompany:rights-decision-version:1"]
    version_id: Uuid
    version_number: VersionNumber


class DocumentSelector(TypedDict):
    """urn:datacompany:locator-selector:1 — generated."""

    bbox: NotRequired[BboxFractions]
    block_id: NotRequired[str]
    character_span: NotRequired[CharacterSpan]
    page: int
    section_path: NotRequired[list[str]]
    table: NotRequired[TableCell]


class TabularSelector(TypedDict):
    """urn:datacompany:locator-selector:1 — generated."""

    cell_range: str
    row_id: NotRequired[str]
    row_index: NotRequired[int]
    sheet_or_table_id: str
    value_digest: PayloadDigest


class MediaSelector(TypedDict):
    """urn:datacompany:locator-selector:1 — generated."""

    end_ms: int
    frame_range: NotRequired[FrameRange]
    start_ms: int
    track: str


class TranscriptSelector(TypedDict):
    """urn:datacompany:locator-selector:1 — generated."""

    character_span: CharacterSpan
    end_ms: int
    speaker_id: str
    start_ms: int
    turn_index: int


class NotebookSelector(TypedDict):
    """urn:datacompany:locator-selector:1 — generated."""

    cell_id: str
    cell_version: str
    notebook_id: str
    output_id: NotRequired[str]


class CodeSelector(TypedDict):
    """urn:datacompany:locator-selector:1 — generated."""

    bundle_version: str
    column_range: NotRequired[ColumnRange]
    line_range: LineRange
    path: str
    source_digest: PayloadDigest


IssueSeverity = Literal["error", "warning"]


FreeText = NewType("FreeText", str)


class Parameter(TypedDict):
    """urn:datacompany:run-manifest:1 — generated."""

    name: CanonicalTypeToken
    value_boolean: NotRequired[bool]
    value_decimal: NotRequired[DecimalString]
    value_integer: NotRequired[BoundedInteger]
    value_text: NotRequired[FreeText]


BoundedInteger = NewType("BoundedInteger", int)


DecimalString = NewType("DecimalString", str)


class ArtifactOutput(TypedDict):
    """urn:datacompany:run-manifest:1 — generated."""

    artifact_ref: PinnedVersionRef
    payload_digest: PayloadDigest


class CharacterSpan(TypedDict):
    """urn:datacompany:locator-selector:1 — generated."""

    end: int
    start: int


class TableCell(TypedDict):
    """urn:datacompany:locator-selector:1 — generated."""

    column: int
    row: int
    table_id: str


class FrameRange(TypedDict):
    """urn:datacompany:locator-selector:1 — generated."""

    first: int
    last: int


class ColumnRange(TypedDict):
    """urn:datacompany:locator-selector:1 — generated."""

    first: int
    last: int


class LineRange(TypedDict):
    """urn:datacompany:locator-selector:1 — generated."""

    first: int
    last: int


SetOfPins = list[PinnedVersionRef]


AnySelector = (
    DocumentSelector
    | TabularSelector
    | MediaSelector
    | TranscriptSelector
    | NotebookSelector
    | CodeSelector
)


ResourceTenantId = Uuid


SortField = CanonicalTypeToken


SortRequest = list[SortKey]


ProblemCode = CanonicalTypeToken


ReleaseRefList = list[ReleaseRef]


DataClassToken = CanonicalTypeToken


EntitlementToken = CanonicalTypeToken


RoleToken = CanonicalTypeToken


BboxFractions = list[DecimalString]
