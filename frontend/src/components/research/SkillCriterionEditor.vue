<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { CreateSkillCriterionRequest, ResearchSkillCriterion, ResearchSkillRubricDetail } from '../../types/researchSkill.ts'
import type { ResearchPhaseProtocolDetail } from '../../types/researchPhase.ts'
import { getPhaseLabelDisplayName, type SupportedLocale } from '../../utils/locale.ts'

const props = defineProps<{
  rubric: ResearchSkillRubricDetail | null
  criterion: ResearchSkillCriterion | null
  protocol: ResearchPhaseProtocolDetail | null
  readonly: boolean
  saving: boolean
}>()

const { locale, t } = useI18n()
const currentLocale = computed(() => locale.value as SupportedLocale)

const emit = defineEmits<{
  save: [criterionId: number | null, payload: CreateSkillCriterionRequest]
}>()

const form = reactive<CreateSkillCriterionRequest>({
  key: '',
  name: '',
  description: null,
  scope: 'overall',
  score_type: 'integer_scale',
  min_value: 1,
  max_value: 5,
  step: 1,
  options_json: null,
  required: false,
  allow_na: false,
  weight: null,
  display_order: 0,
  is_active: true,
  phase_label_ids: [],
})

const canUsePhase = computed(() => Boolean(props.rubric?.phase_protocol_id))

watch(
  () => props.criterion,
  (criterion) => {
    if (!criterion) {
      Object.assign(form, {
        key: '',
        name: '',
        description: null,
        scope: 'overall',
        score_type: 'integer_scale',
        min_value: 1,
        max_value: 5,
        step: 1,
        options_json: null,
        required: false,
        allow_na: false,
        weight: null,
        display_order: props.rubric?.criteria.length ?? 0,
        is_active: true,
        phase_label_ids: [],
      })
      return
    }
    Object.assign(form, {
      key: criterion.key,
      name: criterion.name,
      description: criterion.description,
      scope: criterion.scope,
      score_type: criterion.score_type,
      min_value: criterion.min_value,
      max_value: criterion.max_value,
      step: criterion.step,
      options_json: criterion.options_json ? criterion.options_json.map((option) => ({ ...option })) : null,
      required: criterion.required,
      allow_na: criterion.allow_na,
      weight: criterion.weight,
      display_order: criterion.display_order,
      is_active: criterion.is_active,
      phase_label_ids: criterion.phase_label_ids.slice(),
    })
  },
  { immediate: true },
)

function addOption() {
  form.options_json = [...(form.options_json ?? []), { value: '', label: '' }]
}

function removeOption(index: number) {
  form.options_json = (form.options_json ?? []).filter((_option, optionIndex) => optionIndex !== index)
}

function normalizeForType() {
  if (form.scope === 'overall') {
    form.phase_label_ids = []
  }
  if (form.score_type === 'integer_scale') {
    form.min_value ??= 1
    form.max_value ??= 5
    form.step ??= 1
    form.options_json = null
  } else if (form.score_type === 'number') {
    form.options_json = null
  } else if (form.score_type === 'single_choice') {
    form.min_value = null
    form.max_value = null
    form.step = null
    form.options_json ??= [
      { value: 'option_1', label: t('skillAssessment.defaultOptionOne') },
      { value: 'option_2', label: t('skillAssessment.defaultOptionTwo') },
    ]
  } else {
    form.min_value = null
    form.max_value = null
    form.step = null
    form.options_json = null
  }
}

function submit() {
  normalizeForType()
  emit('save', props.criterion?.id ?? null, {
    ...form,
    description: form.description || null,
    options_json: form.options_json?.map((option) => ({ value: option.value.trim(), label: option.label.trim() })) ?? null,
    phase_label_ids: form.scope === 'phase' ? form.phase_label_ids ?? [] : [],
  })
}
</script>

<template>
  <section class="skill-criterion-editor">
    <h3>{{ criterion ? t('common.edit') : t('rubricManager.criterion') }}</h3>
    <div class="skill-editor-grid">
      <el-input v-model="form.key" :disabled="readonly || Boolean(criterion)" :placeholder="t('rubricManager.key')" />
      <el-input v-model="form.name" :disabled="readonly" :placeholder="t('rubricManager.name')" />
      <el-input v-model="form.description" :disabled="readonly" :placeholder="t('rubricManager.description')" />
      <el-input-number v-model="form.display_order" :disabled="readonly" :min="0" :placeholder="t('rubricManager.displayOrder')" />
      <el-select v-model="form.scope" :disabled="readonly || Boolean(criterion)" @change="normalizeForType">
        <el-option :label="t('rubricManager.overall')" value="overall" />
        <el-option :label="t('rubricManager.phase')" value="phase" :disabled="!canUsePhase" />
      </el-select>
      <el-select v-model="form.score_type" :disabled="readonly || Boolean(criterion)" @change="normalizeForType">
        <el-option :label="t('rubricManager.integerScale')" value="integer_scale" />
        <el-option :label="t('rubricManager.number')" value="number" />
        <el-option :label="t('rubricManager.singleChoice')" value="single_choice" />
        <el-option :label="t('rubricManager.boolean')" value="boolean" />
        <el-option :label="t('rubricManager.text')" value="text" />
      </el-select>
      <el-input-number v-if="form.score_type === 'integer_scale' || form.score_type === 'number'" v-model="form.min_value" :disabled="readonly" :placeholder="t('rubricManager.minimum')" />
      <el-input-number v-if="form.score_type === 'integer_scale' || form.score_type === 'number'" v-model="form.max_value" :disabled="readonly" :placeholder="t('rubricManager.maximum')" />
      <el-input-number v-if="form.score_type === 'integer_scale' || form.score_type === 'number'" v-model="form.step" :disabled="readonly" :min="0" :placeholder="t('rubricManager.step')" />
      <el-input-number v-model="form.weight" :disabled="readonly" :min="0" :placeholder="t('rubricManager.weight')" />
    </div>
    <div class="skill-editor-flags">
      <el-checkbox v-model="form.required" :disabled="readonly">{{ t('skillAssessment.required') }}</el-checkbox>
      <el-checkbox v-model="form.allow_na" :disabled="readonly">{{ t('rubricManager.allowNa') }}</el-checkbox>
      <el-checkbox v-model="form.is_active" :disabled="readonly">{{ t('rubricManager.active') }}</el-checkbox>
    </div>
    <div v-if="form.scope === 'phase'" class="skill-editor-block">
      <label>{{ t('rubricManager.phaseLabels') }}</label>
      <el-select v-model="form.phase_label_ids" multiple :disabled="readonly" :placeholder="t('rubricManager.allPhaseLabels')">
        <el-option
          v-for="label in protocol?.labels ?? []"
          :key="label.id"
          :label="getPhaseLabelDisplayName(label, currentLocale)"
          :value="label.id"
        />
      </el-select>
      <p>{{ t('rubricManager.allPhaseLabelsHelp') }}</p>
    </div>
    <div v-if="form.score_type === 'single_choice'" class="skill-editor-block">
      <label>{{ t('rubricManager.options') }}</label>
      <div v-for="(_option, index) in form.options_json ?? []" :key="index" class="skill-option-row">
        <el-input v-model="(form.options_json ?? [])[index].value" :disabled="readonly" :placeholder="t('rubricManager.optionValue')" />
        <el-input v-model="(form.options_json ?? [])[index].label" :disabled="readonly" :placeholder="t('rubricManager.optionLabel')" />
        <el-button :disabled="readonly" @click="removeOption(index)">{{ t('rubricManager.remove') }}</el-button>
      </div>
      <el-button :disabled="readonly" @click="addOption">{{ t('rubricManager.addOption') }}</el-button>
    </div>
    <el-button type="primary" :loading="saving" :disabled="readonly || !form.key.trim() || !form.name.trim()" @click="submit">
      {{ t('common.save') }}
    </el-button>
  </section>
</template>

<style scoped>
.skill-criterion-editor {
  display: grid;
  gap: 0.8rem;
}

.skill-criterion-editor h3,
.skill-editor-block label {
  margin: 0;
  color: #e2e8f0;
  font-weight: 800;
}

.skill-editor-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.6rem;
}

.skill-editor-flags,
.skill-option-row {
  display: flex;
  gap: 0.6rem;
  flex-wrap: wrap;
  align-items: center;
}

.skill-editor-block {
  display: grid;
  gap: 0.45rem;
}

.skill-editor-block p {
  margin: 0;
  color: rgba(148, 163, 184, 0.9);
}
</style>
