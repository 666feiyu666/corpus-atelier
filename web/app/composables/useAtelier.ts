import { translate, type MessageKey } from '~/i18n'
import type { SettingsPayload, Task } from '~/types'
import { ApiFailure, useApi } from './useApi'

interface Notice {
  text: string
  tone: 'info' | 'warn'
}

interface CredentialTest {
  ok: boolean
}

/**
 * Product-wide state: the settings the boundary reports, the task ledger, and
 * one transient notice. Nothing here decides a task's state transition — the
 * Python services do, and pages re-read them after every action.
 */
export function useAtelier() {
  const api = useApi()
  const settings = useState<SettingsPayload | null>('atelier:settings', () => null)
  const tasks = useState<Task[]>('atelier:tasks', () => [])
  const notice = useState<Notice | null>('atelier:notice', () => null)
  const reachable = useState<boolean>('atelier:reachable', () => true)

  let noticeTimer: ReturnType<typeof setTimeout> | null = null

  const locale = computed(() => settings.value?.language ?? 'en')

  function t(key: MessageKey, values: Record<string, string | number> = {}): string {
    return translate(locale.value, key, values)
  }

  /** For composed keys such as `origin_manual_edit` or `role_palette`. */
  function label(key: string): string {
    return translate(locale.value, key as MessageKey)
  }

  function showNotice(text: string, tone: Notice['tone'] = 'info'): void {
    notice.value = { text, tone }
    if (noticeTimer) clearTimeout(noticeTimer)
    noticeTimer = setTimeout(() => {
      notice.value = null
      noticeTimer = null
    }, tone === 'warn' ? 9000 : 5000)
  }

  /** Report a failure in the interface's own voice; provider text is already short. */
  function report(error: unknown, fallback: MessageKey = 'actionFailed'): void {
    if (error instanceof ApiFailure) {
      if (error.code === 'unreachable') {
        reachable.value = false
        showNotice(t('apiDown'), 'warn')
        return
      }
      reachable.value = true
      showNotice(error.message, 'warn')
      return
    }
    showNotice(t(fallback), 'warn')
  }

  async function loadSettings(): Promise<void> {
    try {
      settings.value = await api.get<SettingsPayload>('/api/v1/settings')
      reachable.value = true
      if (import.meta.client) {
        document.documentElement.lang = settings.value.language
      }
    } catch (error) {
      report(error, 'apiDown')
    }
  }

  async function loadTasks(): Promise<void> {
    try {
      tasks.value = (await api.get<{ tasks: Task[] }>('/api/v1/tasks')).tasks
      reachable.value = true
    } catch (error) {
      report(error, 'apiDown')
    }
  }

  async function setLanguage(language: string): Promise<void> {
    try {
      settings.value = await api.put<SettingsPayload>('/api/v1/settings/language', {
        language,
      })
      if (import.meta.client) {
        document.documentElement.lang = settings.value.language
      }
    } catch (error) {
      report(error)
    }
  }

  async function saveCredential(apiKey: string, remember: boolean): Promise<void> {
    try {
      await api.put('/api/v1/settings/credential', { api_key: apiKey, remember })
      await loadSettings()
    } catch (error) {
      report(error)
    }
  }

  async function clearCredential(): Promise<void> {
    try {
      await api.del('/api/v1/settings/credential')
      await loadSettings()
    } catch (error) {
      report(error)
    }
  }

  async function testCredential(apiKey: string): Promise<boolean | null> {
    try {
      const result = await api.post<CredentialTest>(
        '/api/v1/settings/credential/test',
        apiKey ? { api_key: apiKey } : {},
      )
      return result.ok
    } catch (error) {
      report(error)
      return null
    }
  }

  return {
    api,
    settings,
    tasks,
    notice,
    reachable,
    locale,
    t,
    label,
    showNotice,
    report,
    loadSettings,
    loadTasks,
    setLanguage,
    saveCredential,
    clearCredential,
    testCredential,
  }
}
