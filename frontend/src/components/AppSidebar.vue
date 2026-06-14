<script setup lang="ts">
import { DataAnalysis, FolderOpened, Lock, Tickets, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAdminStore } from '../stores/admin'
import {
  DEFAULT_USER_SETTINGS,
  useUserSettingsStore,
  type UserSettings,
} from '../stores/userSettings'
import { useUsersStore } from '../stores/users'

type ShortcutCaptureTarget =
  | 'add_polygon_vertex_shortcut'
  | 'delete_polygon_vertex_shortcut'
  | 'pan_modifier_shortcut'
  | 'polygon_confirm_point_shortcut'

defineProps<{
  subtitle?: string
}>()

const route = useRoute()
const router = useRouter()
const adminStore = useAdminStore()
const usersStore = useUsersStore()
const userSettingsStore = useUserSettingsStore()
const { isAdmin } = storeToRefs(adminStore)
const { currentUsername, loading: userLoading } = storeToRefs(usersStore)
const { settings: userSettings, loading: settingsLoading } = storeToRefs(userSettingsStore)
const adminLoginVisible = ref(false)
const adminPassword = ref('')
const userLoginVisible = ref(false)
const usernameInput = ref('')
const settingsVisible = ref(false)
const settingsDraft = ref<UserSettings>({ ...DEFAULT_USER_SETTINGS })
const shortcutCaptureTarget = ref<ShortcutCaptureTarget | null>(null)
const settingHelpVisible = ref(false)
const settingHelpText = ref('')
const settingHelpFloatingStyle = ref<Record<string, string>>({
  left: '12px',
  top: '12px',
})

const activeMenu = computed(() => {
  if (route.path.startsWith('/datasets')) return 'datasets'
  if (route.path.startsWith('/jobs')) return 'projects'
  if (route.path.startsWith('/review')) return 'review'
  return 'projects'
})
const hasShortcutConflict = computed(() =>
  settingsDraft.value.add_polygon_vertex_shortcut === settingsDraft.value.delete_polygon_vertex_shortcut,
)
const shortcutWarnings = computed(() => {
  const warnings: string[] = []
  if (settingsDraft.value.polygon_confirm_point_shortcut === settingsDraft.value.pan_modifier_shortcut) {
    warnings.push('Confirm polygon point shortcut conflicts with pan shortcut.')
  }
  if (settingsDraft.value.polygon_confirm_point_shortcut === settingsDraft.value.add_polygon_vertex_shortcut) {
    warnings.push('Confirm polygon point shortcut conflicts with add vertex shortcut.')
  }
  if (settingsDraft.value.polygon_confirm_point_shortcut === settingsDraft.value.delete_polygon_vertex_shortcut) {
    warnings.push('Confirm polygon point shortcut conflicts with delete vertex shortcut.')
  }
  return warnings
})

onMounted(() => {
  if (currentUsername.value) {
    void userSettingsStore.loadSettings(currentUsername.value)
  }
})

onBeforeUnmount(() => {
  stopShortcutCapture()
})

watch(currentUsername, (username) => {
  if (username) {
    void userSettingsStore.loadSettings(username)
    return
  }

  userSettingsStore.resetToDefaults()
})

function navigate(index: string) {
  const routes: Record<string, string> = {
    datasets: '/datasets',
    projects: '/jobs',
    review: '/review',
  }

  void router.push(routes[index])
}

function openAdminLogin() {
  adminPassword.value = ''
  adminLoginVisible.value = true
}

function closeAdminLogin() {
  adminPassword.value = ''
  adminLoginVisible.value = false
}

function submitAdminLogin() {
  if (!adminStore.login(adminPassword.value)) {
    ElMessage.error('Wrong password')
    return
  }

  adminPassword.value = ''
  closeAdminLogin()
  ElMessage.success('Admin mode enabled')
}

function openUserLogin() {
  usernameInput.value = ''
  userLoginVisible.value = true
}

function closeUserLogin() {
  usernameInput.value = ''
  userLoginVisible.value = false
}

async function submitUserLogin() {
  const loggedIn = await usersStore.login(usernameInput.value)
  if (!loggedIn) {
    ElMessage.error(usersStore.error || 'User not found. Please ask admin to add this username.')
    return
  }

  closeUserLogin()
  await userSettingsStore.loadSettings(currentUsername.value)
  ElMessage.success(`Logged in as ${currentUsername.value}`)
}

function logoutUser() {
  usersStore.logout()
  userSettingsStore.resetToDefaults()
  ElMessage.success('Logged out')
}

async function openUserSettings() {
  if (!currentUsername.value) {
    return
  }

  if (userSettingsStore.loadedUsername !== currentUsername.value) {
    await userSettingsStore.loadSettings(currentUsername.value)
  }

  settingsDraft.value = { ...userSettings.value }
  settingsVisible.value = true
}

function closeUserSettings() {
  settingsVisible.value = false
  closeSettingHelp()
  stopShortcutCapture()
  settingsDraft.value = { ...userSettings.value }
}

function resetSettingsDraft() {
  settingsDraft.value = { ...DEFAULT_USER_SETTINGS }
  stopShortcutCapture()
}

async function saveUserSettings() {
  if (!currentUsername.value) {
    return
  }

  if (hasShortcutConflict.value) {
    ElMessage.error('Add and delete polygon vertex shortcuts cannot use the same key.')
    return
  }

  const saved = await userSettingsStore.saveSettings(currentUsername.value, settingsDraft.value)
  if (!saved) {
    ElMessage.error(userSettingsStore.error || 'Save user settings failed')
    return
  }

  closeSettingHelp()
  stopShortcutCapture()
  settingsVisible.value = false
  ElMessage.success('User settings saved')
}

function startShortcutCapture(target: ShortcutCaptureTarget) {
  closeSettingHelp()
  shortcutCaptureTarget.value = target
  window.addEventListener('keydown', handleShortcutCaptureKeydown, { capture: true })
}

function stopShortcutCapture() {
  if (!shortcutCaptureTarget.value) {
    return
  }

  shortcutCaptureTarget.value = null
  window.removeEventListener('keydown', handleShortcutCaptureKeydown, { capture: true })
}

function handleShortcutCaptureKeydown(event: KeyboardEvent) {
  const target = shortcutCaptureTarget.value
  if (!target) {
    return
  }

  event.preventDefault()
  event.stopPropagation()

  const shortcut = normalizeShortcutFromKeyboardEvent(event)
  if (!shortcut) {
    ElMessage.error('Only Shift, Alt, Ctrl, Space, A-Z, and 0-9 are supported.')
    return
  }

  settingsDraft.value = {
    ...settingsDraft.value,
    [target]: shortcut,
  }
  stopShortcutCapture()
}

function normalizeShortcutFromKeyboardEvent(event: KeyboardEvent) {
  if (event.key === 'Shift') {
    return 'shift'
  }
  if (event.key === 'Alt') {
    return 'alt'
  }
  if (event.key === 'Control') {
    return 'ctrl'
  }
  if (event.code === 'Space') {
    return 'space'
  }
  if (/^Key[A-Z]$/.test(event.code)) {
    return event.code.replace('Key', '').toLowerCase()
  }
  if (/^Digit[0-9]$/.test(event.code)) {
    return event.code.replace('Digit', '')
  }
  return null
}

function shortcutCaptureLabel(target: ShortcutCaptureTarget) {
  if (shortcutCaptureTarget.value === target) {
    return 'Press a key...'
  }

  return shortcutDisplayLabel(settingsDraft.value[target])
}

function shortcutDisplayLabel(shortcut: string) {
  if (shortcut === 'ctrl') {
    return 'Ctrl'
  }
  if (shortcut === 'alt') {
    return 'Alt'
  }
  if (shortcut === 'shift') {
    return 'Shift'
  }
  if (shortcut === 'space') {
    return 'Space'
  }
  if (/^[a-z]$/.test(shortcut)) {
    return shortcut.toUpperCase()
  }
  return shortcut
}

function showSettingHelp(message: string, event: MouseEvent) {
  event.preventDefault()
  event.stopPropagation()

  const trigger = event.currentTarget instanceof HTMLElement ? event.currentTarget : null
  const availableWidth = Math.max(window.innerWidth - 24, 120)
  const popoverWidth = Math.min(320, availableWidth)
  const gap = 10
  const viewportPadding = 12
  let left = viewportPadding
  let top = viewportPadding

  if (trigger) {
    const rect = trigger.getBoundingClientRect()
    left = rect.left + rect.width / 2 - popoverWidth / 2
    left = Math.min(Math.max(left, viewportPadding), Math.max(viewportPadding, window.innerWidth - popoverWidth - viewportPadding))

    top = rect.bottom + gap
    if (top + 120 > window.innerHeight - viewportPadding) {
      top = Math.max(viewportPadding, rect.top - 120 - gap)
    }
  }

  settingHelpText.value = message
  settingHelpFloatingStyle.value = {
    left: `${left}px`,
    top: `${top}px`,
    width: `${popoverWidth}px`,
  }
  settingHelpVisible.value = true
}

function closeSettingHelp() {
  settingHelpVisible.value = false
}
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <span class="brand-mark">MA</span>
      <div>
        <h1>Medical Annotation</h1>
        <p>{{ subtitle ?? 'MVP Workbench' }}</p>
      </div>
    </div>

    <el-menu :default-active="activeMenu" class="nav-menu" @select="navigate">
      <el-menu-item index="datasets">
        <el-icon><FolderOpened /></el-icon>
        <span>Datasets</span>
      </el-menu-item>
      <el-menu-item index="projects">
        <el-icon><Tickets /></el-icon>
        <span>Projects</span>
      </el-menu-item>
      <el-menu-item index="review">
        <el-icon><DataAnalysis /></el-icon>
        <span>Review</span>
      </el-menu-item>
    </el-menu>

    <div class="sidebar-admin">
      <div class="sidebar-user-login">
        <template v-if="currentUsername">
          <div class="current-user-label">User: {{ currentUsername }}</div>
          <el-button size="small" plain @click="openUserSettings">
            Settings
          </el-button>
          <el-button size="small" plain @click="logoutUser">
            Logout
          </el-button>
        </template>
        <el-button v-else plain @click="openUserLogin">
          <el-icon><User /></el-icon>
          Login
        </el-button>
      </div>

      <template v-if="isAdmin">
        <div class="admin-active-label">Admin active</div>
        <el-button size="small" plain @click="adminStore.exit">
          Exit Admin
        </el-button>
      </template>
      <el-button v-else plain @click="openAdminLogin">
        <el-icon><Lock /></el-icon>
        Admin
      </el-button>
    </div>

    <Teleport to="body">
      <div
        v-if="settingsVisible"
        class="app-modal-backdrop"
        tabindex="-1"
        @click.self="closeUserSettings"
        @keydown.esc="closeUserSettings"
      >
        <section class="app-modal user-settings-modal" role="dialog" aria-modal="true" aria-labelledby="user-settings-title">
          <header class="user-settings-modal-header">
            <h2 id="user-settings-title">User Settings</h2>
          </header>

          <div class="user-settings-modal-body">
            <section class="settings-section">
              <h3 class="settings-section-title">General</h3>
              <label class="settings-field">
              <span class="settings-field-label">
                Edge snap threshold
                <button
                  class="settings-help-button"
                  type="button"
                  @click="showSettingHelp('边缘吸附阈值，单位是原始图像像素。点距离图像边缘小于该值时，会自动吸附到图像边缘；设置为 0 表示关闭吸附。', $event)"
                >?</button>
              </span>
              <el-input-number
                v-model="settingsDraft.edge_snap_threshold"
                :max="100"
                :min="0"
                :step="1"
              />
              <small>Points within this many image pixels from the border will snap to the image edge.</small>
            </label>

            <label class="settings-field">
              <span class="settings-field-label">
                Default tool
                <button
                  class="settings-help-button"
                  type="button"
                  @click="showSettingHelp('进入标注页面时默认选中的工具。用户进入页面后手动切换工具，不会被自动改回默认工具。', $event)"
                >?</button>
              </span>
              <el-select
                v-model="settingsDraft.default_tool"
                popper-class="settings-select-popper"
                :teleported="true"
              >
                <el-option label="cursor" value="cursor" />
                <el-option label="rectangle" value="rectangle" />
                <el-option label="polygon" value="polygon" />
                <el-option label="sam2" value="sam2" />
              </el-select>
            </label>

            <label class="settings-field">
              <span class="settings-field-label">
                After SAM2 Accept
                <button
                  class="settings-help-button"
                  type="button"
                  @click="showSettingHelp('设置接受 SAM2 结果后自动切换到哪个工具。', $event)"
                >?</button>
              </span>
              <el-select
                v-model="settingsDraft.sam_accept_next_tool"
                popper-class="settings-select-popper"
                :teleported="true"
              >
                <el-option label="Keep current tool" value="keep_current" />
                <el-option label="Switch to default tool" value="default_tool" />
                <el-option label="Switch to cursor" value="cursor" />
                <el-option label="Switch to rectangle" value="rectangle" />
                <el-option label="Switch to polygon" value="polygon" />
                <el-option label="Switch to sam2" value="sam2" />
              </el-select>
              <small>Choose which tool should be active after accepting a SAM2 mask.</small>
            </label>

            <label class="settings-field settings-checkbox-field">
              <span class="settings-field-label">
                Remember last frame per job
                <button
                  class="settings-help-button"
                  type="button"
                  @click="showSettingHelp('开启后，再次打开同一个 Job 时，会自动跳转到上次离开时所在的图像。', $event)"
                >?</button>
              </span>
              <input v-model="settingsDraft.remember_last_frame_per_job" type="checkbox" />
              <small>When enabled, the annotation page will reopen each job at the last frame you visited.</small>
            </label>

            <label class="settings-field settings-checkbox-field">
              <span class="settings-field-label">
                Keep zoom and pan when switching frames
                <button
                  class="settings-help-button"
                  type="button"
                  @click="showSettingHelp('开启后，在同一个 Job 内切换图像时，会保持当前缩放比例和画布拖动位置。', $event)"
                >?</button>
              </span>
              <input v-model="settingsDraft.keep_view_transform_on_frame_switch" type="checkbox" />
              <small>When enabled, zoom scale and canvas pan position will be preserved when switching frames within the same job.</small>
            </label>
            </section>

            <section class="settings-section">
              <h3 class="settings-section-title">SAM2 Defaults</h3>

              <label class="settings-field">
                <span class="settings-field-label">
                  Default SAM2 model
                  <button
                    class="settings-help-button"
                    type="button"
                    @click="showSettingHelp('进入标注页面时，左侧 SAM2 SETTINGS 默认使用的模型。', $event)"
                  >?</button>
                </span>
                <el-select
                  v-model="settingsDraft.sam2_default_model"
                  popper-class="settings-select-popper"
                  :teleported="true"
                >
                  <el-option label="sam2_hiera_tiny" value="sam2_hiera_tiny" />
                  <el-option label="sam2_hiera_small" value="sam2_hiera_small" />
                  <el-option label="sam2_hiera_base_plus" value="sam2_hiera_base_plus" />
                  <el-option label="sam2_hiera_large" value="sam2_hiera_large" />
                </el-select>
              </label>

              <label class="settings-field settings-checkbox-field">
                <span class="settings-field-label">
                  Default multimask output
                  <button
                    class="settings-help-button"
                    type="button"
                    @click="showSettingHelp('进入标注页面时，SAM2 默认是否生成多个候选 mask。', $event)"
                  >?</button>
                </span>
                <input v-model="settingsDraft.sam2_default_multimask_output" type="checkbox" />
              </label>

              <label class="settings-field settings-checkbox-field">
                <span class="settings-field-label">
                  Default show prompt points
                  <button
                    class="settings-help-button"
                    type="button"
                    @click="showSettingHelp('进入标注页面时，SAM2 默认是否显示 prompt 点。', $event)"
                  >?</button>
                </span>
                <input v-model="settingsDraft.sam2_default_show_prompt_points" type="checkbox" />
              </label>

              <label class="settings-field">
                <span class="settings-field-label">
                  Default candidate
                  <button
                    class="settings-help-button"
                    type="button"
                    @click="showSettingHelp('进入标注页面时，SAM2 默认使用的候选结果。best 会自动选择分数最高的候选。', $event)"
                  >?</button>
                </span>
                <el-select
                  v-model="settingsDraft.sam2_default_candidate"
                  popper-class="settings-select-popper"
                  :teleported="true"
                >
                  <el-option label="best" value="best" />
                  <el-option label="0" value="0" />
                  <el-option label="1" value="1" />
                  <el-option label="2" value="2" />
                </el-select>
              </label>

              <label class="settings-field settings-slider-field">
                <span class="settings-field-label">
                  Default polygon simplification: {{ settingsDraft.sam2_default_polygon_epsilon.toFixed(4) }}
                  <button
                    class="settings-help-button"
                    type="button"
                    @click="showSettingHelp('进入标注页面时，SAM2 polygon simplification 的默认值。数值越小，轮廓越精细。', $event)"
                  >?</button>
                </span>
                <input
                  v-model.number="settingsDraft.sam2_default_polygon_epsilon"
                  max="0.02"
                  min="0.0005"
                  step="0.0005"
                  type="range"
                />
                <div class="settings-slider-labels">
                  <small>fine outline</small>
                  <small>coarse outline</small>
                </div>
              </label>

              <label class="settings-field settings-slider-field">
                <span class="settings-field-label">
                  Default mask threshold: {{ settingsDraft.sam2_default_mask_threshold.toFixed(1) }}
                  <button
                    class="settings-help-button"
                    type="button"
                    @click="showSettingHelp('进入标注页面时，SAM2 mask threshold 的默认值。数值越低越宽松，越高越严格。', $event)"
                  >?</button>
                </span>
                <input
                  v-model.number="settingsDraft.sam2_default_mask_threshold"
                  max="5"
                  min="-5"
                  step="0.1"
                  type="range"
                />
                <div class="settings-slider-labels">
                  <small>loose mask</small>
                  <small>strict mask</small>
                </div>
              </label>

              <label class="settings-field">
                <span class="settings-field-label">
                  Default min mask area
                  <button
                    class="settings-help-button"
                    type="button"
                    @click="showSettingHelp('进入标注页面时，SAM2 min mask area 的默认值。小于该面积的 mask contour 会被忽略。', $event)"
                  >?</button>
                </span>
                <el-input-number
                  v-model="settingsDraft.sam2_default_min_mask_area"
                  :max="100000"
                  :min="0"
                  :step="10"
                />
              </label>

              <label class="settings-field">
                <span class="settings-field-label">
                  Default max hole area
                  <button
                    class="settings-help-button"
                    type="button"
                    @click="showSettingHelp('进入标注页面时，SAM2 max hole area 的默认值。小于等于该面积的内部孔洞会被填充。', $event)"
                  >?</button>
                </span>
                <el-input-number
                  v-model="settingsDraft.sam2_default_max_hole_area"
                  :max="100000"
                  :min="0"
                  :step="10"
                />
              </label>
            </section>

            <section class="settings-section">
              <h3 class="settings-section-title">Shortcuts</h3>
              <label class="settings-field">
              <span class="settings-field-label">
                Add polygon vertex shortcut
                <button
                  class="settings-help-button"
                  type="button"
                  @click="showSettingHelp('在 cursor 模式下选中 polygon 后，按住该快捷键并点击高亮边线，可以在该边上新增顶点。', $event)"
                >?</button>
              </span>
              <button
                class="shortcut-capture-button"
                :class="{ listening: shortcutCaptureTarget === 'add_polygon_vertex_shortcut' }"
                type="button"
                @click="startShortcutCapture('add_polygon_vertex_shortcut')"
              >
                {{ shortcutCaptureLabel('add_polygon_vertex_shortcut') }}
              </button>
            </label>

            <label class="settings-field">
              <span class="settings-field-label">
                Delete polygon vertex shortcut
                <button
                  class="settings-help-button"
                  type="button"
                  @click="showSettingHelp('在 cursor 模式下选中 polygon 后，按住该快捷键并点击顶点，可以删除该顶点。polygon 至少保留 3 个顶点。', $event)"
                >?</button>
              </span>
              <button
                class="shortcut-capture-button"
                :class="{ listening: shortcutCaptureTarget === 'delete_polygon_vertex_shortcut' }"
                type="button"
                @click="startShortcutCapture('delete_polygon_vertex_shortcut')"
              >
                {{ shortcutCaptureLabel('delete_polygon_vertex_shortcut') }}
              </button>
            </label>

            <label class="settings-field">
              <span class="settings-field-label">
                Confirm polygon point shortcut
                <button
                  class="settings-help-button"
                  type="button"
                  @click="showSettingHelp('在 polygon 标注模式下，按该键可以在当前鼠标位置添加一个点。', $event)"
                >?</button>
              </span>
              <button
                class="shortcut-capture-button"
                :class="{ listening: shortcutCaptureTarget === 'polygon_confirm_point_shortcut' }"
                type="button"
                @click="startShortcutCapture('polygon_confirm_point_shortcut')"
              >
                {{ shortcutCaptureLabel('polygon_confirm_point_shortcut') }}
              </button>
              <small>In polygon mode, press this key to add a point at the current cursor position.</small>
            </label>

            <label class="settings-field">
              <span class="settings-field-label">
                Pan while drawing shortcut
                <button
                  class="settings-help-button"
                  type="button"
                  @click="showSettingHelp('在 polygon 或 sam2 等绘制模式下，按住该快捷键并拖动鼠标，可以平移画布，不会新增点或改变标注坐标。', $event)"
                >?</button>
              </span>
              <button
                class="shortcut-capture-button"
                :class="{ listening: shortcutCaptureTarget === 'pan_modifier_shortcut' }"
                type="button"
                @click="startShortcutCapture('pan_modifier_shortcut')"
              >
                {{ shortcutCaptureLabel('pan_modifier_shortcut') }}
              </button>
            </label>
            </section>

            <section class="settings-section">
              <h3 class="settings-section-title">SAM2</h3>
              <label class="settings-field settings-checkbox-field">
              <span class="settings-field-label">
                SAM result edge snap
                <button
                  class="settings-help-button"
                  type="button"
                  @click="showSettingHelp('开启后，SAM2 生成的 polygon 中靠近图像边缘的点会自动吸附到图像边缘。', $event)"
                >?</button>
              </span>
              <input v-model="settingsDraft.sam_result_edge_snap_enabled" type="checkbox" />
              <small>When enabled, polygon points generated from SAM2 masks near the image border will snap to the image edge.</small>
            </label>

            <label class="settings-field">
              <span class="settings-field-label">
                SAM result edge snap threshold
                <button
                  class="settings-help-button"
                  type="button"
                  @click="showSettingHelp('SAM2 结果边缘吸附阈值，单位是原始图像像素。只有开启 SAM result edge snap 后生效。', $event)"
                >?</button>
              </span>
              <el-input-number
                v-model="settingsDraft.sam_result_edge_snap_threshold"
                :disabled="!settingsDraft.sam_result_edge_snap_enabled"
                :max="100"
                :min="0"
                :step="1"
              />
            </label>
            </section>

            <el-alert
              v-if="hasShortcutConflict"
              title="Add and delete polygon vertex shortcuts cannot use the same key."
              type="warning"
              show-icon
              :closable="false"
            />
            <el-alert
              v-for="warning in shortcutWarnings"
              :key="warning"
              :title="warning"
              type="warning"
              show-icon
              :closable="false"
            />
          </div>

          <footer class="user-settings-modal-footer">
            <el-button @click="resetSettingsDraft">
              Reset to defaults
            </el-button>
            <el-button @click="closeUserSettings">
              Cancel
            </el-button>
            <el-button type="primary" :loading="settingsLoading" @click="saveUserSettings">
              Save
            </el-button>
          </footer>
        </section>
      </div>
    </Teleport>

    <Teleport to="body">
      <div
        v-if="settingHelpVisible"
        class="settings-help-floating"
        :style="settingHelpFloatingStyle"
        role="tooltip"
        @click.stop
      >
        <p>{{ settingHelpText }}</p>
        <button class="settings-help-floating-close" type="button" @click="closeSettingHelp">
          知道了
        </button>
      </div>
    </Teleport>

    <Teleport to="body">
      <div
        v-if="userLoginVisible"
        class="app-modal-backdrop admin-modal-backdrop"
        tabindex="-1"
        @click.self="closeUserLogin"
        @keydown.esc="closeUserLogin"
      >
        <section class="app-modal admin-modal" role="dialog" aria-modal="true" aria-labelledby="user-login-title">
          <h2 id="user-login-title">User Login</h2>
          <label class="admin-password-field">
            <span>Username</span>
            <el-input
              v-model="usernameInput"
              autofocus
              clearable
              placeholder="Username"
              @keyup.enter="submitUserLogin"
            />
          </label>
          <div class="admin-modal-actions">
            <el-button @click="closeUserLogin">
              Cancel
            </el-button>
            <el-button type="primary" :loading="userLoading" @click="submitUserLogin">
              Login
            </el-button>
          </div>
        </section>
      </div>
    </Teleport>

    <Teleport to="body">
      <div
        v-if="adminLoginVisible"
        class="app-modal-backdrop admin-modal-backdrop"
        tabindex="-1"
        @click.self="closeAdminLogin"
        @keydown.esc="closeAdminLogin"
      >
        <section class="app-modal admin-modal" role="dialog" aria-modal="true" aria-labelledby="admin-login-title">
          <h2 id="admin-login-title">Admin Login</h2>
          <label class="admin-password-field">
            <span>Password</span>
            <el-input
              v-model="adminPassword"
              autofocus
              clearable
              placeholder="Password"
              show-password
              type="password"
              @keyup.enter="submitAdminLogin"
            />
          </label>
          <div class="admin-modal-actions">
            <el-button @click="closeAdminLogin">
              Cancel
            </el-button>
            <el-button type="primary" @click="submitAdminLogin">
              Enter
            </el-button>
          </div>
        </section>
      </div>
    </Teleport>
  </aside>
</template>
