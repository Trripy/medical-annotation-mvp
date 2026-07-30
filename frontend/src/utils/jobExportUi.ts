import type { JobExportRange } from '../stores/jobs'

export type JobExportPayload = {
  export_range: JobExportRange
  include_original_images: boolean
  selected_image_ids: number[]
}

export function buildJobExportPayload(
  exportRange: JobExportRange,
  includeOriginalImages: boolean,
  selectedImageIds: Iterable<number>,
): JobExportPayload {
  return {
    export_range: exportRange,
    include_original_images: includeOriginalImages,
    selected_image_ids: exportRange === 'selected' ? dedupeImageIds(selectedImageIds) : [],
  }
}

export function dedupeImageIds(imageIds: Iterable<number>): number[] {
  const selected: number[] = []
  const seen = new Set<number>()
  for (const rawId of imageIds) {
    const imageId = Number(rawId)
    if (!Number.isInteger(imageId) || seen.has(imageId)) {
      continue
    }
    seen.add(imageId)
    selected.push(imageId)
  }
  return selected
}

export function toggleImageSelection(selectedImageIds: Set<number>, imageId: number, selected: boolean): Set<number> {
  const next = new Set(selectedImageIds)
  if (selected) {
    next.add(imageId)
  } else {
    next.delete(imageId)
  }
  return next
}

export function selectFilteredResults(selectedImageIds: Set<number>, filteredImageIds: Iterable<number>): Set<number> {
  const next = new Set(selectedImageIds)
  for (const imageId of filteredImageIds) {
    next.add(imageId)
  }
  return next
}

export function clearFilteredSelection(selectedImageIds: Set<number>, filteredImageIds: Iterable<number>): Set<number> {
  const next = new Set(selectedImageIds)
  for (const imageId of filteredImageIds) {
    next.delete(imageId)
  }
  return next
}

export function canSubmitJobExport(exportRange: JobExportRange, selectedImageCount: number): boolean {
  return exportRange !== 'selected' || selectedImageCount > 0
}

export type ImageSelectorBatchState = {
  itemsLoaded: number
  total: number
  hasMore: boolean
  loading: boolean
  generation: number
}

export function createImageSelectorBatchState(total = 0): ImageSelectorBatchState {
  return {
    itemsLoaded: 0,
    total,
    hasMore: true,
    loading: false,
    generation: 0,
  }
}

export function getNextImageSelectorOffset(state: ImageSelectorBatchState): number {
  return state.itemsLoaded
}

export function canRequestNextImageBatch(state: ImageSelectorBatchState): boolean {
  return state.hasMore && !state.loading
}

export function beginImageSelectorRequest(state: ImageSelectorBatchState): ImageSelectorBatchState {
  if (!canRequestNextImageBatch(state)) {
    return state
  }
  return { ...state, loading: true }
}

export function applyImageSelectorBatch(
  state: ImageSelectorBatchState,
  response: { itemCount: number; total: number; generation: number },
): ImageSelectorBatchState {
  if (response.generation !== state.generation) {
    return state
  }

  const itemsLoaded = state.itemsLoaded + response.itemCount
  return {
    ...state,
    itemsLoaded,
    total: response.total,
    hasMore: itemsLoaded < response.total,
    loading: false,
  }
}

export function resetImageSelectorQuery(state: ImageSelectorBatchState): ImageSelectorBatchState {
  return {
    itemsLoaded: 0,
    total: 0,
    hasMore: true,
    loading: false,
    generation: state.generation + 1,
  }
}

export function hasVisiblePaginationControls(templateSource: string): boolean {
  return /<el-pagination\b|page-size|page-sizes|current-page|selectCurrentPage|clearCurrentPage/.test(templateSource)
}

export function getImageSelectorStatus(
  state: ImageSelectorBatchState,
): 'loading' | 'empty' | 'allLoaded' | 'ready' {
  if (state.loading && state.itemsLoaded === 0) {
    return 'loading'
  }
  if (!state.loading && state.total === 0 && !state.hasMore) {
    return 'empty'
  }
  if (!state.loading && state.itemsLoaded > 0 && !state.hasMore) {
    return 'allLoaded'
  }
  return 'ready'
}

export function shouldShowThumbnailPlaceholder(thumbnailUrl: string | null | undefined, failed: boolean): boolean {
  return !thumbnailUrl || failed
}
