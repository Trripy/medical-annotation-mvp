import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildIntervalEvidence,
  buildPointEvidence,
  evidenceToUiRange,
  sortSkillEvidence,
  uiRangeToEvidence,
} from '../src/utils/researchSkill.ts'

test('buildPointEvidence uses current 0-based frame', () => {
  assert.deepEqual(buildPointEvidence(12), { start_frame: 12, end_frame_exclusive: null })
})

test('buildIntervalEvidence supports forward, reverse, and same-frame intervals', () => {
  assert.deepEqual(buildIntervalEvidence(10, 15), { start_frame: 10, end_frame_exclusive: 16 })
  assert.deepEqual(buildIntervalEvidence(15, 10), { start_frame: 10, end_frame_exclusive: 16 })
  assert.deepEqual(buildIntervalEvidence(10, 10), { start_frame: 10, end_frame_exclusive: 11 })
})

test('UI evidence conversion is 1-based and inclusive end maps to end-exclusive', () => {
  assert.deepEqual(evidenceToUiRange({ start_frame: 0, end_frame_exclusive: null }), { startFrame: 1, endFrame: null })
  assert.deepEqual(evidenceToUiRange({ start_frame: 9, end_frame_exclusive: 20 }), { startFrame: 10, endFrame: 20 })
  assert.deepEqual(uiRangeToEvidence(10, 20), { start_frame: 9, end_frame_exclusive: 20 })
})

test('sortSkillEvidence orders by start frame then id', () => {
  assert.deepEqual(sortSkillEvidence([
    { id: 3, skill_score_id: 1, start_frame: 20, end_frame_exclusive: null, comment: null, created_at: '', updated_at: '' },
    { id: 2, skill_score_id: 1, start_frame: 10, end_frame_exclusive: null, comment: null, created_at: '', updated_at: '' },
    { id: 1, skill_score_id: 1, start_frame: 10, end_frame_exclusive: null, comment: null, created_at: '', updated_at: '' },
  ]).map((item) => item.id), [1, 2, 3])
})
