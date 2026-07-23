import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createFramePageCacheState,
  DEFAULT_FRAME_PAGE_SIZE,
  ensureFramePageLoaded,
  getFrameAtFromPages,
  getFrameOffsetInPage,
  getFramePageIndex,
  getFramePageIndicesForRange,
  getFramePagesToEvict,
} from '../src/utils/researchVideoFrames.ts'

function createPageItems(pageIndex: number, pageSize = DEFAULT_FRAME_PAGE_SIZE) {
  return Array.from({ length: pageSize }, (_, offset) => ({
    id: (pageIndex * pageSize) + offset,
    frame_index: (pageIndex * pageSize) + offset,
  }))
}

test('getFramePageIndex and getFrameOffsetInPage map frame indices into fixed pages', () => {
  assert.equal(getFramePageIndex(0), 0)
  assert.equal(getFramePageIndex(499), 0)
  assert.equal(getFramePageIndex(500), 1)
  assert.equal(getFramePageIndex(16_728), 33)

  assert.equal(getFrameOffsetInPage(0), 0)
  assert.equal(getFrameOffsetInPage(499), 499)
  assert.equal(getFrameOffsetInPage(500), 0)
  assert.equal(getFrameOffsetInPage(1_516), 16)
})

test('getFrameAtFromPages resolves cached frames without building a placeholder array', () => {
  const pages = new Map<number, readonly { frame_index: number }[]>([
    [0, createPageItems(0)],
    [3, createPageItems(3)],
  ])

  assert.equal(getFrameAtFromPages(pages, 0, 10_000)?.frame_index, 0)
  assert.equal(getFrameAtFromPages(pages, 1_516, 10_000)?.frame_index, 1_516)
  assert.equal(getFrameAtFromPages(pages, 999, 10_000), undefined)
})

test('getFramePageIndicesForRange spans only the pages needed by the visible range', () => {
  assert.deepEqual(getFramePageIndicesForRange(0, 10, 20_000), [0])
  assert.deepEqual(getFramePageIndicesForRange(499, 500, 20_000), [0, 1])
  assert.deepEqual(getFramePageIndicesForRange(2_000, 2_030, 20_000), [4])
  assert.deepEqual(getFramePageIndicesForRange(2_480, 2_530, 20_000), [4, 5])
})

test('ensureFramePageLoaded de-duplicates concurrent page requests', async () => {
  const state = createFramePageCacheState<{ frame_index: number }>()
  let requestCount = 0

  await Promise.all([
    ensureFramePageLoaded({
      state,
      pageIndex: 4,
      totalCount: 20_000,
      generation: 1,
      isCurrentGeneration: (generation) => generation === 1,
      loadPage: async () => {
        requestCount += 1
        await Promise.resolve()
        return createPageItems(4)
      },
    }),
    ensureFramePageLoaded({
      state,
      pageIndex: 4,
      totalCount: 20_000,
      generation: 1,
      isCurrentGeneration: (generation) => generation === 1,
      loadPage: async () => {
        requestCount += 1
        return createPageItems(4)
      },
    }),
  ])

  assert.equal(requestCount, 1)
  assert.equal(state.pages.get(4)?.length, DEFAULT_FRAME_PAGE_SIZE)
  assert.equal(state.loadingPages.size, 0)
})

test('ensureFramePageLoaded clears failed requests so the same page can be retried', async () => {
  const state = createFramePageCacheState<{ frame_index: number }>()
  let requestCount = 0

  await assert.rejects(async () => {
    await ensureFramePageLoaded({
      state,
      pageIndex: 2,
      totalCount: 20_000,
      generation: 1,
      isCurrentGeneration: (generation) => generation === 1,
      loadPage: async () => {
        requestCount += 1
        throw new Error('temporary failure')
      },
    })
  }, /temporary failure/)

  assert.equal(state.loadingPages.size, 0)
  assert.equal(state.pages.has(2), false)

  await ensureFramePageLoaded({
    state,
    pageIndex: 2,
    totalCount: 20_000,
    generation: 1,
    isCurrentGeneration: (generation) => generation === 1,
    loadPage: async () => {
      requestCount += 1
      return createPageItems(2)
    },
  })

  assert.equal(requestCount, 2)
  assert.equal(state.pages.get(2)?.[0]?.frame_index, 1_000)
})

test('ensureFramePageLoaded ignores late responses from a stale video generation', async () => {
  const state = createFramePageCacheState<{ frame_index: number }>()
  let currentGeneration = 1
  let resolvePage: ((items: readonly { frame_index: number }[] | null) => void) | null = null

  const requestPromise = ensureFramePageLoaded({
    state,
    pageIndex: 7,
    totalCount: 20_000,
    generation: 1,
    isCurrentGeneration: (generation) => generation === currentGeneration,
    loadPage: () => new Promise((resolve) => {
      resolvePage = resolve
    }),
  })

  currentGeneration = 2
  resolvePage?.(createPageItems(7))
  await requestPromise

  assert.equal(state.pages.has(7), false)
  assert.equal(state.loadingPages.size, 0)
})

test('getFramePagesToEvict preserves the current page while pruning far older pages first', () => {
  const accessOrderByPage = new Map<number, number>()
  for (let pageIndex = 0; pageIndex <= 12; pageIndex += 1) {
    accessOrderByPage.set(pageIndex, pageIndex + 1)
  }

  const pagesToEvict = getFramePagesToEvict({
    accessOrderByPage,
    cachedPageIndices: Array.from(accessOrderByPage.keys()),
    currentPageIndex: 6,
    maxCachedPages: 12,
  })

  assert.equal(pagesToEvict.length, 1)
  assert.equal(pagesToEvict.includes(6), false)
  assert.equal(pagesToEvict[0], 0)
})
