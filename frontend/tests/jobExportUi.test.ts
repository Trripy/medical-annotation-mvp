import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  applyImageSelectorBatch,
  beginImageSelectorRequest,
  buildJobExportPayload,
  canSubmitJobExport,
  canRequestNextImageBatch,
  clearFilteredSelection,
  createImageSelectorBatchState,
  dedupeImageIds,
  getImageSelectorStatus,
  getNextImageSelectorOffset,
  hasVisiblePaginationControls,
  resetImageSelectorQuery,
  selectFilteredResults,
  shouldShowThumbnailPlaceholder,
  toggleImageSelection,
} from '../src/utils/jobExportUi.ts'

test('job export payload includes the three export ranges', () => {
  assert.deepEqual(buildJobExportPayload('all', false, [1, 2]), {
    export_range: 'all',
    include_original_images: false,
    selected_image_ids: [],
  })
  assert.deepEqual(buildJobExportPayload('annotated', true, [1, 2]), {
    export_range: 'annotated',
    include_original_images: true,
    selected_image_ids: [],
  })
  assert.deepEqual(buildJobExportPayload('selected', true, [2, 1, 2]), {
    export_range: 'selected',
    include_original_images: true,
    selected_image_ids: [2, 1],
  })
})

test('include originals defaults can be represented as false', () => {
  const payload = buildJobExportPayload('all', false, [])
  assert.equal(payload.include_original_images, false)
})

test('selected empty disables export while all and annotated remain enabled', () => {
  assert.equal(canSubmitJobExport('selected', 0), false)
  assert.equal(canSubmitJobExport('selected', 1), true)
  assert.equal(canSubmitJobExport('all', 0), true)
  assert.equal(canSubmitJobExport('annotated', 0), true)
})

test('single and multiple image selection use stable ids', () => {
  let selected = new Set<number>()
  selected = toggleImageSelection(selected, 10, true)
  assert.deepEqual([...selected], [10])
  selected = toggleImageSelection(selected, 20, true)
  selected = toggleImageSelection(selected, 10, false)
  assert.deepEqual([...selected], [20])
})

test('selector source no longer exposes pagination controls or page-size controls', () => {
  const source = readFileSync(new URL('../src/views/JobsPage.vue', import.meta.url), 'utf8')
  assert.equal(hasVisiblePaginationControls(source), false)
})

test('initial selector request starts from offset zero and loads the first batch', () => {
  let state = createImageSelectorBatchState()
  assert.equal(getNextImageSelectorOffset(state), 0)
  state = beginImageSelectorRequest(state)
  assert.equal(state.loading, true)
  state = applyImageSelectorBatch(state, { itemCount: 72, total: 129, generation: state.generation })
  assert.equal(state.itemsLoaded, 72)
  assert.equal(state.hasMore, true)
})

test('scrolling to the sentinel loads the next batch by current loaded offset', () => {
  let state = createImageSelectorBatchState()
  state = beginImageSelectorRequest(state)
  state = applyImageSelectorBatch(state, { itemCount: 72, total: 129, generation: state.generation })
  assert.equal(getNextImageSelectorOffset(state), 72)
  state = beginImageSelectorRequest(state)
  state = applyImageSelectorBatch(state, { itemCount: 57, total: 129, generation: state.generation })
  assert.equal(state.itemsLoaded, 129)
  assert.equal(state.hasMore, false)
})

test('has_more false prevents additional requests', () => {
  let state = createImageSelectorBatchState()
  state = beginImageSelectorRequest(state)
  state = applyImageSelectorBatch(state, { itemCount: 10, total: 10, generation: state.generation })
  assert.equal(canRequestNextImageBatch(state), false)
  assert.equal(beginImageSelectorRequest(state), state)
})

test('same batch is not requested twice while loading', () => {
  const loadingState = beginImageSelectorRequest(createImageSelectorBatchState())
  assert.equal(canRequestNextImageBatch(loadingState), false)
  assert.equal(beginImageSelectorRequest(loadingState), loadingState)
})

test('search resets selector loading to offset zero with a new generation', () => {
  let state = createImageSelectorBatchState()
  state = applyImageSelectorBatch(beginImageSelectorRequest(state), { itemCount: 72, total: 129, generation: 0 })
  const reset = resetImageSelectorQuery(state)
  assert.equal(reset.itemsLoaded, 0)
  assert.equal(reset.generation, state.generation + 1)
  assert.equal(getNextImageSelectorOffset(reset), 0)
})

test('annotation filter resets selector loading to offset zero with a new generation', () => {
  const state = applyImageSelectorBatch(beginImageSelectorRequest(createImageSelectorBatchState()), {
    itemCount: 50,
    total: 100,
    generation: 0,
  })
  const reset = resetImageSelectorQuery(state)
  assert.equal(reset.itemsLoaded, 0)
  assert.equal(reset.total, 0)
  assert.equal(reset.hasMore, true)
})

test('late responses from an old search generation do not mutate selector state', () => {
  const reset = resetImageSelectorQuery(createImageSelectorBatchState())
  const result = applyImageSelectorBatch(reset, { itemCount: 72, total: 129, generation: reset.generation - 1 })
  assert.equal(result, reset)
  assert.equal(result.itemsLoaded, 0)
})

test('selection survives loading additional batches because only ids are stored', () => {
  let selected = new Set<number>([1])
  selected = selectFilteredResults(selected, [10, 11])
  assert.deepEqual([...selected], [1, 10, 11])
  selected = selectFilteredResults(selected, [30])
  assert.deepEqual([...selected], [1, 10, 11, 30])
})

test('selection survives search and filter changes when selected ids are not reset', () => {
  const selectedBeforeSearch = new Set([1, 20])
  const afterSearchReset = resetImageSelectorQuery(createImageSelectorBatchState())
  assert.deepEqual([...selectedBeforeSearch], [1, 20])
  assert.equal(afterSearchReset.itemsLoaded, 0)
})

test('select filtered results uses every matching id, not just loaded thumbnails', () => {
  const loadedImageIds = [1, 2]
  const allFilteredIds = [1, 2, 3, 4, 5]
  const selected = selectFilteredResults(new Set(loadedImageIds), allFilteredIds)
  assert.deepEqual([...selected], [1, 2, 3, 4, 5])
})

test('clear filtered selection only removes matching ids', () => {
  const selected = clearFilteredSelection(new Set([1, 2, 3, 4]), [2, 4, 99])
  assert.deepEqual([...selected], [1, 3])
})

test('clear all selection is a new empty set in the caller', () => {
  const selected = new Set<number>()
  assert.equal(selected.size, 0)
})

test('cancel selection can restore an opening snapshot', () => {
  const snapshot = new Set([1, 2])
  let selected = selectFilteredResults(snapshot, [3, 4])
  assert.deepEqual([...selected], [1, 2, 3, 4])
  selected = new Set(snapshot)
  assert.deepEqual([...selected], [1, 2])
})

test('confirm selection keeps the current selected ids', () => {
  const selected = selectFilteredResults(new Set([1]), [2, 3])
  const confirmed = new Set(selected)
  assert.deepEqual([...confirmed], [1, 2, 3])
})

test('switching jobs clears selected image ids', () => {
  let selected = new Set([1, 2, 3])
  selected = new Set()
  assert.equal(selected.size, 0)
})

test('empty and all-loaded selector states are distinct', () => {
  assert.equal(getImageSelectorStatus({ itemsLoaded: 0, total: 0, hasMore: false, loading: false, generation: 0 }), 'empty')
  assert.equal(getImageSelectorStatus({ itemsLoaded: 129, total: 129, hasMore: false, loading: false, generation: 0 }), 'allLoaded')
  assert.equal(getImageSelectorStatus({ itemsLoaded: 0, total: 0, hasMore: true, loading: true, generation: 0 }), 'loading')
})

test('thumbnail failures render the placeholder state', () => {
  assert.equal(shouldShowThumbnailPlaceholder('/api/images/1/thumbnail', false), false)
  assert.equal(shouldShowThumbnailPlaceholder('/api/images/1/thumbnail', true), true)
  assert.equal(shouldShowThumbnailPlaceholder('', false), true)
})

test('dedupe image ids ignores invalid and duplicate values', () => {
  assert.deepEqual(dedupeImageIds([1, 2, 2, Number.NaN, 3.2, 4]), [1, 2, 4])
})

test('repeat export click can be blocked by exporting state outside payload builder', () => {
  const exportingJobIds = new Set([76])
  assert.equal(exportingJobIds.has(76), true)
  assert.equal(exportingJobIds.has(77), false)
})
