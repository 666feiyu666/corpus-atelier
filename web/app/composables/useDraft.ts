interface DraftState {
  text: string
  base: string | null
}

const STORAGE_KEY = 'atelier:drafts'

function readStored(): Record<string, DraftState> {
  if (!import.meta.client) return {}
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as Record<string, DraftState>) : {}
  } catch {
    return {}
  }
}

/**
 * The unsaved prompt draft, per task, surviving a route change and a reload.
 *
 * A draft is interface state only: the committed revision is the truth, and
 * nothing here ever writes to the task. It exists because losing an unsaved
 * edit on navigation is exactly the failure the product contracts forbid.
 */
export function useDraft(runId: string) {
  const drafts = useState<Record<string, DraftState>>('atelier:drafts', readStored)

  const draft = computed<DraftState | null>(() => drafts.value[runId] ?? null)

  function persist(next: Record<string, DraftState>): void {
    drafts.value = next
    if (!import.meta.client) return
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    } catch {
      // A full or disabled session store must never break editing.
    }
  }

  function store(text: string, base: string | null): void {
    persist({ ...drafts.value, [runId]: { text, base } })
  }

  function clear(): void {
    if (!(runId in drafts.value)) return
    const next = { ...drafts.value }
    delete next[runId]
    persist(next)
  }

  return { draft, store, clear }
}
