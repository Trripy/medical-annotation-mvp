<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ResearchPhaseLabel, ResearchPhaseSegment, ResearchPhaseSegmentSource } from '../../types/researchPhase'
import { getPhaseLabelDisplayName, translateStatus, type SupportedLocale } from '../../utils/locale'
import {
  buildCloseActiveEndFrame,
  formatDurationMs,
  frameToTimestampMs,
  fromUiInclusiveEndFrame,
  fromUiStartFrame,
  toUiFrameNumber,
  toUiInclusiveEndFrame,
} from '../../utils/researchPhaseUi'

type SegmentPatch = {
  phase_label_id?: number | null
  start_frame?: number | null
  end_frame_exclusive?: number | null
  clear_end_frame?: boolean
  source?: ResearchPhaseSegmentSource | null
  confidence?: number | null
  clear_confidence?: boolean
  notes?: string | null
  clear_notes?: boolean
}

const props = defineProps<{
  canMergeNext: boolean
  canMergePrevious: boolean
  currentFrameIndex: number
  fps: number | null
  frameCount: number
  labels: ResearchPhaseLabel[]
  readOnly: boolean
  saving: boolean
  segment: ResearchPhaseSegment | null
}>()

const { locale, t } = useI18n()
const currentLocale = computed(() => locale.value as SupportedLocale)

const emit = defineEmits<{
  deleteSegment: [segmentId: number]
  mergeNext: [segmentId: number]
  mergePrevious: [segmentId: number]
  splitSegment: [segmentId: number]
  updateSegment: [payload: { segmentId: number; patch: SegmentPatch }]
}>()

const startFrameInput = ref('')
const endFrameInput = ref('')
const notesInput = ref('')
const confidenceInput = ref('')
const sourceInput = ref<ResearchPhaseSegmentSource>('manual')
let notesTimer = 0

const startTimeText = computed(() => {
  if (!props.segment) {
    return '--'
  }
  return formatDurationMs(frameToTimestampMs(props.segment.start_frame, props.fps))
})

const endTimeText = computed(() => {
  if (!props.segment || props.segment.end_frame_exclusive === null) {
    return 'Open'
  }
  return formatDurationMs(frameToTimestampMs(props.segment.end_frame_exclusive, props.fps))
})

const durationText = computed(() => {
  if (!props.segment || props.segment.end_frame_exclusive === null) {
    return 'Open'
  }
  const startTime = frameToTimestampMs(props.segment.start_frame, props.fps)
  const endTime = frameToTimestampMs(props.segment.end_frame_exclusive, props.fps)
  return formatDurationMs(startTime === null || endTime === null ? null : Math.max(0, endTime - startTime))
})
const segmentLabelText = computed(() => (
  props.segment ? getPhaseLabelDisplayName(props.segment.phase_label, currentLocale.value) : ''
))

const canSplitAtPlayhead = computed(() => {
  if (!props.segment) {
    return false
  }
  const end = props.segment.end_frame_exclusive ?? props.frameCount
  return props.segment.start_frame < props.currentFrameIndex && props.currentFrameIndex < end
})

watch(
  () => props.segment,
  (segment) => {
    startFrameInput.value = segment ? toUiFrameNumber(segment.start_frame) : ''
    endFrameInput.value = segment ? toUiInclusiveEndFrame(segment.end_frame_exclusive) : ''
    notesInput.value = segment?.notes ?? ''
    confidenceInput.value = segment?.confidence === null || segment?.confidence === undefined ? '' : String(segment.confidence)
    sourceInput.value = segment?.source ?? 'manual'
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (notesTimer) {
    window.clearTimeout(notesTimer)
  }
})

function emitUpdate(patch: SegmentPatch) {
  if (!props.segment || props.readOnly) {
    return
  }
  emit('updateSegment', {
    segmentId: props.segment.id,
    patch,
  })
}

function saveStartFrame() {
  if (!props.segment) {
    return
  }
  const parsed = fromUiStartFrame(startFrameInput.value, props.frameCount)
  if (parsed === null || parsed === props.segment.start_frame) {
    startFrameInput.value = toUiFrameNumber(props.segment.start_frame)
    return
  }
  emitUpdate({ start_frame: parsed })
}

function saveEndFrame() {
  if (!props.segment || props.segment.end_frame_exclusive === null) {
    return
  }
  const parsed = fromUiInclusiveEndFrame(endFrameInput.value, props.frameCount)
  if (parsed === null || parsed === props.segment.end_frame_exclusive) {
    endFrameInput.value = toUiInclusiveEndFrame(props.segment.end_frame_exclusive)
    return
  }
  emitUpdate({ end_frame_exclusive: parsed })
}

function scheduleNotesSave() {
  if (notesTimer) {
    window.clearTimeout(notesTimer)
  }
  notesTimer = window.setTimeout(() => {
    flushNotesSave()
  }, 600)
}

function flushNotesSave() {
  if (!props.segment) {
    return
  }
  const normalized = notesInput.value.trim()
  if (!normalized && !props.segment.notes) {
    return
  }
  if (!normalized) {
    emitUpdate({ clear_notes: true })
    return
  }
  if (normalized !== (props.segment.notes ?? '')) {
    emitUpdate({ notes: normalized })
  }
}

function clearNotes() {
  notesInput.value = ''
  emitUpdate({ clear_notes: true })
}

function saveConfidence() {
  if (!props.segment) {
    return
  }
  const normalized = confidenceInput.value.trim()
  if (!normalized) {
    emitUpdate({ clear_confidence: true })
    return
  }
  const parsed = Number.parseFloat(normalized)
  if (!Number.isFinite(parsed)) {
    confidenceInput.value = props.segment.confidence === null ? '' : String(props.segment.confidence)
    return
  }
  if (parsed !== props.segment.confidence) {
    emitUpdate({ confidence: parsed })
  }
}

function clearConfidence() {
  confidenceInput.value = ''
  emitUpdate({ clear_confidence: true })
}

function saveSource() {
  if (!props.segment || sourceInput.value === props.segment.source) {
    return
  }
  emitUpdate({ source: sourceInput.value })
}

function markAsOpen() {
  emitUpdate({ clear_end_frame: true })
}

function closeAtCurrentFrame() {
  emitUpdate({ end_frame_exclusive: buildCloseActiveEndFrame(props.currentFrameIndex, props.frameCount) })
}

function closeAtVideoEnd() {
  emitUpdate({ end_frame_exclusive: props.frameCount })
}
</script>

<template>
  <section class="phase-inspector">
    <header class="phase-inspector-header">
      <div>
        <p class="phase-inspector-eyebrow">{{ t('phaseAnnotation.inspector') }}</p>
        <h3 v-if="segment">{{ segmentLabelText }}</h3>
        <h3 v-else>{{ t('phaseAnnotation.noSegmentSelected') }}</h3>
      </div>
      <span v-if="segment" class="phase-inspector-badge" :style="{ backgroundColor: segment.phase_label.color }"></span>
    </header>

    <template v-if="segment">
      <div class="phase-inspector-grid">
        <label>
          {{ t('phaseAnnotation.phaseLabel') }}
          <select :disabled="readOnly || saving" :value="segment.phase_label_id" @change="emitUpdate({ phase_label_id: Number(($event.target as HTMLSelectElement).value) })">
            <option v-for="label in labels" :key="label.id" :value="label.id">{{ getPhaseLabelDisplayName(label, currentLocale) }}</option>
          </select>
        </label>

        <label>
          {{ t('phaseAnnotation.startFrame') }}
          <input
            v-model="startFrameInput"
            :disabled="readOnly || saving"
            inputmode="numeric"
            type="text"
            @blur="saveStartFrame"
            @keydown.enter.prevent="saveStartFrame"
          />
        </label>

        <label>
          {{ t('phaseAnnotation.endFrameInclusive') }}
          <input
            v-model="endFrameInput"
            :disabled="readOnly || saving || segment.end_frame_exclusive === null"
            inputmode="numeric"
            type="text"
            @blur="saveEndFrame"
            @keydown.enter.prevent="saveEndFrame"
          />
        </label>

        <label>
          {{ t('phaseAnnotation.source') }}
          <select v-model="sourceInput" :disabled="readOnly || saving" @change="saveSource">
            <option value="manual">{{ translateStatus('manual', t) }}</option>
            <option value="model_suggestion">{{ translateStatus('model_suggestion', t) }}</option>
            <option value="model_corrected">{{ translateStatus('model_corrected', t) }}</option>
            <option value="imported">{{ translateStatus('imported', t) }}</option>
          </select>
        </label>

        <label>
          {{ t('phaseAnnotation.confidence') }}
          <div class="phase-inspector-inline">
            <input
              v-model="confidenceInput"
              :disabled="readOnly || saving"
              inputmode="decimal"
              type="text"
              @blur="saveConfidence"
              @keydown.enter.prevent="saveConfidence"
            />
            <button type="button" :disabled="readOnly || saving" @click="clearConfidence">{{ t('common.clear') }}</button>
          </div>
        </label>

        <label class="phase-inspector-span-two">
          {{ t('phaseAnnotation.notes') }}
          <textarea
            v-model="notesInput"
            :disabled="readOnly || saving"
            rows="4"
            @blur="flushNotesSave"
            @input="scheduleNotesSave"
          ></textarea>
          <button class="phase-inspector-secondary" type="button" :disabled="readOnly || saving" @click="clearNotes">{{ t('phaseAnnotation.clearNotes') }}</button>
        </label>
      </div>

      <dl class="phase-inspector-metadata">
        <div><dt>{{ t('phaseAnnotation.status') }}</dt><dd>{{ segment.end_frame_exclusive === null ? t('status.open') : t('status.closed') }}</dd></div>
        <div><dt>{{ t('phaseAnnotation.startTime') }}</dt><dd>{{ startTimeText === 'Open' ? t('status.open') : startTimeText }}</dd></div>
        <div><dt>{{ t('phaseAnnotation.endTime') }}</dt><dd>{{ endTimeText === 'Open' ? t('status.open') : endTimeText }}</dd></div>
        <div><dt>{{ t('phaseAnnotation.duration') }}</dt><dd>{{ durationText === 'Open' ? t('status.open') : durationText }}</dd></div>
      </dl>

      <div class="phase-inspector-actions">
        <button type="button" :disabled="readOnly || saving || !canSplitAtPlayhead" @click="emit('splitSegment', segment.id)">
          {{ t('phaseAnnotation.splitAtPlayhead') }}
        </button>
        <button type="button" :disabled="readOnly || saving || !canMergePrevious" @click="emit('mergePrevious', segment.id)">
          {{ t('phaseAnnotation.mergePrevious') }}
        </button>
        <button type="button" :disabled="readOnly || saving || !canMergeNext" @click="emit('mergeNext', segment.id)">
          {{ t('phaseAnnotation.mergeNext') }}
        </button>
        <button
          v-if="segment.end_frame_exclusive !== null"
          type="button"
          :disabled="readOnly || saving"
          @click="markAsOpen"
        >
          {{ t('status.open') }}
        </button>
        <button
          v-else
          type="button"
          :disabled="readOnly || saving"
          @click="closeAtCurrentFrame"
        >
          {{ t('phaseAnnotation.closeAtCurrentFrame') }}
        </button>
        <button
          v-if="segment.end_frame_exclusive === null"
          type="button"
          :disabled="readOnly || saving"
          @click="closeAtVideoEnd"
        >
          {{ t('phaseAnnotation.closeAtVideoEnd') }}
        </button>
        <button class="is-danger" type="button" :disabled="readOnly || saving" @click="emit('deleteSegment', segment.id)">
          {{ t('phaseAnnotation.deleteSegment') }}
        </button>
      </div>
    </template>

    <p v-else class="phase-inspector-placeholder">
      {{ t('phaseAnnotation.noSegmentSelected') }}
    </p>
  </section>
</template>

<style scoped>
.phase-inspector {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1rem;
  border-radius: 1rem;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.84);
}

.phase-inspector-header {
  display: flex;
  justify-content: space-between;
  gap: 0.8rem;
  align-items: flex-start;
}

.phase-inspector-eyebrow {
  margin: 0 0 0.2rem;
  font-size: 0.78rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(125, 211, 252, 0.84);
}

.phase-inspector-header h3 {
  margin: 0;
  color: #f8fafc;
}

.phase-inspector-badge {
  width: 18px;
  height: 18px;
  border-radius: 999px;
  box-shadow: 0 0 0 4px rgba(15, 23, 42, 0.72);
}

.phase-inspector-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.9rem;
}

.phase-inspector-grid label,
.phase-inspector-grid input,
.phase-inspector-grid select,
.phase-inspector-grid textarea {
  width: 100%;
}

.phase-inspector-grid label {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  color: rgba(226, 232, 240, 0.92);
  font-size: 0.88rem;
}

.phase-inspector-grid input,
.phase-inspector-grid select,
.phase-inspector-grid textarea {
  padding: 0.65rem 0.75rem;
  border-radius: 0.75rem;
  border: 1px solid rgba(148, 163, 184, 0.2);
  background: rgba(30, 41, 59, 0.82);
  color: #f8fafc;
}

.phase-inspector-inline {
  display: flex;
  gap: 0.5rem;
}

.phase-inspector-span-two {
  grid-column: 1 / -1;
}

.phase-inspector-secondary,
.phase-inspector-actions button,
.phase-inspector-inline button {
  padding: 0.58rem 0.8rem;
  border-radius: 0.75rem;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(30, 41, 59, 0.82);
  color: #e2e8f0;
}

.phase-inspector-metadata {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem;
  margin: 0;
}

.phase-inspector-metadata div {
  padding: 0.75rem;
  border-radius: 0.85rem;
  background: rgba(15, 23, 42, 0.55);
}

.phase-inspector-metadata dt {
  font-size: 0.78rem;
  color: rgba(148, 163, 184, 0.9);
}

.phase-inspector-metadata dd {
  margin: 0.2rem 0 0;
  color: #f8fafc;
  font-weight: 600;
}

.phase-inspector-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
}

.phase-inspector-actions .is-danger {
  border-color: rgba(248, 113, 113, 0.36);
  color: #fecaca;
}

.phase-inspector-placeholder {
  margin: 0;
  color: rgba(148, 163, 184, 0.92);
}

@media (max-width: 900px) {
  .phase-inspector-grid,
  .phase-inspector-metadata {
    grid-template-columns: 1fr;
  }
}
</style>
