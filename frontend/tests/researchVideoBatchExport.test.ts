import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

import { parseContentDispositionFilename } from '../src/utils/download.ts'
import {
  buildBatchExportPayload,
  resolveBatchDownloadFilename,
  setPhaseExportSelection,
  setTrimSelection,
  summarizeSelections,
  type VideoExportSelection,
} from '../src/utils/researchVideoChecklist.ts'

test('batch export filename prefers UTF-8 content disposition then page fallback', () => {
  const header = "attachment; filename=\"research-video-export.zip\"; filename*=UTF-8''%E7%99%BD%E5%86%85%E9%9A%9C%E9%98%B6%E6%AE%B5%E6%A0%87%E7%AD%BE%E7%AC%AC%E4%B8%80%E6%89%B9.zip"

  assert.equal(parseContentDispositionFilename(header), '白内障阶段标签第一批.zip')
  assert.equal(resolveBatchDownloadFilename(header, 'fallback.zip'), '白内障阶段标签第一批.zip')
  assert.equal(resolveBatchDownloadFilename(null, 'research-video-export_20260730_1212.zip'), 'research-video-export_20260730_1212.zip')
  assert.equal(resolveBatchDownloadFilename(null, null), 'research-video-export.zip')
})

test('batch export payload includes batch name and excludes unselected videos', () => {
  const selections = new Map<number, VideoExportSelection>()
  setTrimSelection(selections, 10, true)
  setTrimSelection(selections, 11, false)
  setPhaseExportSelection(selections, 12, 90, 7)

  const payload = buildBatchExportPayload(selections, {
    batchName: '白内障阶段标签第一批',
    includeSummaryCsv: true,
  })

  assert.deepEqual(payload, {
    items: [
      { video_id: 10, include_trim_info: true, phase_exports: [] },
      { video_id: 12, include_trim_info: false, phase_exports: [{ annotation_set_id: 90, mapping_profile_id: 7 }] },
    ],
    include_summary_csv: true,
    batch_name: '白内障阶段标签第一批',
  })
  assert.equal(summarizeSelections(selections).videoCount, 2)
})

test('phase export selection can be removed without leaving empty video entries', () => {
  const selections = new Map<number, VideoExportSelection>()
  setPhaseExportSelection(selections, 20, 3, null)
  assert.equal(selections.has(20), true)

  setPhaseExportSelection(selections, 20, 3, undefined)

  assert.equal(selections.has(20), false)
  assert.deepEqual(buildBatchExportPayload(selections).items, [])
})

test('checklist page contains preview dialog and does not auto-export on load', () => {
  const source = readFileSync(new URL('../src/views/ResearchVideoChecklistPage.vue', import.meta.url), 'utf8')

  assert.match(source, /previewDialogVisible/)
  assert.match(source, /previewExport/)
  assert.match(source, /exportSelected/)
  assert.match(source, /resolveBatchDownloadFilename/)
  assert.doesNotMatch(source, /onMounted\(\(\) => \{[^}]*video-batch-export/s)
})
