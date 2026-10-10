import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

import { createPinia, setActivePinia } from 'pinia'

import enUS from '../src/i18n/locales/en-US.ts'
import zhCN from '../src/i18n/locales/zh-CN.ts'
import { RESEARCH_VIDEO_NAME_PRIVACY_STORAGE_KEY, usePrivacyStore } from '../src/stores/privacy.ts'
import {
  getRelatedResearchVideoDisplayName,
  getResearchVideoAlias,
  getResearchVideoDisplayName,
  getResearchVideoFrameDisplayName,
} from '../src/utils/videoPrivacy.ts'

const sensitiveVideo = {
  id: 49,
  name: '20260313_张三_人民医院_OD_cleaned.mp4',
  original_filename: '20260313_张三_人民医院_OD_cleaned.mp4',
}

function makeStorage(initial: Record<string, string> = {}) {
  const values = { ...initial }
  return {
    getItem(key: string) {
      return values[key] ?? null
    },
    setItem(key: string, value: string) {
      values[key] = value
    },
    values,
  }
}

test('research video privacy aliases use stable video ids and never preserve original name fragments', () => {
  assert.equal(getResearchVideoAlias(49, 'en-US'), 'Video #49')
  assert.equal(getResearchVideoAlias(49, 'zh-CN'), '视频 #49')
  assert.equal(getResearchVideoDisplayName(sensitiveVideo, true, 'en-US'), 'Video #49')
  assert.equal(getResearchVideoDisplayName({ ...sensitiveVideo, id: 58 }, true, 'en-US'), 'Video #58')
  assert.equal(getResearchVideoDisplayName(sensitiveVideo, false, 'en-US'), sensitiveVideo.name)
  assert.equal(getRelatedResearchVideoDisplayName(49, sensitiveVideo.name, true, 'zh-CN'), '视频 #49')
  assert.equal(getResearchVideoFrameDisplayName({ frame_index: 13, filename: sensitiveVideo.name }, true, 'en-US'), 'Frame #14')

  const hiddenText = [
    getResearchVideoDisplayName(sensitiveVideo, true, 'en-US'),
    getRelatedResearchVideoDisplayName(49, sensitiveVideo.name, true, 'zh-CN'),
    getResearchVideoFrameDisplayName({ frame_index: 13, filename: sensitiveVideo.name }, true, 'en-US'),
  ].join('\n')
  assert.doesNotMatch(hiddenText, /张三|人民医院|20260313_张三_人民医院_OD_cleaned\.mp4/)
})

test('privacy store defaults false and persists only a boolean value', () => {
  const storage = makeStorage()
  const originalWindow = globalThis.window
  Object.defineProperty(globalThis, 'window', {
    value: { localStorage: storage },
    configurable: true,
  })
  try {
    setActivePinia(createPinia())
    const store = usePrivacyStore()
    assert.equal(store.hideResearchVideoNames, false)
    store.setHideResearchVideoNames(true)
    assert.equal(storage.values[RESEARCH_VIDEO_NAME_PRIVACY_STORAGE_KEY], 'true')
    assert.deepEqual(Object.keys(storage.values), [RESEARCH_VIDEO_NAME_PRIVACY_STORAGE_KEY])
  } finally {
    Object.defineProperty(globalThis, 'window', {
      value: originalWindow,
      configurable: true,
    })
  }
})

test('privacy store restores true from localStorage', () => {
  const storage = makeStorage({ [RESEARCH_VIDEO_NAME_PRIVACY_STORAGE_KEY]: 'true' })
  const originalWindow = globalThis.window
  Object.defineProperty(globalThis, 'window', {
    value: { localStorage: storage },
    configurable: true,
  })
  try {
    setActivePinia(createPinia())
    const store = usePrivacyStore()
    assert.equal(store.hideResearchVideoNames, true)
  } finally {
    Object.defineProperty(globalThis, 'window', {
      value: originalWindow,
      configurable: true,
    })
  }
})

test('research video pages use shared privacy helpers and do not mask backend payloads', () => {
  const videosPage = readFileSync(new URL('../src/views/ResearchVideosPage.vue', import.meta.url), 'utf8')
  const trimPage = readFileSync(new URL('../src/views/ResearchVideoTrimPage.vue', import.meta.url), 'utf8')
  const phasePage = readFileSync(new URL('../src/views/ResearchVideoPhasePage.vue', import.meta.url), 'utf8')
  const framePage = readFileSync(new URL('../src/views/ResearchVideoAnnotatePage.vue', import.meta.url), 'utf8')
  const skillPage = readFileSync(new URL('../src/views/ResearchVideoSkillPage.vue', import.meta.url), 'utf8')
  const checklistPage = readFileSync(new URL('../src/views/ResearchVideoChecklistPage.vue', import.meta.url), 'utf8')
  const frameList = readFileSync(new URL('../src/components/VirtualFrameList.vue', import.meta.url), 'utf8')

  for (const source of [videosPage, trimPage, phasePage, framePage, skillPage, checklistPage]) {
    assert.match(source, /VideoNamePrivacyToggle|getResearchVideoDisplayName|videoDisplayName|checklistVideoName/)
  }
  assert.match(frameList, /getResearchVideoFrameDisplayName/)
  assert.match(trimPage, /buildTrimPayload\(trimRange\.value, sanitizedName/)
  assert.match(trimPage, /:type="hideResearchVideoNames \? 'password' : 'text'"/)
  assert.match(checklistPage, /buildBatchExportPayload/)
  assert.doesNotMatch(trimPage, /Video #\$\{.*display_name|display_name:\s*videoDisplayName/)
})

test('privacy i18n key sets match', () => {
  assert.deepEqual(Object.keys(zhCN.privacy.videoNames).sort(), Object.keys(enUS.privacy.videoNames).sort())
  assert.equal(zhCN.privacy.videoNames.hide, '隐藏视频名')
  assert.equal(enUS.privacy.videoNames.hide, 'Hide video names')
})

