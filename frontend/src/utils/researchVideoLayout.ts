export const MIN_PLAYER_PANE_HEIGHT = 120
export const DEFAULT_PLAYER_HEIGHT_RATIO = 0.3
export const DEFAULT_PLAYER_SPLIT_HANDLE_HEIGHT = 8

export type ResearchPlayerHeightBoundsInput = {
  viewportHeight: number
  workspaceHeight: number
  splitHandleHeight: number
}

export type ResearchPlayerHeightBounds = {
  minPlayerHeight: number
  maxPlayerHeight: number
}

export type VirtualRangeInput = {
  scrollTop: number
  viewportHeight: number
  itemCount: number
  rowHeight: number
  overscan: number
}

export type VirtualRange = {
  startIndex: number
  endIndex: number
  offsetTop: number
  totalHeight: number
}

export function getResearchPlayerHeightBounds(
  input: ResearchPlayerHeightBoundsInput,
): ResearchPlayerHeightBounds {
  const minPlayerHeight = MIN_PLAYER_PANE_HEIGHT
  const usableWorkspaceHeight = Math.max(input.workspaceHeight, 0)
  const maxPlayerHeight = Math.max(
    minPlayerHeight,
    usableWorkspaceHeight - input.splitHandleHeight,
  )

  return {
    minPlayerHeight,
    maxPlayerHeight,
  }
}

export function clampResearchPlayerHeight(
  nextHeight: number,
  input: ResearchPlayerHeightBoundsInput,
): number {
  const bounds = getResearchPlayerHeightBounds(input)
  return Math.max(bounds.minPlayerHeight, Math.min(nextHeight, bounds.maxPlayerHeight))
}

export function getDefaultResearchPlayerHeight(input: ResearchPlayerHeightBoundsInput): number {
  return clampResearchPlayerHeight(
    Math.round(Math.max(input.workspaceHeight, 0) * DEFAULT_PLAYER_HEIGHT_RATIO),
    input,
  )
}

export function getVirtualRange(input: VirtualRangeInput): VirtualRange {
  if (input.itemCount <= 0 || input.rowHeight <= 0 || input.viewportHeight <= 0) {
    return {
      startIndex: 0,
      endIndex: -1,
      offsetTop: 0,
      totalHeight: 0,
    }
  }

  const overscan = Math.max(0, input.overscan)
  const totalHeight = input.itemCount * input.rowHeight
  const clampedScrollTop = Math.max(0, Math.min(input.scrollTop, totalHeight))
  const firstVisibleIndex = Math.floor(clampedScrollTop / input.rowHeight)
  const visibleCount = Math.max(1, Math.ceil(input.viewportHeight / input.rowHeight))
  const startIndex = Math.max(0, firstVisibleIndex - overscan)
  const endIndex = Math.min(
    input.itemCount - 1,
    firstVisibleIndex + visibleCount + overscan - 1,
  )

  return {
    startIndex,
    endIndex,
    offsetTop: startIndex * input.rowHeight,
    totalHeight,
  }
}
