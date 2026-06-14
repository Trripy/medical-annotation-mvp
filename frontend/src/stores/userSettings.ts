import { defineStore } from 'pinia'

import { apiUrl } from '../utils/api'

export type ToolType = 'cursor' | 'rectangle' | 'polygon' | 'sam2'
export type Shortcut = string
export type SamAcceptNextTool = 'keep_current' | 'default_tool' | ToolType
export type Sam2ModelName = 'sam2_hiera_tiny' | 'sam2_hiera_small' | 'sam2_hiera_base_plus' | 'sam2_hiera_large'
export type Sam2Candidate = 'best' | '0' | '1' | '2'

export type UserSettings = {
  edge_snap_threshold: number
  default_tool: ToolType
  add_polygon_vertex_shortcut: Shortcut
  delete_polygon_vertex_shortcut: Shortcut
  pan_modifier_shortcut: Shortcut
  polygon_confirm_point_shortcut: Shortcut
  sam_result_edge_snap_enabled: boolean
  sam_result_edge_snap_threshold: number
  sam_accept_next_tool: SamAcceptNextTool
  remember_last_frame_per_job: boolean
  keep_view_transform_on_frame_switch: boolean
  sam2_default_model: Sam2ModelName
  sam2_default_multimask_output: boolean
  sam2_default_show_prompt_points: boolean
  sam2_default_candidate: Sam2Candidate
  sam2_default_polygon_epsilon: number
  sam2_default_mask_threshold: number
  sam2_default_min_mask_area: number
  sam2_default_max_hole_area: number
}

export type UserSettingsResponse = UserSettings & {
  username: string
}

export const DEFAULT_USER_SETTINGS: UserSettings = {
  edge_snap_threshold: 5,
  default_tool: 'sam2',
  add_polygon_vertex_shortcut: 'shift',
  delete_polygon_vertex_shortcut: 'alt',
  pan_modifier_shortcut: 'ctrl',
  polygon_confirm_point_shortcut: 'space',
  sam_result_edge_snap_enabled: false,
  sam_result_edge_snap_threshold: 5,
  sam_accept_next_tool: 'keep_current',
  remember_last_frame_per_job: true,
  keep_view_transform_on_frame_switch: true,
  sam2_default_model: 'sam2_hiera_large',
  sam2_default_multimask_output: true,
  sam2_default_show_prompt_points: true,
  sam2_default_candidate: 'best',
  sam2_default_polygon_epsilon: 0.002,
  sam2_default_mask_threshold: 0,
  sam2_default_min_mask_area: 100,
  sam2_default_max_hole_area: 0,
}

const SAM2_MODELS: Sam2ModelName[] = [
  'sam2_hiera_tiny',
  'sam2_hiera_small',
  'sam2_hiera_base_plus',
  'sam2_hiera_large',
]
const SAM2_CANDIDATES: Sam2Candidate[] = ['best', '0', '1', '2']

function cloneDefaultSettings(): UserSettings {
  return { ...DEFAULT_USER_SETTINGS }
}

async function readErrorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const payload = await response.json()
    return typeof payload.detail === 'string' ? payload.detail : fallback
  } catch {
    return fallback
  }
}

function normalizeSettings(settings: Partial<UserSettings>): UserSettings {
  const sam2DefaultModel = SAM2_MODELS.includes(settings.sam2_default_model as Sam2ModelName)
    ? settings.sam2_default_model as Sam2ModelName
    : DEFAULT_USER_SETTINGS.sam2_default_model
  const sam2DefaultCandidate = SAM2_CANDIDATES.includes(settings.sam2_default_candidate as Sam2Candidate)
    ? settings.sam2_default_candidate as Sam2Candidate
    : DEFAULT_USER_SETTINGS.sam2_default_candidate

  return {
    ...cloneDefaultSettings(),
    ...settings,
    edge_snap_threshold: Number.isFinite(Number(settings.edge_snap_threshold))
      ? Number(settings.edge_snap_threshold)
      : DEFAULT_USER_SETTINGS.edge_snap_threshold,
    sam_result_edge_snap_enabled: Boolean(settings.sam_result_edge_snap_enabled),
    sam_result_edge_snap_threshold: Number.isFinite(Number(settings.sam_result_edge_snap_threshold))
      ? Number(settings.sam_result_edge_snap_threshold)
      : DEFAULT_USER_SETTINGS.sam_result_edge_snap_threshold,
    remember_last_frame_per_job: settings.remember_last_frame_per_job !== undefined
      ? Boolean(settings.remember_last_frame_per_job)
      : DEFAULT_USER_SETTINGS.remember_last_frame_per_job,
    keep_view_transform_on_frame_switch: settings.keep_view_transform_on_frame_switch !== undefined
      ? Boolean(settings.keep_view_transform_on_frame_switch)
      : DEFAULT_USER_SETTINGS.keep_view_transform_on_frame_switch,
    sam2_default_model: sam2DefaultModel,
    sam2_default_multimask_output: settings.sam2_default_multimask_output !== undefined
      ? Boolean(settings.sam2_default_multimask_output)
      : DEFAULT_USER_SETTINGS.sam2_default_multimask_output,
    sam2_default_show_prompt_points: settings.sam2_default_show_prompt_points !== undefined
      ? Boolean(settings.sam2_default_show_prompt_points)
      : DEFAULT_USER_SETTINGS.sam2_default_show_prompt_points,
    sam2_default_candidate: sam2DefaultCandidate,
    sam2_default_polygon_epsilon: Number.isFinite(Number(settings.sam2_default_polygon_epsilon))
      ? Number(settings.sam2_default_polygon_epsilon)
      : DEFAULT_USER_SETTINGS.sam2_default_polygon_epsilon,
    sam2_default_mask_threshold: Number.isFinite(Number(settings.sam2_default_mask_threshold))
      ? Number(settings.sam2_default_mask_threshold)
      : DEFAULT_USER_SETTINGS.sam2_default_mask_threshold,
    sam2_default_min_mask_area: Number.isFinite(Number(settings.sam2_default_min_mask_area))
      ? Number(settings.sam2_default_min_mask_area)
      : DEFAULT_USER_SETTINGS.sam2_default_min_mask_area,
    sam2_default_max_hole_area: Number.isFinite(Number(settings.sam2_default_max_hole_area))
      ? Number(settings.sam2_default_max_hole_area)
      : DEFAULT_USER_SETTINGS.sam2_default_max_hole_area,
  }
}

export const useUserSettingsStore = defineStore('userSettings', {
  state: () => ({
    settings: cloneDefaultSettings(),
    loading: false,
    loadedUsername: '',
    error: '',
  }),
  actions: {
    resetToDefaults() {
      this.settings = cloneDefaultSettings()
      this.loadedUsername = ''
      this.error = ''
    },
    async loadSettings(username: string) {
      const normalizedUsername = username.trim()
      if (!normalizedUsername) {
        this.resetToDefaults()
        return true
      }

      this.loading = true
      this.error = ''

      try {
        const query = new URLSearchParams({ username: normalizedUsername })
        const response = await fetch(apiUrl(`/api/users/me/settings?${query.toString()}`))
        if (!response.ok) {
          throw new Error(await readErrorMessage(response, 'Load user settings failed'))
        }

        const payload = await response.json() as UserSettingsResponse
        this.settings = normalizeSettings(payload)
        this.loadedUsername = payload.username
        return true
      } catch (error) {
        this.settings = cloneDefaultSettings()
        this.loadedUsername = ''
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return false
      } finally {
        this.loading = false
      }
    },
    async saveSettings(username: string, settings: UserSettings) {
      const normalizedUsername = username.trim()
      if (!normalizedUsername) {
        this.error = 'Username is required'
        return false
      }

      this.loading = true
      this.error = ''

      try {
        const response = await fetch(apiUrl('/api/users/me/settings'), {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            username: normalizedUsername,
            ...settings,
          }),
        })

        if (!response.ok) {
          throw new Error(await readErrorMessage(response, 'Save user settings failed'))
        }

        const payload = await response.json() as UserSettingsResponse
        this.settings = normalizeSettings(payload)
        this.loadedUsername = payload.username
        return true
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unknown error'
        return false
      } finally {
        this.loading = false
      }
    },
  },
})
