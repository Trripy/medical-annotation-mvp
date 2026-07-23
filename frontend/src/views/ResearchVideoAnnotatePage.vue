<script setup lang="ts">
import { Back, Delete, Finished, Pointer, RefreshRight, VideoPause, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowReactive, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import AnnotationCanvas from '../components/AnnotationCanvas.vue'
import ObjectPanel from '../components/ObjectPanel.vue'
import ResearchVideoTaskNav from '../components/research/ResearchVideoTaskNav.vue'
import VideoPlaybackRateControl from '../components/VideoPlaybackRateControl.vue'
import VirtualFrameList from '../components/VirtualFrameList.vue'
import { useVideoPlaybackRate } from '../composables/useVideoPlaybackRate.ts'
import type { AnnotationObject, Label, ShapeType } from '../stores/annotation'
import {
  useResearchVideosStore,
  type ResearchVideoAnnotation,
  type ResearchVideoFrame,
  type ResearchVideoWorkspaceDetail,
} from '../stores/researchVideos'
import { useUsersStore } from '../stores/users'
import { useUserSettingsStore, type Sam2Candidate, type Sam2ModelName } from '../stores/userSettings'
import { clonePoints, normalizeAnnotationObject } from '../utils/polygon'
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
import { parseResearchFrameQuery } from '../utils/researchPhaseUi'
import { translateApiErrorMessage } from '../utils/locale'

type ToolType = 'cursor' | 'rectangle' | 'polygon' | 'sam2'
type Sam2Settings = {
  model_name: Sam2ModelName
  multimask_output: boolean
  show_prompt_points: boolean
  polygon_epsilon: number
  min_mask_area: number
  mask_threshold: number
  max_hole_area: number
  candidate: Sam2Candidate
}
type ResearchCanvasImage = {
  id: number
  filename: string
  width: number | null
  height: number | null
  frame_index: number | null
  image_url: string
  thumbnail_url: string
}
type LabelDraft = {
  id: number
  name: string
  color: string
  shape_type: ShapeType
  annotation_count: number
}

type ResearchWorkspaceMode = 'video_collapsed' | 'split' | 'video_full'

const PLAYER_HEIGHT_STORAGE_KEY = 'research-video-player-height'
const PLAYER_COLLAPSED_STORAGE_KEY = 'research-video-player-collapsed'
const WORKSPACE_MODE_STORAGE_KEY = 'research-video-workspace-mode'
const PLAYER_SPLIT_HANDLE_HEIGHT = DEFAULT_PLAYER_SPLIT_HANDLE_HEIGHT
const COMPACT_PLAYER_SPLIT_HANDLE_HEIGHT = 6
const FULL_VIDEO_SNAP_THRESHOLD = 24
const RESIZE_OBSERVER_EPSILON = 1
const FRAME_PAGE_SIZE = DEFAULT_FRAME_PAGE_SIZE
const MAX_CACHED_FRAME_PAGES = DEFAULT_MAX_CACHED_FRAME_PAGES

const props = defineProps<{ videoId: string }>()

const researchVideosStore = useResearchVideosStore()
const usersStore = useUsersStore()
const userSettingsStore = useUserSettingsStore()
const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { error, loading, saving } = storeToRefs(researchVideosStore)
const { currentUsername } = storeToRefs(usersStore)
const { settings: userSettings } = storeToRefs(userSettingsStore)

const canvasRef = ref<InstanceType<typeof AnnotationCanvas> | null>(null)
const videoRef = ref<HTMLVideoElement | null>(null)
const splitPaneRef = ref<HTMLElement | null>(null)
const annotationPaneRef = ref<HTMLElement | null>(null)
const gotoFrameInputRef = ref<HTMLInputElement | null>(null)
const selectedFrameIndex = ref(0)
const selectedLabelId = ref<number | null>(null)
const selectedAnnotationId = ref<number | string | null>(null)
const hiddenAnnotationIds = ref<Array<number | string>>([])
const hasUnsavedChanges = ref(false)
const tool = ref<ToolType>('sam2')
const toolOptions: ToolType[] = ['cursor', 'rectangle', 'polygon']
const annotationsByFrame = shallowRef<Record<number, ResearchVideoAnnotation[]>>({})
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
const currentFrameLoading = ref(false)
const isPlaying = ref(false)
const generatingSam2 = ref(false)
const labelManagerVisible = ref(false)
const labelDrafts = ref<LabelDraft[]>([])
const newLabelName = ref('')
const newLabelColor = ref('#22c55e')
const newLabelShapeType = ref<ShapeType>('polygon')
const labelActionLoading = ref(false)
const labelsLoading = ref(false)
const isRightPanelOpen = ref(false)
const viewportHeight = ref(900)
const playerPaneHeight = ref(280)
const workspaceMode = ref<ResearchWorkspaceMode>('split')
const isResizingPlayer = ref(false)
const currentVideoTimeMs = ref(0)
const gotoFrameInput = ref('')
const gotoFrameFocused = ref(false)
const gotoFrameError = ref('')
const isJumpingToFrame = ref(false)
const playerResizeStartY = ref(0)
const playerResizeStartHeight = ref(0)
const playerHeightBeforeMaximize = ref<number | null>(null)
let annotationPaneResizeObserver: ResizeObserver | null = null
let scheduledViewportRefreshFrame = 0
let scheduledPlayerResizeFrame = 0
let videoLoadGeneration = 0
const framePagePrefetchTimers = new Set<number>()
let pendingPlayerPaneHeight: number | null = null
let pendingWorkspaceMode: ResearchWorkspaceMode | null = null
let pendingSplitRestoreHeight: number | null = null
let lastObservedAnnotationPaneWidth = 0
let lastObservedAnnotationPaneHeight = 0
let frameNavigationSequence = 0
let suppressFrameQueryWatch = false
const sam2Settings = ref<Sam2Settings>({
  model_name: userSettings.value.sam2_default_model,
  multimask_output: userSettings.value.sam2_default_multimask_output,
  show_prompt_points: userSettings.value.sam2_default_show_prompt_points,
  polygon_epsilon: userSettings.value.sam2_default_polygon_epsilon,
  min_mask_area: userSettings.value.sam2_default_min_mask_area,
  mask_threshold: userSettings.value.sam2_default_mask_threshold,
  max_hole_area: userSettings.value.sam2_default_max_hole_area,
  candidate: userSettings.value.sam2_default_candidate,
})

const video = computed(() => workspaceVideo.value)
useVideoPlaybackRate(videoRef, computed(() => video.value?.file_url ?? null))
const totalFrames = computed(() => video.value?.frame_count ?? 0)
const currentFrame = computed(() => getFrameAt(selectedFrameIndex.value) ?? null)
const currentFrameNumber = computed(() => totalFrames.value > 0 ? selectedFrameIndex.value + 1 : 0)
const isFirstFrame = computed(() => selectedFrameIndex.value <= 0)
const isLastFrame = computed(() => selectedFrameIndex.value >= totalFrames.value - 1)
const isCompactResearchLayout = computed(() => viewportHeight.value <= 760)
const isPlayerCollapsed = computed(() => workspaceMode.value === 'video_collapsed')
const isVideoFullWorkspace = computed(() => workspaceMode.value === 'video_full')
const currentFrameAnnotations = computed(() =>
  currentFrame.value ? annotationsByFrame.value[currentFrame.value.frame_index] ?? [] : [],
)
const currentCanvasImage = computed<ResearchCanvasImage | null>(() => {
  if (!currentFrame.value) {
    return null
  }
  return {
    id: currentFrame.value.id,
    filename: currentFrame.value.filename,
    width: currentFrame.value.width,
    height: currentFrame.value.height,
    frame_index: currentFrame.value.frame_index,
    image_url: currentFrame.value.image_url,
    thumbnail_url: currentFrame.value.image_url,
  }
})
const researchSam2Context = computed(() => (
  currentFrame.value
    ? {
        research_video_id: Number(props.videoId),
        research_frame_index: currentFrame.value.frame_index,
      }
    : null
))
const currentLabelList = computed<Label[]>(() =>
  (video.value?.labels ?? []).map((label) => ({
    id: label.id,
    name: label.name,
    color: label.color,
    shape_type: label.shape_type,
    sort_order: label.sort_order,
    annotation_count: label.annotation_count,
  })),
)
const compactVideoTimeText = computed(() => formatTimestamp(currentVideoTimeMs.value))
const totalVideoTimeText = computed(() => formatTimestamp(video.value?.duration_ms ?? 0))
const playerPaneMetaText = computed(() => {
  if (!totalFrames.value) {
    return t('common.noFrameSelected')
  }
  if (!currentFrame.value) {
    return `Frame ${currentFrameNumber.value} / ${totalFrames.value} · Loading frame...`
  }
  return `Frame ${currentFrameNumber.value} / ${totalFrames.value} · ${formatTimestamp(currentFrame.value.timestamp_ms)}`
})
const currentObjectCount = computed(() => currentFrameAnnotations.value.length)
const splitHandleSize = computed(() => (isCompactResearchLayout.value ? COMPACT_PLAYER_SPLIT_HANDLE_HEIGHT : PLAYER_SPLIT_HANDLE_HEIGHT))
const playerHeightBounds = computed(() => getPlayerHeightBounds())
const researchSplitStyle = computed(() => ({
  '--research-player-height': `${playerPaneHeight.value}px`,
  '--research-player-min-height': `${playerHeightBounds.value.minPlayerHeight}px`,
  '--research-split-handle-height': `${splitHandleSize.value}px`,
}))

onMounted(async () => {
  viewportHeight.value = window.innerHeight
  window.addEventListener('resize', handleViewportResize)
  await nextTick()
  restorePlayerLayoutPreferences()
  initializeAnnotationPaneResizeObserver()
  if (currentUsername.value) {
    await userSettingsStore.loadSettings(currentUsername.value)
  } else {
    userSettingsStore.resetToDefaults()
  }
  await loadVideo()
  scheduleCanvasViewportRefresh()
})

onBeforeUnmount(() => {
  videoLoadGeneration += 1
  window.removeEventListener('resize', handleViewportResize)
  window.removeEventListener('pointermove', handlePlayerResizeMove)
  window.removeEventListener('pointerup', stopPlayerResize)
  window.removeEventListener('pointercancel', stopPlayerResize)
  annotationPaneResizeObserver?.disconnect()
  annotationPaneResizeObserver = null
  if (scheduledViewportRefreshFrame) {
    window.cancelAnimationFrame(scheduledViewportRefreshFrame)
    scheduledViewportRefreshFrame = 0
  }
  if (scheduledPlayerResizeFrame) {
    window.cancelAnimationFrame(scheduledPlayerResizeFrame)
    scheduledPlayerResizeFrame = 0
  }
  clearScheduledFramePagePrefetches()
})

watch(
  () => props.videoId,
  () => {
    void loadVideo()
  },
)

watch(
  () => selectedFrameIndex.value,
  () => {
    hiddenAnnotationIds.value = []
    selectedAnnotationId.value = null
    currentVideoTimeMs.value = currentFrame.value?.timestamp_ms ?? currentVideoTimeMs.value
  },
)

watch(
  () => selectedFrameIndex.value,
  async (nextFrameIndex) => {
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
      void goToFrame(targetFrameIndex)
    }
  },
)

watch(
  () => [currentFrameNumber.value, totalFrames.value],
  () => {
    if (!gotoFrameFocused.value) {
      gotoFrameInput.value = currentFrameNumber.value > 0 ? String(currentFrameNumber.value) : ''
      gotoFrameError.value = ''
    }
  },
  { immediate: true },
)

watch(
  () => userSettings.value,
  () => {
    sam2Settings.value = {
      model_name: userSettings.value.sam2_default_model,
      multimask_output: userSettings.value.sam2_default_multimask_output,
      show_prompt_points: userSettings.value.sam2_default_show_prompt_points,
      polygon_epsilon: userSettings.value.sam2_default_polygon_epsilon,
      min_mask_area: userSettings.value.sam2_default_min_mask_area,
      mask_threshold: userSettings.value.sam2_default_mask_threshold,
      max_hole_area: userSettings.value.sam2_default_max_hole_area,
      candidate: userSettings.value.sam2_default_candidate,
    }
  },
  { deep: true },
)

async function loadVideo() {
  const finishMeasure = startDevMeasure('research-video-load')
  const generation = ++videoLoadGeneration
  const videoId = Number(props.videoId)
  clearFramePageState()
  const workspace = await researchVideosStore.fetchVideoWorkspace(videoId)
  if (!isCurrentVideoLoadGeneration(generation)) {
    finishMeasure()
    return
  }
  workspaceVideo.value = workspace
  const initialFrameIndex = getInitialFrameIndex(workspace?.frame_count ?? 0)
  selectedFrameIndex.value = initialFrameIndex
  selectedLabelId.value = workspace?.labels[0]?.id ?? null
  annotationsByFrame.value = {}
  hasUnsavedChanges.value = false
  currentVideoTimeMs.value = 0
  if (!workspace) {
    finishMeasure()
    return
  }
  await ensureFrameLoaded(initialFrameIndex, { generation, prefetchAdjacent: false })
  if (!isCurrentVideoLoadGeneration(generation)) {
    finishMeasure()
    return
  }
  if (currentFrame.value) {
    await loadFrameAnnotations(currentFrame.value.frame_index, generation)
  }
  if (!isCurrentVideoLoadGeneration(generation)) {
    finishMeasure()
    return
  }
  void nextTick(() => {
    if (!isCurrentVideoLoadGeneration(generation)) {
      return
    }
    scheduleCanvasViewportRefresh(!isVideoFullWorkspace.value)
    finishMeasure()
  })
}

async function loadFrameAnnotations(frameIndex: number, generation = videoLoadGeneration) {
  if (!video.value || !isCurrentVideoLoadGeneration(generation)) {
    return
  }
  const finishMeasure = startDevMeasure(`research-frame-${frameIndex}-annotations`)
  currentFrameLoading.value = true
  try {
    const annotations = await researchVideosStore.fetchVideoFrameAnnotations(Number(props.videoId), frameIndex)
    if (!isCurrentVideoLoadGeneration(generation)) {
      return
    }
    if (annotations) {
      annotationsByFrame.value = {
        ...annotationsByFrame.value,
        [frameIndex]: annotations.map((annotation) => ({
          ...normalizeAnnotationObject({
            id: annotation.id,
            image_id: annotation.frame_id,
            label_id: annotation.label_id,
            shape_type: annotation.shape_type,
            points: annotation.points,
            attributes: annotation.attributes ?? null,
          }),
          frame_id: annotation.frame_id,
          frame_index: annotation.frame_index,
          visible: annotation.visible,
        })),
      }
    }
  } finally {
    if (isCurrentVideoLoadGeneration(generation)) {
      currentFrameLoading.value = false
    }
    finishMeasure()
  }
}

function clearFramePageState() {
  resetFramePageCache(framePageCacheState)
  clearScheduledFramePagePrefetches()
}

function getFrameAt(frameIndex: number): ResearchVideoFrame | undefined {
  return getFrameAtFromPages(framePages, frameIndex, totalFrames.value, FRAME_PAGE_SIZE)
}

function getFramePageOffsetInVideo(pageIndex: number) {
  return getFramePageOffset(pageIndex, FRAME_PAGE_SIZE)
}

async function ensureFramePageLoaded(
  pageIndex: number,
  options: {
    currentPageIndex?: number
    generation?: number
    prefetchAdjacent?: boolean
  } = {},
): Promise<void> {
  const generation = options.generation ?? videoLoadGeneration
  if (!video.value || !isCurrentVideoLoadGeneration(generation)) {
    return
  }

  await ensureFramePageLoadedInCache({
    state: framePageCacheState as FramePageCacheState<ResearchVideoFrame>,
    pageIndex,
    totalCount: totalFrames.value,
    generation,
    isCurrentGeneration: isCurrentVideoLoadGeneration,
    loadPage: async ({ generation: requestGeneration, offset, limit, pageIndex: requestedPageIndex }) => {
      if (!isCurrentVideoLoadGeneration(requestGeneration)) {
        return null
      }
      const page = await researchVideosStore.fetchVideoFramesPage(Number(props.videoId), {
        offset,
        limit,
      })
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

  if (options.prefetchAdjacent !== false) {
    scheduleFramePagePrefetch(pageIndex + 1, generation, options.currentPageIndex ?? pageIndex)
  }
}

async function ensureFrameLoaded(
  frameIndex: number,
  options: {
    generation?: number
    prefetchAdjacent?: boolean
  } = {},
): Promise<ResearchVideoFrame | undefined> {
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

function getInitialFrameIndex(totalCount: number) {
  if (totalCount <= 0) {
    return 0
  }
  return parseResearchFrameQuery(route.query.frame, totalCount)
}

function clearScheduledFramePagePrefetches() {
  for (const timerId of framePagePrefetchTimers) {
    window.clearTimeout(timerId)
  }
  framePagePrefetchTimers.clear()
}

function scheduleFramePagePrefetch(pageIndex: number, generation: number, currentPageIndex: number) {
  if (
    !isCurrentVideoLoadGeneration(generation) ||
    pageIndex < 0 ||
    getFramePageOffsetInVideo(pageIndex) >= totalFrames.value ||
    framePages.has(pageIndex) ||
    loadingFramePages.has(pageIndex)
  ) {
    return
  }

  const timerId = window.setTimeout(() => {
    framePagePrefetchTimers.delete(timerId)
    if (!isCurrentVideoLoadGeneration(generation)) {
      return
    }
    void ensureFramePageLoaded(pageIndex, {
      currentPageIndex,
      generation,
      prefetchAdjacent: false,
    })
  }, 0)
  framePagePrefetchTimers.add(timerId)
}

function updateCurrentFrameAnnotations(nextAnnotations: AnnotationObject[]) {
  if (!currentFrame.value) {
    return
  }
  annotationsByFrame.value = {
    ...annotationsByFrame.value,
    [currentFrame.value.frame_index]: nextAnnotations.map((annotation) => ({
      ...(annotation as ResearchVideoAnnotation),
      frame_id: currentFrame.value?.id ?? 0,
      frame_index: currentFrame.value?.frame_index ?? 0,
      visible: true,
    })),
  }
  hasUnsavedChanges.value = true
}

async function saveAnnotations() {
  if (!currentFrame.value) {
    return true
  }
  const saved = await researchVideosStore.saveVideoFrameAnnotations(
    Number(props.videoId),
    currentFrame.value.frame_index,
    currentFrameAnnotations.value.map((annotation) => ({
      label_id: annotation.label_id,
      shape_type: annotation.shape_type,
      points: clonePoints(annotation.points),
      attributes: annotation.attributes ?? null,
      visible: true,
    })),
  )
  if (!saved) {
    ElMessage.error(translateApiErrorMessage(researchVideosStore.error, t) || t('common.saveFailed'))
    return false
  }
  await loadFrameAnnotations(currentFrame.value.frame_index)
  hasUnsavedChanges.value = false
  ElMessage.success(t('frameAnnotation.currentFrameSaved'))
  return true
}

async function goToFrame(index: number) {
  if (index < 0 || index >= totalFrames.value) {
    return false
  }
  if (index === selectedFrameIndex.value && currentFrame.value) {
    return true
  }
  const generation = videoLoadGeneration
  const previousFrameIndex = selectedFrameIndex.value
  const sequence = ++frameNavigationSequence
  if (hasUnsavedChanges.value) {
    const saved = await saveAnnotations()
    if (!saved || sequence !== frameNavigationSequence || !isCurrentVideoLoadGeneration(generation)) {
      return false
    }
  }
  selectedFrameIndex.value = index
  const frame = await ensureFrameLoaded(index, { generation, prefetchAdjacent: true })
  if (sequence !== frameNavigationSequence || !isCurrentVideoLoadGeneration(generation)) {
    return false
  }
  if (!frame) {
    selectedFrameIndex.value = previousFrameIndex
    return false
  }
  if (!annotationsByFrame.value[frame.frame_index]) {
    await loadFrameAnnotations(frame.frame_index, generation)
    if (sequence !== frameNavigationSequence || !isCurrentVideoLoadGeneration(generation)) {
      return false
    }
  }
  const frameTimeSeconds = getFrameTimeSeconds(frame)
  if (videoRef.value && Number.isFinite(frameTimeSeconds)) {
    videoRef.value.currentTime = frameTimeSeconds
  }
  currentVideoTimeMs.value = frame.timestamp_ms
  return true
}

function goPrevious() {
  void goToFrame(selectedFrameIndex.value - 1)
}

function goNext() {
  void goToFrame(selectedFrameIndex.value + 1)
}

function deleteAnnotation(id?: number | string | null) {
  const targetId = id ?? selectedAnnotationId.value
  if (targetId === null || !currentFrame.value) {
    return
  }
  updateCurrentFrameAnnotations(currentFrameAnnotations.value.filter((annotation) => annotation.id !== targetId))
  selectedAnnotationId.value = null
}

function selectAnnotation(id: number | string | null) {
  selectedAnnotationId.value = id
}

function toggleAnnotationVisibility(id: number | string) {
  if (hiddenAnnotationIds.value.includes(id)) {
    hiddenAnnotationIds.value = hiddenAnnotationIds.value.filter((item) => item !== id)
    return
  }
  hiddenAnnotationIds.value = [...hiddenAnnotationIds.value, id]
}

function showAllAnnotations() {
  hiddenAnnotationIds.value = []
}

function hideAllAnnotations() {
  hiddenAnnotationIds.value = currentFrameAnnotations.value.map((annotation) => annotation.id)
}

function updateAnnotationLabel(id: number | string, labelId: number) {
  updateCurrentFrameAnnotations(
    currentFrameAnnotations.value.map((annotation) => (
      annotation.id === id ? normalizeAnnotationObject({ ...annotation, label_id: labelId }) : annotation
    )),
  )
}

function updatePolygonSmoothing() {}
function commitPolygonSmoothing() {}
function resetPolygonSmoothing() {}
function startBoundaryAssist() {
  ElMessage.info(t('frameAnnotation.createLayerNotReady'))
}

async function generateSam2Mask() {
  if (!currentCanvasImage.value) {
    return
  }
  if (!selectedLabelId.value) {
    ElMessage.warning(t('frameAnnotation.selectLabelFirst'))
    return
  }
  const prompt = canvasRef.value?.getSam2Prompt()
  if (!prompt || (prompt.point_coords.length === 0 && prompt.box === null)) {
    ElMessage.warning(t('frameAnnotation.addPromptFirst'))
    return
  }
  generatingSam2.value = true
  try {
    const generated = await canvasRef.value?.runSamPrediction()
    if (!generated) {
      throw new Error(t('frameAnnotation.sam2PredictionFailed'))
    }
    ElMessage.success(t('frameAnnotation.sam2PreviewGenerated'))
  } catch (samError) {
    ElMessage.error(samError instanceof Error ? samError.message : t('frameAnnotation.sam2PredictionFailed'))
  } finally {
    generatingSam2.value = false
  }
}

function applyRefinedSam2Polygon(annotationId: number | string, points: number[][]) {
  const target = currentFrameAnnotations.value.find((annotation) => annotation.id === annotationId)
  if (!target) {
    return false
  }
  updateCurrentFrameAnnotations(
    currentFrameAnnotations.value.map((annotation) => (
      annotation.id === annotationId
        ? normalizeAnnotationObject({
            ...annotation,
            points: clonePoints(points),
            attributes: {
              ...(annotation.attributes ?? {}),
              refined_by: 'sam2',
              refined_at: new Date().toISOString(),
            },
          })
        : annotation
    )),
  )
  return true
}

function acceptSam2Mask() {
  const preview = canvasRef.value?.acceptSam2Preview?.()
  if (!preview || !currentFrame.value || !selectedLabelId.value) {
    ElMessage.warning(t('frameAnnotation.noSam2Preview'))
    return
  }
  if (preview.source === 'refine_annotation' && preview.targetAnnotationId !== null) {
    if (applyRefinedSam2Polygon(preview.targetAnnotationId, preview.points)) {
      ElMessage.success(t('frameAnnotation.polygonRefined'))
      return
    }
  }
  const nextAnnotation = normalizeAnnotationObject({
    id: `local_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`,
    image_id: currentFrame.value.id,
    label_id: selectedLabelId.value,
    shape_type: 'polygon',
    points: clonePoints(preview.points),
    attributes: preview.score === null ? null : { tracking_score: preview.score },
  })
  updateCurrentFrameAnnotations([...currentFrameAnnotations.value, nextAnnotation])
  selectedAnnotationId.value = nextAnnotation.id
  ElMessage.success(t('frameAnnotation.sam2Accepted'))
}

function rejectSam2Mask() {
  canvasRef.value?.rejectSam2Preview()
}

async function handleRefineSelectedPolygonWithSam2(annotationId: number | string) {
  const annotation = currentFrameAnnotations.value.find((item) => item.id === annotationId)
  if (!annotation || annotation.shape_type !== 'polygon') {
    ElMessage.warning(t('frameAnnotation.selectPolygonFirst'))
    return
  }
  generatingSam2.value = true
  try {
    const refined = await canvasRef.value?.refineSelectedPolygonWithSam2?.(annotation)
    if (!refined) {
      throw new Error(t('frameAnnotation.sam2RefineFailed'))
    }
    ElMessage.success(t('frameAnnotation.sam2RefinePreviewGenerated'))
  } catch (samError) {
    ElMessage.error(samError instanceof Error ? samError.message : t('frameAnnotation.sam2RefineFailed'))
  } finally {
    generatingSam2.value = false
  }
}

function onVideoPlay() {
  isPlaying.value = true
  updateCurrentVideoTime()
}

function onVideoPause() {
  isPlaying.value = false
  updateCurrentVideoTime()
  syncFrameFromVideo()
}

function onVideoLoadedMetadata() {
  if (videoRef.value) {
    const targetFrame = currentFrame.value ?? getFrameAt(selectedFrameIndex.value)
    if (targetFrame) {
      videoRef.value.currentTime = getFrameTimeSeconds(targetFrame)
    } else if (video.value?.fps) {
      videoRef.value.currentTime = selectedFrameIndex.value / video.value.fps
    }
  }
  updateCurrentVideoTime()
}

function onVideoTimeUpdate() {
  updateCurrentVideoTime()
}

function updateCurrentVideoTime() {
  currentVideoTimeMs.value = Math.round((videoRef.value?.currentTime ?? 0) * 1000)
}

function syncFrameFromVideo() {
  if (!videoRef.value || !video.value?.fps || totalFrames.value === 0) {
    return
  }
  const target = Math.min(
    Math.max(Math.round(videoRef.value.currentTime * video.value.fps), 0),
    totalFrames.value - 1,
  )
  if (target !== selectedFrameIndex.value) {
    void goToFrame(target)
  }
  updateCurrentVideoTime()
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

function clearGoToFrameError() {
  gotoFrameError.value = ''
}

function resetGoToFrameInput() {
  gotoFrameError.value = ''
  gotoFrameInput.value = currentFrameNumber.value > 0 ? String(currentFrameNumber.value) : ''
  gotoFrameInputRef.value?.blur()
}

function handleGoToFrameFocus() {
  gotoFrameFocused.value = true
}

function handleGoToFrameBlur() {
  gotoFrameFocused.value = false
}

function parseGoToFrameInput() {
  if (totalFrames.value <= 0) {
    const message = t('phaseAnnotation.framesStillLoading')
    gotoFrameError.value = message
    ElMessage.warning(message)
    return null
  }

  const normalizedInput = gotoFrameInput.value.trim()
  const rangeMessage = `Frame number must be between 1 and ${totalFrames.value}.`

  if (!normalizedInput || !/^\d+$/.test(normalizedInput)) {
    gotoFrameError.value = rangeMessage
    ElMessage.warning(rangeMessage)
    return null
  }

  const frameNumber = Number.parseInt(normalizedInput, 10)
  if (!Number.isInteger(frameNumber) || frameNumber < 1 || frameNumber > totalFrames.value) {
    gotoFrameError.value = rangeMessage
    ElMessage.warning(rangeMessage)
    return null
  }

  gotoFrameError.value = ''
  return frameNumber
}

async function submitGoToFrame() {
  if (isJumpingToFrame.value) {
    return
  }

  const frameNumber = parseGoToFrameInput()
  if (frameNumber === null) {
    return
  }

  isJumpingToFrame.value = true
  try {
    const navigated = await goToFrame(frameNumber - 1)
    if (!navigated) {
      return
    }
    gotoFrameError.value = ''
    gotoFrameInput.value = String(frameNumber)
    gotoFrameInputRef.value?.blur()
  } finally {
    isJumpingToFrame.value = false
  }
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

function handleViewportResize() {
  viewportHeight.value = window.innerHeight
  if (isVideoFullWorkspace.value) {
    playerPaneHeight.value = getWorkspaceHeight()
    return
  }
  if (workspaceMode.value === 'split') {
    playerPaneHeight.value = clampPlayerHeight(playerPaneHeight.value)
  }
  void refreshCanvasAfterLayoutChange()
}

function initializeAnnotationPaneResizeObserver() {
  annotationPaneResizeObserver?.disconnect()
  if (!annotationPaneRef.value || typeof ResizeObserver === 'undefined') {
    return
  }

  annotationPaneResizeObserver = new ResizeObserver((entries) => {
    const entry = entries[0]
    if (!entry) {
      return
    }
    const nextWidth = entry.contentRect.width
    const nextHeight = entry.contentRect.height
    if (
      Math.abs(nextWidth - lastObservedAnnotationPaneWidth) < RESIZE_OBSERVER_EPSILON &&
      Math.abs(nextHeight - lastObservedAnnotationPaneHeight) < RESIZE_OBSERVER_EPSILON
    ) {
      return
    }
    lastObservedAnnotationPaneWidth = nextWidth
    lastObservedAnnotationPaneHeight = nextHeight
    if (isResizingPlayer.value || isVideoFullWorkspace.value || isPlayerCollapsed.value) {
      return
    }
    scheduleCanvasViewportRefresh()
  })
  annotationPaneResizeObserver.observe(annotationPaneRef.value)
}

function scheduleCanvasViewportRefresh(force = false) {
  if (!force && (isVideoFullWorkspace.value || isPlayerCollapsed.value)) {
    return
  }
  if (scheduledViewportRefreshFrame) {
    window.cancelAnimationFrame(scheduledViewportRefreshFrame)
  }
  scheduledViewportRefreshFrame = window.requestAnimationFrame(() => {
    canvasRef.value?.refreshViewport?.()
    scheduledViewportRefreshFrame = 0
  })
}

function getWorkspaceHeight() {
  return splitPaneRef.value?.clientHeight ?? viewportHeight.value
}

function getPlayerHeightBounds(workspaceHeight = getWorkspaceHeight()) {
  return getResearchPlayerHeightBounds({
    viewportHeight: viewportHeight.value,
    workspaceHeight,
    splitHandleHeight: splitHandleSize.value,
  })
}

function clampPlayerHeight(nextHeight: number, workspaceHeight = getWorkspaceHeight()) {
  return clampResearchPlayerHeight(nextHeight, {
    viewportHeight: viewportHeight.value,
    workspaceHeight,
    splitHandleHeight: splitHandleSize.value,
  })
}

function defaultPlayerHeightForViewport() {
  return getDefaultResearchPlayerHeight({
    viewportHeight: viewportHeight.value,
    workspaceHeight: getWorkspaceHeight(),
    splitHandleHeight: splitHandleSize.value,
  })
}

function persistPlayerLayoutPreferences() {
  window.localStorage.setItem(PLAYER_HEIGHT_STORAGE_KEY, String(playerPaneHeight.value))
  window.localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, workspaceMode.value)
  window.localStorage.setItem(PLAYER_COLLAPSED_STORAGE_KEY, String(isPlayerCollapsed.value))
}

function restorePlayerLayoutPreferences() {
  viewportHeight.value = window.innerHeight
  const storedHeight = window.localStorage.getItem(PLAYER_HEIGHT_STORAGE_KEY)
  const storedMode = window.localStorage.getItem(WORKSPACE_MODE_STORAGE_KEY) as ResearchWorkspaceMode | null
  const storedCollapsed = window.localStorage.getItem(PLAYER_COLLAPSED_STORAGE_KEY)
  playerHeightBeforeMaximize.value = null

  if (storedMode === 'video_collapsed' || storedMode === 'video_full' || storedMode === 'split') {
    workspaceMode.value = storedMode
  } else if (storedCollapsed === null) {
    workspaceMode.value = window.innerHeight < 650 ? 'video_collapsed' : 'split'
  } else {
    workspaceMode.value = storedCollapsed === 'true' ? 'video_collapsed' : 'split'
  }

  const parsedHeight = storedHeight ? Number.parseInt(storedHeight, 10) : Number.NaN
  playerPaneHeight.value = Number.isFinite(parsedHeight)
    ? clampPlayerHeight(parsedHeight)
    : defaultPlayerHeightForViewport()
  if (isVideoFullWorkspace.value) {
    playerPaneHeight.value = getWorkspaceHeight()
  }
}

function togglePlayerCollapsed() {
  if (isPlayerCollapsed.value) {
    enterSplitMode(playerHeightBeforeMaximize.value ?? defaultPlayerHeightForViewport())
    return
  }
  if (workspaceMode.value === 'split') {
    playerHeightBeforeMaximize.value = playerPaneHeight.value
  } else if (playerHeightBeforeMaximize.value === null) {
    playerHeightBeforeMaximize.value = defaultPlayerHeightForViewport()
  }
  workspaceMode.value = 'video_collapsed'
  persistPlayerLayoutPreferences()
  void refreshCanvasAfterLayoutChange()
}

function togglePlayerMaximized() {
  if (isPlayerCollapsed.value) {
    return
  }
  if (isVideoFullWorkspace.value) {
    enterSplitMode(playerHeightBeforeMaximize.value ?? defaultPlayerHeightForViewport())
    return
  }

  enterFullVideoMode()
}

function startPlayerResize(event: PointerEvent) {
  if (isPlayerCollapsed.value || isVideoFullWorkspace.value) {
    return
  }
  event.preventDefault()
  pendingWorkspaceMode = null
  pendingSplitRestoreHeight = null
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
  const deltaY = event.clientY - playerResizeStartY.value
  const nextHeight = clampPlayerHeight(playerResizeStartHeight.value + deltaY)
  const remainingAnnotationHeight = Math.max(0, getWorkspaceHeight() - splitHandleSize.value - nextHeight)
  if (remainingAnnotationHeight <= FULL_VIDEO_SNAP_THRESHOLD) {
    pendingWorkspaceMode = 'video_full'
    pendingPlayerPaneHeight = getWorkspaceHeight()
    pendingSplitRestoreHeight = nextHeight
  } else {
    pendingWorkspaceMode = 'split'
    pendingPlayerPaneHeight = nextHeight
    pendingSplitRestoreHeight = null
  }
  if (scheduledPlayerResizeFrame) {
    return
  }
  scheduledPlayerResizeFrame = window.requestAnimationFrame(() => {
    if (pendingWorkspaceMode) {
      workspaceMode.value = pendingWorkspaceMode
    }
    if (pendingPlayerPaneHeight !== null) {
      playerPaneHeight.value = pendingPlayerPaneHeight
      pendingPlayerPaneHeight = null
    }
    pendingWorkspaceMode = null
    scheduledPlayerResizeFrame = 0
  })
}

function stopPlayerResize() {
  if (!isResizingPlayer.value) {
    return
  }
  if (scheduledPlayerResizeFrame) {
    window.cancelAnimationFrame(scheduledPlayerResizeFrame)
    scheduledPlayerResizeFrame = 0
  }
  if (pendingPlayerPaneHeight !== null) {
    playerPaneHeight.value = pendingPlayerPaneHeight
    pendingPlayerPaneHeight = null
  }
  if (pendingWorkspaceMode) {
    workspaceMode.value = pendingWorkspaceMode
    pendingWorkspaceMode = null
  }
  if (workspaceMode.value === 'video_full' && pendingSplitRestoreHeight !== null) {
    playerHeightBeforeMaximize.value = clampPlayerHeight(pendingSplitRestoreHeight)
  }
  pendingSplitRestoreHeight = null
  isResizingPlayer.value = false
  persistPlayerLayoutPreferences()
  window.removeEventListener('pointermove', handlePlayerResizeMove)
  window.removeEventListener('pointerup', stopPlayerResize)
  window.removeEventListener('pointercancel', stopPlayerResize)
  if (workspaceMode.value === 'split') {
    void refreshCanvasAfterLayoutChange()
  }
}

function enterSplitMode(nextHeight: number) {
  workspaceMode.value = 'split'
  playerPaneHeight.value = clampPlayerHeight(nextHeight)
  playerHeightBeforeMaximize.value = null
  persistPlayerLayoutPreferences()
  void refreshCanvasAfterLayoutChange()
}

function enterFullVideoMode() {
  if (workspaceMode.value === 'split') {
    playerHeightBeforeMaximize.value = playerPaneHeight.value
  } else if (playerHeightBeforeMaximize.value === null) {
    playerHeightBeforeMaximize.value = defaultPlayerHeightForViewport()
  }
  workspaceMode.value = 'video_full'
  playerPaneHeight.value = getWorkspaceHeight()
  persistPlayerLayoutPreferences()
}

async function refreshCanvasAfterLayoutChange() {
  await nextTick()
  scheduleCanvasViewportRefresh(true)
}

function openRightPanel() {
  isRightPanelOpen.value = true
}

function closeRightPanel() {
  isRightPanelOpen.value = false
}

function toggleRightPanel() {
  isRightPanelOpen.value = !isRightPanelOpen.value
}

async function openLabelManager() {
  labelsLoading.value = true
  const labels = await researchVideosStore.fetchVideoLabels(Number(props.videoId))
  labelsLoading.value = false
  if (!labels) {
    ElMessage.error(translateApiErrorMessage(researchVideosStore.error, t) || t('frameAnnotation.failedLoadLabels'))
    return
  }
  labelDrafts.value = labels.map((label) => ({ ...label }))
  labelManagerVisible.value = true
}

function closeLabelManager() {
  if (labelActionLoading.value) {
    return
  }
  labelManagerVisible.value = false
}

async function addManagedLabel() {
  if (!newLabelName.value.trim()) {
    ElMessage.warning(t('frameAnnotation.labelNameRequired'))
    return
  }
  labelActionLoading.value = true
  try {
    const created = await researchVideosStore.createVideoLabel(Number(props.videoId), {
      name: newLabelName.value.trim(),
      color: newLabelColor.value,
      shape_type: newLabelShapeType.value,
    })
    if (!created) {
      throw new Error(researchVideosStore.error || t('frameAnnotation.failedCreateLabel'))
    }
    workspaceVideo.value = await researchVideosStore.fetchVideoWorkspace(Number(props.videoId))
    const labels = await researchVideosStore.fetchVideoLabels(Number(props.videoId))
    labelDrafts.value = labels?.map((label) => ({ ...label })) ?? []
    selectedLabelId.value = created.id
    newLabelName.value = ''
    ElMessage.success(t('frameAnnotation.labelCreated'))
  } catch (labelError) {
    ElMessage.error(labelError instanceof Error ? labelError.message : t('frameAnnotation.failedCreateLabel'))
  } finally {
    labelActionLoading.value = false
  }
}

function formatTimestamp(timestampMs: number) {
  const totalSeconds = Math.floor(timestampMs / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  const milliseconds = Math.floor((timestampMs % 1000) / 10)
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(milliseconds).padStart(2, '0')}`
}

function startDevMeasure(name: string) {
  if (!import.meta.env.DEV || typeof window === 'undefined' || typeof window.performance === 'undefined') {
    return () => undefined
  }
  const startMark = `${name}-start`
  const endMark = `${name}-end`
  window.performance.mark(startMark)
  return () => {
    window.performance.mark(endMark)
    window.performance.measure(name, startMark, endMark)
    const entries = window.performance.getEntriesByName(name)
    const latestEntry = entries[entries.length - 1]
    if (latestEntry) {
      console.info(`[perf] ${name}: ${latestEntry.duration.toFixed(1)}ms`)
    }
    window.performance.clearMarks(startMark)
    window.performance.clearMarks(endMark)
    window.performance.clearMeasures(name)
  }
}
</script>

<template>
  <main class="annotate-page research-annotate-page">
    <aside class="annotate-sidebar annotation-sidebar-left">
      <div class="sidebar-header">
        <router-link to="/research/videos" class="annotate-back">
          <el-icon><Back /></el-icon>
          Research Videos
        </router-link>

        <div>
          <p class="eyebrow">{{ t('frameAnnotation.eyebrow') }}</p>
          <h1 class="research-video-title job-title" :title="video?.name ?? `Video ${videoId}`">
            {{ video?.name ?? `Video ${videoId}` }}
          </h1>
          <p class="job-subtitle">{{ t('frameAnnotation.experimentalWorkspace') }}</p>
        </div>

        <ResearchVideoTaskNav
          :active-task="'frame'"
          :current-frame-index="selectedFrameIndex"
          :video-id="videoId"
        />

        <section class="tool-panel">
          <p class="panel-label">{{ t('frameAnnotation.tool') }}</p>
          <div class="annotation-tool-grid">
            <button
              v-for="toolName in toolOptions"
              :key="toolName"
              class="annotation-tool-button"
              :class="{ active: tool === toolName }"
              type="button"
              @click="tool = toolName"
            >
              {{ toolName }}
            </button>
            <button
              class="annotation-tool-button annotation-tool-button-sam2"
              :class="{ active: tool === 'sam2' }"
              type="button"
              @click="tool = 'sam2'"
            >
              sam2
            </button>
          </div>
        </section>
      </div>

      <div class="sidebar-middle">
        <div class="sidebar-settings-labels sidebar-label-settings-scroll">
          <section class="tool-panel sidebar-labels">
            <div class="panel-label-row">
              <p class="panel-label">{{ t('frameAnnotation.label') }}</p>
              <button class="panel-link-button" type="button" @click="openLabelManager">
                Manage
              </button>
            </div>
            <div class="label-list">
              <button
                v-for="label in currentLabelList"
                :key="label.id"
                class="label-choice"
                :class="{ active: selectedLabelId === label.id }"
                type="button"
                @click="selectedLabelId = label.id"
              >
                <span class="label-swatch" :style="{ backgroundColor: label.color }"></span>
                {{ label.name }}
              </button>
            </div>
          </section>
        </div>

        <div class="sidebar-frames">
          <p class="panel-label">{{ t('frameAnnotation.videoFrames') }}</p>
          <VirtualFrameList
            :total-count="totalFrames"
            :selected-frame-index="selectedFrameIndex"
            :get-frame="getFrameAt"
            @request-range="requestFrameRange"
            @select="goToFrame"
          />
        </div>
      </div>

      <div class="sidebar-footer sidebar-bottom annotate-actions">
        <el-button :icon="Delete" @click="deleteAnnotation()">{{ t('frameAnnotation.deleteCurrent') }}</el-button>
        <el-button :loading="saving" type="primary" :icon="Finished" @click="saveAnnotations">
          {{ t('common.save') }}
        </el-button>
      </div>
    </aside>

    <section class="annotate-stage annotation-main">
      <header class="annotate-stage-bar research-video-stage-bar">
        <div class="annotate-stage-title">
          <strong>{{ currentFrame?.filename ?? `Frame ${currentFrameNumber}` }}</strong>
          <span v-if="currentFrame">
            {{ currentFrame.width }} x {{ currentFrame.height }} · Frame {{ currentFrameNumber }} / {{ totalFrames }}
          </span>
          <span v-else-if="totalFrames">
            Loading frame {{ currentFrameNumber }} / {{ totalFrames }}
          </span>
        </div>
        <div class="annotation-toolbar">
          <div class="toolbar-group toolbar-group-frames">
            <el-button :disabled="isFirstFrame || saving" @click="goPrevious">{{ t('frameAnnotation.previousFrame') }}</el-button>
            <el-button :disabled="!video?.file_url" @click="togglePlayback">
              <el-icon><VideoPause v-if="isPlaying" /><VideoPlay v-else /></el-icon>
              {{ isPlaying ? t('frameAnnotation.pause') : t('frameAnnotation.play') }}
            </el-button>
            <VideoPlaybackRateControl compact />
            <el-button :disabled="isLastFrame || saving" @click="goNext">{{ t('frameAnnotation.nextFrame') }}</el-button>
            <span class="frame-counter">{{ currentFrameNumber }} / {{ totalFrames }}</span>
            <span class="research-frame-goto">
              <span class="research-frame-goto-label">{{ t('common.goTo') }}:</span>
              <input
                ref="gotoFrameInputRef"
                v-model="gotoFrameInput"
                class="research-frame-goto-input"
                :class="{ 'has-error': gotoFrameError }"
                :aria-invalid="Boolean(gotoFrameError)"
                :disabled="!totalFrames || isJumpingToFrame"
                :title="gotoFrameError || t('frameAnnotation.jumpToFrame')"
                autocomplete="off"
                inputmode="numeric"
                pattern="[0-9]*"
                spellcheck="false"
                type="text"
                @blur="handleGoToFrameBlur"
                @focus="handleGoToFrameFocus"
                @input="clearGoToFrameError"
                @keydown.enter.prevent="submitGoToFrame"
                @keydown.esc.prevent="resetGoToFrameInput"
              />
              <el-button :disabled="!totalFrames || isJumpingToFrame" :loading="isJumpingToFrame" @click="submitGoToFrame">
                Go
              </el-button>
            </span>
            <span class="frame-counter" v-if="currentFrame">{{ formatTimestamp(currentFrame.timestamp_ms) }}</span>
          </div>

          <div class="toolbar-group" v-if="tool === 'sam2'">
            <el-button :loading="generatingSam2" type="primary" @click="generateSam2Mask">
              Generate Mask
            </el-button>
            <el-button @click="acceptSam2Mask">{{ t('frameAnnotation.acceptMask') }}</el-button>
            <el-button @click="rejectSam2Mask">{{ t('frameAnnotation.rejectMask') }}</el-button>
          </div>

          <div class="toolbar-group">
            <el-button :loading="currentFrameLoading" @click="loadFrameAnnotations(currentFrame?.frame_index ?? 0)">
              <el-icon><RefreshRight /></el-icon>
              Reload frame
            </el-button>
            <el-button
              class="annotation-objects-toggle"
              :aria-expanded="isRightPanelOpen"
              @click="toggleRightPanel"
            >
              Objects {{ currentObjectCount }}
            </el-button>
          </div>
        </div>
      </header>

      <div class="research-video-workspace" :class="{ 'is-compact': isCompactResearchLayout }">
        <div
          ref="splitPaneRef"
          class="research-video-split"
          :class="{
            'is-player-collapsed': isPlayerCollapsed,
            'is-compact': isCompactResearchLayout,
            'is-resizing': isResizingPlayer,
            'is-video-full': isVideoFullWorkspace,
          }"
          :style="researchSplitStyle"
        >
          <section class="research-player-pane" :class="{ 'is-collapsed': isPlayerCollapsed }">
            <div class="research-player-pane-header">
              <div class="research-player-pane-heading">
                <strong>{{ t('frameAnnotation.videoPreview') }}</strong>
                <span>{{ playerPaneMetaText }}</span>
              </div>

              <div class="research-player-pane-actions">
                <span class="research-video-help-text" :title="t('frameAnnotation.videoHelp')">
                  Pause playback or select a frame to annotate.
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
                <button class="research-player-pane-action" type="button" :disabled="!video?.file_url" @click="togglePlayback">
                  {{ isPlaying ? t('frameAnnotation.pause') : t('frameAnnotation.play') }}
                </button>
                <button class="research-player-pane-action" type="button" @click="togglePlayerCollapsed">
                  Expand video
                </button>
              </div>
            </div>

            <div class="research-player-pane-body" :class="{ 'is-visually-collapsed': isPlayerCollapsed }">
              <div class="research-video-container">
                <video
                  v-if="video?.file_url"
                  ref="videoRef"
                  class="research-video-element"
                  controls
                  preload="metadata"
                  :src="video.file_url"
                  @loadedmetadata="onVideoLoadedMetadata"
                  @pause="onVideoPause"
                  @play="onVideoPlay"
                  @seeked="syncFrameFromVideo"
                  @timeupdate="onVideoTimeUpdate"
                />
              </div>
            </div>
          </section>

          <div
            class="research-split-handle"
            :class="{ 'is-hidden': isPlayerCollapsed }"
            role="separator"
            aria-orientation="horizontal"
            @pointerdown="startPlayerResize"
          >
            <span></span>
          </div>

          <section ref="annotationPaneRef" class="research-annotation-pane">
            <div v-if="currentCanvasImage" class="research-annotation-canvas-shell">
              <AnnotationCanvas
                ref="canvasRef"
                :image="currentCanvasImage"
                :labels="currentLabelList"
                :annotations="currentFrameAnnotations"
                :hidden-annotation-ids="hiddenAnnotationIds"
                :selected-annotation-id="selectedAnnotationId"
                :selected-label-id="selectedLabelId"
                :tracking-preview-points="null"
                :tracking-preview-variant="null"
                :sam2-settings="sam2Settings"
                :research-sam2-context="researchSam2Context"
                :boundary-assist-reference-annotation-id="null"
                :tool="tool"
                :user-settings="userSettings"
                @before-change="() => undefined"
                @change="updateCurrentFrameAnnotations"
                @select-object="selectAnnotation"
              />
            </div>

            <div v-else v-loading="loading" class="annotate-empty research-annotation-empty">
              <el-icon><Pointer /></el-icon>
              <p>{{ t('frameAnnotation.noFrameLoaded') }}</p>
            </div>
          </section>
        </div>
      </div>
    </section>

    <div
      class="annotation-right-panel-backdrop"
      :class="{ 'is-visible': isRightPanelOpen }"
      @click="closeRightPanel"
    ></div>

    <div class="annotate-right-panel-shell" :class="{ 'is-open': isRightPanelOpen }">
      <div class="right-panel-drawer-header">
        <strong>Objects {{ currentObjectCount }}</strong>
        <button type="button" @click="closeRightPanel">{{ t('common.close') }}</button>
      </div>

      <ObjectPanel
        class="annotate-right-panel"
        :annotations="currentFrameAnnotations"
        :hidden-annotation-ids="hiddenAnnotationIds"
        :labels="currentLabelList"
        :sam2-refining="generatingSam2"
        :sam2-tracking="false"
        :selected-annotation-id="selectedAnnotationId"
        @create-layer-above="startBoundaryAssist"
        @delete-annotation="deleteAnnotation"
        @hide-all="hideAllAnnotations"
        @refine-selected-polygon="handleRefineSelectedPolygonWithSam2"
        @track-with-sam2="() => ElMessage.info(t('frameAnnotation.trackPlanned'))"
        @show-all="showAllAnnotations"
        @select-annotation="selectAnnotation"
        @commit-polygon-smoothing="commitPolygonSmoothing"
        @reset-polygon-smoothing="resetPolygonSmoothing"
        @toggle-visibility="toggleAnnotationVisibility"
        @update-annotation-label="updateAnnotationLabel"
        @update-polygon-smoothing="updatePolygonSmoothing"
      />
    </div>

    <button
      class="right-panel-edge-toggle"
      :class="{ 'is-hidden': isRightPanelOpen }"
      type="button"
      @click="openRightPanel"
    >
      Objects {{ currentObjectCount }}
    </button>

    <div v-if="labelManagerVisible" class="app-modal-backdrop" @click.self="closeLabelManager">
      <section class="app-modal label-management-modal" @click.stop>
        <header class="label-management-modal-header">
          <div>
            <p class="eyebrow">{{ t('frameAnnotation.researchLabels') }}</p>
            <h2>{{ t('frameAnnotation.manageLabels') }}</h2>
            <span>{{ video?.name ?? `Video ${videoId}` }}</span>
          </div>
          <el-button :disabled="labelActionLoading" @click="closeLabelManager">{{ t('common.close') }}</el-button>
        </header>

        <div class="label-management-modal-body">
          <div class="label-management-table">
            <div class="label-management-row label-management-row-head">
              <span>{{ t('frameAnnotation.color') }}</span>
              <span>{{ t('frameAnnotation.name') }}</span>
              <span>{{ t('frameAnnotation.shape') }}</span>
              <span>{{ t('frameAnnotation.used') }}</span>
            </div>
            <div v-for="label in labelDrafts" :key="label.id" class="label-management-row">
              <input v-model="label.color" class="label-management-color" type="color" disabled />
              <input v-model="label.name" class="label-management-name" disabled type="text" />
              <select v-model="label.shape_type" class="label-management-shape" disabled>
                <option value="polygon">{{ t('frameAnnotation.polygon') }}</option>
                <option value="rectangle">{{ t('frameAnnotation.rectangle') }}</option>
                <option value="point">{{ t('frameAnnotation.point') }}</option>
              </select>
              <span class="label-management-used">{{ label.annotation_count }}</span>
            </div>
          </div>

          <section class="label-management-add">
            <h3>{{ t('frameAnnotation.addLabel') }}</h3>
            <div class="label-management-add-row">
              <input v-model="newLabelColor" class="label-management-color" type="color" />
              <input v-model="newLabelName" class="label-management-name" :placeholder="t('frameAnnotation.labelName')" type="text" />
              <select v-model="newLabelShapeType" class="label-management-shape">
                <option value="polygon">{{ t('frameAnnotation.polygon') }}</option>
                <option value="rectangle">{{ t('frameAnnotation.rectangle') }}</option>
                <option value="point">{{ t('frameAnnotation.point') }}</option>
              </select>
              <el-button type="primary" :loading="labelActionLoading" @click="addManagedLabel">
                {{ t('frameAnnotation.addLabel') }}
              </el-button>
            </div>
          </section>
        </div>
      </section>
    </div>
  </main>
</template>
