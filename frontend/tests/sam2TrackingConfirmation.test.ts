import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

const pagePath = new URL('../src/views/AnnotatePage.vue', import.meta.url)
const stylesPath = new URL('../src/styles.css', import.meta.url)
const enPath = new URL('../src/i18n/locales/en-US.ts', import.meta.url)
const zhPath = new URL('../src/i18n/locales/zh-CN.ts', import.meta.url)

test('SAM2 tracking start uses a body-teleported confirmation before starting work', async () => {
  const source = await readFile(pagePath, 'utf8')
  const start = source.indexOf('async function startTrackWithSam2')
  const end = source.indexOf('function isTrackingReviewFrame', start)
  const startBody = source.slice(start, end)

  assert.match(startBody, /trackingStartConfirmation\.value = \{[\s\S]*kind: 'discard_preview'/)
  assert.match(startBody, /trackingStartConfirmation\.value = \{[\s\S]*kind: 'direct_create'/)
  assert.match(startBody, /trackingWithSam2\.value = true/)
  assert.match(startBody, /annotationStore\.trackVideoWithSam2/)
  assert.doesNotMatch(startBody, /window\.confirm/)
  assert.match(source, /<Teleport to="body">[\s\S]*trackingStartConfirmationVisible/)
  assert.match(source, /@click="confirmTrackingStart"/)
})

test('SAM2 tracking confirmation only starts tracking after explicit confirm and cleans up on cancel paths', async () => {
  const source = await readFile(pagePath, 'utf8')
  const confirmStart = source.indexOf('function confirmTrackingStart')
  const confirmEnd = source.indexOf('function isTrackingReviewFrame', confirmStart)
  const confirmBody = source.slice(confirmStart, confirmEnd)

  assert.match(confirmBody, /closeTrackingStartConfirmation\(\)/)
  assert.match(confirmBody, /void startTrackWithSam2\(/)
  assert.doesNotMatch(confirmBody, /trackVideoWithSam2/)
  assert.match(source, /function closeTrackWithSam2Dialog\(\)[\s\S]*closeTrackingStartConfirmation\(\)/)
  assert.match(source, /event\.key === 'Escape' && trackingStartConfirmationVisible\.value/)
  assert.match(source, /watch\(selectedImageIndex, \(index\) => \{[\s\S]*closeTrackingStartConfirmation\(\)/)
})

test('SAM2 tracking confirmation shares the nested modal layer above the app modal', async () => {
  const css = await readFile(stylesPath, 'utf8')
  assert.match(css, /\.tracking-start-confirm-backdrop[\s\S]*z-index: 10001/)
  assert.match(css, /\.tracking-start-confirm-dialog[\s\S]*z-index: 10002/)
  assert.match(css, /\.app-modal[\s\S]*z-index: 10000/)
})

test('SAM2 tracking confirmation translations are available in Chinese and English', async () => {
  const [en, zh] = await Promise.all([readFile(enPath, 'utf8'), readFile(zhPath, 'utf8')])
  for (const key of ['startConfirmTitle', 'continueTracking']) {
    assert.match(en, new RegExp(`tracking[\\s\\S]*${key}:`))
    assert.match(zh, new RegExp(`tracking[\\s\\S]*${key}:`))
  }
})
