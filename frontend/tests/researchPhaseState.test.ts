import assert from 'node:assert/strict'
import test from 'node:test'

import { createPinia, setActivePinia } from 'pinia'

import {
  isAnnotationSetReadOnly,
  restoreSelectedSegmentId,
  useResearchPhasesStore,
} from '../src/stores/researchPhases.ts'

const sampleSegment = {
  id: 20,
  annotation_set_id: 11,
  phase_label_id: 2,
  start_frame: 40,
  end_frame_exclusive: 120,
  source: 'manual' as const,
  confidence: 0.85,
  notes: 'note',
  created_at: '2026-07-22T00:00:00Z',
  updated_at: '2026-07-22T00:00:00Z',
  phase_label: {
    id: 2,
    key: 'prep',
    name: 'Prep',
    color: '#22c55e',
  },
}

function createAnnotationSet(
  revision = 3,
  status: 'draft' | 'submitted' | 'reviewed' | 'locked' = 'draft',
  segments = [sampleSegment],
) {
  return {
    id: 11,
    video_id: 9,
    protocol_id: 5,
    annotator_id: 2,
    status,
    revision,
    submitted_at: status === 'submitted' ? '2026-07-22T01:00:00Z' : null,
    created_at: '2026-07-22T00:00:00Z',
    updated_at: '2026-07-22T00:00:00Z',
    protocol_name: 'Default protocol',
    protocol_version: 1,
    annotator_username: 'alice',
    segment_count: segments.length,
    has_open_segment: segments.some((segment) => segment.end_frame_exclusive === null),
    protocol: {
      id: 5,
      name: 'Default protocol',
      version: 1,
      description: null,
      status: 'active' as const,
      is_default: true,
      label_count: 2,
      labels: [
        {
          id: 2,
          protocol_id: 5,
          key: 'prep',
          name: 'Prep',
          color: '#22c55e',
          display_order: 1,
          shortcut: '1',
          description: null,
          is_active: true,
        },
        {
          id: 3,
          protocol_id: 5,
          key: 'operate',
          name: 'Operate',
          color: '#f97316',
          display_order: 2,
          shortcut: '2',
          description: null,
          is_active: true,
        },
      ],
    },
    segments,
  }
}

function createMutationResponse(revision: number, action: 'transitioned' | 'unchanged' = 'transitioned') {
  return {
    action,
    annotation_set: createAnnotationSet(revision),
    changed_segment_ids: [20],
    created_segment_ids: action === 'transitioned' ? [20] : [],
    deleted_segment_ids: [],
  }
}

function createStatusMutationResponse(
  revision: number,
  status: 'draft' | 'submitted',
) {
  const detail = createAnnotationSet(revision, status)
  return {
    action: status === 'submitted' ? 'submitted' : 'reopened',
    annotation_set: detail,
    validation: status === 'submitted'
      ? {
        annotation_set_id: detail.id,
        video_id: detail.video_id,
        revision: detail.revision,
        status: detail.status,
        frame_count: 200,
        segment_count: 1,
        closed_segment_count: 1,
        open_segment_count: 0,
        closed_covered_frame_count: 80,
        closed_coverage_percent: 40,
        issue_counts: {
          error: 0,
          warning: 0,
          info: 0,
        },
        issues: [],
        is_valid: true,
        can_submit: true,
        requires_warning_confirmation: false,
      }
      : null,
  }
}

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'Content-Type': 'application/json',
    },
  })
}

function blobResponse(body: string, headers: Record<string, string>) {
  return new Response(new Blob([body], { type: 'text/csv;charset=utf-8' }), {
    status: 200,
    headers,
  })
}

function useFreshStore() {
  setActivePinia(createPinia())
  return useResearchPhasesStore()
}

test('applyAnnotationSet replaces local annotation set and preserves server revision', () => {
  const store = useFreshStore()
  const detail = createAnnotationSet(7, 'draft', [
    { ...sampleSegment, id: 22, start_frame: 150, end_frame_exclusive: 180 },
    { ...sampleSegment, id: 21, start_frame: 10, end_frame_exclusive: 40 },
  ])

  store.applyAnnotationSet(detail)

  assert.equal(store.currentAnnotationSet?.revision, 7)
  assert.deepEqual(store.segments.map((segment) => segment.id), [21, 22])
})

test('transition success replaces annotation set from server response', async () => {
  const store = useFreshStore()
  store.applyAnnotationSet(createAnnotationSet(3))
  globalThis.fetch = async () => jsonResponse(createMutationResponse(4))

  const result = await store.transitionPhase(2, 40)

  assert.equal(result.ok, true)
  assert.equal(store.currentAnnotationSet?.revision, 4)
  assert.equal(store.saveState, 'saved')
})

test('unchanged mutation does not invent a new revision on the client', async () => {
  const store = useFreshStore()
  store.applyAnnotationSet(createAnnotationSet(3))
  globalThis.fetch = async () => jsonResponse(createMutationResponse(3, 'unchanged'))

  const result = await store.transitionPhase(2, 40)

  assert.equal(result.ok, true)
  assert.equal(store.currentAnnotationSet?.revision, 3)
})

test('submitted annotation sets are treated as read-only until reopened', () => {
  const store = useFreshStore()
  store.applyAnnotationSet(createAnnotationSet(4, 'submitted'))

  const draftCheck = store.requireDraftAnnotationSet()

  assert.equal(isAnnotationSetReadOnly(store.currentAnnotationSet?.status), true)
  assert.equal(draftCheck.ok, false)
})

test('submit warning confirmation uses a distinct 409 path and succeeds on second confirmation', async () => {
  const store = useFreshStore()
  store.applyAnnotationSet(createAnnotationSet(3))
  let callCount = 0
  globalThis.fetch = async () => {
    callCount += 1
    if (callCount === 1) {
      return jsonResponse({
        detail: {
          message: 'Phase annotation set has warnings that require confirmation.',
          validation: createStatusMutationResponse(3, 'submitted').validation,
        },
      }, 409)
    }
    return jsonResponse(createStatusMutationResponse(4, 'submitted'))
  }

  const first = await store.submitAnnotationSet(false)
  const second = await store.submitAnnotationSet(true)

  assert.equal(first.ok, false)
  if (first.ok) {
    throw new Error('expected warning confirmation')
  }
  assert.equal(first.error.kind, 'warning_confirmation')
  assert.equal(store.currentAnnotationSet?.revision, 4)
  assert.equal(second.ok, true)
  assert.equal(store.currentAnnotationSet?.status, 'submitted')
})

test('revision conflicts keep local state untouched and mark the store as conflicted', async () => {
  const store = useFreshStore()
  store.applyAnnotationSet(createAnnotationSet(3))
  globalThis.fetch = async () => jsonResponse({
    detail: {
      message: 'Phase annotation set revision conflict.',
      current_revision: 8,
    },
  }, 409)

  const result = await store.transitionPhase(2, 40)

  assert.equal(result.ok, false)
  if (result.ok) {
    throw new Error('expected conflict result')
  }
  assert.equal(result.error.kind, 'conflict')
  assert.equal(store.currentAnnotationSet?.revision, 3)
  assert.equal(store.saveState, 'conflict')
  assert.equal(store.conflictState?.currentRevision, 8)
})

test('reopen success restores draft editing and clears submitted_at', async () => {
  const store = useFreshStore()
  store.applyAnnotationSet(createAnnotationSet(4, 'submitted'))
  globalThis.fetch = async () => jsonResponse(createStatusMutationResponse(5, 'draft'))

  const result = await store.reopenAnnotationSet()

  assert.equal(result.ok, true)
  assert.equal(store.currentAnnotationSet?.status, 'draft')
  assert.equal(store.currentAnnotationSet?.submitted_at, null)
  assert.equal(store.currentAnnotationSet?.revision, 5)
})

test('restoreSelectedSegmentId recovers existing selections and clears removed ones', () => {
  assert.equal(restoreSelectedSegmentId(20, [{ id: 20 }, { id: 21 }]), 20)
  assert.equal(restoreSelectedSegmentId(20, [{ id: 21 }]), null)
})

test('stale async protocol responses do not overwrite a newer video session', async () => {
  const store = useFreshStore()
  let resolveFetch: ((response: Response) => void) | null = null
  globalThis.fetch = async () => new Promise((resolve) => {
    resolveFetch = resolve
  })

  store.startVideoSession(9)
  const pending = store.fetchProtocols()
  store.startVideoSession(10)
  resolveFetch?.(jsonResponse([{ id: 1, name: 'Old', version: 1, description: null, status: 'active', is_default: true, label_count: 2 }]))
  await pending

  assert.deepEqual(store.protocols, [])
})

test('frame-wise export keeps revision/status unchanged and revokes object URLs', async () => {
  const store = useFreshStore()
  store.applyAnnotationSet(createAnnotationSet(6, 'draft'))
  globalThis.fetch = async () => blobResponse('frame_index\n0\n', {
    'Content-Disposition': `attachment; filename*=UTF-8''%E4%B8%AD%E6%96%87_phase_framewise.csv`,
    'X-Phase-Validation-Errors': '2',
    'X-Phase-Validation-Warnings': '5',
  })

  const createdUrls: string[] = []
  const revokedUrls: string[] = []
  const clickedDownloads: string[] = []
  const originalDocument = globalThis.document
  const originalCreateObjectUrl = URL.createObjectURL
  const originalRevokeObjectUrl = URL.revokeObjectURL

  Object.assign(globalThis, {
    document: {
      body: {
        appendChild() {},
      },
      createElement() {
        return {
          href: '',
          download: '',
          click() {
            clickedDownloads.push(this.download)
          },
          remove() {},
        }
      },
    },
  })
  URL.createObjectURL = () => {
    const url = `blob:${createdUrls.length + 1}`
    createdUrls.push(url)
    return url
  }
  URL.revokeObjectURL = (url: string) => {
    revokedUrls.push(url)
  }

  try {
    const result = await store.downloadFramewiseCsv()

    assert.equal(result.ok, true)
    if (!result.ok) {
      throw new Error('expected successful export')
    }
    assert.equal(result.data.validationErrors, 2)
    assert.equal(result.data.validationWarnings, 5)
    assert.equal(store.currentAnnotationSet?.revision, 6)
    assert.equal(store.currentAnnotationSet?.status, 'draft')
    assert.deepEqual(clickedDownloads, ['中文_phase_framewise.csv'])
    assert.deepEqual(revokedUrls, createdUrls)
  } finally {
    Object.assign(globalThis, {
      document: originalDocument,
    })
    URL.createObjectURL = originalCreateObjectUrl
    URL.revokeObjectURL = originalRevokeObjectUrl
  }
})
