<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  modelValue: boolean
  videoId: number | null
  videoName: string
  notes: string | null
  saving?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  save: [payload: { videoId: number; notes: string | null }]
}>()

const { t } = useI18n()
const noteDraft = ref('')

const normalizedInitialNotes = computed(() => props.notes ?? '')
const noteChanged = computed(() => noteDraft.value !== normalizedInitialNotes.value)
const noteLength = computed(() => noteDraft.value.length)
const canSave = computed(() => Boolean(props.videoId) && noteChanged.value && noteLength.value <= 5000 && !props.saving)

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) {
      noteDraft.value = normalizedInitialNotes.value
    }
  },
)

function shouldClose() {
  return !noteChanged.value || window.confirm(t('researchVideos.unsavedNotes'))
}

function closeDialog() {
  if (!shouldClose()) {
    return
  }
  emit('update:modelValue', false)
}

function beforeClose(done: () => void) {
  if (!shouldClose()) {
    return
  }
  done()
}

function saveNotes() {
  if (!canSave.value || props.videoId === null) {
    return
  }
  emit('save', {
    videoId: props.videoId,
    notes: noteDraft.value.trim() ? noteDraft.value : null,
  })
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="t('researchVideos.editNotes')"
    width="620px"
    :before-close="beforeClose"
    @update:model-value="(value: boolean) => emit('update:modelValue', value)"
  >
    <div class="research-video-notes-dialog">
      <p class="research-video-notes-dialog__name">{{ videoName }}</p>
      <el-input
        v-model="noteDraft"
        type="textarea"
        :rows="8"
        maxlength="5000"
        show-word-limit
        :placeholder="t('researchVideos.noNotes')"
      />
      <p class="research-video-notes-dialog__count">{{ t('researchVideos.notesLength', { count: noteLength, max: 5000 }) }}</p>
    </div>
    <template #footer>
      <el-button :disabled="saving" @click="closeDialog">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="saving" :disabled="!canSave" @click="saveNotes">{{ t('researchVideos.saveNotes') }}</el-button>
    </template>
  </el-dialog>
</template>
