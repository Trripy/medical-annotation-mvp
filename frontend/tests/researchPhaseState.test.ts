import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
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

test('phase mutations are serialized and later requests use the latest confirmed revision', async () => {
  const store = useFreshStore()
  store.applyAnnotationSet(createAnnotationSet(3))
  const requests: Array<{ url: string, body: string }> = []
  let resolveFirst: ((response: Response) => void) | null = null

  globalThis.fetch = async (input, init) => {
    requests.push({
      url: String(input),
      body: String(init?.body ?? ''),
    })
    if (requests.length === 1) {
      return new Promise<Response>((resolve) => {
        resolveFirst = resolve
      })
    }
    return jsonResponse({
      action: 'created',
      annotation_set: createAnnotationSet(5, 'draft', [
        { ...sampleSegment, end_frame_exclusive: 80 },
        { ...sampleSegment, id: 30, phase_label_id: 3, start_frame: 80, end_frame_exclusive: 160 },
      ]),
      changed_segment_ids: [],
      created_segment_ids: [30],
      deleted_segment_ids: [],
    })
  }

  const update = store.updateSegment(20, { end_frame_exclusive: 80 })
  await new Promise((resolve) => setTimeout(resolve, 0))
  const create = store.createSegment({
    phase_label_id: 3,
    start_frame: 80,
    end_frame_exclusive: 160,
    source: 'manual',
  })

  assert.equal(requests.length, 1)
  assert.match(requests[0].url, /\/api\/research\/phase-segments\/20$/)
  assert.equal(JSON.parse(requests[0].body).expected_revision, 3)

  resolveFirst?.(jsonResponse({
    action: 'updated',
    annotation_set: createAnnotationSet(4, 'draft', [
      { ...sampleSegment, end_frame_exclusive: 80 },
    ]),
    changed_segment_ids: [20],
    created_segment_ids: [],
    deleted_segment_ids: [],
  }))

  const updateResult = await update
  const createResult = await create

  assert.equal(updateResult.ok, true)
  assert.equal(createResult.ok, true)
  assert.equal(requests.length, 2)
  assert.match(requests[1].url, /\/api\/research\/phase-annotation-sets\/11\/segments$/)
  assert.equal(JSON.parse(requests[1].body).expected_revision, 4)
  assert.equal(store.currentAnnotationSet?.revision, 5)
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
    await new Promise((resolve) => setTimeout(resolve, 0))
    assert.deepEqual(revokedUrls, createdUrls)
  } finally {
    Object.assign(globalThis, {
      document: originalDocument,
    })
    URL.createObjectURL = originalCreateObjectUrl
    URL.revokeObjectURL = originalRevokeObjectUrl
  }
})

test('json export uses caller fallback filename when content disposition is unavailable', async () => {
  const store = useFreshStore()
  store.applyAnnotationSet(createAnnotationSet(6, 'submitted'))
  globalThis.fetch = async () => blobResponse('{}', {})

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
  URL.createObjectURL = () => 'blob:phase-json'
  URL.revokeObjectURL = () => {}

  try {
    const result = await store.downloadJson({
      fallbackFilename: '前后联合 张燕平 男 76_cleaned_trimmed.json',
    })

    assert.equal(result.ok, true)
    assert.deepEqual(clickedDownloads, ['前后联合 张燕平 男 76_cleaned_trimmed.json'])
    assert.notDeepEqual(clickedDownloads, ['research-video-9.json'])
    await new Promise((resolve) => setTimeout(resolve, 0))
  } finally {
    Object.assign(globalThis, {
      document: originalDocument,
    })
    URL.createObjectURL = originalCreateObjectUrl
    URL.revokeObjectURL = originalRevokeObjectUrl
  }
})

test('phase note editor keeps note edits local and isolates keyboard shortcuts', () => {
  const inspector = readFileSync(new URL('../src/components/research/PhaseSegmentInspector.vue', import.meta.url), 'utf8')
  const phasePage = readFileSync(new URL('../src/views/ResearchVideoPhasePage.vue', import.meta.url), 'utf8')

  assert.match(inspector, /notesDirty/)
  assert.match(inspector, /@keydown\.stop/)
  assert.match(inspector, /@compositionstart="onNotesCompositionStart"/)
  assert.match(inspector, /:disabled="readOnly"/)
  const textareaMatch = inspector.match(/<textarea[\s\S]*?<\/textarea>/)
  assert.ok(textareaMatch)
  assert.doesNotMatch(textareaMatch[0], /readOnly \|\| saving/)
  assert.match(phasePage, /event\.isComposing/)
  assert.match(phasePage, /event\.keyCode === 229/)
  assert.match(phasePage, /isEditableEventTarget/)
  assert.match(phasePage, /validate: !isNotesOnlyPatch/)
})

test('phase creation in an existing gap starts a pending draft instead of posting a closed segment', () => {
  const phasePage = readFileSync(new URL('../src/views/ResearchVideoPhasePage.vue', import.meta.url), 'utf8')
  const timeline = readFileSync(new URL('../src/components/research/PhaseTimeline.vue', import.meta.url), 'utf8')

  assert.match(phasePage, /waitForPendingMutations\(\)/)
  assert.doesNotMatch(phasePage, /saveState\.value === 'error' \|\| saveState\.value === 'conflict'/)
  assert.match(phasePage, /saving\.value \|\| saveState\.value === 'conflict'/)
  assert.match(phasePage, /type PendingPhaseDraft/)
  assert.match(phasePage, /pendingPhaseDraft = ref<PendingPhaseDraft \| null>\(null\)/)
  assert.match(phasePage, /async function startPendingPhase/)
  assert.match(phasePage, /const candidatePendingDraft: PendingPhaseDraft = \{/)
  assert.match(phasePage, /pendingPhaseDraft\.value = candidatePendingDraft/)
  assert.match(phasePage, /findPhaseGapAtFrame\(segments\.value, selectedFrameIndex\.value, totalFrames\.value\)/)
  assert.match(phasePage, /pendingPhasePreviewEndFrameExclusive/)
  assert.match(phasePage, /async function finishPendingPhase/)
  assert.match(phasePage, /end_frame_exclusive: endFrameExclusive/)
  assert.match(phasePage, /cancelPendingPhase/)
  assert.match(phasePage, /handleBeforeUnload/)
  assert.match(timeline, /pendingSegments\?: ResearchPhaseSegment\[\]/)
  assert.match(timeline, /renderedCoverageGaps[\s\S]*sortedSegments\.value/)
  assert.match(timeline, /isPendingDraft/)
  assert.doesNotMatch(phasePage, /phase_label_id: label\.id,[\s\S]{0,180}end_frame_exclusive: gap\.gapEndFrameExclusive/)
  assert.doesNotMatch(phasePage, /phase_label_id: label\.id,[\s\S]{0,180}end_frame_exclusive: null/)
})

test('next phase after closing starts from server end_frame_exclusive without duplicate start toasts', () => {
  const phasePage = readFileSync(new URL('../src/views/ResearchVideoPhasePage.vue', import.meta.url), 'utf8')

  assert.match(phasePage, /type PhaseNextStartHint/)
  assert.match(phasePage, /const nextPhaseStartHint = ref<PhaseNextStartHint \| null>\(null\)/)
  assert.match(phasePage, /sourceEndFrameExclusive: savedEndFrameExclusive/)
  assert.match(phasePage, /startFrame: savedEndFrameExclusive/)
  assert.match(phasePage, /closedAtPlayheadFrame: Math\.max\(0, savedEndFrameExclusive - 1\)/)
  assert.doesNotMatch(phasePage, /await goToFrame\(endFrameExclusive/)
  assert.match(phasePage, /getUsableNextPhaseStartHint\(\)/)
  assert.match(phasePage, /startPendingPhase\(label, startHint\.startFrame, \{ showSuccessMessage: false \}\)/)
  assert.match(phasePage, /nextPhaseStartsAtFollowingFrame/)
  assert.match(phasePage, /resetFailedPendingPhaseAttempt\(\)/)
})
