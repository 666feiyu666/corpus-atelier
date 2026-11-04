<script setup lang="ts">
import type { ImageResult, Session, Task } from '~/types'

const props = defineProps<{
  task: Task
  session: Session
  busy: boolean
}>()
const emit = defineEmits<{ changed: [] }>()

const { t, label, api, report, showNotice } = useAtelier()

type Mode = 'reprompt' | 'edit' | 'compare'

const working = ref('')
const archiving = ref<ImageResult | null>(null)
const openOn = ref<string | null>(null)
const mode = ref<Mode>('reprompt')
const promptDraft = ref('')
const instruction = ref('')
const baseChoice = ref('')

const results = computed(() => props.session.image_results)
const disabled = computed(() => props.busy || Boolean(working.value))

const currentPrompt = computed(
  () => props.session.prompt_revisions.find(
    (item) => item.id === props.session.current_prompt_revision_id,
  )?.prompt_text ?? '',
)

/** Reference images available as the comparison base, newest result first. */
const baseCandidates = computed(() =>
  props.session.image_results.map((item) => ({
    id: item.id,
    text: `${t('resultShort')} ${item.id.slice(-4)}`,
  })),
)

function revisionNumber(id: string): number {
  const index = props.session.prompt_revisions.findIndex((item) => item.id === id)
  return index < 0 ? 0 : index + 1
}

function openComposer(result: ImageResult, next: Mode): void {
  if (openOn.value === result.id && mode.value === next) {
    openOn.value = null
    return
  }
  openOn.value = result.id
  mode.value = next
  instruction.value = ''
  baseChoice.value = ''
  // The editor starts from the prompt that produced this result, which is what
  // "change the prompt and regenerate" means in practice.
  promptDraft.value = currentPrompt.value
}

async function run(key: string, work: () => Promise<void>): Promise<void> {
  working.value = key
  try {
    await work()
  } catch (error) {
    report(error)
  } finally {
    working.value = ''
  }
}

function attemptBody(action: 'generate' | 'edit', revision: string | null, extra: Record<string, unknown> = {}) {
  return {
    action,
    expected_revision: revision,
    reference_image_ids: [],
    reference_roles: {},
    ...extra,
  }
}

/** Path 1 — regenerate with the prompt exactly as it stands. */
function regenerate(result: ImageResult): Promise<void> {
  return run(`regenerate-${result.id}`, async () => {
    await api.post(
      `/api/v1/tasks/${props.task.run_id}/image-attempts`,
      attemptBody('generate', props.session.current_prompt_revision_id),
    )
    emit('changed')
  })
}

/** Path 2 — edit the prompt, save it as a new revision, then freeze a request. */
function reprompt(result: ImageResult): Promise<void> {
  return run(`reprompt-${result.id}`, async () => {
    const text = promptDraft.value.trim()
    if (!text) return
    const saved = await api.post<{ session: Session | null }>(
      `/api/v1/tasks/${props.task.run_id}/prompt-revisions`,
      {
        prompt_text: promptDraft.value,
        expected_revision: props.session.current_prompt_revision_id,
      },
    )
    const revision = saved.session?.current_prompt_revision_id ?? null
    await api.post(
      `/api/v1/tasks/${props.task.run_id}/image-attempts`,
      attemptBody('generate', revision),
    )
    openOn.value = null
    emit('changed')
  })
}

/** Path 3 — continue from this image with an edit instruction. */
function editFrom(result: ImageResult): Promise<void> {
  return run(`edit-${result.id}`, async () => {
    await api.post(
      `/api/v1/tasks/${props.task.run_id}/image-attempts`,
      attemptBody('edit', props.session.current_prompt_revision_id, {
        source_image_id: result.id,
        edit_instruction: instruction.value,
      }),
    )
    openOn.value = null
    emit('changed')
  })
}

/** Compare this result with an earlier image and ask for a new prompt. */
function compare(result: ImageResult): Promise<void> {
  return run(`compare-${result.id}`, async () => {
    await api.post(`/api/v1/tasks/${props.task.run_id}/refine-turns`, {
      result_image_id: result.id,
      base_image_id: baseChoice.value || null,
    })
    openOn.value = null
    emit('changed')
  })
}

function select(result: ImageResult): Promise<void> {
  return run(`select-${result.id}`, async () => {
    await api.post(`/api/v1/tasks/${props.task.run_id}/results/${result.id}/select`)
    emit('changed')
  })
}

function useAsReference(result: ImageResult): void {
  // The reference tray owns the fine-grained roles; this just points at it.
  showNotice(t('referenceHint'))
  openOn.value = null
}

function download(result: ImageResult): string {
  return api.absolute(result.media_url)
}
</script>

<template>
  <section class="wall" aria-labelledby="results-heading">
    <header class="wall-head">
      <h2 id="results-heading">{{ t('resultsHeading') }}</h2>
      <p class="hint">{{ t('wallHint') }}</p>
    </header>

    <p v-if="!results.length" class="emptiness">
      <span class="emptiness-title">{{ t('noResults') }}</span>
      <span class="hint">{{ t('noResultsHint') }}</span>
    </p>

    <ol v-else class="wall-grid">
      <li
        v-for="result in results"
        :key="result.id"
        class="plate"
        :class="{ 'is-active': result.is_active }"
      >
        <a class="plate-image" :href="download(result)" target="_blank" rel="noopener">
          <img :src="api.absolute(result.media_url)" :alt="result.label" loading="lazy" />
        </a>

        <div class="plate-body">
          <p class="plate-line">
            {{ t('resultMeta', {
              revision: revisionNumber(result.prompt_revision_id),
              action: label(`action_${result.action}`),
            }) }}
            <span v-if="result.is_active" class="plate-flag">{{ t('activeResult') }}</span>
          </p>
          <p v-if="result.parent_image_id" class="hint">
            {{ t('parentMeta', { source: result.parent_image_id.slice(-4) }) }}
          </p>

          <div class="plate-actions">
            <button
              v-if="!result.is_active"
              class="btn-quiet"
              type="button"
              :disabled="disabled"
              @click="select(result)"
            >
              {{ t('selectResult') }}
            </button>
            <button
              class="btn-quiet"
              type="button"
              :disabled="disabled"
              @click="regenerate(result)"
            >
              {{ t('regenerate') }}
            </button>
            <button
              class="btn-quiet"
              type="button"
              :disabled="disabled"
              :aria-expanded="openOn === result.id && mode === 'reprompt'"
              @click="openComposer(result, 'reprompt')"
            >
              {{ t('reprompt') }}
            </button>
            <button
              class="btn-quiet"
              type="button"
              :disabled="disabled"
              :aria-expanded="openOn === result.id && mode === 'edit'"
              @click="openComposer(result, 'edit')"
            >
              {{ t('continueEdit') }}
            </button>
            <button
              class="btn-quiet"
              type="button"
              :disabled="disabled || results.length < 2"
              :aria-expanded="openOn === result.id && mode === 'compare'"
              @click="openComposer(result, 'compare')"
            >
              {{ t('compareAction') }}
            </button>
            <a class="btn-quiet" :href="download(result)" download>{{ t('download') }}</a>
            <button class="btn-quiet" type="button" :disabled="disabled" @click="archiving = result">
              {{ t('archive') }}
            </button>
          </div>

          <form
            v-if="openOn === result.id && mode === 'reprompt'"
            class="composer"
            @submit.prevent="reprompt(result)"
          >
            <label class="field" :for="`reprompt-${result.id}`">{{ t('repromptLabel') }}</label>
            <textarea
              :id="`reprompt-${result.id}`"
              v-model="promptDraft"
              rows="6"
              :disabled="disabled"
            />
            <p class="hint">{{ t('promptExactHint') }}</p>
            <div class="composer-foot">
              <button
                class="btn btn-primary"
                type="submit"
                :disabled="disabled || !promptDraft.trim()"
              >
                {{ t('repromptSubmit') }}
              </button>
              <button class="btn-quiet" type="button" @click="openOn = null">{{ t('cancel') }}</button>
            </div>
          </form>

          <form
            v-else-if="openOn === result.id && mode === 'edit'"
            class="composer"
            @submit.prevent="editFrom(result)"
          >
            <label class="field" :for="`edit-${result.id}`">{{ t('editInstruction') }}</label>
            <textarea
              :id="`edit-${result.id}`"
              v-model="instruction"
              rows="4"
              :disabled="disabled"
              :placeholder="t('editPlaceholder')"
            />
            <p class="hint">{{ t('editCanvasHint') }}</p>
            <div class="composer-foot">
              <button
                class="btn btn-primary"
                type="submit"
                :disabled="disabled || !instruction.trim()"
              >
                {{ t('reviewEditRequest') }}
              </button>
              <button class="btn-quiet" type="button" @click="openOn = null">{{ t('cancel') }}</button>
            </div>
          </form>

          <form
            v-else-if="openOn === result.id && mode === 'compare'"
            class="composer"
            @submit.prevent="compare(result)"
          >
            <label class="field" :for="`base-${result.id}`">{{ t('compareBase') }}</label>
            <select :id="`base-${result.id}`" v-model="baseChoice" :disabled="disabled">
              <option value="">{{ t('compareAuto') }}</option>
              <option v-for="item in baseCandidates" :key="item.id" :value="item.id">
                {{ item.text }}
              </option>
            </select>
            <p class="hint">{{ t('compareHint') }}</p>
            <div class="composer-foot">
              <button class="btn btn-primary" type="submit" :disabled="disabled">
                {{ t('compareSubmit') }}
              </button>
              <button class="btn-quiet" type="button" @click="openOn = null">{{ t('cancel') }}</button>
            </div>
          </form>
        </div>
      </li>
    </ol>

    <ArchiveDialog
      v-if="archiving"
      :run-id="task.run_id"
      :image-id="archiving.id"
      @close="archiving = null"
      @archived="emit('changed')"
    />
  </section>
</template>
