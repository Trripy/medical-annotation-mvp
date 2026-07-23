import assert from 'node:assert/strict'
import test from 'node:test'

import {
  calculateSegmentGeometry,
  calculateTimelineWidth,
  calculateVisibleFrameRange,
  clampFrame,
  findSegmentAtFrame,
  frameToPixel,
  pixelToFrame,
} from '../src/utils/researchPhaseTimeline.ts'
import {
  buildCloseActiveEndFrame,
  fromUiInclusiveEndFrame,
  fromUiStartFrame,
  toUiFrameNumber,
  toUiInclusiveEndFrame,
} from '../src/utils/researchPhaseUi.ts'

const sampleSegment = {
  id: 10,
  annotation_set_id: 1,
  phase_label_id: 2,
  start_frame: 100,
  end_frame_exclusive: 180,
  source: 'manual' as const,
  confidence: null,
  notes: null,
  created_at: '2026-07-22T00:00:00Z',
  updated_at: '2026-07-22T00:00:00Z',
  phase_label: {
    id: 2,
    key: 'prep',
    name: 'Prep',
    color: '#22c55e',
  },
}

test('frameToPixel and pixelToFrame map frames with bounded round-trip error', () => {
  const input = { frameCount: 12_000, framesPerPixel: 5 }
  const pixel = frameToPixel(1_234, input)
  const frame = pixelToFrame(pixel, input)

  assert.equal(pixel, 246.8)
  assert.ok(Math.abs(frame - 1_234) <= 1)
})

test('clampFrame keeps values inside [0, frameCount] and handles empty videos', () => {
  assert.equal(clampFrame(-10, 400), 0)
  assert.equal(clampFrame(999, 400), 400)
  assert.equal(clampFrame(12, 0), 0)
})

test('calculateSegmentGeometry returns consistent closed interval geometry', () => {
  const geometry = calculateSegmentGeometry(sampleSegment, {
    frameCount: 1_000,
    framesPerPixel: 4,
  })

  assert.equal(geometry.left, 25)
  assert.equal(geometry.right, 45)
  assert.equal(geometry.width, 20)
})

test('open segments extend to video end in timeline geometry', () => {
  const geometry = calculateSegmentGeometry(
    {
      ...sampleSegment,
      end_frame_exclusive: null,
    },
    {
      frameCount: 1_000,
      framesPerPixel: 10,
    },
  )

  assert.equal(geometry.left, 10)
  assert.equal(geometry.right, 100)
  assert.equal(geometry.width, 90)
})

test('calculateTimelineWidth respects zoom level and minimum width', () => {
  assert.equal(calculateTimelineWidth({ frameCount: 0, framesPerPixel: 6 }), 320)
  assert.equal(calculateTimelineWidth({ frameCount: 5_000, framesPerPixel: 5 }), 1_000)
  assert.equal(calculateTimelineWidth({ frameCount: 5_000, framesPerPixel: 20 }), 320)
})

test('findSegmentAtFrame chooses the first covering segment and respects left-closed right-open boundaries', () => {
  const segments = [
    sampleSegment,
    {
      ...sampleSegment,
      id: 11,
      start_frame: 180,
      end_frame_exclusive: 240,
    },
  ]

  assert.equal(findSegmentAtFrame(segments, 100)?.id, 10)
  assert.equal(findSegmentAtFrame(segments, 179)?.id, 10)
  assert.equal(findSegmentAtFrame(segments, 180)?.id, 11)
  assert.equal(findSegmentAtFrame(segments, 240), null)
})

test('calculateVisibleFrameRange handles frameCount=0 and long videos without NaN', () => {
  const emptyRange = calculateVisibleFrameRange(200, 500, { frameCount: 0, framesPerPixel: 4 })
  assert.deepEqual(emptyRange, { startFrame: 0, endFrameExclusive: 0 })

  const longRange = calculateVisibleFrameRange(12_345, 1_440, { frameCount: 50_000, framesPerPixel: 2.5 })
  assert.ok(Number.isFinite(longRange.startFrame))
  assert.ok(Number.isFinite(longRange.endFrameExclusive))
  assert.ok(longRange.endFrameExclusive >= longRange.startFrame)
})

test('UI start frame conversions keep first and last frames human-readable', () => {
  assert.equal(toUiFrameNumber(0), '1')
  assert.equal(toUiFrameNumber(99), '100')
  assert.equal(fromUiStartFrame('1', 100), 0)
  assert.equal(fromUiStartFrame('100', 100), 99)
})

test('UI inclusive end conversions preserve end-exclusive backend semantics', () => {
  assert.equal(toUiInclusiveEndFrame(100), '100')
  assert.equal(fromUiInclusiveEndFrame('100', 500), 100)
  assert.equal(fromUiInclusiveEndFrame('500', 500), 500)
})

test('close current frame uses current + 1 and clamps to video end', () => {
  assert.equal(buildCloseActiveEndFrame(0, 100), 1)
  assert.equal(buildCloseActiveEndFrame(98, 100), 99)
  assert.equal(buildCloseActiveEndFrame(99, 100), 100)
})
