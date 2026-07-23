<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type {
  ResearchSkillAssessmentDetail,
  ResearchSkillAssessmentSummary,
  ResearchSkillCriterion,
  ResearchSkillPhaseSegment,
  ResearchSkillValidationResponse,
} from '../../types/researchSkill.ts'
import {
  buildPhaseSegmentOccurrences,
  findSkillScore,
  getApplicableCriteria,
  isSkillScoreComplete,
} from '../../utils/researchSkill.ts'
import { getPhaseLabelDisplayName, translateStatus, type SupportedLocale } from '../../utils/locale.ts'
import { formatSkillFrameRange } from '../../utils/researchSkillUi.ts'

const props = defineProps<{
  assessments: ResearchSkillAssessmentSummary[]
  currentAssessment: ResearchSkillAssessmentDetail | null
  validation: ResearchSkillValidationResponse | null
  selectedAssessmentId: number | null
  selectedTargetType: 'overall' | 'phase_segment'
  selectedPhaseSegmentId: number | null
  selectedCriterionId: number | null
}>()

const { locale, t } = useI18n()
const currentLocale = computed(() => locale.value as SupportedLocale)

const emit = defineEmits<{
  selectAssessment: [assessmentId: number]
  createAssessment: []
  openRubrics: []
  selectOverall: []
  selectPhaseSegment: [segmentId: number]
  selectCriterion: [criterionId: number]
}>()

const phaseSegments = computed(() => buildPhaseSegmentOccurrences(props.currentAssessment?.phase_annotation_set?.segments ?? []))
const activeOverallCriteria = computed(() => getApplicableCriteria(props.currentAssessment, 'overall', null))
const activePhaseCriteria = computed(() => {
  const segment = phaseSegments.value.find((item) => item.id === props.selectedPhaseSegmentId) ?? null
  return getApplicableCriteria(props.currentAssessment, 'phase', segment)
})
const visibleCriteria = computed(() => props.selectedTargetType === 'overall' ? activeOverallCriteria.value : activePhaseCriteria.value)

function criterionCompleted(criterion: ResearchSkillCriterion, segment: ResearchSkillPhaseSegment | null) {
  const score = findSkillScore(
    props.currentAssessment?.scores ?? [],
    criterion.id,
    criterion.scope === 'overall' ? 'overall' : 'phase_segment',
    segment?.id ?? null,
  )
  return isSkillScoreComplete(score)
}

function segmentCompletion(segment: ResearchSkillPhaseSegment) {
  const criteria = getApplicableCriteria(props.currentAssessment, 'phase', segment)
  if (criteria.length === 0) {
    return t('skillAssessment.noCriteria')
  }
  const completed = criteria.filter((criterion) => criterionCompleted(criterion, segment)).length
  return `${completed}/${criteria.length}`
}

function localizedPhaseSegmentLabel(segment: ResearchSkillPhaseSegment & { occurrence?: number }) {
  const label = getPhaseLabelDisplayName(
    { phase_key: segment.phase_key, phase_name: segment.phase_name },
    currentLocale.value,
  )
  return `${label}${segment.occurrence ? ` #${segment.occurrence}` : ''}`
}
</script>

<template>
  <aside class="skill-assessment-nav">
    <section class="skill-nav-card">
      <div class="skill-nav-heading">
        <div>
          <h3>{{ t('skillAssessment.assessments') }}</h3>
          <p>{{ t('skillAssessment.assessmentCount', { count: assessments.length }) }}</p>
        </div>
        <el-button size="small" type="primary" @click="emit('createAssessment')">{{ t('common.create') }}</el-button>
      </div>
      <button
        v-for="assessment in assessments"
        :key="assessment.id"
        type="button"
        class="skill-assessment-choice"
        :class="{ active: selectedAssessmentId === assessment.id }"
        @click="emit('selectAssessment', assessment.id)"
      >
        <strong>{{ assessment.rubric_name }} v{{ assessment.rubric_version }}</strong>
        <span>{{ assessment.rater_username }} · {{ translateStatus(assessment.status, t) }} · {{ t('skillAssessment.scoreCount', { count: assessment.score_count }) }}</span>
      </button>
      <el-button class="skill-wide-button" @click="emit('openRubrics')">{{ t('rubricManager.title') }}</el-button>
    </section>

    <section v-if="currentAssessment" class="skill-nav-card">
      <h3>{{ currentAssessment.rubric.name }} v{{ currentAssessment.rubric.version }}</h3>
      <p>{{ t('phaseAnnotation.status') }} {{ translateStatus(currentAssessment.status, t) }} · {{ t('phaseAnnotation.revision') }} {{ currentAssessment.revision }}</p>
      <el-progress :percentage="Math.round(currentAssessment.completion.completion_percent)" :stroke-width="8" />
      <p>
        {{ t('skillAssessment.required') }} {{ currentAssessment.completion.required_completed }}/{{ currentAssessment.completion.required_total }}
        · {{ t('phaseAnnotation.errors') }} {{ validation?.issue_counts.error ?? 0 }}
        · {{ t('phaseAnnotation.warnings') }} {{ validation?.issue_counts.warning ?? 0 }}
      </p>
    </section>

    <section v-if="currentAssessment" class="skill-nav-card">
      <button
        type="button"
        class="skill-target-choice"
        :class="{ active: selectedTargetType === 'overall' }"
        @click="emit('selectOverall')"
      >
        <strong>{{ t('skillAssessment.overall') }}</strong>
        <span>{{ activeOverallCriteria.filter((criterion) => criterionCompleted(criterion, null)).length }}/{{ activeOverallCriteria.length }} {{ t('skillAssessment.complete') }}</span>
      </button>
      <h4>{{ t('skillAssessment.phaseSegments') }}</h4>
      <button
        v-for="segment in phaseSegments"
        :key="segment.id"
        type="button"
        class="skill-target-choice"
        :class="{ active: selectedPhaseSegmentId === segment.id }"
        @click="emit('selectPhaseSegment', segment.id)"
      >
        <strong>{{ localizedPhaseSegmentLabel(segment) }}</strong>
        <span>{{ formatSkillFrameRange(segment.start_frame, segment.end_frame_exclusive) }} · {{ segmentCompletion(segment) }}</span>
      </button>
      <p v-if="phaseSegments.length === 0" class="skill-muted">
        {{ t('skillAssessment.matchingPhaseSetRequired') }}
      </p>
    </section>

    <section v-if="currentAssessment" class="skill-nav-card">
      <h3>{{ t('skillAssessment.criteria') }}</h3>
      <button
        v-for="criterion in visibleCriteria"
        :key="criterion.id"
        type="button"
        class="skill-criterion-choice"
        :class="{ active: selectedCriterionId === criterion.id, complete: criterionCompleted(criterion, phaseSegments.find((segment) => segment.id === selectedPhaseSegmentId) ?? null) }"
        @click="emit('selectCriterion', criterion.id)"
      >
        <strong>{{ criterion.name }}</strong>
        <span>{{ criterion.required ? t('skillAssessment.required') : t('skillAssessment.optional') }} · {{ criterion.score_type }}</span>
      </button>
      <p v-if="visibleCriteria.length === 0" class="skill-muted">
        {{ t('skillAssessment.noCriteriaForTarget') }}
      </p>
    </section>
  </aside>
</template>

<style scoped>
.skill-assessment-nav {
  display: grid;
  gap: 1rem;
  align-content: start;
}

.skill-nav-card {
  display: grid;
  gap: 0.7rem;
  padding: 1rem;
  border-radius: 1.1rem;
  background: rgba(15, 23, 42, 0.78);
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.skill-nav-heading {
  display: flex;
  justify-content: space-between;
  gap: 0.8rem;
  align-items: center;
}

.skill-nav-card h3,
.skill-nav-card h4 {
  margin: 0;
  color: #e2e8f0;
}

.skill-nav-card p,
.skill-muted {
  margin: 0;
  color: rgba(148, 163, 184, 0.9);
  font-size: 0.88rem;
}

.skill-assessment-choice,
.skill-target-choice,
.skill-criterion-choice {
  width: 100%;
  display: grid;
  gap: 0.2rem;
  padding: 0.75rem;
  border-radius: 0.85rem;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(30, 41, 59, 0.64);
  color: #cbd5e1;
  text-align: left;
  cursor: pointer;
}

.skill-assessment-choice.active,
.skill-target-choice.active,
.skill-criterion-choice.active {
  border-color: rgba(34, 211, 238, 0.5);
  background: rgba(8, 47, 73, 0.8);
  color: #ecfeff;
}

.skill-criterion-choice.complete strong::after {
  content: ' ✓';
  color: #22c55e;
}

.skill-assessment-choice span,
.skill-target-choice span,
.skill-criterion-choice span {
  color: rgba(148, 163, 184, 0.92);
  font-size: 0.82rem;
}

.skill-wide-button {
  width: 100%;
}
</style>
