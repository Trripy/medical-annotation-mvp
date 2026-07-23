<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ResearchSkillEvidence, ResearchSkillPhaseSegment, ResearchSkillScore } from '../../types/researchSkill.ts'
import { getPhaseLabelDisplayName, type SupportedLocale } from '../../utils/locale.ts'

const props = defineProps<{
  frameCount: number
  currentFrameIndex: number
  phaseSegments: ResearchSkillPhaseSegment[]
  score: ResearchSkillScore | null
  pendingStartFrame: number | null
}>()

const emit = defineEmits<{
  seek: [frameIndex: number]
  selectEvidence: [evidence: ResearchSkillEvidence]
}>()

const { locale, t } = useI18n()
const currentLocale = computed(() => locale.value as SupportedLocale)

const timelineWidth = computed(() => Math.max(props.frameCount, 1))

function percent(frame: number) {
  return `${Math.min(100, Math.max(0, (frame / timelineWidth.value) * 100))}%`
}

function onTimelineClick(event: MouseEvent) {
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const ratio = rect.width > 0 ? (event.clientX - rect.left) / rect.width : 0
  emit('seek', Math.min(props.frameCount - 1, Math.max(0, Math.round(ratio * props.frameCount))))
}

function phaseName(segment: ResearchSkillPhaseSegment) {
  return getPhaseLabelDisplayName(
    { phase_key: segment.phase_key, phase_name: segment.phase_name },
    currentLocale.value,
  )
}
</script>

<template>
  <section class="skill-evidence-timeline">
    <header>
      <h3>{{ t('skillAssessment.evidenceTimeline') }}</h3>
      <div class="skill-timeline-actions">
        <el-button size="small">{{ t('skillAssessment.fit') }}</el-button>
        <el-button size="small">{{ t('skillAssessment.zoomIn') }}</el-button>
        <el-button size="small">{{ t('skillAssessment.zoomOut') }}</el-button>
      </div>
    </header>
    <div class="skill-timeline-track" @click="onTimelineClick">
      <div
        v-for="segment in phaseSegments"
        :key="`segment-${segment.id}`"
        class="skill-timeline-phase"
        :style="{
          left: percent(segment.start_frame),
          width: percent((segment.end_frame_exclusive ?? frameCount) - segment.start_frame),
        }"
        :title="`${phaseName(segment)} ${segment.start_frame + 1}-${segment.end_frame_exclusive ?? frameCount}`"
      >
        {{ phaseName(segment) }}
      </div>
      <button
        v-for="evidence in score?.evidence ?? []"
        :key="evidence.id"
        type="button"
        class="skill-timeline-evidence"
        :class="{ point: evidence.end_frame_exclusive === null }"
        :style="{
          left: percent(evidence.start_frame),
          width: evidence.end_frame_exclusive === null ? '0.45rem' : percent(evidence.end_frame_exclusive - evidence.start_frame),
        }"
        @click.stop="emit('selectEvidence', evidence)"
      />
      <div
        v-if="pendingStartFrame !== null"
        class="skill-timeline-pending"
        :style="{ left: percent(pendingStartFrame) }"
      />
      <div class="skill-timeline-playhead" :style="{ left: percent(currentFrameIndex) }" />
    </div>
  </section>
</template>

<style scoped>
.skill-evidence-timeline {
  padding: 1rem;
  border-radius: 1.1rem;
  background: rgba(15, 23, 42, 0.74);
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.skill-evidence-timeline header {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: center;
  margin-bottom: 0.8rem;
}

.skill-evidence-timeline h3 {
  margin: 0;
  color: #e2e8f0;
}

.skill-timeline-actions {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
}

.skill-timeline-track {
  position: relative;
  height: 5rem;
  border-radius: 0.85rem;
  overflow: hidden;
  background: repeating-linear-gradient(90deg, rgba(30, 41, 59, 0.9), rgba(30, 41, 59, 0.9) 10px, rgba(15, 23, 42, 0.92) 10px, rgba(15, 23, 42, 0.92) 20px);
  cursor: pointer;
}

.skill-timeline-phase,
.skill-timeline-evidence,
.skill-timeline-playhead,
.skill-timeline-pending {
  position: absolute;
}

.skill-timeline-phase {
  top: 0.8rem;
  height: 1.6rem;
  min-width: 0.35rem;
  padding: 0 0.35rem;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  border-radius: 999px;
  background: rgba(56, 189, 248, 0.25);
  color: #bae6fd;
  font-size: 0.72rem;
  line-height: 1.6rem;
}

.skill-timeline-evidence {
  bottom: 0.8rem;
  height: 0.8rem;
  min-width: 0.45rem;
  border: 0;
  border-radius: 999px;
  background: #facc15;
  cursor: pointer;
}

.skill-timeline-evidence.point {
  transform: translateX(-50%);
}

.skill-timeline-playhead {
  top: 0;
  bottom: 0;
  width: 2px;
  background: #f8fafc;
}

.skill-timeline-pending {
  top: 0;
  bottom: 0;
  width: 2px;
  background: #fb7185;
}
</style>
