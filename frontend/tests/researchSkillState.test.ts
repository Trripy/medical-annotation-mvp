import assert from 'node:assert/strict'
import test from 'node:test'

import { createPinia, setActivePinia } from 'pinia'

import { isSkillRevisionConflict, useResearchSkillsStore } from '../src/stores/researchSkills.ts'
import type { ResearchSkillAssessmentDetail, ResearchSkillMutationResponse } from '../src/types/researchSkill.ts'

function createAssessment(revision = 1, status: 'draft' | 'submitted' = 'draft'): ResearchSkillAssessmentDetail {
  return {
    id: 1,
    video_id: 9,
    rubric_id: 1,
    rater_id: 2,
    phase_annotation_set_id: null,
    status,
    revision,
    overall_comment: null,
    submitted_at: status === 'submitted' ? '2026-07-23T00:00:00Z' : null,
    reviewed_at: null,
    locked_at: null,
    created_at: '',
    updated_at: '',
    rubric_name: 'Rubric',
    rubric_version: 1,
    rater_username: 'reader',
    score_count: 0,
    video: { id: 9, name: 'Video', fps: 25, frame_count: 100, duration_ms: 4000 },
    rubric: {
      id: 1,
      name: 'Rubric',
      version: 1,
      description: null,
      status: 'active',
      phase_protocol_id: null,
      created_by_id: null,
      criterion_count: 1,
      created_at: '',
      updated_at: '',
      criteria: [],
    },
    phase_annotation_set: null,
    scores: [],
    completion: { required_total: 0, required_completed: 0, overall_required_total: 0, overall_required_completed: 0, phase_required_total: 0, phase_required_completed: 0, completion_percent: 100 },
  }
}

function mutationResponse(revision: number, action: 'updated' | 'unchanged' = 'updated'): ResearchSkillMutationResponse {
  return {
    action,
    assessment: createAssessment(revision),
    changed_score_ids: [],
    created_score_ids: [],
    deleted_score_ids: [],
    changed_evidence_ids: [],
    created_evidence_ids: [],
    deleted_evidence_ids: [],
  }
}

function useFreshStore() {
  setActivePinia(createPinia())
  const store = useResearchSkillsStore()
  store.applyAssessment(createAssessment(1))
  return store
}

test('server response replaces local revision and unchanged does not invent revision', () => {
  const store = useFreshStore()
  store.applyAssessment(createAssessment(7))
  assert.equal(store.currentAssessment?.revision, 7)
  store.applyAssessment(mutationResponse(7, 'unchanged').assessment)
  assert.equal(store.currentAssessment?.revision, 7)
})

test('submitted assessment is read-only until reopen response', () => {
  const store = useFreshStore()
  store.applyAssessment(createAssessment(4, 'submitted'))
  assert.equal(store.isReadOnly, true)
  store.applyAssessment(createAssessment(5, 'draft'))
  assert.equal(store.isReadOnly, false)
})

test('revision conflict detection is distinct from warning confirmation', () => {
  assert.equal(isSkillRevisionConflict({ message: 'Skill assessment revision conflict.', current_revision: 3 }), true)
  assert.equal(isSkillRevisionConflict({ message: 'Skill assessment has warnings that require confirmation.' }), false)
})

test('mutation queue runs serially and second mutation uses latest revision', async () => {
  const store = useFreshStore()
  const revisions: number[] = []
  const first = store.enqueueAssessmentMutation(async (revision) => {
    revisions.push(revision)
    store.applyAssessment(createAssessment(2))
    return { ok: true, data: mutationResponse(2) }
  })
  const second = store.enqueueAssessmentMutation(async (revision) => {
    revisions.push(revision)
    store.applyAssessment(createAssessment(3))
    return { ok: true, data: mutationResponse(3) }
  })
  await Promise.all([first, second])
  assert.deepEqual(revisions, [1, 2])
  assert.equal(store.currentAssessment?.revision, 3)
})

test('conflict clears subsequent mutation queue', async () => {
  const store = useFreshStore()
  let secondRan = false
  const first = await store.enqueueAssessmentMutation(async () => ({
    ok: false,
    error: {
      kind: 'conflict',
      message: 'Skill assessment revision conflict.',
      currentRevision: 9,
      validation: null,
      detail: null,
    },
  }))
  await store.enqueueAssessmentMutation(async () => {
    secondRan = true
    return { ok: true, data: mutationResponse(2) }
  })
  assert.equal(first.ok, false)
  assert.equal(store.saveState, 'conflict')
  assert.equal(secondRan, false)
})

test('session switch ignores stale queued response', async () => {
  const store = useFreshStore()
  const pending = store.enqueueAssessmentMutation(async () => {
    store.startVideoSession(10)
    return { ok: true, data: mutationResponse(2) }
  })
  await pending
  assert.equal(store.currentAssessment, null)
})

test('assessment switch clears target and selection state', async () => {
  const store = useFreshStore()
  store.selectedTargetType = 'phase_segment'
  store.selectedPhaseSegmentId = 12
  store.selectedCriterionId = 3
  store.selectedScoreId = 4
  globalThis.fetch = async () => new Response(JSON.stringify(createAssessment(2)), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })

  await store.selectAssessment(2)

  assert.equal(store.selectedTargetType, 'overall')
  assert.equal(store.selectedPhaseSegmentId, null)
  assert.equal(store.selectedCriterionId, null)
  assert.equal(store.selectedScoreId, null)
  assert.equal(store.currentAssessment?.revision, 2)
})

test('export does not modify revision and revokes object URL', async () => {
  const store = useFreshStore()
  let revoked = ''
  globalThis.fetch = async () => new Response(new Blob(['{}'], { type: 'application/json' }), {
    status: 200,
    headers: { 'Content-Disposition': "attachment; filename*=UTF-8''skill.json" },
  })
  const originalDocument = globalThis.document
  const originalUrl = globalThis.URL
  globalThis.document = {
    body: { appendChild() {} },
    createElement() {
      return { href: '', download: '', click() {}, remove() {} }
    },
  } as unknown as Document
  globalThis.URL = {
    createObjectURL() { return 'blob:skill' },
    revokeObjectURL(value: string) { revoked = value },
  } as unknown as typeof URL

  try {
    const result = await store.downloadJson()

    assert.equal(result.ok, true)
    assert.equal(store.currentAssessment?.revision, 1)
    await new Promise((resolve) => setTimeout(resolve, 0))
    assert.equal(revoked, 'blob:skill')
  } finally {
    globalThis.document = originalDocument
    globalThis.URL = originalUrl
  }
})
