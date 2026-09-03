import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

import {
  applyDefaultPhaseSelections,
  buildBatchExportPayload,
  latestSubmittedSet,
  resolveResearchVideoThumbnailUrl,
  selectLatestSubmittedPhaseExports,
  setPhaseExportSelection,
  setTrimSelection,
  summarizeSelections,
  type ChecklistItem,
  type VideoExportSelection,
} from '../src/utils/researchVideoChecklist.ts'

function item(id: number, sets: ChecklistItem['phase']['sets'] = []): ChecklistItem {
  return {
    video: {
      id,
      display_name: `video-${id}.mp4`,
      status: 'ready',
      duration_ms: 1000,
      fps: 25,
      frame_count: 25,
      width: 320,
      height: 240,
      created_at: '2026-07-30T00:00:00Z',
      thumbnail_url: null,
      hidden_from_video_list: false,
      hidden_at: null,
      hidden_reason: null,
      notes: null,
    },
    trim: {
      origin_type: 'uploaded',
      is_trimmed: false,
      source_video_id: null,
      source_video_display_name: null,
      trim_start_frame: null,
      trim_end_frame_exclusive: null,
      trim_start_time_ms: null,
      trim_end_time_ms: null,
      kept_frame_count: null,
      kept_duration_ms: null,
      derived_video_count: 0,
      derived_video_ids: [],
      latest_derived_at: null,
      derived_videos: [],
    },
    phase: {
      annotation_set_count: sets.length,
      draft_count: sets.filter((set) => set.status === 'draft').length,
      submitted_count: sets.filter((set) => set.status === 'submitted').length,
      latest_annotation_set_id: sets[0]?.annotation_set_id ?? null,
      latest_status: sets[0]?.status ?? null,
      latest_version: sets[0]?.version ?? null,
      latest_protocol_id: sets[0]?.protocol_id ?? null,
      latest_protocol_name: sets[0]?.protocol_name ?? null,
      latest_segment_count: sets[0]?.segment_count ?? 0,
      latest_coverage_percent: sets[0]?.coverage_percent ?? 0,
      latest_error_count: sets[0]?.error_count ?? 0,
      latest_warning_count: sets[0]?.warning_count ?? 0,
      latest_updated_at: sets[0]?.updated_at ?? null,
      latest_submitted_at: sets[0]?.submitted_at ?? null,
      sets,
    },
  }
}

function annotationSet(id: number, status: string, submittedAt: string | null = null) {
  return {
    annotation_set_id: id,
    status,
    version: id,
    protocol_id: 3,
    protocol_name: 'Cataract',
    segment_count: 12,
    coverage_percent: 100,
    error_count: 0,
    warning_count: 0,
    updated_at: `2026-07-30T00:0${id}:00Z`,
    submitted_at: submittedAt,
    available_mapping_profiles: [
      { id: 20, name: 'Merged', version: 1, status: 'published', key: 'merged' },
    ],
  }
}

test('video list includes checklist entry and router exposes static checklist route before dynamic video id route', () => {
  const videosPage = readFileSync(new URL('../src/views/ResearchVideosPage.vue', import.meta.url), 'utf8')
  const router = readFileSync(new URL('../src/router.ts', import.meta.url), 'utf8')

  assert.match(videosPage, /videoChecklist\.entry/)
  assert.match(videosPage, /\/research\/videos\/checklist/)
  assert.ok(router.indexOf("path: '/research/videos/checklist'") < router.indexOf("path: '/research/videos/:videoId/annotate'"))
})

test('selection payload only contains selected artifacts keyed by video id', () => {
  const selections = new Map<number, VideoExportSelection>()

  setTrimSelection(selections, 54, true)
  setPhaseExportSelection(selections, 55, 6, null)
  setPhaseExportSelection(selections, 55, 8, 2)

  assert.deepEqual(summarizeSelections(selections), {
    videoCount: 2,
    trimCount: 1,
    phaseCount: 2,
    hasSelection: true,
  })
  assert.deepEqual(buildBatchExportPayload(selections), {
    items: [
      { video_id: 54, include_trim_info: true, phase_exports: [] },
      {
        video_id: 55,
        include_trim_info: false,
        phase_exports: [
          { annotation_set_id: 6, mapping_profile_id: null },
          { annotation_set_id: 8, mapping_profile_id: 2 },
        ],
      },
    ],
    include_summary_csv: true,
    batch_name: null,
  })
})

test('latest submitted shortcut skips drafts and preserves existing trim selections', () => {
  const selections = new Map<number, VideoExportSelection>()
  setTrimSelection(selections, 1, true)

  const result = selectLatestSubmittedPhaseExports(selections, [
    item(1, [annotationSet(1, 'draft'), annotationSet(2, 'submitted', '2026-07-30T00:02:00Z')]),
    item(2, [annotationSet(3, 'draft')]),
  ])

  assert.deepEqual(result, { selected: 1, skipped: 1 })
  assert.equal(selections.get(1)?.includeTrimInfo, true)
  assert.deepEqual(selections.get(1)?.phaseExports, [{ annotationSetId: 2, mappingProfileId: null }])
  assert.equal(selections.has(2), false)
})

test('latestSubmittedSet selects the newest submitted annotation set', () => {
  const selected = latestSubmittedSet(item(1, [
    annotationSet(4, 'submitted', '2026-07-30T00:04:00Z'),
    annotationSet(5, 'submitted', '2026-07-30T00:05:00Z'),
    annotationSet(6, 'draft'),
  ]))

  assert.equal(selected?.annotation_set_id, 5)
})

test('latestSubmittedSet uses submitted_at then version then id and skips drafts', () => {
  const selected = latestSubmittedSet(item(1, [
    annotationSet(7, 'draft', null),
    { ...annotationSet(8, 'submitted', '2026-07-30T00:05:00Z'), version: 1 },
    { ...annotationSet(9, 'submitted', '2026-07-30T00:05:00Z'), version: 2 },
  ]))

  assert.equal(selected?.annotation_set_id, 9)
})

test('default selections apply original labels and respect manual overrides', () => {
  const selections = new Map<number, VideoExportSelection>()

  const result = applyDefaultPhaseSelections(selections, [
    {
      video_id: 1,
      annotation_set_id: 10,
      status: 'submitted',
      version: 3,
      submitted_at: '2026-07-30T00:00:00Z',
      protocol_id: 5,
      protocol_name: 'Cataract',
    },
    {
      video_id: 2,
      annotation_set_id: 20,
      status: 'submitted',
      version: 4,
      submitted_at: '2026-07-30T01:00:00Z',
      protocol_id: 5,
      protocol_name: 'Cataract',
    },
  ], new Set([2]))

  assert.deepEqual(result, { selected: 1, skippedByOverride: 1 })
  assert.deepEqual(selections.get(1)?.phaseExports, [{ annotationSetId: 10, mappingProfileId: null }])
  assert.equal(selections.has(2), false)
})

test('checklist thumbnail URL uses the same resolved API URL shape as video list thumbnails', () => {
  const url = resolveResearchVideoThumbnailUrl('/api/research/videos/54/thumbnail', 54)

  assert.match(url, /^http:\/\/.*:8000\/api\/research\/videos\/54\/thumbnail\?v=54$/)
  assert.equal(resolveResearchVideoThumbnailUrl(null), '')
})

test('checklist page does not use array indexes as export selection keys', () => {
  const source = readFileSync(new URL('../src/views/ResearchVideoChecklistPage.vue', import.meta.url), 'utf8')

  assert.match(source, /Map<number,\s*VideoExportSelection>/)
  assert.match(source, /row-key="video\.id"/)
  assert.doesNotMatch(source, /selectedExports\.value\.set\(index/)
  assert.match(source, /video-batch-export\/preview/)
  assert.match(source, /video-batch-export/)
})
