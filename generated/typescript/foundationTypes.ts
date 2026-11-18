/**
 * GENERATED FILE — do not edit by hand.
 *
 * Regenerate with `python scripts/generate_types.py`; CI runs the same script with
 * `--check` and fails on any difference, so an edit here is reverted by the next gate.
 *
 * These are STRUCTURAL bindings, not validators. They say what a consumer programs
 * against; they do not enforce a pattern, an interval, a scope conditional or any
 * released cross-field rule. Validation is `research_contracts.canonical.validate_instance`
 * in Python and the canonical package in TypeScript. A value that type-checks here has
 * not been validated.
 */

export interface CapabilityStatus {
  available: boolean;
  capability_id: CanonicalTypeToken;
  data_classes?: CanonicalTypeToken[];
  enabled: boolean;
  installed: boolean;
  method_id?: CanonicalTypeToken;
  provider_health?: "absent" | "degraded" | "healthy" | "unhealthy";
  qualification_report_ref?: PinnedVersionRef;
  qualified: boolean;
  required_for_publication: boolean;
  unavailable_reason?: UnavailableReason;
  use_modes?: UseMode[];
}

export interface EvidenceLocationCandidate {
  artifact_ref?: ArtifactRef;
  coordinate_manifest_ref?: PinnedVersionRef;
  derivation_provenance_refs: SetOfPins;
  document_version_ref?: DocumentVersionRef;
  language: Bcp47Locale;
  quoted_text_digest?: PayloadDigest;
  selector: AnySelector;
  selector_schema_ref: SchemaRef;
  selector_type: SelectorKind;
}

export interface EvidenceLocationVersion {
  artifact_ref?: ArtifactRef;
  content_hash: ContentHash;
  coordinate_manifest_ref?: PinnedVersionRef;
  document_version_ref?: DocumentVersionRef;
  entity_id: Uuid;
  entity_type: CanonicalTypeToken;
  evidence_location_id: Uuid;
  language: Bcp47Locale;
  owner_context: BoundedContext;
  quoted_text_digest?: PayloadDigest;
  resolved_at: Timestamp;
  resource_scope: ResourceScope;
  resource_tenant_id?: ResourceTenantId;
  schema_ref: SchemaRef;
  selector: AnySelector;
  selector_schema_ref: SchemaRef;
  selector_type: SelectorKind;
  version_id: Uuid;
  version_number: VersionNumber;
}

export interface ProblemDetails {
  code: ProblemCode;
  correlation_id: Uuid;
  issues?: FieldIssue[];
  message: string;
  retryable: boolean;
  status: HttpStatus;
}

export interface ResearchAccessContext {
  actor_id: ActorSubject;
  actor_tenant_id: Uuid;
  causation_id: Uuid;
  correlation_id: Uuid;
  data_classes: DataClassToken[];
  delegation_id?: Uuid;
  entitlements: EntitlementToken[];
  expires_at: Timestamp;
  idempotency_key?: IdempotencyKey;
  initiated_by?: ActorSubject;
  pack_refs?: ReleaseRefList;
  policy_version: Uuid;
  profile_ref?: ReleaseRef;
  project_id?: Uuid;
  protocol_version_id?: Uuid;
  purpose: Purpose;
  requested_at: Timestamp;
  resource_scope: ResourceScope;
  resource_tenant_id?: ResourceTenantId;
  roles: RoleToken[];
  workspace_id?: Uuid;
}

export interface RunManifest {
  aggregate_version: number;
  approvals?: Approvals;
  content_hash: ContentHash;
  created_at: Timestamp;
  created_by: ActorSubject;
  entity_id: Uuid;
  entity_type: CanonicalTypeToken;
  environment: Environment;
  extraction?: Extraction;
  inputs: Inputs;
  method: Method;
  outputs: Outputs;
  resource_scope: ResourceScope;
  resource_tenant_id?: ResourceTenantId;
  rights?: Rights;
  run_manifest_id: Uuid;
  run_ref: PinnedVersionRef;
  schema_ref: SchemaRef;
  sources?: Source[];
  versions: Versions;
}

export interface StatusFields {
  available: boolean;
  capability_id: CanonicalTypeToken;
  data_classes?: CanonicalTypeToken[];
  enabled: boolean;
  installed: boolean;
  method_id?: CanonicalTypeToken;
  provider_health?: "absent" | "degraded" | "healthy" | "unhealthy";
  qualification_report_ref?: PinnedVersionRef;
  qualified: boolean;
  required_for_publication: boolean;
  unavailable_reason?: UnavailableReason;
  use_modes?: UseMode[];
}

export type CanonicalTypeToken = string & { readonly __brand: "CanonicalTypeToken" };

export interface PinnedVersionRef {
  content_hash: ContentHash;
  entity_id: Uuid;
  entity_type: CanonicalTypeToken;
  owner_context: BoundedContext;
  resolved_at: Timestamp;
  resource_scope: ResourceScope;
  resource_tenant_id?: ResourceTenantId;
  schema_ref: SchemaRef;
  version_id: Uuid;
  version_number: VersionNumber;
}

export type UnavailableReason = "degraded" | "disabled" | "not_installed" | "optional_provider_absent" | "rights_unavailable" | "stale_projection" | "temporarily_unavailable" | "unentitled" | "unhealthy" | "unqualified";

export type UseMode = "exploratory" | "publication";

export interface CandidateFields {
  artifact_ref?: ArtifactRef;
  coordinate_manifest_ref?: PinnedVersionRef;
  derivation_provenance_refs: SetOfPins;
  document_version_ref?: DocumentVersionRef;
  language: Bcp47Locale;
  quoted_text_digest?: PayloadDigest;
  selector_schema_ref: SchemaRef;
}

export interface SelectorFields {
  selector: AnySelector;
  selector_type: SelectorKind;
}

export interface ArtifactRef {
  content_hash: ContentHash;
  entity_id: Uuid;
  entity_type: CanonicalTypeToken;
  owner_context: BoundedContext;
  resolved_at: Timestamp;
  resource_scope: ResourceScope;
  resource_tenant_id?: ResourceTenantId;
  schema_ref: "urn:datacompany:artifact-version:1";
  version_id: Uuid;
  version_number: VersionNumber;
}

export interface DocumentVersionRef {
  content_hash: ContentHash;
  entity_id: Uuid;
  entity_type: CanonicalTypeToken;
  owner_context: BoundedContext;
  resolved_at: Timestamp;
  resource_scope: ResourceScope;
  resource_tenant_id?: ResourceTenantId;
  schema_ref: "urn:datacompany:document-version:1";
  version_id: Uuid;
  version_number: VersionNumber;
}

export type Bcp47Locale = string & { readonly __brand: "Bcp47Locale" };

export type PayloadDigest = string & { readonly __brand: "PayloadDigest" };

export type SchemaRef = string & { readonly __brand: "SchemaRef" };

export type SelectorKind = "code" | "document" | "media" | "notebook" | "tabular" | "transcript";

export interface IdentityRefFields {
  entity_id: Uuid;
  entity_type: CanonicalTypeToken;
  owner_context: BoundedContext;
  resource_scope: ResourceScope;
  resource_tenant_id?: ResourceTenantId;
}

export interface PinFields {
  content_hash: ContentHash;
  resolved_at: Timestamp;
  schema_ref: SchemaRef;
  version_id: Uuid;
  version_number: VersionNumber;
}

export interface EvidenceLocationFields {
  artifact_ref?: ArtifactRef;
  content_hash?: ContentHash;
  coordinate_manifest_ref?: PinnedVersionRef;
  document_version_ref?: DocumentVersionRef;
  evidence_location_id: Uuid;
  language: Bcp47Locale;
  quoted_text_digest?: PayloadDigest;
  selector_schema_ref: SchemaRef;
}

export type ContentHash = string & { readonly __brand: "ContentHash" };

export type Uuid = string & { readonly __brand: "Uuid" };

export type BoundedContext = string & { readonly __brand: "BoundedContext" };

export type Timestamp = string & { readonly __brand: "Timestamp" };

export type ResourceScope = "global" | "tenant";

export type VersionNumber = number & { readonly __brand: "VersionNumber" };

export type Cursor = string & { readonly __brand: "Cursor" };

export interface PageRequest {
  cursor?: Cursor;
  page_size?: number;
  sort: SortRequest;
}

export interface PageRequestFields {
  cursor?: Cursor;
  page_size?: number;
  sort: SortRequest;
}

export interface PageResponse {
  items: unknown[];
  next_cursor?: Cursor;
  sort: SortRequest;
}

export type SortDirection = "ascending" | "descending";

export interface SortKey {
  direction: SortDirection;
  field: SortField;
}

export interface ProblemFields {
  code: ProblemCode;
  correlation_id: Uuid;
  issues?: FieldIssue[];
  message: string;
  retryable: boolean;
  status: HttpStatus;
}

export interface FieldIssue {
  code: ProblemCode;
  pointer: string;
  severity: IssueSeverity;
}

export type HttpStatus = number & { readonly __brand: "HttpStatus" };

export type PackReleaseStatus = "deprecated" | "discovered" | "installed" | "verified" | "withdrawn";

export interface ProfileReleaseDescriptor {
  default_locale: Bcp47Locale;
  id: ReleaseId;
  kernel_compatibility: string;
  pack_refs: ReleaseRefList;
  policy_bundle_ref?: ReleaseRef;
  qualification_suite_ref?: ReleaseRef;
  status: ProfileReleaseStatus;
  supported_locales: Bcp47Locale[];
  version: Semver;
  workflow_bundle_ref?: ReleaseRef;
}

export type ProfileReleaseStatus = "candidate" | "deprecated" | "published" | "verified" | "withdrawn";

export type ReleaseId = string & { readonly __brand: "ReleaseId" };

export type ReleaseRef = string & { readonly __brand: "ReleaseRef" };

export type Semver = string & { readonly __brand: "Semver" };

export interface ContextFields {
  actor_id: ActorSubject;
  actor_tenant_id: Uuid;
  causation_id: Uuid;
  correlation_id: Uuid;
  data_classes: DataClassToken[];
  delegation_id?: Uuid;
  entitlements: EntitlementToken[];
  expires_at: Timestamp;
  idempotency_key?: IdempotencyKey;
  initiated_by?: ActorSubject;
  pack_refs?: ReleaseRefList;
  policy_version: Uuid;
  profile_ref?: ReleaseRef;
  project_id?: Uuid;
  protocol_version_id?: Uuid;
  purpose: Purpose;
  requested_at: Timestamp;
  resource_scope: ResourceScope;
  resource_tenant_id?: ResourceTenantId;
  roles: RoleToken[];
  workspace_id?: Uuid;
}

export type ActorSubject = string & { readonly __brand: "ActorSubject" };

export type IdempotencyKey = string & { readonly __brand: "IdempotencyKey" };

export type Purpose = "administration" | "publication" | "research" | "review";

export interface StableIdentity {
  aggregate_version: number;
  created_at: Timestamp;
  created_by: ActorSubject;
  entity_id: Uuid;
  entity_type: CanonicalTypeToken;
  resource_scope: ResourceScope;
  resource_tenant_id?: ResourceTenantId;
}

export interface IdentityFields {
  aggregate_version: number;
  created_at: Timestamp;
  created_by: ActorSubject;
  entity_id: Uuid;
  entity_type: CanonicalTypeToken;
  resource_scope: ResourceScope;
  resource_tenant_id?: ResourceTenantId;
}

export interface ManifestFields {
  approvals?: Approvals;
  content_hash: ContentHash;
  environment: Environment;
  extraction?: Extraction;
  inputs: Inputs;
  method: Method;
  outputs: Outputs;
  rights?: Rights;
  run_manifest_id: Uuid;
  run_ref: PinnedVersionRef;
  schema_ref: SchemaRef;
  sources?: Source[];
  versions: Versions;
}

export interface Approvals {
  approval_refs: SetOfPins;
  supersedes_ref?: PinnedVersionRef;
}

export interface Environment {
  application_commit: string;
  hardware_class?: FreeText;
  image_digest: PayloadDigest;
  numerical_library_versions?: FreeText[];
  operating_system?: FreeText;
  validation_suite_version: FreeText;
}

export interface Extraction {
  extraction_model_ref?: PinnedVersionRef;
  parser_version?: FreeText;
  prompt_ref?: PinnedVersionRef;
  proposal_ref?: PinnedVersionRef;
}

export interface Inputs {
  input_hash: ContentHash;
  input_refs: SetOfPins;
  parameters: Parameter[];
}

export interface Method {
  convergence_policy?: FreeText;
  engine_provider: BoundedContext;
  engine_version: FreeText;
  method_id: CanonicalTypeToken;
  packages: FreeText[];
  seed?: BoundedInteger;
  tolerance_policy?: DecimalString;
}

export interface Outputs {
  artifact_refs: ArtifactOutput[];
}

export interface Rights {
  rights_status: CanonicalTypeToken;
  translation_status?: CanonicalTypeToken;
}

export interface Source {
  document_hash: PayloadDigest;
  edition?: FreeText;
  etag?: FreeText;
  last_modified?: Timestamp;
  retrieved_at: Timestamp;
  source_url: string;
}

export interface Versions {
  mapping_refs?: SetOfPins;
  pack_refs?: ReleaseRefList;
  profile_ref?: ReleaseRef;
  protocol_version_ref: PinnedVersionRef;
  schema_refs: SchemaRef[];
  template_refs?: SetOfPins;
  terminology_release_refs?: SetOfPins;
}

export interface EvidenceLocationRef {
  content_hash: ContentHash;
  entity_id: Uuid;
  entity_type: CanonicalTypeToken;
  owner_context: BoundedContext;
  resolved_at: Timestamp;
  resource_scope: ResourceScope;
  resource_tenant_id?: ResourceTenantId;
  schema_ref: "urn:datacompany:evidence-location-version:1";
  version_id: Uuid;
  version_number: VersionNumber;
}

export interface RightsDecisionRef {
  content_hash: ContentHash;
  entity_id: Uuid;
  entity_type: CanonicalTypeToken;
  owner_context: BoundedContext;
  resolved_at: Timestamp;
  resource_scope: ResourceScope;
  resource_tenant_id?: ResourceTenantId;
  schema_ref: "urn:datacompany:rights-decision-version:1";
  version_id: Uuid;
  version_number: VersionNumber;
}

export interface DocumentSelector {
  bbox?: BboxFractions;
  block_id?: string;
  character_span?: CharacterSpan;
  page: number;
  section_path?: string[];
  table?: TableCell;
}

export interface TabularSelector {
  cell_range: string;
  row_id?: string;
  row_index?: number;
  sheet_or_table_id: string;
  value_digest: PayloadDigest;
}

export interface MediaSelector {
  end_ms: number;
  frame_range?: FrameRange;
  start_ms: number;
  track: string;
}

export interface TranscriptSelector {
  character_span: CharacterSpan;
  end_ms: number;
  speaker_id: string;
  start_ms: number;
  turn_index: number;
}

export interface NotebookSelector {
  cell_id: string;
  cell_version: string;
  notebook_id: string;
  output_id?: string;
}

export interface CodeSelector {
  bundle_version: string;
  column_range?: ColumnRange;
  line_range: LineRange;
  path: string;
  source_digest: PayloadDigest;
}

export type IssueSeverity = "error" | "warning";

export type FreeText = string & { readonly __brand: "FreeText" };

export interface Parameter {
  name: CanonicalTypeToken;
  value_boolean?: boolean;
  value_decimal?: DecimalString;
  value_integer?: BoundedInteger;
  value_text?: FreeText;
}

export type BoundedInteger = number & { readonly __brand: "BoundedInteger" };

export type DecimalString = string & { readonly __brand: "DecimalString" };

export interface ArtifactOutput {
  artifact_ref: PinnedVersionRef;
  payload_digest: PayloadDigest;
}

export interface CharacterSpan {
  end: number;
  start: number;
}

export interface TableCell {
  column: number;
  row: number;
  table_id: string;
}

export interface FrameRange {
  first: number;
  last: number;
}

export interface ColumnRange {
  first: number;
  last: number;
}

export interface LineRange {
  first: number;
  last: number;
}

export type SetOfPins = PinnedVersionRef[];

export type AnySelector = DocumentSelector | TabularSelector | MediaSelector | TranscriptSelector | NotebookSelector | CodeSelector;

export type ResourceTenantId = Uuid;

export type SortField = CanonicalTypeToken;

export type SortRequest = SortKey[];

export type ProblemCode = CanonicalTypeToken;

export type ReleaseRefList = ReleaseRef[];

export type DataClassToken = CanonicalTypeToken;

export type EntitlementToken = CanonicalTypeToken;

export type RoleToken = CanonicalTypeToken;

export type BboxFractions = DecimalString[];
