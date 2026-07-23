<script setup lang="ts">
import { Back, RefreshRight, VideoPause, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowReactive, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import VirtualFrameList from '../components/VirtualFrameList.vue'
import PhaseSegmentInspector from '../components/research/PhaseSegmentInspector.vue'
import PhaseTimeline from '../components/research/PhaseTimeline.vue'
import PhaseValidationPanel from '../components/research/PhaseValidationPanel.vue'
import ResearchVideoTaskNav from '../components/research/ResearchVideoTaskNav.vue'
import VideoPlaybackRateControl from '../components/VideoPlaybackRateControl.vue'
import { useVideoPlaybackRate } from '../composables/useVideoPlaybackRate.ts'
import {
  useResearchPhasesStore,
  restoreSelectedSegmentId,
  type PhaseActionResult,
} from '../stores/researchPhases'
import {
  useResearchVideosStore,
  type ResearchVideoFrame,
  type ResearchVideoWorkspaceDetail,
} from '../stores/researchVideos'
import { useUsersStore } from '../stores/users'
import type {
  ResearchPhaseLabel,
  ResearchPhaseMutationResponse,
  ResearchPhaseSegment,
  ResearchPhaseValidationIssue,
} from '../types/researchPhase'
import {
  DEFAULT_FRAME_PAGE_SIZE,
  DEFAULT_MAX_CACHED_FRAME_PAGES,
  ensureFramePageLoaded as ensureFramePageLoadedInCache,
  getFrameAtFromPages,
  getFramePageIndex,
  getFramePageIndicesForRange,
  getFramePageOffset,
  resetFramePageCache,
  type FramePageCacheState,
} from '../utils/researchVideoFrames'
import {
  clampResearchPlayerHeight,
  DEFAULT_PLAYER_SPLIT_HANDLE_HEIGHT,
  getDefaultResearchPlayerHeight,
  getResearchPlayerHeightBounds,
} from '../utils/researchVideoLayout'
import { findSegmentAtFrame } from '../utils/researchPhaseTimeline'
import {
  getPhaseLabelDisplayName,
  getPhaseProtocolDisplayName,
  translateApiErrorMessage,
  translateStatus,
  type SupportedLocale,
} from '../utils/locale'
import {
  buildCloseActiveEndFrame,
  formatDurationMs,
  frameToTimestampMs,
  parseResearchFrameQuery,
} from '../utils/researchPhaseUi'

type ResearchWorkspaceMode = 'video_collapsed' | 'split' | 'video_full'

const PLAYER_HEIGHT_STORAGE_KEY = 'research-phase-player-height'
const WORKSPACE_MODE_STORAGE_KEY = 'research-phase-workspace-mode'
const PAUSE_AFTER_PHASE_CHANGE_STORAGE_KEY = 'research-phase-pause-after-change'
const FRAME_PAGE_SIZE = DEFAULT_FRAME_PAGE_SIZE
const MAX_CACHED_FRAME_PAGES = DEFAULT_MAX_CACHED_FRAME_PAGES

const props = defineProps<{ videoId: string }>()

const route = useRoute()
const router = useRouter()
const { locale, t } = useI18n()
const researchVideosStore = useResearchVideosStore()
const researchPhasesStore = useResearchPhasesStore()
const usersStore = useUsersStore()
const {
  protocols,
  currentAnnotationSet,
  segments,
  validation,
  loadingProtocols,
  loadingAnnotationSet,
  saving,
  validating,
  submitting,
  exporting,
  saveState,
  errorMessage,
  conflictState,
  isReadOnly,
  exportKind,
} = storeToRefs(researchPhasesStore)
const { currentUsername } = storeToRefs(usersStore)

const videoRef = ref<HTMLVideoElement | null>(null)
const splitPaneRef = ref<HTMLElement | null>(null)
const gotoFrameInputRef = ref<HTMLInputElement | null>(null)
const timelineRef = ref<InstanceType<typeof PhaseTimeline> | null>(null)
const workspaceVideo = shallowRef<ResearchVideoWorkspaceDetail | null>(null)
const framePages = shallowReactive(new Map<number, readonly ResearchVideoFrame[]>())
const loadingFramePages = shallowReactive(new Map<number, Promise<void>>())
const framePageAccessOrder = shallowReactive(new Map<number, number>())
const framePageCacheState: FramePageCacheState<ResearchVideoFrame> = {
  pages: framePages,
  loadingPages: loadingFramePages,
  pageAccessOrder: framePageAccessOrder,
  accessSequence: 0,
}
const selectedFrameIndex = ref(0)
const selectedSegmentId = ref<number | null>(null)
const currentFrameLoading = ref(false)
const isPlaying = ref(false)
const currentVideoTimeMs = ref(0)
const gotoFrameInput = ref('')
const gotoFrameError = ref('')
const gotoFrameFocused = ref(false)
const isJumpingToFrame = ref(false)
const phasePageError = ref('')
const pauseAfterPhaseChange = ref(false)
const showFrameList = ref(true)
const showSidebarDrawer = ref(false)
const showInspectorDrawer = ref(false)
const showConflictDialog = ref(false)
const viewportHeight = ref(typeof window === 'undefined' ? 900 : window.innerHeight)
const viewportWidth = ref(typeof window === 'undefined' ? 1440 : window.innerWidth)
const playerPaneHeight = ref(280)
const workspaceMode = ref<ResearchWorkspaceMode>('split')
const isResizingPlayer = ref(false)
const playerResizeStartY = ref(0)
const playerResizeStartHeight = ref(0)

let videoLoadGeneration = 0
let frameNavigationSequence = 0
let suppressFrameQueryWatch = false

const video = computed(() => workspaceVideo.value)
useVideoPlaybackRate(videoRef, computed(() => video.value?.file_url ?? null))
const currentLocale = computed(() => locale.value as SupportedLocale)
const totalFrames = computed(() => video.value?.frame_count ?? 0)
const currentFrame = computed(() => getFrameAt(selectedFrameIndex.value) ?? null)
const currentFrameNumber = computed(() => totalFrames.value > 0 ? selectedFrameIndex.value + 1 : 0)
const isFirstFrame = computed(() => selectedFrameIndex.value <= 0)
const isLastFrame = computed(() => selectedFrameIndex.value >= Math.max(totalFrames.value - 1, 0))
const activeProtocolChoices = computed(() => protocols.value.filter((protocol) => protocol.status === 'active'))
const protocolLabels = computed<ResearchPhaseLabel[]>(() => currentAnnotationSet.value?.protocol.labels ?? [])
const activeLabels = computed(() => protocolLabels.value.filter((label) => label.is_active))
const selectedSegment = computed(() => segments.value.find((segment) => segment.id === selectedSegmentId.value) ?? null)
const currentFrameSegment = computed(() => findSegmentAtFrame(segments.value, selectedFrameIndex.value))
const openSegment = computed(() => segments.value.find((segment) => segment.end_frame_exclusive === null) ?? null)
const activePhaseLabelId = computed(() => currentFrameSegment.value?.phase_label_id ?? openSegment.value?.phase_label_id ?? null)
const currentPhaseName = computed(() => currentFrameSegment.value
  ? getPhaseLabelDisplayName(currentFrameSegment.value.phase_label, currentLocale.value)
  : t('phaseAnnotation.unlabeled'))
const compactVideoTimeText = computed(() => formatTimestamp(currentVideoTimeMs.value))
const totalVideoTimeText = computed(() => formatTimestamp(video.value?.duration_ms ?? 0))
const currentFrameTimeText = computed(() => formatTimestamp(currentFrame.value?.timestamp_ms ?? currentVideoTimeMs.value))
const currentFrameStatusText = computed(() => {
  if (!currentFrame.value && totalFrames.value > 0) {
    return `${t('common.loadingFrame')} ${currentFrameNumber.value} / ${totalFrames.value}`
  }
  if (!currentFrame.value) {
    return t('common.noFrameSelected')
  }
  return `${t('common.frame')} ${currentFrameNumber.value} / ${totalFrames.value} · ${currentFrameTimeText.value}`
})
const qcSummaryText = computed(() => {
  if (!validation.value) {
    return t('phaseAnnotation.validationPending')
  }
  return `${t('phaseAnnotation.errors')} ${validation.value.issue_counts.error} · ${t('phaseAnnotation.warnings')} ${validation.value.issue_counts.warning} · ${t('phaseAnnotation.coverage')} ${validation.value.closed_coverage_percent.toFixed(2)}%`
})
const saveStateLabel = computed(() => {
  if (isReadOnly.value) {
    return t('status.readonly')
  }
  if (saveState.value === 'saving') {
    return t('status.saving')
  }
  if (saveState.value === 'saved') {
    return t('status.saved')
  }
  if (saveState.value === 'conflict') {
    return t('status.conflict')
  }
  if (saveState.value === 'error') {
    return t('status.failed')
  }
  return t('status.idle')
})
const currentProtocolName = computed(() => (
  currentAnnotationSet.value
    ? getPhaseProtocolDisplayName(
      {
        name: currentAnnotationSet.value.protocol_name,
        is_default: currentAnnotationSet.value.protocol.is_default,
      },
      currentLocale.value,
    )
    : ''
))
const isCompactLayout = computed(() => viewportWidth.value <= 980)
const isNarrowLayout = computed(() => viewportWidth.value <= 1200)
const isPlayerCollapsed = computed(() => workspaceMode.value === 'video_collapsed')
const isVideoFullWorkspace = computed(() => workspaceMode.value === 'video_full')
const splitHandleSize = computed(() => DEFAULT_PLAYER_SPLIT_HANDLE_HEIGHT)
const playerHeightBounds = computed(() => getResearchPlayerHeightBounds({
  viewportHeight: viewportHeight.value,
  workspaceHeight: getWorkspaceHeight(),
  splitHandleHeight: splitHandleSize.value,
}))
const researchSplitStyle = computed(() => ({
  '--research-player-height': `${playerPaneHeight.value}px`,
  '--research-player-min-height': `${playerHeightBounds.value.minPlayerHeight}px`,
  '--research-split-handle-height': `${splitHandleSize.value}px`,
}))
const selectedSegmentIndex = computed(() => (
  selectedSegment.value ? segments.value.findIndex((segment) => segment.id === selectedSegment.value?.id) : -1
))
const previousSegment = computed(() => (
  selectedSegmentIndex.value > 0 ? segments.value[selectedSegmentIndex.value - 1] : null
))
const nextSegment = computed(() => (
  selectedSegmentIndex.value >= 0 && selectedSegmentIndex.value < segments.value.length - 1
    ? segments.value[selectedSegmentIndex.value + 1]
    : null
))
const canMergePrevious = computed(() => Boolean(
  selectedSegment.value
  && previousSegment.value
  && previousSegment.value.end_frame_exclusive !== null
  && previousSegment.value.end_frame_exclusive === selectedSegment.value.start_frame
  && previousSegment.value.phase_label_id === selectedSegment.value.phase_label_id,
))
const canMergeNext = computed(() => Boolean(
  selectedSegment.value
  && selectedSegment.value.end_frame_exclusive !== null
  && nextSegment.value
  && selectedSegment.value.end_frame_exclusive === nextSegment.value.start_frame
  && nextSegment.value.phase_label_id === selectedSegment.value.phase_label_id,
))
const showVideoEndCloseHint = computed(() => Boolean(
  openSegment.value
  && totalFrames.value > 0
  && selectedFrameIndex.value >= totalFrames.value - 1,
))

onMounted(async () => {
  restoreLayoutPreferences()
  restorePauseAfterPhaseChangePreference()
  window.addEventListener('resize', handleViewportResize)
  window.addEventListener('keydown', handleLabelShortcutKeydown)
  await loadPhaseWorkspace()
})

onBeforeUnmount(() => {
  videoLoadGeneration += 1
  window.removeEventListener('resize', handleViewportResize)
  window.removeEventListener('pointermove', handlePlayerResizeMove)
  window.removeEventListener('pointerup', stopPlayerResize)
  window.removeEventListener('pointercancel', stopPlayerResize)
  window.removeEventListener('keydown', handleLabelShortcutKeydown)
  researchPhasesStore.clearVideoState()
})

watch(
  () => props.videoId,
  () => {
    void loadPhaseWorkspace()
  },
)

watch(
  () => conflictState.value,
  (nextValue) => {
    showConflictDialog.value = Boolean(nextValue)
  },
)

watch(
  () => selectedFrameIndex.value,
  async (nextFrameIndex) => {
    if (!gotoFrameFocused.value) {
      gotoFrameInput.value = totalFrames.value > 0 ? String(nextFrameIndex + 1) : ''
      gotoFrameError.value = ''
    }
    if (suppressFrameQueryWatch) {
      return
    }
    const currentQueryValue = Array.isArray(route.query.frame) ? route.query.frame[0] : route.query.frame
    if (String(currentQueryValue ?? '') === String(nextFrameIndex)) {
      return
    }
    suppressFrameQueryWatch = true
    try {
      await router.replace({
        query: {
          ...route.query,
          frame: String(nextFrameIndex),
        },
      })
    } finally {
      suppressFrameQueryWatch = false
    }
  },
)

watch(
  () => route.query.frame,
  (nextValue) => {
    if (suppressFrameQueryWatch || totalFrames.value <= 0) {
      return
    }
    const targetFrameIndex = parseResearchFrameQuery(nextValue, totalFrames.value)
    if (targetFrameIndex !== selectedFrameIndex.value) {
      void goToFrame(targetFrameIndex, { syncVideo: true })
    }
  },
)

async function loadPhaseWorkspace() {
  const generation = ++videoLoadGeneration
  const videoId = Number(props.videoId)
  phasePageError.value = ''
  selectedSegmentId.value = null
  workspaceVideo.value = null
  isPlaying.value = false
  currentVideoTimeMs.value = 0
  clearFramePageState()
  researchPhasesStore.startVideoSession(videoId)

  const workspace = await researchVideosStore.fetchVideoWorkspace(videoId)
  if (!isCurrentVideoLoadGeneration(generation)) {
    return
  }
  workspaceVideo.value = workspace
  if (!workspace) {
    phasePageError.value = translateApiErrorMessage(researchVideosStore.error, t) || t('phaseAnnotation.workspaceRequestFailed')
    return
  }

  selectedFrameIndex.value = parseResearchFrameQuery(route.query.frame, workspace.frame_count)
  await ensureFrameLoaded(selectedFrameIndex.value, { generation, prefetchAdjacent: false })
  if (!isCurrentVideoLoadGeneration(generation)) {
    return
  }

  const protocolResult = await researchPhasesStore.fetchProtocols()
  if (!isCurrentVideoLoadGeneration(generation)) {
    return
  }
  if (!protocolResult.ok) {
    phasePageError.value = protocolResult.error.message
    return
  }

  const selectedProtocol = activeProtocolChoices.value.find((protocol) => protocol.is_default)
    ?? activeProtocolChoices.value[0]
  if (!selectedProtocol) {
    phasePageError.value = t('errors.noActivePhaseProtocol')
    return
  }

  await researchPhasesStore.fetchVideoAnnotationSets(videoId)
  const createResult = await researchPhasesStore.getOrCreateAnnotationSet(
    videoId,
    selectedProtocol.id,
    currentUsername.value,
  )
  if (!isCurrentVideoLoadGeneration(generation)) {
    return
  }
  if (!createResult.ok) {
    phasePageError.value = createResult.error.message
    return
  }

  if (createResult.data.created) {
    ElMessage.success(t('phaseAnnotation.setCreated'))
  }

  const validateResult = await researchPhasesStore.validateAnnotationSet()
  if (!isCurrentVideoLoadGeneration(generation)) {
    return
  }
  if (!validateResult.ok) {
    phasePageError.value = validateResult.error.message
    return
  }

  await nextTick()
  syncVideoToCurrentFrame()
}

function clearFramePageState() {
  resetFramePageCache(framePageCacheState)
}

function getFrameAt(frameIndex: number): ResearchVideoFrame | undefined {
  return getFrameAtFromPages(framePages, frameIndex, totalFrames.value, FRAME_PAGE_SIZE)
}

function getWorkspaceHeight() {
  return splitPaneRef.value?.clientHeight ?? Math.max(420, viewportHeight.value - 360)
}

function clampPlayerHeight(nextHeight: number) {
  return clampResearchPlayerHeight(nextHeight, {
    viewportHeight: viewportHeight.value,
    workspaceHeight: getWorkspaceHeight(),
    splitHandleHeight: splitHandleSize.value,
  })
}

function restoreLayoutPreferences() {
  const storedMode = window.localStorage.getItem(WORKSPACE_MODE_STORAGE_KEY)
  if (storedMode === 'video_collapsed' || storedMode === 'split' || storedMode === 'video_full') {
    workspaceMode.value = storedMode
  }
  const storedHeight = Number.parseInt(window.localStorage.getItem(PLAYER_HEIGHT_STORAGE_KEY) ?? '', 10)
  playerPaneHeight.value = Number.isFinite(storedHeight)
    ? clampPlayerHeight(storedHeight)
    : getDefaultResearchPlayerHeight({
      viewportHeight: viewportHeight.value,
      workspaceHeight: getWorkspaceHeight(),
      splitHandleHeight: splitHandleSize.value,
    })
}

function restorePauseAfterPhaseChangePreference() {
  pauseAfterPhaseChange.value = window.localStorage.getItem(PAUSE_AFTER_PHASE_CHANGE_STORAGE_KEY) === 'true'
}

function persistLayoutPreferences() {
  window.localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, workspaceMode.value)
  window.localStorage.setItem(PLAYER_HEIGHT_STORAGE_KEY, String(playerPaneHeight.value))
}

function persistPauseAfterPhaseChangePreference() {
  window.localStorage.setItem(PAUSE_AFTER_PHASE_CHANGE_STORAGE_KEY, String(pauseAfterPhaseChange.value))
}

function handleViewportResize() {
  viewportHeight.value = window.innerHeight
  viewportWidth.value = window.innerWidth
  if (workspaceMode.value === 'split') {
    playerPaneHeight.value = clampPlayerHeight(playerPaneHeight.value)
  }
}

async function ensureFramePageLoaded(
  pageIndex: number,
  options: {
    currentPageIndex?: number
    generation?: number
    prefetchAdjacent?: boolean
  } = {},
) {
  const generation = options.generation ?? videoLoadGeneration
  if (!video.value || !isCurrentVideoLoadGeneration(generation)) {
    return
  }
  await ensureFramePageLoadedInCache({
    state: framePageCacheState,
    pageIndex,
    totalCount: totalFrames.value,
    generation,
    isCurrentGeneration: isCurrentVideoLoadGeneration,
    loadPage: async ({ generation: requestGeneration, offset, limit }) => {
      if (!isCurrentVideoLoadGeneration(requestGeneration)) {
        return null
      }
      const page = await researchVideosStore.fetchVideoFramesPage(Number(props.videoId), { offset, limit })
      if (!isCurrentVideoLoadGeneration(requestGeneration)) {
        return null
      }
      return page?.items ?? null
    },
    currentPageIndex: options.currentPageIndex ?? pageIndex,
    maxCachedPages: MAX_CACHED_FRAME_PAGES,
    preservedPageIndices: [getFramePageIndex(selectedFrameIndex.value, FRAME_PAGE_SIZE)],
    pageSize: FRAME_PAGE_SIZE,
  })
}

async function ensureFrameLoaded(
  frameIndex: number,
  options: {
    generation?: number
    prefetchAdjacent?: boolean
  } = {},
) {
  await ensureFramePageLoaded(getFramePageIndex(frameIndex, FRAME_PAGE_SIZE), {
    currentPageIndex: getFramePageIndex(frameIndex, FRAME_PAGE_SIZE),
    generation: options.generation,
    prefetchAdjacent: options.prefetchAdjacent,
  })
  return getFrameAt(frameIndex)
}

function requestFrameRange(startIndex: number, endIndex: number) {
  for (const pageIndex of getFramePageIndicesForRange(startIndex, endIndex, totalFrames.value, FRAME_PAGE_SIZE)) {
    void ensureFramePageLoaded(pageIndex, {
      currentPageIndex: getFramePageIndex(selectedFrameIndex.value, FRAME_PAGE_SIZE),
      generation: videoLoadGeneration,
      prefetchAdjacent: false,
    })
  }
}

function isCurrentVideoLoadGeneration(generation: number) {
  return generation === videoLoadGeneration
}

function getFrameTimeSeconds(frame: Pick<ResearchVideoFrame, 'frame_index' | 'timestamp_ms'>) {
  if (Number.isFinite(frame.timestamp_ms)) {
    return frame.timestamp_ms / 1000
  }
  if (video.value?.fps) {
    return frame.frame_index / video.value.fps
  }
  return 0
}

async function goToFrame(index: number, options: { syncVideo: boolean } = { syncVideo: true }) {
  if (index < 0 || index >= totalFrames.value) {
    return false
  }
  if (index === selectedFrameIndex.value && currentFrame.value) {
    if (options.syncVideo) {
      syncVideoToCurrentFrame()
    }
    return true
  }

  const generation = videoLoadGeneration
  const sequence = ++frameNavigationSequence
  selectedFrameIndex.value = index
  currentFrameLoading.value = true
  const frame = await ensureFrameLoaded(index, { generation, prefetchAdjacent: true })
  if (!frame || sequence !== frameNavigationSequence || !isCurrentVideoLoadGeneration(generation)) {
    currentFrameLoading.value = false
    return false
  }
  currentFrameLoading.value = false
  currentVideoTimeMs.value = frame.timestamp_ms
  if (options.syncVideo) {
    syncVideoToCurrentFrame()
  }
  return true
}

function syncVideoToCurrentFrame() {
  if (!videoRef.value || !currentFrame.value) {
    return
  }
  const nextTime = getFrameTimeSeconds(currentFrame.value)
  if (Number.isFinite(nextTime)) {
    videoRef.value.currentTime = nextTime
  }
}

function syncFrameFromVideo() {
  if (!videoRef.value || !video.value?.fps || totalFrames.value <= 0) {
    return
  }
  const nextFrameIndex = Math.min(
    Math.max(Math.round(videoRef.value.currentTime * video.value.fps), 0),
    totalFrames.value - 1,
  )
  if (nextFrameIndex !== selectedFrameIndex.value) {
    selectedFrameIndex.value = nextFrameIndex
    void ensureFrameLoaded(nextFrameIndex, { generation: videoLoadGeneration, prefetchAdjacent: true })
  }
  currentVideoTimeMs.value = Math.round(videoRef.value.currentTime * 1000)
}

function togglePlayback() {
  if (!videoRef.value) {
    return
  }
  if (videoRef.value.paused) {
    void videoRef.value.play()
    return
  }
  videoRef.value.pause()
}

function onVideoPlay() {
  isPlaying.value = true
}

function onVideoPause() {
  isPlaying.value = false
  syncFrameFromVideo()
}

function onVideoLoadedMetadata() {
  syncVideoToCurrentFrame()
}

function onVideoTimeUpdate() {
  syncFrameFromVideo()
}

function clearGoToFrameError() {
  gotoFrameError.value = ''
}

function handleGoToFrameFocus() {
  gotoFrameFocused.value = true
}

function handleGoToFrameBlur() {
  gotoFrameFocused.value = false
}

function resetGoToFrameInput() {
  gotoFrameError.value = ''
  gotoFrameInput.value = totalFrames.value > 0 ? String(selectedFrameIndex.value + 1) : ''
  gotoFrameInputRef.value?.blur()
}

function parseGoToFrameInput() {
  if (totalFrames.value <= 0) {
    const message = t('phaseAnnotation.framesStillLoading')
    gotoFrameError.value = message
    ElMessage.warning(message)
    return null
  }
  const normalized = gotoFrameInput.value.trim()
  if (!/^\d+$/.test(normalized)) {
    const message = `Frame number must be between 1 and ${totalFrames.value}.`
    gotoFrameError.value = message
    ElMessage.warning(message)
    return null
  }
  const frameNumber = Number.parseInt(normalized, 10)
  if (!Number.isInteger(frameNumber) || frameNumber < 1 || frameNumber > totalFrames.value) {
    const message = `Frame number must be between 1 and ${totalFrames.value}.`
    gotoFrameError.value = message
    ElMessage.warning(message)
    return null
  }
  return frameNumber - 1
}

async function submitGoToFrame() {
  if (isJumpingToFrame.value) {
    return
  }
  const targetFrameIndex = parseGoToFrameInput()
  if (targetFrameIndex === null) {
    return
  }
  isJumpingToFrame.value = true
  try {
    await goToFrame(targetFrameIndex, { syncVideo: true })
  } finally {
    isJumpingToFrame.value = false
  }
}

function goPrevious() {
  void goToFrame(selectedFrameIndex.value - 1, { syncVideo: true })
}

function goNext() {
  void goToFrame(selectedFrameIndex.value + 1, { syncVideo: true })
}

function togglePlayerCollapsed() {
  workspaceMode.value = workspaceMode.value === 'video_collapsed' ? 'split' : 'video_collapsed'
  persistLayoutPreferences()
}

function togglePlayerMaximized() {
  workspaceMode.value = workspaceMode.value === 'video_full' ? 'split' : 'video_full'
  persistLayoutPreferences()
}

function startPlayerResize(event: PointerEvent) {
  if (workspaceMode.value !== 'split') {
    return
  }
  isResizingPlayer.value = true
  playerResizeStartY.value = event.clientY
  playerResizeStartHeight.value = playerPaneHeight.value
  window.addEventListener('pointermove', handlePlayerResizeMove)
  window.addEventListener('pointerup', stopPlayerResize)
  window.addEventListener('pointercancel', stopPlayerResize)
}

function handlePlayerResizeMove(event: PointerEvent) {
  if (!isResizingPlayer.value) {
    return
  }
  const delta = event.clientY - playerResizeStartY.value
  playerPaneHeight.value = clampPlayerHeight(playerResizeStartHeight.value + delta)
}

function stopPlayerResize() {
  if (!isResizingPlayer.value) {
    return
  }
  isResizingPlayer.value = false
  persistLayoutPreferences()
  window.removeEventListener('pointermove', handlePlayerResizeMove)
  window.removeEventListener('pointerup', stopPlayerResize)
  window.removeEventListener('pointercancel', stopPlayerResize)
}

function handleLabelShortcutKeydown(event: KeyboardEvent) {
  if (researchPhasesStore.isReadOnly || saving.value || saveState.value === 'conflict') {
    return
  }
  if (event.ctrlKey || event.altKey || event.metaKey) {
    return
  }
  const target = event.target as HTMLElement | null
  if (
    target
    && (
      target.tagName === 'INPUT'
      || target.tagName === 'TEXTAREA'
      || target.tagName === 'SELECT'
      || target.isContentEditable
    )
  ) {
    return
  }
  const pressedKey = event.key.toLowerCase()
  for (const label of activeLabels.value) {
    if (!label.shortcut || label.shortcut.toLowerCase() !== pressedKey) {
      continue
    }
    event.preventDefault()
    void handleTransition(label)
    return
  }
}

async function afterMutation(
  result: PhaseActionResult<ResearchPhaseMutationResponse>,
  options: {
    message?: string
    nextSelectedSegmentId?: number | null
    scrollFrame?: number | null
  } = {},
) {
  if (!result.ok) {
    if (result.error.kind !== 'conflict') {
      ElMessage.error(result.error.message)
    }
    return false
  }
  const restoreTarget = options.nextSelectedSegmentId ?? selectedSegmentId.value
  selectedSegmentId.value = restoreSelectedSegmentId(restoreTarget, researchPhasesStore.segments)
  await researchPhasesStore.validateAnnotationSet()
  if (options.scrollFrame !== undefined && options.scrollFrame !== null) {
    await nextTick()
    timelineRef.value?.scrollToFrame(options.scrollFrame)
  }
  if (options.message) {
    ElMessage.success(options.message)
  }
  return true
}

async function handleTransition(label: ResearchPhaseLabel) {
  const result = await researchPhasesStore.transitionPhase(label.id, selectedFrameIndex.value)
  if (!result.ok) {
    if (result.error.kind !== 'conflict') {
      ElMessage.error(result.error.message)
    }
    return
  }
  const createdSegmentId = result.data.created_segment_ids.length > 0
    ? result.data.created_segment_ids[result.data.created_segment_ids.length - 1]
    : undefined
  const nextSelectedSegmentId = createdSegmentId
    ?? findSegmentAtFrame(researchPhasesStore.segments, selectedFrameIndex.value)?.id
    ?? selectedSegmentId.value
  selectedSegmentId.value = nextSelectedSegmentId ?? null
  await researchPhasesStore.validateAnnotationSet()
  if (pauseAfterPhaseChange.value && videoRef.value && !videoRef.value.paused) {
    videoRef.value.pause()
  }
  if (result.data.action === 'unchanged') {
    ElMessage.info(t('phaseAnnotation.alreadyActive'))
  } else {
    ElMessage.success(t('phaseAnnotation.transitioned'))
  }
}

async function handleCloseCurrentPhase(closeAtVideoEnd = false) {
  const endFrameExclusive = closeAtVideoEnd
    ? totalFrames.value
    : buildCloseActiveEndFrame(selectedFrameIndex.value, totalFrames.value)
  await afterMutation(
    await researchPhasesStore.closeActiveSegment(endFrameExclusive),
    {
      message: closeAtVideoEnd ? t('phaseAnnotation.activeClosedAtEnd') : t('phaseAnnotation.activeClosed'),
      nextSelectedSegmentId: openSegment.value?.id ?? selectedSegmentId.value,
    },
  )
}

async function handleSegmentPatch(segmentId: number, patch: Record<string, unknown>) {
  await afterMutation(
    await researchPhasesStore.updateSegment(segmentId, patch),
    {
      nextSelectedSegmentId: segmentId,
    },
  )
}

async function handleDeleteSegment(segmentId: number) {
  const currentIndex = segments.value.findIndex((segment) => segment.id === segmentId)
  const fallbackSelection = segments.value[currentIndex + 1]?.id ?? segments.value[currentIndex - 1]?.id ?? null
  try {
    await ElMessageBox.confirm(
      t('phaseAnnotation.deleteConfirm'),
      t('phaseAnnotation.deleteSegment'),
      {
        type: 'warning',
      },
    )
  } catch {
    return
  }
  const deleted = await researchPhasesStore.deleteSegment(segmentId)
  if (await afterMutation(deleted, { message: t('phaseAnnotation.segmentDeleted'), nextSelectedSegmentId: fallbackSelection })) {
    selectedSegmentId.value = restoreSelectedSegmentId(fallbackSelection, researchPhasesStore.segments)
  }
}

async function handleSplitSegment(segmentId: number) {
  try {
    await ElMessageBox.confirm(
      `Split this phase at frame ${selectedFrameIndex.value + 1}?`,
      t('phaseAnnotation.splitTitle'),
      { type: 'warning' },
    )
  } catch {
    return
  }
  const result = await researchPhasesStore.splitSegment(segmentId, selectedFrameIndex.value)
  const nextSelectedSegmentId = result.ok ? (result.data.created_segment_ids[0] ?? segmentId) : segmentId
  await afterMutation(result, {
    message: t('phaseAnnotation.segmentSplit'),
    nextSelectedSegmentId,
    scrollFrame: selectedFrameIndex.value,
  })
}

async function handleMergeSegments(leftSegmentId: number, rightSegmentId: number) {
  await afterMutation(
    await researchPhasesStore.mergeSegments(leftSegmentId, rightSegmentId),
    {
      message: t('phaseAnnotation.segmentsMerged'),
      nextSelectedSegmentId: leftSegmentId,
    },
  )
}

async function handleValidate() {
  const result = await researchPhasesStore.validateAnnotationSet()
  if (!result.ok) {
    ElMessage.error(result.error.message)
    return
  }
  ElMessage.success(t('phaseAnnotation.validationRefreshed'))
}

async function handleGoToIssue(issue: ResearchPhaseValidationIssue) {
  if (issue.segment_id !== null) {
    selectedSegmentId.value = issue.segment_id
    await nextTick()
    timelineRef.value?.scrollToSelectedSegment()
  }
  if (issue.frame_start !== null) {
    await goToFrame(issue.frame_start, { syncVideo: true })
    await nextTick()
    timelineRef.value?.scrollToFrame(issue.frame_start)
  }
}

async function handleMergeIssue(issue: ResearchPhaseValidationIssue) {
  if (issue.segment_id === null || issue.related_segment_id === null) {
    return
  }
  await handleMergeSegments(issue.segment_id, issue.related_segment_id)
}

async function handleSubmit() {
  const validationResult = await researchPhasesStore.validateAnnotationSet()
  if (!validationResult.ok) {
    ElMessage.error(validationResult.error.message)
    return
  }
  if (!validationResult.data.is_valid) {
    ElMessage.error(t('phaseAnnotation.resolveErrorsBeforeSubmit'))
    return
  }

  const submitResult = await researchPhasesStore.submitAnnotationSet(false)
  if (submitResult.ok) {
    ElMessage.success(t('phaseAnnotation.submitted'))
    return
  }
  if (submitResult.error.kind === 'warning_confirmation') {
    try {
      await ElMessageBox.confirm(
        `This annotation set has ${submitResult.error.validation?.issue_counts.warning ?? 0} warnings.\nSubmit anyway?`,
        t('phaseAnnotation.confirmWarnings'),
        {
          type: 'warning',
        },
      )
    } catch {
      return
    }
    const confirmedResult = await researchPhasesStore.submitAnnotationSet(true)
    if (!confirmedResult.ok) {
      if (confirmedResult.error.kind !== 'conflict') {
        ElMessage.error(confirmedResult.error.message)
      }
      return
    }
    ElMessage.success(t('phaseAnnotation.submitted'))
    return
  }
  if (submitResult.error.kind !== 'conflict') {
    ElMessage.error(submitResult.error.message)
  }
}

async function handleReopen() {
  try {
    await ElMessageBox.confirm(
      t('phaseAnnotation.reopenConfirm'),
      t('phaseAnnotation.reopenTitle'),
      { type: 'warning' },
    )
  } catch {
    return
  }
  const result = await researchPhasesStore.reopenAnnotationSet()
  if (!result.ok) {
    if (result.error.kind !== 'conflict') {
      ElMessage.error(result.error.message)
    }
    return
  }
  await researchPhasesStore.validateAnnotationSet()
  ElMessage.success(t('phaseAnnotation.reopened'))
}

async function handleExport(command: 'json' | 'segments' | 'framewise') {
  if (command === 'framewise') {
    ElMessage.info(t('phaseAnnotation.preparingFramewiseCsv'))
  }
  const result = command === 'json'
    ? await researchPhasesStore.downloadJson()
    : command === 'segments'
      ? await researchPhasesStore.downloadSegmentCsv()
      : await researchPhasesStore.downloadFramewiseCsv()
  if (!result.ok) {
    ElMessage.error(result.error.message)
    return
  }
  if (command === 'framewise' && (result.data.validationErrors > 0 || result.data.validationWarnings > 0)) {
    ElMessage.info(`Frame-wise export includes validation headers: ${result.data.validationErrors} errors, ${result.data.validationWarnings} warnings.`)
    return
  }
  ElMessage.success(`Exported ${result.data.filename}.`)
}

async function reloadLatestAfterConflict() {
  const annotationSetId = currentAnnotationSet.value?.id
  if (!annotationSetId) {
    return
  }
  const previousSelectedSegmentId = selectedSegmentId.value
  const preservedFrameIndex = selectedFrameIndex.value
  const fetchResult = await researchPhasesStore.fetchAnnotationSet(annotationSetId)
  if (!fetchResult.ok) {
    ElMessage.error(fetchResult.error.message)
    return
  }
  selectedSegmentId.value = restoreSelectedSegmentId(previousSelectedSegmentId, researchPhasesStore.segments)
  showConflictDialog.value = false
  await researchPhasesStore.validateAnnotationSet()
  await goToFrame(Math.min(preservedFrameIndex, Math.max(totalFrames.value - 1, 0)), { syncVideo: true })
}

function formatTimestamp(timestampMs: number | null | undefined) {
  if (timestampMs === null || timestampMs === undefined || !Number.isFinite(timestampMs)) {
    return '--:--.--'
  }
  const totalSeconds = Math.floor(timestampMs / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  const milliseconds = Math.floor((timestampMs % 1000) / 10)
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(milliseconds).padStart(2, '0')}`
}
</script>

<template>
  <main class="research-phase-page">
    <header class="research-phase-header">
      <div class="research-phase-header-main">
        <router-link to="/research/videos" class="annotate-back">
          <el-icon><Back /></el-icon>
          {{ t('phaseAnnotation.researchVideos') }}
        </router-link>

        <div class="research-phase-title-block">
          <p class="research-phase-eyebrow">{{ t('phaseAnnotation.eyebrow') }}</p>
          <h1 class="research-video-title" :title="video?.name ?? `Video ${videoId}`">
            {{ video?.name ?? `Video ${videoId}` }}
          </h1>
          <p class="research-phase-subtitle">
            {{ currentFrameStatusText }} · {{ t('phaseAnnotation.currentPhase') }} {{ currentPhaseName }}
          </p>
        </div>
      </div>

      <ResearchVideoTaskNav
        :active-task="'phase'"
        :current-frame-index="selectedFrameIndex"
        :video-id="videoId"
      />
    </header>

    <section v-if="phasePageError" class="research-phase-error">
      <strong>{{ phasePageError }}</strong>
      <p>{{ translateApiErrorMessage(errorMessage, t) || t('phaseAnnotation.noAnnotationSet') }}</p>
    </section>

    <section v-else class="research-phase-layout">
      <aside v-if="!isCompactLayout" class="research-phase-sidebar">
        <div class="research-phase-card">
          <p class="research-phase-card-eyebrow">{{ t('phaseAnnotation.protocol') }}</p>
          <strong>{{ currentProtocolName || t('common.loading') }}</strong>
          <span v-if="currentAnnotationSet">v{{ currentAnnotationSet.protocol_version }}</span>
          <span v-else-if="loadingProtocols || loadingAnnotationSet">{{ t('phaseAnnotation.loadingWorkspace') }}</span>
          <span v-else>{{ t('phaseAnnotation.noAnnotationSet') }}</span>
        </div>

        <div class="research-phase-card">
          <p class="research-phase-card-eyebrow">{{ t('phaseAnnotation.annotationSet') }}</p>
          <strong>{{ translateStatus(currentAnnotationSet?.status ?? 'draft', t) }}</strong>
          <span>{{ t('phaseAnnotation.revision') }} {{ currentAnnotationSet?.revision ?? '--' }}</span>
          <span>{{ saveStateLabel }}</span>
          <span v-if="currentAnnotationSet?.submitted_at">Submitted {{ currentAnnotationSet.submitted_at }}</span>
        </div>

        <div class="research-phase-card">
          <div class="research-phase-card-row">
            <p class="research-phase-card-eyebrow">{{ t('phaseAnnotation.phaseLabels') }}</p>
            <label class="research-phase-toggle">
              <input v-model="pauseAfterPhaseChange" type="checkbox" @change="persistPauseAfterPhaseChangePreference" />
              {{ t('phaseAnnotation.pauseAfterChange') }}
            </label>
          </div>
          <div class="research-phase-label-list">
            <button
              v-for="label in activeLabels"
              :key="label.id"
              class="research-phase-label-button"
              :class="{ active: activePhaseLabelId === label.id }"
              :disabled="saving || isReadOnly || saveState === 'conflict'"
              type="button"
              @click="handleTransition(label)"
            >
              <span class="research-phase-label-swatch" :style="{ backgroundColor: label.color }"></span>
              <span>{{ getPhaseLabelDisplayName(label, currentLocale) }}</span>
              <span v-if="label.shortcut" class="research-phase-label-shortcut">{{ label.shortcut }}</span>
            </button>
          </div>

          <div class="research-phase-sidebar-actions">
            <el-button :disabled="saving || isReadOnly || saveState === 'conflict' || !openSegment" @click="handleCloseCurrentPhase(false)">
              {{ t('phaseAnnotation.closeCurrent') }}
            </el-button>
            <el-button :disabled="validating" :loading="validating" @click="handleValidate">
              <el-icon><RefreshRight /></el-icon>
              {{ t('common.validate') }}
            </el-button>
            <el-button
              v-if="currentAnnotationSet?.status === 'draft'"
              type="primary"
              :disabled="submitting || saveState === 'conflict'"
              :loading="submitting"
              @click="handleSubmit"
            >
              {{ t('common.submit') }}
            </el-button>
            <el-button
              v-else-if="currentAnnotationSet?.status === 'submitted'"
              :disabled="submitting || saveState === 'conflict'"
              :loading="submitting"
              @click="handleReopen"
            >
              {{ t('skillAssessment.reopenForEditing') }}
            </el-button>

            <el-dropdown :disabled="exporting || !currentAnnotationSet" @command="handleExport">
              <el-button :loading="exporting">{{ t('common.export') }}</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="json">{{ t('phaseAnnotation.phaseJson') }}</el-dropdown-item>
                  <el-dropdown-item command="segments">{{ t('phaseAnnotation.segmentCsv') }}</el-dropdown-item>
                  <el-dropdown-item command="framewise">{{ t('phaseAnnotation.framewiseCsv') }}</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>

          <p class="research-phase-qc-inline">{{ qcSummaryText }}</p>
        </div>

        <div class="research-phase-card">
          <div class="research-phase-card-row">
            <p class="research-phase-card-eyebrow">{{ t('phaseAnnotation.videoFrames') }}</p>
            <button class="research-phase-link-button" type="button" @click="showFrameList = !showFrameList">
              {{ showFrameList ? t('frameAnnotation.collapse') : t('frameAnnotation.expand') }}
            </button>
          </div>
          <VirtualFrameList
            v-if="showFrameList"
            :total-count="totalFrames"
            :selected-frame-index="selectedFrameIndex"
            :get-frame="getFrameAt"
            @request-range="requestFrameRange"
            @select="goToFrame"
          />
        </div>

        <PhaseValidationPanel
          :current-status="currentAnnotationSet?.status ?? null"
          :validation="validation"
          @go-to-issue="handleGoToIssue"
          @merge-issue="handleMergeIssue"
          @close-at-current="handleCloseCurrentPhase(false)"
          @close-at-video-end="handleCloseCurrentPhase(true)"
        />
      </aside>

      <section class="research-phase-main">
        <div class="research-phase-mobile-actions" v-if="isCompactLayout">
          <el-button @click="showSidebarDrawer = true">{{ t('phaseAnnotation.labelsAndQc') }}</el-button>
          <el-button @click="showInspectorDrawer = true">{{ t('phaseAnnotation.inspector') }}</el-button>
        </div>

        <div class="research-video-workspace">
          <div
            ref="splitPaneRef"
            class="research-video-split"
            :class="{
              'is-player-collapsed': isPlayerCollapsed,
              'is-video-full': isVideoFullWorkspace,
              'is-resizing': isResizingPlayer,
            }"
            :style="researchSplitStyle"
          >
            <section class="research-player-pane" :class="{ 'is-collapsed': isPlayerCollapsed }">
              <div class="research-player-pane-header">
                <div class="research-player-pane-heading">
                  <strong>{{ t('phaseAnnotation.videoPreview') }}</strong>
                  <span>{{ currentFrameStatusText }}</span>
                </div>

                <div class="research-player-pane-actions">
                  <span class="research-video-help-text">
                    {{ t('common.previous') }} / {{ t('common.next') }} / {{ t('common.goTo') }}
                  </span>
                  <button
                    v-if="!isPlayerCollapsed"
                    class="research-player-pane-action"
                    type="button"
                    @click="togglePlayerMaximized"
                  >
                    {{ isVideoFullWorkspace ? t('frameAnnotation.restore') : t('frameAnnotation.maximize') }}
                  </button>
                  <button class="research-player-pane-action" type="button" @click="togglePlayerCollapsed">
                    {{ isPlayerCollapsed ? t('frameAnnotation.expand') : t('frameAnnotation.collapse') }}
                  </button>
                </div>
              </div>

              <div v-if="isPlayerCollapsed" class="research-player-compact-bar">
                <div class="research-player-compact-meta">
                  <strong :title="video?.original_filename ?? video?.name ?? `Video ${videoId}`">
                    {{ video?.original_filename ?? video?.name ?? `Video ${videoId}` }}
                  </strong>
                  <span>{{ compactVideoTimeText }} / {{ totalVideoTimeText }}</span>
                </div>
                <div class="research-player-compact-actions">
                  <VideoPlaybackRateControl compact />
                  <button class="research-player-pane-action" type="button" @click="togglePlayback">
                    {{ isPlaying ? t('frameAnnotation.pause') : t('frameAnnotation.play') }}
                  </button>
                </div>
              </div>

              <div class="research-player-pane-body" :class="{ 'is-visually-collapsed': isPlayerCollapsed }">
                <div class="research-video-container">
                  <video
                    ref="videoRef"
                    class="research-video-element"
                    :src="video?.file_url"
                    preload="metadata"
                    controls
                    @loadedmetadata="onVideoLoadedMetadata"
                    @pause="onVideoPause"
                    @play="onVideoPlay"
                    @timeupdate="onVideoTimeUpdate"
                  ></video>
                </div>
              </div>
            </section>

            <div
              class="research-split-handle"
              :class="{ 'is-hidden': isPlayerCollapsed || isVideoFullWorkspace }"
              @pointerdown.prevent="startPlayerResize"
            >
              <span></span>
            </div>

            <section class="research-annotation-pane research-phase-player-toolbar">
              <div class="research-phase-toolbar">
                <div class="research-phase-toolbar-group">
                  <el-button :disabled="isFirstFrame" @click="goPrevious">{{ t('common.previous') }}</el-button>
                  <el-button :disabled="!video?.file_url" @click="togglePlayback">
                    <el-icon><VideoPause v-if="isPlaying" /><VideoPlay v-else /></el-icon>
                    {{ isPlaying ? t('frameAnnotation.pause') : t('frameAnnotation.play') }}
                  </el-button>
                  <VideoPlaybackRateControl compact />
                  <el-button :disabled="isLastFrame" @click="goNext">{{ t('common.next') }}</el-button>
                  <span class="research-phase-toolbar-meta">{{ currentFrameNumber }} / {{ totalFrames }}</span>
                  <span class="research-phase-toolbar-meta">{{ currentFrameTimeText }}</span>
                </div>

                <div class="research-phase-toolbar-group">
                  <span class="research-phase-goto">
                    <span>{{ t('common.goTo') }}</span>
                    <input
                      ref="gotoFrameInputRef"
                      v-model="gotoFrameInput"
                      :disabled="!totalFrames || isJumpingToFrame"
                      :title="gotoFrameError || t('frameAnnotation.jumpToFrame')"
                      autocomplete="off"
                      inputmode="numeric"
                      type="text"
                      @blur="handleGoToFrameBlur"
                      @focus="handleGoToFrameFocus"
                      @input="clearGoToFrameError"
                      @keydown.enter.prevent="submitGoToFrame"
                      @keydown.esc.prevent="resetGoToFrameInput"
                    />
                    <el-button :disabled="!totalFrames || isJumpingToFrame" :loading="isJumpingToFrame" @click="submitGoToFrame">
                      {{ t('common.go') }}
                    </el-button>
                  </span>
                  <span class="research-phase-toolbar-meta">{{ t('phaseAnnotation.currentPhase') }} {{ currentPhaseName }}</span>
                  <span class="research-phase-toolbar-meta">{{ saveStateLabel }}</span>
                </div>
              </div>

              <div v-if="showVideoEndCloseHint" class="research-phase-banner">
                <span>{{ t('phaseAnnotation.activeSegmentOpen') }}</span>
                <el-button size="small" @click="handleCloseCurrentPhase(true)">{{ t('phaseAnnotation.closeAtVideoEnd') }}</el-button>
              </div>
            </section>
          </div>
        </div>

        <PhaseTimeline
          ref="timelineRef"
          :current-frame-index="selectedFrameIndex"
          :frame-count="totalFrames"
          :readonly="isReadOnly || saveState === 'conflict'"
          :segments="segments"
          :selected-segment-id="selectedSegmentId"
          @seek="goToFrame"
          @select-segment="selectedSegmentId = $event"
          @update-segment-boundary="handleSegmentPatch($event.segmentId, $event.patch)"
        />
      </section>

      <aside v-if="!isCompactLayout" class="research-phase-inspector-column">
        <PhaseSegmentInspector
          :can-merge-next="canMergeNext"
          :can-merge-previous="canMergePrevious"
          :current-frame-index="selectedFrameIndex"
          :fps="video?.fps ?? null"
          :frame-count="totalFrames"
          :labels="protocolLabels"
          :read-only="isReadOnly || saveState === 'conflict'"
          :saving="saving"
          :segment="selectedSegment"
          @delete-segment="handleDeleteSegment"
          @merge-next="nextSegment && handleMergeSegments($event, nextSegment.id)"
          @merge-previous="previousSegment && handleMergeSegments(previousSegment.id, $event)"
          @split-segment="handleSplitSegment"
          @update-segment="handleSegmentPatch($event.segmentId, $event.patch)"
        />
      </aside>
    </section>

    <el-drawer v-model="showSidebarDrawer" :title="t('phaseAnnotation.phaseControls')" size="88%">
      <div class="research-phase-drawer-body">
        <div class="research-phase-card">
          <p class="research-phase-card-eyebrow">{{ t('phaseAnnotation.protocol') }}</p>
          <strong>{{ currentProtocolName || t('common.loading') }}</strong>
          <span v-if="currentAnnotationSet">v{{ currentAnnotationSet.protocol_version }}</span>
        </div>

        <div class="research-phase-card">
          <div class="research-phase-card-row">
            <p class="research-phase-card-eyebrow">{{ t('phaseAnnotation.phaseLabels') }}</p>
            <label class="research-phase-toggle">
              <input v-model="pauseAfterPhaseChange" type="checkbox" @change="persistPauseAfterPhaseChangePreference" />
              {{ t('phaseAnnotation.pauseAfterChange') }}
            </label>
          </div>
          <div class="research-phase-label-list">
            <button
              v-for="label in activeLabels"
              :key="label.id"
              class="research-phase-label-button"
              :class="{ active: activePhaseLabelId === label.id }"
              :disabled="saving || isReadOnly || saveState === 'conflict'"
              type="button"
              @click="handleTransition(label)"
            >
              <span class="research-phase-label-swatch" :style="{ backgroundColor: label.color }"></span>
              <span>{{ getPhaseLabelDisplayName(label, currentLocale) }}</span>
              <span v-if="label.shortcut" class="research-phase-label-shortcut">{{ label.shortcut }}</span>
            </button>
          </div>
        </div>

        <PhaseValidationPanel
          :current-status="currentAnnotationSet?.status ?? null"
          :validation="validation"
          @go-to-issue="handleGoToIssue"
          @merge-issue="handleMergeIssue"
          @close-at-current="handleCloseCurrentPhase(false)"
          @close-at-video-end="handleCloseCurrentPhase(true)"
        />

        <div class="research-phase-card">
          <p class="research-phase-card-eyebrow">{{ t('phaseAnnotation.videoFrames') }}</p>
          <VirtualFrameList
            :total-count="totalFrames"
            :selected-frame-index="selectedFrameIndex"
            :get-frame="getFrameAt"
            @request-range="requestFrameRange"
            @select="goToFrame"
          />
        </div>
      </div>
    </el-drawer>

    <el-drawer v-model="showInspectorDrawer" direction="rtl" :title="t('phaseAnnotation.segmentInspector')" size="88%">
      <PhaseSegmentInspector
        :can-merge-next="canMergeNext"
        :can-merge-previous="canMergePrevious"
        :current-frame-index="selectedFrameIndex"
        :fps="video?.fps ?? null"
        :frame-count="totalFrames"
        :labels="protocolLabels"
        :read-only="isReadOnly || saveState === 'conflict'"
        :saving="saving"
        :segment="selectedSegment"
        @delete-segment="handleDeleteSegment"
        @merge-next="nextSegment && handleMergeSegments($event, nextSegment.id)"
        @merge-previous="previousSegment && handleMergeSegments(previousSegment.id, $event)"
        @split-segment="handleSplitSegment"
        @update-segment="handleSegmentPatch($event.segmentId, $event.patch)"
      />
    </el-drawer>

    <el-dialog
      v-model="showConflictDialog"
      :title="t('phaseAnnotation.conflictTitle')"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :show-close="false"
      width="460px"
    >
      <p>{{ t('phaseAnnotation.conflictBody') }}</p>
      <p v-if="conflictState?.currentRevision !== null">
        {{ t('phaseAnnotation.revision') }}: {{ conflictState?.currentRevision }}
      </p>
      <template #footer>
        <el-button @click="showConflictDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="reloadLatestAfterConflict">{{ t('phaseAnnotation.reloadLatest') }}</el-button>
      </template>
    </el-dialog>
  </main>
</template>

<style scoped>
.research-phase-page {
  display: flex;
  flex-direction: column;
  gap: 1.1rem;
  padding: 1.1rem;
  min-height: 100vh;
  background:
    radial-gradient(circle at top left, rgba(14, 116, 144, 0.18), transparent 38%),
    radial-gradient(circle at top right, rgba(251, 191, 36, 0.08), transparent 28%),
    linear-gradient(180deg, #020617, #0f172a 48%, #111827);
  color: #f8fafc;
}

.research-phase-header,
.research-phase-error,
.research-phase-card,
.research-phase-inspector-column,
.research-phase-main {
  min-width: 0;
}

.research-phase-header {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
  align-items: flex-start;
}

.research-phase-header-main {
  display: flex;
  gap: 1rem;
  align-items: flex-start;
  flex-wrap: wrap;
}

.research-phase-title-block {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.research-phase-eyebrow {
  margin: 0;
  font-size: 0.82rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: rgba(125, 211, 252, 0.86);
}

.research-phase-subtitle {
  margin: 0;
  color: rgba(148, 163, 184, 0.92);
}

.research-phase-layout {
  display: grid;
  grid-template-columns: minmax(280px, 320px) minmax(0, 1fr) minmax(320px, 380px);
  gap: 1rem;
  min-height: 0;
}

.research-phase-sidebar,
.research-phase-inspector-column {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-height: 0;
}

.research-phase-main {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-width: 0;
}

.research-phase-card,
.research-phase-error {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  padding: 1rem;
  border-radius: 1rem;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.84);
}

.research-phase-card strong,
.research-phase-error strong {
  color: #f8fafc;
}

.research-phase-card span,
.research-phase-error p,
.research-phase-qc-inline {
  color: rgba(148, 163, 184, 0.92);
}

.research-phase-card-eyebrow {
  margin: 0;
  font-size: 0.78rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(125, 211, 252, 0.84);
}

.research-phase-card-row {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  align-items: center;
  flex-wrap: wrap;
}

.research-phase-toggle {
  display: inline-flex;
  gap: 0.45rem;
  align-items: center;
  font-size: 0.84rem;
  color: rgba(226, 232, 240, 0.92);
}

.research-phase-label-list {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.research-phase-label-button {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.78rem 0.85rem;
  border-radius: 0.9rem;
  border: 1px solid rgba(148, 163, 184, 0.2);
  background: rgba(30, 41, 59, 0.78);
  color: #e2e8f0;
  text-align: left;
}

.research-phase-label-button.active {
  border-color: rgba(34, 211, 238, 0.46);
  background: rgba(8, 47, 73, 0.76);
}

.research-phase-label-button:disabled {
  opacity: 0.55;
}

.research-phase-label-swatch {
  width: 14px;
  height: 14px;
  border-radius: 999px;
  flex: 0 0 auto;
}

.research-phase-label-shortcut {
  margin-left: auto;
  padding: 0.2rem 0.45rem;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.72);
  font-size: 0.78rem;
}

.research-phase-sidebar-actions,
.research-phase-mobile-actions,
.research-phase-toolbar,
.research-phase-toolbar-group,
.research-phase-goto,
.research-phase-drawer-body {
  display: flex;
}

.research-phase-sidebar-actions,
.research-phase-mobile-actions,
.research-phase-drawer-body {
  flex-direction: column;
  gap: 0.7rem;
}

.research-phase-mobile-actions {
  display: none;
  flex-direction: row;
}

.research-phase-link-button {
  border: 0;
  background: transparent;
  color: #7dd3fc;
  cursor: pointer;
}

.research-phase-player-toolbar {
  gap: 0.75rem;
}

.research-phase-toolbar {
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
  padding: 0.2rem 0;
}

.research-phase-toolbar-group {
  gap: 0.7rem;
  align-items: center;
  flex-wrap: wrap;
}

.research-phase-toolbar-meta {
  color: rgba(148, 163, 184, 0.92);
  font-size: 0.88rem;
}

.research-phase-goto {
  gap: 0.55rem;
  align-items: center;
}

.research-phase-goto input {
  width: 90px;
  padding: 0.55rem 0.65rem;
  border-radius: 0.75rem;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(30, 41, 59, 0.82);
  color: #f8fafc;
}

.research-phase-banner {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
  padding: 0.75rem 0.9rem;
  border-radius: 0.85rem;
  background: rgba(120, 53, 15, 0.42);
  color: #fde68a;
}

@media (max-width: 1200px) {
  .research-phase-layout {
    grid-template-columns: minmax(260px, 300px) minmax(0, 1fr);
  }

  .research-phase-inspector-column {
    display: none;
  }

  .research-phase-mobile-actions {
    display: flex;
  }
}

@media (max-width: 980px) {
  .research-phase-layout {
    grid-template-columns: 1fr;
  }

  .research-phase-sidebar {
    display: none;
  }

  .research-phase-mobile-actions {
    display: flex;
  }
}

@media (max-width: 720px) {
  .research-phase-page {
    padding: 0.8rem;
  }

  .research-phase-toolbar {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
