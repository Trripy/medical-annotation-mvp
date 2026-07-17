<script setup lang="ts">
import { Back, Delete, Finished, Pointer, RefreshRight } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AnnotationCanvas from '../components/AnnotationCanvas.vue'
import ObjectPanel from '../components/ObjectPanel.vue'
import {
  useAnnotationStore,
  type AnnotationObject,
  type Sam2ExistingAnnotationPolicy,
  type Sam2TrackDirection,
  type Sam2TrackVideoFrameResult,
  type Sam2TrackVideoResponse,
  type Label,
  type LabelDeleteStrategy,
  type LabelUsage,
  type ShapeType,
} from '../stores/annotation'
import {
  useUserSettingsStore,
  type Sam2Candidate,
  type Sam2ModelName,
  type UserSettings,
} from '../stores/userSettings'
import { useUsersStore } from '../stores/users'
import {
  LABEL_COLOR_PALETTE,
  isColorConflict,
  normalizeHexColor,
  pickDistinctLabelColor,
} from '../utils/labelColors'
import {
  buildPolygonSmoothingAttributes,
  clampPolygonSmoothValue,
  clonePoints,
  getPolygonRawPoints,
  getPolygonSmoothValue,
  normalizeAnnotationObject,
  simplifyPolygonRdp,
  sliderValueToSmoothEpsilon,
} from '../utils/polygon'

type ToolType = 'cursor' | 'rectangle' | 'polygon' | 'sam2' | 'classify'
type LabelKind = 'object_annotation' | 'image_classification'
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
type Sam2PreviewAcceptPayload = {
  points: number[][]
  score: number | null
  source: 'prompt' | 'refine_annotation'
  targetAnnotationId: number | string | null
}
type TrackOutputMode = 'preview_first' | 'direct_create'
type TrackingReviewStatus = 'pending' | 'accepted' | 'rejected' | 'needs_fix'
type TrackingCommitOutcome = 'saved' | 'skipped' | 'failed' | 'already_committed' | 'invalid'
type TrackWithSam2FormState = {
  direction: Sam2TrackDirection
  forwardEndFrameIndex: number
  backwardEndFrameIndex: number
  reviewInterval: number
  existingAnnotationPolicy: Sam2ExistingAnnotationPolicy
  outputMode: TrackOutputMode
}
type TrackingPreviewFrameResult = Sam2TrackVideoFrameResult & {
  review_status: TrackingReviewStatus
  committed: boolean
  fix_annotation_id?: number | string | null
}
type TrackingPreviewState = {
  jobId: number
  sourceAnnotationId: number | string | null
  sourceFrameIndex: number
  startFrameIndex: number
  endFrameIndex: number
  direction: Sam2TrackDirection
  existingAnnotationPolicy: Sam2ExistingAnnotationPolicy
  labelId: number
  modelName: string
  reviewInterval: number
  results: TrackingPreviewFrameResult[]
  reviewFrames: number[]
  warnings: string[]
}
type TrackingCommitContext = {
  jobId: number
  sourceAnnotationId: number | string | null
  sourceFrameIndex: number
  direction: Sam2TrackDirection
  existingAnnotationPolicy: Sam2ExistingAnnotationPolicy
  labelId: number
  modelName: string
  outputMode: TrackOutputMode
}
type PreparedTrackingCommit =
  | {
      outcome: 'invalid' | 'skipped'
    }
  | {
      outcome: 'prepared'
      nextAnnotations: AnnotationObject[]
      removedSameLabelCount: number
    }
type LabelDraft = {
  id: number
  name: string
  color: string
  shape_type: ShapeType
  annotation_count: number
  frame_count: number
}

const props = defineProps<{
  jobId: string
}>()

const route = useRoute()
const router = useRouter()
const annotationStore = useAnnotationStore()
const usersStore = useUsersStore()
const userSettingsStore = useUserSettingsStore()
const { job, loading, saving, error } = storeToRefs(annotationStore)
const { currentUsername } = storeToRefs(usersStore)
const { settings: userSettings } = storeToRefs(userSettingsStore)
const selectedImageIndex = ref(0)
const selectedLabelId = ref<number | null>(null)
const tool = ref<ToolType>('sam2')
const hasUserChangedTool = ref(false)
const canvasRef = ref<InstanceType<typeof AnnotationCanvas> | null>(null)
const goToIndex = ref('1')
const hasUnsavedChanges = ref(false)
const selectedAnnotationId = ref<number | string | null>(null)
const hiddenAnnotationIds = ref<Array<number | string>>([])
const generatingSam2 = ref(false)
const hasSam2Preview = ref(false)
const frameQueryReady = ref(false)
const undoStack = ref<AnnotationObject[][]>([])
const suppressNextSelectToolSwitch = ref(false)
const hasUserChangedSam2Settings = ref(false)
const sam2Settings = ref<Sam2Settings>(sam2SettingsFromUserSettings(userSettings.value))
const labelManagerVisible = ref(false)
const labelDrafts = ref<LabelDraft[]>([])
const labelManagerLoading = ref(false)
const labelActionLoading = ref(false)
const newLabelName = ref('')
const newLabelColor = ref('#22c55e')
const newLabelKind = ref<LabelKind>('object_annotation')
const newLabelShapeType = ref<ShapeType>('polygon')
const deleteLabelModalVisible = ref(false)
const pendingDeleteLabel = ref<LabelDraft | null>(null)
const pendingDeleteUsage = ref<LabelUsage | null>(null)
const deleteLabelStrategy = ref<LabelDeleteStrategy>('move_to_undefined')
const reassignTargetLabelId = ref<number | null>(null)
const activePolygonSmoothingAnnotationId = ref<number | string | null>(null)
const boundaryAssistReferenceAnnotationId = ref<number | string | null>(null)
const refiningSelectedPolygonWithSam2 = ref(false)
const trackWithSam2DialogVisible = ref(false)
const trackingReviewDialogVisible = ref(false)
const trackingWithSam2 = ref(false)
const acceptingTrackingPreview = ref(false)
const trackingDialogAnnotationId = ref<number | string | null>(null)
const trackingReviewRangeStart = ref(0)
const trackingReviewRangeEnd = ref(0)
const isRightPanelOpen = ref(false)
const trackWithSam2Form = ref<TrackWithSam2FormState>({
  direction: 'forward',
  forwardEndFrameIndex: 0,
  backwardEndFrameIndex: 0,
  reviewInterval: 10,
  existingAnnotationPolicy: 'skip_same_label',
  outputMode: 'preview_first',
})
const trackingPreviewState = ref<TrackingPreviewState | null>(null)

const currentImage = computed(() => job.value?.images[selectedImageIndex.value] ?? null)
const totalImages = computed(() => job.value?.images.length ?? 0)
const currentImageNumber = computed(() => (currentImage.value ? selectedImageIndex.value + 1 : 0))
const isFirstImage = computed(() => selectedImageIndex.value <= 0)
const isLastImage = computed(() => selectedImageIndex.value >= totalImages.value - 1)
const canTrackForwardFromCurrentFrame = computed(() => totalImages.value > 1 && !isLastImage.value)
const canTrackBackwardFromCurrentFrame = computed(() => totalImages.value > 1 && !isFirstImage.value)
const canTrackBothDirectionsFromCurrentFrame = computed(() =>
  canTrackForwardFromCurrentFrame.value || canTrackBackwardFromCurrentFrame.value,
)
const jobsBackRoute = computed(() =>
  job.value?.project_id !== null && job.value?.project_id !== undefined
    ? `/jobs/projects/${job.value.project_id}`
    : '/jobs',
)
const currentImageAnnotations = computed(() => {
  if (!currentImage.value || !job.value) {
    return []
  }

  return job.value.annotations.filter((annotation) => annotation.image_id === currentImage.value?.id)
})
const objectLabels = computed(() => (job.value?.labels ?? []).filter((label) => !isClassificationLabel(label)))
const classificationLabels = computed(() => (job.value?.labels ?? []).filter((label) => isClassificationLabel(label)))
const classificationLabelIds = computed(() => new Set(classificationLabels.value.map((label) => label.id)))
const currentImageObjectAnnotations = computed(() =>
  currentImageAnnotations.value.filter((annotation) => !isClassificationAnnotation(annotation)),
)
const objectLabelDrafts = computed(() => labelDrafts.value.filter((label) => !isClassificationLabel(label)))
const classificationLabelDrafts = computed(() => labelDrafts.value.filter((label) => isClassificationLabel(label)))
const canUseClassificationTool = computed(() => classificationLabels.value.length > 0)
const classificationAnnotationsByImageId = computed(() => {
  const map = new Map<number, AnnotationObject>()
  if (!job.value) {
    return map
  }

  for (const annotation of job.value.annotations) {
    if (!isClassificationAnnotation(annotation)) {
      continue
    }
    map.set(annotation.image_id, annotation)
  }
  return map
})
const currentImageClassificationAnnotation = computed(() =>
  currentImage.value ? classificationAnnotationsByImageId.value.get(currentImage.value.id) ?? null : null,
)
const currentImageClassificationLabelId = computed(() => currentImageClassificationAnnotation.value?.label_id ?? null)
const currentImageClassificationLabel = computed(() =>
  currentImageClassificationLabelId.value !== null
    ? classificationLabels.value.find((label) => label.id === currentImageClassificationLabelId.value) ?? null
    : null,
)
const classificationFrameBadges = computed(() => {
  const map = new Map<number, { label: string; color: string }>()
  for (const [imageId, annotation] of classificationAnnotationsByImageId.value.entries()) {
    const label = classificationLabels.value.find((item) => item.id === annotation.label_id)
    if (label) {
      map.set(imageId, { label: label.name, color: label.color })
    }
  }
  return map
})
const canUndo = computed(() => undoStack.value.length > 0)
const trackingDialogTargetAnnotation = computed(() =>
  currentImageAnnotations.value.find((annotation) => annotation.id === trackingDialogAnnotationId.value) ?? null,
)
const trackingDialogTargetLabel = computed(() => {
  const labelId = trackingDialogTargetAnnotation.value?.label_id ?? null
  return job.value?.labels.find((label) => label.id === labelId) ?? null
})
const trackingPreviewMap = computed(() =>
  new Map((trackingPreviewState.value?.results ?? []).map((result) => [result.image_id, result])),
)
const currentTrackingPreviewResult = computed(() =>
  currentImage.value ? trackingPreviewMap.value.get(currentImage.value.id) ?? null : null,
)
const currentTrackingFixAnnotation = computed(() => {
  const result = currentTrackingPreviewResult.value
  if (!result?.fix_annotation_id) {
    return null
  }
  return currentImageAnnotations.value.find((annotation) => annotation.id === result.fix_annotation_id) ?? null
})
const currentTrackingPreviewPoints = computed(() => {
  const result = currentTrackingPreviewResult.value
  if (!result || result.status !== 'tracked' || !result.points || result.points.length < 3 || result.committed) {
    return null
  }
  if (result.review_status === 'needs_fix' && currentTrackingFixAnnotation.value) {
    return null
  }
  if (result.review_status === 'rejected') {
    return null
  }
  return result.points
})
const currentTrackingPreviewVariant = computed<'pending' | 'accepted' | 'needs_fix' | null>(() => {
  const result = currentTrackingPreviewResult.value
  if (!result || !currentTrackingPreviewPoints.value) {
    return null
  }
  if (result.review_status === 'accepted') {
    return 'accepted'
  }
  if (result.review_status === 'needs_fix') {
    return 'needs_fix'
  }
  return 'pending'
})
const trackingReviewFrameSet = computed(() => new Set(trackingPreviewState.value?.reviewFrames ?? []))
const trackingPreviewFailedCount = computed(() =>
  trackingPreviewState.value?.results.filter((result) => result.status === 'failed').length ?? 0,
)
const trackingPreviewProcessedCount = computed(() => trackingPreviewState.value?.results.length ?? 0)
const trackingPreviewPendingCount = computed(() =>
  trackingPreviewState.value?.results.filter((result) => result.status === 'tracked' && result.review_status === 'pending').length ?? 0,
)
const trackingPreviewAcceptedCount = computed(() =>
  trackingPreviewState.value?.results.filter((result) => result.status !== 'failed' && result.review_status === 'accepted').length ?? 0,
)
const trackingPreviewRejectedCount = computed(() =>
  trackingPreviewState.value?.results.filter((result) => result.status !== 'failed' && result.review_status === 'rejected').length ?? 0,
)
const trackingPreviewNeedsFixCount = computed(() =>
  trackingPreviewState.value?.results.filter((result) => result.status === 'tracked' && result.review_status === 'needs_fix').length ?? 0,
)
const trackingPreviewReviewFramesText = computed(() => {
  const reviewFrames = trackingPreviewState.value?.reviewFrames ?? []
  if (reviewFrames.length === 0) {
    return 'none'
  }
  if (reviewFrames.length <= 3) {
    return reviewFrames.join(', ')
  }
  return `${reviewFrames.slice(0, 3).join(', ')} ...`
})
const trackingPreviewDirectionText = computed(() =>
  trackingPreviewState.value ? formatTrackingDirection(trackingPreviewState.value.direction) : '',
)
const trackingPreviewCompactText = computed(() => {
  if (!trackingPreviewState.value) {
    return ''
  }
  return `Tracking preview · ${trackingPreviewDirectionText.value} · Pending ${trackingPreviewPendingCount.value} · Accepted ${trackingPreviewAcceptedCount.value} · Fix ${trackingPreviewNeedsFixCount.value} · Review ${trackingPreviewState.value.reviewFrames.length}`
})
const trackingPreviewMinFrameIndex = computed(() => {
  const results = trackingPreviewState.value?.results ?? []
  if (results.length === 0) {
    return 0
  }
  return Math.min(...results.map((result) => result.frame_index))
})
const trackingPreviewMaxFrameIndex = computed(() => {
  const results = trackingPreviewState.value?.results ?? []
  if (results.length === 0) {
    return 0
  }
  return Math.max(...results.map((result) => result.frame_index))
})
const currentTrackingFixAnnotationIsAcceptable = computed(() =>
  Boolean(
    currentTrackingPreviewResult.value?.review_status === 'needs_fix' &&
    currentTrackingFixAnnotation.value &&
    currentTrackingFixAnnotation.value.shape_type === 'polygon' &&
    currentTrackingFixAnnotation.value.points.length >= 3,
  ),
)
const currentTrackingFrameCanAccept = computed(() =>
  Boolean(
    currentTrackingPreviewResult.value &&
    !currentTrackingPreviewResult.value.committed &&
    (
      (
        trackingResultHasValidPolygon(currentTrackingPreviewResult.value) &&
        currentTrackingPreviewResult.value.review_status !== 'rejected' &&
        currentTrackingPreviewResult.value.review_status !== 'needs_fix'
      ) ||
      currentTrackingFixAnnotationIsAcceptable.value
    ),
  ),
)
const currentTrackingFrameCanFlag = computed(() =>
  Boolean(currentTrackingPreviewResult.value?.status === 'tracked' && !currentTrackingPreviewResult.value.committed),
)

onMounted(async () => {
  if (currentUsername.value) {
    await userSettingsStore.loadSettings(currentUsername.value)
    applyDefaultTool()
    applySam2DefaultsFromUserSettings()
  } else {
    userSettingsStore.resetToDefaults()
    applyDefaultTool()
    applySam2DefaultsFromUserSettings()
  }

  await annotationStore.fetchJob(props.jobId)
  applyInitialFrameSelection()
  frameQueryReady.value = true
  persistLastFrame()
  selectedLabelId.value = objectLabels.value[0]?.id ?? null
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('beforeunload', onBeforeUnload)
})

onBeforeUnmount(() => {
  persistLastFrame()
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('beforeunload', onBeforeUnload)
})

watch(selectedImageIndex, (index) => {
  goToIndex.value = String(currentImageNumber.value || 1)
  selectedAnnotationId.value = null
  hiddenAnnotationIds.value = []
  hasSam2Preview.value = false
  undoStack.value = []
  activePolygonSmoothingAnnotationId.value = null
  boundaryAssistReferenceAnnotationId.value = null
  if (frameQueryReady.value) {
    syncFrameQuery(index)
    persistLastFrame()
  }
})

watch(currentImageAnnotations, (annotations) => {
  if (
    boundaryAssistReferenceAnnotationId.value !== null &&
    !annotations.some((annotation) => annotation.id === boundaryAssistReferenceAnnotationId.value && annotation.shape_type === 'polygon')
  ) {
    boundaryAssistReferenceAnnotationId.value = null
  }
})

watch(objectLabels, () => {
  reconcileSelectedLabel()
})

watch(canUseClassificationTool, (available) => {
  if (!available && tool.value === 'classify') {
    tool.value = 'cursor'
  }
})

watch(
  () => route.query.frame,
  () => {
    if (!frameQueryReady.value || !job.value) {
      return
    }

    const nextIndex = frameIndexFromQuery()
    if (nextIndex !== selectedImageIndex.value) {
      selectedImageIndex.value = nextIndex
      return
    }

    syncFrameQuery(nextIndex)
  },
)

watch(
  () => userSettings.value.default_tool,
  () => {
    applyDefaultTool()
  },
)

watch(
  () => [
    userSettings.value.sam2_default_model,
    userSettings.value.sam2_default_multimask_output,
    userSettings.value.sam2_default_show_prompt_points,
    userSettings.value.sam2_default_candidate,
    userSettings.value.sam2_default_polygon_epsilon,
    userSettings.value.sam2_default_mask_threshold,
    userSettings.value.sam2_default_min_mask_area,
    userSettings.value.sam2_default_max_hole_area,
  ],
  () => {
    applySam2DefaultsFromUserSettings()
  },
)

watch(currentUsername, (username) => {
  if (!username) {
    userSettingsStore.resetToDefaults()
    applyDefaultTool()
    applySam2DefaultsFromUserSettings()
    return
  }

  void userSettingsStore.loadSettings(username).then(() => {
    applyDefaultTool()
    applySam2DefaultsFromUserSettings()
  })
})

function applyDefaultTool() {
  if (hasUserChangedTool.value) {
    return
  }

  tool.value = userSettings.value.default_tool
}

function setTool(nextTool: ToolType) {
  if (nextTool === 'classify' && !canUseClassificationTool.value) {
    ElMessage.info('Add image classification labels in Manage Labels first.')
    return
  }
  hasUserChangedTool.value = true
  tool.value = nextTool
}

function sam2SettingsFromUserSettings(settings: UserSettings): Sam2Settings {
  return {
    model_name: settings.sam2_default_model,
    multimask_output: settings.sam2_default_multimask_output,
    show_prompt_points: settings.sam2_default_show_prompt_points,
    polygon_epsilon: settings.sam2_default_polygon_epsilon,
    min_mask_area: settings.sam2_default_min_mask_area,
    mask_threshold: settings.sam2_default_mask_threshold,
    max_hole_area: settings.sam2_default_max_hole_area,
    candidate: settings.sam2_default_candidate,
  }
}

function applySam2DefaultsFromUserSettings() {
  if (hasUserChangedSam2Settings.value) {
    return
  }

  sam2Settings.value = sam2SettingsFromUserSettings(userSettings.value)
}

function markSam2SettingsChanged() {
  hasUserChangedSam2Settings.value = true
}

function labelToDraft(label: Label): LabelDraft {
  return {
    id: label.id,
    name: label.name,
    color: label.color,
    shape_type: label.shape_type,
    annotation_count: label.annotation_count ?? 0,
    frame_count: label.frame_count ?? 0,
  }
}

function isClassificationLabel(label: Pick<Label, 'shape_type'> | Pick<LabelDraft, 'shape_type'>) {
  return label.shape_type === 'classification'
}

function isClassificationAnnotation(annotation: AnnotationObject) {
  if (annotation.shape_type === 'classification') {
    return true
  }
  const attributes = annotation.attributes as Record<string, unknown> | null | undefined
  if (attributes?.classification === true || attributes?.annotation_kind === 'image_classification') {
    return true
  }
  return classificationLabelIds.value.has(annotation.label_id)
}

function labelUsedCount(label: LabelDraft) {
  return isClassificationLabel(label) ? label.frame_count : label.annotation_count
}

function compatibleReassignLabelOptions(sourceLabel: LabelDraft | null) {
  if (!sourceLabel) {
    return []
  }
  return labelDrafts.value.filter((label) => (
    label.id !== sourceLabel.id &&
    isClassificationLabel(label) === isClassificationLabel(sourceLabel)
  ))
}

function isUndefinedLabel(label: { name: string }) {
  return label.name.trim().toLowerCase() === 'undefined'
}

function nextLabelColor() {
  const usedColors = new Set(
    [...(job.value?.labels ?? []), ...labelDrafts.value].map((label) => label.color).filter(Boolean),
  )
  return pickDistinctLabelColor(LABEL_COLOR_PALETTE[(job.value?.labels.length ?? labelDrafts.value.length) % LABEL_COLOR_PALETTE.length], usedColors)
}

function resetNewLabelForm() {
  newLabelName.value = ''
  newLabelColor.value = nextLabelColor()
  newLabelKind.value = 'object_annotation'
  newLabelShapeType.value = 'polygon'
}

async function openLabelManager() {
  labelManagerVisible.value = true
  resetNewLabelForm()
  await loadManagedLabels()
}

function closeLabelManager() {
  if (labelActionLoading.value) {
    return
  }

  labelManagerVisible.value = false
  closeDeleteLabelModal()
}

async function loadManagedLabels() {
  labelManagerLoading.value = true
  const labels = await annotationStore.fetchJobLabels(props.jobId)
  labelManagerLoading.value = false

  if (!labels) {
    ElMessage.error(annotationStore.error || 'Failed to load labels.')
    return
  }

  labelDrafts.value = labels.map(labelToDraft)
  const labelIds = new Set(labels.map((label) => label.id))
  const hasStaleAnnotationLabels = job.value?.annotations.some((annotation) => !labelIds.has(annotation.label_id)) ?? false
  if (hasStaleAnnotationLabels) {
    await annotationStore.fetchJob(props.jobId)
  }
  if (job.value) {
    job.value.labels = labels
  }
  reconcileSelectedLabel()
}

function reconcileSelectedLabel(preferredLabelId: number | null = selectedLabelId.value) {
  const labels = objectLabels.value
  if (preferredLabelId !== null && labels.some((label) => label.id === preferredLabelId)) {
    selectedLabelId.value = preferredLabelId
    return
  }

  selectedLabelId.value = labels[0]?.id ?? null
}

async function refreshJobAfterLabelChange(preferredLabelId: number | null = selectedLabelId.value) {
  await annotationStore.fetchJob(props.jobId)
  reconcileSelectedLabel(preferredLabelId)
  selectedAnnotationId.value = currentImageAnnotations.value.some((annotation) => annotation.id === selectedAnnotationId.value)
    ? selectedAnnotationId.value
    : null
  const annotationIds = new Set(currentImageAnnotations.value.map((annotation) => annotation.id))
  hiddenAnnotationIds.value = hiddenAnnotationIds.value.filter((id) => annotationIds.has(id))
  await loadManagedLabels()
}

async function ensureCurrentFrameSavedBeforeLabelMutation() {
  if (!hasUnsavedChanges.value) {
    return true
  }

  const saved = await saveAnnotations()
  if (!saved) {
    ElMessage.error('Failed to save current annotations. Label change was not applied.')
    return false
  }

  return true
}

async function addManagedLabel() {
  const name = newLabelName.value.trim()
  if (!name) {
    ElMessage.warning('Label name is required.')
    return
  }

  const usedColors = new Set(labelDrafts.value.map((label) => label.color).filter(Boolean))
  const color = pickDistinctLabelColor(newLabelColor.value, usedColors)
  if (normalizeHexColor(newLabelColor.value) !== color) {
    ElMessage.warning(`Label color is too similar to another label color. Using ${color} instead.`)
  }

  const shapeType = newLabelKind.value === 'image_classification' ? 'classification' : newLabelShapeType.value

  labelActionLoading.value = true
  const created = await annotationStore.createJobLabel(props.jobId, {
    name,
    color,
    shape_type: shapeType,
  })
  labelActionLoading.value = false

  if (!created) {
    ElMessage.error(annotationStore.error || 'Create label failed.')
    return
  }

  ElMessage.success('Label created.')
  resetNewLabelForm()
  await refreshJobAfterLabelChange(created.id)
}

async function saveManagedLabel(label: LabelDraft) {
  const name = label.name.trim()
  if (!name) {
    ElMessage.warning('Label name is required.')
    return
  }

  const usedColors = new Set(
    labelDrafts.value.filter((item) => item.id !== label.id).map((item) => item.color).filter(Boolean),
  )
  const normalizedColor = normalizeHexColor(label.color)
  if (!normalizedColor) {
    ElMessage.warning('Label color must be a 6-digit hex color.')
    return
  }
  if (isColorConflict(normalizedColor, usedColors)) {
    ElMessage.warning('This color is too similar to another label color.')
    return
  }

  const nextShapeType = isClassificationLabel(label) ? 'classification' : label.shape_type

  labelActionLoading.value = true
  const updated = await annotationStore.updateJobLabel(props.jobId, label.id, {
    name,
    color: normalizedColor,
    shape_type: nextShapeType,
  })
  labelActionLoading.value = false

  if (!updated) {
    ElMessage.error(annotationStore.error || 'Update label failed.')
    return
  }

  ElMessage.success('Label updated.')
  await refreshJobAfterLabelChange(selectedLabelId.value)
}

async function requestDeleteManagedLabel(label: LabelDraft) {
  if (!(await ensureCurrentFrameSavedBeforeLabelMutation())) {
    return
  }

  const usage = await annotationStore.getJobLabelUsage(props.jobId, label.id)
  if (!usage) {
    ElMessage.error(annotationStore.error || 'Failed to check label usage.')
    return
  }

  pendingDeleteLabel.value = label
  pendingDeleteUsage.value = usage
  reassignTargetLabelId.value = compatibleReassignLabelOptions(label)[0]?.id ?? null
  if (usage.annotation_count === 0) {
    deleteLabelStrategy.value = 'delete_annotations'
  } else if (isClassificationLabel(label)) {
    deleteLabelStrategy.value = reassignTargetLabelId.value ? 'reassign' : 'delete_annotations'
  } else if (isUndefinedLabel(label)) {
    deleteLabelStrategy.value = reassignTargetLabelId.value ? 'reassign' : 'delete_annotations'
  } else {
    deleteLabelStrategy.value = 'move_to_undefined'
  }
  deleteLabelModalVisible.value = true
}

function closeDeleteLabelModal() {
  deleteLabelModalVisible.value = false
  pendingDeleteLabel.value = null
  pendingDeleteUsage.value = null
  deleteLabelStrategy.value = 'move_to_undefined'
  reassignTargetLabelId.value = null
}

async function confirmDeleteUnusedLabel() {
  const label = pendingDeleteLabel.value
  if (!label) {
    return
  }

  const deleted = await executeDeleteManagedLabel(label, { preferredLabelId: null })
  if (deleted) {
    closeDeleteLabelModal()
  }
}

async function confirmDeleteUsedLabel() {
  const label = pendingDeleteLabel.value
  if (!label) {
    return
  }

  if (deleteLabelStrategy.value === 'reassign' && !reassignTargetLabelId.value) {
    ElMessage.warning('Choose a target label.')
    return
  }

  const deleted = await executeDeleteManagedLabel(label, {
    strategy: deleteLabelStrategy.value,
    targetLabelId: reassignTargetLabelId.value,
  })
  if (deleted) {
    closeDeleteLabelModal()
  }
}

async function executeDeleteManagedLabel(
  label: LabelDraft,
  options: {
    strategy?: LabelDeleteStrategy
    targetLabelId?: number | null
    preferredLabelId?: number | null
  } = {},
) {
  labelActionLoading.value = true
  const result = await annotationStore.deleteJobLabel(
    props.jobId,
    label.id,
    options.strategy
      ? {
          strategy: options.strategy,
          target_label_id: options.targetLabelId ?? null,
        }
      : undefined,
  )
  labelActionLoading.value = false

  if (!result) {
    ElMessage.error(annotationStore.error || 'Delete label failed.')
    return false
  }

  let preferredLabelId = options.preferredLabelId ?? selectedLabelId.value
  if (selectedLabelId.value === label.id) {
    preferredLabelId = options.targetLabelId ?? null
  }
  ElMessage.success('Label deleted.')
  await refreshJobAfterLabelChange(preferredLabelId)
  if (options.strategy === 'move_to_undefined') {
    const undefinedLabel = job.value?.labels.find(isUndefinedLabel)
    selectedLabelId.value = undefinedLabel?.id ?? selectedLabelId.value
  }
  return true
}

function updateCurrentImageAnnotations(nextAnnotations: AnnotationObject[]) {
  if (!job.value || !currentImage.value) {
    return
  }

  updateAnnotationsForImage(currentImage.value.id, nextAnnotations)
}

function updateAnnotationsForImage(imageId: number, nextAnnotations: AnnotationObject[]) {
  if (!job.value) {
    return
  }

  const normalizedAnnotations = nextAnnotations.map((annotation) => normalizeAnnotationObject(annotation))
  job.value.annotations = [
    ...job.value.annotations.filter((annotation) => annotation.image_id !== imageId),
    ...normalizedAnnotations,
  ]
  hasUnsavedChanges.value = true
}

function cloneAnnotations(annotations: AnnotationObject[]): AnnotationObject[] {
  return JSON.parse(JSON.stringify(annotations)) as AnnotationObject[]
}

function buildClassificationAnnotation(imageId: number, labelId: number): AnnotationObject {
  const timestamp = new Date().toISOString()
  return normalizeAnnotationObject({
    id: `local_classification_${imageId}_${Math.random().toString(36).slice(2, 10)}`,
    image_id: imageId,
    label_id: labelId,
    shape_type: 'classification',
    points: [],
    attributes: {
      annotation_kind: 'image_classification',
      classification: true,
      created_by_tool: 'classify',
      classified_at: timestamp,
    },
  })
}

function nextAnnotationsWithClassification(imageId: number, labelId: number | null): AnnotationObject[] {
  const imageAnnotations = imageAnnotationsFor(imageId)
  const nonClassificationAnnotations = imageAnnotations.filter((annotation) => !isClassificationAnnotation(annotation))
  if (labelId === null) {
    return nonClassificationAnnotations
  }
  return [...nonClassificationAnnotations, buildClassificationAnnotation(imageId, labelId)]
}

function nextImageIndexForClassification() {
  if (isLastImage.value) {
    return null
  }
  return selectedImageIndex.value + 1
}

async function saveClassificationForCurrentImage(labelId: number | null) {
  if (!currentImage.value) {
    return false
  }
  if (canvasRef.value?.isDrawingPolygon()) {
    ElMessage.warning('Please finish or cancel the current polygon first.')
    return false
  }
  if (canvasRef.value?.isBoundaryAssistActive) {
    ElMessage.warning('Please finish or cancel the boundary-assisted polygon first.')
    return false
  }

  const nextAnnotations = nextAnnotationsWithClassification(currentImage.value.id, labelId)
  const saved = await annotationStore.saveImageAnnotations(currentImage.value.id, nextAnnotations)
  if (!saved) {
    return false
  }

  reconcileTrackingFixAnnotationsForImage(currentImage.value.id)
  hasUnsavedChanges.value = false
  selectedAnnotationId.value = null
  hiddenAnnotationIds.value = hiddenAnnotationIds.value.filter((id) =>
    nextAnnotations.some((annotation) => annotation.id === id),
  )
  return true
}

async function applyImageClassification(labelId: number) {
  const label = classificationLabels.value.find((item) => item.id === labelId)
  if (!label || !currentImage.value) {
    return
  }

  const saved = await saveClassificationForCurrentImage(labelId)
  if (!saved) {
    ElMessage.error('Failed to save classification. Please retry.')
    return
  }

  const nextIndex = nextImageIndexForClassification()
  if (nextIndex === null) {
    ElMessage.success('Classification saved. This is the last frame.')
    return
  }

  selectedImageIndex.value = nextIndex
  hasUnsavedChanges.value = false
  ElMessage.success(`Classification saved: ${label.name}.`)
}

async function clearImageClassification() {
  if (!currentImage.value || !currentImageClassificationAnnotation.value) {
    return
  }

  const saved = await saveClassificationForCurrentImage(null)
  if (!saved) {
    ElMessage.error('Failed to clear classification. Please retry.')
    return
  }

  ElMessage.success('Classification cleared.')
}

function pushUndoState() {
  if (!currentImage.value) {
    return
  }

  undoStack.value = [...undoStack.value, cloneAnnotations(currentImageAnnotations.value)].slice(-50)
}

function undo() {
  if (!job.value || !currentImage.value || undoStack.value.length === 0) {
    return
  }

  activePolygonSmoothingAnnotationId.value = null
  const previous = undoStack.value[undoStack.value.length - 1]
  undoStack.value = undoStack.value.slice(0, -1)
  job.value.annotations = [
    ...job.value.annotations.filter((annotation) => annotation.image_id !== currentImage.value?.id),
    ...cloneAnnotations(previous),
  ]
  const existingIds = new Set(previous.map((annotation) => annotation.id))
  hiddenAnnotationIds.value = hiddenAnnotationIds.value.filter((id) => existingIds.has(id))
  if (selectedAnnotationId.value !== null && !existingIds.has(selectedAnnotationId.value)) {
    selectedAnnotationId.value = null
  }
  hasUnsavedChanges.value = true
}

function selectAnnotation(id: number | string | null) {
  selectedAnnotationId.value = id
  if (id !== null && !suppressNextSelectToolSwitch.value) {
    setTool('cursor')
  }
}

function startBoundaryAssist(annotationId: number | string) {
  const annotation = currentImageAnnotations.value.find((item) => item.id === annotationId)
  if (!annotation || annotation.shape_type !== 'polygon') {
    ElMessage.warning('Select a polygon annotation first.')
    return
  }

  const preferredLabel = job.value?.labels.find((label) => label.name.trim().toLowerCase() === 'layer_up')
  const fallbackLabelId = preferredLabel?.id ?? selectedLabelId.value ?? job.value?.labels[0]?.id ?? null
  if (!fallbackLabelId) {
    ElMessage.warning('Create a label before using boundary-assisted polygon.')
    return
  }

  selectedLabelId.value = fallbackLabelId

  boundaryAssistReferenceAnnotationId.value = annotation.id
  selectAnnotation(annotation.id)
  setTool('cursor')
}

function cancelBoundaryAssist() {
  boundaryAssistReferenceAnnotationId.value = null
}

async function continueBoundaryAssistAsPolygon(payload: {
  initialPoints: number[][]
  attributes: Record<string, unknown> | null
}) {
  boundaryAssistReferenceAnnotationId.value = null
  selectedAnnotationId.value = null
  setTool('polygon')
  await nextTick()
  canvasRef.value?.startPolygonDraftWithInitialPoints?.(payload.initialPoints, payload.attributes)
}

function completeBoundaryAssist(createdAnnotationId: number | string) {
  boundaryAssistReferenceAnnotationId.value = null
  selectAnnotation(createdAnnotationId)
}

function deleteAnnotation(id: number | string | null = selectedAnnotationId.value) {
  if (id === null || !job.value || !currentImage.value) {
    return
  }

  activePolygonSmoothingAnnotationId.value = null
  pushUndoState()
  updateCurrentImageAnnotations(currentImageAnnotations.value.filter((annotation) => annotation.id !== id))
  hiddenAnnotationIds.value = hiddenAnnotationIds.value.filter((hiddenId) => hiddenId !== id)
  selectedAnnotationId.value = null
}

function updateAnnotationLabel(id: number | string, labelId: number) {
  if (!job.value || !currentImage.value) {
    return
  }

  const target = currentImageAnnotations.value.find((annotation) => annotation.id === id)
  if (!target || target.label_id === labelId) {
    return
  }

  activePolygonSmoothingAnnotationId.value = null
  pushUndoState()
  updateCurrentImageAnnotations(
    currentImageAnnotations.value.map((annotation) => (
      annotation.id === id ? { ...annotation, label_id: labelId } : annotation
    )),
  )
}

function toggleAnnotationVisibility(id: number | string) {
  hiddenAnnotationIds.value = hiddenAnnotationIds.value.includes(id)
    ? hiddenAnnotationIds.value.filter((hiddenId) => hiddenId !== id)
    : [...hiddenAnnotationIds.value, id]
}

function showAllAnnotations() {
  hiddenAnnotationIds.value = []
}

function hideAllAnnotations() {
  hiddenAnnotationIds.value = currentImageAnnotations.value.map((annotation) => annotation.id)
}

function applyPolygonSmoothing(annotation: AnnotationObject, smoothValue: number): AnnotationObject {
  if (!currentImage.value || annotation.shape_type !== 'polygon') {
    return annotation
  }

  const rawPoints = getPolygonRawPoints(annotation)
  const clampedSmoothValue = clampPolygonSmoothValue(smoothValue)
  const epsilon = sliderValueToSmoothEpsilon(clampedSmoothValue, currentImage.value.width, currentImage.value.height)
  const nextPoints = clampedSmoothValue === 0
    ? clonePoints(rawPoints)
    : simplifyPolygonRdp(rawPoints, epsilon)

  return {
    ...annotation,
    points: nextPoints.length >= 3 ? nextPoints : clonePoints(rawPoints),
    attributes: buildPolygonSmoothingAttributes(rawPoints, clampedSmoothValue, annotation.attributes),
  }
}

function ensurePolygonSmoothingUndoState(annotationId: number | string) {
  if (activePolygonSmoothingAnnotationId.value === annotationId) {
    return
  }

  pushUndoState()
  activePolygonSmoothingAnnotationId.value = annotationId
}

function updatePolygonSmoothing(annotationId: number | string, smoothValue: number) {
  const target = currentImageAnnotations.value.find((annotation) => annotation.id === annotationId)
  if (!target || target.shape_type !== 'polygon') {
    return
  }

  ensurePolygonSmoothingUndoState(annotationId)
  updateCurrentImageAnnotations(
    currentImageAnnotations.value.map((annotation) => (
      annotation.id === annotationId ? applyPolygonSmoothing(annotation, smoothValue) : annotation
    )),
  )
}

function commitPolygonSmoothing(annotationId: number | string, smoothValue: number) {
  const target = currentImageAnnotations.value.find((annotation) => annotation.id === annotationId)
  if (!target || target.shape_type !== 'polygon') {
    return
  }

  if (activePolygonSmoothingAnnotationId.value !== annotationId) {
    pushUndoState()
  }
  updateCurrentImageAnnotations(
    currentImageAnnotations.value.map((annotation) => (
      annotation.id === annotationId ? applyPolygonSmoothing(annotation, smoothValue) : annotation
    )),
  )
  activePolygonSmoothingAnnotationId.value = null
}

function resetPolygonSmoothing(annotationId: number | string) {
  const target = currentImageAnnotations.value.find((annotation) => annotation.id === annotationId)
  if (!target || target.shape_type !== 'polygon' || getPolygonSmoothValue(target) === 0) {
    return
  }

  pushUndoState()
  updateCurrentImageAnnotations(
    currentImageAnnotations.value.map((annotation) => (
      annotation.id === annotationId ? applyPolygonSmoothing(annotation, 0) : annotation
    )),
  )
  activePolygonSmoothingAnnotationId.value = null
}

async function generateSam2Mask() {
  if (!currentImage.value) {
    return
  }

  if (!selectedLabelId.value) {
    ElMessage.warning('Please select a label before generating a SAM2 mask.')
    return
  }

  const prompt = canvasRef.value?.getSam2Prompt()
  if (!prompt || (prompt.point_coords.length === 0 && prompt.box === null)) {
    ElMessage.warning('Add foreground/background points or draw a box prompt first.')
    return
  }

  generatingSam2.value = true
  try {
    const generated = await canvasRef.value?.runSamPrediction()
    if (!generated) {
      throw new Error('SAM2 prediction failed')
    }
    ElMessage.success('SAM2 mask generated.')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : 'SAM2 prediction failed')
  } finally {
    generatingSam2.value = false
  }
}

function acceptSam2Mask() {
  const preview = canvasRef.value?.acceptSam2Preview?.() as Sam2PreviewAcceptPayload | null | undefined
  if (!preview) {
    ElMessage.warning('No SAM2 mask preview to accept.')
    return
  }

  hasSam2Preview.value = false
  if (preview.source === 'refine_annotation') {
    if (applyRefinedSam2Polygon(preview)) {
      ElMessage.success('Polygon refined with SAM2.')
    }
    return
  }

  if (!acceptSam2GeneratedPolygon(preview)) {
    ElMessage.warning('No SAM2 mask preview to accept.')
    return
  }

  ElMessage.success('SAM2 mask accepted.')
  applyToolAfterSamAccept()
}

function applyToolAfterSamAccept() {
  const nextToolMode = userSettings.value.sam_accept_next_tool
  if (nextToolMode === 'keep_current') {
    return
  }

  if (nextToolMode === 'default_tool') {
    setTool(userSettings.value.default_tool)
    return
  }

  setTool(nextToolMode)
}

function rejectSam2Mask() {
  canvasRef.value?.rejectSam2Preview()
  hasSam2Preview.value = false
}

function acceptSam2GeneratedPolygon(preview: Sam2PreviewAcceptPayload) {
  if (!currentImage.value || !selectedLabelId.value || preview.points.length < 3) {
    return false
  }

  pushUndoState()
  const annotation = normalizeAnnotationObject({
    id: `local_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`,
    image_id: currentImage.value.id,
    label_id: selectedLabelId.value,
    shape_type: 'polygon',
    points: clonePoints(preview.points),
    attributes: buildPolygonSmoothingAttributes(preview.points, 0),
  })
  updateCurrentImageAnnotations([...currentImageAnnotations.value, annotation])
  suppressNextSelectToolSwitch.value = true
  try {
    selectAnnotation(annotation.id)
  } finally {
    suppressNextSelectToolSwitch.value = false
  }
  return true
}

function applyRefinedSam2Polygon(preview: Sam2PreviewAcceptPayload) {
  if (!currentImage.value || preview.targetAnnotationId === null || preview.points.length < 3) {
    return false
  }

  const target = currentImageAnnotations.value.find((annotation) => annotation.id === preview.targetAnnotationId)
  if (!target || target.shape_type !== 'polygon') {
    ElMessage.warning('Selected polygon is no longer available.')
    return false
  }

  const refinedPoints = clonePoints(preview.points)
  const existingAttributes = target.attributes && typeof target.attributes === 'object'
    ? { ...target.attributes }
    : null

  pushUndoState()
  updateCurrentImageAnnotations(
    currentImageAnnotations.value.map((annotation) => {
      if (annotation.id !== target.id) {
        return annotation
      }

      return {
        ...annotation,
        points: clonePoints(refinedPoints),
        attributes: buildPolygonSmoothingAttributes(refinedPoints, 0, {
          ...(existingAttributes ?? {}),
          refined_by: 'sam2',
          refined_from: clonePoints(target.points),
          refine_source: 'rough_polygon_mask',
          refined_at: new Date().toISOString(),
        }),
      }
    }),
  )
  activePolygonSmoothingAnnotationId.value = null
  suppressNextSelectToolSwitch.value = true
  try {
    selectAnnotation(target.id)
  } finally {
    suppressNextSelectToolSwitch.value = false
  }
  return true
}

async function handleRefineSelectedPolygonWithSam2(annotationId: number | string) {
  const annotation = currentImageAnnotations.value.find((item) => item.id === annotationId)
  if (!annotation) {
    ElMessage.warning('Please select a polygon annotation first.')
    return
  }

  if (annotation.shape_type !== 'polygon') {
    ElMessage.warning('Only polygon annotations can be refined with SAM2.')
    return
  }

  if (annotation.points.length < 3) {
    ElMessage.warning('Polygon must have at least 3 points.')
    return
  }

  refiningSelectedPolygonWithSam2.value = true
  try {
    const refined = await canvasRef.value?.refineSelectedPolygonWithSam2?.(annotation)
    if (!refined) {
      throw new Error('Cannot refine selected polygon with SAM2.')
    }
    hasSam2Preview.value = true
    ElMessage.success('SAM2 refine preview generated.')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : 'SAM2 refine failed')
  } finally {
    refiningSelectedPolygonWithSam2.value = false
  }
}

function imageFrameIndex(image = currentImage.value, fallbackIndex = selectedImageIndex.value) {
  if (!image) {
    return fallbackIndex
  }
  return image.frame_index ?? fallbackIndex
}

function firstJobFrameIndex() {
  const images = job.value?.images ?? []
  if (images.length === 0) {
    return 0
  }
  const firstImage = images[0]
  return firstImage.frame_index ?? 0
}

function lastJobFrameIndex() {
  const images = job.value?.images ?? []
  if (images.length === 0) {
    return 0
  }
  const lastImage = images[images.length - 1]
  return lastImage.frame_index ?? (images.length - 1)
}

function defaultForwardTrackingEndFrameIndex() {
  return Math.min(imageFrameIndex() + 20, lastJobFrameIndex())
}

function defaultBackwardTrackingEndFrameIndex() {
  return Math.max(imageFrameIndex() - 20, firstJobFrameIndex())
}

function resetTrackWithSam2Form() {
  const defaultDirection: Sam2TrackDirection = canTrackForwardFromCurrentFrame.value
    ? 'forward'
    : canTrackBackwardFromCurrentFrame.value
      ? 'backward'
      : 'forward'
  trackWithSam2Form.value = {
    direction: defaultDirection,
    forwardEndFrameIndex: defaultForwardTrackingEndFrameIndex(),
    backwardEndFrameIndex: defaultBackwardTrackingEndFrameIndex(),
    reviewInterval: 10,
    existingAnnotationPolicy: 'skip_same_label',
    outputMode: 'preview_first',
  }
}

function clearTrackingPreview() {
  trackingPreviewState.value = null
  trackingReviewDialogVisible.value = false
  trackingReviewRangeStart.value = 0
  trackingReviewRangeEnd.value = 0
}

function trackingResultInitialReviewStatus(result: Sam2TrackVideoFrameResult): TrackingReviewStatus {
  if (result.status === 'source') {
    return 'accepted'
  }
  if (result.status === 'failed') {
    return 'rejected'
  }
  return 'pending'
}

function initializeTrackingReviewRange(targetFrameIndex = imageFrameIndex()) {
  if (!trackingPreviewState.value) {
    trackingReviewRangeStart.value = 0
    trackingReviewRangeEnd.value = 0
    return
  }

  const minFrameIndex = trackingPreviewMinFrameIndex.value
  const maxFrameIndex = trackingPreviewMaxFrameIndex.value
  const clampedTarget = Math.min(Math.max(targetFrameIndex, minFrameIndex), maxFrameIndex)
  trackingReviewRangeStart.value = clampedTarget
  trackingReviewRangeEnd.value = clampedTarget
}

function formatTrackingDirection(direction: Sam2TrackDirection) {
  if (direction === 'backward') {
    return 'Backward'
  }
  if (direction === 'both') {
    return 'Both'
  }
  return 'Forward'
}

function formatPropagationDirection(direction: TrackingPreviewFrameResult['propagation_direction']) {
  if (direction === 'backward') {
    return 'Backward'
  }
  if (direction === 'forward') {
    return 'Forward'
  }
  return 'Source'
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

function buildTrackingCommitContext(
  options: {
    jobId: number
    sourceAnnotationId: number | string | null
    sourceFrameIndex: number
    direction: Sam2TrackDirection
    existingAnnotationPolicy: Sam2ExistingAnnotationPolicy
    labelId: number
    modelName: string
    outputMode: TrackOutputMode
  },
): TrackingCommitContext {
  return {
    jobId: options.jobId,
    sourceAnnotationId: options.sourceAnnotationId,
    sourceFrameIndex: options.sourceFrameIndex,
    direction: options.direction,
    existingAnnotationPolicy: options.existingAnnotationPolicy,
    labelId: options.labelId,
    modelName: options.modelName,
    outputMode: options.outputMode,
  }
}

function trackingCommitContextFromPreviewState(previewState: TrackingPreviewState): TrackingCommitContext {
  return buildTrackingCommitContext({
    jobId: previewState.jobId,
    sourceAnnotationId: previewState.sourceAnnotationId,
    sourceFrameIndex: previewState.sourceFrameIndex,
    direction: previewState.direction,
    existingAnnotationPolicy: previewState.existingAnnotationPolicy,
    labelId: previewState.labelId,
    modelName: previewState.modelName,
    outputMode: 'preview_first',
  })
}

function trackingCommitContextFromResponse(
  response: Sam2TrackVideoResponse,
  annotation: AnnotationObject,
  outputMode: TrackOutputMode,
): TrackingCommitContext {
  return buildTrackingCommitContext({
    jobId: response.job_id,
    sourceAnnotationId: response.source_annotation_id ?? annotation.id ?? null,
    sourceFrameIndex: response.start_frame_index,
    direction: response.direction,
    existingAnnotationPolicy: trackWithSam2Form.value.existingAnnotationPolicy,
    labelId: annotation.label_id,
    modelName: response.model_name,
    outputMode,
  })
}

function openTrackingReviewDialog() {
  if (!trackingPreviewState.value) {
    return
  }

  initializeTrackingReviewRange()
  trackingReviewDialogVisible.value = true
}

function closeTrackingReviewDialog() {
  if (acceptingTrackingPreview.value) {
    return
  }

  trackingReviewDialogVisible.value = false
}

function trackingResultHasValidPolygon(result: TrackingPreviewFrameResult | Sam2TrackVideoFrameResult) {
  return result.status === 'tracked' && Boolean(result.points && result.points.length >= 3)
}

function updateTrackingPreviewResult(
  imageId: number,
  updater: (result: TrackingPreviewFrameResult) => TrackingPreviewFrameResult,
) {
  if (!trackingPreviewState.value) {
    return
  }

  trackingPreviewState.value = {
    ...trackingPreviewState.value,
    results: trackingPreviewState.value.results.map((result) => (
      result.image_id === imageId ? updater(result) : result
    )),
  }
}

function findAnnotationById(annotationId: number | string | null | undefined) {
  if (!annotationId || !job.value) {
    return null
  }
  return job.value.annotations.find((annotation) => annotation.id === annotationId) ?? null
}

function existingFixAnnotationForResult(result: TrackingPreviewFrameResult) {
  if (!result.fix_annotation_id) {
    return null
  }
  const annotation = findAnnotationById(result.fix_annotation_id)
  if (!annotation || annotation.image_id !== result.image_id || annotation.shape_type !== 'polygon') {
    return null
  }
  return annotation
}

function canAcceptFixedTrackingResult(result: TrackingPreviewFrameResult) {
  const fixAnnotation = existingFixAnnotationForResult(result)
  return Boolean(
    result.review_status === 'needs_fix' &&
    !result.committed &&
    fixAnnotation &&
    fixAnnotation.shape_type === 'polygon' &&
    fixAnnotation.points.length >= 3,
  )
}

function canAcceptTrackingResult(result: TrackingPreviewFrameResult) {
  if (result.committed) {
    return false
  }
  if (canAcceptFixedTrackingResult(result)) {
    return true
  }
  return (
    trackingResultHasValidPolygon(result) &&
    result.review_status !== 'rejected' &&
    result.review_status !== 'needs_fix'
  )
}

function trackingPreviewHasUnresolvedFrames(results: TrackingPreviewFrameResult[]) {
  return results.some((result) =>
    result.review_status === 'pending' || result.review_status === 'needs_fix',
  )
}

function buildTrackingFixAnnotation(
  result: TrackingPreviewFrameResult,
  previewState: TrackingPreviewState,
): AnnotationObject {
  const trackedPoints = clonePoints(result.points ?? [])
  return normalizeAnnotationObject({
    id: `local_fix_${result.image_id}_${Math.random().toString(36).slice(2, 10)}`,
    image_id: result.image_id,
    label_id: previewState.labelId,
    shape_type: 'polygon',
    points: clonePoints(trackedPoints),
    attributes: buildPolygonSmoothingAttributes(trackedPoints, 0, {
      generated_by: 'sam2_video_tracking_needs_fix',
      source_annotation_id: previewState.sourceAnnotationId,
      source_frame_index: previewState.sourceFrameIndex,
      tracked_frame_index: result.frame_index,
      tracking_direction: previewState.direction,
      propagation_direction: result.propagation_direction,
      model_name: previewState.modelName,
      tracking_score: result.score,
      review_status: 'needs_fix',
      editable_fix_candidate: true,
    }),
  })
}

function reconcileTrackingFixAnnotationsForImage(imageId: number) {
  if (!trackingPreviewState.value || !job.value) {
    return
  }

  const imageAnnotations = job.value.annotations.filter((annotation) => annotation.image_id === imageId)
  trackingPreviewState.value = {
    ...trackingPreviewState.value,
    results: trackingPreviewState.value.results.map((result) => {
      if (result.image_id !== imageId || result.review_status !== 'needs_fix') {
        return result
      }

      const matchedAnnotation = imageAnnotations.find((annotation) => {
        if (annotation.shape_type !== 'polygon') {
          return false
        }
        const attributes = annotation.attributes as Record<string, unknown> | null | undefined
        return Boolean(
          attributes &&
          attributes.editable_fix_candidate === true &&
          attributes.tracked_frame_index === result.frame_index &&
          annotation.label_id === trackingPreviewState.value?.labelId,
        )
      })

      if (!matchedAnnotation) {
        return result
      }

      return {
        ...result,
        fix_annotation_id: matchedAnnotation.id,
      }
    }),
  }
}

async function ensureEditableFixAnnotation(imageId: number) {
  if (!trackingPreviewState.value || !job.value) {
    return null
  }

  const previewState = trackingPreviewState.value
  const result = previewState.results.find((item) => item.image_id === imageId)
  if (!result || !trackingResultHasValidPolygon(result)) {
    return null
  }

  const existingFixAnnotation = existingFixAnnotationForResult(result)
  if (existingFixAnnotation) {
    updateTrackingPreviewResult(imageId, (currentResult) => ({
      ...currentResult,
      review_status: 'needs_fix',
      fix_annotation_id: existingFixAnnotation.id,
    }))
    return {
      annotationId: existingFixAnnotation.id,
      created: false,
    }
  }

  const targetImageIndex = findImageIndexById(imageId)
  if (targetImageIndex < 0) {
    return null
  }

  if (currentImage.value?.id !== imageId) {
    await goToImage(targetImageIndex)
  }

  if (!currentImage.value || currentImage.value.id !== imageId) {
    return null
  }

  pushUndoState()
  const fixAnnotation = buildTrackingFixAnnotation(result, previewState)
  updateCurrentImageAnnotations([...currentImageAnnotations.value, fixAnnotation])
  updateTrackingPreviewResult(imageId, (currentResult) => ({
    ...currentResult,
    review_status: 'needs_fix',
    fix_annotation_id: fixAnnotation.id,
  }))
  return {
    annotationId: fixAnnotation.id,
    created: true,
  }
}

function setTrackingFrameReviewStatus(imageId: number, reviewStatus: TrackingReviewStatus) {
  updateTrackingPreviewResult(imageId, (result) => {
    if (result.status === 'source' || result.status === 'failed') {
      return result
    }
    return {
      ...result,
      review_status: reviewStatus,
    }
  })
}

function rejectTrackingFrame(imageId: number) {
  const result = trackingPreviewMap.value.get(imageId)
  if (!result || result.status !== 'tracked') {
    return
  }
  if (result.committed) {
    ElMessage.info('This tracking result has already been accepted. Edit the saved annotation directly if it needs changes.')
    return
  }
  setTrackingFrameReviewStatus(imageId, 'rejected')
}

async function markTrackingFrameNeedsFix(imageId: number) {
  const result = trackingPreviewMap.value.get(imageId)
  if (!result || result.status !== 'tracked') {
    return
  }
  if (result.committed) {
    ElMessage.info('This tracking result has already been accepted. Edit the saved annotation directly if it needs changes.')
    return
  }
  if (!trackingPreviewState.value) {
    return
  }

  trackingReviewDialogVisible.value = false
  const ensuredFixAnnotation = await ensureEditableFixAnnotation(imageId)
  if (!ensuredFixAnnotation) {
    ElMessage.warning('Unable to create an editable fix annotation for this frame.')
    return
  }

  if (currentImage.value?.id !== imageId) {
    const targetImageIndex = findImageIndexById(imageId)
    if (targetImageIndex >= 0) {
      await goToImage(targetImageIndex)
    }
  }

  if (currentImage.value?.id !== imageId) {
    ElMessage.warning('Unable to switch to the fix frame.')
    return
  }

  suppressNextSelectToolSwitch.value = true
  try {
    selectAnnotation(ensuredFixAnnotation.annotationId)
  } finally {
    suppressNextSelectToolSwitch.value = false
  }
  setTool('cursor')
  ElMessage[ensuredFixAnnotation.created ? 'success' : 'info'](
    ensuredFixAnnotation.created
      ? 'Fix annotation created. You can now edit the polygon and save it.'
      : 'This frame already has an editable fix annotation.',
  )
}

function findImageIndexById(imageId: number) {
  return job.value?.images.findIndex((image) => image.id === imageId) ?? -1
}

async function goToTrackingFrame(imageId: number) {
  const index = findImageIndexById(imageId)
  if (index < 0) {
    ElMessage.warning('Tracking frame is no longer available in this job.')
    return
  }
  trackingReviewDialogVisible.value = false
  await goToImage(index)
}

function acceptTrackingRange() {
  if (!trackingPreviewState.value) {
    return
  }

  if (!Number.isFinite(trackingReviewRangeStart.value) || !Number.isFinite(trackingReviewRangeEnd.value)) {
    ElMessage.warning('Enter a valid tracking frame range first.')
    return
  }

  const startFrame = Math.min(trackingReviewRangeStart.value, trackingReviewRangeEnd.value)
  const endFrame = Math.max(trackingReviewRangeStart.value, trackingReviewRangeEnd.value)
  const candidates = trackingPreviewState.value.results.filter((result) => (
    trackingResultHasValidPolygon(result) &&
    !result.committed &&
    result.review_status !== 'needs_fix' &&
    result.review_status !== 'rejected' &&
    result.frame_index >= startFrame &&
    result.frame_index <= endFrame
  ))

  if (candidates.length === 0) {
    ElMessage.warning('No valid tracked frames were found in the selected range.')
    return
  }

  for (const result of candidates) {
    setTrackingFrameReviewStatus(result.image_id, 'accepted')
  }
  ElMessage.success(`Marked ${candidates.length} frame(s) as accepted for review.`)
}

function openTrackWithSam2(annotationId: number | string) {
  const annotation = currentImageAnnotations.value.find((item) => item.id === annotationId)
  if (!annotation) {
    ElMessage.warning('Please select a polygon annotation first.')
    return
  }
  if (annotation.shape_type !== 'polygon') {
    ElMessage.warning('Only polygon annotations can be tracked with SAM2.')
    return
  }
  if (annotation.points.length < 3) {
    ElMessage.warning('Polygon must have at least 3 points.')
    return
  }

  trackingDialogAnnotationId.value = annotation.id
  resetTrackWithSam2Form()
  trackWithSam2DialogVisible.value = true
}

function closeTrackWithSam2Dialog() {
  if (trackingWithSam2.value) {
    return
  }
  trackWithSam2DialogVisible.value = false
  trackingDialogAnnotationId.value = null
}

function applyTrackingPreview(response: Sam2TrackVideoResponse, annotation: AnnotationObject) {
  const commitContext = trackingCommitContextFromResponse(response, annotation, 'preview_first')
  const previewResults = response.results.map((result) => ({
    ...result,
    review_status: trackingResultInitialReviewStatus(result),
    committed: result.status === 'source',
    fix_annotation_id: null,
  }))
  const frameIndices = previewResults.map((result) => result.frame_index)
  const minFrameIndex = frameIndices.length > 0 ? Math.min(...frameIndices) : response.start_frame_index
  const maxFrameIndex = frameIndices.length > 0 ? Math.max(...frameIndices) : response.end_frame_index

  trackingPreviewState.value = {
    jobId: commitContext.jobId,
    sourceAnnotationId: commitContext.sourceAnnotationId,
    sourceFrameIndex: commitContext.sourceFrameIndex,
    startFrameIndex: minFrameIndex,
    endFrameIndex: maxFrameIndex,
    direction: commitContext.direction,
    existingAnnotationPolicy: commitContext.existingAnnotationPolicy,
    labelId: commitContext.labelId,
    modelName: commitContext.modelName,
    reviewInterval: trackWithSam2Form.value.reviewInterval,
    results: previewResults,
    reviewFrames: response.review_frames,
    warnings: response.warnings,
  }
  initializeTrackingReviewRange(response.start_frame_index)
}

async function saveDirectTrackingResults(
  response: Sam2TrackVideoResponse,
  annotation: AnnotationObject,
) {
  if (!(await ensureCurrentFrameSavedBeforeTrackingCommit())) {
    return null
  }

  const commitContext = trackingCommitContextFromResponse(response, annotation, 'direct_create')
  let savedCount = 0
  let skippedCount = 0
  let failedCount = 0
  let saveFailedCount = 0

  for (const result of response.results) {
    if (result.status === 'source') {
      continue
    }
    if (result.status === 'failed') {
      failedCount += 1
      continue
    }

    const timestamp = new Date().toISOString()
    const preparedCommit = prepareTrackingResultCommit(result, commitContext, {
      createdAt: timestamp,
      savedAt: timestamp,
    })

    if (preparedCommit.outcome !== 'prepared') {
      if (preparedCommit.outcome === 'skipped') {
        skippedCount += 1
      } else {
        failedCount += 1
      }
      continue
    }

    const saved = await annotationStore.saveImageAnnotations(result.image_id, preparedCommit.nextAnnotations)
    if (saved) {
      savedCount += 1
    } else {
      saveFailedCount += 1
    }
  }

  return {
    savedCount,
    skippedCount,
    failedCount,
    saveFailedCount,
  }
}

async function startTrackWithSam2() {
  if (!job.value || !currentImage.value) {
    return
  }

  const annotation = trackingDialogTargetAnnotation.value
  if (!annotation || annotation.shape_type !== 'polygon') {
    ElMessage.warning('Select a polygon annotation to track it through frames with SAM2.')
    return
  }
  if (annotation.points.length < 3) {
    ElMessage.warning('Polygon must have at least 3 points.')
    return
  }

  if (trackingPreviewState.value) {
    const discardPreviewMessage = trackWithSam2Form.value.outputMode === 'direct_create'
      ? 'A tracking preview is already active. Starting direct tracking will discard the current preview. Continue?'
      : 'A tracking preview is already active. Starting a new tracking run will discard the current preview. Continue?'
    if (!window.confirm(discardPreviewMessage)) {
      return
    }
  }

  if (trackWithSam2Form.value.outputMode === 'direct_create') {
    const confirmed = window.confirm(
      'Directly create annotations will skip the review step and automatically save generated annotations to the database. Continue?',
    )
    if (!confirmed) {
      return
    }
  }

  if (trackingPreviewState.value) {
    clearTrackingPreview()
  }

  const startFrameIndex = imageFrameIndex()
  const clampedForwardEndFrameIndex = Math.min(
    Math.max(trackWithSam2Form.value.forwardEndFrameIndex, startFrameIndex),
    lastJobFrameIndex(),
  )
  const clampedBackwardEndFrameIndex = Math.max(
    Math.min(trackWithSam2Form.value.backwardEndFrameIndex, startFrameIndex),
    firstJobFrameIndex(),
  )

  if (trackWithSam2Form.value.direction === 'forward') {
    if (!canTrackForwardFromCurrentFrame.value) {
      ElMessage.warning('Cannot track forward from the last frame.')
      return
    }
    if (clampedForwardEndFrameIndex <= startFrameIndex) {
      ElMessage.warning('End frame must be after the selected start frame.')
      return
    }
  } else if (trackWithSam2Form.value.direction === 'backward') {
    if (!canTrackBackwardFromCurrentFrame.value) {
      ElMessage.warning('Cannot track backward from the first frame.')
      return
    }
    if (clampedBackwardEndFrameIndex >= startFrameIndex) {
      ElMessage.warning('End frame must be before the selected start frame.')
      return
    }
  } else {
    if (!canTrackBothDirectionsFromCurrentFrame.value) {
      ElMessage.warning('No additional frames are available for bidirectional tracking.')
      return
    }
    if (clampedBackwardEndFrameIndex > startFrameIndex) {
      ElMessage.warning('Backward end frame must be before or equal to the selected start frame.')
      return
    }
    if (clampedForwardEndFrameIndex < startFrameIndex) {
      ElMessage.warning('Forward end frame must be after or equal to the selected start frame.')
      return
    }
  }

  trackingWithSam2.value = true
  try {
    const response = await annotationStore.trackVideoWithSam2({
      start_image_id: currentImage.value.id,
      start_frame_index: startFrameIndex,
      annotation_id: annotation.id,
      label_id: annotation.label_id,
      points: clonePoints(annotation.points),
      direction: trackWithSam2Form.value.direction,
      end_frame_index: trackWithSam2Form.value.direction === 'forward'
        ? clampedForwardEndFrameIndex
        : trackWithSam2Form.value.direction === 'backward'
          ? clampedBackwardEndFrameIndex
          : null,
      backward_end_frame_index: trackWithSam2Form.value.direction === 'both'
        ? clampedBackwardEndFrameIndex
        : null,
      forward_end_frame_index: trackWithSam2Form.value.direction === 'both'
        ? clampedForwardEndFrameIndex
        : null,
      review_interval: trackWithSam2Form.value.reviewInterval,
      existing_annotation_policy: trackWithSam2Form.value.existingAnnotationPolicy,
      model_name: sam2Settings.value.model_name,
      polygon_epsilon: sam2Settings.value.polygon_epsilon,
      min_mask_area: sam2Settings.value.min_mask_area,
      mask_threshold: sam2Settings.value.mask_threshold,
      max_hole_area: sam2Settings.value.max_hole_area,
    })

    if (!response) {
      throw new Error(annotationStore.error || 'Track with SAM2 failed.')
    }

    if (trackWithSam2Form.value.outputMode === 'direct_create') {
      const report = await saveDirectTrackingResults(response, annotation)
      if (!report) {
        return
      }

      trackWithSam2DialogVisible.value = false
      trackingDialogAnnotationId.value = null

      if (report.saveFailedCount > 0) {
        if (report.savedCount > 0) {
          ElMessage.error(
            `Created ${report.savedCount + report.saveFailedCount} tracking annotation(s), saved ${report.savedCount}, failed to save ${report.saveFailedCount} frame(s).`,
          )
        } else {
          ElMessage.error('Tracking annotations were generated but failed to save. Please retry or use Preview mode.')
        }
        return
      }

      if (report.savedCount === 0) {
        if (report.skippedCount > 0 || report.failedCount > 0) {
          ElMessage.warning(
            `No tracking annotations were created.${report.skippedCount > 0 ? ` Skipped ${report.skippedCount}.` : ''}${report.failedCount > 0 ? ` Failed ${report.failedCount}.` : ''}`,
          )
        } else {
          ElMessage.info('No tracking annotations were created.')
        }
        return
      }

      ElMessage.success(
        `Created and saved ${report.savedCount} tracking annotation(s).${report.skippedCount > 0 ? ` Skipped ${report.skippedCount}.` : ''}${report.failedCount > 0 ? ` Failed ${report.failedCount}.` : ''}`,
      )
      return
    }

    applyTrackingPreview(response, annotation)
    trackWithSam2DialogVisible.value = false
    trackingDialogAnnotationId.value = null
    if (response.warnings.length > 0) {
      ElMessage.warning(`Tracking preview generated with ${response.warnings.length} warning(s).`)
    } else {
      ElMessage.success('Tracking preview generated.')
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : 'Track with SAM2 failed.')
  } finally {
    trackingWithSam2.value = false
  }
}

function isTrackingReviewFrame(frameIndex: number) {
  return trackingReviewFrameSet.value.has(frameIndex)
}

function trackingFrameBadge(imageId: number, frameIndex: number) {
  const result = trackingPreviewMap.value.get(imageId)
  if (result) {
    if (result.status === 'failed') {
      return { label: 'Failed', className: 'failed' }
    }
    if (result.review_status === 'needs_fix') {
      return { label: 'Fix', className: 'needs-fix' }
    }
    if (result.review_status === 'accepted') {
      return { label: 'Accepted', className: 'accepted' }
    }
    if (result.review_status === 'rejected') {
      return { label: 'Rejected', className: 'rejected' }
    }
    if (trackingResultHasValidPolygon(result)) {
      return { label: 'Preview', className: 'preview' }
    }
  }

  if (isTrackingReviewFrame(frameIndex)) {
    return { label: 'Review', className: 'review' }
  }
  return null
}

function trackingFrameButtonClasses(imageId: number, frameIndex: number) {
  const badge = trackingFrameBadge(imageId, frameIndex)
  return {
    'has-tracking-preview': badge?.className === 'preview',
    'is-tracking-review': badge?.className === 'review',
    'has-tracking-accepted': badge?.className === 'accepted',
    'has-tracking-rejected': badge?.className === 'rejected',
    'has-tracking-needs-fix': badge?.className === 'needs-fix',
    'has-tracking-failed': badge?.className === 'failed',
  }
}

function classificationFrameBadge(imageId: number) {
  return classificationFrameBadges.value.get(imageId) ?? null
}

function buildAnnotationFromTrackingResult(
  result: TrackingPreviewFrameResult | Sam2TrackVideoFrameResult,
  context: TrackingCommitContext,
  options: {
    createdAt?: string
    savedAt?: string | null
  } = {},
): AnnotationObject {
  const trackedPoints = clonePoints(result.points ?? [])
  const createdAt = options.createdAt ?? new Date().toISOString()
  const baseAttributes: Record<string, unknown> = {
    source_annotation_id: context.sourceAnnotationId,
    source_frame_index: context.sourceFrameIndex,
    tracked_frame_index: result.frame_index,
    tracking_direction: context.direction,
    propagation_direction: result.propagation_direction,
    model_name: context.modelName,
    tracking_score: result.score,
  }
  const modeSpecificAttributes = context.outputMode === 'direct_create'
    ? {
        generated_by: 'sam2_video_tracking_direct',
        direct_create: true,
        auto_saved: Boolean(options.savedAt),
        existing_annotation_policy_applied: context.existingAnnotationPolicy,
        created_at: createdAt,
        ...(options.savedAt ? { saved_at: options.savedAt } : {}),
      }
    : {
        generated_by: 'sam2_video_tracking',
      }
  return normalizeAnnotationObject({
    id: `local_track_${result.image_id}_${Math.random().toString(36).slice(2, 10)}`,
    image_id: result.image_id,
    label_id: context.labelId,
    shape_type: 'polygon',
    points: trackedPoints,
    attributes: buildPolygonSmoothingAttributes(trackedPoints, 0, {
      ...baseAttributes,
      ...modeSpecificAttributes,
    }),
  })
}

function prepareTrackingResultCommit(
  result: TrackingPreviewFrameResult | Sam2TrackVideoFrameResult,
  context: TrackingCommitContext,
  options: {
    createdAt?: string
    savedAt?: string | null
  } = {},
): PreparedTrackingCommit {
  if (!trackingResultHasValidPolygon(result)) {
    return { outcome: 'invalid' }
  }

  const existingAnnotations = imageAnnotationsFor(result.image_id)
  const sameLabelAnnotations = existingAnnotations.filter((annotation) => annotation.label_id === context.labelId)
  if (context.existingAnnotationPolicy === 'skip_same_label' && sameLabelAnnotations.length > 0) {
    return { outcome: 'skipped' }
  }

  const nextFrameAnnotations = existingAnnotations.filter((annotation) => (
    context.existingAnnotationPolicy === 'replace_same_label'
      ? annotation.label_id !== context.labelId
      : true
  ))

  return {
    outcome: 'prepared',
    nextAnnotations: [
      ...nextFrameAnnotations,
      buildAnnotationFromTrackingResult(result, context, options),
    ],
    removedSameLabelCount: sameLabelAnnotations.length,
  }
}

async function ensureCurrentFrameSavedBeforeTrackingCommit() {
  if (!hasUnsavedChanges.value) {
    return true
  }

  const saved = await saveAnnotations()
  if (!saved) {
    ElMessage.error('Failed to save current annotations before applying tracking results.')
    return false
  }
  return true
}

async function commitTrackingResult(imageId: number): Promise<TrackingCommitOutcome> {
  if (!trackingPreviewState.value || !job.value) {
    return 'invalid' as const
  }

  const previewState = trackingPreviewState.value
  const result = previewState.results.find((item) => item.image_id === imageId)
  if (!result || !trackingResultHasValidPolygon(result)) {
    return 'invalid' as const
  }
  if (result.committed) {
    return 'already_committed' as const
  }

  const commitContext = trackingCommitContextFromPreviewState(previewState)
  const preparedCommit = prepareTrackingResultCommit(result, commitContext)
  if (preparedCommit.outcome !== 'prepared') {
    return preparedCommit.outcome === 'skipped' ? 'skipped' : 'invalid'
  }

  const saved = await annotationStore.saveImageAnnotations(result.image_id, preparedCommit.nextAnnotations)
  if (!saved) {
    return 'failed' as const
  }

  updateTrackingPreviewResult(result.image_id, (currentResult) => ({
    ...currentResult,
    review_status: 'accepted',
    committed: true,
  }))
  return 'saved' as const
}

function imageAnnotationsFor(imageId: number) {
  if (!job.value) {
    return []
  }
  return job.value.annotations.filter((annotation) => annotation.image_id === imageId)
}

function acceptFixedTrackingFrame(
  result: TrackingPreviewFrameResult,
  options: {
    showMessages?: boolean
  } = {},
): TrackingCommitOutcome {
  if (!trackingPreviewState.value || !job.value) {
    return 'invalid'
  }

  const previewState = trackingPreviewState.value
  const fixAnnotation = existingFixAnnotationForResult(result)
  if (!fixAnnotation || fixAnnotation.image_id !== result.image_id) {
    if (options.showMessages !== false) {
      ElMessage.warning('No editable fix annotation found for this frame.')
    }
    return 'invalid'
  }

  if (fixAnnotation.shape_type !== 'polygon' || fixAnnotation.points.length < 3) {
    if (options.showMessages !== false) {
      ElMessage.warning('Fix annotation must be a valid polygon.')
    }
    return 'invalid'
  }

  if (result.committed) {
    return 'already_committed'
  }

  const imageAnnotations = imageAnnotationsFor(result.image_id)
  const sameLabelAnnotations = imageAnnotations.filter((annotation) => (
    annotation.label_id === previewState.labelId &&
    annotation.id !== fixAnnotation.id
  ))

  if (previewState.existingAnnotationPolicy === 'skip_same_label' && sameLabelAnnotations.length > 0) {
    if (options.showMessages !== false) {
      ElMessage.warning('This frame already has an annotation with the same label.')
    }
    return 'skipped'
  }

  let nextAnnotations = imageAnnotations
  if (previewState.existingAnnotationPolicy === 'replace_same_label') {
    nextAnnotations = imageAnnotations.filter((annotation) => !(
      annotation.label_id === previewState.labelId &&
      annotation.id !== fixAnnotation.id
    ))
  }

  const existingAttributes = fixAnnotation.attributes && typeof fixAnnotation.attributes === 'object'
    ? { ...fixAnnotation.attributes }
    : null
  const acceptedAt = new Date().toISOString()
  nextAnnotations = nextAnnotations.map((annotation) => {
    if (annotation.id !== fixAnnotation.id) {
      return annotation
    }

    return normalizeAnnotationObject({
      ...annotation,
      attributes: {
        ...(existingAttributes ?? {}),
        review_status: 'accepted',
        accepted_from: 'needs_fix',
        accepted_at: acceptedAt,
        committed_from_tracking_review: true,
        existing_annotation_policy_applied: previewState.existingAnnotationPolicy,
      },
    })
  })

  if (currentImage.value?.id === result.image_id) {
    pushUndoState()
    updateCurrentImageAnnotations(nextAnnotations)
  } else {
    updateAnnotationsForImage(result.image_id, nextAnnotations)
  }

  updateTrackingPreviewResult(result.image_id, (currentResult) => ({
    ...currentResult,
    review_status: 'accepted',
    committed: true,
  }))

  if (options.showMessages !== false) {
    if (previewState.existingAnnotationPolicy === 'replace_same_label' && sameLabelAnnotations.length > 0) {
      ElMessage.success('Fixed annotation accepted. Existing annotations with the same label were replaced. Click Save to persist it.')
    } else {
      ElMessage.success('Fixed annotation accepted. Click Save to persist it.')
    }
  }

  return 'saved'
}

async function commitTrackingResults(
  results: TrackingPreviewFrameResult[],
  messages: {
    empty: string
    successPrefix: string
    partialPrefix: string
  },
  options: {
    showMessages?: boolean
  } = {},
) {
  if (!trackingPreviewState.value || !job.value) {
    return null
  }
  if (!(await ensureCurrentFrameSavedBeforeTrackingCommit())) {
    return null
  }

  const candidates = results.filter((result) => canAcceptTrackingResult(result))
  if (candidates.length === 0) {
    if (options.showMessages !== false) {
      ElMessage.warning(messages.empty)
    }
    return {
      savedCount: 0,
      skippedCount: 0,
      failedCount: 0,
      attemptedCount: 0,
    }
  }

  let savedCount = 0
  let skippedCount = 0
  let failedCount = 0

  acceptingTrackingPreview.value = true
  try {
    for (const result of candidates) {
      const outcome = result.review_status === 'needs_fix'
        ? acceptFixedTrackingFrame(result, { showMessages: false })
        : await commitTrackingResult(result.image_id)
      if (outcome === 'saved') {
        savedCount += 1
      } else if (outcome === 'skipped' || outcome === 'already_committed') {
        skippedCount += 1
      } else if (outcome === 'failed') {
        failedCount += 1
      }
    }
  } finally {
    acceptingTrackingPreview.value = false
  }

  if (failedCount > 0) {
    if (options.showMessages !== false) {
      ElMessage.error(
        `${messages.partialPrefix} ${savedCount} frame(s)${skippedCount > 0 ? `, skipped ${skippedCount}` : ''}, failed ${failedCount}.`,
      )
    }
    return {
      savedCount,
      skippedCount,
      failedCount,
      attemptedCount: candidates.length,
    }
  }

  if (options.showMessages !== false) {
    ElMessage.success(
      `${messages.successPrefix} ${savedCount} frame(s)${skippedCount > 0 ? `, skipped ${skippedCount}` : ''}.`,
    )
  }
  return {
    savedCount,
    skippedCount,
    failedCount,
    attemptedCount: candidates.length,
  }
}

async function acceptCurrentTrackingFrame() {
  const result = currentTrackingPreviewResult.value
  if (!result) {
    ElMessage.warning('No tracking preview is available on the current frame.')
    return
  }

  await acceptTrackingFrame(result.image_id)
}

async function acceptTrackingFrame(imageId: number) {
  const result = trackingPreviewMap.value.get(imageId)
  if (!result) {
    ElMessage.warning('No tracking preview is available on this frame.')
    return
  }
  if (result.committed) {
    ElMessage.info('This tracking result has already been accepted.')
    return
  }

  if (result.review_status === 'needs_fix') {
    const outcome = acceptFixedTrackingFrame(result)
    if (outcome !== 'saved') {
      return
    }
    return
  }

  if (!trackingResultHasValidPolygon(result)) {
    ElMessage.warning('This tracking frame does not contain a valid polygon.')
    return
  }

  setTrackingFrameReviewStatus(result.image_id, 'accepted')
  await commitTrackingResults([result], {
    empty: 'No valid tracking frame is available to accept.',
    successPrefix: 'Saved accepted tracking',
    partialPrefix: 'Saved accepted tracking',
  })
}

async function acceptReviewedTrackingFrames() {
  if (!trackingPreviewState.value) {
    return
  }

  const reviewedResults = trackingPreviewState.value.results.filter((result) => (
    trackingResultHasValidPolygon(result) &&
    result.review_status === 'accepted' &&
    !result.committed
  ))
  await commitTrackingResults(reviewedResults, {
    empty: 'No reviewed tracking frames are ready to save.',
    successPrefix: 'Saved reviewed tracked',
    partialPrefix: 'Saved reviewed tracked',
  })
}

async function acceptTrackingPreview() {
  if (!trackingPreviewState.value) {
    return
  }

  const blockedResults = trackingPreviewState.value.results.filter((result) =>
    result.review_status === 'rejected' || result.review_status === 'needs_fix',
  )
  if (blockedResults.length > 0) {
    const confirmed = window.confirm(
      'Some frames are marked as rejected or needs fix. Accept All will save all currently acceptable results and skip unresolved frames. Continue?',
    )
    if (!confirmed) {
      return
    }
  }

  const acceptedResults = trackingPreviewState.value.results.filter((result) => (
    canAcceptTrackingResult(result)
  ))
  const report = await commitTrackingResults(acceptedResults, {
    empty: 'No valid tracking frames are available to accept.',
    successPrefix: 'Saved tracked',
    partialPrefix: 'Saved tracked',
  }, {
    showMessages: false,
  })

  if (!report) {
    return
  }

  if (report.failedCount > 0) {
    ElMessage.error(
      `Saved tracked ${report.savedCount} frame(s)${report.skippedCount > 0 ? `, skipped ${report.skippedCount}` : ''}, failed ${report.failedCount}.`,
    )
    return
  }

  const remainingResults = trackingPreviewState.value?.results ?? []
  if (trackingPreviewHasUnresolvedFrames(remainingResults)) {
    ElMessage.warning('Some frames still need fixing.')
    return
  }

  clearTrackingPreview()
  if (report.attemptedCount === 0) {
    ElMessage.info('No pending tracking frames remain. Tracking preview closed.')
    return
  }
  ElMessage.success('Tracking results accepted. Click Save to persist the annotations.')
}

function rejectCurrentTrackingFrame() {
  const result = currentTrackingPreviewResult.value
  if (!result || result.status !== 'tracked') {
    ElMessage.warning('No tracked preview is available on the current frame.')
    return
  }
  rejectTrackingFrame(result.image_id)
}

function markCurrentTrackingFrameNeedsFix() {
  const result = currentTrackingPreviewResult.value
  if (!result || result.status !== 'tracked') {
    ElMessage.warning('No tracked preview is available on the current frame.')
    return
  }
  markTrackingFrameNeedsFix(result.image_id)
}

function rejectTrackingPreview() {
  clearTrackingPreview()
  ElMessage.info('Tracking preview discarded. Saved annotations remain unchanged.')
}

function frameIndexFromQuery() {
  const total = totalImages.value
  if (total <= 0) {
    return 0
  }

  const rawFrame = Array.isArray(route.query.frame) ? route.query.frame[0] : route.query.frame
  const parsedFrame = Number(rawFrame)
  if (!Number.isInteger(parsedFrame)) {
    return 0
  }

  const clampedFrame = Math.min(Math.max(parsedFrame, 1), total)
  return clampedFrame - 1
}

function applyInitialFrameSelection() {
  if (!job.value || totalImages.value <= 0) {
    selectedImageIndex.value = 0
    return
  }

  if (route.query.frame !== undefined) {
    const nextIndex = frameIndexFromQuery()
    selectedImageIndex.value = nextIndex
    syncFrameQuery(nextIndex)
    return
  }

  const lastFrameIndex = readLastFrameIndex()
  if (lastFrameIndex !== null) {
    selectedImageIndex.value = lastFrameIndex
    syncFrameQuery(lastFrameIndex)
    return
  }

  selectedImageIndex.value = 0
}

function syncFrameQuery(index = selectedImageIndex.value) {
  const total = totalImages.value
  if (total <= 0) {
    return
  }

  const frame = String(Math.min(Math.max(index + 1, 1), total))
  const currentFrame = Array.isArray(route.query.frame) ? route.query.frame[0] : route.query.frame
  if (currentFrame === frame) {
    return
  }

  void router.replace({
    query: {
      ...route.query,
      frame,
    },
  })
}

function getLastFrameStorageKey() {
  const usernameOrGuest = currentUsername.value?.trim() || 'guest'
  return `annotation:last-frame:${usernameOrGuest}:${props.jobId}`
}

function readLastFrameIndex() {
  if (!userSettings.value.remember_last_frame_per_job || totalImages.value <= 0) {
    return null
  }

  try {
    const rawValue = localStorage.getItem(getLastFrameStorageKey())
    if (!rawValue) {
      return null
    }

    const payload = JSON.parse(rawValue) as { frameIndex?: unknown }
    const frameIndex = Number(payload.frameIndex)
    if (!Number.isInteger(frameIndex) || frameIndex < 0 || frameIndex >= totalImages.value) {
      return null
    }

    return frameIndex
  } catch {
    return null
  }
}

function persistLastFrame() {
  if (!userSettings.value.remember_last_frame_per_job || !job.value || !currentImage.value) {
    return
  }

  try {
    localStorage.setItem(getLastFrameStorageKey(), JSON.stringify({
      frameIndex: selectedImageIndex.value,
      imageId: currentImage.value.id,
      updatedAt: new Date().toISOString(),
    }))
  } catch {
    // Ignore storage quota or browser privacy failures; annotation state is unaffected.
  }
}

function onBeforeUnload() {
  persistLastFrame()
}

async function saveAnnotations() {
  if (!currentImage.value) {
    return true
  }

  const saved = await annotationStore.saveImageAnnotations(currentImage.value.id, currentImageAnnotations.value)
  if (saved) {
    reconcileTrackingFixAnnotationsForImage(currentImage.value.id)
    hasUnsavedChanges.value = false
  }

  return saved
}

async function goToImage(index: number) {
  if (!job.value || index === selectedImageIndex.value) {
    return
  }

  if (index < 0 || index >= job.value.images.length) {
    ElMessage.warning(`Image index must be between 1 and ${job.value.images.length}`)
    return
  }

  if (canvasRef.value?.isDrawingPolygon()) {
    ElMessage.warning('Please finish or cancel the current polygon first.')
    return
  }

  if (canvasRef.value?.isBoundaryAssistActive) {
    ElMessage.warning('Please finish or cancel the boundary-assisted polygon first.')
    return
  }

  if (hasUnsavedChanges.value) {
    const saved = await saveAnnotations()
    if (!saved) {
      ElMessage.error('Failed to save annotations. Image was not changed.')
      return
    }
  }

  selectedImageIndex.value = index
  hasUnsavedChanges.value = false
}

function goPrevious() {
  void goToImage(selectedImageIndex.value - 1)
}

function goNext() {
  void goToImage(selectedImageIndex.value + 1)
}

function submitGoToIndex() {
  const nextIndex = Number.parseInt(goToIndex.value, 10)

  if (!Number.isInteger(nextIndex) || nextIndex < 1 || nextIndex > totalImages.value) {
    ElMessage.warning(`Image index must be between 1 and ${totalImages.value}`)
    return
  }

  void goToImage(nextIndex - 1)
}

function onKeydown(event: KeyboardEvent) {
  if (isTextEntryTarget(event.target)) {
    return
  }

  if (event.code === 'Space') {
    return
  }

  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
    event.preventDefault()
    void saveAnnotations()
    return
  }

  if (event.ctrlKey && event.key.toLowerCase() === 'z') {
    event.preventDefault()
    if (canvasRef.value?.isBoundaryAssistActive) {
      canvasRef.value.undoBoundaryAssistStep?.()
      return
    }

    if (tool.value === 'polygon' && canvasRef.value?.removeLastPolygonPoint()) {
      return
    }

    undo()
    return
  }

  if (event.key === 'ArrowLeft' || event.key.toLowerCase() === 'a') {
    event.preventDefault()
    goPrevious()
    return
  }

  if (event.key === 'ArrowRight' || event.key.toLowerCase() === 'd') {
    event.preventDefault()
    goNext()
  }
}

function isTextEntryTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) {
    return false
  }

  const tagName = target.tagName.toLowerCase()
  return tagName === 'input' || tagName === 'textarea' || tagName === 'select' || target.isContentEditable
}
</script>

<template>
  <main class="annotate-page annotate-layout">
    <aside class="annotate-sidebar annotation-sidebar-left">
      <div class="sidebar-header">
        <router-link :to="jobsBackRoute" class="annotate-back">
          <el-icon><Back /></el-icon>
          Jobs
        </router-link>

        <div>
          <p class="eyebrow">Annotation workspace</p>
          <h1 class="job-title">{{ job?.name ?? `Job ${jobId}` }}</h1>
          <p v-if="job" class="job-subtitle">ID: #{{ job.id }}</p>
        </div>

        <section class="tool-panel">
          <p class="panel-label">Tool</p>
          <div class="annotation-tool-grid">
            <button
              v-for="toolName in ['cursor', 'rectangle', 'polygon']"
              :key="toolName"
              class="annotation-tool-button"
              :class="{ active: tool === toolName }"
              type="button"
              @click="setTool(toolName as ToolType)"
            >
              {{ toolName }}
            </button>
            <button
              class="annotation-tool-button annotation-tool-button-sam2"
              :class="{ active: tool === 'sam2' }"
              type="button"
              @click="setTool('sam2')"
            >
              sam2
            </button>
            <button
              class="annotation-tool-button annotation-tool-button-classify"
              :class="{ active: tool === 'classify', disabled: !canUseClassificationTool }"
              :disabled="!canUseClassificationTool"
              :title="canUseClassificationTool ? '' : 'Add image classification labels in Manage Labels first.'"
              type="button"
              @click="setTool('classify')"
            >
              classify
            </button>
          </div>
        </section>
      </div>

      <div class="sidebar-middle left-panel-main" :class="{ 'sidebar-middle-sam2': tool === 'sam2' }">
        <div class="sidebar-settings-labels sidebar-label-settings-scroll">
          <section class="tool-panel sidebar-labels">
            <div class="panel-label-row">
              <p class="panel-label">Label</p>
              <button class="panel-link-button" type="button" @click="openLabelManager">
                Manage
              </button>
            </div>
            <div class="label-list">
              <button
                v-for="label in objectLabels"
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
            <p v-if="objectLabels.length === 0" class="tool-panel-hint">
              Add object annotation labels in Manage Labels to draw polygons, rectangles, or points.
            </p>
          </section>

          <div v-if="tool === 'sam2'" class="sidebar-sam2-settings">
            <section class="tool-panel sam2-settings-panel">
              <p class="panel-label">SAM2 Settings</p>
              <label class="sam2-setting-row">
                <span>Model</span>
                <select v-model="sam2Settings.model_name" @change="markSam2SettingsChanged">
                  <option value="sam2_hiera_tiny">sam2_hiera_tiny</option>
                  <option value="sam2_hiera_small">sam2_hiera_small</option>
                  <option value="sam2_hiera_base_plus">sam2_hiera_base_plus</option>
                  <option value="sam2_hiera_large">sam2_hiera_large</option>
                </select>
              </label>
              <label class="sam2-setting-row">
                <span>multimask_output</span>
                <input v-model="sam2Settings.multimask_output" type="checkbox" @change="markSam2SettingsChanged" />
              </label>
              <label class="sam2-setting-row">
                <span>Show prompt points</span>
                <input v-model="sam2Settings.show_prompt_points" type="checkbox" @change="markSam2SettingsChanged" />
              </label>
              <label class="sam2-setting-row">
                <span>candidate</span>
                <select v-model="sam2Settings.candidate" @change="markSam2SettingsChanged">
                  <option value="best">best</option>
                  <option value="0">0</option>
                  <option value="1">1</option>
                  <option value="2">2</option>
                </select>
              </label>
              <label class="sam2-setting-slider">
                <span>polygon simplification</span>
                <input
                  v-model.number="sam2Settings.polygon_epsilon"
                  max="0.02"
                  min="0.0005"
                  step="0.0005"
                  type="range"
                  @input="markSam2SettingsChanged"
                />
                <small>fine outline</small>
                <small>coarse outline</small>
              </label>
              <label class="sam2-setting-slider">
                <span>mask threshold: {{ sam2Settings.mask_threshold.toFixed(1) }}</span>
                <input
                  v-model.number="sam2Settings.mask_threshold"
                  max="5"
                  min="-5"
                  step="0.1"
                  type="range"
                  @input="markSam2SettingsChanged"
                />
                <small>loose mask</small>
                <small>strict mask</small>
              </label>
              <label class="sam2-setting-row">
                <span>min mask area</span>
                <input
                  v-model.number="sam2Settings.min_mask_area"
                  max="100000"
                  min="0"
                  step="10"
                  type="number"
                  @change="markSam2SettingsChanged"
                  @input="markSam2SettingsChanged"
                />
              </label>
              <label class="sam2-setting-row">
                <span>max hole area</span>
                <input
                  v-model.number="sam2Settings.max_hole_area"
                  max="100000"
                  min="0"
                  step="10"
                  type="number"
                  @change="markSam2SettingsChanged"
                  @input="markSam2SettingsChanged"
                />
              </label>
            </section>
          </div>
        </div>

        <div class="sidebar-frames">
          <p class="panel-label">Frames</p>
          <div class="frame-list">
            <button
              v-for="(image, index) in job?.images ?? []"
              :key="image.id"
              class="frame-choice"
              :class="[trackingFrameButtonClasses(image.id, image.frame_index ?? index), { active: selectedImageIndex === index }]"
              type="button"
              @click="goToImage(index)"
            >
              <span>{{ index + 1 }}. {{ image.filename }}</span>
              <span class="frame-choice-badges">
                <span
                  v-if="classificationFrameBadge(image.id)"
                  class="frame-choice-badge classification"
                  :style="{
                    borderColor: `${classificationFrameBadge(image.id)?.color}66`,
                    color: classificationFrameBadge(image.id)?.color,
                  }"
                >
                  {{ classificationFrameBadge(image.id)?.label }}
                </span>
                <span
                  v-if="trackingFrameBadge(image.id, image.frame_index ?? index)"
                  class="frame-choice-badge"
                  :class="trackingFrameBadge(image.id, image.frame_index ?? index)?.className"
                >
                  {{ trackingFrameBadge(image.id, image.frame_index ?? index)?.label }}
                </span>
              </span>
            </button>
          </div>
        </div>
      </div>

      <div class="sidebar-footer sidebar-bottom annotate-actions left-panel-footer">
        <el-button :icon="Delete" @click="deleteAnnotation()">Delete current</el-button>
        <el-button :loading="saving" type="primary" :icon="Finished" @click="saveAnnotations">
          Save
        </el-button>
      </div>
    </aside>

    <section class="annotate-stage annotation-main">
      <header class="annotate-stage-bar">
        <div class="annotate-stage-title">
          <strong>{{ currentImage?.filename ?? 'No image' }}</strong>
          <span v-if="currentImage">
            {{ currentImage.width }} x {{ currentImage.height }} · {{ currentImageNumber }} / {{ totalImages }}
          </span>
        </div>
        <div class="annotation-toolbar">
          <div class="toolbar-group toolbar-group-frames">
            <el-button :disabled="isFirstImage || saving" @click="goPrevious">Previous</el-button>
            <span class="frame-counter">{{ currentImageNumber }} / {{ totalImages }}</span>
            <el-button :disabled="isLastImage || saving" @click="goNext">Next</el-button>
            <form class="image-jump" @submit.prevent="submitGoToIndex">
              <label for="go-to-image">Go to:</label>
              <el-input
                id="go-to-image"
                v-model="goToIndex"
                class="image-jump-input"
                :max="totalImages"
                :min="1"
                type="number"
              />
              <el-button :disabled="saving || totalImages === 0" native-type="submit">Go</el-button>
            </form>
          </div>

          <div class="toolbar-group toolbar-group-view">
            <el-button :disabled="!canUndo" @click="undo">Undo</el-button>
            <el-button @click="canvasRef?.zoomOut()">Zoom -</el-button>
            <span class="zoom-label">Zoom: {{ canvasRef?.zoomPercent ?? 100 }}%</span>
            <el-button @click="canvasRef?.zoomIn()">Zoom +</el-button>
            <el-button @click="canvasRef?.fitToScreen()">Fit</el-button>
            <el-button @click="canvasRef?.resetView()">Reset</el-button>
          </div>

          <div v-if="tool === 'sam2' || hasSam2Preview" class="toolbar-group toolbar-group-sam2">
            <el-button
              v-if="tool === 'sam2'"
              class="sam-generate-btn"
              :loading="generatingSam2"
              style="--el-button-bg-color: #2563eb; --el-button-border-color: #2563eb; --el-button-text-color: #ffffff; --el-button-hover-bg-color: #1d4ed8; --el-button-hover-border-color: #1d4ed8; --el-button-hover-text-color: #ffffff; --el-button-active-bg-color: #1e40af; --el-button-active-border-color: #1e40af; --el-button-active-text-color: #ffffff; --el-button-disabled-text-color: #ffffff;"
              type="primary"
              @click="generateSam2Mask"
            >
              Generate Mask
            </el-button>
            <el-button
              class="sam-accept-btn"
              :disabled="!hasSam2Preview"
              style="--el-button-bg-color: #16a34a; --el-button-border-color: #16a34a; --el-button-text-color: #ffffff; --el-button-hover-bg-color: #15803d; --el-button-hover-border-color: #15803d; --el-button-hover-text-color: #ffffff; --el-button-active-bg-color: #166534; --el-button-active-border-color: #166534; --el-button-active-text-color: #ffffff; --el-button-disabled-text-color: #ffffff;"
              type="success"
              @click="acceptSam2Mask"
            >
              Accept
            </el-button>
            <el-button :disabled="!hasSam2Preview" @click="rejectSam2Mask">Reject</el-button>
          </div>

          <div class="toolbar-group toolbar-group-reload">
            <el-button :loading="loading" :icon="RefreshRight" @click="annotationStore.fetchJob(jobId)">
              Reload
            </el-button>
          </div>

          <div class="toolbar-group toolbar-group-objects">
            <el-button
              class="annotation-objects-toggle"
              :aria-expanded="isRightPanelOpen"
              @click="toggleRightPanel"
            >
              Objects {{ currentImageObjectAnnotations.length }}
            </el-button>
          </div>
        </div>
      </header>

      <div class="annotation-center-content">
        <el-alert v-if="error" :title="error" type="error" show-icon />

        <section v-if="tool === 'classify' && classificationLabels.length > 0" class="classification-toolbar">
          <div class="classification-toolbar-copy">
            <strong>Image class</strong>
            <span>
              Current:
              <template v-if="currentImageClassificationLabel">
                {{ currentImageClassificationLabel.name }}
              </template>
              <template v-else>
                Unclassified
              </template>
            </span>
          </div>
          <div class="classification-toolbar-actions">
            <button
              v-for="label in classificationLabels"
              :key="label.id"
              class="classification-chip"
              :class="{ active: currentImageClassificationLabelId === label.id }"
              type="button"
              :style="{ '--classification-color': label.color }"
              @click="applyImageClassification(label.id)"
            >
              <span class="classification-chip-dot"></span>
              {{ label.name }}
            </button>
            <button
              class="classification-chip classification-chip-clear"
              :disabled="!currentImageClassificationAnnotation"
              type="button"
              @click="clearImageClassification"
            >
              Clear class
            </button>
          </div>
        </section>

        <section
          v-if="trackingPreviewState"
          class="tracking-preview-banner tracking-preview-banner-wide"
        >
          <div class="tracking-preview-summary">
            <div class="tracking-preview-title">Tracking preview active</div>
            <div class="tracking-preview-compact-summary">
              {{ trackingPreviewCompactText }}
            </div>
            <div class="tracking-preview-stats">
              <span>Direction: {{ trackingPreviewDirectionText }}</span>
              <span>Frames: {{ trackingPreviewProcessedCount }}</span>
              <span>Pending: {{ trackingPreviewPendingCount }}</span>
              <span>Accepted: {{ trackingPreviewAcceptedCount }}</span>
              <span>Rejected: {{ trackingPreviewRejectedCount }}</span>
              <span>Needs fix: {{ trackingPreviewNeedsFixCount }}</span>
              <span>Failed: {{ trackingPreviewFailedCount }}</span>
            </div>
            <div class="tracking-preview-review-frames">
              Review frames: {{ trackingPreviewReviewFramesText }}
            </div>
            <div
              v-if="currentTrackingPreviewResult?.status === 'failed' && currentTrackingPreviewResult.detail"
              class="tracking-preview-warning"
            >
              Current frame warning: {{ currentTrackingPreviewResult.detail }}
            </div>
          </div>
          <div class="tracking-preview-actions">
            <el-button :disabled="acceptingTrackingPreview" @click="openTrackingReviewDialog">
              Review Results
            </el-button>
            <el-button :disabled="acceptingTrackingPreview || !currentTrackingFrameCanAccept" @click="acceptCurrentTrackingFrame">
              Accept Current
            </el-button>
            <el-button :disabled="acceptingTrackingPreview || !currentTrackingFrameCanFlag" @click="rejectCurrentTrackingFrame">
              Reject Current
            </el-button>
            <el-button :disabled="acceptingTrackingPreview || !currentTrackingFrameCanFlag" @click="markCurrentTrackingFrameNeedsFix">
              Mark Needs Fix
            </el-button>
            <el-button :disabled="acceptingTrackingPreview" @click="acceptReviewedTrackingFrames">
              Accept Reviewed
            </el-button>
            <el-button :disabled="acceptingTrackingPreview" @click="rejectTrackingPreview">
              Reject All
            </el-button>
            <el-button type="primary" :loading="acceptingTrackingPreview" @click="acceptTrackingPreview">
              Accept All
            </el-button>
          </div>
        </section>

        <section class="canvas-section">
          <AnnotationCanvas
            v-if="currentImage"
            ref="canvasRef"
            class="annotation-canvas-shell"
            :image="currentImage"
            :labels="job?.labels ?? []"
            :annotations="currentImageObjectAnnotations"
            :hidden-annotation-ids="hiddenAnnotationIds"
            :selected-annotation-id="selectedAnnotationId"
            :selected-label-id="selectedLabelId"
            :tracking-preview-points="currentTrackingPreviewPoints"
            :tracking-preview-variant="currentTrackingPreviewVariant"
            :sam2-settings="sam2Settings"
            :boundary-assist-reference-annotation-id="boundaryAssistReferenceAnnotationId"
            :tool="tool"
            :user-settings="userSettings"
            @boundary-assist-cancel="cancelBoundaryAssist"
            @boundary-assist-continue-polygon="continueBoundaryAssistAsPolygon"
            @boundary-assist-complete="completeBoundaryAssist"
            @before-change="pushUndoState"
            @change="updateCurrentImageAnnotations"
            @sam2-preview-change="hasSam2Preview = $event"
            @select-object="selectAnnotation"
          />

          <div v-else v-loading="loading" class="annotate-empty">
            <el-icon><Pointer /></el-icon>
            <p>No image loaded</p>
          </div>
        </section>
      </div>
    </section>

    <div
      class="annotation-right-panel-backdrop"
      :class="{ 'is-visible': isRightPanelOpen }"
      @click="closeRightPanel"
    ></div>

    <div class="annotate-right-panel-shell" :class="{ 'is-open': isRightPanelOpen }">
      <div class="right-panel-drawer-header">
        <strong>Objects {{ currentImageObjectAnnotations.length }}</strong>
        <button type="button" @click="closeRightPanel">Close</button>
      </div>
      <ObjectPanel
        class="annotate-right-panel"
        :annotations="currentImageObjectAnnotations"
        :hidden-annotation-ids="hiddenAnnotationIds"
        :labels="objectLabels"
        :sam2-refining="refiningSelectedPolygonWithSam2 || generatingSam2"
        :sam2-tracking="trackingWithSam2 || acceptingTrackingPreview"
        :selected-annotation-id="selectedAnnotationId"
        @create-layer-above="startBoundaryAssist"
        @delete-annotation="deleteAnnotation"
        @hide-all="hideAllAnnotations"
        @refine-selected-polygon="handleRefineSelectedPolygonWithSam2"
        @track-with-sam2="openTrackWithSam2"
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
      type="button"
      class="right-panel-edge-toggle"
      :class="{ 'is-hidden': isRightPanelOpen }"
      @click="openRightPanel"
    >
      Objects {{ currentImageObjectAnnotations.length }}
    </button>

    <div v-if="trackWithSam2DialogVisible" class="app-modal-backdrop" @click.self="closeTrackWithSam2Dialog">
      <section class="app-modal track-sam2-modal" @click.stop>
        <header class="track-sam2-modal-header">
          <div>
            <p class="eyebrow">SAM2 video tracking</p>
            <h2>Track with SAM2</h2>
            <span>Select a polygon annotation to track it through frames with SAM2.</span>
          </div>
          <el-button :disabled="trackingWithSam2" @click="closeTrackWithSam2Dialog">Close</el-button>
        </header>

        <div class="track-sam2-modal-body">
          <section class="track-sam2-summary">
            <h3>Selected object</h3>
            <p>Label: {{ trackingDialogTargetLabel?.name ?? 'Unknown' }}</p>
            <p>Current frame: {{ currentImageNumber }} / {{ totalImages }}</p>
            <p>Image: {{ currentImage?.filename ?? 'Unknown' }}</p>
          </section>

          <section class="track-sam2-section">
            <h3>Tracking direction</h3>
            <label class="track-sam2-radio" :class="{ disabled: !canTrackForwardFromCurrentFrame }">
              <input
                v-model="trackWithSam2Form.direction"
                :disabled="!canTrackForwardFromCurrentFrame"
                type="radio"
                value="forward"
              />
              <span>Forward</span>
            </label>
            <label class="track-sam2-radio" :class="{ disabled: !canTrackBackwardFromCurrentFrame }">
              <input
                v-model="trackWithSam2Form.direction"
                :disabled="!canTrackBackwardFromCurrentFrame"
                type="radio"
                value="backward"
              />
              <span>Backward</span>
            </label>
            <label class="track-sam2-radio" :class="{ disabled: !canTrackBothDirectionsFromCurrentFrame }">
              <input
                v-model="trackWithSam2Form.direction"
                :disabled="!canTrackBothDirectionsFromCurrentFrame"
                type="radio"
                value="both"
              />
              <span>Both directions</span>
            </label>
          </section>

          <section class="track-sam2-section">
            <h3>Tracking range</h3>
            <label class="track-sam2-field">
              <span>Start frame</span>
              <input :value="imageFrameIndex()" disabled type="number" />
            </label>
            <template v-if="trackWithSam2Form.direction === 'forward'">
              <label class="track-sam2-field">
                <span>End frame</span>
                <input
                  v-model.number="trackWithSam2Form.forwardEndFrameIndex"
                  :max="lastJobFrameIndex()"
                  :min="imageFrameIndex()"
                  type="number"
                />
              </label>
            </template>
            <template v-else-if="trackWithSam2Form.direction === 'backward'">
              <label class="track-sam2-field">
                <span>End frame</span>
                <input
                  v-model.number="trackWithSam2Form.backwardEndFrameIndex"
                  :max="imageFrameIndex()"
                  :min="firstJobFrameIndex()"
                  type="number"
                />
              </label>
            </template>
            <template v-else>
              <label class="track-sam2-field">
                <span>Backward end frame</span>
                <input
                  v-model.number="trackWithSam2Form.backwardEndFrameIndex"
                  :max="imageFrameIndex()"
                  :min="firstJobFrameIndex()"
                  type="number"
                />
              </label>
              <label class="track-sam2-field">
                <span>Forward end frame</span>
                <input
                  v-model.number="trackWithSam2Form.forwardEndFrameIndex"
                  :max="lastJobFrameIndex()"
                  :min="imageFrameIndex()"
                  type="number"
                />
              </label>
            </template>
          </section>

          <section class="track-sam2-section">
            <h3>Review interval</h3>
            <label class="track-sam2-field">
              <span>Review every N frames</span>
              <input v-model.number="trackWithSam2Form.reviewInterval" max="1000" min="1" type="number" />
            </label>
            <p class="track-sam2-help">
              Recommended: review every 10–20 frames. If tracking drifts, correct the mask on an intermediate frame and continue tracking from there.
            </p>
          </section>

          <section class="track-sam2-section">
            <h3>Output mode</h3>
            <label class="track-sam2-radio">
              <input v-model="trackWithSam2Form.outputMode" type="radio" value="preview_first" />
              <span>Preview first, then accept</span>
            </label>
            <label class="track-sam2-radio">
              <input v-model="trackWithSam2Form.outputMode" type="radio" value="direct_create" />
              <span>Directly create annotations</span>
            </label>
            <p v-if="trackWithSam2Form.outputMode === 'direct_create'" class="track-sam2-help">
              Direct mode will create annotations and save them automatically. Use Preview mode if you want to review or fix tracking results before saving.
            </p>
          </section>

          <section class="track-sam2-section">
            <h3>Existing annotations</h3>
            <label class="track-sam2-radio">
              <input v-model="trackWithSam2Form.existingAnnotationPolicy" type="radio" value="skip_same_label" />
              <span>Skip frames that already have this label</span>
            </label>
            <label class="track-sam2-radio">
              <input v-model="trackWithSam2Form.existingAnnotationPolicy" type="radio" value="replace_same_label" />
              <span>Replace existing annotations with same label</span>
            </label>
            <label class="track-sam2-radio">
              <input v-model="trackWithSam2Form.existingAnnotationPolicy" type="radio" value="append" />
              <span>Append as new annotations</span>
            </label>
          </section>
        </div>

        <footer class="track-sam2-modal-footer">
          <el-button :disabled="trackingWithSam2" @click="closeTrackWithSam2Dialog">Cancel</el-button>
          <el-button type="primary" :loading="trackingWithSam2" @click="startTrackWithSam2">
            Start Tracking
          </el-button>
        </footer>
      </section>
    </div>

    <div v-if="trackingReviewDialogVisible && trackingPreviewState" class="app-modal-backdrop" @click.self="closeTrackingReviewDialog">
      <section class="app-modal tracking-review-modal" @click.stop>
        <header class="track-sam2-modal-header">
          <div>
            <p class="eyebrow">Tracking workflow</p>
            <h2>Tracking Review</h2>
            <span>Review frames, jump to drift points, and accept only the tracking results you trust.</span>
          </div>
          <el-button :disabled="acceptingTrackingPreview" @click="closeTrackingReviewDialog">Close</el-button>
        </header>

        <div class="track-sam2-modal-body tracking-review-modal-body">
          <section class="tracking-review-summary">
            <div class="tracking-review-summary-card">
              <strong>Frames processed</strong>
              <span>{{ trackingPreviewProcessedCount }}</span>
            </div>
            <div class="tracking-review-summary-card">
              <strong>Pending</strong>
              <span>{{ trackingPreviewPendingCount }}</span>
            </div>
            <div class="tracking-review-summary-card">
              <strong>Accepted</strong>
              <span>{{ trackingPreviewAcceptedCount }}</span>
            </div>
            <div class="tracking-review-summary-card">
              <strong>Rejected</strong>
              <span>{{ trackingPreviewRejectedCount }}</span>
            </div>
            <div class="tracking-review-summary-card">
              <strong>Needs fix</strong>
              <span>{{ trackingPreviewNeedsFixCount }}</span>
            </div>
            <div class="tracking-review-summary-card">
              <strong>Failed</strong>
              <span>{{ trackingPreviewFailedCount }}</span>
            </div>
          </section>

          <section class="track-sam2-section">
            <h3>Accept selected range</h3>
            <div class="tracking-review-range">
              <label class="track-sam2-field">
                <span>Start frame</span>
                <input
                  v-model.number="trackingReviewRangeStart"
                  :max="trackingPreviewState.endFrameIndex"
                  :min="trackingPreviewState.startFrameIndex"
                  type="number"
                />
              </label>
              <label class="track-sam2-field">
                <span>End frame</span>
                <input
                  v-model.number="trackingReviewRangeEnd"
                  :max="trackingPreviewState.endFrameIndex"
                  :min="trackingPreviewState.startFrameIndex"
                  type="number"
                />
              </label>
              <el-button :disabled="acceptingTrackingPreview" @click="acceptTrackingRange">
                Accept Range
              </el-button>
            </div>
            <p class="track-sam2-help">
              Recommended workflow: review every 10–20 frames. If drift is visible, mark that frame as needs fix, correct the polygon there, then run Track with SAM2 again from the corrected frame.
            </p>
          </section>

          <section class="track-sam2-section">
            <h3>Tracking results</h3>
            <div class="tracking-review-table-scroll">
              <div class="tracking-review-table">
                <div class="tracking-review-row tracking-review-row-head">
                  <span>Frame</span>
                  <span>Filename</span>
                  <span>Direction</span>
                  <span>Status</span>
                  <span>Review</span>
                  <span>Action</span>
                </div>
                <div
                  v-for="result in trackingPreviewState.results"
                  :key="result.image_id"
                  class="tracking-review-row"
                  :class="[
                    `tracking-review-row-status-${result.status}`,
                    `tracking-review-row-review-${result.review_status}`,
                    { committed: result.committed },
                  ]"
                >
                  <span>
                    {{ result.frame_index }}
                    <span v-if="isTrackingReviewFrame(result.frame_index)" class="tracking-review-tag review">Review</span>
                  </span>
                  <span>{{ result.filename }}</span>
                  <span>{{ formatPropagationDirection(result.propagation_direction) }}</span>
                  <span>
                    <span class="tracking-review-tag" :class="result.status">{{ result.status }}</span>
                  </span>
                  <span>
                    <span class="tracking-review-tag" :class="result.review_status">{{ result.review_status }}</span>
                    <span v-if="result.committed" class="tracking-review-tag committed">saved</span>
                  </span>
                  <span class="tracking-review-actions">
                    <el-button size="small" @click="goToTrackingFrame(result.image_id)">Go</el-button>
                  <el-button
                    size="small"
                    :disabled="result.status !== 'tracked' || !canAcceptTrackingResult(result)"
                    @click="acceptTrackingFrame(result.image_id)"
                  >
                    Accept
                  </el-button>
                    <el-button
                      size="small"
                      :disabled="result.status !== 'tracked' || result.committed"
                      @click="rejectTrackingFrame(result.image_id)"
                    >
                      Reject
                    </el-button>
                    <el-button
                      size="small"
                      :disabled="result.status !== 'tracked' || result.committed"
                      @click="markTrackingFrameNeedsFix(result.image_id)"
                    >
                      Needs Fix
                    </el-button>
                  </span>
                </div>
              </div>
            </div>
          </section>
        </div>

        <footer class="track-sam2-modal-footer tracking-review-modal-footer">
          <el-button :disabled="acceptingTrackingPreview" @click="closeTrackingReviewDialog">Close</el-button>
          <el-button :disabled="acceptingTrackingPreview" @click="acceptReviewedTrackingFrames">
            Accept Reviewed
          </el-button>
          <el-button type="primary" :loading="acceptingTrackingPreview" @click="acceptTrackingPreview">
            Accept All
          </el-button>
        </footer>
      </section>
    </div>

    <div v-if="labelManagerVisible" class="app-modal-backdrop" @click.self="closeLabelManager">
      <section class="app-modal label-management-modal" @click.stop>
        <header class="label-management-modal-header">
          <div>
            <p class="eyebrow">Job labels</p>
            <h2>Manage Labels</h2>
            <span>{{ job?.name ?? `Job ${jobId}` }}</span>
          </div>
          <el-button :disabled="labelActionLoading" @click="closeLabelManager">Close</el-button>
        </header>

        <div v-loading="labelManagerLoading" class="label-management-modal-body">
          <section class="label-management-section">
            <div class="label-management-section-header">
              <h3>Object annotation labels</h3>
              <span>Polygon, rectangle, and point labels used on the canvas.</span>
            </div>
            <div class="label-management-table">
              <div class="label-management-row label-management-row-head">
                <span>Color</span>
                <span>Name</span>
                <span>Shape</span>
                <span>Used</span>
                <span>Actions</span>
              </div>

              <div v-for="label in objectLabelDrafts" :key="label.id" class="label-management-row">
                <input v-model="label.color" class="label-management-color" type="color" />
                <input
                  v-model="label.name"
                  class="label-management-name"
                  :disabled="isUndefinedLabel(label)"
                  type="text"
                />
                <select v-model="label.shape_type" class="label-management-shape">
                  <option value="polygon">polygon</option>
                  <option value="rectangle">rectangle</option>
                  <option value="point">point</option>
                </select>
                <span class="label-management-used">{{ labelUsedCount(label) }}</span>
                <div class="label-management-actions">
                  <el-button size="small" :loading="labelActionLoading" @click="saveManagedLabel(label)">
                    Save
                  </el-button>
                  <el-button
                    size="small"
                    text
                    type="danger"
                    :loading="labelActionLoading"
                    @click="requestDeleteManagedLabel(label)"
                  >
                    Delete
                  </el-button>
                </div>
              </div>

              <div v-if="objectLabelDrafts.length === 0" class="label-management-empty">
                No object annotation labels yet.
              </div>
            </div>
          </section>

          <section class="label-management-section">
            <div class="label-management-section-header">
              <h3>Image classification labels</h3>
              <span>Whole-image classes used by the classify tool.</span>
            </div>
            <div class="label-management-table">
              <div class="label-management-row label-management-row-head">
                <span>Color</span>
                <span>Name</span>
                <span>Type</span>
                <span>Used</span>
                <span>Actions</span>
              </div>

              <div v-for="label in classificationLabelDrafts" :key="label.id" class="label-management-row">
                <input v-model="label.color" class="label-management-color" type="color" />
                <input
                  v-model="label.name"
                  class="label-management-name"
                  type="text"
                />
                <input class="label-management-shape" disabled type="text" value="classification" />
                <span class="label-management-used">{{ labelUsedCount(label) }}</span>
                <div class="label-management-actions">
                  <el-button size="small" :loading="labelActionLoading" @click="saveManagedLabel(label)">
                    Save
                  </el-button>
                  <el-button
                    size="small"
                    text
                    type="danger"
                    :loading="labelActionLoading"
                    @click="requestDeleteManagedLabel(label)"
                  >
                    Delete
                  </el-button>
                </div>
              </div>

              <div v-if="classificationLabelDrafts.length === 0" class="label-management-empty">
                No image classification labels yet.
              </div>
            </div>
          </section>

          <section class="label-management-add">
            <h3>Add Label</h3>
            <div class="label-management-add-row label-management-add-row-extended">
              <input v-model="newLabelColor" class="label-management-color" type="color" />
              <input v-model="newLabelName" class="label-management-name" placeholder="Label name" type="text" />
              <select v-model="newLabelKind" class="label-management-shape">
                <option value="object_annotation">Object annotation</option>
                <option value="image_classification">Image classification</option>
              </select>
              <select
                v-if="newLabelKind === 'object_annotation'"
                v-model="newLabelShapeType"
                class="label-management-shape"
              >
                <option value="polygon">polygon</option>
                <option value="rectangle">rectangle</option>
                <option value="point">point</option>
              </select>
              <input
                v-else
                class="label-management-shape"
                disabled
                type="text"
                value="classification"
              />
              <el-button type="primary" :loading="labelActionLoading" @click="addManagedLabel">
                Add Label
              </el-button>
            </div>
          </section>
        </div>
      </section>
    </div>

    <Teleport to="body">
      <div
        v-if="deleteLabelModalVisible"
        class="label-delete-dialog-backdrop"
        @click.self="closeDeleteLabelModal"
      >
        <section class="label-delete-dialog" @click.stop>
          <button class="label-delete-dialog-close" type="button" @click="closeDeleteLabelModal">×</button>

          <h3>Delete Label</h3>

          <template v-if="pendingDeleteUsage?.annotation_count === 0">
            <p>Delete label "{{ pendingDeleteLabel?.name }}"?</p>

            <div class="modal-actions">
              <el-button @click="closeDeleteLabelModal">Cancel</el-button>
              <el-button type="danger" :loading="labelActionLoading" @click="confirmDeleteUnusedLabel">
                Delete Label
              </el-button>
            </div>
          </template>

          <template v-else>
            <p>
              This label is used by {{ pendingDeleteUsage?.annotation_count ?? 0 }}
              annotations in {{ pendingDeleteUsage?.frame_count ?? 0 }} frames.
              Please choose how to handle these annotations.
            </p>

            <el-radio-group v-model="deleteLabelStrategy" class="delete-label-strategy-group">
              <el-radio label="reassign" value="reassign">
                Reassign annotations to another label
              </el-radio>

              <el-radio
                v-if="pendingDeleteLabel && !isUndefinedLabel(pendingDeleteLabel)"
                label="move_to_undefined"
                value="move_to_undefined"
              >
                Move annotations to undefined
              </el-radio>

              <el-radio label="delete_annotations" value="delete_annotations">
                Delete annotations using this label
              </el-radio>
            </el-radio-group>

            <el-select
              v-if="deleteLabelStrategy === 'reassign'"
              v-model="reassignTargetLabelId"
              teleported
              class="delete-label-target-select"
              placeholder="Select target label"
            >
              <el-option
                v-for="label in compatibleReassignLabelOptions(pendingDeleteLabel)"
                :key="label.id"
                :label="label.name"
                :value="label.id"
              />
            </el-select>

            <div v-if="deleteLabelStrategy === 'delete_annotations'" class="danger-warning">
              This will permanently delete all annotations using this label. This action cannot be undone.
            </div>

            <div class="modal-actions">
              <el-button @click="closeDeleteLabelModal">Cancel</el-button>
              <el-button type="danger" :loading="labelActionLoading" @click="confirmDeleteUsedLabel">
                Confirm Delete
              </el-button>
            </div>
          </template>
        </section>
      </div>
    </Teleport>
  </main>
</template>
