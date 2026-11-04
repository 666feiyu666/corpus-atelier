<script setup lang="ts">
import type { CorpusFacet } from '~/types'

const props = defineProps<{ runId: string; imageId: string }>()
const emit = defineEmits<{ close: []; archived: [] }>()

const { t, api, report, locale, showNotice } = useAtelier()

const facets = ref<CorpusFacet[]>([])
const selected = ref<string[]>([])
const busy = ref(false)

async function load(): Promise<void> {
  try {
    const data = await api.get<{ facets: CorpusFacet[] }>('/api/v1/corpus/taxonomy')
    facets.value = data.facets
  } catch (error) {
    report(error)
  }
}

function toggle(id: string): void {
  selected.value = selected.value.includes(id)
    ? selected.value.filter((item) => item !== id)
    : [...selected.value, id]
}

function tagLabel(tag: { en: string; zh: string }): string {
  return locale.value === 'zh-CN' ? tag.zh : tag.en
}

function facetLabel(facet: CorpusFacet): string {
  return locale.value === 'zh-CN' ? facet.label.zh : facet.label.en
}

async function confirm(): Promise<void> {
  if (!selected.value.length) {
    report(new Error(t('archiveNeedsTag')))
    return
  }
  busy.value = true
  try {
    await api.post(`/api/v1/tasks/${props.runId}/archive`, {
      tags: selected.value,
      image_id: props.imageId,
    })
    showNotice(t('archived'))
    emit('archived')
    emit('close')
  } catch (error) {
    report(error)
  } finally {
    busy.value = false
  }
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') emit('close')
}

onMounted(load)
</script>

<template>
  <div class="scrim" @click.self="emit('close')" @keydown="onKeydown">
    <section class="dialog" role="dialog" aria-modal="true" aria-labelledby="archive-heading">
      <header class="row" style="justify-content: space-between">
        <h2 id="archive-heading">{{ t('archiveHeading') }}</h2>
        <button class="btn-quiet" type="button" @click="emit('close')">{{ t('close') }}</button>
      </header>
      <p class="hint" style="margin-top: 8px">{{ t('archiveHint') }}</p>

      <div class="stack" style="margin-top: 12px; max-height: 46vh; overflow-y: auto">
        <div v-for="facet in facets" :key="facet.id">
          <p class="ledger-day">{{ facetLabel(facet) }}</p>
          <div class="row" style="gap: 6px 14px">
            <label
              v-for="tag in facet.tags"
              :key="tag.id"
              class="row"
              style="gap: 5px; font-size: 13px"
            >
              <input
                type="checkbox"
                :checked="selected.includes(tag.id)"
                @change="toggle(tag.id)"
              />
              <span>{{ tagLabel(tag) }}</span>
            </label>
          </div>
        </div>
      </div>

      <hr class="rule" />
      <div class="row">
        <button class="btn btn-primary" type="button" :disabled="busy" @click="confirm">
          {{ t('archiveConfirm') }}
        </button>
        <button class="btn-quiet" type="button" :disabled="busy" @click="selected = []">
          {{ t('clearLabels') }}
        </button>
        <span class="eyebrow">{{ selected.length }}</span>
      </div>
    </section>
  </div>
</template>
