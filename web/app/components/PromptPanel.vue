<script setup lang="ts">
import type { Proposal, Revision, Session, Task } from '~/types'

const props = defineProps<{
  task: Task
  session: Session
  busy: boolean
}>()

const emit = defineEmits<{ changed: [] }>()

const { t, label, api, report, showNotice } = useAtelier()
const { draft: storedDraft, store: storeDraft, clear: clearDraft } = useDraft(props.task.run_id)

const draft = ref('')
const base = ref<string | null>(null)
const working = ref(false)
const openHistory = ref(true)
const explaining = ref<string | null>(null)

const current = computed<Revision | null>(() => {
  const id = props.session.current_prompt_revision_id
  return props.session.prompt_revisions.find((item) => item.id === id) ?? null
})

const dirty = computed(() => current.value !== null && draft.value !== current.value.prompt_text)

const stale = computed(() => base.value !== props.session.current_prompt_revision_id)

const proposals = computed<Proposal[]>(() =>
  props.session.prompt_proposals.filter((item) => !item.adopted_revision_id),
)

// Follow a newer revision unless a stored draft exists; a draft is the person's
// unsaved edit and outranks any revision that arrived while it was being written.
watch(
  [() => props.session.current_prompt_revision_id, () => props.session.prompt_revisions.length],
  () => {
    const stored = storedDraft.value
    if (stored) {
      draft.value = stored.text
      base.value = stored.base
      return
    }
    const revision = current.value
    draft.value = revision?.prompt_text ?? ''
    base.value = revision?.id ?? null
  },
  { immediate: true },
)

function onInput(): void {
  storeDraft(draft.value, base.value)
}

function reload(): void {
  clearDraft()
  draft.value = current.value?.prompt_text ?? ''
  base.value = current.value?.id ?? null
}

async function save(): Promise<void> {
  if (!current.value || !dirty.value) return
  working.value = true
  try {
    await api.post(`/api/v1/tasks/${props.task.run_id}/prompt-revisions`, {
      prompt_text: draft.value,
      expected_revision: props.session.current_prompt_revision_id,
    })
    clearDraft()
    emit('changed')
  } catch (error) {
    report(error)
  } finally {
    working.value = false
  }
}

async function askForRevision(): Promise<void> {
  working.value = true
  try {
    await api.post(`/api/v1/tasks/${props.task.run_id}/prompt-proposals`, {
      kind: 'generate',
    })
    emit('changed')
  } catch (error) {
    report(error)
  } finally {
    working.value = false
  }
}

async function adopt(proposal: Proposal): Promise<void> {
  working.value = true
  try {
    await api.post(
      `/api/v1/tasks/${props.task.run_id}/prompt-proposals/${proposal.id}/adopt`,
      { expected_revision: props.session.current_prompt_revision_id },
    )
    clearDraft()
    emit('changed')
  } catch (error) {
    report(error)
  } finally {
    working.value = false
  }
}

async function dismiss(proposal: Proposal): Promise<void> {
  // An un-adopted proposal is interface state only: nothing is stored to delete.
  showNotice(t('dismissProposal'))
  explaining.value = explaining.value === proposal.id ? null : proposal.id
}

async function restore(revision: Revision): Promise<void> {
  working.value = true
  try {
    await api.post(
      `/api/v1/tasks/${props.task.run_id}/prompt-revisions/${revision.id}/restore`,
      { expected_revision: props.session.current_prompt_revision_id },
    )
    clearDraft()
    emit('changed')
  } catch (error) {
    report(error)
  } finally {
    working.value = false
  }
}

function revisionNumber(id: string | null): number {
  const index = props.session.prompt_revisions.findIndex((item) => item.id === id)
  return index < 0 ? 0 : index + 1
}

const disabled = computed(() => props.busy || working.value)
</script>

<template>
  <section class="panel" aria-labelledby="prompt-heading">
    <div class="panel-head">
      <h2 id="prompt-heading">{{ t('promptHeading') }}</h2>
      <span class="eyebrow">
        {{ t('revisionCount', {
          number: revisionNumber(session.current_prompt_revision_id),
          origin: current ? label(`origin_${current.origin}`) : '—',
        }) }}
      </span>
    </div>

    <textarea
      v-model="draft"
      rows="9"
      :disabled="disabled"
      :aria-label="t('promptHeading')"
      @input="onInput"
    />

    <div class="row" style="margin-top: 8px">
      <button class="btn btn-primary" type="button" :disabled="disabled || !dirty" @click="save">
        {{ t('savePrompt') }}
      </button>
      <button class="btn" type="button" :disabled="disabled || !dirty" @click="reload">
        {{ t('reloadPrompt') }}
      </button>
      <button class="btn" type="button" :disabled="disabled" @click="askForRevision">
        {{ t('reviseWithModel') }}
      </button>
      <span v-if="dirty" class="eyebrow">{{ t('dirtyDraft') }}</span>
      <span v-else-if="stale" class="eyebrow" style="color: var(--signal)">
        {{ t('savePrompt') }} · {{ t('revisionCount', {
          number: revisionNumber(session.current_prompt_revision_id),
          origin: '',
        }) }}
      </span>
    </div>

    <p v-if="current?.negative_prompt" class="hint" style="margin-top: 12px">
      {{ t('negativePrompt') }}
    </p>
    <pre v-if="current?.negative_prompt" class="proof-text">{{ current.negative_prompt }}</pre>

    <div v-if="current?.visible_copy.length" style="margin-top: 12px">
      <p class="hint">{{ t('visibleCopy') }}</p>
      <div v-for="(item, index) in current.visible_copy" :key="index" class="revision">
        <pre class="revision-text is-open">{{ item.text }}</pre>
        <p class="revision-meta">
          <span v-if="item.language">{{ item.language }}</span>
          <span v-if="item.uncertain" style="color: var(--signal)">?</span>
        </p>
      </div>
    </div>

    <div v-if="current?.uncertainties.length" style="margin-top: 12px">
      <p class="hint">{{ t('uncertainties') }}</p>
      <ul style="margin: 0 0 0 18px; font-size: 13.5px">
        <li v-for="(item, index) in current.uncertainties" :key="index">{{ item }}</li>
      </ul>
    </div>

    <div v-for="proposal in proposals" :key="proposal.id" class="proof">
      <div class="proof-head">
        <strong style="font-size: 13.5px">{{ t('proposalHeading') }}</strong>
        <span class="eyebrow">{{ proposal.kind }}</span>
      </div>
      <pre class="proof-text">{{ proposal.prompt_text }}</pre>
      <p v-if="proposal.notes" class="hint" style="margin-top: 8px">{{ proposal.notes }}</p>
      <div class="row" style="margin-top: 12px">
        <button class="btn btn-primary" type="button" :disabled="disabled" @click="adopt(proposal)">
          {{ t('adoptProposal') }}
        </button>
        <button class="btn-quiet" type="button" @click="dismiss(proposal)">
          {{ t('dismissProposal') }}
        </button>
      </div>
    </div>

    <details
      v-if="session.prompt_revisions.length > 1"
      style="margin-top: 18px"
      :open="openHistory"
      @toggle="openHistory = ($event.target as HTMLDetailsElement).open"
    >
      <summary class="dim" style="cursor: pointer; font-size: 13.5px">
        {{ t('revisionHistory') }} · {{ session.prompt_revisions.length }}
      </summary>
      <div style="margin-top: 12px">
        <article
          v-for="revision in [...session.prompt_revisions].reverse()"
          :key="revision.id"
          class="revision"
          :class="{ 'is-current': revision.id === session.current_prompt_revision_id }"
        >
          <p class="revision-meta">
            <span>{{ t('revisionCount', {
              number: revisionNumber(revision.id),
              origin: label(`origin_${revision.origin}`),
            }) }}</span>
            <span v-if="revision.note">· {{ revision.note }}</span>
          </p>
          <pre class="revision-text" :class="{ 'is-open': explaining === revision.id }">{{ revision.prompt_text }}</pre>
          <div class="row" style="margin-top: 4px">
            <button
              class="btn-quiet"
              type="button"
              @click="explaining = explaining === revision.id ? null : revision.id"
            >
              {{ explaining === revision.id ? '−' : '+' }}
            </button>
            <button
              v-if="revision.id !== session.current_prompt_revision_id"
              class="btn-quiet"
              type="button"
              :disabled="disabled"
              @click="restore(revision)"
            >
              {{ t('restoreRevision') }}
            </button>
          </div>
        </article>
      </div>
    </details>
  </section>
</template>
