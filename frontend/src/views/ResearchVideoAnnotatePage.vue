<script setup lang="ts">
import { Back, Delete, Finished, Pointer, RefreshRight, VideoPause, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, onMounted, ref, watch } from 'vue'

import AnnotationCanvas from '../components/AnnotationCanvas.vue'
import ObjectPanel from '../components/ObjectPanel.vue'
import type { AnnotationObject, Label, ShapeType } from '../stores/annotation'
import { useResearchVideosStore, type ResearchVideoAnnotation } from '../stores/researchVideos'
import { useUsersStore } from '../stores/users'
import { useUserSettingsStore, type Sam2Candidate, type Sam2ModelName } from '../stores/userSettings'
import { clonePoints, normalizeAnnotationObject } from '../utils/polygon'

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

const props = defineProps<{ videoId: string }>()

const researchVideosStore = useResearchVideosStore()
const usersStore = useUsersStore()
const userSettingsStore = useUserSettingsStore()
const { currentVideo, error, loading, saving } = storeToRefs(researchVideosStore)
const { currentUsername } = storeToRefs(usersStore)
const { settings: userSettings } = storeToRefs(userSettingsStore)

const canvasRef = ref<InstanceType<typeof AnnotationCanvas> | null>(null)
const videoRef = ref<HTMLVideoElement | null>(null)
const selectedFrameIndex = ref(0)
const selectedLabelId = ref<number | null>(null)
const selectedAnnotationId = ref<number | string | null>(null)
const hiddenAnnotationIds = ref<Array<number | string>>([])
const hasUnsavedChanges = ref(false)
const tool = ref<ToolType>('sam2')
const toolOptions: ToolType[] = ['cursor', 'rectangle', 'polygon']
const annotationsByFrame = ref<Record<number, ResearchVideoAnnotation[]>>({})
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

const video = computed(() => currentVideo.value)
const frames = computed(() => video.value?.frames ?? [])
const currentFrame = computed(() => frames.value[selectedFrameIndex.value] ?? null)
const currentFrameNumber = computed(() => currentFrame.value ? selectedFrameIndex.value + 1 : 0)
const totalFrames = computed(() => frames.value.length)
const isFirstFrame = computed(() => selectedFrameIndex.value <= 0)
const isLastFrame = computed(() => selectedFrameIndex.value >= totalFrames.value - 1)
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

onMounted(async () => {
  if (currentUsername.value) {
    await userSettingsStore.loadSettings(currentUsername.value)
  } else {
    userSettingsStore.resetToDefaults()
  }
  await loadVideo()
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
  },
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
  await researchVideosStore.fetchVideo(Number(props.videoId))
  selectedFrameIndex.value = 0
  selectedLabelId.value = currentVideo.value?.labels[0]?.id ?? null
  annotationsByFrame.value = {}
  if (currentVideo.value?.frames.length) {
    await loadFrameAnnotations(currentVideo.value.frames[0].frame_index)
  }
}

async function loadFrameAnnotations(frameIndex: number) {
  if (!currentVideo.value) {
    return
  }
  currentFrameLoading.value = true
  try {
    const annotations = await researchVideosStore.fetchVideoFrameAnnotations(Number(props.videoId), frameIndex)
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
    currentFrameLoading.value = false
  }
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
    ElMessage.error(researchVideosStore.error || 'Save failed')
    return false
  }
  await loadFrameAnnotations(currentFrame.value.frame_index)
  hasUnsavedChanges.value = false
  ElMessage.success('Current frame saved')
  return true
}

async function goToFrame(index: number) {
  if (index < 0 || index >= totalFrames.value || index === selectedFrameIndex.value) {
    return
  }
  if (hasUnsavedChanges.value) {
    const saved = await saveAnnotations()
    if (!saved) {
      return
    }
  }
  selectedFrameIndex.value = index
  const frame = frames.value[index]
  if (!annotationsByFrame.value[frame.frame_index]) {
    await loadFrameAnnotations(frame.frame_index)
  }
  if (videoRef.value && video.value?.fps) {
    videoRef.value.currentTime = frame.frame_index / video.value.fps
  }
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
  ElMessage.info('Create layer above is not yet wired for Research videos.')
}

async function generateSam2Mask() {
  if (!currentCanvasImage.value) {
    return
  }
  if (!selectedLabelId.value) {
    ElMessage.warning('Please select a label first.')
    return
  }
  const prompt = canvasRef.value?.getSam2Prompt()
  if (!prompt || (prompt.point_coords.length === 0 && prompt.box === null)) {
    ElMessage.warning('Add prompt points or a box first.')
    return
  }
  generatingSam2.value = true
  try {
    const generated = await canvasRef.value?.runSamPrediction()
    if (!generated) {
      throw new Error('SAM2 prediction failed')
    }
    ElMessage.success('SAM2 preview generated')
  } catch (samError) {
    ElMessage.error(samError instanceof Error ? samError.message : 'SAM2 prediction failed')
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
    ElMessage.warning('No SAM2 preview to accept.')
    return
  }
  if (preview.source === 'refine_annotation' && preview.targetAnnotationId !== null) {
    if (applyRefinedSam2Polygon(preview.targetAnnotationId, preview.points)) {
      ElMessage.success('Polygon refined with SAM2')
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
  ElMessage.success('SAM2 result accepted')
}

function rejectSam2Mask() {
  canvasRef.value?.rejectSam2Preview()
}

async function handleRefineSelectedPolygonWithSam2(annotationId: number | string) {
  const annotation = currentFrameAnnotations.value.find((item) => item.id === annotationId)
  if (!annotation || annotation.shape_type !== 'polygon') {
    ElMessage.warning('Select a polygon annotation first.')
    return
  }
  generatingSam2.value = true
  try {
    const refined = await canvasRef.value?.refineSelectedPolygonWithSam2?.(annotation)
    if (!refined) {
      throw new Error('SAM2 refine failed')
    }
    ElMessage.success('SAM2 refine preview generated')
  } catch (samError) {
    ElMessage.error(samError instanceof Error ? samError.message : 'SAM2 refine failed')
  } finally {
    generatingSam2.value = false
  }
}

function onVideoPlay() {
  isPlaying.value = true
}

function onVideoPause() {
  isPlaying.value = false
  syncFrameFromVideo()
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

async function openLabelManager() {
  labelsLoading.value = true
  const labels = await researchVideosStore.fetchVideoLabels(Number(props.videoId))
  labelsLoading.value = false
  if (!labels) {
    ElMessage.error(researchVideosStore.error || 'Failed to load labels')
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
    ElMessage.warning('Label name is required')
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
      throw new Error(researchVideosStore.error || 'Failed to create label')
    }
    await researchVideosStore.fetchVideo(Number(props.videoId))
    const labels = await researchVideosStore.fetchVideoLabels(Number(props.videoId))
    labelDrafts.value = labels?.map((label) => ({ ...label })) ?? []
    selectedLabelId.value = created.id
    newLabelName.value = ''
    ElMessage.success('Label created')
  } catch (labelError) {
    ElMessage.error(labelError instanceof Error ? labelError.message : 'Failed to create label')
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
          <p class="eyebrow">Video annotation</p>
          <h1>{{ video?.name ?? `Video ${videoId}` }}</h1>
          <p class="job-subtitle">Experimental workspace</p>
        </div>

        <section class="tool-panel">
          <p class="panel-label">Tool</p>
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
              <p class="panel-label">Label</p>
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
          <p class="panel-label">Video frames</p>
          <div class="frame-list">
            <button
              v-for="(frame, index) in frames"
              :key="frame.id"
              class="frame-choice"
              :class="{ active: selectedFrameIndex === index }"
              type="button"
              @click="goToFrame(index)"
            >
              <span>{{ index + 1 }}. {{ frame.filename }}</span>
              <span class="frame-choice-badge review">{{ formatTimestamp(frame.timestamp_ms) }}</span>
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
      <header class="annotate-stage-bar research-video-stage-bar">
        <div class="annotate-stage-title">
          <strong>{{ currentFrame?.filename ?? 'No frame loaded' }}</strong>
          <span v-if="currentFrame">
            {{ currentFrame.width }} x {{ currentFrame.height }} · Frame {{ currentFrameNumber }} / {{ totalFrames }}
          </span>
        </div>
        <div class="annotation-toolbar">
          <div class="toolbar-group toolbar-group-frames">
            <el-button :disabled="isFirstFrame || saving" @click="goPrevious">Previous frame</el-button>
            <el-button :disabled="!video?.file_url" @click="togglePlayback">
              <el-icon><VideoPause v-if="isPlaying" /><VideoPlay v-else /></el-icon>
              {{ isPlaying ? 'Pause' : 'Play' }}
            </el-button>
            <el-button :disabled="isLastFrame || saving" @click="goNext">Next frame</el-button>
            <span class="frame-counter">{{ currentFrameNumber }} / {{ totalFrames }}</span>
            <span class="frame-counter" v-if="currentFrame">{{ formatTimestamp(currentFrame.timestamp_ms) }}</span>
          </div>

          <div class="toolbar-group" v-if="tool === 'sam2'">
            <el-button :loading="generatingSam2" type="primary" @click="generateSam2Mask">
              Generate Mask
            </el-button>
            <el-button @click="acceptSam2Mask">Accept Mask</el-button>
            <el-button @click="rejectSam2Mask">Reject Mask</el-button>
          </div>

          <div class="toolbar-group">
            <el-button :loading="currentFrameLoading" @click="loadFrameAnnotations(currentFrame?.frame_index ?? 0)">
              <el-icon><RefreshRight /></el-icon>
              Reload frame
            </el-button>
          </div>
        </div>
      </header>

      <section class="research-video-player-shell">
        <div class="research-video-player-panel">
          <video
            v-if="video?.file_url"
            ref="videoRef"
            class="research-video-player"
            controls
            :src="video.file_url"
            @pause="onVideoPause"
            @play="onVideoPlay"
            @seeked="syncFrameFromVideo"
          />
          <p class="research-video-player-help">
            Annotations are edited on extracted frames. Pause playback or select a frame to annotate.
          </p>
        </div>
      </section>

      <AnnotationCanvas
        v-if="currentCanvasImage"
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

      <div v-else v-loading="loading" class="annotate-empty">
        <el-icon><Pointer /></el-icon>
        <p>No frame loaded</p>
      </div>
    </section>

    <ObjectPanel
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
      @track-with-sam2="() => ElMessage.info('Track with SAM2 for Research videos is planned for a later iteration.')"
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
            <p class="eyebrow">Research labels</p>
            <h2>Manage Labels</h2>
            <span>{{ video?.name ?? `Video ${videoId}` }}</span>
          </div>
          <el-button :disabled="labelActionLoading" @click="closeLabelManager">Close</el-button>
        </header>

        <div class="label-management-modal-body">
          <div class="label-management-table">
            <div class="label-management-row label-management-row-head">
              <span>Color</span>
              <span>Name</span>
              <span>Shape</span>
              <span>Used</span>
            </div>
            <div v-for="label in labelDrafts" :key="label.id" class="label-management-row">
              <input v-model="label.color" class="label-management-color" type="color" disabled />
              <input v-model="label.name" class="label-management-name" disabled type="text" />
              <select v-model="label.shape_type" class="label-management-shape" disabled>
                <option value="polygon">polygon</option>
                <option value="rectangle">rectangle</option>
                <option value="point">point</option>
              </select>
              <span class="label-management-used">{{ label.annotation_count }}</span>
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
  </main>
</template>
