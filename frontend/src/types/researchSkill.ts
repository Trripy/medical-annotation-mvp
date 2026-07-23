export type ResearchSkillRubricStatus = 'draft' | 'active' | 'archived'
export type ResearchSkillAssessmentStatus = 'draft' | 'submitted' | 'reviewed' | 'locked'
export type ResearchSkillCriterionScope = 'overall' | 'phase'
export type ResearchSkillScoreType = 'integer_scale' | 'number' | 'single_choice' | 'boolean' | 'text'
export type ResearchSkillTargetType = 'overall' | 'phase_segment'
export type ResearchSkillMutationAction =
  | 'created'
  | 'updated'
  | 'deleted'
  | 'unchanged'
  | 'evidence_created'
  | 'evidence_updated'
  | 'evidence_deleted'
export type ResearchSkillStatusMutationAction = 'submitted' | 'reopened'
export type ResearchSkillValidationSeverity = 'error' | 'warning' | 'info'
export type ResearchSkillValidationIssueType =
  | 'missing_required_score'
  | 'invalid_value'
  | 'na_not_allowed'
  | 'phase_score_without_segment'
  | 'segment_not_in_selected_phase_set'
  | 'criterion_not_applicable'
  | 'assessment_phase_set_missing'
  | 'assessment_phase_set_draft'
  | 'rubric_not_active'
  | 'inactive_criterion'
  | 'evidence_out_of_bounds'
  | 'incomplete_phase_criteria'

export type ResearchSkillPhaseLabel = {
  id: number
  key: string
  name: string
  color: string
}

export type ResearchSkillCriterion = {
  id: number
  rubric_id: number
  key: string
  name: string
  description: string | null
  scope: ResearchSkillCriterionScope
  score_type: ResearchSkillScoreType
  min_value: number | null
  max_value: number | null
  step: number | null
  options_json: Array<{ value: string; label: string }> | null
  required: boolean
  allow_na: boolean
  weight: number | null
  display_order: number
  is_active: boolean
  phase_label_ids: number[]
  phase_labels: ResearchSkillPhaseLabel[]
  created_at: string
  updated_at: string
}

export type ResearchSkillCriterionPhaseLabel = {
  criterion_id: number
  phase_label_id: number
}

export type ResearchSkillRubricSummary = {
  id: number
  name: string
  version: number
  description: string | null
  status: ResearchSkillRubricStatus
  phase_protocol_id: number | null
  created_by_id: number | null
  criterion_count: number
  created_at: string
  updated_at: string
}

export type ResearchSkillRubricDetail = ResearchSkillRubricSummary & {
  criteria: ResearchSkillCriterion[]
}

export type ResearchSkillVideoSummary = {
  id: number
  name: string
  fps: number | null
  frame_count: number
  duration_ms: number | null
}

export type ResearchSkillPhaseSegment = {
  id: number
  phase_label_id: number
  phase_key: string
  phase_name: string
  start_frame: number
  end_frame_exclusive: number | null
}

export type ResearchSkillPhaseAnnotationSet = {
  id: number
  protocol_id: number
  status: string
  revision: number
  segments: ResearchSkillPhaseSegment[]
}

export type ResearchSkillEvidence = {
  id: number
  skill_score_id: number
  start_frame: number
  end_frame_exclusive: number | null
  comment: string | null
  created_at: string
  updated_at: string
}

export type ResearchSkillScore = {
  id: number
  assessment_id: number
  criterion_id: number
  criterion_key: string
  criterion_name: string
  scope: ResearchSkillCriterionScope
  score_type: ResearchSkillScoreType
  target_key: string
  phase_segment_id: number | null
  value: unknown
  is_na: boolean
  comment: string | null
  evidence: ResearchSkillEvidence[]
  created_at: string
  updated_at: string
}

export type ResearchSkillCompletion = {
  required_total: number
  required_completed: number
  overall_required_total: number
  overall_required_completed: number
  phase_required_total: number
  phase_required_completed: number
  completion_percent: number
}

export type ResearchSkillAssessmentSummary = {
  id: number
  video_id: number
  rubric_id: number
  rater_id: number
  phase_annotation_set_id: number | null
  status: ResearchSkillAssessmentStatus
  revision: number
  overall_comment: string | null
  submitted_at: string | null
  reviewed_at: string | null
  locked_at: string | null
  created_at: string
  updated_at: string
  rubric_name: string
  rubric_version: number
  rater_username: string
  score_count: number
}

export type ResearchSkillAssessmentDetail = ResearchSkillAssessmentSummary & {
  video: ResearchSkillVideoSummary
  rubric: ResearchSkillRubricDetail
  phase_annotation_set: ResearchSkillPhaseAnnotationSet | null
  scores: ResearchSkillScore[]
  completion: ResearchSkillCompletion
}

export type ResearchSkillValidationIssue = {
  issue_type: ResearchSkillValidationIssueType
  severity: ResearchSkillValidationSeverity
  message: string
  criterion_id: number | null
  score_id: number | null
  phase_segment_id: number | null
  evidence_id: number | null
  details: Record<string, unknown>
}

export type ResearchSkillValidationResponse = {
  assessment_id: number
  revision: number
  status: ResearchSkillAssessmentStatus
  required_total: number
  required_completed: number
  completion_percent: number
  issue_counts: { error: number; warning: number; info: number }
  issues: ResearchSkillValidationIssue[]
  is_valid: boolean
  can_submit: boolean
  requires_warning_confirmation: boolean
}

export type CreateSkillRubricRequest = {
  name: string
  version?: number
  description?: string | null
  phase_protocol_id?: number | null
  username?: string | null
}

export type UpdateSkillRubricRequest = {
  name?: string | null
  description?: string | null
  phase_protocol_id?: number | null
  clear_phase_protocol?: boolean
}

export type CloneSkillRubricRequest = {
  name?: string | null
  description?: string | null
}

export type CreateSkillCriterionRequest = {
  key: string
  name: string
  description?: string | null
  scope: ResearchSkillCriterionScope
  score_type: ResearchSkillScoreType
  min_value?: number | null
  max_value?: number | null
  step?: number | null
  options_json?: Array<{ value: string; label: string }> | null
  required?: boolean
  allow_na?: boolean
  weight?: number | null
  display_order: number
  is_active?: boolean
  phase_label_ids?: number[]
}

export type UpdateSkillCriterionRequest = Partial<CreateSkillCriterionRequest> & {
  clear_weight?: boolean
}

export type CreateSkillAssessmentRequest = {
  rubric_id: number
  username: string
  phase_annotation_set_id?: number | null
}

export type UpdateSkillAssessmentRequest = {
  overall_comment?: string | null
  clear_overall_comment?: boolean
  phase_annotation_set_id?: number | null
  clear_phase_annotation_set?: boolean
  expected_revision: number
}

export type UpsertSkillScoreRequest = {
  target_type: ResearchSkillTargetType
  phase_segment_id?: number | null
  value?: unknown
  is_na?: boolean
  comment?: string | null
  clear_comment?: boolean
  expected_revision: number
}

export type CreateSkillEvidenceRequest = {
  start_frame: number
  end_frame_exclusive?: number | null
  comment?: string | null
  expected_revision: number
}

export type UpdateSkillEvidenceRequest = {
  start_frame?: number | null
  end_frame_exclusive?: number | null
  clear_end_frame?: boolean
  comment?: string | null
  clear_comment?: boolean
  expected_revision: number
}

export type SubmitSkillAssessmentRequest = {
  expected_revision: number
  confirm_warnings?: boolean
}

export type ReopenSkillAssessmentRequest = {
  expected_revision: number
}

export type ResearchSkillMutationResponse = {
  action: ResearchSkillMutationAction
  assessment: ResearchSkillAssessmentDetail
  changed_score_ids: number[]
  created_score_ids: number[]
  deleted_score_ids: number[]
  changed_evidence_ids: number[]
  created_evidence_ids: number[]
  deleted_evidence_ids: number[]
}

export type ResearchSkillStatusMutationResponse = {
  action: ResearchSkillStatusMutationAction
  assessment: ResearchSkillAssessmentDetail
  validation: ResearchSkillValidationResponse | null
}

export type CreateSkillAssessmentResponse = {
  created: boolean
  assessment: ResearchSkillAssessmentDetail
}

export type ResearchSkillConflictDetail = {
  message: string
  current_revision?: number | null
}

export type ResearchSkillValidationErrorDetail = {
  message: string
  validation?: ResearchSkillValidationResponse
}
