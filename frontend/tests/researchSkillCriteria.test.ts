import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildIntegerScaleOptions,
  buildPhaseSegmentOccurrences,
  findSkillScore,
  getApplicableCriteria,
  isCriterionApplicableToTarget,
  isSkillScoreComplete,
  normalizeScorePayloadValue,
  sortSkillCriteria,
} from '../src/utils/researchSkill.ts'
import type { ResearchSkillAssessmentDetail, ResearchSkillCriterion, ResearchSkillPhaseSegment } from '../src/types/researchSkill.ts'

const overallCriterion = {
  id: 1,
  rubric_id: 1,
  key: 'overall',
  name: 'Overall',
  description: null,
  scope: 'overall',
  score_type: 'integer_scale',
  min_value: 1,
  max_value: 5,
  step: 1,
  options_json: null,
  required: true,
  allow_na: false,
  weight: null,
  display_order: 2,
  is_active: true,
  phase_label_ids: [],
  phase_labels: [],
  created_at: '',
  updated_at: '',
} satisfies ResearchSkillCriterion

const phaseAllCriterion = {
  ...overallCriterion,
  id: 2,
  key: 'phase_all',
  name: 'Phase all',
  scope: 'phase',
  score_type: 'number',
  display_order: 1,
} satisfies ResearchSkillCriterion

const phaseFilteredCriterion = {
  ...phaseAllCriterion,
  id: 3,
  key: 'phase_filtered',
  name: 'Phase filtered',
  phase_label_ids: [10],
  display_order: 0,
} satisfies ResearchSkillCriterion

const segment = {
  id: 20,
  phase_label_id: 10,
  phase_key: 'incision',
  phase_name: 'Incision',
  start_frame: 10,
  end_frame_exclusive: 20,
} satisfies ResearchSkillPhaseSegment

function assessment(): ResearchSkillAssessmentDetail {
  return {
    id: 1,
    video_id: 1,
    rubric_id: 1,
    rater_id: 1,
    phase_annotation_set_id: 1,
    status: 'draft',
    revision: 1,
    overall_comment: null,
    submitted_at: null,
    reviewed_at: null,
    locked_at: null,
    created_at: '',
    updated_at: '',
    rubric_name: 'Rubric',
    rubric_version: 1,
    rater_username: 'reader',
    score_count: 0,
    video: { id: 1, name: 'Video', fps: 25, frame_count: 100, duration_ms: 4000 },
    rubric: {
      id: 1,
      name: 'Rubric',
      version: 1,
      description: null,
      status: 'active',
      phase_protocol_id: 1,
      created_by_id: null,
      criterion_count: 3,
      created_at: '',
      updated_at: '',
      criteria: [overallCriterion, phaseAllCriterion, phaseFilteredCriterion],
    },
    phase_annotation_set: { id: 1, protocol_id: 1, status: 'submitted', revision: 1, segments: [segment] },
    scores: [],
    completion: {
      required_total: 0,
      required_completed: 0,
      overall_required_total: 0,
      overall_required_completed: 0,
      phase_required_total: 0,
      phase_required_completed: 0,
      completion_percent: 100,
    },
  }
}

test('criterion applicability distinguishes overall and phase targets', () => {
  assert.equal(isCriterionApplicableToTarget(overallCriterion, null), true)
  assert.equal(isCriterionApplicableToTarget(overallCriterion, segment), false)
  assert.equal(isCriterionApplicableToTarget(phaseAllCriterion, segment), true)
  assert.equal(isCriterionApplicableToTarget(phaseAllCriterion, null), false)
})

test('phase_label_ids empty means all labels and non-empty filters labels', () => {
  assert.equal(isCriterionApplicableToTarget(phaseAllCriterion, { phase_label_id: 999 }), true)
  assert.equal(isCriterionApplicableToTarget(phaseFilteredCriterion, { phase_label_id: 10 }), true)
  assert.equal(isCriterionApplicableToTarget(phaseFilteredCriterion, { phase_label_id: 11 }), false)
})

test('criteria sorting and applicable criteria follow display_order then id', () => {
  assert.deepEqual(sortSkillCriteria([overallCriterion, phaseAllCriterion, phaseFilteredCriterion]).map((item) => item.id), [3, 2, 1])
  assert.deepEqual(getApplicableCriteria(assessment(), 'phase', segment).map((item) => item.id), [3, 2])
  assert.deepEqual(getApplicableCriteria(assessment(), 'overall', null).map((item) => item.id), [1])
})

test('phase occurrence numbering handles repeated phases', () => {
  const occurrences = buildPhaseSegmentOccurrences([
    { ...segment, id: 21, start_frame: 40 },
    { ...segment, id: 20, start_frame: 10 },
  ])
  assert.deepEqual(occurrences.map((item) => item.displayName), ['Incision #1', 'Incision #2'])
})

test('score controls helper distinguishes false, N/A, and completion', () => {
  assert.deepEqual(buildIntegerScaleOptions(1, 5, 1), [1, 2, 3, 4, 5])
  assert.equal(normalizeScorePayloadValue('x', true), null)
  assert.equal(isSkillScoreComplete(null), false)
  assert.equal(isSkillScoreComplete({ id: 1, assessment_id: 1, criterion_id: 1, criterion_key: 'b', criterion_name: 'Boolean', scope: 'overall', score_type: 'boolean', target_key: 'overall', phase_segment_id: null, value: false, is_na: false, comment: null, evidence: [], created_at: '', updated_at: '' }), true)
  assert.equal(isSkillScoreComplete({ id: 2, assessment_id: 1, criterion_id: 1, criterion_key: 'na', criterion_name: 'NA', scope: 'overall', score_type: 'text', target_key: 'overall', phase_segment_id: null, value: null, is_na: true, comment: null, evidence: [], created_at: '', updated_at: '' }), true)
})

test('findSkillScore uses stable target key identity', () => {
  const scores = [
    { id: 1, assessment_id: 1, criterion_id: 3, criterion_key: 'phase_filtered', criterion_name: 'Phase filtered', scope: 'phase', score_type: 'number', target_key: 'segment:20', phase_segment_id: 20, value: 8, is_na: false, comment: null, evidence: [], created_at: '', updated_at: '' },
  ]
  assert.equal(findSkillScore(scores, 3, 'phase_segment', 20)?.id, 1)
  assert.equal(findSkillScore(scores, 3, 'phase_segment', 21), null)
})
