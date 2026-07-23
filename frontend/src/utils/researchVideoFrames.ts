export const DEFAULT_FRAME_PAGE_SIZE = 500
export const DEFAULT_MAX_CACHED_FRAME_PAGES = 12

export type FramePageCacheState<T> = {
  pages: Map<number, readonly T[]>
  loadingPages: Map<number, Promise<void>>
  pageAccessOrder: Map<number, number>
  accessSequence: number
}

export type EnsureFramePageLoadedOptions<T> = {
  state: FramePageCacheState<T>
  pageIndex: number
  totalCount: number
  generation: number
  isCurrentGeneration: (generation: number) => boolean
  loadPage: (input: {
    generation: number
    limit: number
    offset: number
    pageIndex: number
  }) => Promise<readonly T[] | null>
  currentPageIndex?: number
  maxCachedPages?: number
  pageSize?: number
  preservedPageIndices?: Iterable<number>
}

export type FramePageEvictionInput = {
  accessOrderByPage: ReadonlyMap<number, number>
  cachedPageIndices: Iterable<number>
  currentPageIndex: number
  maxCachedPages: number
  preservedPageIndices?: Iterable<number>
}

export function createFramePageCacheState<T>(): FramePageCacheState<T> {
  return {
    pages: new Map<number, readonly T[]>(),
    loadingPages: new Map<number, Promise<void>>(),
    pageAccessOrder: new Map<number, number>(),
    accessSequence: 0,
  }
}

export function resetFramePageCache<T>(state: FramePageCacheState<T>) {
  state.pages.clear()
  state.loadingPages.clear()
  state.pageAccessOrder.clear()
  state.accessSequence = 0
}

export function getFramePageIndex(frameIndex: number, pageSize = DEFAULT_FRAME_PAGE_SIZE) {
  return Math.floor(frameIndex / pageSize)
}

export function getFrameOffsetInPage(frameIndex: number, pageSize = DEFAULT_FRAME_PAGE_SIZE) {
  return frameIndex % pageSize
}

export function getFramePageOffset(pageIndex: number, pageSize = DEFAULT_FRAME_PAGE_SIZE) {
  return pageIndex * pageSize
}

export function getFramePageIndicesForRange(
  startIndex: number,
  endIndex: number,
  totalCount: number,
  pageSize = DEFAULT_FRAME_PAGE_SIZE,
) {
  if (startIndex > endIndex || totalCount <= 0) {
    return []
  }

  const clampedStart = Math.max(0, startIndex)
  const clampedEnd = Math.min(totalCount - 1, endIndex)
  const startPageIndex = getFramePageIndex(clampedStart, pageSize)
  const endPageIndex = getFramePageIndex(clampedEnd, pageSize)
  const pageIndices: number[] = []

  for (let pageIndex = startPageIndex; pageIndex <= endPageIndex; pageIndex += 1) {
    if (getFramePageOffset(pageIndex, pageSize) >= totalCount) {
      break
    }
    pageIndices.push(pageIndex)
  }

  return pageIndices
}

export function getFrameAtFromPages<T>(
  pages: ReadonlyMap<number, readonly T[]>,
  frameIndex: number,
  totalCount: number,
  pageSize = DEFAULT_FRAME_PAGE_SIZE,
) {
  if (frameIndex < 0 || frameIndex >= totalCount) {
    return undefined
  }

  const page = pages.get(getFramePageIndex(frameIndex, pageSize))
  if (!page) {
    return undefined
  }

  return page[getFrameOffsetInPage(frameIndex, pageSize)]
}

export function getFramePagesToEvict(input: FramePageEvictionInput) {
  const cachedPageIndices = Array.from(input.cachedPageIndices)
  if (cachedPageIndices.length <= input.maxCachedPages) {
    return []
  }

  const preferredPreservedPages = new Set<number>([
    input.currentPageIndex,
    input.currentPageIndex - 1,
    input.currentPageIndex + 1,
  ])
  for (const pageIndex of input.preservedPageIndices ?? []) {
    preferredPreservedPages.add(pageIndex)
  }

  const normalizedPreservedPages = new Set(
    Array.from(preferredPreservedPages).filter((pageIndex) => pageIndex >= 0),
  )

  const sortedCandidates = (preservedPages: ReadonlySet<number>) => cachedPageIndices
    .filter((pageIndex) => !preservedPages.has(pageIndex))
    .sort((leftPageIndex, rightPageIndex) => {
      const leftDistance = Math.abs(leftPageIndex - input.currentPageIndex)
      const rightDistance = Math.abs(rightPageIndex - input.currentPageIndex)
      if (leftDistance !== rightDistance) {
        return rightDistance - leftDistance
      }

      const leftAccessOrder = input.accessOrderByPage.get(leftPageIndex) ?? 0
      const rightAccessOrder = input.accessOrderByPage.get(rightPageIndex) ?? 0
      if (leftAccessOrder !== rightAccessOrder) {
        return leftAccessOrder - rightAccessOrder
      }

      return leftPageIndex - rightPageIndex
    })

  const pagesToEvict: number[] = []
  let remainingCount = cachedPageIndices.length
  const firstPassCandidates = sortedCandidates(normalizedPreservedPages)
  for (const pageIndex of firstPassCandidates) {
    if (remainingCount <= input.maxCachedPages) {
      break
    }
    pagesToEvict.push(pageIndex)
    remainingCount -= 1
  }

  if (remainingCount <= input.maxCachedPages) {
    return pagesToEvict
  }

  const fallbackPreservedPages = new Set<number>([input.currentPageIndex])
  const secondPassCandidates = sortedCandidates(fallbackPreservedPages)
  for (const pageIndex of secondPassCandidates) {
    if (remainingCount <= input.maxCachedPages || pagesToEvict.includes(pageIndex)) {
      continue
    }
    pagesToEvict.push(pageIndex)
    remainingCount -= 1
  }

  return pagesToEvict
}

export function pruneFramePageCache<T>(
  state: FramePageCacheState<T>,
  currentPageIndex: number,
  maxCachedPages = DEFAULT_MAX_CACHED_FRAME_PAGES,
  preservedPageIndices?: Iterable<number>,
) {
  const pagesToEvict = getFramePagesToEvict({
    accessOrderByPage: state.pageAccessOrder,
    cachedPageIndices: state.pages.keys(),
    currentPageIndex,
    maxCachedPages,
    preservedPageIndices,
  })

  for (const pageIndex of pagesToEvict) {
    state.pages.delete(pageIndex)
    state.pageAccessOrder.delete(pageIndex)
  }

  return pagesToEvict
}

export async function ensureFramePageLoaded<T>(
  options: EnsureFramePageLoadedOptions<T>,
): Promise<void> {
  const {
    state,
    pageIndex,
    totalCount,
    generation,
    isCurrentGeneration,
    loadPage,
    currentPageIndex = pageIndex,
    maxCachedPages = DEFAULT_MAX_CACHED_FRAME_PAGES,
    pageSize = DEFAULT_FRAME_PAGE_SIZE,
    preservedPageIndices,
  } = options

  if (
    pageIndex < 0 ||
    totalCount <= 0 ||
    getFramePageOffset(pageIndex, pageSize) >= totalCount
  ) {
    return
  }

  const cachedPage = state.pages.get(pageIndex)
  if (cachedPage) {
    touchFramePage(state, pageIndex)
    return
  }

  const existingRequest = state.loadingPages.get(pageIndex)
  if (existingRequest) {
    await existingRequest
    if (state.pages.has(pageIndex)) {
      touchFramePage(state, pageIndex)
    }
    return
  }

  let request: Promise<void>
  request = (async () => {
    const items = await loadPage({
      generation,
      limit: pageSize,
      offset: getFramePageOffset(pageIndex, pageSize),
      pageIndex,
    })

    if (!items || !isCurrentGeneration(generation)) {
      return
    }

    state.pages.set(pageIndex, Array.from(items))
    touchFramePage(state, pageIndex)
    pruneFramePageCache(state, currentPageIndex, maxCachedPages, preservedPageIndices)
  })().finally(() => {
    if (state.loadingPages.get(pageIndex) === request) {
      state.loadingPages.delete(pageIndex)
    }
  })

  state.loadingPages.set(pageIndex, request)
  await request
}

function touchFramePage<T>(state: FramePageCacheState<T>, pageIndex: number) {
  state.accessSequence += 1
  state.pageAccessOrder.set(pageIndex, state.accessSequence)
}
