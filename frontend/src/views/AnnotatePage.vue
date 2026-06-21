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
type LabelDraft = {
  id: number
  name: string
  color: string
  shape_type: ShapeType
  annotation_count: number
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
const newLabelShapeType = ref<ShapeType>('polygon')
const deleteLabelModalVisible = ref(false)
const pendingDeleteLabel = ref<LabelDraft | null>(null)
const pendingDeleteUsage = ref<LabelUsage | null>(null)
const deleteLabelStrategy = ref<LabelDeleteStrategy>('move_to_undefined')
const reassignTargetLabelId = ref<number | null>(null)
const activePolygonSmoothingAnnotationId = ref<number | string | null>(null)
const boundaryAssistReferenceAnnotationId = ref<number | string | null>(null)

const currentImage = computed(() => job.value?.images[selectedImageIndex.value] ?? null)
const totalImages = computed(() => job.value?.images.length ?? 0)
const currentImageNumber = computed(() => (currentImage.value ? selectedImageIndex.value + 1 : 0))
const isFirstImage = computed(() => selectedImageIndex.value <= 0)
const isLastImage = computed(() => selectedImageIndex.value >= totalImages.value - 1)
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
const canUndo = computed(() => undoStack.value.length > 0)

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
  selectedLabelId.value = job.value?.labels[0]?.id ?? null
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
  }
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
  const labels = job.value?.labels ?? []
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

  labelActionLoading.value = true
  const created = await annotationStore.createJobLabel(props.jobId, {
    name,
    color,
    shape_type: newLabelShapeType.value,
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

  labelActionLoading.value = true
  const updated = await annotationStore.updateJobLabel(props.jobId, label.id, {
    name,
    color: normalizedColor,
    shape_type: label.shape_type,
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
  reassignTargetLabelId.value = labelDrafts.value.find((item) => item.id !== label.id)?.id ?? null
  if (usage.annotation_count === 0) {
    deleteLabelStrategy.value = 'delete_annotations'
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

  const normalizedAnnotations = nextAnnotations.map((annotation) => normalizeAnnotationObject(annotation))
  job.value.annotations = [
    ...job.value.annotations.filter((annotation) => annotation.image_id !== currentImage.value?.id),
    ...normalizedAnnotations,
  ]
  hasUnsavedChanges.value = true
}

function cloneAnnotations(annotations: AnnotationObject[]): AnnotationObject[] {
  return JSON.parse(JSON.stringify(annotations)) as AnnotationObject[]
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
  suppressNextSelectToolSwitch.value = true
  let accepted = false
  try {
    accepted = canvasRef.value?.acceptSam2Preview() ?? false
  } finally {
    suppressNextSelectToolSwitch.value = false
  }

  if (!accepted) {
    ElMessage.warning('No SAM2 mask preview to accept.')
    return
  }

  hasSam2Preview.value = false
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
  <main class="annotate-page">
    <aside class="annotate-sidebar annotation-sidebar-left">
      <div class="sidebar-header">
        <router-link :to="jobsBackRoute" class="annotate-back">
          <el-icon><Back /></el-icon>
          Jobs
        </router-link>

        <div>
          <p class="eyebrow">Annotation workspace</p>
          <h1>{{ job?.name ?? `Job ${jobId}` }}</h1>
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
          </div>
        </section>
      </div>

      <div class="sidebar-middle" :class="{ 'sidebar-middle-sam2': tool === 'sam2' }">
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
                v-for="label in job?.labels ?? []"
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
              :class="{ active: selectedImageIndex === index }"
              type="button"
              @click="goToImage(index)"
            >
              {{ index + 1 }}. {{ image.filename }}
            </button>
          </div>
        </div>
      </div>

      <div class="sidebar-footer sidebar-bottom annotate-actions">
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

          <div v-if="tool === 'sam2'" class="toolbar-group toolbar-group-sam2">
            <el-button
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
        </div>
      </header>

      <el-alert v-if="error" :title="error" type="error" show-icon />

      <AnnotationCanvas
        v-if="currentImage"
        ref="canvasRef"
        :image="currentImage"
        :labels="job?.labels ?? []"
        :annotations="currentImageAnnotations"
        :hidden-annotation-ids="hiddenAnnotationIds"
        :selected-annotation-id="selectedAnnotationId"
        :selected-label-id="selectedLabelId"
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

    <ObjectPanel
      :annotations="currentImageAnnotations"
      :hidden-annotation-ids="hiddenAnnotationIds"
      :labels="job?.labels ?? []"
      :selected-annotation-id="selectedAnnotationId"
      @create-layer-above="startBoundaryAssist"
      @delete-annotation="deleteAnnotation"
      @hide-all="hideAllAnnotations"
      @show-all="showAllAnnotations"
      @select-annotation="selectAnnotation"
      @commit-polygon-smoothing="commitPolygonSmoothing"
      @reset-polygon-smoothing="resetPolygonSmoothing"
      @toggle-visibility="toggleAnnotationVisibility"
      @update-annotation-label="updateAnnotationLabel"
      @update-polygon-smoothing="updatePolygonSmoothing"
    />

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
          <div class="label-management-table">
            <div class="label-management-row label-management-row-head">
              <span>Color</span>
              <span>Name</span>
              <span>Shape</span>
              <span>Used</span>
              <span>Actions</span>
            </div>

            <div v-for="label in labelDrafts" :key="label.id" class="label-management-row">
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
              <span class="label-management-used">{{ label.annotation_count }}</span>
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

            <div v-if="labelDrafts.length === 0" class="label-management-empty">
              No labels yet. Add a label before creating annotations.
            </div>
          </div>

          <section class="label-management-add">
            <h3>Add Label</h3>
            <div class="label-management-add-row">
              <input v-model="newLabelColor" class="label-management-color" type="color" />
              <input v-model="newLabelName" class="label-management-name" placeholder="Label name" type="text" />
              <select v-model="newLabelShapeType" class="label-management-shape">
                <option value="polygon">polygon</option>
                <option value="rectangle">rectangle</option>
                <option value="point">point</option>
              </select>
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
                v-for="label in labelDrafts.filter((item) => item.id !== pendingDeleteLabel?.id)"
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
