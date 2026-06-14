<script setup lang="ts">
import { Delete, Hide, View } from '@element-plus/icons-vue'
import { computed, nextTick, ref, watch } from 'vue'
import type { ComponentPublicInstance } from 'vue'

import type { AnnotationObject, Label } from '../stores/annotation'

const props = defineProps<{
  annotations: AnnotationObject[]
  labels: Label[]
  selectedAnnotationId: number | string | null
  hiddenAnnotationIds: Array<number | string>
}>()

const emit = defineEmits<{
  deleteAnnotation: [id: number | string]
  selectAnnotation: [id: number | string]
  toggleVisibility: [id: number | string]
  updateAnnotationLabel: [id: number | string, labelId: number]
}>()

const cardRefs = ref(new Map<number | string, HTMLElement>())

const objectCount = computed(() => props.annotations.length)

watch(
  () => props.selectedAnnotationId,
  async (id) => {
    if (id === null) {
      return
    }

    await nextTick()
    cardRefs.value.get(id)?.scrollIntoView({ block: 'nearest' })
  },
)

function labelFor(labelId: number): Label | undefined {
  return props.labels.find((label) => label.id === labelId)
}

function isHidden(id: number | string): boolean {
  return props.hiddenAnnotationIds.includes(id)
}

function setCardRef(id: number | string, element: Element | ComponentPublicInstance | null) {
  if (element instanceof HTMLElement) {
    cardRefs.value.set(id, element)
    return
  }

  cardRefs.value.delete(id)
}

function updateLabel(id: number | string, labelId: string | number) {
  emit('updateAnnotationLabel', id, Number(labelId))
}
</script>

<template>
  <aside class="annotation-sidebar-right">
    <header class="objects-panel-header">
      <div>
        <p class="panel-label">Objects</p>
        <h2>Objects {{ objectCount }}</h2>
      </div>
    </header>

    <section class="objects-list">
      <article
        v-for="(annotation, index) in annotations"
        :key="annotation.id"
        :ref="(element) => setCardRef(annotation.id, element)"
        class="object-card"
        :class="{ selected: selectedAnnotationId === annotation.id, hidden: isHidden(annotation.id) }"
        :style="{ borderColor: selectedAnnotationId === annotation.id ? labelFor(annotation.label_id)?.color : undefined }"
        @click="emit('selectAnnotation', annotation.id)"
      >
        <div class="object-card-top">
          <div>
            <strong>Object #{{ index + 1 }}</strong>
            <span class="object-shape-type">{{ annotation.shape_type }} shape</span>
          </div>
          <span class="label-swatch" :style="{ backgroundColor: labelFor(annotation.label_id)?.color }"></span>
        </div>

        <el-select
          class="object-label-select"
          :model-value="annotation.label_id"
          size="small"
          @click.stop
          @change="(labelId: string | number) => updateLabel(annotation.id, labelId)"
        >
          <el-option
            v-for="label in labels"
            :key="label.id"
            :label="label.name"
            :value="label.id"
          />
        </el-select>

        <div class="object-card-actions">
          <el-button size="small" text @click.stop="emit('toggleVisibility', annotation.id)">
            <el-icon><Hide v-if="isHidden(annotation.id)" /><View v-else /></el-icon>
            {{ isHidden(annotation.id) ? 'Hidden' : 'Visible' }}
          </el-button>
          <el-button size="small" text type="danger" @click.stop="emit('deleteAnnotation', annotation.id)">
            <el-icon><Delete /></el-icon>
            Delete
          </el-button>
        </div>
      </article>

      <div v-if="annotations.length === 0" class="objects-empty">
        No annotations on this image.
      </div>
    </section>
  </aside>
</template>
