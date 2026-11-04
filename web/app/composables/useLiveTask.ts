import type { TaskDetail, TaskStatus } from '~/types'
import { useApi } from './useApi'

// Steps the Python runtime may still finish; while any is true the page polls
// quickly, otherwise it refreshes slowly so a second window stays honest.
const BUSY_STATUSES: TaskStatus[] = [
  'created',
  'discussing_request',
  'extracting',
  'generating_image',
]

/**
 * One task's live view. Every action re-reads from the boundary rather than
 * guessing the new state, so an interrupted or remote outcome is never invented
 * by the browser.
 */
export function useLiveTask(runId: string) {
  const api = useApi()
  const detail = ref<TaskDetail | null>(null)
  const failure = ref<string | null>(null)
  const loading = ref(true)

  let timer: ReturnType<typeof setTimeout> | null = null
  let stopped = false

  const task = computed(() => detail.value?.task ?? null)
  const session = computed(() => detail.value?.session ?? null)

  const live = computed(() => {
    const value = detail.value
    if (!value) return false
    if (value.task.running) return true
    if (BUSY_STATUSES.includes(value.task.status)) return true
    return Boolean(value.session?.pending_turn)
  })

  async function refresh(): Promise<void> {
    try {
      detail.value = await api.get<TaskDetail>(`/api/v1/tasks/${runId}`)
      failure.value = null
    } catch (error) {
      failure.value = error instanceof Error ? error.message : String(error)
    } finally {
      loading.value = false
    }
  }

  function loop(): void {
    if (stopped) return
    timer = setTimeout(async () => {
      await refresh()
      loop()
    }, live.value ? 1200 : 6000)
  }

  onMounted(async () => {
    await refresh()
    loop()
  })

  onUnmounted(() => {
    stopped = true
    if (timer) clearTimeout(timer)
  })

  return { detail, task, session, loading, failure, live, refresh }
}
