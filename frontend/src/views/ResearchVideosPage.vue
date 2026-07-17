<script setup lang="ts">
import { Clock, Delete, RefreshRight, UploadFilled, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import AppSidebar from '../components/AppSidebar.vue'
import { apiUrl } from '../utils/api'
import { useResearchVideosStore } from '../stores/researchVideos'

const router = useRouter()
const researchVideosStore = useResearchVideosStore()
const { error, loading, saving, videos } = storeToRefs(researchVideosStore)
const uploadInputRef = ref<HTMLInputElement | null>(null)
const selectedUploadName = ref('')

onMounted(() => {
  void researchVideosStore.fetchVideos()
})

const videoCards = computed(() => videos.value)

function formatDuration(durationMs: number | null) {
  if (!durationMs || durationMs <= 0) {
    return 'Unknown'
  }
  const totalSeconds = Math.round(durationMs / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}

function openUploadDialog() {
  uploadInputRef.value?.click()
}

async function handleUploadChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) {
    return
  }

  const created = await researchVideosStore.uploadVideo(file, selectedUploadName.value || file.name)
  input.value = ''
  selectedUploadName.value = ''

  if (!created) {
    ElMessage.error(researchVideosStore.error || 'Video import failed')
    return
  }

  ElMessage.success('Video imported')
  await researchVideosStore.fetchVideos()
}

function openVideo(videoId: number) {
  void router.push(`/research/videos/${videoId}/annotate`)
}

async function deleteVideo(videoId: number, name: string) {
  try {
    await ElMessageBox.confirm(
      `Delete research video "${name}"?`,
      'Delete Research Video',
      {
        cancelButtonText: 'Cancel',
        confirmButtonText: 'Delete',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  try {
    const response = await fetch(apiUrl(`/api/research/videos/${videoId}`), { method: 'DELETE' })
    if (!response.ok) {
      throw new Error(`Delete failed: ${response.status}`)
    }
    await researchVideosStore.fetchVideos()
    ElMessage.success('Research video deleted')
  } catch (deleteError) {
    ElMessage.error(deleteError instanceof Error ? deleteError.message : 'Delete failed')
  }
}
</script>

<template>
  <main class="workspace">
    <AppSidebar subtitle="Research" />

    <section class="content">
      <header class="topbar">
        <div>
          <p class="eyebrow">Experimental workspace</p>
          <h2>Video Experiments</h2>
          <p class="page-subtitle">Upload a video file for experimental frame-level annotation.</p>
        </div>
        <div class="topbar-actions">
          <el-button :loading="loading" @click="researchVideosStore.fetchVideos">
            <el-icon><RefreshRight /></el-icon>
            Refresh
          </el-button>
          <el-button type="primary" :loading="saving" @click="openUploadDialog">
            <el-icon><UploadFilled /></el-icon>
            Import video
          </el-button>
        </div>
      </header>

      <el-alert v-if="error" :title="error" type="error" show-icon />

      <section class="research-upload-inline">
        <el-input v-model="selectedUploadName" placeholder="Optional display name" />
        <input
          ref="uploadInputRef"
          accept="video/mp4,video/quicktime,video/x-msvideo,video/x-matroska,video/webm"
          class="hidden-file-input"
          type="file"
          @change="handleUploadChange"
        />
        <span class="research-upload-help">At least mp4 is supported in the first version.</span>
      </section>

      <section class="research-video-grid">
        <article v-for="video in videoCards" :key="video.id" class="research-video-card">
          <div class="research-video-thumb">
            <img v-if="video.thumbnail_url" :src="video.thumbnail_url" :alt="video.name" />
            <div v-else class="research-video-thumb-empty">
              <el-icon><VideoPlay /></el-icon>
            </div>
          </div>

          <div class="research-video-meta">
            <div class="research-video-title-row">
              <h3>{{ video.name }}</h3>
              <span class="research-video-status" :class="video.status">{{ video.status }}</span>
            </div>
            <p class="research-video-filename">{{ video.original_filename }}</p>
            <div class="research-video-stats">
              <span>{{ formatDuration(video.duration_ms) }}</span>
              <span>{{ video.fps ? `${video.fps.toFixed(2)} fps` : 'Unknown fps' }}</span>
              <span>{{ video.frame_count }} frames</span>
              <span>{{ video.width && video.height ? `${video.width} x ${video.height}` : 'Unknown resolution' }}</span>
            </div>
            <div class="research-video-created">
              <el-icon><Clock /></el-icon>
              <span>{{ new Date(video.created_at).toLocaleString() }}</span>
            </div>
          </div>

          <div class="research-video-actions">
            <el-button type="primary" @click="openVideo(video.id)">
              <el-icon><VideoPlay /></el-icon>
              Open
            </el-button>
            <el-button text type="danger" @click="deleteVideo(video.id, video.name)">
              <el-icon><Delete /></el-icon>
              Delete
            </el-button>
          </div>
        </article>

        <div v-if="!loading && videoCards.length === 0" class="research-empty-state">
          No research videos yet. Import a video to start experimenting.
        </div>
      </section>
    </section>
  </main>
</template>
