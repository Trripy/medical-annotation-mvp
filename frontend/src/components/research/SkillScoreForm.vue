<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ResearchSkillCriterion, ResearchSkillScore } from '../../types/researchSkill.ts'
import { buildIntegerScaleOptions, canStoreScoreComment } from '../../utils/researchSkill.ts'
import { criterionTypeLabel } from '../../utils/researchSkillUi.ts'

const props = defineProps<{
  criterion: ResearchSkillCriterion | null
  score: ResearchSkillScore | null
  readonly: boolean
  saving: boolean
}>()

const { t } = useI18n()

const emit = defineEmits<{
  save: [payload: { criterion_id?: number; value?: unknown; is_na?: boolean; comment?: string | null; clear_comment?: boolean }]
  deleteScore: []
}>()

const localValue = ref<unknown>(null)
const localComment = ref('')
const commentTimer = ref<number | null>(null)
const textTimer = ref<number | null>(null)
const pendingTextCriterionId = ref<number | null>(null)
const numericValue = computed({
  get: () => typeof localValue.value === 'number' ? localValue.value : undefined,
  set: (value: number | undefined) => {
    localValue.value = value ?? null
  },
})
const textValue = computed({
  get: () => typeof localValue.value === 'string' ? localValue.value : '',
  set: (value: string) => {
    localValue.value = value
  },
})

const integerOptions = computed(() => props.criterion ? buildIntegerScaleOptions(props.criterion.min_value, props.criterion.max_value, props.criterion.step) : [])
const isNa = computed(() => Boolean(props.score?.is_na))
const canAddComment = computed(() => canStoreScoreComment(props.score, localValue.value, isNa.value))

watch(
  () => [props.criterion?.id ?? null, props.score?.id ?? null],
  () => {
    clearTextTimer()
    clearCommentTimer()
    localValue.value = props.score?.value ?? null
    localComment.value = props.score?.comment ?? ''
  },
  { immediate: true },
)

function saveValue(value: unknown) {
  if (!props.criterion || props.readonly) {
    return
  }
  localValue.value = value
  emit('save', { criterion_id: props.criterion.id, value, is_na: false })
}

function saveNumberValue() {
  if (localValue.value === null || localValue.value === undefined || localValue.value === '') {
    return
  }
  saveValue(Number(localValue.value))
}

function toggleNa(value: boolean) {
  if (!props.criterion || props.readonly) {
    return
  }
  localValue.value = null
  emit('save', { criterion_id: props.criterion.id, value: null, is_na: value })
}

function clearCommentTimer() {
  if (commentTimer.value !== null) {
    window.clearTimeout(commentTimer.value)
    commentTimer.value = null
  }
}

function clearTextTimer() {
  if (textTimer.value !== null) {
    window.clearTimeout(textTimer.value)
    textTimer.value = null
  }
}

function scheduleTextSave(value: string) {
  if (!props.criterion || props.readonly) {
    return
  }
  localValue.value = value
  pendingTextCriterionId.value = props.criterion.id
  clearTextTimer()
  textTimer.value = window.setTimeout(() => {
    emit('save', { criterion_id: pendingTextCriterionId.value ?? props.criterion?.id, value: localValue.value, is_na: false })
    textTimer.value = null
    pendingTextCriterionId.value = null
  }, 600)
}

function flushTextSave() {
  if (textTimer.value === null) {
    return
  }
  window.clearTimeout(textTimer.value)
  emit('save', { criterion_id: pendingTextCriterionId.value ?? props.criterion?.id, value: localValue.value, is_na: false })
  textTimer.value = null
  pendingTextCriterionId.value = null
}

function scheduleCommentSave() {
  if (props.readonly || !props.criterion || !canAddComment.value) {
    return
  }
  clearCommentTimer()
  commentTimer.value = window.setTimeout(() => {
    emit('save', { criterion_id: props.criterion?.id, comment: localComment.value || null })
    commentTimer.value = null
  }, 600)
}

function clearComment() {
  localComment.value = ''
  emit('save', { criterion_id: props.criterion?.id, clear_comment: true })
}

onBeforeUnmount(() => {
  flushTextSave()
  clearCommentTimer()
})
</script>

<template>
  <section class="skill-score-form">
    <div v-if="!criterion" class="skill-empty-panel">
      {{ t('skillAssessment.selectCriterion') }}
    </div>
    <template v-else>
      <header class="skill-score-form-header">
        <div>
          <h3>{{ criterion.name }}</h3>
          <p>{{ criterionTypeLabel(criterion) }} · {{ criterion.required ? t('skillAssessment.required') : t('skillAssessment.optional') }}</p>
        </div>
        <el-tag v-if="score?.is_na" type="warning">N/A</el-tag>
        <el-tag v-else-if="score && score.value !== null && score.value !== undefined" type="success">{{ t('skillAssessment.scored') }}</el-tag>
        <el-tag v-else type="info">{{ t('skillAssessment.missing') }}</el-tag>
      </header>

      <p v-if="criterion.description" class="skill-muted skill-criterion-description">{{ criterion.description }}</p>

      <div class="skill-score-control">
        <template v-if="criterion.score_type === 'integer_scale'">
          <el-button-group v-if="integerOptions.length > 0 && integerOptions.length <= 10">
            <el-button
              v-for="option in integerOptions"
              :key="option"
              :disabled="readonly || saving || isNa"
              :type="localValue === option && !isNa ? 'primary' : 'default'"
              @click="saveValue(option)"
            >
              {{ option }}
            </el-button>
          </el-button-group>
          <el-input-number
            v-else
            v-model="numericValue"
            :disabled="readonly || saving || isNa"
            :min="criterion.min_value ?? undefined"
            :max="criterion.max_value ?? undefined"
            :step="criterion.step ?? 1"
            @change="saveNumberValue"
            @blur="saveNumberValue"
          />
        </template>

        <el-input-number
          v-else-if="criterion.score_type === 'number'"
          v-model="numericValue"
          :disabled="readonly || saving || isNa"
          :min="criterion.min_value ?? undefined"
          :max="criterion.max_value ?? undefined"
          :step="criterion.step ?? 1"
          @change="saveNumberValue"
          @blur="saveNumberValue"
        />

        <div
          v-else-if="criterion.score_type === 'single_choice'"
          class="skill-choice-card-list"
          role="radiogroup"
        >
          <button
            v-for="option in criterion.options_json ?? []"
            :key="option.value"
            type="button"
            class="skill-choice-card"
            :class="{ active: localValue === option.value }"
            :disabled="readonly || saving || isNa"
            role="radio"
            :aria-checked="localValue === option.value"
            @click="saveValue(option.value)"
          >
            <span class="skill-choice-card-score">{{ option.value }}</span>
            <span class="skill-choice-card-label">{{ option.label }}</span>
          </button>
        </div>

        <el-radio-group
          v-else-if="criterion.score_type === 'boolean'"
          :model-value="localValue"
          :disabled="readonly || saving || isNa"
          @change="saveValue"
        >
          <el-radio-button :label="true">{{ t('common.yes') }}</el-radio-button>
          <el-radio-button :label="false">{{ t('common.no') }}</el-radio-button>
        </el-radio-group>

        <el-input
          v-else
          v-model="textValue"
          :disabled="readonly || saving || isNa"
          type="textarea"
          maxlength="5000"
          show-word-limit
          :rows="5"
          :placeholder="t('skillAssessment.enterTextScore')"
          @input="scheduleTextSave(String($event))"
        />
      </div>

      <el-checkbox
        v-if="criterion.allow_na"
        :model-value="isNa"
        :disabled="readonly || saving"
        @change="toggleNa"
      >
        {{ t('common.notApplicable') }}
      </el-checkbox>

      <div class="skill-score-comment">
        <div class="skill-score-comment-heading">
          <label>{{ t('skillAssessment.scoreComment') }}</label>
          <el-button size="small" :disabled="readonly || saving || !score?.comment" @click="clearComment">{{ t('phaseAnnotation.clearNotes') }}</el-button>
        </div>
        <el-input
          v-model="localComment"
          type="textarea"
          :rows="4"
          maxlength="10000"
          :disabled="readonly || saving || !canAddComment"
          :placeholder="t('skillAssessment.scoreCommentPlaceholder')"
          @input="scheduleCommentSave"
        />
      </div>

      <el-button
        v-if="score"
        type="danger"
        plain
        :disabled="readonly || saving"
        @click="emit('deleteScore')"
      >
        {{ t('common.delete') }}
      </el-button>
    </template>
  </section>
</template>

<style scoped>
.skill-score-form {
  display: grid;
  gap: 0.75rem;
}

.skill-score-form-header {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: flex-start;
}

.skill-score-form-header h3 {
  margin: 0;
  color: #e2e8f0;
}

.skill-score-form-header p,
.skill-muted {
  margin: 0.25rem 0 0;
  color: rgba(148, 163, 184, 0.92);
}

.skill-criterion-description {
  padding: 0.62rem;
  border-radius: 0.58rem;
  background: rgba(15, 23, 42, 0.54);
  max-height: 14rem;
  overflow: auto;
  overflow-wrap: anywhere;
  line-height: 1.6;
  white-space: pre-line;
}

.skill-score-control {
  min-width: 0;
}

.skill-choice-card-list {
  display: grid;
  gap: 0.45rem;
  max-height: 22rem;
  overflow: auto;
}

.skill-choice-card {
  display: grid;
  grid-template-columns: 3.4rem minmax(0, 1fr);
  gap: 0.62rem;
  align-items: start;
  width: 100%;
  padding: 0.58rem 0.65rem;
  border-radius: 0.58rem;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.62);
  color: #dbeafe;
  text-align: left;
}

.skill-choice-card.active {
  border-color: rgba(34, 211, 238, 0.58);
  background: rgba(8, 47, 73, 0.8);
  box-shadow: 0 0 0 2px rgba(34, 211, 238, 0.16);
}

.skill-choice-card:disabled {
  cursor: not-allowed;
  opacity: 0.62;
}

.skill-choice-card-score {
  display: inline-flex;
  justify-content: center;
  min-width: 2.4rem;
  padding: 0.22rem 0.42rem;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.82);
  color: #f8fafc;
  font-weight: 800;
}

.skill-choice-card-label {
  min-width: 0;
  overflow-wrap: anywhere;
  line-height: 1.45;
}

.skill-score-comment {
  display: grid;
  gap: 0.5rem;
}

.skill-score-comment-heading {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  align-items: center;
}

.skill-score-comment label {
  color: #cbd5e1;
  font-weight: 700;
}

.skill-empty-panel {
  padding: 1rem;
  border-radius: 1rem;
  color: rgba(203, 213, 225, 0.9);
  background: rgba(15, 23, 42, 0.72);
  border: 1px solid rgba(148, 163, 184, 0.18);
}
</style>
