export type ServerVideoSelectionFilter = 'all' | 'selected' | 'unselected'

export type ServerImportQueueStatus = 'pending' | 'importing' | 'success' | 'failed' | 'skipped' | 'cancelled'

export interface ScannedServerVideo {
  name: string
  relative_path: string
  size_bytes: number
  modified_at?: string | null
  extension?: string
}

export type ServerImportQueueItem<T extends ScannedServerVideo = ScannedServerVideo> = T & {
  status: ServerImportQueueStatus
  message: string
}

export interface SelectionCheckboxState {
  checked: boolean
  indeterminate: boolean
}

export function getFilteredScannedVideos<T extends ScannedServerVideo>(
  videos: readonly T[],
  selectedPaths: ReadonlySet<string>,
  search: string,
  filter: ServerVideoSelectionFilter,
): T[] {
  const query = search.trim().toLowerCase()
  return videos.filter((video) => {
    const matchesQuery =
      !query ||
      video.name.toLowerCase().includes(query) ||
      video.relative_path.toLowerCase().includes(query)
    if (!matchesQuery) {
      return false
    }
    const isSelected = selectedPaths.has(video.relative_path)
    if (filter === 'selected') {
      return isSelected
    }
    if (filter === 'unselected') {
      return !isSelected
    }
    return true
  })
}

export function selectAllVideos<T extends ScannedServerVideo>(videos: readonly T[]): Set<string> {
  return new Set(videos.map((video) => video.relative_path))
}

export function selectFilteredVideos<T extends ScannedServerVideo>(
  selectedPaths: ReadonlySet<string>,
  filteredVideos: readonly T[],
): Set<string> {
  const next = new Set(selectedPaths)
  for (const video of filteredVideos) {
    next.add(video.relative_path)
  }
  return next
}

export function clearFilteredVideos<T extends ScannedServerVideo>(
  selectedPaths: ReadonlySet<string>,
  filteredVideos: readonly T[],
): Set<string> {
  const next = new Set(selectedPaths)
  for (const video of filteredVideos) {
    next.delete(video.relative_path)
  }
  return next
}

export function invertFilteredVideos<T extends ScannedServerVideo>(
  selectedPaths: ReadonlySet<string>,
  filteredVideos: readonly T[],
): Set<string> {
  const next = new Set(selectedPaths)
  for (const video of filteredVideos) {
    if (next.has(video.relative_path)) {
      next.delete(video.relative_path)
    } else {
      next.add(video.relative_path)
    }
  }
  return next
}

export function calculateSelectedSize<T extends ScannedServerVideo>(
  videos: readonly T[],
  selectedPaths: ReadonlySet<string>,
): number {
  return videos.reduce((total, video) => {
    return selectedPaths.has(video.relative_path) ? total + video.size_bytes : total
  }, 0)
}

export function getSelectionCheckboxState<T extends ScannedServerVideo>(
  filteredVideos: readonly T[],
  selectedPaths: ReadonlySet<string>,
): SelectionCheckboxState {
  if (filteredVideos.length === 0) {
    return { checked: false, indeterminate: false }
  }
  const selectedCount = filteredVideos.filter((video) => selectedPaths.has(video.relative_path)).length
  return {
    checked: selectedCount === filteredVideos.length,
    indeterminate: selectedCount > 0 && selectedCount < filteredVideos.length,
  }
}

export function buildImportQueue<T extends ScannedServerVideo>(
  videos: readonly T[],
  selectedPaths: ReadonlySet<string>,
): ServerImportQueueItem<T>[] {
  return videos
    .filter((video) => selectedPaths.has(video.relative_path))
    .map((video) => ({ ...video, status: 'pending', message: '' }))
}

export function cancelPendingQueueItems<T extends ScannedServerVideo>(
  queue: readonly ServerImportQueueItem<T>[],
): ServerImportQueueItem<T>[] {
  return queue.map((item) => (item.status === 'pending' ? { ...item, status: 'cancelled' } : item))
}
