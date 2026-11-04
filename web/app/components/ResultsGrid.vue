<script setup lang="ts">
import type { ImageResult, Session, Task } from '~/types'

const props = defineProps<{
  task: Task
  session: Session
  busy: boolean
}>()
const emit = defineEmits<{ changed: []; edit: [imageId: string] }>()

const { t, label, api, report } = useAtelier()
const working = ref('')
const archiving = ref<ImageResult | null>(null)

const results = computed(() => props.session.image_results)

function revisionNumber(id: string): number {
  const index = props.session.prompt_revisions.findIndex((item) => item.id === id)
  return index < 0 ? 0 : index + 1
}

function shortId(id: string | null): string {
  return id ? id.slice(-4) : '—'
}

async function select(result: ImageResult): Promise<void> {
  working.value = result.id
  try {
    await api.post(`/api/v1/tasks/${props.task.run_id}/results/${result.id}/select`)
    emit('changed')
  } catch (error) {
    report(error)
  } finally {
    working.value = ''
  }
}

async function refine(result: ImageResult): Promise<void> {
  working.value = result.id
  try {
    await api.post(`/api/v1/tasks/${props.task.run_id}/refine-turns`, {
      result_image_id: result.id,
    })
    emit('changed')
  } catch (error) {
    report(error)
  } finally {
    working.value = ''
  }
}

function download(result: ImageResult): string {
  return api.absolute(result.media_url)
}

const disabled = computed(() => props.busy || Boolean(working.value))
</script>

<template>
  <section class="panel" aria-labelledby="results-heading">
    <div class="panel-head">
      <h2 id="results-heading">{{ t('resultsHeading') }} · {{ results.length }}</h2>
    </div>

    <p v-if="!results.length" class="hint">{{ t('noResults') }}</p>

    <div v-else class="results">
      <article
        v-for="result in results"
        :key="result.id"
        class="result"
        :class="{ 'is-active': result.is_active }"
      >
        <a :href="download(result)" target="_blank" rel="noopener">
          <img :src="api.absolute(result.media_url)" :alt="result.label" />
        </a>
        <p class="meta">
          {{ t('resultMeta', {
            revision: revisionNumber(result.prompt_revision_id),
            action: label(`action_${result.action}`),
          }) }}
          <template v-if="result.is_active"> · {{ t('activeResult') }}</template>
        </p>
        <p v-if="result.parent_image_id" class="meta">
          {{ t('parentMeta', { source: shortId(result.parent_image_id) }) }}
        </p>
        <div class="row">
          <button
            v-if="!result.is_active"
            class="btn-quiet"
            type="button"
            :disabled="disabled"
            @click="select(result)"
          >
            {{ t('selectResult') }}
          </button>
          <button class="btn-quiet" type="button" :disabled="disabled" @click="emit('edit', result.id)">
            {{ t('editThis') }}
          </button>
          <button
            v-if="session.entry_mode === 'image'"
            class="btn-quiet"
            type="button"
            :disabled="disabled"
            @click="refine(result)"
          >
            {{ t('refine') }}
          </button>
          <a class="btn-quiet" :href="download(result)" download>{{ t('download') }}</a>
          <button class="btn-quiet" type="button" :disabled="disabled" @click="archiving = result">
            {{ t('archive') }}
          </button>
        </div>
      </article>
    </div>

    <ArchiveDialog
      v-if="archiving"
      :run-id="task.run_id"
      :image-id="archiving.id"
      @close="archiving = null"
      @archived="emit('changed')"
    />
  </section>
</template>
