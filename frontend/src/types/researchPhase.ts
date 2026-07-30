export type ResearchPhaseProtocolStatus = 'draft' | 'active' | 'archived'
export type ResearchPhaseLabelMappingProfileStatus = 'draft' | 'published' | 'archived'
export type ResearchPhaseAnnotationSetStatus = 'draft' | 'submitted' | 'reviewed' | 'locked'
export type ResearchPhaseSegmentSource = 'manual' | 'model_suggestion' | 'model_corrected' | 'imported'
export type ResearchPhaseMutationAction =
  | 'created'
  | 'transitioned'
  | 'closed'
  | 'updated'
  | 'unchanged'
  | 'deleted'
  | 'split'
  | 'merged'
export type ResearchPhaseStatusMutationAction = 'submitted' | 'reopened'
export type ResearchPhaseValidationSeverity = 'error' | 'warning' | 'info'
export type ResearchPhaseValidationIssueType =
  | 'no_segments'
  | 'open_segment'
  | 'overlap'
  | 'gap'
  | 'zero_length'
  | 'out_of_bounds'
  | 'inactive_label'
  | 'adjacent_same_label'
  | 'unusual_order'
  | 'very_short_segment'
  | 'video_end_not_covered'
  | 'duplicate_start'

export type ResearchPhaseLabel = {
  id: number
  protocol_id: number
  key: string
  name: string
  color: string
  display_order: number
  shortcut: string | null
  description: string | null
  is_active: boolean
}

export type ResearchPhaseProtocolSummary = {
  id: number
  name: string
  version: number
  description: string | null
  status: ResearchPhaseProtocolStatus
  is_default: boolean
  label_count: number
}

export type ResearchPhaseProtocolDetail = ResearchPhaseProtocolSummary & {
  labels: ResearchPhaseLabel[]
}

export type ResearchPhaseLabelMappingSourceLabel = {
  id: number
  key: string
  name: string
  color: string
  display_order: number
}

export type ResearchPhaseLabelMappingTarget = {
  id: number
  profile_id: number
  key: string
  name: string
  color: string
  order_index: number
  source_labels: ResearchPhaseLabelMappingSourceLabel[]
}

export type ResearchPhaseLabelMappingProfileSummary = {
  id: number
  protocol_id: number
  name: string
  description: string | null
  version: number
  status: ResearchPhaseLabelMappingProfileStatus
  created_by_id: number | null
  created_at: string
  updated_at: string
  source_label_count: number
  target_count: number
  merged_group_count: number
  unmapped_label_count: number
}

export type ResearchPhaseLabelMappingProfileDetail = ResearchPhaseLabelMappingProfileSummary & {
  targets: ResearchPhaseLabelMappingTarget[]
}

export type CreateResearchPhaseLabelMappingProfileRequest = {
  name: string
  description?: string | null
  version?: number
  created_by_id?: number | null
  initialize_identity_mapping?: boolean
}

export type MergeResearchPhaseMappingClassesRequest = {
  source_label_ids: number[]
  target_key: string
  target_name: string
  target_color: string
}

export type UnmergeResearchPhaseMappingTargetRequest = {
  target_id: number
}

export type DuplicateResearchPhaseLabelMappingProfileRequest = {
  name: string
  description?: string | null
}

export type ResearchPhaseSegmentPhaseLabel = {
  id: number
  key: string
  name: string
  color: string
}

export type ResearchPhaseSegment = {
  id: number
  annotation_set_id: number
  phase_label_id: number
  start_frame: number
  end_frame_exclusive: number | null
  source: ResearchPhaseSegmentSource
  confidence: number | null
  notes: string | null
  created_at: string
  updated_at: string
  phase_label: ResearchPhaseSegmentPhaseLabel
}

export type ResearchPhaseAnnotationSetSummary = {
  id: number
  video_id: number
  protocol_id: number
  annotator_id: number
  status: ResearchPhaseAnnotationSetStatus
  revision: number
  submitted_at: string | null
  created_at: string
  updated_at: string
  protocol_name: string
  protocol_version: number
  annotator_username: string
  segment_count: number
  has_open_segment: boolean
}

export type ResearchPhaseAnnotationSetDetail = ResearchPhaseAnnotationSetSummary & {
  protocol: ResearchPhaseProtocolDetail
  segments: ResearchPhaseSegment[]
}

export type CreateResearchPhaseAnnotationSetRequest = {
  protocol_id: number
  username: string
}

export type CreateResearchPhaseAnnotationSetResponse = {
  created: boolean
  annotation_set: ResearchPhaseAnnotationSetDetail
}

export type CreateResearchPhaseSegmentRequest = {
  phase_label_id: number
  start_frame: number
  end_frame_exclusive: number | null
  source?: ResearchPhaseSegmentSource
  confidence?: number | null
  notes?: string | null
  expected_revision: number
}

export type TransitionResearchPhaseRequest = {
  phase_label_id: number
  current_frame: number
  expected_revision: number
}

export type CloseActivePhaseSegmentRequest = {
  end_frame_exclusive: number
  expected_revision: number
}

export type UpdateResearchPhaseSegmentRequest = {
  phase_label_id?: number | null
  start_frame?: number | null
  end_frame_exclusive?: number | null
  clear_end_frame?: boolean
  source?: ResearchPhaseSegmentSource | null
  confidence?: number | null
  clear_confidence?: boolean
  notes?: string | null
  clear_notes?: boolean
  expected_revision: number
}

export type SplitPhaseSegmentRequest = {
  split_frame: number
  expected_revision: number
}

export type MergePhaseSegmentsRequest = {
  left_segment_id: number
  right_segment_id: number
  expected_revision: number
}

export type SubmitPhaseAnnotationSetRequest = {
  expected_revision: number
  confirm_warnings?: boolean
}

export type ReopenPhaseAnnotationSetRequest = {
  expected_revision: number
}

export type ResearchPhaseMutationResponse = {
  action: ResearchPhaseMutationAction
  annotation_set: ResearchPhaseAnnotationSetDetail
  changed_segment_ids: number[]
  created_segment_ids: number[]
  deleted_segment_ids: number[]
}

export type ResearchPhaseValidationIssue = {
  issue_type: ResearchPhaseValidationIssueType
  severity: ResearchPhaseValidationSeverity
  message: string
  segment_id: number | null
  related_segment_id: number | null
  frame_start: number | null
  frame_end_exclusive: number | null
  details: Record<string, unknown>
}

export type ResearchPhaseValidationIssueCounts = {
  error: number
  warning: number
  info: number
}

export type ResearchPhaseValidationResponse = {
  annotation_set_id: number
  video_id: number
  revision: number
  status: ResearchPhaseAnnotationSetStatus
  frame_count: number
  segment_count: number
  closed_segment_count: number
  open_segment_count: number
  closed_covered_frame_count: number
  closed_coverage_percent: number
  issue_counts: ResearchPhaseValidationIssueCounts
  issues: ResearchPhaseValidationIssue[]
  is_valid: boolean
  can_submit: boolean
  requires_warning_confirmation: boolean
}

export type ResearchPhaseStatusMutationResponse = {
  action: ResearchPhaseStatusMutationAction
  annotation_set: ResearchPhaseAnnotationSetDetail
  validation: ResearchPhaseValidationResponse | null
}

export type ResearchPhaseConflictDetail = {
  message: string
  current_revision?: number | null
}

export type ResearchPhaseValidationErrorDetail = {
  message: string
  validation?: ResearchPhaseValidationResponse
}
