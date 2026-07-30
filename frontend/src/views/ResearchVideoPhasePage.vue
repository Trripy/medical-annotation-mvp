<script setup lang="ts">
import { RefreshRight, VideoPause, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowReactive, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import VirtualFrameList from '../components/VirtualFrameList.vue'
import PhaseSegmentInspector from '../components/research/PhaseSegmentInspector.vue'
import PhaseTimeline from '../components/research/PhaseTimeline.vue'
import PhaseValidationPanel from '../components/research/PhaseValidationPanel.vue'
import ResearchVideoWorkspaceHeader from '../components/research/ResearchVideoWorkspaceHeader.vue'
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
  ResearchPhaseLabelMappingProfileDetail,
  ResearchPhaseMutationResponse,
  ResearchPhaseSegment,
  ResearchPhaseValidationIssue,
} from '../types/researchPhase'
import {
  buildPhaseExportFilename,
  calculateMappedFrameConservation,
  mapAndMergePhaseSegments,
  slugifyMappingKey,
  type PhaseLabelViewMode,
} from '../utils/phaseLabelMapping'
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
  clampPhaseVideoHeight,
  collapsePhaseVideo,
  expandPhaseVideo,
  getDefaultPhaseVideoHeight,
  nextPhaseRightPanelTabAfterSegmentSelect,
  nextPhaseRightPanelTabAfterValidate,
  parsePersistedPhaseVideoHeight,
  type PhaseRightPanelTab,
} from '../utils/researchWorkflowUi.ts'
import { findSegmentAtFrame, resolveNewPhaseStartFrame } from '../utils/researchPhaseTimeline'
import {
  formatDateTime,
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

const PLAYER_HEIGHT_STORAGE_KEY = 'research-phase-player-height'
const VIDEO_COLLAPSED_STORAGE_KEY = 'research-phase-video-collapsed'
const LAST_EXPANDED_VIDEO_HEIGHT_STORAGE_KEY = 'research-phase-last-expanded-video-height'
const PAUSE_AFTER_PHASE_CHANGE_STORAGE_KEY = 'research-phase-pause-after-change'
const FRAME_PAGE_SIZE = DEFAULT_FRAME_PAGE_SIZE
const MAX_CACHED_FRAME_PAGES = DEFAULT_MAX_CACHED_FRAME_PAGES
const PHASE_VIDEO_HEIGHT_KEYBOARD_STEP = 24

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
  mappingProfiles,
  mappingProfileDetails,
  loadingMappingProfiles,
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
const activeRightPanelTab = ref<PhaseRightPanelTab>('inspector')
const showConflictDialog = ref(false)
const viewportHeight = ref(typeof window === 'undefined' ? 900 : window.innerHeight)
const viewportWidth = ref(typeof window === 'undefined' ? 1440 : window.innerWidth)
const phaseVideoHeight = ref(320)
const isVideoCollapsed = ref(false)
const lastExpandedVideoHeight = ref(320)
const isDraggingVideoHeight = ref(false)
const pendingNextStartFrame = ref<number | null>(null)
const labelViewMode = ref<PhaseLabelViewMode>('original')
const selectedMappingProfileId = ref<number | null>(null)
const showMappingDrawer = ref(false)
const showCreateMappingProfileDialog = ref(false)
const selectedMappingSourceLabelIds = ref<number[]>([])
const mergeTargetName = ref('')
const mergeTargetKey = ref('')
const mergeTargetColor = ref('#1f9fe5')
const createMappingProfileForm = ref({
  name: '',
  description: '',
})

let videoLoadGeneration = 0
let frameNavigationSequence = 0
let suppressFrameQueryWatch = false
let videoResizePointerId: number | null = null
let videoResizeHandle: HTMLElement | null = null
let videoResizeStartY = 0
let videoResizeStartHeight = 0
let videoResizeOriginalHeight = 0
let pendingVideoHeight: number | null = null
let scheduledVideoResizeFrame = 0

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
const publishedMappingProfiles = computed(() => mappingProfiles.value.filter((profile) => profile.status === 'published'))
const selectedMappingProfile = computed<ResearchPhaseLabelMappingProfileDetail | null>(() => {
  if (selectedMappingProfileId.value === null) {
    return null
  }
  return mappingProfileDetails.value[selectedMappingProfileId.value] ?? null
})
const isMappedView = computed(() => labelViewMode.value === 'mapped' && selectedMappingProfile.value !== null)
const mappedSegments = computed(() => mapAndMergePhaseSegments(segments.value, selectedMappingProfile.value, totalFrames.value))
const timelineSegments = computed<ResearchPhaseSegment[]>(() => (
  isMappedView.value
    ? mappedSegments.value
    : segments.value
))
const mappingFrameConservation = computed(() => calculateMappedFrameConservation(segments.value, mappedSegments.value, totalFrames.value))
const mergedMappingTargets = computed(() => selectedMappingProfile.value?.targets.filter((target) => target.source_labels.length > 1) ?? [])
const selectedMappingLabels = computed(() => activeLabels.value.filter((label) => selectedMappingSourceLabelIds.value.includes(label.id)))
const unmergedMappingClassCount = computed(() => selectedMappingProfile.value
  ? Math.max(selectedMappingProfile.value.source_label_count - mergedMappingTargets.value.reduce((total, target) => total + target.source_labels.length, 0), 0)
  : 0)
const mergePreviewText = computed(() => {
  if (selectedMappingLabels.value.length < 2 || !mergeTargetName.value.trim()) {
    return ''
  }
  return `${selectedMappingLabels.value.map((label) => getPhaseLabelDisplayName(label, currentLocale.value)).join(' + ')} → ${mergeTargetName.value.trim()}`
})
const exportMappingProfileId = ref<number | null>(null)
const phaseExportFilenamePreview = computed(() => buildPhaseExportFilename({
  videoDisplayName: video.value?.name ?? video.value?.original_filename ?? null,
  videoId: video.value?.id ?? Number(props.videoId),
  mappingMode: exportMappingProfileId.value ? 'profile' : 'original',
  mappingProfileKey: exportMappingProfileId.value
    ? slugifyMappingKey(mappingProfiles.value.find((profile) => profile.id === exportMappingProfileId.value)?.name ?? '')
    : null,
}))
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
const submittedAtText = computed(() => formatDateTime(currentAnnotationSet.value?.submitted_at, currentLocale.value))
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
const researchSplitStyle = computed(() => ({
  '--phase-video-height': `${isVideoCollapsed.value ? 52 : phaseVideoHeight.value}px`,
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
const workspaceHeaderMetaItems = computed(() => [
  `${t('common.frame')} ${currentFrameNumber.value} / ${totalFrames.value}`,
  currentFrameTimeText.value,
  `${t('phaseAnnotation.currentPhase')} ${currentPhaseName.value}`,
])
const pendingNextPhaseText = computed(() => {
  if (pendingNextStartFrame.value === null) {
    return ''
  }
  const previousEndFrame = pendingNextStartFrame.value
  const nextFrame = pendingNextStartFrame.value + 1
  return `${t('phaseAnnotation.previousSegmentEndedAt', { frame: previousEndFrame })} ${t('phaseAnnotation.nextSegmentStartsAt', { frame: nextFrame })}`
})

onMounted(async () => {
  restoreLayoutPreferences()
  restorePauseAfterPhaseChangePreference()
  window.addEventListener('resize', handleViewportResize)
  window.addEventListener('keydown', handleLabelShortcutKeydown)
  await loadPhaseWorkspace()
})

onBeforeUnmount(() => {
  videoLoadGeneration += 1
  pendingNextStartFrame.value = null
  window.removeEventListener('resize', handleViewportResize)
  removeVideoResizeListeners()
  window.removeEventListener('keydown', handleLabelShortcutKeydown)
  researchPhasesStore.clearVideoState()
})

watch(
  () => props.videoId,
  () => {
    pendingNextStartFrame.value = null
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
    if (pendingNextStartFrame.value !== null && nextFrameIndex !== pendingNextStartFrame.value) {
      pendingNextStartFrame.value = null
    }
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
  () => currentAnnotationSet.value?.status,
  () => {
    if (isReadOnly.value) {
      pendingNextStartFrame.value = null
    }
  },
)

watch(
  () => currentAnnotationSet.value?.protocol_id,
  async (protocolId) => {
    labelViewMode.value = 'original'
    selectedMappingProfileId.value = null
    exportMappingProfileId.value = null
    if (!protocolId) {
      return
    }
    const result = await researchPhasesStore.fetchMappingProfiles(protocolId, true)
    if (!result.ok) {
      ElMessage.warning(result.error.message)
    }
  },
)

watch(
  () => selectedMappingProfileId.value,
  async (profileId) => {
    if (profileId === null) {
      return
    }
    if (mappingProfileDetails.value[profileId]) {
      return
    }
    const result = await researchPhasesStore.fetchMappingProfile(profileId)
    if (!result.ok) {
      ElMessage.warning(result.error.message)
      labelViewMode.value = 'original'
      selectedMappingProfileId.value = null
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
  pendingNextStartFrame.value = null
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

function restoreLayoutPreferences() {
  const workspaceHeight = getPhaseWorkspaceHeight()
  phaseVideoHeight.value = parsePersistedPhaseVideoHeight(window.localStorage.getItem(PLAYER_HEIGHT_STORAGE_KEY), workspaceHeight)
  lastExpandedVideoHeight.value = parsePersistedPhaseVideoHeight(
    window.localStorage.getItem(LAST_EXPANDED_VIDEO_HEIGHT_STORAGE_KEY),
    workspaceHeight,
  )
  isVideoCollapsed.value = window.localStorage.getItem(VIDEO_COLLAPSED_STORAGE_KEY) === 'true'
  if (!isVideoCollapsed.value) {
    lastExpandedVideoHeight.value = phaseVideoHeight.value
  }
}

function restorePauseAfterPhaseChangePreference() {
  pauseAfterPhaseChange.value = window.localStorage.getItem(PAUSE_AFTER_PHASE_CHANGE_STORAGE_KEY) === 'true'
}

function persistLayoutPreferences() {
  window.localStorage.setItem(VIDEO_COLLAPSED_STORAGE_KEY, String(isVideoCollapsed.value))
  window.localStorage.setItem(LAST_EXPANDED_VIDEO_HEIGHT_STORAGE_KEY, String(lastExpandedVideoHeight.value))
  if (!isVideoCollapsed.value) {
    window.localStorage.setItem(PLAYER_HEIGHT_STORAGE_KEY, String(phaseVideoHeight.value))
  }
}

function persistPauseAfterPhaseChangePreference() {
  window.localStorage.setItem(PAUSE_AFTER_PHASE_CHANGE_STORAGE_KEY, String(pauseAfterPhaseChange.value))
}

function handleViewportResize() {
  viewportHeight.value = window.innerHeight
  viewportWidth.value = window.innerWidth
  const workspaceHeight = getPhaseWorkspaceHeight()
  phaseVideoHeight.value = clampPhaseVideoHeight(phaseVideoHeight.value, workspaceHeight)
  lastExpandedVideoHeight.value = clampPhaseVideoHeight(lastExpandedVideoHeight.value, workspaceHeight)
  persistLayoutPreferences()
}

function getPhaseWorkspaceHeight() {
  const mainHeight = splitPaneRef.value?.closest('.research-phase-main')?.clientHeight ?? 0
  return mainHeight > 0 ? mainHeight : Math.max(420, viewportHeight.value - 170)
}

function setPhaseVideoHeight(nextHeight: number, persist = true) {
  const clampedHeight = clampPhaseVideoHeight(nextHeight, getPhaseWorkspaceHeight())
  phaseVideoHeight.value = clampedHeight
  lastExpandedVideoHeight.value = clampedHeight
  if (persist) {
    persistLayoutPreferences()
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

async function goToFrame(index: number, options: { syncVideo: boolean; preservePending?: boolean } = { syncVideo: true }) {
  if (index < 0 || index >= totalFrames.value) {
    return false
  }
  if (!options.preservePending && pendingNextStartFrame.value !== null && index !== pendingNextStartFrame.value) {
    pendingNextStartFrame.value = null
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
    const message = t('frameAnnotation.imageIndexRange', { max: totalFrames.value })
    gotoFrameError.value = message
    ElMessage.warning(message)
    return null
  }
  const frameNumber = Number.parseInt(normalized, 10)
  if (!Number.isInteger(frameNumber) || frameNumber < 1 || frameNumber > totalFrames.value) {
    const message = t('frameAnnotation.imageIndexRange', { max: totalFrames.value })
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
  if (isVideoCollapsed.value) {
    const expanded = expandPhaseVideo(lastExpandedVideoHeight.value, getPhaseWorkspaceHeight())
    isVideoCollapsed.value = expanded.isCollapsed
    phaseVideoHeight.value = expanded.videoHeight
    lastExpandedVideoHeight.value = expanded.videoHeight
  } else {
    const collapsed = collapsePhaseVideo(phaseVideoHeight.value, getPhaseWorkspaceHeight())
    isVideoCollapsed.value = collapsed.isCollapsed
    lastExpandedVideoHeight.value = collapsed.lastExpandedHeight
  }
  persistLayoutPreferences()
}

function resetPhaseVideoHeight() {
  setPhaseVideoHeight(getDefaultPhaseVideoHeight(getPhaseWorkspaceHeight()))
}

function startPlayerResize(event: PointerEvent) {
  if (isVideoCollapsed.value) {
    return
  }
  const handle = event.currentTarget as HTMLElement | null
  isDraggingVideoHeight.value = true
  videoResizePointerId = event.pointerId
  videoResizeHandle = handle
  videoResizeStartY = event.clientY
  videoResizeStartHeight = phaseVideoHeight.value
  videoResizeOriginalHeight = phaseVideoHeight.value
  handle?.setPointerCapture?.(event.pointerId)
  document.body.classList.add('is-phase-video-resizing')
  window.addEventListener('pointermove', handlePlayerResizeMove)
  window.addEventListener('pointerup', stopPlayerResize)
  window.addEventListener('pointercancel', cancelPlayerResize)
  window.addEventListener('keydown', handleVideoResizeKeydown)
}

function handlePlayerResizeMove(event: PointerEvent) {
  if (!isDraggingVideoHeight.value || event.pointerId !== videoResizePointerId) {
    return
  }
  const delta = event.clientY - videoResizeStartY
  pendingVideoHeight = clampPhaseVideoHeight(videoResizeStartHeight + delta, getPhaseWorkspaceHeight())
  if (scheduledVideoResizeFrame) {
    return
  }
  scheduledVideoResizeFrame = window.requestAnimationFrame(() => {
    if (pendingVideoHeight !== null) {
      phaseVideoHeight.value = pendingVideoHeight
      lastExpandedVideoHeight.value = pendingVideoHeight
      pendingVideoHeight = null
    }
    scheduledVideoResizeFrame = 0
  })
}

function stopPlayerResize(event?: PointerEvent) {
  if (!isDraggingVideoHeight.value) {
    return
  }
  if (pendingVideoHeight !== null) {
    phaseVideoHeight.value = pendingVideoHeight
    lastExpandedVideoHeight.value = pendingVideoHeight
    pendingVideoHeight = null
  }
  if (event && videoResizePointerId !== null) {
    videoResizeHandle?.releasePointerCapture?.(videoResizePointerId)
  }
  isDraggingVideoHeight.value = false
  videoResizePointerId = null
  videoResizeHandle = null
  document.body.classList.remove('is-phase-video-resizing')
  removeVideoResizeListeners()
  persistLayoutPreferences()
}

function cancelPlayerResize(event?: PointerEvent) {
  if (!isDraggingVideoHeight.value) {
    return
  }
  if (scheduledVideoResizeFrame) {
    window.cancelAnimationFrame(scheduledVideoResizeFrame)
    scheduledVideoResizeFrame = 0
  }
  phaseVideoHeight.value = clampPhaseVideoHeight(videoResizeOriginalHeight, getPhaseWorkspaceHeight())
  pendingVideoHeight = null
  if (event && videoResizePointerId !== null) {
    videoResizeHandle?.releasePointerCapture?.(videoResizePointerId)
  }
  isDraggingVideoHeight.value = false
  videoResizePointerId = null
  videoResizeHandle = null
  document.body.classList.remove('is-phase-video-resizing')
  removeVideoResizeListeners()
}

function removeVideoResizeListeners() {
  window.removeEventListener('pointermove', handlePlayerResizeMove)
  window.removeEventListener('pointerup', stopPlayerResize)
  window.removeEventListener('pointercancel', cancelPlayerResize)
  window.removeEventListener('keydown', handleVideoResizeKeydown)
}

function handleVideoResizeKeydown(event: KeyboardEvent) {
  if (event.isComposing || event.keyCode === 229 || isEditableEventTarget(event.target)) {
    return
  }
  if (event.key !== 'Escape') {
    return
  }
  event.preventDefault()
  cancelPlayerResize()
}

function handleResizeHandleKeydown(event: KeyboardEvent) {
  if (event.key === 'ArrowUp') {
    event.preventDefault()
    setPhaseVideoHeight(phaseVideoHeight.value - PHASE_VIDEO_HEIGHT_KEYBOARD_STEP)
  } else if (event.key === 'ArrowDown') {
    event.preventDefault()
    setPhaseVideoHeight(phaseVideoHeight.value + PHASE_VIDEO_HEIGHT_KEYBOARD_STEP)
  } else if (event.key === 'Home') {
    event.preventDefault()
    setPhaseVideoHeight(0)
  } else if (event.key === 'End') {
    event.preventDefault()
    resetPhaseVideoHeight()
  }
}

function isEditableEventTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) {
    return false
  }
  const tagName = target.tagName.toLowerCase()
  return (
    tagName === 'input'
    || tagName === 'textarea'
    || tagName === 'select'
    || target.isContentEditable
    || Boolean(target.closest('input, textarea, select, [contenteditable="true"], .el-input, .el-textarea, .el-select, .el-dialog'))
  )
}

function shouldIgnorePhaseGlobalShortcut(event: KeyboardEvent) {
  return (
    event.isComposing
    || event.keyCode === 229
    || event.ctrlKey
    || event.altKey
    || event.metaKey
    || isEditableEventTarget(event.target)
  )
}

function handleLabelShortcutKeydown(event: KeyboardEvent) {
  if (researchPhasesStore.isReadOnly || saving.value || saveState.value === 'conflict') {
    return
  }
  if (shouldIgnorePhaseGlobalShortcut(event)) {
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
    validate?: boolean
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
  if (options.validate !== false) {
    await researchPhasesStore.validateAnnotationSet()
  }
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
  if (isMappedView.value) {
    ElMessage.info(t('phaseMapping.mappingViewNotice'))
    return
  }
  if (pendingNextStartFrame.value !== null) {
    const resolution = resolveNewPhaseStartFrame({
      currentFrame: selectedFrameIndex.value,
      pendingNextStartFrame: pendingNextStartFrame.value,
      existingSegments: segments.value,
      videoFrameCount: totalFrames.value,
    })
    if (resolution.conflict !== 'none') {
      const occupiedSegment = resolution.occupiedSegmentId === null
        ? null
        : segments.value.find((segment) => segment.id === resolution.occupiedSegmentId) ?? null
      if (occupiedSegment) {
        selectedSegmentId.value = occupiedSegment.id
        activeRightPanelTab.value = nextPhaseRightPanelTabAfterSegmentSelect()
      }
      if (resolution.reason === 'no-next-frame') {
        ElMessage.warning(t('phaseAnnotation.noNextFrame'))
      } else if (resolution.reason === 'next-frame-already-annotated' && occupiedSegment) {
        ElMessage.warning(t('phaseAnnotation.nextFrameAlreadyAnnotated', {
          label: getPhaseLabelDisplayName(occupiedSegment.phase_label, currentLocale.value),
        }))
      } else {
        ElMessage.warning(t('phaseAnnotation.nextFrameOccupied'))
      }
      pendingNextStartFrame.value = null
      return
    }

    const nextStartFrame = resolution.startFrame
    if (nextStartFrame === null) {
      ElMessage.warning(t('phaseAnnotation.nextFrameOccupied'))
      pendingNextStartFrame.value = null
      return
    }
    const result = await researchPhasesStore.createSegment({
      phase_label_id: label.id,
      start_frame: nextStartFrame,
      end_frame_exclusive: null,
      source: 'manual',
    })
    const createdSegmentId = result.ok && result.data.created_segment_ids.length > 0
      ? result.data.created_segment_ids[result.data.created_segment_ids.length - 1]
      : null
    if (await afterMutation(result, {
      message: t('phaseAnnotation.startedAtNextFrame', { frame: (resolution.startFrame ?? 0) + 1 }),
      nextSelectedSegmentId: createdSegmentId,
      scrollFrame: nextStartFrame,
    })) {
      pendingNextStartFrame.value = null
      if (pauseAfterPhaseChange.value && videoRef.value && !videoRef.value.paused) {
        videoRef.value.pause()
      }
    }
    return
  }

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
  const closed = await afterMutation(
    await researchPhasesStore.closeActiveSegment(endFrameExclusive),
    {
      message: closeAtVideoEnd ? t('phaseAnnotation.activeClosedAtEnd') : t('phaseAnnotation.activeClosed'),
      nextSelectedSegmentId: openSegment.value?.id ?? selectedSegmentId.value,
    },
  )
  if (!closed || closeAtVideoEnd) {
    pendingNextStartFrame.value = null
    return
  }
  if (endFrameExclusive >= totalFrames.value) {
    pendingNextStartFrame.value = null
    ElMessage.info(t('phaseAnnotation.noNextFrame'))
    return
  }
  pendingNextStartFrame.value = endFrameExclusive
  if (videoRef.value && !videoRef.value.paused) {
    videoRef.value.pause()
  }
  await goToFrame(endFrameExclusive, { syncVideo: true, preservePending: true })
  ElMessage.info(t('phaseAnnotation.pendingNextPhase', { frame: endFrameExclusive + 1 }))
}

async function handleSegmentPatch(segmentId: number, patch: Record<string, unknown>) {
  const patchKeys = Object.keys(patch)
  const isNotesOnlyPatch = patchKeys.length === 1 && (patchKeys[0] === 'notes' || patchKeys[0] === 'clear_notes')
  await afterMutation(
    await researchPhasesStore.updateSegment(segmentId, patch),
    {
      nextSelectedSegmentId: segmentId,
      validate: !isNotesOnlyPatch,
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
  activeRightPanelTab.value = nextPhaseRightPanelTabAfterValidate(activeRightPanelTab.value, result.data)
  ElMessage.success(t('phaseAnnotation.validationRefreshed'))
}

async function handleGoToIssue(issue: ResearchPhaseValidationIssue) {
  activeRightPanelTab.value = 'validation'
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

function handleTimelineSegmentSelect(segmentId: number) {
  pendingNextStartFrame.value = null
  selectedSegmentId.value = segmentId
  activeRightPanelTab.value = nextPhaseRightPanelTabAfterSegmentSelect()
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
    ? await researchPhasesStore.downloadJson({
        mappingProfileId: exportMappingProfileId.value,
        fallbackFilename: phaseExportFilenamePreview.value,
      })
    : command === 'segments'
      ? await researchPhasesStore.downloadSegmentCsv()
      : await researchPhasesStore.downloadFramewiseCsv()
  if (!result.ok) {
    ElMessage.error(result.error.message)
    return
  }
  if (command === 'framewise' && (result.data.validationErrors > 0 || result.data.validationWarnings > 0)) {
    ElMessage.info(t('phaseAnnotation.framewiseExportValidationHeaders', {
      errors: result.data.validationErrors,
      warnings: result.data.validationWarnings,
    }))
    return
  }
  ElMessage.success(t('phaseAnnotation.exportedFile', { filename: result.data.filename }))
}

async function openMappingDrawer() {
  showMappingDrawer.value = true
  if (currentAnnotationSet.value) {
    const result = await researchPhasesStore.fetchMappingProfiles(currentAnnotationSet.value.protocol_id, true)
    if (!result.ok) {
      ElMessage.error(result.error.message)
    }
  }
}

function openCreateMappingProfileDialog() {
  createMappingProfileForm.value = {
    name: t('phaseMapping.defaultProfileName'),
    description: '',
  }
  showCreateMappingProfileDialog.value = true
}

async function handleCreateMappingProfile() {
  if (!currentAnnotationSet.value) {
    return
  }
  const profileName = createMappingProfileForm.value.name.trim() || t('phaseMapping.defaultProfileName')
  const result = await researchPhasesStore.createMappingProfile(currentAnnotationSet.value.protocol_id, {
    name: profileName,
    description: createMappingProfileForm.value.description.trim() || null,
    initialize_identity_mapping: true,
  })
  if (!result.ok) {
    ElMessage.error(result.error.message)
    return
  }
  selectedMappingProfileId.value = result.data.id
  selectedMappingSourceLabelIds.value = []
  showCreateMappingProfileDialog.value = false
  ElMessage.success(t('phaseMapping.profileCreated'))
}

function handlePrepareMergeSelected() {
  const selectedLabels = activeLabels.value.filter((label) => selectedMappingSourceLabelIds.value.includes(label.id))
  mergeTargetName.value = selectedLabels.map((label) => getPhaseLabelDisplayName(label, currentLocale.value)).join('/')
  mergeTargetKey.value = buildUniqueMergeTargetKey(slugifyMappingKey(mergeTargetName.value) || slugifyMappingKey(selectedLabels.map((label) => label.key).join('-or-')))
  mergeTargetColor.value = selectedLabels[0]?.color ?? '#1f9fe5'
}

function buildUniqueMergeTargetKey(baseKey: string) {
  const existingKeys = new Set(selectedMappingProfile.value?.targets.map((target) => target.key) ?? [])
  const safeBaseKey = baseKey || 'merged-class'
  if (!existingKeys.has(safeBaseKey)) {
    return safeBaseKey
  }
  let suffix = 2
  while (existingKeys.has(`${safeBaseKey}-${suffix}`)) {
    suffix += 1
  }
  return `${safeBaseKey}-${suffix}`
}

async function handleMergeSelectedClasses() {
  if (!selectedMappingProfile.value || selectedMappingSourceLabelIds.value.length < 2) {
    return
  }
  const targetName = mergeTargetName.value.trim()
  const targetKey = mergeTargetKey.value.trim() || buildUniqueMergeTargetKey(slugifyMappingKey(targetName))
  if (!targetName || !targetKey) {
    ElMessage.warning(t('phaseMapping.selectAtLeastTwo'))
    return
  }
  const result = await researchPhasesStore.mergeMappingClasses(selectedMappingProfile.value.id, {
    source_label_ids: selectedMappingSourceLabelIds.value,
    target_key: targetKey,
    target_name: targetName,
    target_color: mergeTargetColor.value,
  })
  if (!result.ok) {
    ElMessage.error(result.error.message)
    return
  }
  selectedMappingSourceLabelIds.value = []
  mergeTargetName.value = ''
  mergeTargetKey.value = ''
  mergeTargetColor.value = '#1f9fe5'
  ElMessage.success(t('phaseMapping.classesMerged'))
}

async function handleUnmergeTarget(targetId: number) {
  if (!selectedMappingProfile.value) {
    return
  }
  const result = await researchPhasesStore.unmergeMappingTarget(selectedMappingProfile.value.id, { target_id: targetId })
  if (!result.ok) {
    ElMessage.error(result.error.message)
    return
  }
  ElMessage.success(t('phaseMapping.unmerged'))
}

async function handlePublishMappingProfile() {
  if (!selectedMappingProfile.value) {
    return
  }
  const result = await researchPhasesStore.publishMappingProfile(selectedMappingProfile.value.id)
  if (!result.ok) {
    ElMessage.error(result.error.message)
    return
  }
  ElMessage.success(t('phaseMapping.publishedMessage'))
}

async function handleDuplicateMappingProfile() {
  if (!selectedMappingProfile.value) {
    return
  }
  const result = await researchPhasesStore.duplicateMappingProfile(selectedMappingProfile.value.id, {
    name: `${selectedMappingProfile.value.name} copy`,
    description: selectedMappingProfile.value.description,
  })
  if (!result.ok) {
    ElMessage.error(result.error.message)
    return
  }
  selectedMappingProfileId.value = result.data.id
  ElMessage.success(t('phaseMapping.duplicated'))
}

async function handleArchiveMappingProfile() {
  if (!selectedMappingProfile.value) {
    return
  }
  const result = await researchPhasesStore.archiveMappingProfile(selectedMappingProfile.value.id)
  if (!result.ok) {
    ElMessage.error(result.error.message)
    return
  }
  labelViewMode.value = 'original'
  ElMessage.success(t('phaseMapping.archivedMessage'))
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
    <ResearchVideoWorkspaceHeader
      active-task="phase"
      :current-frame-index="selectedFrameIndex"
      :meta-items="workspaceHeaderMetaItems"
      :task-label="t('taskNav.phase')"
      :title="video?.name ?? t('research.videoFallback', { id: videoId })"
      :video-id="videoId"
    />

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
          <el-button size="small" @click="openMappingDrawer">{{ t('phaseMapping.title') }}</el-button>
        </div>

        <div class="research-phase-card">
          <p class="research-phase-card-eyebrow">{{ t('phaseMapping.labelView') }}</p>
          <el-segmented
            v-model="labelViewMode"
            :options="[
              { label: t('phaseMapping.originalView'), value: 'original' },
              { label: t('phaseMapping.mappedView'), value: 'mapped', disabled: publishedMappingProfiles.length === 0 },
            ]"
          />
          <el-select
            v-if="labelViewMode === 'mapped'"
            v-model="selectedMappingProfileId"
            :placeholder="t('phaseMapping.noPublishedProfile')"
            size="small"
          >
            <el-option
              v-for="profile in publishedMappingProfiles"
              :key="profile.id"
              :label="`${profile.name} v${profile.version}`"
              :value="profile.id"
            />
          </el-select>
          <span v-if="isMappedView" class="research-phase-muted">{{ t('phaseMapping.mappingViewNotice') }}</span>
        </div>

        <div class="research-phase-card">
          <p class="research-phase-card-eyebrow">{{ t('phaseAnnotation.annotationSet') }}</p>
          <div class="research-phase-set-status">
            <span class="research-phase-status-badge">{{ translateStatus(currentAnnotationSet?.status ?? 'draft', t) }}</span>
            <span>{{ t('phaseAnnotation.revision') }} {{ currentAnnotationSet?.revision ?? '--' }}</span>
            <span>{{ saveStateLabel }}</span>
          </div>
          <span class="research-phase-qc-inline">{{ qcSummaryText }}</span>
          <span v-if="currentAnnotationSet?.submitted_at" class="research-phase-submitted-at">
            {{ t('phaseAnnotation.submittedAt', { time: submittedAtText }) }}
          </span>
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
              :disabled="saving || isReadOnly || isMappedView || saveState === 'conflict'"
              type="button"
              @click="handleTransition(label)"
            >
              <span class="research-phase-label-swatch" :style="{ backgroundColor: label.color }"></span>
              <span class="research-phase-label-name" :title="getPhaseLabelDisplayName(label, currentLocale)">{{ getPhaseLabelDisplayName(label, currentLocale) }}</span>
              <span v-if="label.shortcut" class="research-phase-label-shortcut">{{ label.shortcut }}</span>
            </button>
          </div>
        </div>

      </aside>

      <section class="research-phase-main">
        <div class="research-phase-mobile-actions" v-if="isCompactLayout">
          <el-button @click="showSidebarDrawer = true">{{ t('phaseAnnotation.labelsAndQc') }}</el-button>
          <el-button @click="showInspectorDrawer = true">{{ t('phaseAnnotation.inspector') }}</el-button>
        </div>

        <div class="research-video-workspace research-phase-video-workspace">
          <div
            ref="splitPaneRef"
            class="research-video-split research-phase-video-split"
            :class="{
              'is-player-collapsed': isVideoCollapsed,
              'is-resizing': isDraggingVideoHeight,
            }"
            :style="researchSplitStyle"
          >
            <section class="research-player-pane" :class="{ 'is-collapsed': isVideoCollapsed }">
              <div class="research-player-pane-header">
                <div class="research-player-pane-heading">
                  <strong>{{ t('phaseAnnotation.videoPreview') }}</strong>
                  <span>{{ currentFrameStatusText }}</span>
                </div>

                <div class="research-player-pane-actions">
                  <span class="research-video-help-text">
                    {{ t('common.previous') }} / {{ t('common.next') }} / {{ t('common.goTo') }}
                  </span>
                  <button class="research-player-pane-action" type="button" @click="togglePlayerCollapsed">
                    {{ isVideoCollapsed ? t('frameAnnotation.expand') : t('frameAnnotation.collapse') }}
                  </button>
                </div>
              </div>

              <div v-if="isVideoCollapsed" class="research-player-compact-bar">
                <div class="research-player-compact-meta">
                  <strong :title="video?.original_filename ?? video?.name ?? t('research.videoFallback', { id: videoId })">
                    {{ video?.original_filename ?? video?.name ?? t('research.videoFallback', { id: videoId }) }}
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

              <div class="research-player-pane-body" :class="{ 'is-visually-collapsed': isVideoCollapsed }">
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
              class="research-split-handle research-phase-resize-handle"
              :class="{ 'is-hidden': isVideoCollapsed }"
              aria-label="调整视频区域高度"
              role="separator"
              tabindex="0"
              @pointerdown.prevent="startPlayerResize"
              @dblclick.prevent="resetPhaseVideoHeight"
              @keydown="handleResizeHandleKeydown"
            >
              <span></span>
            </div>
          </div>

          <section class="research-phase-player-toolbar">
            <div class="research-phase-toolbar">
              <div class="research-phase-toolbar-group research-phase-toolbar-left">
                <el-button :disabled="isFirstFrame" @click="goPrevious">{{ t('common.previous') }}</el-button>
                <el-button :disabled="!video?.file_url" @click="togglePlayback">
                  <el-icon><VideoPause v-if="isPlaying" /><VideoPlay v-else /></el-icon>
                  {{ isPlaying ? t('frameAnnotation.pause') : t('frameAnnotation.play') }}
                </el-button>
                <VideoPlaybackRateControl compact />
                <el-button :disabled="isLastFrame" @click="goNext">{{ t('common.next') }}</el-button>
              </div>

              <div class="research-phase-toolbar-group research-phase-toolbar-center">
                <span class="research-phase-toolbar-meta">{{ currentFrameNumber }} / {{ totalFrames }}</span>
                <span class="research-phase-toolbar-meta">{{ currentFrameTimeText }}</span>
              </div>

              <div class="research-phase-toolbar-group research-phase-toolbar-right">
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
                <span class="research-phase-current-badge">{{ currentPhaseName }}</span>
              </div>
            </div>

            <div v-if="showVideoEndCloseHint" class="research-phase-banner">
              <span>{{ t('phaseAnnotation.activeSegmentOpen') }}</span>
              <el-button size="small" @click="handleCloseCurrentPhase(true)">{{ t('phaseAnnotation.closeAtVideoEnd') }}</el-button>
            </div>
            <div v-if="pendingNextStartFrame !== null && !isReadOnly" class="research-phase-banner is-pending-next">
              <span>{{ pendingNextPhaseText }}</span>
              <strong>{{ t('phaseAnnotation.pendingNextPhase', { frame: pendingNextStartFrame + 1 }) }}</strong>
            </div>
            <div v-if="isMappedView" class="research-phase-banner">
              <span>{{ t('phaseMapping.mappingViewNotice') }}</span>
              <strong>{{ t('phaseMapping.frameConservation') }}: {{ mappingFrameConservation.passed ? t('phaseMapping.passed') : t('status.failed') }}</strong>
            </div>
          </section>
        </div>

        <PhaseTimeline
          ref="timelineRef"
          :current-frame-index="selectedFrameIndex"
          :fps="video?.fps ?? null"
          :frame-count="totalFrames"
          :readonly="isReadOnly || isMappedView || saveState === 'conflict'"
          :segments="timelineSegments"
          :selected-segment-id="selectedSegmentId"
          @seek="goToFrame"
          @clear-selection="selectedSegmentId = null"
          @select-segment="handleTimelineSegmentSelect"
          @update-segment-boundary="handleSegmentPatch($event.segmentId, $event.patch)"
        />
      </section>

      <aside v-if="!isCompactLayout" class="research-phase-inspector-column">
        <el-tabs v-model="activeRightPanelTab" class="research-phase-right-tabs">
          <el-tab-pane :label="t('phaseAnnotation.inspector')" name="inspector">
            <div class="research-phase-right-scroll">
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
            </div>
          </el-tab-pane>
          <el-tab-pane :label="t('phaseAnnotation.qcValidate')" name="validation">
            <div class="research-phase-right-scroll">
              <PhaseValidationPanel
                :current-status="currentAnnotationSet?.status ?? null"
                :validation="validation"
                @go-to-issue="handleGoToIssue"
                @merge-issue="handleMergeIssue"
                @close-at-current="handleCloseCurrentPhase(false)"
                @close-at-video-end="handleCloseCurrentPhase(true)"
              />
            </div>
          </el-tab-pane>
        </el-tabs>

        <div class="research-phase-right-actions">
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
          <el-select
            v-model="exportMappingProfileId"
            :placeholder="t('phaseExport.originalLabels')"
            clearable
            size="small"
            class="research-phase-export-profile"
          >
            <el-option :label="t('phaseExport.originalLabels')" :value="null" />
            <el-option
              v-for="profile in publishedMappingProfiles"
              :key="profile.id"
              :label="`${profile.name} v${profile.version}`"
              :value="profile.id"
            />
          </el-select>
          <span class="research-phase-export-filename" :title="phaseExportFilenamePreview">{{ phaseExportFilenamePreview }}</span>
        </div>
      </aside>
    </section>

    <el-drawer v-model="showMappingDrawer" :title="t('phaseMapping.title')" size="min(1120px, 92vw)" class="phase-mapping-drawer-shell">
      <div class="phase-mapping-drawer">
        <aside class="phase-mapping-list">
          <el-button type="primary" @click="openCreateMappingProfileDialog">{{ t('phaseMapping.createProfile') }}</el-button>
          <el-skeleton v-if="loadingMappingProfiles" :rows="3" animated />
          <button
            v-for="profile in mappingProfiles"
            :key="profile.id"
            class="phase-mapping-profile-button"
            :class="{ active: selectedMappingProfileId === profile.id }"
            type="button"
            @click="selectedMappingProfileId = profile.id; researchPhasesStore.fetchMappingProfile(profile.id)"
          >
            <strong>{{ profile.name }}</strong>
            <span>{{ t(`phaseMapping.${profile.status}`) }} · v{{ profile.version }}</span>
            <small>{{ t('phaseMapping.targetClasses') }} {{ profile.target_count }} · {{ t('phaseMapping.mergedGroups') }} {{ profile.merged_group_count }}</small>
          </button>
        </aside>

        <section class="phase-mapping-detail">
          <div v-if="!selectedMappingProfile" class="research-empty-state">{{ t('phaseMapping.noProfile') }}</div>
          <template v-else>
            <div class="phase-mapping-detail-header">
              <div>
                <h3>{{ selectedMappingProfile.name }}</h3>
                <p>{{ selectedMappingProfile.description || t('common.placeholder') }}</p>
              </div>
            </div>

            <section class="phase-mapping-summary-grid">
              <div>
                <span>{{ t('phaseMapping.originalLabels') }}</span>
                <strong>{{ selectedMappingProfile.source_label_count }}</strong>
              </div>
              <div>
                <span>{{ t('phaseMapping.targetClasses') }}</span>
                <strong>{{ selectedMappingProfile.target_count }}</strong>
              </div>
              <div>
                <span>{{ t('phaseMapping.mergedGroups') }}</span>
                <strong>{{ selectedMappingProfile.merged_group_count }}</strong>
              </div>
              <div>
                <span>{{ t('phaseMapping.unmappedLabels') }}</span>
                <strong>{{ selectedMappingProfile.unmapped_label_count }}</strong>
              </div>
              <div>
                <span>{{ t('phaseMapping.status') }}</span>
                <strong>{{ t(`phaseMapping.${selectedMappingProfile.status}`) }}</strong>
              </div>
            </section>

            <div v-if="selectedMappingProfile.status === 'draft'" class="phase-mapping-merge-panel">
              <header class="phase-mapping-section-header">
                <span>{{ t('phaseMapping.simpleMode') }}</span>
                <strong>{{ t('phaseMapping.mergeClasses') }}</strong>
              </header>
              <p class="research-phase-muted">{{ t('phaseMapping.originalDataUnchanged') }}</p>

              <div class="phase-mapping-step">
                <strong>{{ t('phaseMapping.selectClasses') }}</strong>
                <span>{{ t('phaseMapping.selectedClasses', { count: selectedMappingSourceLabelIds.length }) }}</span>
                <el-checkbox-group v-model="selectedMappingSourceLabelIds" class="phase-mapping-source-grid" @change="handlePrepareMergeSelected">
                  <el-checkbox v-for="label in activeLabels" :key="label.id" :label="label.id" class="phase-mapping-source-option">
                    <span class="research-phase-label-swatch" :style="{ backgroundColor: label.color }"></span>
                    <span :title="getPhaseLabelDisplayName(label, currentLocale)">{{ getPhaseLabelDisplayName(label, currentLocale) }}</span>
                  </el-checkbox>
                </el-checkbox-group>
                <el-button size="small" :disabled="selectedMappingSourceLabelIds.length === 0" @click="selectedMappingSourceLabelIds = []; handlePrepareMergeSelected()">
                  {{ t('phaseMapping.clearSelection') }}
                </el-button>
              </div>

              <div class="phase-mapping-step">
                <strong>{{ t('phaseMapping.mergedClassName') }}</strong>
                <el-input v-model="mergeTargetName" :placeholder="t('phaseMapping.targetName')" @input="mergeTargetKey = buildUniqueMergeTargetKey(slugifyMappingKey(mergeTargetName))" />
              </div>

              <div class="phase-mapping-step">
                <strong>{{ t('phaseMapping.mergePreview') }}</strong>
                <p class="phase-mapping-preview">{{ mergePreviewText || t('phaseMapping.selectAtLeastTwo') }}</p>
                <el-button type="primary" :disabled="selectedMappingSourceLabelIds.length < 2 || !mergeTargetName.trim()" @click="handleMergeSelectedClasses">
                  {{ t('phaseMapping.mergeSelected') }}
                </el-button>
              </div>

              <el-collapse class="phase-mapping-advanced">
                <el-collapse-item :title="t('phaseMapping.advancedSettings')" name="advanced">
                  <div class="phase-mapping-merge-form">
                    <el-input v-model="mergeTargetKey" :placeholder="t('phaseMapping.targetKey')" />
                    <el-color-picker v-model="mergeTargetColor" />
                  </div>
                </el-collapse-item>
              </el-collapse>
            </div>

            <section class="phase-mapping-groups">
              <div class="phase-mapping-section-header">
                <span>{{ t('phaseMapping.currentMergedGroups') }} ({{ mergedMappingTargets.length }})</span>
                <small>{{ t('phaseMapping.unmergedClassCount', { count: unmergedMappingClassCount }) }}</small>
              </div>
              <div v-if="mergedMappingTargets.length === 0" class="research-empty-state">{{ t('phaseMapping.noMergedGroups') }}</div>
              <div v-for="target in mergedMappingTargets" :key="target.id" class="phase-mapping-target">
                <span class="research-phase-label-swatch" :style="{ backgroundColor: target.color }"></span>
                <div>
                  <strong>{{ target.name }}</strong>
                  <p>{{ target.source_labels.map((label) => label.name).join(' / ') }}</p>
                </div>
                <el-button
                  v-if="target.source_labels.length > 1"
                  :disabled="selectedMappingProfile.status !== 'draft'"
                  size="small"
                  @click="handleUnmergeTarget(target.id)"
                >
                  {{ t('phaseMapping.unmerge') }}
                </el-button>
              </div>
            </section>

            <el-collapse class="phase-mapping-all-mappings">
              <el-collapse-item :title="t('phaseMapping.viewAllMappings')" name="all-mappings">
                <table class="phase-mapping-table">
                  <thead>
                    <tr>
                      <th>{{ t('phaseMapping.sourceLabels') }}</th>
                      <th>{{ t('phaseMapping.mappedLabel') }}</th>
                      <th>{{ t('phaseMapping.status') }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <template v-for="target in selectedMappingProfile.targets" :key="target.id">
                      <tr
                        v-for="sourceLabel in target.source_labels"
                        :key="`${target.id}-${sourceLabel.id}`"
                        :class="{ merged: target.source_labels.length > 1 }"
                      >
                        <td :title="sourceLabel.name">
                          <span class="research-phase-label-swatch" :style="{ backgroundColor: sourceLabel.color }"></span>
                          {{ sourceLabel.name }}
                        </td>
                        <td :title="target.name">{{ target.name }}</td>
                        <td>{{ target.source_labels.length > 1 ? t('phaseMapping.merged') : t('phaseMapping.unchanged') }}</td>
                      </tr>
                    </template>
                  </tbody>
                </table>
              </el-collapse-item>
            </el-collapse>
          </template>
        </section>

        <footer v-if="selectedMappingProfile" class="phase-mapping-footer">
          <span>
            {{ t('phaseMapping.originalLabels') }} {{ selectedMappingProfile.source_label_count }} ·
            {{ t('phaseMapping.targetClasses') }} {{ selectedMappingProfile.target_count }} ·
            {{ t('phaseMapping.mergedGroups') }} {{ selectedMappingProfile.merged_group_count }} ·
            {{ t('phaseMapping.unmappedLabels') }} {{ selectedMappingProfile.unmapped_label_count }}
          </span>
          <div class="phase-mapping-actions">
            <el-button @click="handleDuplicateMappingProfile">{{ t('phaseMapping.duplicate') }}</el-button>
            <el-button :disabled="selectedMappingProfile.status === 'draft' || selectedMappingProfile.status === 'archived'" @click="handleArchiveMappingProfile">
              {{ t('phaseMapping.archive') }}
            </el-button>
            <el-button :disabled="selectedMappingProfile.status !== 'draft'" type="primary" @click="handlePublishMappingProfile">
              {{ t('phaseMapping.publish') }}
            </el-button>
          </div>
        </footer>
      </div>
    </el-drawer>

    <el-dialog v-model="showCreateMappingProfileDialog" :title="t('phaseMapping.createProfile')" width="420px">
      <div class="phase-mapping-create-form">
        <label>
          <span>{{ t('phaseMapping.profileName') }}</span>
          <el-input v-model="createMappingProfileForm.name" />
        </label>
        <label>
          <span>{{ t('phaseMapping.description') }}</span>
          <el-input v-model="createMappingProfileForm.description" type="textarea" :rows="3" />
        </label>
      </div>
      <template #footer>
        <el-button @click="showCreateMappingProfileDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="handleCreateMappingProfile">{{ t('common.create') }}</el-button>
      </template>
    </el-dialog>

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
              :disabled="saving || isReadOnly || isMappedView || saveState === 'conflict'"
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
  height: 100dvh;
  min-height: 0;
  overflow: hidden;
  background:
    radial-gradient(circle at top left, rgba(14, 116, 144, 0.18), transparent 38%),
    radial-gradient(circle at top right, rgba(251, 191, 36, 0.08), transparent 28%),
    linear-gradient(180deg, #020617, #0f172a 48%, #111827);
  color: #f8fafc;
}

.research-phase-error,
.research-phase-card,
.research-phase-inspector-column,
.research-phase-main {
  min-width: 0;
}

.research-phase-layout {
  display: grid;
  flex: 1 1 auto;
  grid-template-columns: 260px minmax(0, 1fr) 320px;
  gap: 0.85rem;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.research-phase-sidebar,
.research-phase-inspector-column {
  display: flex;
  flex-direction: column;
  gap: 0.72rem;
  height: 100%;
  min-height: 0;
}

.research-phase-sidebar {
  overflow-x: hidden;
  overflow-y: auto;
}

.research-phase-inspector-column {
  overflow: hidden;
}

.research-phase-main {
  display: flex;
  flex-direction: column;
  gap: 0.72rem;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.research-phase-card,
.research-phase-error {
  display: flex;
  flex-direction: column;
  gap: 0.38rem;
  padding: 0.78rem;
  border-radius: 0.72rem;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.84);
}

.research-phase-sidebar .research-phase-card {
  flex: 0 0 auto;
  height: auto;
  min-height: max-content;
  overflow: visible;
}

.research-phase-sidebar .research-phase-card:nth-child(4) {
  display: flex;
  flex: 1 1 auto;
  min-height: 220px;
  overflow: hidden;
}

.research-phase-set-status {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  align-items: center;
  color: rgba(148, 163, 184, 0.92);
  font-size: 0.84rem;
}

.research-phase-status-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.16rem 0.46rem;
  border-radius: 999px;
  background: rgba(14, 165, 233, 0.18);
  color: #bae6fd !important;
  font-weight: 700;
}

.research-phase-submitted-at {
  overflow-wrap: anywhere;
  white-space: normal;
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
  flex: 1 1 auto;
  flex-direction: column;
  gap: 0.42rem;
  min-height: 0;
  overflow: auto;
  padding-right: 0.15rem;
}

.research-phase-label-button {
  display: flex;
  align-items: center;
  gap: 0.58rem;
  padding: 0.56rem 0.65rem;
  border-radius: 0.62rem;
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
  width: 12px;
  height: 12px;
  border-radius: 999px;
  flex: 0 0 auto;
}

.research-phase-label-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  gap: 0.52rem;
}

.research-phase-sidebar-actions :deep(.el-button),
.research-phase-sidebar-actions :deep(.el-dropdown),
.research-phase-sidebar-actions :deep(.el-dropdown .el-button) {
  width: 100%;
  margin-left: 0;
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

.research-phase-video-workspace {
  flex: 0 0 auto;
  overflow: visible;
}

.research-phase-video-split {
  display: block;
  flex: 0 0 auto;
  height: var(--phase-video-height);
  min-height: 52px;
  overflow: visible;
  transition: height 120ms ease;
}

.research-phase-video-split.is-resizing {
  transition: none;
}

.research-phase-video-split .research-player-pane {
  height: 100%;
}

.research-phase-video-split.is-player-collapsed .research-player-pane {
  height: 52px;
}

.research-phase-player-toolbar {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  margin-top: 0.55rem;
  padding: 0.68rem;
  border-radius: 0.72rem;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.74);
}

.research-phase-toolbar {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) auto minmax(0, 1.1fr);
  gap: 0.65rem;
  align-items: center;
  justify-content: stretch;
  flex-wrap: wrap;
  padding: 0.2rem 0;
}

.research-phase-toolbar-group {
  gap: 0.46rem;
  align-items: center;
  flex-wrap: wrap;
}

.research-phase-toolbar-center {
  justify-content: center;
}

.research-phase-toolbar-right {
  justify-content: flex-end;
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
  width: 72px;
  padding: 0.42rem 0.52rem;
  border-radius: 0.55rem;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(30, 41, 59, 0.82);
  color: #f8fafc;
}

.research-phase-current-badge {
  max-width: 13rem;
  overflow: hidden;
  padding: 0.38rem 0.62rem;
  border-radius: 999px;
  background: rgba(8, 47, 73, 0.78);
  color: #bae6fd;
  text-overflow: ellipsis;
  white-space: nowrap;
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

.research-phase-banner.is-pending-next {
  align-items: center;
  background: rgba(14, 116, 144, 0.28);
  color: #cffafe;
  border: 1px solid rgba(103, 232, 249, 0.22);
}

.research-phase-banner.is-pending-next strong {
  color: #f8fafc;
}

.research-phase-right-tabs {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
}

.research-phase-right-tabs :deep(.el-tabs__header) {
  flex: 0 0 auto;
  margin-bottom: 0.55rem;
}

.research-phase-right-tabs :deep(.el-tabs__content) {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.research-phase-right-tabs :deep(.el-tab-pane) {
  height: 100%;
  min-height: 0;
}

.research-phase-right-scroll {
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  padding-right: 0.12rem;
}

.research-phase-right-actions {
  display: grid;
  flex: 0 0 auto;
  gap: 0.45rem;
  padding: 0.68rem;
  border-radius: 0.72rem;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.84);
}

.research-phase-right-actions :deep(.el-button),
.research-phase-right-actions :deep(.el-dropdown),
.research-phase-right-actions :deep(.el-dropdown .el-button) {
  width: 100%;
  margin-left: 0;
}

.research-phase-export-profile {
  width: 100%;
}

.research-phase-export-filename {
  min-width: 0;
  overflow: hidden;
  color: #94a3b8;
  font-size: 0.78rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.phase-mapping-drawer {
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  height: calc(100vh - 118px);
  min-height: 0;
  overflow: hidden;
  color: #111827;
}

.phase-mapping-drawer > .phase-mapping-list,
.phase-mapping-drawer > .phase-mapping-detail {
  grid-row: 1;
}

.phase-mapping-drawer > .phase-mapping-list {
  grid-column: 1;
}

.phase-mapping-drawer > .phase-mapping-detail {
  grid-column: 2;
}

.phase-mapping-drawer {
  grid-template-columns: 270px minmax(0, 1fr);
  gap: 1rem;
}

.phase-mapping-list,
.phase-mapping-detail {
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
}

.phase-mapping-list {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  padding-right: 0.25rem;
}

.phase-mapping-profile-button {
  display: grid;
  gap: 0.18rem;
  width: 100%;
  min-width: 0;
  padding: 0.72rem;
  border: 1px solid #d1d5db;
  border-radius: 0.58rem;
  background: #fff;
  color: #111827;
  text-align: left;
}

.phase-mapping-profile-button.active,
.phase-mapping-profile-button:hover {
  border-color: #2563eb;
  background: #eff6ff;
}

.phase-mapping-profile-button span,
.phase-mapping-profile-button small {
  color: #64748b;
}

.phase-mapping-detail {
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
  padding-right: 0.25rem;
}

.phase-mapping-detail-header,
.phase-mapping-target {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  min-width: 0;
}

.phase-mapping-actions,
.phase-mapping-merge-form {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}

.phase-mapping-merge-panel,
.phase-mapping-target {
  padding: 0.75rem;
  border: 1px solid #e5e7eb;
  border-radius: 0.65rem;
  background: #fff;
}

.phase-mapping-summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(118px, 1fr));
  gap: 0.6rem;
}

.phase-mapping-summary-grid > div {
  display: grid;
  gap: 0.18rem;
  padding: 0.68rem;
  border: 1px solid #e5e7eb;
  border-radius: 0.55rem;
  background: #f8fafc;
}

.phase-mapping-summary-grid span,
.phase-mapping-section-header small {
  color: #64748b;
  font-size: 0.82rem;
}

.phase-mapping-section-header {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  align-items: center;
  justify-content: space-between;
}

.phase-mapping-step {
  display: grid;
  gap: 0.5rem;
  margin-top: 0.72rem;
}

.phase-mapping-source-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 0.38rem;
}

.phase-mapping-source-option {
  min-width: 0;
  margin-right: 0;
}

.phase-mapping-source-option :deep(.el-checkbox__label) {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 0.42rem;
}

.phase-mapping-source-option :deep(.el-checkbox__label span:last-child) {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.phase-mapping-preview {
  margin: 0;
  color: #334155;
  overflow-wrap: anywhere;
}

.phase-mapping-advanced,
.phase-mapping-all-mappings {
  --el-collapse-header-bg-color: #fff;
  --el-collapse-content-bg-color: #fff;
}

.phase-mapping-groups {
  display: grid;
  gap: 0.55rem;
}

.phase-mapping-target > div {
  min-width: 0;
  flex: 1 1 auto;
}

.phase-mapping-target p,
.phase-mapping-detail-header p {
  margin: 0.18rem 0 0;
  overflow: hidden;
  color: #64748b;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.phase-mapping-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 0.86rem;
}

.phase-mapping-table th,
.phase-mapping-table td {
  padding: 0.48rem 0.5rem;
  border-bottom: 1px solid #e5e7eb;
  overflow: hidden;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.phase-mapping-table th {
  color: #475569;
  font-weight: 700;
}

.phase-mapping-table td:first-child {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.38rem;
}

.phase-mapping-table tr.merged {
  background: #f0f9ff;
}

.phase-mapping-footer {
  grid-column: 1 / -1;
  grid-row: 2;
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
  justify-content: space-between;
  padding-top: 0.8rem;
  border-top: 1px solid #e5e7eb;
  background: #fff;
  color: #334155;
}

.phase-mapping-create-form {
  display: grid;
  gap: 0.8rem;
}

.phase-mapping-create-form label {
  display: grid;
  gap: 0.35rem;
}

.research-phase-resize-handle {
  height: 12px;
  margin: 0.24rem 0 0;
  border-radius: 999px;
  outline: none;
}

.research-phase-resize-handle span {
  width: 96px;
  height: 5px;
  background: rgba(125, 211, 252, 0.52);
}

.research-phase-resize-handle:hover span,
.research-phase-resize-handle:focus-visible span {
  background: rgba(34, 211, 238, 0.9);
  box-shadow: 0 0 0 4px rgba(34, 211, 238, 0.14);
}

:global(body.is-phase-video-resizing) {
  cursor: row-resize;
  user-select: none;
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
    grid-template-columns: 1fr;
  }

  .research-phase-toolbar-center,
  .research-phase-toolbar-right {
    justify-content: flex-start;
  }
}
</style>
