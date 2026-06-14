<script setup lang="ts">
import { ArrowDown, Back, Picture, RefreshRight, Tickets } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppSidebar from '../components/AppSidebar.vue'
import { useAdminStore } from '../stores/admin'
import { useJobsStore, type JobCard, type JobExportFormat, type ProjectCard } from '../stores/jobs'
import { useUsersStore, type UserAccount } from '../stores/users'

const route = useRoute()
const router = useRouter()
const adminStore = useAdminStore()
const jobsStore = useJobsStore()
const usersStore = useUsersStore()
const { jobs, loading, error, projects } = storeToRefs(jobsStore)
const { isAdmin } = storeToRefs(adminStore)
const { users, loading: usersLoading, error: usersError } = storeToRefs(usersStore)
const newUsername = ref('')

const projectId = computed(() => route.params.projectId ? String(route.params.projectId) : '')
const isProjectJobsMode = computed(() => projectId.value.length > 0)
const selectedProject = computed(() =>
  projects.value.find((project) => String(project.id) === projectId.value) ?? null,
)
const projectTitle = computed(() => {
  if (selectedProject.value) {
    return selectedProject.value.name
  }

  if (projectId.value === '0') {
    return 'Unassigned Project'
  }

  return jobs.value[0]?.project_name ?? 'Project'
})

watch(
  () => route.params.projectId,
  () => {
    void loadPage()
  },
  { immediate: true },
)

watch(
  isAdmin,
  (enabled) => {
    if (enabled) {
      void usersStore.fetchUsers()
    }
  },
  { immediate: true },
)

async function loadPage() {
  if (isProjectJobsMode.value) {
    await jobsStore.fetchProjects()
    await jobsStore.fetchProjectJobs(projectId.value)
    return
  }

  await jobsStore.fetchProjects()
}

async function addUsername() {
  const added = await usersStore.addUser(newUsername.value)
  if (!added) {
    ElMessage.error(usersStore.error || 'Add user failed')
    return
  }

  newUsername.value = ''
  ElMessage.success('User added')
}

async function confirmDeleteUser(user: UserAccount) {
  try {
    await ElMessageBox.confirm(
      `Are you sure you want to delete user "${user.username}"?`,
      'Delete User',
      {
        cancelButtonText: 'Cancel',
        confirmButtonText: 'Delete User',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  const deleted = await usersStore.deleteUser(user.id)
  if (!deleted) {
    ElMessage.error(usersStore.error || 'Delete user failed')
    return
  }

  ElMessage.success('User deleted')
}

function refreshPage() {
  void loadPage()
}

function openProject(project: ProjectCard) {
  void router.push(`/jobs/projects/${project.id}`)
}

function backToProjects() {
  void router.push('/jobs')
}

function openJob(job: JobCard) {
  void router.push(`/jobs/${job.id}/annotate`)
}

async function exportJob(job: JobCard, format: JobExportFormat) {
  const exported = await jobsStore.exportJob(job.id, format)
  if (exported) {
    ElMessage.success('Export completed')
    return
  }

  ElMessage.error('Export failed')
}

function handleExportCommand(job: JobCard, command: string | number | object) {
  void exportJob(job, command as JobExportFormat)
}

async function confirmDeleteProject(project: ProjectCard) {
  if (!isAdmin.value || project.id === 0) {
    return
  }

  try {
    await ElMessageBox.confirm(
      `Are you sure you want to delete project "${project.name}"?\nThis will also delete all jobs, images, labels and annotations under this project.`,
      'Delete Project',
      {
        cancelButtonText: 'Cancel',
        confirmButtonText: 'Delete Project',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  const deleted = await jobsStore.deleteProject(project.id)
  if (!deleted) {
    ElMessage.error(jobsStore.error || 'Delete project failed')
    return
  }

  ElMessage.success('Project deleted')
  await loadPage()
}

async function confirmDeleteJob(job: JobCard) {
  if (!isAdmin.value) {
    return
  }

  try {
    await ElMessageBox.confirm(
      `Are you sure you want to delete job "${job.name}"?\nThis will delete all images, labels and annotations under this job.`,
      'Delete Job',
      {
        cancelButtonText: 'Cancel',
        confirmButtonText: 'Delete Job',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  const deleted = await jobsStore.deleteJob(job.id)
  if (!deleted) {
    ElMessage.error(jobsStore.error || 'Delete job failed')
    return
  }

  ElMessage.success('Job deleted')
  await loadPage()
}
</script>

<template>
  <main class="workspace">
    <AppSidebar :subtitle="isProjectJobsMode ? 'Project Jobs' : 'Projects'" />

    <section class="content">
      <header class="topbar jobs-topbar">
        <div>
          <p class="eyebrow">{{ isProjectJobsMode ? 'Project jobs' : 'Annotation projects' }}</p>
          <h2>{{ isProjectJobsMode ? `${projectTitle} / Jobs` : 'Projects' }}</h2>
        </div>
        <div class="jobs-topbar-actions">
          <el-button v-if="isProjectJobsMode" plain @click="backToProjects">
            <el-icon><Back /></el-icon>
            Back to Projects
          </el-button>
          <el-button :loading="loading" type="primary" @click="refreshPage">
            <el-icon><RefreshRight /></el-icon>
            Refresh
          </el-button>
        </div>
      </header>

      <el-alert v-if="error" :title="error" type="error" show-icon />
      <el-alert v-if="usersError && isAdmin" :title="usersError" type="error" show-icon />

      <section v-if="isAdmin" class="admin-user-panel">
        <div class="admin-user-panel-header">
          <div>
            <p class="eyebrow">Admin</p>
            <h3>User Management</h3>
          </div>
          <form class="admin-user-add" @submit.prevent="addUsername">
            <el-input
              v-model="newUsername"
              clearable
              placeholder="Add username"
            />
            <el-button type="primary" :loading="usersLoading" native-type="submit">
              Add
            </el-button>
          </form>
        </div>

        <div v-loading="usersLoading" class="admin-user-list">
          <div v-for="user in users" :key="user.id" class="admin-user-row">
            <span>{{ user.username }}</span>
            <el-button size="small" type="danger" plain @click="confirmDeleteUser(user)">
              Delete
            </el-button>
          </div>
          <p v-if="!usersLoading && users.length === 0" class="admin-user-empty">
            No users yet
          </p>
        </div>
      </section>

      <section v-if="!isProjectJobsMode" v-loading="loading" class="jobs-board">
        <article
          v-for="project in projects"
          :key="project.id"
          class="job-card project-card"
          role="button"
          tabindex="0"
          @click="openProject(project)"
          @keydown.enter.prevent="openProject(project)"
        >
          <div class="job-thumb">
            <img
              v-if="jobsStore.thumbnailUrl(project.thumbnail_url)"
              :src="jobsStore.thumbnailUrl(project.thumbnail_url)"
              :alt="`${project.name} thumbnail`"
            />
            <div v-else class="job-thumb-empty">
              <el-icon><Picture /></el-icon>
            </div>
          </div>

          <div class="job-card-body">
            <div class="job-mainline">
              <strong class="job-card-title">{{ project.name }}</strong>
              <el-tag size="small" type="info">
                Project
              </el-tag>
            </div>
            <span v-if="project.id !== 0" class="job-secondary">ID: {{ project.id }}</span>
            <div class="job-meta">
              <span>Jobs: {{ project.job_count }}</span>
              <span>Frames: {{ project.frame_count }}</span>
            </div>
            <div class="job-card-actions">
              <el-button size="small" type="primary" @click.stop="openProject(project)">
                View Jobs
              </el-button>
              <el-button
                v-if="isAdmin && project.id !== 0"
                size="small"
                type="danger"
                plain
                @click.stop="confirmDeleteProject(project)"
              >
                Delete Project
              </el-button>
            </div>
          </div>
        </article>

        <div v-if="!loading && projects.length === 0" class="empty-jobs">
          <el-icon><Tickets /></el-icon>
          <p>No projects yet</p>
        </div>
      </section>

      <section v-else v-loading="loading" class="jobs-board">
        <article
          v-for="job in jobs"
          :key="job.id"
          class="job-card"
          role="button"
          tabindex="0"
          @click="openJob(job)"
          @keydown.enter.prevent="openJob(job)"
        >
          <div class="job-thumb">
            <img
              v-if="jobsStore.thumbnailUrl(job.thumbnail_url)"
              :src="jobsStore.thumbnailUrl(job.thumbnail_url)"
              :alt="`${job.name} thumbnail`"
            />
            <div v-else class="job-thumb-empty">
              <el-icon><Picture /></el-icon>
            </div>
          </div>

          <div class="job-card-body">
            <div class="job-card-header">
              <h3 class="job-card-title" :title="job.name || 'Untitled Job'">
                {{ job.name || 'Untitled Job' }}
              </h3>
              <el-tag class="job-status-badge" size="small" :type="job.status === 'completed' ? 'success' : 'warning'">
                {{ job.status }}
              </el-tag>
            </div>
            <span class="job-secondary">ID: {{ job.id }}</span>
            <div class="job-meta">
              <span>Project: {{ job.project_name ?? 'No project' }}</span>
              <span>Frames: {{ job.frames }}</span>
            </div>
            <div class="job-card-actions">
              <el-button size="small" type="primary" @click.stop="openJob(job)">
                Open
              </el-button>
              <el-dropdown
                trigger="click"
                @click.stop
                @command="handleExportCommand(job, $event)"
              >
                <el-button size="small" plain :loading="jobsStore.isExporting(job.id)" @click.stop>
                  Export
                  <el-icon class="el-icon--right"><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="labelme">
                      LabelMe
                    </el-dropdown-item>
                    <el-dropdown-item command="overlay">
                      Overlay Images
                    </el-dropdown-item>
                    <el-dropdown-item command="indexed-mask">
                      Indexed Masks
                    </el-dropdown-item>
                    <el-dropdown-item command="color-mask">
                      Color Masks
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <el-button
                v-if="isAdmin"
                size="small"
                type="danger"
                plain
                @click.stop="confirmDeleteJob(job)"
              >
                Delete Job
              </el-button>
            </div>
          </div>
        </article>

        <div v-if="!loading && jobs.length === 0" class="empty-jobs">
          <el-icon><Tickets /></el-icon>
          <p>No jobs in this project</p>
        </div>
      </section>
    </section>
  </main>
</template>
