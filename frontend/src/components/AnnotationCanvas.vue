<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import type { AnnotationObject, JobImage, Label } from '../stores/annotation'
import type { Shortcut, UserSettings } from '../stores/userSettings'
import { apiUrl } from '../utils/api'
import { generateClientId } from '../utils/id'

type ToolType = 'cursor' | 'rectangle' | 'polygon' | 'sam2'
type Sam2PointLabel = 0 | 1
type Sam2ModelName = 'sam2_hiera_tiny' | 'sam2_hiera_small' | 'sam2_hiera_base_plus' | 'sam2_hiera_large'
type Sam2PromptPoint = {
  id: string
  point: number[]
  label: Sam2PointLabel
}
type Sam2Prompt = {
  point_coords: number[][]
  point_labels: number[]
  box: number[] | null
}
type Sam2Settings = {
  model_name: Sam2ModelName
  multimask_output: boolean
  show_prompt_points: boolean
  polygon_epsilon: number
  min_mask_area: number
  mask_threshold: number
  max_hole_area: number
  candidate: 'best' | '0' | '1' | '2'
}
type Sam2PredictResponse = {
  image_id: number
  score: number
  points: number[][]
  model_name: Sam2ModelName
  candidate: 'best' | '0' | '1' | '2'
  polygon_epsilon: number
  mask_threshold: number
  max_hole_area: number
  num_contours: number
  mask_area: number
}

const props = defineProps<{
  image: JobImage
  labels: Label[]
  annotations: AnnotationObject[]
  hiddenAnnotationIds: Array<number | string>
  selectedLabelId: number | null
  selectedAnnotationId: number | string | null
  sam2Settings: Sam2Settings
  tool: ToolType
  userSettings: UserSettings
}>()

const emit = defineEmits<{
  beforeChange: []
  change: [annotations: AnnotationObject[]]
  selectObject: [id: string | number | null]
  sam2PreviewChange: [available: boolean]
}>()

const imageElement = ref<HTMLImageElement | null>(null)
const canvasElement = ref<HTMLDivElement | null>(null)
const containerSize = ref({ width: 1, height: 1 })
const loadedImageUrl = ref('')
const draftPoints = ref<number[][]>([])
const mousePoint = ref<number[] | null>(null)
const isPointerInside = ref(false)
const rectangleStart = ref<number[] | null>(null)
const rectanglePreviewEnd = ref<number[] | null>(null)
const drawingRectangle = ref(false)
const sam2Points = ref<Sam2PromptPoint[]>([])
const sam2Box = ref<number[] | null>(null)
const sam2BoxStart = ref<number[] | null>(null)
const sam2BoxPreviewEnd = ref<number[] | null>(null)
const sam2PointerLabel = ref<Sam2PointLabel>(1)
const drawingSam2Box = ref(false)
const sam2PreviewPoints = ref<number[][] | null>(null)
const sam2Prediction = ref<Sam2PredictResponse | null>(null)
const sam2Error = ref<string | null>(null)
const hoveredSamPointId = ref<string | null>(null)
const hoveredPolygonVertexIndex = ref<number | null>(null)
const hoveredPolygonSegmentIndex = ref<number | null>(null)
const viewScale = ref(1)
const offsetX = ref(0)
const offsetY = ref(0)
const pressedKeys = ref(new Set<string>())
const isPanning = ref(false)
const lastPanPoint = ref<{ x: number; y: number } | null>(null)
const isCursorPanning = ref(false)
const panStartPoint = ref<{ x: number; y: number } | null>(null)
const panStartOffset = ref<{ x: number; y: number } | null>(null)
const hasMovedDuringPan = ref(false)
const suppressNextCanvasClick = ref(false)
type RectangleHandle = 'tl' | 'tr' | 'br' | 'bl'
type DraggingHandle = {
  type: 'polygon-vertex'
  annotationId: number | string
  pointIndex: number
} | {
  type: 'rectangle-handle'
  annotationId: number | string
  handle: RectangleHandle
}

const draggingHandle = ref<DraggingHandle | null>(null)
const hasInitializedView = ref(false)
const lastViewAppliedImageUrl = ref('')

const minScale = 0.1
const maxScale = 10
const scaleBy = 1.1
let samPredictionDebounceTimer: ReturnType<typeof window.setTimeout> | null = null
let samPointDeleteHideTimer: ReturnType<typeof window.setTimeout> | null = null

const currentAnnotations = computed(() =>
  props.annotations.filter((annotation) => annotation.image_id === props.image.id),
)
const visibleAnnotations = computed(() =>
  currentAnnotations.value.filter((annotation) => !props.hiddenAnnotationIds.includes(annotation.id)),
)
const selectedAnnotation = computed(() =>
  currentAnnotations.value.find((annotation) => annotation.id === props.selectedAnnotationId) ?? null,
)
const displayedAnnotations = computed(() =>
  visibleAnnotations.value.map((annotation) => {
    const points = annotation.points.map(imageToCanvasPoint)
    const rectangle = annotation.shape_type === 'rectangle' && points.length >= 2
      ? {
          x: Math.min(points[0][0], points[1][0]),
          y: Math.min(points[0][1], points[1][1]),
          width: Math.abs(points[1][0] - points[0][0]),
          height: Math.abs(points[1][1] - points[0][1]),
        }
      : null

    return {
      annotation,
      points,
      pointsValue: points.map((point) => point.join(',')).join(' '),
      rectangle,
      stroke: labelFor(annotation.label_id)?.color ?? '#22c55e',
      fill: labelFill(annotation.label_id),
    }
  }),
)

const activeLabel = computed(() => props.labels.find((label) => label.id === props.selectedLabelId))
const activeColor = computed(() => activeLabel.value?.color ?? '#22c55e')
const drawingToolActive = computed(() => props.tool === 'rectangle' || props.tool === 'polygon' || props.tool === 'sam2')
const annotationGroupPointerEvents = computed(() => props.tool === 'cursor' ? 'all' : 'none')
const annotationShapePointerEvents = computed(() => props.tool === 'cursor' ? 'visiblePainted' : 'none')
const selectedAnnotationId = computed(() => props.selectedAnnotationId)
const zoomPercent = computed(() => Math.round(viewScale.value * 100))
const isDraggingHandle = computed(() => draggingHandle.value !== null)
const isEditingExistingAnnotation = computed(() => draggingHandle.value !== null)
const isPanModifierActive = computed(() => pressedKeys.value.has(props.userSettings.pan_modifier_shortcut))
const shouldShowCursorPoint = computed(() =>
  drawingToolActive.value &&
  isPointerInside.value &&
  !isPanning.value &&
  !isCursorPanning.value &&
  !isEditingExistingAnnotation.value &&
  displayedMousePoint.value !== null,
)
const shouldShowDraftDrawing = computed(() =>
  !isEditingExistingAnnotation.value && (props.tool === 'rectangle' || props.tool === 'polygon'),
)
const showPolygonHint = computed(() => props.tool === 'polygon')
const polygonHintStarted = computed(() => draftPoints.value.length >= 1)
const polygonHintReady = computed(() => draftPoints.value.length >= 3)
const polygonHintText = computed(() =>
  polygonHintReady.value
    ? `Press Enter to Complete Polygon · ${shortcutLabel(props.userSettings.polygon_confirm_point_shortcut)} to add point`
    : `Press Enter to Finish Polygon · ${shortcutLabel(props.userSettings.polygon_confirm_point_shortcut)} to add point`,
)
const showPolygonEditHint = computed(() =>
  props.tool === 'cursor' && selectedAnnotation.value?.shape_type === 'polygon',
)
const polygonEditHintText = computed(() =>
  `${shortcutLabel(props.userSettings.add_polygon_vertex_shortcut)} + click edge to add vertex · ${shortcutLabel(props.userSettings.delete_polygon_vertex_shortcut)} + click vertex to delete`,
)
const shouldShowSam2PromptPoints = computed(() => props.tool === 'sam2' && props.sam2Settings.show_prompt_points)
const displayedMousePoint = computed(() => (mousePoint.value ? imageToCanvasPoint(mousePoint.value) : null))
const displayedDraftPoints = computed(() => draftPoints.value.map(imageToCanvasPoint))
const displayedRectangleStart = computed(() => (rectangleStart.value ? imageToCanvasPoint(rectangleStart.value) : null))
const displayedRectangleEnd = computed(() => (rectanglePreviewEnd.value ? imageToCanvasPoint(rectanglePreviewEnd.value) : null))
const displayedSam2Points = computed(() =>
  sam2Points.value.map((promptPoint) => ({
    key: promptPoint.id,
    id: promptPoint.id,
    label: promptPoint.label,
    point: imageToCanvasPoint(promptPoint.point),
  })),
)
const displayedSam2PreviewPoints = computed(() => sam2PreviewPoints.value?.map(imageToCanvasPoint) ?? [])
const displayedSam2PreviewValue = computed(() => displayedSam2PreviewPoints.value.map((point) => point.join(',')).join(' '))
const displayedSam2Box = computed(() => (sam2Box.value ? rectFromImageBox(sam2Box.value) : null))
const displayedSam2BoxPreview = computed(() => {
  if (!sam2BoxStart.value || !sam2BoxPreviewEnd.value) {
    return null
  }

  const start = imageToCanvasPoint(sam2BoxStart.value)
  const end = imageToCanvasPoint(sam2BoxPreviewEnd.value)
  return rectFromCanvasPoints(start, end)
})
const selectedControlPoints = computed(() => {
  const annotation = selectedAnnotation.value
  if (!annotation || props.hiddenAnnotationIds.includes(annotation.id)) {
    return []
  }

  if (annotation.shape_type === 'rectangle' && annotation.points.length >= 2) {
    const rect = normalizedRectangle(annotation.points)
    return [
      { key: 'tl', point: imageToCanvasPoint([rect.minX, rect.minY]), kind: 'rect' },
      { key: 'tr', point: imageToCanvasPoint([rect.maxX, rect.minY]), kind: 'rect' },
      { key: 'br', point: imageToCanvasPoint([rect.maxX, rect.maxY]), kind: 'rect' },
      { key: 'bl', point: imageToCanvasPoint([rect.minX, rect.maxY]), kind: 'rect' },
    ]
  }

  return annotation.points.map((point, index) => ({
    key: String(index),
    point: imageToCanvasPoint(point),
    kind: 'polygon',
  }))
})
const hoveredPolygonSegment = computed(() => {
  const annotation = selectedAnnotation.value
  const segmentIndex = hoveredPolygonSegmentIndex.value
  if (props.tool !== 'cursor' || !annotation || annotation.shape_type !== 'polygon' || segmentIndex === null) {
    return null
  }

  const start = annotation.points[segmentIndex]
  const end = annotation.points[(segmentIndex + 1) % annotation.points.length]
  if (!start || !end) {
    return null
  }

  return {
    start: imageToCanvasPoint(start),
    end: imageToCanvasPoint(end),
  }
})
const imageStyle = computed(() => ({
  width: `${props.image.width || 1}px`,
  height: `${props.image.height || 1}px`,
  transform: `translate(${offsetX.value}px, ${offsetY.value}px) scale(${viewScale.value})`,
}))
const cursorStyle = computed(() => {
  if (isPanning.value || isCursorPanning.value) {
    return 'grabbing'
  }

  if (draggingHandle.value) {
    return 'move'
  }

  if (drawingToolActive.value && isPanModifierActive.value) {
    return 'grab'
  }

  if (props.tool === 'cursor') {
    return 'grab'
  }

  return drawingToolActive.value && !isEditingExistingAnnotation.value ? 'crosshair' : 'default'
})
const rectanglePreview = computed(() => {
  if (!displayedRectangleStart.value || !displayedRectangleEnd.value) {
    return null
  }

  const [x1, y1] = displayedRectangleStart.value
  const [x2, y2] = displayedRectangleEnd.value
  return {
    x: Math.min(x1, x2),
    y: Math.min(y1, y2),
    width: Math.abs(x2 - x1),
    height: Math.abs(y2 - y1),
  }
})

watch(
  () => props.image,
  () => {
    draftPoints.value = []
    resetRectangleDraft()
    clearSam2State()
    mousePoint.value = null
    isPointerInside.value = false
    isPanning.value = false
    clearPressedKeys()
    lastPanPoint.value = null
    clearPolygonEditHover()
    resetCursorPan()
    draggingHandle.value = null
    suppressNextCanvasClick.value = false
    window.removeEventListener('pointermove', handleGlobalPointerMove)
    window.removeEventListener('pointerup', stopDragHandle)
    window.removeEventListener('pointermove', handleCursorPanMove)
    window.removeEventListener('pointerup', stopCursorPan)
    preloadImage()
  },
  { immediate: true },
)

watch(
  () => props.tool,
  () => {
    resetRectangleDraft()
    clearPolygonEditHover()
    if (props.tool !== 'polygon') {
      draftPoints.value = []
    }
    if (props.tool !== 'sam2') {
      clearSam2State()
    }
  },
)

watch(
  () => props.selectedAnnotationId,
  () => {
    clearPolygonEditHover()
  },
)

watch(
  () => props.sam2Settings.model_name,
  () => {
    clearSam2Preview()
    if (props.tool === 'sam2' && hasSamPrompts()) {
      scheduleSamPrediction()
    }
  },
)

watch(
  () => [
    props.sam2Settings.polygon_epsilon,
    props.sam2Settings.candidate,
    props.sam2Settings.multimask_output,
    props.sam2Settings.min_mask_area,
    props.sam2Settings.mask_threshold,
    props.sam2Settings.max_hole_area,
  ],
  () => {
    if (props.tool === 'sam2' && hasSamPrompts()) {
      scheduleSamPrediction()
    }
  },
)

watch(
  () => [
    props.userSettings.sam_result_edge_snap_enabled,
    props.userSettings.sam_result_edge_snap_threshold,
  ],
  () => {
    if (sam2Prediction.value) {
      sam2PreviewPoints.value = applySamResultEdgeSnapToPolygon(sam2Prediction.value.points)
    }
  },
)

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('keyup', onKeyup)
  window.addEventListener('blur', clearPressedKeys)
  window.addEventListener('mouseup', stopPointerInteractions)
  window.addEventListener('resize', fitToScreen)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('keyup', onKeyup)
  window.removeEventListener('blur', clearPressedKeys)
  window.removeEventListener('mouseup', stopPointerInteractions)
  window.removeEventListener('pointermove', handleGlobalPointerMove)
  window.removeEventListener('pointerup', stopDragHandle)
  window.removeEventListener('pointermove', handleCursorPanMove)
  window.removeEventListener('pointerup', stopCursorPan)
  window.removeEventListener('resize', fitToScreen)
  clearSamPredictionDebounce()
  clearSamPointDeleteTimer()
})

function preloadImage() {
  const imageUrl = props.image.image_url
  console.log('current image url:', imageUrl)

  loadedImageUrl.value = ''
  const img = new window.Image()
  img.crossOrigin = 'anonymous'
  img.onload = () => {
    loadedImageUrl.value = imageUrl
    void nextTick(() => {
      updateContainerSize()
      applyViewForLoadedImage()
    })
  }
  img.onerror = () => {
    console.error('failed to load image:', imageUrl)
  }
  img.src = imageUrl
}

function updateContainerSize() {
  if (!canvasElement.value) {
    return
  }

  containerSize.value = {
    width: canvasElement.value.clientWidth || 1,
    height: canvasElement.value.clientHeight || 1,
  }
}

function applyViewForLoadedImage() {
  const imageUrl = loadedImageUrl.value || props.image.image_url
  if (imageUrl && lastViewAppliedImageUrl.value === imageUrl) {
    return
  }
  lastViewAppliedImageUrl.value = imageUrl

  if (!hasInitializedView.value) {
    fitToScreen()
    hasInitializedView.value = true
    return
  }

  if (!props.userSettings.keep_view_transform_on_frame_switch) {
    fitToScreen()
    return
  }

  preserveCurrentViewTransform()
}

function preserveCurrentViewTransform() {
  updateContainerSize()
  viewScale.value = clamp(viewScale.value, minScale, maxScale)

  const imageWidth = Math.max(props.image.width || 1, 1)
  const imageHeight = Math.max(props.image.height || 1, 1)
  const scaledWidth = imageWidth * viewScale.value
  const scaledHeight = imageHeight * viewScale.value
  const minimumVisiblePixels = 1

  offsetX.value = clamp(
    offsetX.value,
    minimumVisiblePixels - scaledWidth,
    containerSize.value.width - minimumVisiblePixels,
  )
  offsetY.value = clamp(
    offsetY.value,
    minimumVisiblePixels - scaledHeight,
    containerSize.value.height - minimumVisiblePixels,
  )
}

function labelFor(labelId: number): Label | undefined {
  return props.labels.find((label) => label.id === labelId)
}

function normalizedRectangle(points: number[][]) {
  const [first, second] = points
  const x1 = first?.[0] ?? 0
  const y1 = first?.[1] ?? 0
  const x2 = second?.[0] ?? x1
  const y2 = second?.[1] ?? y1
  return {
    minX: Math.min(x1, x2),
    minY: Math.min(y1, y2),
    maxX: Math.max(x1, x2),
    maxY: Math.max(y1, y2),
  }
}

function labelFill(labelId: number): string {
  return colorWithAlpha(labelFor(labelId)?.color ?? '#22c55e', 0.16)
}

function activeFill(): string {
  return colorWithAlpha(activeColor.value, 0.16)
}

function colorWithAlpha(color: string, alpha: number): string {
  if (!color.startsWith('#')) {
    return color
  }

  const hex = color.slice(1)
  const normalized = hex.length === 3
    ? hex.split('').map((character) => `${character}${character}`).join('')
    : hex

  const red = Number.parseInt(normalized.slice(0, 2), 16)
  const green = Number.parseInt(normalized.slice(2, 4), 16)
  const blue = Number.parseInt(normalized.slice(4, 6), 16)
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`
}

function imageToCanvas(x: number, y: number) {
  return {
    x: x * viewScale.value + offsetX.value,
    y: y * viewScale.value + offsetY.value,
  }
}

function imageToCanvasPoint(point: number[]): number[] {
  const canvasPoint = imageToCanvas(point[0], point[1])
  return [canvasPoint.x, canvasPoint.y]
}

function canvasToImage(x: number, y: number) {
  return {
    x: (x - offsetX.value) / viewScale.value,
    y: (y - offsetY.value) / viewScale.value,
  }
}

function pointerToCanvas(event: MouseEvent) {
  if (!canvasElement.value) {
    return null
  }

  const rect = canvasElement.value.getBoundingClientRect()
  return {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top,
  }
}

function fromPointer(event: MouseEvent): number[] | null {
  const canvasPoint = pointerToCanvas(event)
  if (!canvasPoint) {
    return null
  }

  const imagePoint = canvasToImage(canvasPoint.x, canvasPoint.y)
  if (!isImagePointInside(imagePoint.x, imagePoint.y)) {
    return null
  }

  const snappedPoint = applyEdgeSnap(imagePoint)
  return [snappedPoint.x, snappedPoint.y]
}

function isInsideImage(event: MouseEvent): boolean {
  const canvasPoint = pointerToCanvas(event)
  if (!canvasPoint) {
    return false
  }

  const imagePoint = canvasToImage(canvasPoint.x, canvasPoint.y)
  return isImagePointInside(imagePoint.x, imagePoint.y)
}

function isImagePointInside(x: number, y: number): boolean {
  const imageWidth = props.image.width || 1
  const imageHeight = props.image.height || 1
  return x >= 0 && y >= 0 && x <= imageWidth && y <= imageHeight
}

function onPointerMove(event: PointerEvent) {
  const canvasPoint = pointerToCanvas(event)
  if (isPanning.value && canvasPoint && lastPanPoint.value) {
    offsetX.value += canvasPoint.x - lastPanPoint.value.x
    offsetY.value += canvasPoint.y - lastPanPoint.value.y
    lastPanPoint.value = canvasPoint
    return
  }

  if (!isInsideImage(event)) {
    isPointerInside.value = false
    mousePoint.value = null
    clearPolygonEditHover()
    return
  }

  const point = fromPointer(event)
  if (!point) {
    return
  }

  isPointerInside.value = true
  mousePoint.value = point
  updatePolygonEditHover(canvasPoint)

  if (drawingRectangle.value) {
    rectanglePreviewEnd.value = point
  }

  if (drawingSam2Box.value) {
    sam2BoxPreviewEnd.value = point
  }
}

function onPointerLeave() {
  isPointerInside.value = false
  mousePoint.value = null
  clearPolygonEditHover()
}

function onPointerDown(event: PointerEvent) {
  const targetName = eventTargetName(event)
  console.log('[stage] mousedown target name:', targetName)

  if (targetName.includes('sam2-point-delete')) {
    return
  }

  if (draggingHandle.value) {
    return
  }

  if (
    drawingToolActive.value &&
    event.button === 0 &&
    isShortcutPressed(event, props.userSettings.pan_modifier_shortcut)
  ) {
    startToolPan(event)
    return
  }

  if (event.button === 1) {
    startToolPan(event)
    return
  }

  if (isDraggingHandle.value) {
    return
  }

  if (props.tool === 'sam2') {
    startSam2Prompt(event)
    return
  }

  if (props.tool === 'polygon') {
    return
  }

  if (props.tool === 'cursor') {
    startCursorPan(event)
    return
  }

  if (!props.selectedLabelId) {
    return
  }

  if (props.tool !== 'rectangle' || !isInsideImage(event)) {
    return
  }

  event.preventDefault()
  console.log('[draw] start rectangle')
  const point = fromPointer(event)
  if (!point) {
    return
  }

  rectangleStart.value = point
  rectanglePreviewEnd.value = point
  drawingRectangle.value = true
}

function onPointerUp(event: PointerEvent) {
  if (isDraggingHandle.value) {
    return
  }

  if (drawingSam2Box.value) {
    finishSam2Prompt(event)
    return
  }

  if (isCursorPanning.value) {
    return
  }

  if (isPanning.value) {
    isPanning.value = false
    lastPanPoint.value = null
    suppressNextCanvasClick.value = true
    return
  }

  if (!props.selectedLabelId || props.tool !== 'rectangle' || !drawingRectangle.value || !rectangleStart.value) {
    return
  }

  const point = fromPointer(event)
  if (!point) {
    resetRectangleDraft()
    return
  }

  const width = Math.abs(point[0] - rectangleStart.value[0])
  const height = Math.abs(point[1] - rectangleStart.value[1])
  if (width < 1 || height < 1) {
    resetRectangleDraft()
    return
  }

  commitAnnotation({
    id: generateClientId('local'),
    image_id: props.image.id,
    label_id: props.selectedLabelId,
    shape_type: 'rectangle',
    points: [rectangleStart.value, point],
  })
}

function stopPointerInteractions() {
  isPanning.value = false
  lastPanPoint.value = null
  stopDragHandle()
  stopCursorPan()
}

function startToolPan(event: PointerEvent) {
  event.preventDefault()
  event.stopPropagation()
  hideCursorPoint()
  const canvasPoint = pointerToCanvas(event)
  if (!canvasPoint) {
    return
  }

  isPanning.value = true
  lastPanPoint.value = canvasPoint
}

function onCanvasClick(event: MouseEvent) {
  const targetName = eventTargetName(event)
  const isAnnotationTarget = targetName.includes('annotation-handle') || targetName.includes('annotation-shape')
  if (
    suppressNextCanvasClick.value ||
    (props.tool === 'cursor' && isAnnotationTarget) ||
    isDraggingHandle.value ||
    isCursorPanning.value
  ) {
    suppressNextCanvasClick.value = false
    event.preventDefault()
    event.stopPropagation()
    return
  }

  if (
    isPanning.value ||
    (drawingToolActive.value && isShortcutPressed(event, props.userSettings.pan_modifier_shortcut)) ||
    !isInsideImage(event)
  ) {
    return
  }

  if (props.tool === 'cursor') {
    event.preventDefault()
    emit('selectObject', null)
    return
  }

  if (props.tool === 'sam2') {
    event.preventDefault()
    return
  }

  if (!props.selectedLabelId || props.tool !== 'polygon') {
    return
  }

  if (event.detail > 1) {
    return
  }

  event.preventDefault()
  const point = fromPointer(event)
  if (!point) {
    return
  }

  console.log('[draw] add polygon point')
  addDraftPolygonPoint(point)
}

function addDraftPolygonPoint(point: number[]) {
  draftPoints.value = [...draftPoints.value, point]
}

function finishPolygon() {
  if (props.tool !== 'polygon' || !props.selectedLabelId || draftPoints.value.length < 3) {
    return
  }

  commitAnnotation({
    id: generateClientId('local'),
    image_id: props.image.id,
    label_id: props.selectedLabelId,
    shape_type: 'polygon',
    points: draftPoints.value,
  })
}

function commitAnnotation(annotation: AnnotationObject) {
  emit('beforeChange')
  draftPoints.value = []
  resetRectangleDraft()
  emit('change', [...currentAnnotations.value, annotation])
  emit('selectObject', annotation.id)
}

function startSam2Prompt(event: PointerEvent) {
  if (!isInsideImage(event)) {
    return
  }

  event.preventDefault()
  event.stopPropagation()
  clearDraftDrawing()
  clearSam2Preview()
  suppressNextCanvasClick.value = true

  const point = fromPointer(event)
  if (!point) {
    return
  }

  sam2PointerLabel.value = event.button === 2 || event.altKey ? 0 : 1
  sam2BoxStart.value = point
  sam2BoxPreviewEnd.value = point
  drawingSam2Box.value = true
}

function finishSam2Prompt(event: PointerEvent) {
  event.preventDefault()
  event.stopPropagation()

  const start = sam2BoxStart.value
  const end = fromPointer(event) ?? sam2BoxPreviewEnd.value ?? start
  if (!start || !end) {
    resetSam2BoxDraft()
    return
  }

  const moved = Math.abs(end[0] - start[0]) > 3 || Math.abs(end[1] - start[1]) > 3
  if (moved) {
    const minX = Math.min(start[0], end[0])
    const minY = Math.min(start[1], end[1])
    const maxX = Math.max(start[0], end[0])
    const maxY = Math.max(start[1], end[1])
    sam2Box.value = [minX, minY, maxX, maxY]
    console.log('SAM mode box', sam2Box.value)
  } else {
    sam2Points.value = [
      ...sam2Points.value,
      {
        id: generateClientId('sam_point'),
        point: start,
        label: sam2PointerLabel.value,
      },
    ]
    console.log('SAM mode click')
    console.log('Foreground points', samForegroundPoints())
    console.log('Background points', samBackgroundPoints())
  }

  resetSam2BoxDraft()
  hideCursorPoint()
  void runSamPrediction()
}

function getSam2Prompt(): Sam2Prompt {
  return {
    point_coords: sam2Points.value.map((promptPoint) => promptPoint.point),
    point_labels: sam2Points.value.map((promptPoint) => promptPoint.label),
    box: sam2Box.value,
  }
}

function hasSamPrompts(): boolean {
  return sam2Points.value.length > 0 || sam2Box.value !== null
}

function samForegroundPoints(): number[][] {
  return sam2Points.value.filter((promptPoint) => promptPoint.label === 1).map((promptPoint) => promptPoint.point)
}

function samBackgroundPoints(): number[][] {
  return sam2Points.value.filter((promptPoint) => promptPoint.label === 0).map((promptPoint) => promptPoint.point)
}

async function runSamPrediction(): Promise<boolean> {
  console.log('runSamPrediction')
  clearSamPredictionDebounce()
  const prompt = getSam2Prompt()
  if (prompt.point_coords.length === 0 && prompt.box === null) {
    console.warn('sam predict skipped: no prompt')
    clearSam2Preview()
    return false
  }

  const endpoint = apiUrl('/api/sam2/predict')
  const payload = {
    image_id: props.image.id,
    model_name: props.sam2Settings.model_name,
    point_coords: prompt.point_coords,
    point_labels: prompt.point_labels,
    box: prompt.box,
    multimask_output: props.sam2Settings.multimask_output,
    candidate: props.sam2Settings.candidate,
    polygon_epsilon: props.sam2Settings.polygon_epsilon,
    min_mask_area: props.sam2Settings.min_mask_area,
    mask_threshold: props.sam2Settings.mask_threshold,
    max_hole_area: props.sam2Settings.max_hole_area,
  }
  console.log('sam request', endpoint, payload)

  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    })

    if (!response.ok) {
      const body = await response.json().catch(() => null)
      sam2Error.value = body?.detail ?? `SAM2 request failed: ${response.status}`
      console.error('sam predict failed', sam2Error.value)
      return false
    }

    const result: Sam2PredictResponse = await response.json()
    console.log('sam predict', result)
    setSam2Preview(result)
    return true
  } catch (error) {
    sam2Error.value = error instanceof Error ? error.message : 'SAM2 prediction failed'
    console.error('sam predict failed', error)
    return false
  }
}

function setSam2Preview(result: Sam2PredictResponse) {
  sam2Prediction.value = result
  sam2Error.value = null
  sam2PreviewPoints.value = applySamResultEdgeSnapToPolygon(result.points)
  emit('sam2PreviewChange', true)
}

function clearSam2Preview() {
  if (sam2PreviewPoints.value || sam2Prediction.value) {
    emit('sam2PreviewChange', false)
  }
  sam2PreviewPoints.value = null
  sam2Prediction.value = null
  sam2Error.value = null
}

function rejectSam2Preview() {
  clearSam2State()
}

function acceptSam2Preview() {
  if (!sam2PreviewPoints.value || !props.selectedLabelId || sam2PreviewPoints.value.length < 3) {
    return false
  }

  commitAnnotation({
    id: generateClientId('local'),
    image_id: props.image.id,
    label_id: props.selectedLabelId,
    shape_type: 'polygon',
    points: sam2PreviewPoints.value,
  })
  clearSam2State()
  return true
}

function selectObject(id: string | number) {
  emit('selectObject', id)
}

function selectObjectFromShape(event: MouseEvent | PointerEvent, id: string | number) {
  if (props.tool !== 'cursor') {
    return
  }

  event.preventDefault()
  event.stopPropagation()
  suppressNextCanvasClick.value = true

  if (
    event.type === 'pointerdown' &&
    isShortcutPressed(event, props.userSettings.add_polygon_vertex_shortcut) &&
    id === props.selectedAnnotationId
  ) {
    if (insertPolygonVertexAtHoveredSegment(id, event)) {
      return
    }
  }

  clearDraftDrawing()
  selectObject(id)
}

function suppressControlPointClick(event: MouseEvent) {
  event.preventDefault()
  event.stopPropagation()
  suppressNextCanvasClick.value = true
}

function deleteSelected() {
  if (props.selectedAnnotationId === null) {
    return
  }

  const remaining = currentAnnotations.value.filter((annotation) => annotation.id !== props.selectedAnnotationId)
  emit('beforeChange')
  emit('change', remaining)
  emit('selectObject', null)
}

function startCursorPan(event: PointerEvent) {
  event.preventDefault()
  event.stopPropagation()
  clearDraftDrawing()
  hideCursorPoint()
  isCursorPanning.value = true
  hasMovedDuringPan.value = false
  panStartPoint.value = {
    x: event.clientX,
    y: event.clientY,
  }
  panStartOffset.value = {
    x: offsetX.value,
    y: offsetY.value,
  }
  window.addEventListener('pointermove', handleCursorPanMove)
  window.addEventListener('pointerup', stopCursorPan, { once: true })
  console.log('[pan] start cursor pan')
}

function handleCursorPanMove(event: PointerEvent) {
  if (!isCursorPanning.value || !panStartPoint.value || !panStartOffset.value) {
    return
  }

  event.preventDefault()
  const dx = event.clientX - panStartPoint.value.x
  const dy = event.clientY - panStartPoint.value.y

  if (Math.abs(dx) > 2 || Math.abs(dy) > 2) {
    hasMovedDuringPan.value = true
  }

  if (hasMovedDuringPan.value) {
    offsetX.value = panStartOffset.value.x + dx
    offsetY.value = panStartOffset.value.y + dy
    console.log('[pan] moving', dx, dy)
  }
}

function stopCursorPan(event?: PointerEvent) {
  if (!isCursorPanning.value) {
    return
  }

  event?.preventDefault()
  console.log('[pan] stop cursor pan')

  if (!hasMovedDuringPan.value) {
    emit('selectObject', null)
  }

  suppressNextCanvasClick.value = true
  resetCursorPan()
  window.removeEventListener('pointermove', handleCursorPanMove)
  window.removeEventListener('pointerup', stopCursorPan)
}

function resetCursorPan() {
  isCursorPanning.value = false
  panStartPoint.value = null
  panStartOffset.value = null
  hasMovedDuringPan.value = false
}

function startDragPolygonVertex(annotationId: number | string, pointIndex: number, event: PointerEvent) {
  event.preventDefault()
  event.stopPropagation()
  console.log('[handle] start polygon vertex drag', annotationId, pointIndex)
  suppressNextCanvasClick.value = true
  emit('beforeChange')
  draggingHandle.value = { type: 'polygon-vertex', annotationId, pointIndex }
  clearDraftDrawing()
  hideCursorPoint()
  window.addEventListener('pointermove', handleGlobalPointerMove)
  window.addEventListener('pointerup', stopDragHandle, { once: true })
  emit('selectObject', annotationId)
}

function startDragRectangleHandle(annotationId: number | string, handle: RectangleHandle, event: PointerEvent) {
  event.preventDefault()
  event.stopPropagation()
  console.log('[handle] start rectangle handle drag', annotationId, handle)
  suppressNextCanvasClick.value = true
  emit('beforeChange')
  draggingHandle.value = { type: 'rectangle-handle', annotationId, handle }
  clearDraftDrawing()
  hideCursorPoint()
  window.addEventListener('pointermove', handleGlobalPointerMove)
  window.addEventListener('pointerup', stopDragHandle, { once: true })
  emit('selectObject', annotationId)
}

function startControlPointDrag(event: PointerEvent, controlPoint: { key: string; kind: string }) {
  if (props.tool !== 'cursor') {
    event.preventDefault()
    event.stopPropagation()
    return
  }

  if (props.selectedAnnotationId === null) {
    return
  }

  if (
    controlPoint.kind === 'polygon' &&
    (isShortcutPressed(event, props.userSettings.delete_polygon_vertex_shortcut) || event.button === 2)
  ) {
    deletePolygonVertex(props.selectedAnnotationId, Number(controlPoint.key), event)
    return
  }

  if (controlPoint.kind === 'rect') {
    startDragRectangleHandle(props.selectedAnnotationId, controlPoint.key as RectangleHandle, event)
    return
  }

  startDragPolygonVertex(props.selectedAnnotationId, Number(controlPoint.key), event)
}

function handleControlPointContextMenu(event: MouseEvent, controlPoint: { key: string; kind: string }) {
  if (props.selectedAnnotationId === null || props.tool !== 'cursor' || controlPoint.kind !== 'polygon') {
    return
  }

  deletePolygonVertex(props.selectedAnnotationId, Number(controlPoint.key), event)
}

function handleGlobalPointerMove(event: PointerEvent) {
  if (!draggingHandle.value) {
    return
  }

  event.preventDefault()
  const canvasPoint = pointerToCanvas(event)
  if (!canvasPoint) {
    return
  }

  const imagePoint = applyEdgeSnap(canvasToImage(canvasPoint.x, canvasPoint.y))
  console.log('[handle] moving', draggingHandle.value)

  if (draggingHandle.value.type === 'polygon-vertex') {
    updatePolygonVertex(
      draggingHandle.value.annotationId,
      draggingHandle.value.pointIndex,
      imagePoint,
    )
    return
  }

  if (draggingHandle.value.type === 'rectangle-handle') {
    updateRectangleHandle(
      draggingHandle.value.annotationId,
      draggingHandle.value.handle,
      imagePoint,
    )
  }
}

function stopDragHandle(event?: PointerEvent) {
  event?.preventDefault()
  if (draggingHandle.value) {
    console.log('[handle] stop drag')
  }
  draggingHandle.value = null
  hideCursorPoint()
  window.removeEventListener('pointermove', handleGlobalPointerMove)
  window.removeEventListener('pointerup', stopDragHandle)
}

function updatePolygonVertex(
  annotationId: number | string,
  pointIndex: number,
  imagePoint: { x: number; y: number },
) {
  updateAnnotationPoints(annotationId, (annotation) => {
    if (annotation.shape_type !== 'polygon') {
      return annotation.points
    }

    return annotation.points.map((point, index) => (
      index === pointIndex ? [imagePoint.x, imagePoint.y] : point
    ))
  })
}

function insertPolygonVertexAtHoveredSegment(annotationId: number | string, event: MouseEvent | PointerEvent): boolean {
  const annotation = selectedAnnotation.value
  if (!annotation || annotation.id !== annotationId || annotation.shape_type !== 'polygon') {
    return false
  }

  const canvasPoint = pointerToCanvas(event)
  const imagePoint = fromPointer(event)
  if (!canvasPoint || !imagePoint) {
    return false
  }

  const segmentIndex = hoveredPolygonSegmentIndex.value
  if (segmentIndex === null) {
    return false
  }

  emit('beforeChange')
  updateAnnotationPoints(annotation.id, (currentAnnotation) => {
    if (currentAnnotation.shape_type !== 'polygon') {
      return currentAnnotation.points
    }

    const nextPoints = [...currentAnnotation.points]
    nextPoints.splice(segmentIndex + 1, 0, imagePoint)
    return nextPoints
  })
  void nextTick(() => updatePolygonEditHover(canvasPoint))
  return true
}

function deletePolygonVertex(annotationId: number | string, pointIndex: number, event: MouseEvent | PointerEvent) {
  event.preventDefault()
  event.stopPropagation()
  suppressNextCanvasClick.value = true

  const annotation = selectedAnnotation.value
  if (!annotation || annotation.id !== annotationId || annotation.shape_type !== 'polygon') {
    return
  }

  if (annotation.points.length <= 3) {
    ElMessage.warning('Polygon must have at least 3 points.')
    return
  }

  emit('beforeChange')
  updateAnnotationPoints(annotation.id, (currentAnnotation) => (
    currentAnnotation.shape_type === 'polygon'
      ? currentAnnotation.points.filter((_point, index) => index !== pointIndex)
      : currentAnnotation.points
  ))
}

function findNearestSegment(
  canvasPoint: { x: number; y: number },
  polygonPointsImage: number[][],
): number | null {
  if (polygonPointsImage.length < 3) {
    return null
  }

  let nearestIndex: number | null = null
  let nearestDistance = Number.POSITIVE_INFINITY
  const canvasPoints = polygonPointsImage.map(imageToCanvasPoint)

  for (let index = 0; index < canvasPoints.length; index += 1) {
    const start = canvasPoints[index]
    const end = canvasPoints[(index + 1) % canvasPoints.length]
    const distance = distanceToSegment(canvasPoint, start, end)
    if (distance < nearestDistance) {
      nearestDistance = distance
      nearestIndex = index
    }
  }

  return nearestDistance <= 8 ? nearestIndex : null
}

function updatePolygonEditHover(canvasPoint: { x: number; y: number } | null) {
  const annotation = selectedAnnotation.value
  if (!canvasPoint || props.tool !== 'cursor' || !annotation || annotation.shape_type !== 'polygon') {
    clearPolygonEditHover()
    return
  }

  let nearestVertexIndex: number | null = null
  let nearestVertexDistance = Number.POSITIVE_INFINITY
  const canvasPoints = annotation.points.map(imageToCanvasPoint)
  for (let index = 0; index < canvasPoints.length; index += 1) {
    const point = canvasPoints[index]
    const distance = Math.hypot(canvasPoint.x - point[0], canvasPoint.y - point[1])
    if (distance < nearestVertexDistance) {
      nearestVertexDistance = distance
      nearestVertexIndex = index
    }
  }

  if (nearestVertexDistance <= 8) {
    hoveredPolygonVertexIndex.value = nearestVertexIndex
    hoveredPolygonSegmentIndex.value = null
    return
  }

  hoveredPolygonVertexIndex.value = null
  hoveredPolygonSegmentIndex.value = findNearestSegment(canvasPoint, annotation.points)
}

function clearPolygonEditHover() {
  hoveredPolygonVertexIndex.value = null
  hoveredPolygonSegmentIndex.value = null
}

function distanceToSegment(
  point: { x: number; y: number },
  start: number[],
  end: number[],
): number {
  const dx = end[0] - start[0]
  const dy = end[1] - start[1]
  const lengthSquared = dx * dx + dy * dy
  if (lengthSquared === 0) {
    return Math.hypot(point.x - start[0], point.y - start[1])
  }

  const t = clamp(((point.x - start[0]) * dx + (point.y - start[1]) * dy) / lengthSquared, 0, 1)
  const projectionX = start[0] + t * dx
  const projectionY = start[1] + t * dy
  return Math.hypot(point.x - projectionX, point.y - projectionY)
}

function updateRectangleHandle(
  annotationId: number | string,
  handle: RectangleHandle,
  imagePoint: { x: number; y: number },
) {
  updateAnnotationPoints(annotationId, (annotation) => {
    if (annotation.shape_type !== 'rectangle') {
      return annotation.points
    }

    const rect = normalizedRectangle(annotation.points)
    let x1 = rect.minX
    let y1 = rect.minY
    let x2 = rect.maxX
    let y2 = rect.maxY

    if (handle === 'tl') {
      x1 = imagePoint.x
      y1 = imagePoint.y
    }
    if (handle === 'tr') {
      x2 = imagePoint.x
      y1 = imagePoint.y
    }
    if (handle === 'br') {
      x2 = imagePoint.x
      y2 = imagePoint.y
    }
    if (handle === 'bl') {
      x1 = imagePoint.x
      y2 = imagePoint.y
    }

    const minX = Math.min(x1, x2)
    const maxX = Math.max(x1, x2)
    const minY = Math.min(y1, y2)
    const maxY = Math.max(y1, y2)
    return [[minX, minY], [maxX, maxY]]
  })
}

function updateAnnotationPoints(id: number | string, pointFactory: (annotation: AnnotationObject) => number[][]) {
  emit('change', currentAnnotations.value.map((annotation) => (
    annotation.id === id ? { ...annotation, points: pointFactory(annotation) } : annotation
  )))
}

function clampAnnotationPoint(point: { x: number; y: number }) {
  const imageWidth = props.image.width || 1
  const imageHeight = props.image.height || 1
  return {
    x: clamp(point.x, 0, imageWidth),
    y: clamp(point.y, 0, imageHeight),
  }
}

function clampRasterPoint(point: { x: number; y: number }) {
  const maxX = Math.max((props.image.width || 1) - 1, 0)
  const maxY = Math.max((props.image.height || 1) - 1, 0)
  return {
    x: clamp(point.x, 0, maxX),
    y: clamp(point.y, 0, maxY),
  }
}

function applyEdgeSnap(point: { x: number; y: number }) {
  const threshold = props.userSettings.edge_snap_threshold ?? 5
  return applyPointEdgeSnap(point, threshold)
}

function applySamResultEdgeSnapToPolygon(points: number[][]) {
  if (!props.userSettings.sam_result_edge_snap_enabled) {
    return points
  }

  const threshold = props.userSettings.sam_result_edge_snap_threshold ?? 5
  if (threshold <= 0) {
    return points
  }

  return points.map((point) => {
    const snappedPoint = applyPointEdgeSnap({ x: point[0], y: point[1] }, threshold)
    return [snappedPoint.x, snappedPoint.y]
  })
}

function applyPointEdgeSnap(point: { x: number; y: number }, threshold: number) {
  const imageWidth = props.image.width || 1
  const imageHeight = props.image.height || 1
  let x = point.x
  let y = point.y

  if (threshold > 0) {
    if (x <= threshold) {
      x = 0
    }
    if (imageWidth - x <= threshold) {
      x = imageWidth
    }
    if (y <= threshold) {
      y = 0
    }
    if (imageHeight - y <= threshold) {
      y = imageHeight
    }
  }

  return clampAnnotationPoint({ x, y })
}

function isShortcutPressed(event: MouseEvent | KeyboardEvent, shortcut: Shortcut): boolean {
  if (shortcut === 'shift') {
    return event.shiftKey
  }
  if (shortcut === 'alt') {
    return event.altKey
  }
  if (shortcut === 'ctrl') {
    return event.ctrlKey
  }
  if (shortcut === 'space') {
    return pressedKeys.value.has('space') || ('code' in event && event.code === 'Space')
  }
  return pressedKeys.value.has(shortcut)
}

function normalizeShortcutFromKeyboardEvent(event: KeyboardEvent): string | null {
  if (event.key === 'Shift') {
    return 'shift'
  }
  if (event.key === 'Alt') {
    return 'alt'
  }
  if (event.key === 'Control') {
    return 'ctrl'
  }
  if (event.code === 'Space') {
    return 'space'
  }
  if (/^Key[A-Z]$/.test(event.code)) {
    return event.code.replace('Key', '').toLowerCase()
  }
  if (/^Digit[0-9]$/.test(event.code)) {
    return event.code.replace('Digit', '')
  }
  return null
}

function shortcutLabel(shortcut: Shortcut): string {
  if (shortcut === 'ctrl') {
    return 'Ctrl'
  }
  if (shortcut === 'alt') {
    return 'Alt'
  }
  if (shortcut === 'shift') {
    return 'Shift'
  }
  if (shortcut === 'space') {
    return 'Space'
  }
  if (/^[a-z]$/.test(shortcut)) {
    return shortcut.toUpperCase()
  }
  return shortcut
}

function eventTargetName(event: MouseEvent): string {
  const target = event.target
  if (!(target instanceof Element)) {
    return ''
  }

  return target.getAttribute('data-name') || target.getAttribute('class') || ''
}

function resetRectangleDraft() {
  rectangleStart.value = null
  rectanglePreviewEnd.value = null
  drawingRectangle.value = false
}

function hideCursorPoint() {
  mousePoint.value = null
  isPointerInside.value = false
}

function clearDraftDrawing() {
  draftPoints.value = []
  resetRectangleDraft()
}

function scheduleSamPrediction() {
  clearSamPredictionDebounce()
  if (!hasSamPrompts()) {
    clearSam2Preview()
    return
  }

  samPredictionDebounceTimer = window.setTimeout(() => {
    samPredictionDebounceTimer = null
    void runSamPrediction()
  }, 300)
}

function clearSamPredictionDebounce() {
  if (samPredictionDebounceTimer !== null) {
    window.clearTimeout(samPredictionDebounceTimer)
    samPredictionDebounceTimer = null
  }
}

function resetSam2BoxDraft() {
  sam2BoxStart.value = null
  sam2BoxPreviewEnd.value = null
  drawingSam2Box.value = false
}

function clearSam2State() {
  clearSamPredictionDebounce()
  clearSamPointDeleteTimer()
  hoveredSamPointId.value = null
  sam2Points.value = []
  sam2Box.value = null
  resetSam2BoxDraft()
  hideCursorPoint()
  clearSam2Preview()
}

function deleteSamPoint(pointId: string, event: MouseEvent | PointerEvent) {
  event.preventDefault()
  event.stopPropagation()
  suppressNextCanvasClick.value = true
  sam2Points.value = sam2Points.value.filter((point) => point.id !== pointId)
  if (hoveredSamPointId.value === pointId) {
    hoveredSamPointId.value = null
  }
  hideCursorPoint()

  if (hasSamPrompts()) {
    scheduleSamPrediction()
  } else {
    clearSam2Preview()
  }
}

function onSamPointMouseEnter(pointId: string) {
  clearSamPointDeleteTimer()
  hoveredSamPointId.value = pointId
}

function onSamPointMouseLeave() {
  clearSamPointDeleteTimer()
  samPointDeleteHideTimer = window.setTimeout(() => {
    hoveredSamPointId.value = null
    samPointDeleteHideTimer = null
  }, 500)
}

function clearSamPointDeleteTimer() {
  if (samPointDeleteHideTimer !== null) {
    window.clearTimeout(samPointDeleteHideTimer)
    samPointDeleteHideTimer = null
  }
}

function cancelDraft() {
  clearDraftDrawing()
}

function removeLastPolygonPoint() {
  if (props.tool !== 'polygon' || draftPoints.value.length === 0) {
    return false
  }

  draftPoints.value = draftPoints.value.slice(0, -1)
  return true
}

function onKeydown(event: KeyboardEvent) {
  if (isTextEntryTarget(event.target)) {
    return
  }

  const shortcut = normalizeShortcutFromKeyboardEvent(event)
  if (shortcut) {
    const wasShortcutPressed = pressedKeys.value.has(shortcut)
    const nextPressedKeys = new Set(pressedKeys.value)
    nextPressedKeys.add(shortcut)
    pressedKeys.value = nextPressedKeys

    if (shortcut === props.userSettings.pan_modifier_shortcut) {
      event.preventDefault()
      return
    }

    if (
      shortcut === props.userSettings.polygon_confirm_point_shortcut &&
      props.tool === 'polygon' &&
      mousePoint.value &&
      !wasShortcutPressed &&
      !event.repeat &&
      !isPanning.value &&
      !isCursorPanning.value
    ) {
      event.preventDefault()
      addDraftPolygonPoint(mousePoint.value)
      return
    }
  }

  if (event.key === 'Enter' && props.tool === 'polygon' && draftPoints.value.length > 0) {
    event.preventDefault()
    finishPolygon()
    return
  }

  if (event.key === 'Escape' && (draftPoints.value.length > 0 || drawingRectangle.value)) {
    event.preventDefault()
    cancelDraft()
    return
  }

  if (event.key === 'Backspace' && props.tool === 'polygon' && draftPoints.value.length > 0) {
    event.preventDefault()
    removeLastPolygonPoint()
  }
}

function onKeyup(event: KeyboardEvent) {
  const shortcut = normalizeShortcutFromKeyboardEvent(event)
  if (shortcut) {
    const nextPressedKeys = new Set(pressedKeys.value)
    nextPressedKeys.delete(shortcut)
    pressedKeys.value = nextPressedKeys

    const releasedPanModifier = shortcut === props.userSettings.pan_modifier_shortcut
    if (releasedPanModifier) {
      event.preventDefault()
    }
    if (releasedPanModifier && isPanning.value) {
      isPanning.value = false
      lastPanPoint.value = null
      suppressNextCanvasClick.value = true
    }
  }
}

function clearPressedKeys() {
  pressedKeys.value = new Set()
}

function isTextEntryTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) {
    return false
  }

  const tagName = target.tagName.toLowerCase()
  return tagName === 'input' || tagName === 'textarea' || tagName === 'select' || target.isContentEditable
}

function isDrawingPolygon() {
  return props.tool === 'polygon' && draftPoints.value.length > 0
}

function onWheel(event: WheelEvent) {
  event.preventDefault()
  const canvasPoint = pointerToCanvas(event)
  if (!canvasPoint) {
    return
  }

  const oldScale = viewScale.value
  const mousePointTo = {
    x: (canvasPoint.x - offsetX.value) / oldScale,
    y: (canvasPoint.y - offsetY.value) / oldScale,
  }
  const nextScale = event.deltaY > 0 ? oldScale / scaleBy : oldScale * scaleBy
  setScaleAroundPoint(nextScale, canvasPoint, mousePointTo)
}

function setScaleAroundPoint(nextScale: number, canvasPoint: { x: number; y: number }, imagePoint: { x: number; y: number }) {
  viewScale.value = clamp(nextScale, minScale, maxScale)
  offsetX.value = canvasPoint.x - imagePoint.x * viewScale.value
  offsetY.value = canvasPoint.y - imagePoint.y * viewScale.value
}

function zoomIn() {
  zoomFromCenter(viewScale.value * scaleBy)
}

function zoomOut() {
  zoomFromCenter(viewScale.value / scaleBy)
}

function zoomFromCenter(nextScale: number) {
  updateContainerSize()
  const canvasPoint = {
    x: containerSize.value.width / 2,
    y: containerSize.value.height / 2,
  }
  const imagePoint = canvasToImage(canvasPoint.x, canvasPoint.y)
  setScaleAroundPoint(nextScale, canvasPoint, imagePoint)
}

function fitToScreen() {
  updateContainerSize()
  const imageWidth = props.image.width || 1
  const imageHeight = props.image.height || 1
  const fitScale = Math.min(
    containerSize.value.width / imageWidth,
    containerSize.value.height / imageHeight,
  ) * 0.9

  viewScale.value = clamp(fitScale, minScale, maxScale)
  offsetX.value = (containerSize.value.width - imageWidth * viewScale.value) / 2
  offsetY.value = (containerSize.value.height - imageHeight * viewScale.value) / 2
}

function resetView() {
  updateContainerSize()
  viewScale.value = 1
  offsetX.value = (containerSize.value.width - (props.image.width || 1)) / 2
  offsetY.value = (containerSize.value.height - (props.image.height || 1)) / 2
}

function rectFromImageBox(box: number[]) {
  const start = imageToCanvasPoint([box[0], box[1]])
  const end = imageToCanvasPoint([box[2], box[3]])
  return rectFromCanvasPoints(start, end)
}

function rectFromCanvasPoints(start: number[], end: number[]) {
  return {
    x: Math.min(start[0], end[0]),
    y: Math.min(start[1], end[1]),
    width: Math.abs(end[0] - start[0]),
    height: Math.abs(end[1] - start[1]),
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

defineExpose({
  acceptSam2Preview,
  deleteSelected,
  fitToScreen,
  getSam2Prompt,
  isDrawingPolygon,
  removeLastPolygonPoint,
  rejectSam2Preview,
  resetView,
  runSamPrediction,
  setSam2Preview,
  zoomIn,
  zoomOut,
  zoomPercent,
})
</script>

<template>
  <div class="annotation-canvas-wrap">
    <div
      ref="canvasElement"
      class="annotation-canvas"
      :class="{ 'annotation-canvas-active': drawingToolActive }"
      :style="{ cursor: cursorStyle }"
      @click="onCanvasClick"
      @contextmenu.prevent
      @dblclick.stop="finishPolygon"
      @mouseleave="onPointerLeave"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @wheel="onWheel"
    >
      <div
        v-if="showPolygonHint"
        class="polygon-mode-hint"
        :class="{ started: polygonHintStarted, ready: polygonHintReady }"
      >
        {{ polygonHintText }}
      </div>
      <div v-if="showPolygonEditHint" class="polygon-mode-hint polygon-edit-hint">
        {{ polygonEditHintText }}
      </div>

      <img
        v-if="loadedImageUrl"
        ref="imageElement"
        class="annotation-image"
        :src="loadedImageUrl"
        :alt="image.filename"
        :style="imageStyle"
        crossorigin="anonymous"
        @load="applyViewForLoadedImage"
      />

      <svg class="annotation-overlay">
        <g
          v-for="displayAnnotation in displayedAnnotations"
          :key="displayAnnotation.annotation.id"
          class="annotation-shape"
          data-name="annotation-shape"
          :data-annotation-id="displayAnnotation.annotation.id"
          :style="{ pointerEvents: annotationGroupPointerEvents }"
          :class="{ selected: displayAnnotation.annotation.id === selectedAnnotationId }"
          @click="selectObjectFromShape($event, displayAnnotation.annotation.id)"
          @mousedown="selectObjectFromShape($event, displayAnnotation.annotation.id)"
          @pointerdown="selectObjectFromShape($event, displayAnnotation.annotation.id)"
        >
          <rect
            v-if="displayAnnotation.rectangle"
            data-name="annotation-shape"
            :data-annotation-id="displayAnnotation.annotation.id"
            :x="displayAnnotation.rectangle.x"
            :y="displayAnnotation.rectangle.y"
            :width="displayAnnotation.rectangle.width"
            :height="displayAnnotation.rectangle.height"
            :stroke="displayAnnotation.stroke"
            :fill="displayAnnotation.fill"
            :style="{ pointerEvents: annotationShapePointerEvents }"
          />
          <polygon
            v-else
            data-name="annotation-shape"
            :data-annotation-id="displayAnnotation.annotation.id"
            :points="displayAnnotation.pointsValue"
            :stroke="displayAnnotation.stroke"
            :fill="displayAnnotation.fill"
            :style="{ pointerEvents: annotationShapePointerEvents }"
          />
        </g>

        <polygon
          v-if="displayedSam2PreviewValue"
          class="sam2-mask-preview"
          :points="displayedSam2PreviewValue"
          pointer-events="none"
        />

        <line
          v-if="hoveredPolygonSegment"
          class="polygon-hover-segment"
          :x1="hoveredPolygonSegment.start[0]"
          :y1="hoveredPolygonSegment.start[1]"
          :x2="hoveredPolygonSegment.end[0]"
          :y2="hoveredPolygonSegment.end[1]"
          pointer-events="none"
        />

        <template v-if="props.tool === 'cursor'">
          <circle
            v-for="controlPoint in selectedControlPoints"
            :key="`${selectedAnnotationId}-${controlPoint.kind === 'rect' ? 'rect-handle' : 'polygon-handle'}-${controlPoint.key}`"
            class="annotation-control-point annotation-handle"
            :class="{ 'polygon-vertex-hovered': controlPoint.kind === 'polygon' && hoveredPolygonVertexIndex === Number(controlPoint.key) }"
            :data-name="`annotation-handle ${controlPoint.kind === 'rect' ? 'rectangle-handle' : 'polygon-handle'}`"
            :data-annotation-id="selectedAnnotationId"
            :data-handle="controlPoint.kind === 'rect' ? controlPoint.key : undefined"
            :data-point-index="controlPoint.kind === 'polygon' ? controlPoint.key : undefined"
            :cx="controlPoint.point[0]"
            :cy="controlPoint.point[1]"
            :r="controlPoint.kind === 'polygon' && hoveredPolygonVertexIndex === Number(controlPoint.key) ? 7 : 6"
            pointer-events="all"
            @click.stop.prevent="suppressControlPointClick"
            @contextmenu.stop.prevent="handleControlPointContextMenu($event, controlPoint)"
            @pointerdown.stop.prevent="startControlPointDrag($event, controlPoint)"
          />
        </template>

        <rect
          v-if="displayedSam2Box"
          class="sam2-box-prompt"
          :x="displayedSam2Box.x"
          :y="displayedSam2Box.y"
          :width="displayedSam2Box.width"
          :height="displayedSam2Box.height"
          pointer-events="none"
        />
        <rect
          v-if="displayedSam2BoxPreview"
          class="sam2-box-draft"
          :x="displayedSam2BoxPreview.x"
          :y="displayedSam2BoxPreview.y"
          :width="displayedSam2BoxPreview.width"
          :height="displayedSam2BoxPreview.height"
          pointer-events="none"
        />
        <template v-if="shouldShowSam2PromptPoints">
          <g
            v-for="promptPoint in displayedSam2Points"
            :key="`sam2-point-${promptPoint.key}`"
            class="sam2-prompt-group"
            @click.stop.prevent
            @mouseenter="onSamPointMouseEnter(promptPoint.id)"
            @mouseleave="onSamPointMouseLeave"
            @pointerdown.stop.prevent
          >
            <circle
              class="sam2-prompt-hover-area"
              :cx="promptPoint.point[0] + 5"
              :cy="promptPoint.point[1] - 5"
              r="16"
            />
            <circle
              class="sam2-prompt-point"
              :class="promptPoint.label === 1 ? 'positive' : 'negative'"
              :cx="promptPoint.point[0]"
              :cy="promptPoint.point[1]"
              r="5"
              pointer-events="none"
            />
            <g
              v-if="hoveredSamPointId === promptPoint.id"
              class="sam2-point-delete"
              data-name="sam2-point-delete"
              @click.stop.prevent="deleteSamPoint(promptPoint.id, $event)"
              @pointerdown.stop.prevent="deleteSamPoint(promptPoint.id, $event)"
            >
              <circle
                class="sam2-point-delete-hit"
                :cx="promptPoint.point[0] + 10"
                :cy="promptPoint.point[1] - 10"
                r="7"
              />
              <circle
                class="sam2-point-delete-bg"
                :cx="promptPoint.point[0] + 10"
                :cy="promptPoint.point[1] - 10"
                r="3.5"
              />
              <text
                :x="promptPoint.point[0] + 10"
                :y="promptPoint.point[1] - 8.2"
                text-anchor="middle"
                pointer-events="none"
              >x</text>
            </g>
          </g>
        </template>

        <rect
          v-if="shouldShowDraftDrawing && rectanglePreview"
          class="draft-rect"
          :x="rectanglePreview.x"
          :y="rectanglePreview.y"
          :width="rectanglePreview.width"
          :height="rectanglePreview.height"
          :stroke="activeColor"
          :fill="activeFill()"
          pointer-events="none"
        />
        <circle
          v-if="shouldShowDraftDrawing && displayedRectangleStart"
          class="draft-vertex"
          :cx="displayedRectangleStart[0]"
          :cy="displayedRectangleStart[1]"
          r="4"
          pointer-events="none"
        />

        <polyline
          v-if="shouldShowDraftDrawing && displayedDraftPoints.length"
          class="draft-shape"
          :points="displayedDraftPoints.map((point) => point.join(',')).join(' ')"
          :stroke="activeColor"
          pointer-events="none"
        />
        <line
          v-if="shouldShowDraftDrawing && displayedDraftPoints.length && displayedMousePoint"
          class="draft-line"
          :x1="displayedDraftPoints[displayedDraftPoints.length - 1][0]"
          :y1="displayedDraftPoints[displayedDraftPoints.length - 1][1]"
          :x2="displayedMousePoint[0]"
          :y2="displayedMousePoint[1]"
          :stroke="activeColor"
          pointer-events="none"
        />
        <circle
          v-for="(point, pointIndex) in shouldShowDraftDrawing ? displayedDraftPoints : []"
          :key="`draft-point-${pointIndex}`"
          class="draft-vertex"
          :cx="point[0]"
          :cy="point[1]"
          r="4"
          pointer-events="none"
        />
        <circle
          v-if="shouldShowCursorPoint && displayedMousePoint"
          class="cursor-point"
          :cx="displayedMousePoint[0]"
          :cy="displayedMousePoint[1]"
          r="4"
          pointer-events="none"
        />
      </svg>
    </div>
  </div>
</template>
