<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ResearchSkillEvidence, ResearchSkillScore } from '../../types/researchSkill.ts'
import { sortSkillEvidence } from '../../utils/researchSkill.ts'
import { formatEvidenceRange, formatSkillTime } from '../../utils/researchSkillUi.ts'

const props = defineProps<{
  score: ResearchSkillScore | null
  currentFrameIndex: number
  fps: number | null | undefined
  readonly: boolean
  saving: boolean
}>()

const { t } = useI18n()

const emit = defineEmits<{
  addPoint: []
  startInterval: []
  finishInterval: []
  cancelInterval: []
  goEvidence: [evidence: ResearchSkillEvidence]
  updateEvidence: [evidenceId: number, payload: { start_frame?: number; end_frame_exclusive?: number | null; clear_end_frame?: boolean; comment?: string | null; clear_comment?: boolean }]
  deleteEvidence: [evidenceId: number]
}>()

const pendingStartFrame = defineModel<number | null>('pendingStartFrame', { required: true })
const editingEvidenceId = ref<number | null>(null)
const editStartFrame = ref('')
const editEndFrame = ref('')
const editComment = ref('')

const sortedEvidence = computed(() => sortSkillEvidence(props.score?.evidence ?? []))
const canAddEvidence = computed(() => Boolean(props.score) && !props.readonly && !props.saving)

function beginEdit(evidence: ResearchSkillEvidence) {
  editingEvidenceId.value = evidence.id
  editStartFrame.value = String(evidence.start_frame + 1)
  editEndFrame.value = evidence.end_frame_exclusive === null ? '' : String(evidence.end_frame_exclusive)
  editComment.value = evidence.comment ?? ''
}

function saveEdit(evidence: ResearchSkillEvidence) {
  const startFrame = Number.parseInt(editStartFrame.value, 10)
  const endFrame = editEndFrame.value.trim() ? Number.parseInt(editEndFrame.value, 10) : null
  if (!Number.isInteger(startFrame) || startFrame < 1) {
    return
  }
  emit('updateEvidence', evidence.id, {
    start_frame: startFrame - 1,
    end_frame_exclusive: endFrame,
    clear_end_frame: endFrame === null,
    comment: editComment.value || null,
  })
  editingEvidenceId.value = null
}
</script>

<template>
  <section class="skill-evidence-panel">
    <header>
      <div>
        <h3>{{ t('skillAssessment.evidence') }}</h3>
        <p v-if="!score">{{ t('skillAssessment.saveScoreBeforeEvidence') }}</p>
        <p v-else>{{ t('skillAssessment.evidenceCount', { count: sortedEvidence.length }) }}</p>
      </div>
    </header>

    <div class="skill-evidence-actions">
      <el-button size="small" :disabled="!canAddEvidence" @click="emit('addPoint')">
        {{ t('skillAssessment.addCurrentFrame') }}
      </el-button>
      <el-button
        v-if="pendingStartFrame === null"
        size="small"
        :disabled="!canAddEvidence"
        @click="emit('startInterval')"
      >
        {{ t('skillAssessment.startInterval') }}
      </el-button>
      <template v-else>
        <el-button size="small" type="primary" :disabled="!canAddEvidence" @click="emit('finishInterval')">
          {{ t('skillAssessment.finishInterval') }}
        </el-button>
        <el-button size="small" @click="emit('cancelInterval')">
          {{ t('skillAssessment.cancelInterval') }}
        </el-button>
        <span class="skill-muted">{{ t('skillAssessment.startedAtFrame', { frame: pendingStartFrame + 1 }) }}</span>
      </template>
    </div>

    <div v-if="sortedEvidence.length === 0" class="skill-empty-panel">
      {{ t('skillAssessment.noEvidence') }}
    </div>
    <article v-for="evidence in sortedEvidence" :key="evidence.id" class="skill-evidence-item">
      <template v-if="editingEvidenceId === evidence.id">
        <div class="skill-evidence-edit-grid">
          <el-input v-model="editStartFrame" size="small" :placeholder="t('phaseAnnotation.startFrame')" />
          <el-input v-model="editEndFrame" size="small" :placeholder="t('skillAssessment.inclusiveEndPointHelp')" />
        </div>
        <el-input v-model="editComment" type="textarea" :rows="2" :placeholder="t('skillAssessment.evidenceComment')" />
        <div class="skill-evidence-actions">
          <el-button size="small" type="primary" @click="saveEdit(evidence)">{{ t('common.save') }}</el-button>
          <el-button size="small" @click="editingEvidenceId = null">{{ t('common.cancel') }}</el-button>
        </div>
      </template>
      <template v-else>
        <div>
          <strong>{{ formatEvidenceRange(evidence) }}</strong>
          <span>{{ formatSkillTime(evidence.start_frame, fps) }}</span>
        </div>
        <p v-if="evidence.comment">{{ evidence.comment }}</p>
        <div class="skill-evidence-actions">
          <el-button size="small" @click="emit('goEvidence', evidence)">{{ t('common.go') }}</el-button>
          <el-button size="small" :disabled="readonly || saving" @click="beginEdit(evidence)">{{ t('common.edit') }}</el-button>
          <el-button size="small" type="danger" plain :disabled="readonly || saving" @click="emit('deleteEvidence', evidence.id)">{{ t('common.delete') }}</el-button>
        </div>
      </template>
    </article>
  </section>
</template>

<style scoped>
.skill-evidence-panel {
  display: grid;
  gap: 0.85rem;
}

.skill-evidence-panel h3 {
  margin: 0;
  color: #e2e8f0;
}

.skill-evidence-panel p,
.skill-muted {
  margin: 0.25rem 0 0;
  color: rgba(148, 163, 184, 0.9);
}

.skill-evidence-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  align-items: center;
}

.skill-evidence-item,
.skill-empty-panel {
  padding: 0.8rem;
  border-radius: 0.9rem;
  background: rgba(15, 23, 42, 0.7);
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.skill-evidence-item strong {
  display: block;
  color: #e2e8f0;
}

.skill-evidence-item span {
  color: rgba(148, 163, 184, 0.9);
}

.skill-evidence-edit-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}
</style>
