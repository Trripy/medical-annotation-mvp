import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import enUS from '../src/i18n/locales/en-US.ts'
import zhCN from '../src/i18n/locales/zh-CN.ts'
import {
  backendRangeToUi,
  buildTrimPayload,
  clampTrimRange,
  defaultTrimmedName,
  formatTrimTimestamp,
  getTimelineGeometry,
  HIDE_SOURCE_AFTER_TRIM_STORAGE_KEY,
  frameToSeconds,
  isFullRange,
  isRangeTooShort,
  parseTrimTimestamp,
  readHideSourceAfterTrimPreference,
  sanitizeTrimOutputName,
  secondsToFrame,
  trimOutputFrameCount,
  uiRangeToBackend,
  writeHideSourceAfterTrimPreference,
} from '../src/utils/videoTrim.ts'

const trimPageSource = readFileSync(new URL('../src/views/ResearchVideoTrimPage.vue', import.meta.url), 'utf8')
const timelineSource = readFileSync(new URL('../src/components/research/VideoTrimTimeline.vue', import.meta.url), 'utf8')
const routerSource = readFileSync(new URL('../src/router.ts', import.meta.url), 'utf8')
const videosPageSource = readFileSync(new URL('../src/views/ResearchVideosPage.vue', import.meta.url), 'utf8')
const videoStoreSource = readFileSync(new URL('../src/stores/researchVideos.ts', import.meta.url), 'utf8')

test('trim range converts between backend half-open and UI inclusive frames', () => {
  assert.deepEqual(backendRangeToUi({ startFrame: 100, endFrameExclusive: 1000 }), {
    startFrameInclusiveOneBased: 101,
    endFrameInclusiveOneBased: 1000,
  })
  assert.deepEqual(uiRangeToBackend({ startFrameInclusiveOneBased: 101, endFrameInclusiveOneBased: 1000 }), {
    startFrame: 100,
    endFrameExclusive: 1000,
  })
})

test('trim handles clamp to frame count and minimum range', () => {
  assert.deepEqual(clampTrimRange({ startFrame: -10, endFrameExclusive: 5 }, 100, 10), {
    startFrame: 0,
    endFrameExclusive: 10,
  })
  assert.deepEqual(clampTrimRange({ startFrame: 95, endFrameExclusive: 200 }, 100, 10), {
    startFrame: 90,
    endFrameExclusive: 100,
  })
})

test('full range too-short and frame count helpers are stable', () => {
  assert.equal(isFullRange({ startFrame: 0, endFrameExclusive: 125 }, 125), true)
  assert.equal(isRangeTooShort({ startFrame: 10, endFrameExclusive: 20 }, 25), true)
  assert.equal(trimOutputFrameCount({ startFrame: 10, endFrameExclusive: 100 }), 90)
})

test('duration and removed range calculations use fps only', () => {
  assert.equal(frameToSeconds(25, 25), 1)
  assert.equal(secondsToFrame(2.4, 25, 125), 60)
  assert.equal(formatTrimTimestamp(3661.25), '01:01:01.250')
  assert.equal(parseTrimTimestamp('00:00:02.400'), 2.4)
})

test('default output names are mp4 and path characters are sanitized', () => {
  assert.equal(defaultTrimmedName('case001.mov'), 'case001_trimmed.mp4')
  assert.equal(sanitizeTrimOutputName('../bad/name.mov', 'case001.mov'), 'name.mp4')
  assert.equal(sanitizeTrimOutputName('bad:name', 'case001.mov'), 'bad_name.mp4')
})

test('submit payload sends backend range output name acknowledgement and hide-source option', () => {
  const payload = buildTrimPayload({ startFrame: 2, endFrameExclusive: 50 }, 'case_trimmed.mp4', true)
  assert.deepEqual(payload, {
    start_frame: 2,
    end_frame_exclusive: 50,
    display_name: 'case_trimmed.mp4',
    acknowledge_annotations_not_copied: true,
    hide_source_after_success: false,
  })
  assert.equal('fps' in payload, false)
  assert.equal('frame_count' in payload, false)

  assert.equal(
    buildTrimPayload({ startFrame: 2, endFrameExclusive: 50 }, 'case_trimmed.mp4', true, true)
      .hide_source_after_success,
    true,
  )
})

test('trim hide-source preference stores only a boolean in a fixed localStorage key', () => {
  const values = new Map<string, string>()
  const storage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value)
    },
  }

  assert.equal(HIDE_SOURCE_AFTER_TRIM_STORAGE_KEY, 'researchVideoTrim.hideSourceAfterSuccess')
  assert.equal(readHideSourceAfterTrimPreference(storage), false)
  writeHideSourceAfterTrimPreference(true, storage)
  assert.equal(values.get(HIDE_SOURCE_AFTER_TRIM_STORAGE_KEY), 'true')
  assert.equal(readHideSourceAfterTrimPreference(storage), true)
  writeHideSourceAfterTrimPreference(false, storage)
  assert.equal(values.get(HIDE_SOURCE_AFTER_TRIM_STORAGE_KEY), 'false')
  assert.deepEqual([...values.entries()], [[HIDE_SOURCE_AFTER_TRIM_STORAGE_KEY, 'false']])
})

test('trim page exposes hide-source controls and sends backend field with actual-response toasts', () => {
  assert.match(trimPageSource, /hideSourceAfterSuccess/)
  assert.match(trimPageSource, /rememberHideSourceChoice/)
  assert.match(trimPageSource, /researchVideoTrim\.hideSourceAfterSuccess/)
  assert.match(videoStoreSource, /hide_source_after_success/)
  assert.match(trimPageSource, /response\.source_video_hidden/)
  assert.match(trimPageSource, /trimSucceededSourceHidden/)
  assert.match(trimPageSource, /trimSucceededSourceVisible/)
  assert.doesNotMatch(trimPageSource, /\/visibility/)
})

test('trim route list action and timeline do not create per-frame DOM', () => {
  assert.match(routerSource, /\/research\/videos\/:videoId\/trim/)
  assert.match(videosPageSource, /openTrimVideo/)
  assert.match(trimPageSource, /fetchVideoTrimInfo/)
  assert.match(trimPageSource, /acknowledged/)
  assert.doesNotMatch(timelineSource, /v-for=.*frame/i)
  assert.doesNotMatch(timelineSource, /Array\.from|new Array|\.fill\(/)
})

test('preview keeps playback rate code path and auto stops at end', () => {
  assert.match(trimPageSource, /useVideoPlaybackRate/)
  assert.match(trimPageSource, /previewing\.value && currentFrame\.value >= trimRange\.value\.endFrameExclusive/)
  assert.match(trimPageSource, /video\.pause\(\)/)
})

test('timeline geometry remains fixed-size for large frame counts', () => {
  const small = getTimelineGeometry({
    frameCount: 100,
    startFrame: 10,
    endFrameExclusive: 80,
    currentFrame: 50,
  })
  assert.deepEqual(Object.keys(small).sort(), ['endPercent', 'playheadPercent', 'selectionWidthPercent', 'startPercent'])
  assert.equal(small.startPercent, 10)
  assert.equal(small.endPercent, 80)
  assert.equal(small.selectionWidthPercent, 70)
  assert.equal(small.playheadPercent, 50)

  const medium = getTimelineGeometry({
    frameCount: 100_000,
    startFrame: 25_000,
    endFrameExclusive: 75_000,
    currentFrame: 50_000,
  })
  assert.equal(medium.selectionWidthPercent, 50)

  const started = performance.now()
  const large = getTimelineGeometry({
    frameCount: 10_000_000,
    startFrame: 1_000_000,
    endFrameExclusive: 9_000_000,
    currentFrame: 4_000_000,
  })
  const elapsed = performance.now() - started
  assert.equal(large.startPercent, 10)
  assert.equal(large.endPercent, 90)
  assert.equal(large.selectionWidthPercent, 80)
  assert.equal(large.playheadPercent, 40)
  assert.ok(elapsed < 20)
})

test('trim page avoids recursive range watcher and per-keystroke time setters', () => {
  assert.doesNotMatch(trimPageSource, /watch\(trimRange/)
  assert.match(trimPageSource, /function setTrimRange/)
  assert.match(trimPageSource, /next\.startFrame !== trimRange\.value\.startFrame/)
  assert.doesNotMatch(trimPageSource, /const startTimeText = computed\(\{[\s\S]*set:/)
  assert.doesNotMatch(trimPageSource, /const endTimeText = computed\(\{[\s\S]*set:/)
  assert.match(trimPageSource, /@change="commitStartTime"/)
  assert.match(trimPageSource, /@change="commitEndTime"/)
})

test('current time updates display state without creating a seek loop', () => {
  const handleTimeUpdateBody = trimPageSource.match(/function handleTimeUpdate\(\) \{([\s\S]*?)\n\}/)?.[1] ?? ''
  assert.match(handleTimeUpdateBody, /currentFrame\.value =/)
  assert.doesNotMatch(handleTimeUpdateBody, /video\.currentTime =/)
  assert.doesNotMatch(trimPageSource, /watch\(currentFrame/)
})

test('trim page requests only trim-info and does not load frames or workspace APIs', () => {
  assert.match(trimPageSource, /fetchVideoTrimInfo/)
  assert.doesNotMatch(trimPageSource, /fetchVideoFramesPage|\/frames\?|\/workspace|fetchVideoWorkspace/)
  assert.doesNotMatch(trimPageSource, /fetchVideoDetail/)
})

test('video trim i18n keys match between Chinese and English', () => {
  assert.deepEqual(Object.keys(zhCN.videoTrim).sort(), Object.keys(enUS.videoTrim).sort())
  assert.deepEqual(Object.keys(zhCN.video).sort(), Object.keys(enUS.video).sort())
  assert.equal(zhCN.videoTrim.title, '剪切视频')
  assert.equal(enUS.videoTrim.action, 'Trim')
})
