import assert from 'node:assert/strict'
import { test } from 'node:test'

import type { ResearchPhaseLabelMappingProfileDetail, ResearchPhaseSegment } from '../src/types/researchPhase.ts'
import {
  buildPhaseExportFilename,
  calculateMappedFrameConservation,
  mapAndMergePhaseSegments,
  slugifyMappingKey,
} from '../src/utils/phaseLabelMapping.ts'

function segment(id: number, phaseLabelId: number, key: string, name: string, start: number, end: number): ResearchPhaseSegment {
  return {
    id,
    annotation_set_id: 1,
    phase_label_id: phaseLabelId,
    start_frame: start,
    end_frame_exclusive: end,
    source: 'manual',
    confidence: null,
    notes: null,
    created_at: '2026-07-30T00:00:00Z',
    updated_at: '2026-07-30T00:00:00Z',
    phase_label: { id: phaseLabelId, key, name, color: '#fff' },
  }
}

const profile: ResearchPhaseLabelMappingProfileDetail = {
  id: 5,
  protocol_id: 1,
  name: 'cataract-lmm-merged',
  description: null,
  version: 1,
  status: 'published',
  created_by_id: null,
  created_at: '2026-07-30T00:00:00Z',
  updated_at: '2026-07-30T00:00:00Z',
  source_label_count: 3,
  target_count: 2,
  merged_group_count: 1,
  unmapped_label_count: 0,
  targets: [
    {
      id: 10,
      profile_id: 5,
      key: 'viscoelastic-or-flush',
      name: 'Viscoelastic/Flush',
      color: '#0ea5e9',
      order_index: 1,
      source_labels: [
        { id: 1, key: 'viscoelastic', name: 'Viscoelastic', color: '#0ea5e9', display_order: 1 },
        { id: 2, key: 'flush', name: 'Flush', color: '#22c55e', display_order: 2 },
      ],
    },
    {
      id: 11,
      profile_id: 5,
      key: 'incision',
      name: 'Incision',
      color: '#f97316',
      order_index: 3,
      source_labels: [
        { id: 3, key: 'incision', name: 'Incision', color: '#f97316', display_order: 3 },
      ],
    },
  ],
}

test('maps and merges adjacent segments with the same target', () => {
  const mapped = mapAndMergePhaseSegments([
    segment(1, 1, 'viscoelastic', 'Viscoelastic', 100, 150),
    segment(2, 2, 'flush', 'Flush', 150, 200),
  ], profile, 300)

  assert.equal(mapped.length, 1)
  assert.equal(mapped[0].start_frame, 100)
  assert.equal(mapped[0].end_frame_exclusive, 200)
  assert.deepEqual(mapped[0].source_segment_ids, [1, 2])
  assert.deepEqual(mapped[0].source_label_ids, [1, 2])
})

test('does not merge across another class or a real gap', () => {
  const mapped = mapAndMergePhaseSegments([
    segment(1, 1, 'viscoelastic', 'Viscoelastic', 100, 150),
    segment(2, 3, 'incision', 'Incision', 150, 170),
    segment(3, 2, 'flush', 'Flush', 170, 200),
    segment(4, 1, 'viscoelastic', 'Viscoelastic', 210, 220),
  ], profile, 300)

  assert.equal(mapped.length, 4)
  assert.deepEqual(mapped.map((item) => [item.start_frame, item.end_frame_exclusive]), [
    [100, 150],
    [150, 170],
    [170, 200],
    [210, 220],
  ])
})

test('mapped frame conservation is exact', () => {
  const source = [
    segment(1, 1, 'viscoelastic', 'Viscoelastic', 100, 150),
    segment(2, 2, 'flush', 'Flush', 150, 200),
  ]
  const mapped = mapAndMergePhaseSegments(source, profile, 300)

  assert.deepEqual(calculateMappedFrameConservation(source, mapped, 300), {
    sourceFrames: 100,
    mappedFrames: 100,
    passed: true,
  })
})

test('phase export filename comes from the video display name', () => {
  assert.equal(
    buildPhaseExportFilename({
      videoDisplayName: '前后联合 赵平广 男 57岁_cleaned_trimmed.mp4',
      videoId: 62,
      mappingMode: 'original',
    }),
    '前后联合 赵平广 男 57岁_cleaned_trimmed.json',
  )
  assert.equal(
    buildPhaseExportFilename({
      videoDisplayName: '前后联合 赵平广 男 57岁_cleaned_trimmed.mp4',
      videoId: 62,
      mappingMode: 'profile',
      mappingProfileKey: 'cataract-lmm-merged',
    }),
    '前后联合 赵平广 男 57岁_cleaned_trimmed__cataract-lmm-merged.json',
  )
})

test('phase export filename sanitizes unsafe characters and avoids legacy fallback', () => {
  assert.equal(buildPhaseExportFilename({ videoDisplayName: 'case001.MP4', videoId: 1, mappingMode: 'original' }), 'case001.json')
  assert.equal(buildPhaseExportFilename({ videoDisplayName: 'bad/name:?.mp4', videoId: 1, mappingMode: 'original' }), 'bad_name__.json')
  assert.equal(buildPhaseExportFilename({ videoDisplayName: '', videoId: 9, mappingMode: 'original' }), 'research-video-9.json')
  assert.notEqual(buildPhaseExportFilename({ videoDisplayName: '', videoId: 9, mappingMode: 'original' }), 'phase-export-9.json')
})

test('profile key slug keeps export suffix safe', () => {
  assert.equal(slugifyMappingKey('Cataract LMM 合并 类别'), 'cataract-lmm')
})
