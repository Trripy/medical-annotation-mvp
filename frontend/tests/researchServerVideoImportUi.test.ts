import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import enUS from '../src/i18n/locales/en-US.ts'
import zhCN from '../src/i18n/locales/zh-CN.ts'
import {
  buildImportQueue,
  calculateSelectedSize,
  cancelPendingQueueItems,
  clearFilteredVideos,
  getFilteredScannedVideos,
  getSelectionCheckboxState,
  invertFilteredVideos,
  selectAllVideos,
  selectFilteredVideos,
} from '../src/utils/researchServerVideoImportUi.ts'

const pageSource = readFileSync(new URL('../src/views/ResearchVideosPage.vue', import.meta.url), 'utf8')
const storeSource = readFileSync(new URL('../src/stores/researchVideos.ts', import.meta.url), 'utf8')

const scannedVideos = [
  { name: 'alpha.mp4', relative_path: 'cases/alpha.mp4', size_bytes: 100, modified_at: '2026-07-01T00:00:00Z' },
  { name: 'beta.mp4', relative_path: 'cases/beta.mp4', size_bytes: 200, modified_at: '2026-07-02T00:00:00Z' },
  { name: 'gamma.mov', relative_path: 'nested/gamma.mov', size_bytes: 300, modified_at: '2026-07-03T00:00:00Z' },
]

test('research import dialog exposes local and server tabs', () => {
  assert.match(pageSource, /importDialogVisible/)
  assert.match(pageSource, /name="local"/)
  assert.match(pageSource, /name="server"/)
  assert.match(pageSource, /researchVideoImport\.source\.local/)
  assert.match(pageSource, /researchVideoImport\.source\.server/)
})

test('default import entry opens local upload without removing upload input behavior', () => {
  assert.match(pageSource, /function openUploadDialog\(\)[\s\S]*importSourceTab\.value = 'local'/)
  assert.match(pageSource, /ref="uploadInputRef"/)
  assert.match(pageSource, /@change="handleUploadChange"/)
  assert.match(storeSource, /async uploadVideo\(file: File/)
})

test('server import roots browse scan and import endpoints are wired', () => {
  assert.match(storeSource, /\/api\/research\/server-video-import\/roots/)
  assert.match(storeSource, /\/api\/research\/server-video-import\/browse/)
  assert.match(storeSource, /\/api\/research\/server-video-import\/scan-folder/)
  assert.match(storeSource, /\/api\/research\/server-video-import\/file/)
})

test('server import payload uses aliases and relative paths only', () => {
  assert.match(storeSource, /root_id: rootId/)
  assert.match(storeSource, /relative_path: relativePath/)
  assert.doesNotMatch(storeSource, /absolute_path/)
  assert.doesNotMatch(pageSource, /absolute_path/)
})

test('server browser supports root switching folder navigation parent breadcrumb refresh and search', () => {
  assert.match(pageSource, /onServerRootChange/)
  assert.match(pageSource, /browseServerDirectory\(directory\.relative_path\)/)
  assert.match(pageSource, /parent_relative_path/)
  assert.match(pageSource, /serverBreadcrumbs/)
  assert.match(pageSource, /serverSearch/)
  assert.match(pageSource, /researchVideoImport\.server\.refresh/)
})

test('server import handles not configured state', () => {
  assert.match(pageSource, /serverRootsEnabled/)
  assert.match(pageSource, /researchVideoImport\.server\.notConfigured/)
})

test('folder scan supports recursive toggle and scan preview counts', () => {
  assert.match(pageSource, /includeSubfolders/)
  assert.match(pageSource, /scanCurrentFolder/)
  assert.match(pageSource, /serverScan\.video_count/)
  assert.match(pageSource, /serverScan\.total_size_bytes/)
  assert.match(pageSource, /unsupported_count/)
  assert.match(pageSource, /unreadable_count/)
})

test('scan opens the selection step and does not create the import queue immediately', () => {
  assert.match(pageSource, /serverImportStep\.value = 'selection'/)
  assert.match(pageSource, /selectedVideoPaths\.value = selectAllVideos\(payload\.videos\)/)
  assert.doesNotMatch(pageSource, /payload\.videos\.map\(\(video\) => \(\{ \.\.\.video, status: 'pending'/)
})

test('batch import is sequential and failed files do not stop later files', () => {
  assert.match(pageSource, /for \(const item of importQueue\.value\)/)
  assert.match(pageSource, /await researchVideosStore\.importServerVideo/)
  assert.match(pageSource, /item\.status = 'failed'/)
  assert.doesNotMatch(pageSource, /Promise\.all/)
})

test('stop remaining import cancels pending queue items only', () => {
  assert.match(pageSource, /stopQueueRequested/)
  assert.match(pageSource, /item\.status = 'cancelled'/)
  assert.match(pageSource, /stopRemainingImports/)
})

test('import dialog cleanup clears temporary server queue state', () => {
  assert.match(pageSource, /@closed="resetImportDialogState"/)
  assert.match(pageSource, /clearServerScanState\(\)/)
  assert.match(pageSource, /clearServerQueueState\(\)/)
})

test('server import i18n keys exist in Chinese and English', () => {
  const enKeys = Object.keys(enUS.researchVideoImport.server).sort()
  const zhKeys = Object.keys(zhCN.researchVideoImport.server).sort()
  assert.deepEqual(zhKeys, enKeys)
  assert.deepEqual(Object.keys(zhCN.researchVideoImport.steps).sort(), Object.keys(enUS.researchVideoImport.steps).sort())
  assert.deepEqual(Object.keys(zhCN.researchVideoImport.selection).sort(), Object.keys(enUS.researchVideoImport.selection).sort())
  assert.equal(zhCN.researchVideoImport.source.local, '本地上传')
  assert.equal(zhCN.researchVideoImport.source.server, '服务器导入')
})

test('scan result selection defaults to all importable videos', () => {
  const selected = selectAllVideos(scannedVideos)
  assert.equal(selected.size, 3)
  assert.equal(calculateSelectedSize(scannedVideos, selected), 600)
})

test('filtered selection operations preserve selections outside the filter', () => {
  const selected = new Set(['cases/alpha.mp4'])
  const filtered = getFilteredScannedVideos(scannedVideos, selected, 'nested', 'all')
  assert.deepEqual(filtered.map((video) => video.relative_path), ['nested/gamma.mov'])

  const afterSelect = selectFilteredVideos(selected, filtered)
  assert.deepEqual([...afterSelect].sort(), ['cases/alpha.mp4', 'nested/gamma.mov'])

  const afterClear = clearFilteredVideos(afterSelect, filtered)
  assert.deepEqual([...afterClear], ['cases/alpha.mp4'])

  const afterInvert = invertFilteredVideos(afterClear, filtered)
  assert.deepEqual([...afterInvert].sort(), ['cases/alpha.mp4', 'nested/gamma.mov'])
})

test('selection filter supports selected and unselected views without clearing selection', () => {
  const selected = new Set(['cases/beta.mp4'])
  assert.deepEqual(
    getFilteredScannedVideos(scannedVideos, selected, '', 'selected').map((video) => video.relative_path),
    ['cases/beta.mp4'],
  )
  assert.deepEqual(
    getFilteredScannedVideos(scannedVideos, selected, '', 'unselected').map((video) => video.relative_path),
    ['cases/alpha.mp4', 'nested/gamma.mov'],
  )
})

test('selection checkbox state distinguishes all partial and empty filtered selections', () => {
  assert.deepEqual(getSelectionCheckboxState(scannedVideos, selectAllVideos(scannedVideos)), {
    checked: true,
    indeterminate: false,
  })
  assert.deepEqual(getSelectionCheckboxState(scannedVideos, new Set(['cases/alpha.mp4'])), {
    checked: false,
    indeterminate: true,
  })
  assert.deepEqual(getSelectionCheckboxState(scannedVideos, new Set()), {
    checked: false,
    indeterminate: false,
  })
})

test('import queue contains only selected videos in scan order', () => {
  const queue = buildImportQueue(scannedVideos, new Set(['nested/gamma.mov', 'cases/alpha.mp4']))
  assert.deepEqual(queue.map((item) => item.relative_path), ['cases/alpha.mp4', 'nested/gamma.mov'])
  assert.deepEqual(queue.map((item) => item.status), ['pending', 'pending'])
})

test('stop remaining helper only cancels pending items', () => {
  const queue = cancelPendingQueueItems([
    { ...scannedVideos[0], status: 'pending', message: '' },
    { ...scannedVideos[1], status: 'importing', message: '' },
    { ...scannedVideos[2], status: 'success', message: 'ok' },
  ])
  assert.deepEqual(queue.map((item) => item.status), ['cancelled', 'importing', 'success'])
})

test('selection interface has no mixed waiting queue in scan result view', () => {
  assert.match(pageSource, /server-video-selection-step/)
  assert.match(pageSource, /server-video-import-progress/)
  assert.match(pageSource, /toggleFilteredSelectionHeader/)
  assert.match(pageSource, /selectionFilter/)
  assert.match(pageSource, /canStartSelectedImport/)
})
