<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ResearchPhaseProtocolDetail, ResearchPhaseProtocolSummary } from '../../types/researchPhase.ts'
import type {
  CreateSkillCriterionRequest,
  ResearchSkillCriterion,
  ResearchSkillRubricDetail,
  ResearchSkillRubricSummary,
} from '../../types/researchSkill.ts'
import { getPhaseProtocolDisplayName, translateStatus, type SupportedLocale } from '../../utils/locale.ts'
import SkillCriterionEditor from './SkillCriterionEditor.vue'

const props = defineProps<{
  modelValue: boolean
  rubrics: ResearchSkillRubricSummary[]
  selectedRubric: ResearchSkillRubricDetail | null
  protocols: ResearchPhaseProtocolSummary[]
  protocolDetail: ResearchPhaseProtocolDetail | null
  currentUsername: string
  loading: boolean
  saving: boolean
}>()

const { locale, t } = useI18n()
const currentLocale = computed(() => locale.value as SupportedLocale)

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  fetchRubrics: [includeArchived: boolean]
  selectRubric: [rubricId: number]
  createRubric: [payload: { name: string; description?: string | null; phase_protocol_id?: number | null; username?: string | null }]
  updateRubric: [rubricId: number, payload: { name?: string; description?: string | null; phase_protocol_id?: number | null; clear_phase_protocol?: boolean }]
  cloneRubric: [rubricId: number]
  activateRubric: [rubricId: number]
  archiveRubric: [rubricId: number]
  saveCriterion: [criterionId: number | null, payload: CreateSkillCriterionRequest]
}>()

const includeArchived = ref(true)
const selectedCriterionId = ref<number | null>(null)
const rubricForm = reactive({
  name: '',
  description: '',
  phase_protocol_id: null as number | null,
})

const selectedCriterion = computed<ResearchSkillCriterion | null>(() => (
  props.selectedRubric?.criteria.find((criterion) => criterion.id === selectedCriterionId.value) ?? null
))
const isRubricReadonly = computed(() => props.selectedRubric?.status !== 'draft')

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      emit('fetchRubrics', includeArchived.value)
    }
  },
)

watch(
  () => props.selectedRubric,
  (rubric) => {
    rubricForm.name = rubric?.name ?? ''
    rubricForm.description = rubric?.description ?? ''
    rubricForm.phase_protocol_id = rubric?.phase_protocol_id ?? null
    selectedCriterionId.value = rubric?.criteria[0]?.id ?? null
  },
  { immediate: true },
)

function createRubric() {
  emit('createRubric', {
    name: rubricForm.name,
    description: rubricForm.description || null,
    phase_protocol_id: rubricForm.phase_protocol_id,
    username: props.currentUsername,
  })
}

function updateRubric() {
  if (!props.selectedRubric) {
    return
  }
  emit('updateRubric', props.selectedRubric.id, {
    name: rubricForm.name,
    description: rubricForm.description || null,
    phase_protocol_id: rubricForm.phase_protocol_id,
    clear_phase_protocol: rubricForm.phase_protocol_id === null,
  })
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="t('rubricManager.title')"
    width="min(1100px, 94vw)"
    class="skill-rubric-dialog"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="skill-rubric-manager">
      <aside class="skill-rubric-list">
        <div class="skill-rubric-toolbar">
          <el-checkbox v-model="includeArchived" @change="emit('fetchRubrics', includeArchived)">{{ t('rubricManager.includeArchived') }}</el-checkbox>
          <el-button size="small" :loading="loading" @click="emit('fetchRubrics', includeArchived)">{{ t('common.refresh') }}</el-button>
        </div>
        <button
          v-for="rubric in rubrics"
          :key="rubric.id"
          type="button"
          class="skill-rubric-choice"
          :class="{ active: selectedRubric?.id === rubric.id }"
          @click="emit('selectRubric', rubric.id)"
        >
          <strong>{{ rubric.name }} v{{ rubric.version }}</strong>
          <span>{{ translateStatus(rubric.status, t) }} · {{ rubric.criterion_count }} {{ t('rubricManager.criteria') }}</span>
        </button>
      </aside>

      <main class="skill-rubric-detail">
        <section class="skill-rubric-card">
          <h3>{{ selectedRubric ? t('skillAssessment.rubric') : t('rubricManager.createDraftRubric') }}</h3>
          <el-input v-model="rubricForm.name" :disabled="isRubricReadonly" :placeholder="t('rubricManager.rubricName')" />
          <el-input v-model="rubricForm.description" :disabled="isRubricReadonly" type="textarea" :rows="2" :placeholder="t('rubricManager.description')" />
          <el-select v-model="rubricForm.phase_protocol_id" :disabled="isRubricReadonly" clearable :placeholder="t('rubricManager.optionalPhaseProtocol')">
            <el-option
              v-for="protocol in protocols"
              :key="protocol.id"
              :label="`${getPhaseProtocolDisplayName(protocol, currentLocale)} v${protocol.version}`"
              :value="protocol.id"
            />
          </el-select>
          <div class="skill-rubric-actions">
            <el-button v-if="!selectedRubric" type="primary" :loading="saving" @click="createRubric">{{ t('rubricManager.createDraftRubric') }}</el-button>
            <el-button v-else type="primary" :disabled="isRubricReadonly" :loading="saving" @click="updateRubric">{{ t('rubricManager.saveRubric') }}</el-button>
            <el-button v-if="selectedRubric" @click="emit('cloneRubric', selectedRubric.id)">{{ t('rubricManager.cloneNewVersion') }}</el-button>
            <el-button v-if="selectedRubric?.status === 'draft'" type="success" @click="emit('activateRubric', selectedRubric.id)">{{ t('rubricManager.activate') }}</el-button>
            <el-button v-if="selectedRubric?.status === 'active'" type="warning" @click="emit('archiveRubric', selectedRubric.id)">{{ t('rubricManager.archive') }}</el-button>
            <el-button @click="selectedCriterionId = null">{{ t('rubricManager.newCriterion') }}</el-button>
          </div>
          <p v-if="selectedRubric?.status === 'active'">{{ t('rubricManager.activeReadonly') }}</p>
          <p v-else-if="selectedRubric?.status === 'archived'">{{ t('rubricManager.archivedReadonly') }}</p>
          <p v-else>{{ t('rubricManager.draftHelp') }}</p>
        </section>

        <section class="skill-rubric-card">
          <h3>{{ t('rubricManager.criteria') }}</h3>
          <div class="skill-criteria-list">
            <button
              v-for="criterion in selectedRubric?.criteria ?? []"
              :key="criterion.id"
              type="button"
              class="skill-criterion-row"
              :class="{ active: selectedCriterionId === criterion.id }"
              @click="selectedCriterionId = criterion.id"
            >
              <strong>{{ criterion.display_order }} · {{ criterion.name }}</strong>
              <span>{{ translateStatus(criterion.scope, t) }} · {{ criterion.score_type }} · {{ criterion.is_active ? t('status.active') : t('status.inactive') }}</span>
            </button>
          </div>
        </section>

        <section class="skill-rubric-card">
          <SkillCriterionEditor
            :rubric="selectedRubric"
            :criterion="selectedCriterion"
            :protocol="protocolDetail"
            :readonly="isRubricReadonly || !selectedRubric"
            :saving="saving"
            @save="(criterionId, payload) => emit('saveCriterion', criterionId, payload)"
          />
        </section>
      </main>
    </div>
  </el-dialog>
</template>

<style scoped>
.skill-rubric-manager {
  display: grid;
  grid-template-columns: minmax(220px, 0.9fr) minmax(0, 2fr);
  gap: 1rem;
  max-height: 72vh;
  overflow: hidden;
}

.skill-rubric-list,
.skill-rubric-detail {
  min-height: 0;
  overflow: auto;
}

.skill-rubric-list,
.skill-rubric-detail,
.skill-rubric-card {
  display: grid;
  gap: 0.75rem;
}

.skill-rubric-card {
  padding: 1rem;
  border-radius: 1rem;
  background: rgba(15, 23, 42, 0.08);
  border: 1px solid rgba(148, 163, 184, 0.22);
}

.skill-rubric-toolbar,
.skill-rubric-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}

.skill-rubric-choice,
.skill-criterion-row {
  display: grid;
  gap: 0.2rem;
  width: 100%;
  padding: 0.7rem;
  border-radius: 0.8rem;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: #fff;
  text-align: left;
  cursor: pointer;
}

.skill-rubric-choice.active,
.skill-criterion-row.active {
  border-color: #0891b2;
  background: #ecfeff;
}

.skill-rubric-choice span,
.skill-criterion-row span,
.skill-rubric-card p {
  color: #64748b;
}

@media (max-width: 760px) {
  .skill-rubric-manager {
    grid-template-columns: 1fr;
  }
}
</style>
