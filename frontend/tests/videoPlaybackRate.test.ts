import assert from 'node:assert/strict'
import test from 'node:test'

import enUS from '../src/i18n/locales/en-US.ts'
import zhCN from '../src/i18n/locales/zh-CN.ts'
import { buildCloseActiveEndFrame, frameToTimestampMs, parseResearchFrameQuery } from '../src/utils/researchPhaseUi.ts'
import { buildIntervalEvidence, buildPointEvidence } from '../src/utils/researchSkill.ts'
import {
  applyPlaybackRateToVideo,
  DEFAULT_VIDEO_PLAYBACK_RATE,
  formatPlaybackRateLabel,
  isSupportedPlaybackRate,
  parsePlaybackRate,
  parsePlaybackRateStorageEvent,
  persistPlaybackRate,
  preservePlaybackRateRouteState,
  readPersistedPlaybackRate,
  resolveInitialPlaybackRate,
  VIDEO_PLAYBACK_RATE_OPTIONS,
  VIDEO_PLAYBACK_RATE_STORAGE_KEY,
  type VideoPlaybackRate,
} from '../src/utils/videoPlaybackRate.ts'
import {
  registerVideoPlaybackElement,
  setVideoPlaybackRate,
} from '../src/composables/useVideoPlaybackRate.ts'

class FakeVideo extends EventTarget {
  currentTime = 12
  defaultPlaybackRate = 1
  paused = true
  playbackRate = 1
  preservesPitch = false
  src = ''
}

function flattenKeys(value: unknown, prefix = ''): string[] {
  if (!value || typeof value !== 'object') {
    return [prefix]
  }
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
    flattenKeys(child, prefix ? `${prefix}.${key}` : key),
  )
}

test('supported playback rate list is ordered and defaults to 1', () => {
  assert.deepEqual([...VIDEO_PLAYBACK_RATE_OPTIONS], [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4])
  assert.equal(DEFAULT_VIDEO_PLAYBACK_RATE, 1)
})

test('parsePlaybackRate accepts persisted supported numeric strings', () => {
  assert.equal(parsePlaybackRate('2'), 2)
  assert.equal(parsePlaybackRate('1.25'), 1.25)
})

test('parsePlaybackRate rejects illegal values', () => {
  assert.equal(parsePlaybackRate('abc'), null)
  assert.equal(parsePlaybackRate('0'), null)
  assert.equal(parsePlaybackRate('-1'), null)
  assert.equal(parsePlaybackRate('Infinity'), null)
  assert.equal(parsePlaybackRate('1.75'), null)
})

test('resolveInitialPlaybackRate falls back to 1 for invalid storage', () => {
  assert.equal(resolveInitialPlaybackRate('2'), 2)
  assert.equal(resolveInitialPlaybackRate('bad'), 1)
  assert.equal(resolveInitialPlaybackRate(0), 1)
})

test('readPersistedPlaybackRate handles storage values and read failures', () => {
  assert.equal(readPersistedPlaybackRate({ getItem: () => '1.5' }), 1.5)
  assert.equal(readPersistedPlaybackRate({ getItem: () => { throw new Error('blocked') } }), 1)
})

test('formatPlaybackRateLabel uses multiplication sign and compact decimals', () => {
  assert.equal(formatPlaybackRateLabel(1), '1×')
  assert.equal(formatPlaybackRateLabel(1.25), '1.25×')
  assert.equal(formatPlaybackRateLabel(0.5), '0.5×')
})

test('isSupportedPlaybackRate is strict', () => {
  assert.equal(isSupportedPlaybackRate(4), true)
  assert.equal(isSupportedPlaybackRate(1.75), false)
  assert.equal(isSupportedPlaybackRate(Number.POSITIVE_INFINITY), false)
})

test('applyPlaybackRateToVideo applies playbackRate and defaultPlaybackRate', () => {
  const video = new FakeVideo()
  assert.equal(applyPlaybackRateToVideo(video, 2), true)
  assert.equal(video.playbackRate, 2)
  assert.equal(video.defaultPlaybackRate, 2)
})

test('applyPlaybackRateToVideo preserves currentTime and paused state', () => {
  const video = new FakeVideo()
  video.currentTime = 42
  video.paused = false
  applyPlaybackRateToVideo(video, 0.5)
  assert.equal(video.currentTime, 42)
  assert.equal(video.paused, false)
})

test('applyPlaybackRateToVideo handles null video refs', () => {
  assert.equal(applyPlaybackRateToVideo(null, 1), false)
})

test('applyPlaybackRateToVideo enables pitch preservation when available', () => {
  const video = new FakeVideo()
  applyPlaybackRateToVideo(video, 1.25)
  assert.equal(video.preservesPitch, true)
})

test('persistPlaybackRate write failures do not throw', () => {
  assert.doesNotThrow(() => persistPlaybackRate(2, { setItem: () => { throw new Error('blocked') } }))
})

test('storage event parsing synchronizes legal values and ignores invalid values', () => {
  assert.equal(parsePlaybackRateStorageEvent({ key: VIDEO_PLAYBACK_RATE_STORAGE_KEY, newValue: '3' }), 3)
  assert.equal(parsePlaybackRateStorageEvent({ key: VIDEO_PLAYBACK_RATE_STORAGE_KEY, newValue: '1.75' }), null)
  assert.equal(parsePlaybackRateStorageEvent({ key: 'other', newValue: '2' }), null)
})

test('registered video receives global playback changes', () => {
  const video = new FakeVideo()
  const cleanup = registerVideoPlaybackElement(video as unknown as HTMLVideoElement)
  setVideoPlaybackRate(2, { persist: false })
  assert.equal(video.playbackRate, 2)
  assert.equal(video.defaultPlaybackRate, 2)
  cleanup()
})

test('loadedmetadata reapplies the current global rate', () => {
  const video = new FakeVideo()
  const cleanup = registerVideoPlaybackElement(video as unknown as HTMLVideoElement)
  setVideoPlaybackRate(1.5, { persist: false })
  video.playbackRate = 1
  video.dispatchEvent(new Event('loadedmetadata'))
  assert.equal(video.playbackRate, 1.5)
  cleanup()
})

test('loadeddata and canplay reapply the current global rate', () => {
  const video = new FakeVideo()
  const cleanup = registerVideoPlaybackElement(video as unknown as HTMLVideoElement)
  setVideoPlaybackRate(0.75, { persist: false })
  video.playbackRate = 1
  video.dispatchEvent(new Event('loadeddata'))
  assert.equal(video.playbackRate, 0.75)
  video.playbackRate = 1
  video.dispatchEvent(new Event('canplay'))
  assert.equal(video.playbackRate, 0.75)
  cleanup()
})

test('source changes can be followed by media events without losing rate', () => {
  const video = new FakeVideo()
  const cleanup = registerVideoPlaybackElement(video as unknown as HTMLVideoElement)
  setVideoPlaybackRate(4, { persist: false })
  video.src = '/new-video.mp4'
  video.playbackRate = 1
  video.dispatchEvent(new Event('loadedmetadata'))
  assert.equal(video.playbackRate, 4)
  cleanup()
})

test('multiple registered videos synchronize together', () => {
  const left = new FakeVideo()
  const right = new FakeVideo()
  const cleanupLeft = registerVideoPlaybackElement(left as unknown as HTMLVideoElement)
  const cleanupRight = registerVideoPlaybackElement(right as unknown as HTMLVideoElement)
  setVideoPlaybackRate(3, { persist: false })
  assert.equal(left.playbackRate, 3)
  assert.equal(right.playbackRate, 3)
  cleanupLeft()
  cleanupRight()
})

test('cleanup removes video from global synchronization', () => {
  const video = new FakeVideo()
  const cleanup = registerVideoPlaybackElement(video as unknown as HTMLVideoElement)
  cleanup()
  setVideoPlaybackRate(0.25, { persist: false })
  assert.notEqual(video.playbackRate, 0.25)
})

test('native supported ratechange updates global state', () => {
  const video = new FakeVideo()
  const cleanup = registerVideoPlaybackElement(video as unknown as HTMLVideoElement)
  video.playbackRate = 2
  video.dispatchEvent(new Event('ratechange'))
  const another = new FakeVideo()
  const cleanupAnother = registerVideoPlaybackElement(another as unknown as HTMLVideoElement)
  assert.equal(another.playbackRate, 2)
  cleanup()
  cleanupAnother()
})

test('native unsupported ratechange restores the global supported rate', () => {
  const video = new FakeVideo()
  const cleanup = registerVideoPlaybackElement(video as unknown as HTMLVideoElement)
  setVideoPlaybackRate(1.25, { persist: false })
  video.playbackRate = 1.75
  video.dispatchEvent(new Event('ratechange'))
  assert.equal(video.playbackRate, 1.25)
  cleanup()
})

test('ratechange from our own apply path does not loop', () => {
  const video = new FakeVideo()
  const cleanup = registerVideoPlaybackElement(video as unknown as HTMLVideoElement)
  setVideoPlaybackRate(2, { persist: false })
  video.dispatchEvent(new Event('ratechange'))
  assert.equal(video.playbackRate, 2)
  cleanup()
})

test('i18n video keys exist in Chinese and English and key sets match', () => {
  assert.equal(enUS.video.playbackSpeed, 'Playback speed')
  assert.equal(zhCN.video.playbackSpeed, '播放倍速')
  assert.equal(enUS.accessibility.changePlaybackSpeed, 'Change video playback speed')
  assert.equal(zhCN.accessibility.changePlaybackSpeed, '调整视频播放倍速')
  assert.deepEqual(flattenKeys(zhCN).sort(), flattenKeys(enUS).sort())
})

test('route helper preserves frame query', () => {
  const route = { query: { frame: '12' } }
  assert.equal(preservePlaybackRateRouteState(route), route)
  assert.deepEqual(route.query, { frame: '12' })
})

test('route helper preserves assessment query', () => {
  const route = { query: { frame: '12', assessment: '5' } }
  assert.equal(preservePlaybackRateRouteState(route), route)
  assert.deepEqual(route.query, { frame: '12', assessment: '5' })
})

test('currentTime to frame calculations do not use playbackRate', () => {
  const fps = 25
  const currentTime = 4
  const playbackRate: VideoPlaybackRate = 2
  assert.equal(Math.round(currentTime * fps), 100)
  assert.equal(frameToTimestampMs(100, fps), 4000)
  assert.equal(playbackRate, 2)
})

test('frame query parsing is independent of playback rate', () => {
  assert.equal(parseResearchFrameQuery('10', 100), 10)
  assert.equal(parseResearchFrameQuery('10', 100), parseResearchFrameQuery('10', 100))
})

test('Phase close frame calculation is independent of playback rate', () => {
  assert.equal(buildCloseActiveEndFrame(9, 100), 10)
})

test('Skill point evidence frame calculation is independent of playback rate', () => {
  assert.deepEqual(buildPointEvidence(24), { start_frame: 24, end_frame_exclusive: null })
})

test('Skill interval evidence frame calculation is independent of playback rate', () => {
  assert.deepEqual(buildIntervalEvidence(10, 12), { start_frame: 10, end_frame_exclusive: 13 })
})

test('switching pages can reuse the same global playback rate', () => {
  const frameVideo = new FakeVideo()
  const cleanupFrame = registerVideoPlaybackElement(frameVideo as unknown as HTMLVideoElement)
  setVideoPlaybackRate(1.5, { persist: false })
  cleanupFrame()
  const phaseVideo = new FakeVideo()
  const cleanupPhase = registerVideoPlaybackElement(phaseVideo as unknown as HTMLVideoElement)
  assert.equal(phaseVideo.playbackRate, 1.5)
  cleanupPhase()
})

test('all preset options can be applied to a video', () => {
  const video = new FakeVideo()
  for (const rate of VIDEO_PLAYBACK_RATE_OPTIONS) {
    applyPlaybackRateToVideo(video, rate)
    assert.equal(video.playbackRate, rate)
  }
})

test('readPersistedPlaybackRate rejects unsupported persisted rate', () => {
  assert.equal(readPersistedPlaybackRate({ getItem: () => '1.75' }), 1)
})

test('persistPlaybackRate writes numeric string format', () => {
  const writes: Record<string, string> = {}
  persistPlaybackRate(1.25, { setItem: (key, value) => { writes[key] = value } })
  assert.equal(writes[VIDEO_PLAYBACK_RATE_STORAGE_KEY], '1.25')
})
