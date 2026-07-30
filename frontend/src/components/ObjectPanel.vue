<script setup lang="ts">
import { Delete, Hide, View } from '@element-plus/icons-vue'
import { computed, nextTick, ref, watch } from 'vue'
import type { ComponentPublicInstance } from 'vue'
import { useI18n } from 'vue-i18n'

import type { AnnotationObject, Label } from '../stores/annotation'
import { sortAnnotationsFrontToBack } from '../utils/annotationLayerOrder'
import { getPolygonSmoothValue } from '../utils/polygon'

const props = defineProps<{
  annotations: AnnotationObject[]
  labels: Label[]
  selectedAnnotationId: number | string | null
  hiddenAnnotationIds: Array<number | string>
  sam2Refining: boolean
  sam2Tracking: boolean
}>()

const { t } = useI18n()

const emit = defineEmits<{
  deleteAnnotation: [id: number | string]
  selectAnnotation: [id: number | string]
  toggleVisibility: [id: number | string]
  updateAnnotationLabel: [id: number | string, labelId: number]
  createLayerAbove: [id: number | string]
  refineSelectedPolygon: [id: number | string]
  trackWithSam2: [id: number | string]
  showAll: []
  hideAll: []
  updatePolygonSmoothing: [id: number | string, value: number]
  commitPolygonSmoothing: [id: number | string, value: number]
  resetPolygonSmoothing: [id: number | string]
  reorderAnnotation: [id: number | string, targetFrontIndex: number]
  moveAnnotationLayer: [id: number | string, direction: 'up' | 'down' | 'top' | 'bottom']
}>()

const cardRefs = ref(new Map<number | string, HTMLElement>())
const polygonSmoothingValue = ref(0)
const draggingAnnotationId = ref<number | string | null>(null)
const dragOverAnnotationId = ref<number | string | null>(null)

const objectAnnotations = computed(() =>
  sortAnnotationsFrontToBack(props.annotations.filter((annotation) => !isClassificationAnnotation(annotation))),
)
const objectCount = computed(() => objectAnnotations.value.length)
const hiddenCount = computed(() => objectAnnotations.value.filter((annotation) => isHidden(annotation.id)).length)
const selectedAnnotation = computed(() =>
  objectAnnotations.value.find((annotation) => annotation.id === props.selectedAnnotationId) ?? null,
)
const selectedPolygonAnnotation = computed(() =>
  selectedAnnotation.value?.shape_type === 'polygon' ? selectedAnnotation.value : null,
)

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

watch(
  () => selectedPolygonAnnotation.value,
  (annotation) => {
    polygonSmoothingValue.value = annotation ? getPolygonSmoothValue(annotation) : 0
  },
  { immediate: true },
)

function labelFor(labelId: number): Label | undefined {
  return props.labels.find((label) => label.id === labelId)
}

function isClassificationAnnotation(annotation: AnnotationObject): boolean {
  return annotation.shape_type === 'classification' || annotation.attributes?.classification === true
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

function startDrag(annotationId: number | string, event: DragEvent) {
  draggingAnnotationId.value = annotationId
  dragOverAnnotationId.value = annotationId
  event.dataTransfer?.setData('text/plain', String(annotationId))
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
  }
}

function updateDragTarget(annotationId: number | string, event: DragEvent) {
  event.preventDefault()
  if (draggingAnnotationId.value === null) {
    return
  }
  dragOverAnnotationId.value = annotationId
}

function finishDrag(annotationId: number | string, event: DragEvent) {
  event.preventDefault()
  const draggedId = draggingAnnotationId.value
  draggingAnnotationId.value = null
  dragOverAnnotationId.value = null
  if (draggedId === null) {
    return
  }

  const targetIndex = objectAnnotations.value.findIndex((annotation) => annotation.id === annotationId)
  if (targetIndex < 0) {
    return
  }
  emit('reorderAnnotation', draggedId, targetIndex)
}

function clearDragState() {
  draggingAnnotationId.value = null
  dragOverAnnotationId.value = null
}

function updateSmoothing(value: number | null) {
  if (!selectedPolygonAnnotation.value || value === null) {
    return
  }
  polygonSmoothingValue.value = Number(value)
  emit('updatePolygonSmoothing', selectedPolygonAnnotation.value.id, polygonSmoothingValue.value)
}

function commitSmoothing(value: number | null) {
  if (!selectedPolygonAnnotation.value || value === null) {
    return
  }
  polygonSmoothingValue.value = Number(value)
  emit('commitPolygonSmoothing', selectedPolygonAnnotation.value.id, polygonSmoothingValue.value)
}
</script>

<template>
  <aside class="annotation-sidebar-right">
    <header class="objects-panel-header">
      <div>
        <p class="panel-label">{{ t('frameAnnotation.objects') }}</p>
        <h2>{{ t('frameAnnotation.objects') }} {{ objectCount }}</h2>
      </div>
      <div class="objects-panel-bulk-actions">
        <el-button size="small" :disabled="objectAnnotations.length === 0 || hiddenCount === 0" @click="emit('showAll')">
          {{ t('frameAnnotation.showAll') }}
        </el-button>
        <el-button size="small" :disabled="objectAnnotations.length === 0 || hiddenCount === objectAnnotations.length" @click="emit('hideAll')">
          {{ t('frameAnnotation.hideAll') }}
        </el-button>
      </div>
    </header>

    <section class="objects-list">
      <section class="object-smoothing-panel">
        <div class="object-smoothing-header">
          <div>
            <p class="panel-label">{{ t('frameAnnotation.polygonSmoothing') }}</p>
            <h3>{{ selectedPolygonAnnotation ? t('frameAnnotation.selectedPolygon') : t('frameAnnotation.selectPolygon') }}</h3>
          </div>
          <el-button
            size="small"
            text
            :disabled="!selectedPolygonAnnotation"
            @click="selectedPolygonAnnotation && emit('resetPolygonSmoothing', selectedPolygonAnnotation.id)"
          >
            {{ t('frameAnnotation.resetToOriginal') }}
          </el-button>
        </div>
        <template v-if="selectedPolygonAnnotation">
          <div class="object-smoothing-scale">
            <span>{{ t('settings.fineOutline') }}</span>
            <span>{{ t('settings.coarseOutline') }}</span>
          </div>
          <el-slider
            :model-value="polygonSmoothingValue"
            :min="0"
            :max="100"
            :step="1"
            @input="updateSmoothing"
            @change="commitSmoothing"
          />
        </template>
        <p v-else class="object-smoothing-empty">
          {{ t('frameAnnotation.smoothingHelp') }}
        </p>
        <el-button
          size="small"
          type="primary"
          plain
          :disabled="!selectedPolygonAnnotation"
          @click="selectedPolygonAnnotation && emit('createLayerAbove', selectedPolygonAnnotation.id)"
        >
          {{ t('frameAnnotation.createLayerAbove') }}
        </el-button>
        <el-button
          size="small"
          type="primary"
          plain
          :loading="sam2Refining"
          :disabled="!selectedPolygonAnnotation || sam2Refining"
          :title="selectedPolygonAnnotation ? '' : t('frameAnnotation.refinePolygonOnly')"
          @click="selectedPolygonAnnotation && emit('refineSelectedPolygon', selectedPolygonAnnotation.id)"
        >
          {{ t('frameAnnotation.refineWithSam2') }}
        </el-button>
        <el-button
          size="small"
          type="primary"
          plain
          :loading="sam2Tracking"
          :disabled="!selectedPolygonAnnotation || sam2Tracking || sam2Refining"
          :title="selectedPolygonAnnotation ? '' : t('frameAnnotation.trackPolygonOnly')"
          @click="selectedPolygonAnnotation && emit('trackWithSam2', selectedPolygonAnnotation.id)"
        >
          {{ t('frameAnnotation.trackWithSam2') }}
        </el-button>
      </section>

      <article
        v-for="(annotation, index) in objectAnnotations"
        :key="annotation.id"
        :ref="(element) => setCardRef(annotation.id, element)"
        class="object-card"
        :class="{
          selected: selectedAnnotationId === annotation.id,
          hidden: isHidden(annotation.id),
          dragging: draggingAnnotationId === annotation.id,
          'drag-over': dragOverAnnotationId === annotation.id && draggingAnnotationId !== annotation.id,
        }"
        :style="{ borderColor: selectedAnnotationId === annotation.id ? labelFor(annotation.label_id)?.color : undefined }"
        @dragover="updateDragTarget(annotation.id, $event)"
        @drop="finishDrag(annotation.id, $event)"
        @click="emit('selectAnnotation', annotation.id)"
      >
        <div class="object-card-top">
          <button
            class="object-drag-handle"
            type="button"
            draggable="true"
            :aria-label="t('frameAnnotation.dragLayer')"
            @click.stop
            @dragstart.stop="startDrag(annotation.id, $event)"
            @dragend="clearDragState"
          >
            ⋮⋮
          </button>
          <div>
            <strong>{{ t('frameAnnotation.object') }} #{{ index + 1 }}</strong>
            <span class="object-shape-type">
              {{ annotation.shape_type }} {{ t('frameAnnotation.shapeSuffix') }} ·
              {{ index === 0 ? t('frameAnnotation.topLayer') : index === objectAnnotations.length - 1 ? t('frameAnnotation.bottomLayer') : t('frameAnnotation.layerOrder', { order: objectAnnotations.length - index }) }}
            </span>
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
          <el-button-group class="object-layer-actions" @click.stop>
            <el-button size="small" text :disabled="index === 0" @click="emit('moveAnnotationLayer', annotation.id, 'up')">
              {{ t('frameAnnotation.layerUp') }}
            </el-button>
            <el-button size="small" text :disabled="index === objectAnnotations.length - 1" @click="emit('moveAnnotationLayer', annotation.id, 'down')">
              {{ t('frameAnnotation.layerDown') }}
            </el-button>
            <el-button size="small" text :disabled="index === 0" @click="emit('moveAnnotationLayer', annotation.id, 'top')">
              {{ t('frameAnnotation.layerTop') }}
            </el-button>
            <el-button size="small" text :disabled="index === objectAnnotations.length - 1" @click="emit('moveAnnotationLayer', annotation.id, 'bottom')">
              {{ t('frameAnnotation.layerBottom') }}
            </el-button>
          </el-button-group>
          <el-button size="small" text @click.stop="emit('toggleVisibility', annotation.id)">
            <el-icon><Hide v-if="isHidden(annotation.id)" /><View v-else /></el-icon>
            {{ isHidden(annotation.id) ? t('frameAnnotation.hidden') : t('frameAnnotation.visible') }}
          </el-button>
          <el-button size="small" text type="danger" @click.stop="emit('deleteAnnotation', annotation.id)">
            <el-icon><Delete /></el-icon>
            {{ t('common.delete') }}
          </el-button>
        </div>
      </article>

      <div v-if="objectAnnotations.length === 0" class="objects-empty">
        {{ t('frameAnnotation.noAnnotationsOnImage') }}
      </div>
    </section>
  </aside>
</template>
