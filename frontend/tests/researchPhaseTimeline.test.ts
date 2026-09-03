import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import enUS from '../src/i18n/locales/en-US.ts'
import zhCN from '../src/i18n/locales/zh-CN.ts'
import {
  calculateSegmentGeometry,
  calculatePhaseSegmentEdges,
  calculateTimelineWidth,
  calculateVisibleFrameRange,
  clampFrame,
  findSegmentAtFrame,
  frameToPixel,
  getClippedPhaseSegmentGeometry,
  getFocusedVisibleRange,
  findPhaseGapAtFrame,
  getPhaseSegmentPresentation,
  getPhaseSegmentTooltip,
  getValidPhaseNextStartHint,
  getVisiblePhaseCoverageGaps,
  getTimelinePlayheadPercent,
  hitTestPhaseSegment,
  pixelToFrame,
  resolveNewPhaseStartFrame,
  segmentsAreAdjacent,
  segmentsOverlap,
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

const phaseTimelineSource = readFileSync(new URL('../src/components/research/PhaseTimeline.vue', import.meta.url), 'utf8')

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

test('phase segment geometry keeps true frame-proportional width without minimum expansion', () => {
  const oneFrame = calculateSegmentGeometry({ start_frame: 100, end_frame_exclusive: 101 }, {
    frameCount: 1_000_000,
    framesPerPixel: 100,
  })
  assert.equal(oneFrame.left, 1)
  assert.equal(oneFrame.right, 1.01)
  assert.ok(Math.abs(oneFrame.width - 0.01) < 1e-9)

  const twoFrames = calculateSegmentGeometry({ start_frame: 100, end_frame_exclusive: 102 }, {
    frameCount: 23_582,
    framesPerPixel: 20,
  })
  assert.ok(Math.abs(twoFrames.width - 0.1) < 1e-9)
})

test('clipped visible-window geometry handles full partial and invisible segments', () => {
  assert.deepEqual(getClippedPhaseSegmentGeometry({ start_frame: 100, end_frame_exclusive: 200 }, {
    startFrame: 0,
    endFrameExclusive: 400,
  }), {
    leftPercent: 25,
    rightPercent: 50,
    widthPercent: 25,
    clippedStartFrame: 100,
    clippedEndFrameExclusive: 200,
    visible: true,
  })

  const leftClipped = getClippedPhaseSegmentGeometry({ start_frame: 50, end_frame_exclusive: 150 }, {
    startFrame: 100,
    endFrameExclusive: 300,
  })
  assert.equal(leftClipped.leftPercent, 0)
  assert.equal(leftClipped.rightPercent, 25)
  assert.equal(leftClipped.visible, true)

  const rightClipped = getClippedPhaseSegmentGeometry({ start_frame: 250, end_frame_exclusive: 400 }, {
    startFrame: 100,
    endFrameExclusive: 300,
  })
  assert.equal(rightClipped.leftPercent, 75)
  assert.equal(rightClipped.rightPercent, 100)
  assert.equal(rightClipped.visible, true)

  assert.equal(getClippedPhaseSegmentGeometry({ start_frame: 400, end_frame_exclusive: 500 }, {
    startFrame: 100,
    endFrameExclusive: 300,
  }).visible, false)
})

test('adjacent half-open intervals meet without cumulative rounding gaps', () => {
  const first = getClippedPhaseSegmentGeometry({ start_frame: 0, end_frame_exclusive: 10 }, {
    startFrame: 0,
    endFrameExclusive: 30,
  })
  const second = getClippedPhaseSegmentGeometry({ start_frame: 10, end_frame_exclusive: 30 }, {
    startFrame: 0,
    endFrameExclusive: 30,
  })
  assert.equal(first.rightPercent, second.leftPercent)
  assert.equal(first.widthPercent + second.widthPercent, 100)
})

test('phase segment edge geometry uses shared left and right boundaries', () => {
  const timelineWidth = calculateTimelineWidth({ frameCount: 200, framesPerPixel: 1 })
  const first = calculatePhaseSegmentEdges({ start_frame: 0, end_frame_exclusive: 100 }, {
    frameCount: 200,
    framesPerPixel: 1,
  })
  const second = calculatePhaseSegmentEdges({ start_frame: 100, end_frame_exclusive: 200 }, {
    frameCount: 200,
    framesPerPixel: 1,
  })

  assert.equal(first.leftPx, 0)
  assert.equal(first.rightPx, timelineWidth - 100)
  assert.equal(second.leftPx, 100)
  assert.equal(second.rightPx, timelineWidth - 200)
  assert.equal(first.leftPx + first.trueWidthPx, second.leftPx)
})

test('subpixel phase segment marker does not change true geometry', () => {
  const edges = calculatePhaseSegmentEdges({ start_frame: 100, end_frame_exclusive: 101 }, {
    frameCount: 1_000_000,
    framesPerPixel: 100,
  })

  assert.ok(edges.trueWidthPx < 1)
  assert.equal(edges.needsSubpixelMarker, true)
  assert.equal(edges.leftPx, 1)
  assert.ok(Math.abs((calculateTimelineWidth({ frameCount: 1_000_000, framesPerPixel: 100 }) - edges.rightPx) - 1.01) < 1e-9)
})

test('coverage gaps are only emitted for real unannotated frames', () => {
  assert.deepEqual(getVisiblePhaseCoverageGaps({ startFrame: 0, endFrameExclusive: 300 }, [
    { start_frame: 0, end_frame_exclusive: 100 },
    { start_frame: 100, end_frame_exclusive: 110 },
    { start_frame: 110, end_frame_exclusive: 300 },
  ]), [])

  assert.deepEqual(getVisiblePhaseCoverageGaps({ startFrame: 0, endFrameExclusive: 300 }, [
    { start_frame: 0, end_frame_exclusive: 100 },
    { start_frame: 110, end_frame_exclusive: 200 },
  ]), [
    { startFrame: 100, endFrameExclusive: 110, durationFrames: 10 },
    { startFrame: 200, endFrameExclusive: 300, durationFrames: 100 },
  ])
})

test('half-open overlap accepts adjacent segments and rejects real overlap', () => {
  const a = { start_frame: 0, end_frame_exclusive: 100 }
  const b = { start_frame: 100, end_frame_exclusive: 200 }
  const c = { start_frame: 99, end_frame_exclusive: 200 }
  assert.equal(segmentsAreAdjacent(a, b), true)
  assert.equal(segmentsOverlap(a, b), false)
  assert.equal(segmentsOverlap(a, c), true)
  assert.equal(segmentsOverlap({ start_frame: 40, end_frame_exclusive: 80 }, { start_frame: 40, end_frame_exclusive: 80 }), true)
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

test('findPhaseGapAtFrame returns real unannotated gaps from confirmed half-open segments', () => {
  const segments = [
    { ...sampleSegment, id: 1, start_frame: 1760, end_frame_exclusive: 2588 },
    { ...sampleSegment, id: 2, start_frame: 3400, end_frame_exclusive: 4200 },
  ]

  assert.deepEqual(findPhaseGapAtFrame(segments, 2818, 5_000), {
    gapStartFrame: 2588,
    gapEndFrameExclusive: 3400,
    previousSegmentId: 1,
    nextSegmentId: 2,
    containsTargetFrame: true,
  })
  assert.equal(findPhaseGapAtFrame(segments, 2587, 5_000), null)
  assert.deepEqual(findPhaseGapAtFrame(segments, 120, 5_000), {
    gapStartFrame: 0,
    gapEndFrameExclusive: 1760,
    previousSegmentId: null,
    nextSegmentId: 1,
    containsTargetFrame: true,
  })
  assert.deepEqual(findPhaseGapAtFrame(segments, 4500, 5_000), {
    gapStartFrame: 4200,
    gapEndFrameExclusive: 5000,
    previousSegmentId: 2,
    nextSegmentId: null,
    containsTargetFrame: true,
  })
})

test('findPhaseGapAtFrame does not create fake gaps at adjacent segment boundaries', () => {
  const segments = [
    { ...sampleSegment, id: 1, start_frame: 0, end_frame_exclusive: 100 },
    { ...sampleSegment, id: 2, start_frame: 100, end_frame_exclusive: 200 },
  ]

  assert.equal(findPhaseGapAtFrame(segments, 99, 300), null)
  assert.equal(findPhaseGapAtFrame(segments, 100, 300), null)
  assert.deepEqual(findPhaseGapAtFrame(segments, 250, 300), {
    gapStartFrame: 200,
    gapEndFrameExclusive: 300,
    previousSegmentId: 2,
    nextSegmentId: null,
    containsTargetFrame: true,
  })
})

test('phase segment presentation changes by pixel width', () => {
  assert.equal(getPhaseSegmentPresentation(120), 'full')
  assert.equal(getPhaseSegmentPresentation(80), 'label-only')
  assert.equal(getPhaseSegmentPresentation(40), 'compact')
  assert.equal(getPhaseSegmentPresentation(2), 'marker-only')
})

test('phase segment tooltip uses 1-based inclusive frame display without off-by-one', () => {
  const tooltip = getPhaseSegmentTooltip(sampleSegment, 1_000, 25)
  assert.equal(tooltip.name, 'Prep')
  assert.equal(tooltip.startFrameOneBased, 101)
  assert.equal(tooltip.endFrameInclusiveOneBased, 180)
  assert.equal(tooltip.durationFrames, 80)
  assert.equal(tooltip.startTimeSeconds, 4)
  assert.equal(tooltip.endTimeSeconds, 7.2)
})

test('hit testing selects true containing segment and nearby tiny segment by center distance', () => {
  const segments = [
    { ...sampleSegment, id: 1, start_frame: 100, end_frame_exclusive: 101 },
    { ...sampleSegment, id: 2, start_frame: 110, end_frame_exclusive: 112 },
  ]
  assert.equal(hitTestPhaseSegment(100.02, 1_000, 0, 1_000, segments)?.id, 1)
  assert.equal(hitTestPhaseSegment(111, 1_000, 0, 1_000, segments)?.id, 2)
  assert.equal(hitTestPhaseSegment(500, 1_000, 0, 1_000, segments), null)
})

test('focused selected segment range keeps context and clamps to video boundaries', () => {
  const focused = getFocusedVisibleRange({
    segment: { start_frame: 420, end_frame_exclusive: 489 },
    frameCount: 23_582,
    fps: 25,
    viewportWidth: 1_000,
  })
  assert.ok(focused.endFrameExclusive - focused.startFrame >= 125)
  assert.ok(focused.startFrame <= 420)
  assert.ok(focused.endFrameExclusive >= 489)
  assert.ok(focused.framesPerPixel > 0)

  assert.equal(getFocusedVisibleRange({
    segment: { start_frame: 0, end_frame_exclusive: 2 },
    frameCount: 23_582,
    fps: 25,
    viewportWidth: 1_000,
  }).startFrame, 0)

  assert.equal(getFocusedVisibleRange({
    segment: { start_frame: 23_580, end_frame_exclusive: 23_582 },
    frameCount: 23_582,
    fps: 25,
    viewportWidth: 1_000,
  }).endFrameExclusive, 23_582)
})

test('playhead percent uses the same visible window coordinate system', () => {
  assert.equal(getTimelinePlayheadPercent(150, 100, 300), 25)
  assert.equal(getTimelinePlayheadPercent(10, 100, 300), 0)
  assert.equal(getTimelinePlayheadPercent(500, 100, 300), 100)
})

test('phase timeline source does not use per-frame DOM arrays or geometry-breaking segment CSS', () => {
  const segmentCssBlock = phaseTimelineSource.match(/\.phase-timeline-segment\s*\{[^}]*\}/)?.[0] ?? ''
  const segmentBodyCssBlock = phaseTimelineSource.match(/\.phase-timeline-segment__body\s*\{[^}]*\}/)?.[0] ?? ''
  const markerOnlyCssBlock = phaseTimelineSource.match(/\.phase-timeline-segment\.is-marker-only\s*\{[^}]*\}/)?.[0] ?? ''
  assert.doesNotMatch(phaseTimelineSource, /Array\.from\(\{\s*length:\s*frameCount/)
  assert.doesNotMatch(phaseTimelineSource, /new Array\(frameCount/)
  assert.doesNotMatch(phaseTimelineSource, /v-for="frame in frameCount/)
  assert.doesNotMatch(segmentCssBlock, /flex-grow/)
  assert.doesNotMatch(segmentCssBlock, /flex-basis/)
  assert.doesNotMatch(segmentCssBlock, /min-width:\s*(?:30|40|60)px/)
  assert.match(segmentCssBlock, /margin:\s*0/)
  assert.match(segmentCssBlock, /border-radius:\s*0/)
  assert.match(segmentBodyCssBlock, /--phase-segment-color/)
  assert.doesNotMatch(segmentBodyCssBlock, /background:\s*transparent/)
  assert.doesNotMatch(markerOnlyCssBlock, /background:\s*transparent/)
  assert.doesNotMatch(phaseTimelineSource, /\.phase-timeline-segment\.is-marker-only::before/)
  assert.match(phaseTimelineSource, /phase-timeline-segment__subpixel-marker/)
  assert.match(phaseTimelineSource, /renderedConfirmedSegments/)
  assert.match(phaseTimelineSource, /v-for="entry in renderedConfirmedSegments"/)
  assert.match(phaseTimelineSource, /phase-timeline-coverage-layer/)
  assert.match(phaseTimelineSource, /phase-timeline-coverage-segment/)
  assert.match(phaseTimelineSource, /phase-timeline-gap/)
  assert.match(phaseTimelineSource, /is-marker-only/)
  assert.match(phaseTimelineSource, /@dblclick\.stop\.prevent="!entry\.isPendingDraft && handleSegmentDblClick/)
  assert.match(phaseTimelineSource, /!entry\.isPendingDraft && emit\('selectSegment'/)
  assert.match(phaseTimelineSource, /role="option"/)
  assert.match(phaseTimelineSource, /aria-selected/)
})

test('pending next phase start resolves from the frame after close and keeps repeated labels legal', () => {
  const repeatedLabelSegments = [
    { ...sampleSegment, id: 1, phase_label_id: 10, start_frame: 0, end_frame_exclusive: 1303 },
    { ...sampleSegment, id: 2, phase_label_id: 11, start_frame: 1400, end_frame_exclusive: 1500 },
  ]
  const resolution = resolveNewPhaseStartFrame({
    currentFrame: 1302,
    pendingNextStartFrame: 1303,
    existingSegments: repeatedLabelSegments,
    videoFrameCount: 2_000,
  })
  assert.deepEqual(resolution, {
    startFrame: 1303,
    source: 'pending-next-frame',
    conflict: 'none',
    occupiedSegmentId: null,
    reason: 'ok',
  })
  assert.equal(segmentsOverlap(repeatedLabelSegments[0], { ...sampleSegment, phase_label_id: 10, start_frame: 1303, end_frame_exclusive: null }, 2_000), false)
})

test('pending next phase detects occupied next frame and video end', () => {
  const existing = [
    { ...sampleSegment, id: 1, start_frame: 0, end_frame_exclusive: 100 },
    { ...sampleSegment, id: 2, start_frame: 100, end_frame_exclusive: 200 },
    { ...sampleSegment, id: 3, start_frame: 250, end_frame_exclusive: 300 },
  ]
  assert.deepEqual(resolveNewPhaseStartFrame({
    currentFrame: 99,
    pendingNextStartFrame: 100,
    existingSegments: existing,
    videoFrameCount: 400,
  }), {
    startFrame: null,
    source: 'pending-next-frame',
    conflict: 'occupied-start',
    occupiedSegmentId: 2,
    reason: 'next-frame-already-annotated',
  })
  assert.deepEqual(resolveNewPhaseStartFrame({
    currentFrame: 260,
    pendingNextStartFrame: 260,
    existingSegments: existing,
    videoFrameCount: 400,
  }), {
    startFrame: null,
    source: 'pending-next-frame',
    conflict: 'occupied-inside',
    occupiedSegmentId: 3,
    reason: 'next-frame-occupied',
  })
  assert.equal(resolveNewPhaseStartFrame({
    currentFrame: 399,
    pendingNextStartFrame: 400,
    existingSegments: existing,
    videoFrameCount: 400,
  }).reason, 'no-next-frame')
})

test('next phase start hint is valid only for the server-confirmed following frame', () => {
  const hint = {
    annotationSetId: 7,
    startFrame: 12192,
    sourceSegmentId: 3,
    sourceEndFrameExclusive: 12192,
    annotationSetRevision: 28,
    closedAtPlayheadFrame: 12191,
  }
  const context = {
    annotationSetId: 7,
    annotationSetRevision: 28,
    currentFrame: 12191,
    videoFrameCount: 14961,
    existingSegments: [
      { ...sampleSegment, id: 3, end_frame_exclusive: 12192 },
      { ...sampleSegment, id: 4, end_frame_exclusive: 13000 },
    ],
  }

  assert.deepEqual(getValidPhaseNextStartHint(hint, context), hint)
  assert.equal(getValidPhaseNextStartHint({ ...hint, startFrame: 12191 }, context), null)
  assert.equal(getValidPhaseNextStartHint(hint, { ...context, currentFrame: 12192 }), null)
  assert.equal(getValidPhaseNextStartHint(hint, { ...context, annotationSetRevision: 29 }), null)
  assert.equal(getValidPhaseNextStartHint(hint, {
    ...context,
    existingSegments: [{ ...sampleSegment, id: 3, end_frame_exclusive: 12191 }],
  }), null)
  assert.equal(getValidPhaseNextStartHint({ ...hint, startFrame: 14961, sourceEndFrameExclusive: 14961 }, {
    ...context,
    existingSegments: [{ ...sampleSegment, id: 3, end_frame_exclusive: 14961 }],
  }), null)
})

test('phase timeline i18n keys match between Chinese and English', () => {
  assert.deepEqual(Object.keys(zhCN.phaseTimeline).sort(), Object.keys(enUS.phaseTimeline).sort())
  assert.equal(zhCN.phaseTimeline.focusSelected, '放大到选中区间')
  assert.equal(enUS.phaseTimeline.focusSelected, 'Focus selected segment')
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
