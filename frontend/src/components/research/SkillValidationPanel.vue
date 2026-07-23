<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ResearchSkillValidationIssue, ResearchSkillValidationResponse } from '../../types/researchSkill.ts'
import { formatPercent, translateSkillValidationIssue, translateStatus, type SupportedLocale } from '../../utils/locale.ts'

defineProps<{
  validation: ResearchSkillValidationResponse | null
  validating: boolean
}>()

const { locale, t } = useI18n()
const currentLocale = computed(() => locale.value as SupportedLocale)

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
          {{ t('skillAssessment.required') }} {{ validation.required_completed }}/{{ validation.required_total }}
          · {{ formatPercent(validation.completion_percent, currentLocale) }}
          · {{ t('phaseAnnotation.errors') }} {{ validation.issue_counts.error }}
          · {{ t('phaseAnnotation.warnings') }} {{ validation.issue_counts.warning }}
        </p>
        <p v-else>{{ t('phaseAnnotation.validationPending') }}</p>
      </div>
      <el-button size="small" :loading="validating" @click="emit('validate')">{{ t('common.validate') }}</el-button>
    </header>

    <div v-if="!validation" class="skill-empty-panel">{{ t('skillAssessment.runValidation') }}</div>
    <div v-else-if="validation.issues.length === 0" class="skill-empty-panel success">{{ t('skillAssessment.noValidationIssues') }}</div>
    <button
      v-for="issue in validation?.issues ?? []"
      :key="`${issue.issue_type}-${issue.criterion_id}-${issue.score_id}-${issue.phase_segment_id}-${issue.evidence_id}`"
      type="button"
      class="skill-validation-issue"
      :class="issue.severity"
      @click="emit('issue', issue)"
    >
      <strong>{{ translateStatus(issue.severity, t) }} · {{ issue.issue_type }}</strong>
      <span>{{ translateSkillValidationIssue(issue, t) }}</span>
    </button>
  </section>
</template>

<style scoped>
.skill-validation-panel {
  display: grid;
  gap: 0.8rem;
  padding: 1rem;
  border-radius: 1.1rem;
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
  padding: 0.75rem;
  border-radius: 0.85rem;
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

.skill-validation-issue.error {
  border-color: rgba(248, 113, 113, 0.45);
}

.skill-validation-issue.warning {
  border-color: rgba(250, 204, 21, 0.45);
}

.skill-validation-issue span {
  color: rgba(203, 213, 225, 0.9);
}
</style>
