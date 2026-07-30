<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ResearchSkillValidationIssue, ResearchSkillValidationResponse } from '../../types/researchSkill.ts'
import { formatPercent, translateSkillValidationIssue, translateStatus, type SupportedLocale } from '../../utils/locale.ts'
import { compactSkillValidationIssues, summarizeSkillValidation } from '../../utils/researchWorkflowUi.ts'

const props = defineProps<{
  validation: ResearchSkillValidationResponse | null
  validating: boolean
}>()

const { locale, t } = useI18n()
const currentLocale = computed(() => locale.value as SupportedLocale)
const showDetails = ref(false)
const summary = computed(() => summarizeSkillValidation(props.validation))
const compactIssues = computed(() => compactSkillValidationIssues(summary.value.issues))

const emit = defineEmits<{
  validate: []
  issue: [issue: ResearchSkillValidationIssue]
}>()
</script>

<template>
  <section class="skill-validation-panel">
    <header>
      <div>
        <h3>{{ t('skillAssessment.validation') }}</h3>
        <p v-if="validation">
          {{ t('skillAssessment.required') }} {{ summary.requiredCompleted }}/{{ summary.requiredTotal }}
          · {{ formatPercent(summary.completionPercent, currentLocale) }}
          · {{ t('phaseAnnotation.errors') }} {{ summary.errors }}
          · {{ t('phaseAnnotation.warnings') }} {{ summary.warnings }}
        </p>
        <p v-else>{{ t('phaseAnnotation.validationPending') }}</p>
      </div>
      <el-button size="small" :loading="validating" @click="emit('validate')">{{ t('common.validate') }}</el-button>
    </header>

    <div class="skill-validation-summary-grid" v-if="validation">
      <article>
        <strong>{{ summary.requiredCompleted }}/{{ summary.requiredTotal }}</strong>
        <span>{{ t('skillAssessment.required') }}</span>
      </article>
      <article>
        <strong>{{ summary.errors }}</strong>
        <span>{{ t('phaseAnnotation.errors') }}</span>
      </article>
      <article>
        <strong>{{ summary.warnings }}</strong>
        <span>{{ t('phaseAnnotation.warnings') }}</span>
      </article>
      <article>
        <strong>{{ formatPercent(summary.completionPercent, currentLocale) }}</strong>
        <span>{{ t('skillAssessment.complete') }}</span>
      </article>
    </div>

    <div v-if="!validation" class="skill-empty-panel">{{ t('skillAssessment.runValidation') }}</div>
    <div v-else-if="validation.issues.length === 0" class="skill-empty-panel success">{{ t('skillAssessment.noValidationIssues') }}</div>
    <template v-else>
      <button class="skill-validation-detail-toggle" type="button" @click="showDetails = !showDetails">
        {{ showDetails ? t('frameAnnotation.collapse') : t('frameAnnotation.expand') }}
        {{ compactIssues.length }}
      </button>
      <div v-if="showDetails" class="skill-validation-issue-list">
        <button
          v-for="issue in compactIssues"
          :key="`${issue.issue_type}-${issue.criterion_id}-${issue.score_id}-${issue.phase_segment_id}-${issue.evidence_id}`"
          type="button"
          class="skill-validation-issue"
          :class="issue.severity"
          @click="emit('issue', issue)"
        >
          <strong>{{ translateStatus(issue.severity, t) }} · {{ issue.issue_type }}<span v-if="issue.issueCount > 1"> x{{ issue.issueCount }}</span></strong>
          <span>{{ translateSkillValidationIssue(issue, t) }}</span>
        </button>
      </div>
    </template>
  </section>
</template>

<style scoped>
.skill-validation-panel {
  display: grid;
  gap: 0.62rem;
  padding: 0.78rem;
  border-radius: 0.72rem;
  background: rgba(15, 23, 42, 0.78);
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.skill-validation-panel header {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: center;
}

.skill-validation-panel h3,
.skill-validation-panel p {
  margin: 0;
}

.skill-validation-panel h3 {
  color: #e2e8f0;
}

.skill-validation-panel p {
  color: rgba(148, 163, 184, 0.9);
}

.skill-empty-panel,
.skill-validation-issue {
  padding: 0.58rem;
  border-radius: 0.58rem;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(30, 41, 59, 0.64);
  color: #cbd5e1;
}

.skill-empty-panel.success {
  border-color: rgba(34, 197, 94, 0.32);
  color: #bbf7d0;
}

.skill-validation-issue {
  display: grid;
  gap: 0.2rem;
  width: 100%;
  text-align: left;
  cursor: pointer;
}

.skill-validation-summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.5rem;
}

.skill-validation-summary-grid article {
  display: grid;
  gap: 0.1rem;
  padding: 0.58rem;
  border-radius: 0.58rem;
  background: rgba(15, 23, 42, 0.58);
}

.skill-validation-summary-grid strong {
  color: #e2e8f0;
}

.skill-validation-summary-grid span {
  color: rgba(148, 163, 184, 0.9);
  font-size: 0.78rem;
}

.skill-validation-detail-toggle {
  justify-self: end;
  padding: 0.42rem 0.68rem;
  border-radius: 0.55rem;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(30, 41, 59, 0.78);
  color: #e2e8f0;
}

.skill-validation-issue-list {
  display: grid;
  gap: 0.42rem;
  max-height: 260px;
  overflow: auto;
}

.skill-validation-issue.error {
  border-color: rgba(248, 113, 113, 0.45);
}

.skill-validation-issue.warning {
  border-color: rgba(250, 204, 21, 0.45);
}

.skill-validation-issue span {
  color: rgba(203, 213, 225, 0.9);
}

@media (max-width: 760px) {
  .skill-validation-summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
