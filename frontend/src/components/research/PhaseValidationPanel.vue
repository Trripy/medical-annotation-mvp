<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type {
  ResearchPhaseAnnotationSetStatus,
  ResearchPhaseValidationIssue,
  ResearchPhaseValidationResponse,
} from '../../types/researchPhase'
import { formatPercent, translatePhaseValidationIssue, translateStatus, type SupportedLocale } from '../../utils/locale'

const props = defineProps<{
  currentStatus: ResearchPhaseAnnotationSetStatus | null
  validation: ResearchPhaseValidationResponse | null
}>()

const { locale, t } = useI18n()
const currentLocale = computed(() => locale.value as SupportedLocale)

const emit = defineEmits<{
  goToIssue: [issue: ResearchPhaseValidationIssue]
  mergeIssue: [issue: ResearchPhaseValidationIssue]
  closeAtCurrent: [issue: ResearchPhaseValidationIssue]
  closeAtVideoEnd: [issue: ResearchPhaseValidationIssue]
}>()

function formatFrameRange(issue: ResearchPhaseValidationIssue) {
  if (issue.frame_start === null && issue.frame_end_exclusive === null) {
    return t('common.noFrameSelected')
  }
  if (issue.frame_start !== null && issue.frame_end_exclusive !== null) {
    return `${t('common.frames')} ${issue.frame_start + 1}-${issue.frame_end_exclusive}`
  }
  if (issue.frame_start !== null) {
    return `${t('common.frame')} ${issue.frame_start + 1}`
  }
  return `${t('phaseAnnotation.endFrameInclusive')} ${issue.frame_end_exclusive}`
}
</script>

<template>
  <section class="phase-validation">
    <header class="phase-validation-header">
      <div>
        <p class="phase-validation-eyebrow">{{ t('phaseAnnotation.qcValidate') }}</p>
        <h3>{{ t('phaseAnnotation.validationSummary') }}</h3>
      </div>
      <span class="phase-validation-status">{{ translateStatus(currentStatus ?? 'draft', t) }}</span>
    </header>

    <template v-if="validation">
      <div class="phase-validation-summary-grid">
        <article>
          <strong>{{ validation.issue_counts.error }}</strong>
          <span>{{ t('phaseAnnotation.errors') }}</span>
        </article>
        <article>
          <strong>{{ validation.issue_counts.warning }}</strong>
          <span>{{ t('phaseAnnotation.warnings') }}</span>
        </article>
        <article>
          <strong>{{ formatPercent(validation.closed_coverage_percent, currentLocale) }}</strong>
          <span>{{ t('phaseAnnotation.coverage') }}</span>
        </article>
        <article>
          <strong>{{ validation.closed_segment_count }}</strong>
          <span>{{ t('phaseAnnotation.closed') }}</span>
        </article>
        <article>
          <strong>{{ validation.open_segment_count }}</strong>
          <span>{{ t('phaseAnnotation.open') }}</span>
        </article>
      </div>

      <ul class="phase-validation-issues">
        <li v-for="issue in validation.issues" :key="`${issue.issue_type}-${issue.segment_id}-${issue.related_segment_id}-${issue.frame_start}`">
          <div class="phase-validation-issue-main">
            <span class="phase-validation-severity" :class="`is-${issue.severity}`">{{ translateStatus(issue.severity, t) }}</span>
            <div>
              <strong>{{ translatePhaseValidationIssue(issue, t) }}</strong>
              <p>{{ formatFrameRange(issue) }}</p>
            </div>
          </div>
          <div class="phase-validation-issue-actions">
            <button type="button" @click="emit('goToIssue', issue)">{{ t('common.go') }}</button>
            <button
              v-if="issue.issue_type === 'adjacent_same_label'"
              type="button"
              @click="emit('mergeIssue', issue)"
            >
              {{ t('phaseAnnotation.mergeNext') }}
            </button>
            <button
              v-if="issue.issue_type === 'open_segment'"
              type="button"
              @click="emit('closeAtCurrent', issue)"
            >
              {{ t('phaseAnnotation.closeAtCurrentFrame') }}
            </button>
            <button
              v-if="issue.issue_type === 'open_segment'"
              type="button"
              @click="emit('closeAtVideoEnd', issue)"
            >
              {{ t('phaseAnnotation.closeAtVideoEnd') }}
            </button>
          </div>
        </li>
      </ul>
    </template>

    <p v-else class="phase-validation-placeholder">
      {{ t('phaseAnnotation.validationPending') }}
    </p>
  </section>
</template>

<style scoped>
.phase-validation {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1rem;
  border-radius: 1rem;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.84);
}

.phase-validation-header {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: flex-start;
}

.phase-validation-eyebrow {
  margin: 0 0 0.2rem;
  font-size: 0.78rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(125, 211, 252, 0.84);
}

.phase-validation-header h3,
.phase-validation-summary-grid strong,
.phase-validation-issue-main strong {
  color: #f8fafc;
}

.phase-validation-summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.75rem;
}

.phase-validation-summary-grid article {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  padding: 0.8rem;
  border-radius: 0.85rem;
  background: rgba(15, 23, 42, 0.56);
}

.phase-validation-summary-grid span,
.phase-validation-issue-main p,
.phase-validation-placeholder,
.phase-validation-status {
  color: rgba(148, 163, 184, 0.92);
}

.phase-validation-status {
  padding: 0.45rem 0.75rem;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  text-transform: capitalize;
}

.phase-validation-issues {
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: 420px;
  overflow: auto;
}

.phase-validation-issues li {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.85rem;
  border-radius: 0.85rem;
  background: rgba(15, 23, 42, 0.56);
}

.phase-validation-issue-main {
  display: flex;
  gap: 0.75rem;
}

.phase-validation-issue-main p {
  margin: 0.3rem 0 0;
}

.phase-validation-severity {
  min-width: 4.8rem;
  height: fit-content;
  padding: 0.35rem 0.6rem;
  border-radius: 999px;
  text-align: center;
  font-size: 0.78rem;
  text-transform: uppercase;
  font-weight: 700;
}

.phase-validation-severity.is-error {
  background: rgba(127, 29, 29, 0.52);
  color: #fecaca;
}

.phase-validation-severity.is-warning {
  background: rgba(120, 53, 15, 0.5);
  color: #fde68a;
}

.phase-validation-severity.is-info {
  background: rgba(8, 47, 73, 0.6);
  color: #bae6fd;
}

.phase-validation-issue-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.phase-validation-issue-actions button {
  padding: 0.55rem 0.8rem;
  border-radius: 0.75rem;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(30, 41, 59, 0.82);
  color: #e2e8f0;
}

@media (max-width: 900px) {
  .phase-validation-summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .phase-validation-issues li {
    flex-direction: column;
  }
}
</style>
