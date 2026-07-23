<script setup lang="ts">
import { Back, RefreshRight, VideoPause, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, shallowReactive, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import SkillAssessmentNavigator from '../components/research/SkillAssessmentNavigator.vue'
import SkillEvidencePanel from '../components/research/SkillEvidencePanel.vue'
import SkillEvidenceTimeline from '../components/research/SkillEvidenceTimeline.vue'
import SkillRubricManager from '../components/research/SkillRubricManager.vue'
import SkillScoreForm from '../components/research/SkillScoreForm.vue'
import SkillValidationPanel from '../components/research/SkillValidationPanel.vue'
import ResearchVideoTaskNav from '../components/research/ResearchVideoTaskNav.vue'
import VideoPlaybackRateControl from '../components/VideoPlaybackRateControl.vue'
import { useVideoPlaybackRate } from '../composables/useVideoPlaybackRate.ts'
import { useResearchPhasesStore } from '../stores/researchPhases.ts'
import { useResearchSkillsStore } from '../stores/researchSkills.ts'
import { useResearchVideosStore, type ResearchVideoFrame, type ResearchVideoWorkspaceDetail } from '../stores/researchVideos.ts'
import { useUsersStore } from '../stores/users.ts'
import type { ResearchPhaseAnnotationSetSummary } from '../types/researchPhase.ts'
import type { ResearchSkillCriterion, ResearchSkillEvidence, ResearchSkillValidationIssue } from '../types/researchSkill.ts'
import { DEFAULT_FRAME_PAGE_SIZE, ensureFramePageLoaded as ensureFramePageLoadedInCache, getFrameAtFromPages, getFramePageIndex, resetFramePageCache, type FramePageCacheState } from '../utils/researchVideoFrames.ts'
import { getPhaseProtocolDisplayName, translateApiErrorMessage, translateStatus, type SupportedLocale } from '../utils/locale.ts'
import { parseResearchFrameQuery } from '../utils/researchPhaseUi.ts'
import { buildIntervalEvidence, buildPhaseSegmentOccurrences, buildPointEvidence, findSkillScore, getApplicableCriteria } from '../utils/researchSkill.ts'
import { formatSkillTime } from '../utils/researchSkillUi.ts'

const props = defineProps<{ videoId: string }>()

const route = useRoute()
const router = useRouter()
const { locale, t } = useI18n()
const videosStore = useResearchVideosStore()
const skillsStore = useResearchSkillsStore()
const phasesStore = useResearchPhasesStore()
const usersStore = useUsersStore()

const {
  rubrics,
  selectedRubric,
  assessments,
  selectedAssessmentId,
  currentAssessment,
  validation,
  saving,
  validating,
  submitting,
  exporting,
  managingRubric,
  saveState,
  conflictState,
  selectedTargetType,
  selectedPhaseSegmentId,
  selectedCriterionId,
  selectedScoreId,
  selectedEvidenceId,
  isReadOnly,
  selectedCriterion,
  selectedScore,
} = storeToRefs(skillsStore)
const { protocols, annotationSets, protocolDetails } = storeToRefs(phasesStore)
const { currentUsername } = storeToRefs(usersStore)

const videoRef = ref<HTMLVideoElement | null>(null)
const gotoFrameInput = ref('')
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
const currentVideoTimeMs = ref(0)
const isPlaying = ref(false)
const pageError = ref('')
const showRubricManager = ref(false)
const showCreateAssessment = ref(false)
const showNavigatorDrawer = ref(false)
const showScoreDrawer = ref(false)
const pendingEvidenceStartFrame = ref<number | null>(null)
const suppressQueryWatch = ref(false)
const overallCommentInput = ref('')
const createAssessmentForm = reactive({
  rubric_id: null as number | null,
  phase_annotation_set_id: null as number | null,
})

let videoLoadGeneration = 0
let validateTimer: number | null = null
let overallCommentTimer: number | null = null

const video = computed(() => workspaceVideo.value)
useVideoPlaybackRate(videoRef, computed(() => video.value?.file_url ?? null))
const currentLocale = computed(() => locale.value as SupportedLocale)
const totalFrames = computed(() => video.value?.frame_count ?? 0)
const currentFrame = computed(() => getFrameAtFromPages(framePages, selectedFrameIndex.value, totalFrames.value, DEFAULT_FRAME_PAGE_SIZE))
const phaseSegments = computed(() => buildPhaseSegmentOccurrences(currentAssessment.value?.phase_annotation_set?.segments ?? []))
const selectedPhaseSegment = computed(() => phaseSegments.value.find((segment) => segment.id === selectedPhaseSegmentId.value) ?? null)
const applicableCriteria = computed(() => getApplicableCriteria(
  currentAssessment.value,
  selectedTargetType.value === 'overall' ? 'overall' : 'phase',
  selectedPhaseSegment.value,
))
const activeRubrics = computed(() => rubrics.value.filter((rubric) => rubric.status === 'active'))
const selectedCreateRubric = computed(() => rubrics.value.find((rubric) => rubric.id === createAssessmentForm.rubric_id) ?? null)
const matchingPhaseSets = computed(() => {
  const rubric = selectedRubric.value?.id === createAssessmentForm.rubric_id ? selectedRubric.value : null
  const protocolId = rubric?.phase_protocol_id ?? selectedCreateRubric.value?.phase_protocol_id ?? null
  if (!protocolId) {
    return []
  }
  return annotationSets.value.filter((set) => set.protocol_id === protocolId)
})
const currentProtocolDetail = computed(() => {
  const protocolId = selectedRubric.value?.phase_protocol_id
  return protocolId ? protocolDetails.value[protocolId] ?? null : null
})
const saveStateLabel = computed(() => {
  if (isReadOnly.value) return t('status.readonly')
  if (saveState.value === 'saving') return t('status.saving')
  if (saveState.value === 'saved') return t('status.saved')
  if (saveState.value === 'conflict') return t('status.conflict')
  if (saveState.value === 'error') return t('status.failed')
  return t('status.idle')
})

onMounted(async () => {
  await loadSkillWorkspace()
})

onBeforeUnmount(() => {
  videoLoadGeneration += 1
  flushOverallComment()
  clearValidateTimer()
  skillsStore.clearVideoState()
})

watch(() => props.videoId, () => {
  void loadSkillWorkspace()
})

watch(() => selectedFrameIndex.value, async (frameIndex) => {
  gotoFrameInput.value = totalFrames.value > 0 ? String(frameIndex + 1) : ''
  if (suppressQueryWatch.value) return
  suppressQueryWatch.value = true
  try {
    await router.replace({ query: { ...route.query, frame: String(frameIndex), assessment: selectedAssessmentId.value ? String(selectedAssessmentId.value) : undefined } })
  } finally {
    suppressQueryWatch.value = false
  }
})

watch(() => selectedAssessmentId.value, async (assessmentId) => {
  if (suppressQueryWatch.value) return
  suppressQueryWatch.value = true
  try {
    await router.replace({ query: { ...route.query, frame: String(selectedFrameIndex.value), assessment: assessmentId ? String(assessmentId) : undefined } })
  } finally {
    suppressQueryWatch.value = false
  }
})

watch(() => currentAssessment.value?.overall_comment ?? '', (value) => {
  if (overallCommentTimer === null) {
    overallCommentInput.value = value
  }
}, { immediate: true })

watch(() => route.query.assessment, (value) => {
  if (suppressQueryWatch.value) return
  const assessmentId = Number.parseInt(String(Array.isArray(value) ? value[0] : value ?? ''), 10)
  if (Number.isInteger(assessmentId) && assessmentId > 0 && assessmentId !== selectedAssessmentId.value) {
    void selectAssessment(assessmentId)
  }
})

async function loadSkillWorkspace() {
  const generation = ++videoLoadGeneration
  const videoId = Number(props.videoId)
  pageError.value = ''
  workspaceVideo.value = null
  resetFramePageCache(framePageCacheState)
  skillsStore.startVideoSession(videoId)
  phasesStore.startVideoSession(videoId)

  const workspace = await videosStore.fetchVideoWorkspace(videoId)
  if (generation !== videoLoadGeneration) return
  workspaceVideo.value = workspace
  if (!workspace) {
    pageError.value = translateApiErrorMessage(videosStore.error, t) || t('skillAssessment.workspaceRequestFailed')
    return
  }
  selectedFrameIndex.value = parseResearchFrameQuery(route.query.frame, workspace.frame_count)
  gotoFrameInput.value = String(selectedFrameIndex.value + 1)
  await ensureFrameLoaded(selectedFrameIndex.value)

  await Promise.all([
    skillsStore.fetchVideoAssessments(videoId),
    skillsStore.fetchRubrics({ includeArchived: true }),
    phasesStore.fetchProtocols(),
    phasesStore.fetchVideoAnnotationSets(videoId),
  ])
  const protocolIds = new Set<number>()
  for (const rubric of rubrics.value) {
    if (rubric.phase_protocol_id) protocolIds.add(rubric.phase_protocol_id)
  }
  await Promise.all([...protocolIds].map((protocolId) => phasesStore.fetchProtocol(protocolId)))

  if (generation !== videoLoadGeneration) return
  const assessmentFromQuery = Number.parseInt(String(route.query.assessment ?? ''), 10)
  if (Number.isInteger(assessmentFromQuery) && assessmentFromQuery > 0) {
    const result = await skillsStore.fetchAssessment(assessmentFromQuery)
    if (result.ok && result.data.video_id === videoId) {
      await afterAssessmentLoaded()
      return
    }
    await clearAssessmentQuery()
  }
  const ownAssessment = assessments.value
    .filter((assessment) => assessment.rater_username === currentUsername.value)
    .sort((left, right) => right.updated_at.localeCompare(left.updated_at))[0]
  if (ownAssessment) {
    await selectAssessment(ownAssessment.id)
  } else {
    showCreateAssessment.value = true
  }
  await nextTick()
  syncVideoToCurrentFrame()
}

async function afterAssessmentLoaded() {
  chooseDefaultTargetAndCriterion()
  await skillsStore.validateAssessment()
  scheduleValidate()
}

async function clearAssessmentQuery() {
  suppressQueryWatch.value = true
  try {
    await router.replace({ query: { ...route.query, assessment: undefined } })
  } finally {
    suppressQueryWatch.value = false
  }
}

function chooseDefaultTargetAndCriterion() {
  selectedTargetType.value = 'overall'
  selectedPhaseSegmentId.value = null
  const firstCriterion = getApplicableCriteria(currentAssessment.value, 'overall', null)[0]
  selectedCriterionId.value = firstCriterion?.id ?? null
  selectedScoreId.value = selectedCriterionId.value
    ? findSkillScore(currentAssessment.value?.scores ?? [], selectedCriterionId.value, 'overall', null)?.id ?? null
    : null
}

async function selectAssessment(assessmentId: number) {
  const result = await skillsStore.selectAssessment(assessmentId)
  if (!result.ok) {
    ElMessage.error(result.error.message)
    return
  }
  await afterAssessmentLoaded()
}

async function createAssessment() {
  if (!createAssessmentForm.rubric_id || !currentUsername.value) {
    ElMessage.warning(t('skillAssessment.selectRubricAndUser'))
    return
  }
  const result = await skillsStore.getOrCreateAssessment(Number(props.videoId), {
    rubric_id: createAssessmentForm.rubric_id,
    username: currentUsername.value,
    phase_annotation_set_id: createAssessmentForm.phase_annotation_set_id,
  })
  if (!result.ok) {
    ElMessage.error(result.error.message)
    return
  }
  showCreateAssessment.value = false
  ElMessage.success(result.data.created ? t('skillAssessment.created') : t('skillAssessment.openedExisting'))
  await afterAssessmentLoaded()
}

function selectOverall() {
  selectedTargetType.value = 'overall'
  selectedPhaseSegmentId.value = null
  const criteria = getApplicableCriteria(currentAssessment.value, 'overall', null)
  selectedCriterionId.value = criteria[0]?.id ?? null
  selectedScoreId.value = selectedCriterionId.value ? findSkillScore(currentAssessment.value?.scores ?? [], selectedCriterionId.value, 'overall', null)?.id ?? null : null
}

async function selectPhaseSegment(segmentId: number) {
  selectedTargetType.value = 'phase_segment'
  selectedPhaseSegmentId.value = segmentId
  const segment = phaseSegments.value.find((item) => item.id === segmentId) ?? null
  selectedCriterionId.value = getApplicableCriteria(currentAssessment.value, 'phase', segment)[0]?.id ?? null
  selectedScoreId.value = selectedCriterionId.value ? findSkillScore(currentAssessment.value?.scores ?? [], selectedCriterionId.value, 'phase_segment', segmentId)?.id ?? null : null
  if (segment) {
    await goToFrame(segment.start_frame)
  }
}

function selectCriterion(criterionId: number) {
  selectedCriterionId.value = criterionId
  selectedScoreId.value = findSkillScore(
    currentAssessment.value?.scores ?? [],
    criterionId,
    selectedTargetType.value,
    selectedTargetType.value === 'overall' ? null : selectedPhaseSegmentId.value,
  )?.id ?? null
}

async function saveScore(payload: { criterion_id?: number; value?: unknown; is_na?: boolean; comment?: string | null; clear_comment?: boolean }) {
  const criterionId = payload.criterion_id ?? selectedCriterion.value?.id
  if (!criterionId) return
  const { criterion_id: _criterionId, ...scorePayload } = payload
  const result = await skillsStore.upsertScore(criterionId, {
    target_type: selectedTargetType.value,
    phase_segment_id: selectedTargetType.value === 'phase_segment' ? selectedPhaseSegmentId.value : null,
    ...scorePayload,
  })
  if (!result.ok) {
    ElMessage.error(result.error.message)
    return
  }
  scheduleValidate()
}

async function deleteScore() {
  if (!selectedScore.value) return
  await ElMessageBox.confirm(t('skillAssessment.deleteScoreConfirm'), t('skillAssessment.deleteScoreTitle'), { type: 'warning' })
  const result = await skillsStore.deleteScore(selectedScore.value.id)
  if (!result.ok) ElMessage.error(result.error.message)
  scheduleValidate()
}

async function addPointEvidence() {
  if (!selectedScore.value) return
  const result = await skillsStore.createEvidence(selectedScore.value.id, buildPointEvidence(selectedFrameIndex.value))
  if (!result.ok) ElMessage.error(result.error.message)
  scheduleValidate()
}

function startIntervalEvidence() {
  pendingEvidenceStartFrame.value = selectedFrameIndex.value
}

async function finishIntervalEvidence() {
  if (!selectedScore.value || pendingEvidenceStartFrame.value === null) return
  const result = await skillsStore.createEvidence(selectedScore.value.id, buildIntervalEvidence(pendingEvidenceStartFrame.value, selectedFrameIndex.value))
  pendingEvidenceStartFrame.value = null
  if (!result.ok) ElMessage.error(result.error.message)
  scheduleValidate()
}

async function updateEvidence(evidenceId: number, payload: { start_frame?: number; end_frame_exclusive?: number | null; clear_end_frame?: boolean; comment?: string | null; clear_comment?: boolean }) {
  const result = await skillsStore.updateEvidence(evidenceId, payload)
  if (!result.ok) ElMessage.error(result.error.message)
  scheduleValidate()
}

async function deleteEvidence(evidenceId: number) {
  await ElMessageBox.confirm(t('skillAssessment.deleteEvidenceConfirm'), t('skillAssessment.deleteEvidenceTitle'), { type: 'warning' })
  const result = await skillsStore.deleteEvidence(evidenceId)
  if (!result.ok) ElMessage.error(result.error.message)
  scheduleValidate()
}

async function goEvidence(evidence: ResearchSkillEvidence) {
  selectedEvidenceId.value = evidence.id
  await goToFrame(evidence.start_frame)
}

async function submitAssessment(confirmWarnings = false) {
  const validationResult = await skillsStore.validateAssessment()
  if (validationResult.ok && validationResult.data.issue_counts.error > 0) {
    ElMessage.error(t('skillAssessment.resolveErrorsBeforeSubmit'))
    return
  }
  const result = await skillsStore.submitAssessment(confirmWarnings)
  if (!result.ok) {
    if (result.error.kind === 'warning_confirmation') {
      await ElMessageBox.confirm(t('skillAssessment.submitWarningsConfirm'), t('skillAssessment.confirmWarnings'), { type: 'warning' })
      await submitAssessment(true)
      return
    }
    ElMessage.error(result.error.message)
    return
  }
  ElMessage.success(t('skillAssessment.submitted'))
}

async function reopenAssessment() {
  await ElMessageBox.confirm(t('skillAssessment.reopenConfirm'), t('skillAssessment.reopenTitle'))
  const result = await skillsStore.reopenAssessment()
  if (!result.ok) ElMessage.error(result.error.message)
}

function scheduleValidate() {
  clearValidateTimer()
  validateTimer = window.setTimeout(() => {
    void skillsStore.validateAssessment()
    validateTimer = null
  }, 300)
}

function clearValidateTimer() {
  if (validateTimer !== null) {
    window.clearTimeout(validateTimer)
    validateTimer = null
  }
}

function handleIssue(issue: ResearchSkillValidationIssue) {
  if (issue.phase_segment_id) {
    void selectPhaseSegment(issue.phase_segment_id)
  }
  if (issue.criterion_id) {
    selectedCriterionId.value = issue.criterion_id
  }
  if (issue.score_id) {
    selectedScoreId.value = issue.score_id
  }
  if (issue.evidence_id) {
    selectedEvidenceId.value = issue.evidence_id
    const evidence = selectedScore.value?.evidence.find((item) => item.id === issue.evidence_id)
    if (evidence) void goToFrame(evidence.start_frame)
  }
}

async function saveCriterion(criterionId: number | null, payload: Parameters<typeof skillsStore.createCriterion>[1]) {
  if (!selectedRubric.value) return
  const result = criterionId
    ? await skillsStore.updateCriterion(criterionId, payload)
    : await skillsStore.createCriterion(selectedRubric.value.id, payload)
  if (!result.ok) ElMessage.error(result.error.message)
}

async function handleRubricSelect(rubricId: number) {
  await skillsStore.fetchRubric(rubricId)
  const protocolId = selectedRubric.value?.phase_protocol_id
  if (protocolId) await phasesStore.fetchProtocol(protocolId)
}

async function cloneRubric(rubricId: number) {
  await ElMessageBox.confirm(t('skillAssessment.cloneRubricConfirm'), t('skillAssessment.cloneRubricTitle'))
  const result = await skillsStore.cloneRubric(rubricId)
  if (!result.ok) ElMessage.error(result.error.message)
}

async function activateRubric(rubricId: number) {
  await ElMessageBox.confirm(t('skillAssessment.activateRubricConfirm'), t('skillAssessment.activateRubricTitle'))
  const result = await skillsStore.activateRubric(rubricId)
  if (!result.ok) ElMessage.error(result.error.message)
}

async function archiveRubric(rubricId: number) {
  await ElMessageBox.confirm(t('skillAssessment.archiveRubricConfirm'), t('skillAssessment.archiveRubricTitle'), { type: 'warning' })
  const result = await skillsStore.archiveRubric(rubricId)
  if (!result.ok) ElMessage.error(result.error.message)
}

async function updateOverallComment(value: string) {
  const result = await skillsStore.updateAssessment({ overall_comment: value || null })
  if (!result.ok) ElMessage.error(result.error.message)
  scheduleValidate()
}

function scheduleOverallCommentSave(value: string) {
  overallCommentInput.value = value
  clearOverallCommentTimer()
  overallCommentTimer = window.setTimeout(() => {
    void updateOverallComment(overallCommentInput.value)
    overallCommentTimer = null
  }, 600)
}

function clearOverallCommentTimer() {
  if (overallCommentTimer !== null) {
    window.clearTimeout(overallCommentTimer)
    overallCommentTimer = null
  }
}

function flushOverallComment() {
  if (overallCommentTimer === null) {
    return
  }
  clearOverallCommentTimer()
  void updateOverallComment(overallCommentInput.value)
}

async function ensureFrameLoaded(frameIndex: number) {
  await ensureFramePageLoadedInCache({
    state: framePageCacheState,
    pageIndex: getFramePageIndex(frameIndex, DEFAULT_FRAME_PAGE_SIZE),
    totalCount: totalFrames.value,
    generation: videoLoadGeneration,
    isCurrentGeneration: (generation) => generation === videoLoadGeneration,
    loadPage: async ({ offset, limit }) => {
      const page = await videosStore.fetchVideoFramesPage(Number(props.videoId), { offset, limit })
      return page?.items ?? null
    },
    currentPageIndex: getFramePageIndex(frameIndex, DEFAULT_FRAME_PAGE_SIZE),
    maxCachedPages: 4,
    preservedPageIndices: [getFramePageIndex(selectedFrameIndex.value, DEFAULT_FRAME_PAGE_SIZE)],
    pageSize: DEFAULT_FRAME_PAGE_SIZE,
  })
}

async function goToFrame(frameIndex: number) {
  if (frameIndex < 0 || frameIndex >= totalFrames.value) return
  selectedFrameIndex.value = frameIndex
  await ensureFrameLoaded(frameIndex)
  syncVideoToCurrentFrame()
}

function previousFrame() {
  void goToFrame(Math.max(0, selectedFrameIndex.value - 1))
}

function nextFrame() {
  void goToFrame(Math.min(totalFrames.value - 1, selectedFrameIndex.value + 1))
}

function goToInputFrame() {
  const parsed = Number.parseInt(gotoFrameInput.value, 10)
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > totalFrames.value) {
    ElMessage.warning(`Frame number must be between 1 and ${totalFrames.value}.`)
    return
  }
  void goToFrame(parsed - 1)
}

function getFrameTimeSeconds(frame: ResearchVideoFrame | undefined) {
  if (!frame) return 0
  if (Number.isFinite(frame.timestamp_ms)) return frame.timestamp_ms / 1000
  return video.value?.fps ? frame.frame_index / video.value.fps : 0
}

function syncVideoToCurrentFrame() {
  if (!videoRef.value) return
  videoRef.value.currentTime = getFrameTimeSeconds(currentFrame.value)
}

function syncFrameFromVideo() {
  if (!videoRef.value || !video.value?.fps || totalFrames.value <= 0) return
  const nextFrame = Math.min(totalFrames.value - 1, Math.max(0, Math.round(videoRef.value.currentTime * video.value.fps)))
  selectedFrameIndex.value = nextFrame
  currentVideoTimeMs.value = Math.round(videoRef.value.currentTime * 1000)
  void ensureFrameLoaded(nextFrame)
}

function togglePlayback() {
  if (!videoRef.value) return
  if (videoRef.value.paused) void videoRef.value.play()
  else videoRef.value.pause()
}
</script>

<template>
  <div class="research-skill-page">
    <header class="research-skill-header">
      <router-link class="research-back-link" to="/research/videos">
        <el-icon><Back /></el-icon>
        {{ t('phaseAnnotation.researchVideos') }}
      </router-link>
      <div>
        <h1>{{ video?.name ?? t('skillAssessment.title') }}</h1>
        <p>{{ t('common.frame') }} {{ totalFrames > 0 ? selectedFrameIndex + 1 : 0 }} / {{ totalFrames }} · {{ formatSkillTime(selectedFrameIndex, video?.fps) }}</p>
      </div>
      <ResearchVideoTaskNav active-task="skill" :video-id="videoId" :current-frame-index="selectedFrameIndex" />
      <el-tag :type="saveState === 'conflict' ? 'danger' : saveState === 'saved' ? 'success' : 'info'">{{ saveStateLabel }}</el-tag>
    </header>

    <el-alert v-if="pageError" :title="pageError" type="error" show-icon />

    <main class="research-skill-grid">
      <SkillAssessmentNavigator
        class="research-skill-left"
        :assessments="assessments"
        :current-assessment="currentAssessment"
        :validation="validation"
        :selected-assessment-id="selectedAssessmentId"
        :selected-target-type="selectedTargetType"
        :selected-phase-segment-id="selectedPhaseSegmentId"
        :selected-criterion-id="selectedCriterionId"
        @select-assessment="selectAssessment"
        @create-assessment="showCreateAssessment = true"
        @open-rubrics="showRubricManager = true"
        @select-overall="selectOverall"
        @select-phase-segment="selectPhaseSegment"
        @select-criterion="selectCriterion"
      />

      <section class="research-skill-center">
        <div class="research-skill-video-card">
          <video
            v-if="video"
            ref="videoRef"
            class="research-skill-video"
            :src="video.file_url"
            preload="metadata"
            controls
            @play="isPlaying = true"
            @pause="isPlaying = false; syncFrameFromVideo()"
            @timeupdate="syncFrameFromVideo"
            @loadedmetadata="syncVideoToCurrentFrame"
          />
          <div class="research-skill-toolbar">
            <el-button :icon="isPlaying ? VideoPause : VideoPlay" @click="togglePlayback">
              {{ isPlaying ? t('frameAnnotation.pause') : t('frameAnnotation.play') }}
            </el-button>
            <VideoPlaybackRateControl compact />
            <el-button @click="previousFrame">{{ t('common.previous') }}</el-button>
            <el-button @click="nextFrame">{{ t('common.next') }}</el-button>
            <el-input v-model="gotoFrameInput" class="research-skill-goto" @keyup.enter="goToInputFrame" />
            <el-button @click="goToInputFrame">{{ t('common.goTo') }}</el-button>
            <el-button :icon="RefreshRight" @click="syncVideoToCurrentFrame">{{ t('common.sync') }}</el-button>
          </div>
        </div>

        <SkillEvidenceTimeline
          :frame-count="totalFrames"
          :current-frame-index="selectedFrameIndex"
          :phase-segments="currentAssessment?.phase_annotation_set?.segments ?? []"
          :score="selectedScore"
          :pending-start-frame="pendingEvidenceStartFrame"
          @seek="goToFrame"
          @select-evidence="goEvidence"
        />

        <SkillValidationPanel
          :validation="validation"
          :validating="validating"
          @validate="skillsStore.validateAssessment()"
          @issue="handleIssue"
        />

        <section class="research-skill-actions">
          <el-input
            v-model="overallCommentInput"
            type="textarea"
            :rows="2"
            :disabled="isReadOnly || saving"
            :placeholder="t('skillAssessment.overallComment')"
            @input="scheduleOverallCommentSave(String($event))"
          />
          <div class="research-skill-action-row">
            <el-button :loading="exporting" :disabled="!currentAssessment" @click="skillsStore.downloadJson()">{{ t('skillAssessment.jsonExport') }}</el-button>
            <el-button :loading="exporting" :disabled="!currentAssessment" @click="skillsStore.downloadCsv()">{{ t('skillAssessment.csvExport') }}</el-button>
            <el-button v-if="currentAssessment?.status === 'draft'" type="primary" :loading="submitting" @click="submitAssessment(false)">{{ t('skillAssessment.submitAssessment') }}</el-button>
            <el-button v-if="currentAssessment?.status === 'submitted'" type="warning" :loading="submitting" @click="reopenAssessment">{{ t('skillAssessment.reopenForEditing') }}</el-button>
          </div>
        </section>
      </section>

      <aside class="research-skill-right">
        <SkillScoreForm
          :criterion="selectedCriterion"
          :score="selectedScore"
          :readonly="isReadOnly"
          :saving="saving"
          @save="saveScore"
          @delete-score="deleteScore"
        />
        <SkillEvidencePanel
          v-model:pending-start-frame="pendingEvidenceStartFrame"
          :score="selectedScore"
          :current-frame-index="selectedFrameIndex"
          :fps="video?.fps"
          :readonly="isReadOnly"
          :saving="saving"
          @add-point="addPointEvidence"
          @start-interval="startIntervalEvidence"
          @finish-interval="finishIntervalEvidence"
          @cancel-interval="pendingEvidenceStartFrame = null"
          @go-evidence="goEvidence"
          @update-evidence="updateEvidence"
          @delete-evidence="deleteEvidence"
        />
      </aside>
    </main>

    <el-dialog v-model="showCreateAssessment" :title="t('skillAssessment.createAssessment')" width="min(560px, 94vw)">
      <div class="research-skill-create-dialog">
        <el-select v-model="createAssessmentForm.rubric_id" :placeholder="t('skillAssessment.activeRubric')" @change="(id: number) => skillsStore.fetchRubric(id)">
          <el-option
            v-for="rubric in activeRubrics"
            :key="rubric.id"
            :label="`${rubric.name} v${rubric.version}`"
            :value="rubric.id"
          />
        </el-select>
        <el-select v-model="createAssessmentForm.phase_annotation_set_id" clearable :placeholder="t('skillAssessment.optionalPhaseSet')">
          <el-option
            v-for="set in matchingPhaseSets"
            :key="set.id"
            :label="`${getPhaseProtocolDisplayName({ name: set.protocol_name, is_default: true }, currentLocale)} v${set.protocol_version} · ${set.annotator_username} · ${translateStatus(set.status, t)} · ${set.segment_count} ${t('common.frames')}`"
            :value="set.id"
          />
        </el-select>
        <p>{{ t('skillAssessment.rater') }}: {{ currentUsername || t('skillAssessment.noCurrentUser') }}</p>
        <el-button type="primary" @click="createAssessment">{{ t('skillAssessment.createOpenAssessment') }}</el-button>
      </div>
    </el-dialog>

    <SkillRubricManager
      v-model="showRubricManager"
      :rubrics="rubrics"
      :selected-rubric="selectedRubric"
      :protocols="protocols"
      :protocol-detail="currentProtocolDetail"
      :current-username="currentUsername"
      :loading="false"
      :saving="managingRubric"
      @fetch-rubrics="(includeArchived) => skillsStore.fetchRubrics({ includeArchived })"
      @select-rubric="handleRubricSelect"
      @create-rubric="skillsStore.createRubric"
      @update-rubric="skillsStore.updateRubric"
      @clone-rubric="cloneRubric"
      @activate-rubric="activateRubric"
      @archive-rubric="archiveRubric"
      @save-criterion="saveCriterion"
    />

    <el-dialog :model-value="Boolean(conflictState)" :title="t('skillAssessment.changedTitle')" width="420px" :close-on-click-modal="false">
      <p>{{ t('skillAssessment.changedBody') }}</p>
      <template #footer>
        <el-button @click="skillsStore.conflictState = null">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="skillsStore.reloadLatestAssessment()">{{ t('phaseAnnotation.reloadLatest') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.research-skill-page {
  min-height: 100vh;
  padding: 1.25rem;
  background:
    radial-gradient(circle at 15% 10%, rgba(20, 184, 166, 0.2), transparent 30rem),
    radial-gradient(circle at 85% 0%, rgba(234, 179, 8, 0.16), transparent 28rem),
    #020617;
  color: #e2e8f0;
}

.research-skill-header {
  display: grid;
  grid-template-columns: auto minmax(180px, 1fr) auto auto;
  gap: 1rem;
  align-items: center;
  margin-bottom: 1rem;
}

.research-back-link {
  display: inline-flex;
  gap: 0.35rem;
  color: #bae6fd;
  text-decoration: none;
  align-items: center;
}

.research-skill-header h1,
.research-skill-header p {
  margin: 0;
}

.research-skill-header p {
  color: rgba(148, 163, 184, 0.92);
}

.research-skill-grid {
  display: grid;
  grid-template-columns: minmax(250px, 0.82fr) minmax(420px, 1.45fr) minmax(300px, 0.95fr);
  gap: 1rem;
  align-items: start;
}

.research-skill-center,
.research-skill-right {
  display: grid;
  gap: 1rem;
}

.research-skill-right {
  padding: 1rem;
  border-radius: 1.1rem;
  background: rgba(15, 23, 42, 0.78);
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.research-skill-video-card,
.research-skill-actions {
  display: grid;
  gap: 0.8rem;
  padding: 1rem;
  border-radius: 1.1rem;
  background: rgba(15, 23, 42, 0.78);
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.research-skill-video {
  width: 100%;
  max-height: 46vh;
  border-radius: 1rem;
  background: #000;
}

.research-skill-toolbar,
.research-skill-action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}

.research-skill-goto {
  width: 7rem;
}

.research-skill-create-dialog {
  display: grid;
  gap: 1rem;
}

@media (max-width: 1280px) {
  .research-skill-grid {
    grid-template-columns: minmax(230px, 0.8fr) minmax(360px, 1.2fr);
  }

  .research-skill-right {
    grid-column: 1 / -1;
  }
}

@media (max-width: 840px) {
  .research-skill-page {
    padding: 0.75rem;
  }

  .research-skill-header,
  .research-skill-grid {
    grid-template-columns: 1fr;
  }
}
</style>
