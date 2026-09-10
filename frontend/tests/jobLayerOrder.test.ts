import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

const pagePath = new URL('../src/views/AnnotatePage.vue', import.meta.url)
const storePath = new URL('../src/stores/annotation.ts', import.meta.url)
const enPath = new URL('../src/i18n/locales/en-US.ts', import.meta.url)
const zhPath = new URL('../src/i18n/locales/zh-CN.ts', import.meta.url)

test('Job layer rule UI is Job-scoped and sends front-to-back order', async () => {
  const source = await readFile(pagePath, 'utf8')
  assert.match(source, /jobLayerOrder\.jobScopedNotice/)
  assert.match(source, /draggable="true"/)
  assert.match(source, /saveLayerRule\(true\)/)
  assert.match(source, /previewJobLayerOrderRule/)
  assert.match(source, /applyLayerRuleOnNextSave/)
})

test('Save + Apply previews before opening a body-teleported confirmation and only confirms later', async () => {
  const source = await readFile(pagePath, 'utf8')
  const saveStart = source.indexOf('async function saveLayerRule')
  const persistStart = source.indexOf('async function persistLayerRule')
  const saveBody = source.slice(saveStart, persistStart)
  assert.match(saveBody, /previewJobLayerOrderRule/)
  assert.match(saveBody, /layerRuleApplyConfirmVisible\.value = true/)
  assert.doesNotMatch(saveBody, /saveJobLayerOrderRule/)
  assert.match(source, /<Teleport to="body">[\s\S]*layerRuleApplyConfirmVisible/)
  assert.match(source, /@click="confirmLayerRuleApply"/)
  assert.match(source, /saveJobLayerOrderRule\([\s\S]*applyExisting/)
  assert.match(source, /event\.key === 'Escape' && layerRuleApplyConfirmVisible\.value/)
  assert.match(source, /closeLayerRuleDialog[\s\S]*layerRuleApplyConfirmVisible\.value = false/)
})

test('confirmation uses a scoped layer above the rule editor rather than a global arbitrary z-index', async () => {
  const css = await readFile(new URL('../src/styles.css', import.meta.url), 'utf8')
  assert.match(css, /\.job-layer-rule-confirm-backdrop[\s\S]*z-index: 10001/)
  assert.match(css, /\.job-layer-rule-confirm-dialog[\s\S]*z-index: 10002/)
  assert.match(css, /\.app-modal[\s\S]*z-index: 10000/)
})

test('Delete Rule uses a separate body-teleported confirmation and only deletes after explicit confirmation', async () => {
  const source = await readFile(pagePath, 'utf8')
  const requestStart = source.indexOf('function requestLayerRuleDelete')
  const confirmStart = source.indexOf('async function confirmLayerRuleDelete')
  const requestBody = source.slice(requestStart, confirmStart)
  const confirmEnd = source.indexOf('async function goToImage', confirmStart)
  const confirmBody = source.slice(confirmStart, confirmEnd)

  assert.doesNotMatch(source, /ElMessageBox/)
  assert.match(requestBody, /layerRuleDeleteConfirmVisible\.value = true/)
  assert.doesNotMatch(requestBody, /deleteJobLayerOrderRule/)
  assert.match(source, /<Teleport to="body">[\s\S]*layerRuleDeleteConfirmVisible/)
  assert.match(source, /@click="confirmLayerRuleDelete"/)
  assert.match(confirmBody, /deleteJobLayerOrderRule\(deletingJobId\)/)
  assert.match(confirmBody, /fetchJobLayerOrderRule\(deletingJobId\)/)
  assert.match(confirmBody, /layerRuleAutoApply\.value = false/)
  assert.match(source, /event\.key === 'Escape' && layerRuleDeleteConfirmVisible\.value/)
  assert.match(source, /closeLayerRuleDialog[\s\S]*resetLayerRuleDeleteConfirmation\(\)/)
  assert.match(source, /watch\(\(\) => props\.jobId, \(\) => \{[\s\S]*resetLayerRuleDeleteConfirmation\(\)/)
})

test('store uses one batch preview/save API and never sends gap-like per-object requests', async () => {
  const source = await readFile(storePath, 'utf8')
  assert.match(source, /layer-order-rule\/preview/)
  assert.match(source, /method: 'PUT'/)
  assert.match(source, /apply_layer_rule/)
})

test('layer rule translations are available in Chinese and English', async () => {
  const [en, zh] = await Promise.all([readFile(enPath, 'utf8'), readFile(zhPath, 'utf8')])
  for (const key of [
    'shortTitle', 'title', 'autoApply', 'saveAndApply', 'jobScopedNotice', 'deleted',
    'deleteConfirmTitle', 'deleteConfirmDescription', 'deleteConfirmAnnotationNotice', 'deleteConfirmButton',
  ]) {
    assert.match(en, new RegExp(`jobLayerOrder[\\s\\S]*${key}:`))
    assert.match(zh, new RegExp(`jobLayerOrder[\\s\\S]*${key}:`))
  }
})
