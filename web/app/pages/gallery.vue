<script setup lang="ts">
import type { CorpusFacet, CorpusRecord, CorpusSearch, CorpusTag } from '~/types'

const { t, api, report, locale, showNotice } = useAtelier()

const PAGE_SIZE = 12

const query = ref('')
const collection = ref('')
const page = ref(0)
const payload = ref<CorpusSearch | null>(null)
const facets = ref<CorpusFacet[]>([])
const loading = ref(false)
const openRecord = ref<CorpusRecord | null>(null)
const drawer = ref<HTMLElement | null>(null)

const collections = computed(
  () => facets.value.find((facet) => facet.id === 'collection')?.tags ?? [],
)
const total = computed(() => payload.value?.total ?? 0)
const pages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const records = computed(() => payload.value?.records ?? [])

async function load(): Promise<void> {
  loading.value = true
  try {
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      page: String(page.value),
    })
    const text = query.value.trim()
    if (text) params.set('q', text)
    if (collection.value) params.set('tags', collection.value)
    payload.value = await api.get<CorpusSearch>(`/api/v1/corpus/search?${params.toString()}`)
  } catch (error) {
    report(error)
  } finally {
    loading.value = false
  }
}

async function loadTaxonomy(): Promise<void> {
  try {
    const data = await api.get<{ facets: CorpusFacet[] }>('/api/v1/corpus/taxonomy')
    facets.value = data.facets
  } catch (error) {
    report(error)
  }
}

function search(): void {
  page.value = 0
  load()
}

function chooseCollection(id: string): void {
  collection.value = collection.value === id ? '' : id
  page.value = 0
  load()
}

function step(delta: number): void {
  const next = page.value + delta
  if (next < 0 || next >= pages.value) return
  page.value = next
  load()
}

function tagLabel(id: string): string {
  for (const facet of facets.value) {
    const hit = facet.tags.find((tag) => tag.id === id)
    if (hit) return label(hit)
  }
  return id
}

function label(tag: CorpusTag): string {
  return locale.value === 'zh-CN' ? tag.zh : tag.en
}

function excerpt(text: string, size = 150): string {
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length <= size ? flat : `${flat.slice(0, size)}…`
}

function imageUrl(record: CorpusRecord): string | null {
  return record.image ? api.absolute(record.image.media_url) : null
}

async function open(record: CorpusRecord): Promise<void> {
  openRecord.value = record
  await nextTick()
  drawer.value?.focus()
}

function close(): void {
  openRecord.value = null
}

async function copyPrompt(record: CorpusRecord): Promise<void> {
  try {
    await navigator.clipboard.writeText(record.prompt)
    showNotice(t('copied'))
  } catch {
    report(new Error(t('copyFailed')))
  }
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && openRecord.value) close()
}

watch(collection, () => {
  page.value = 0
  load()
})

onMounted(async () => {
  await loadTaxonomy()
  await load()
  if (import.meta.client) window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  if (import.meta.client) window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div class="gallery-layout">
    <aside class="gallery-filters" aria-labelledby="gallery-heading">
      <h1 id="gallery-heading">{{ t('galleryHeading') }}</h1>
      <p class="hint">{{ t('galleryHint') }}</p>

      <form class="filter-form" @submit.prevent="search">
        <label class="field" for="corpus-search">{{ t('search') }}</label>
        <input
          id="corpus-search"
          v-model="query"
          type="search"
          :placeholder="t('searchPlaceholder')"
        />
        <button class="btn" type="submit" :disabled="loading">{{ t('search') }}</button>
      </form>

      <div class="filter-group">
        <p class="field">{{ t('allCollections') }}</p>
        <ul class="filter-list">
          <li>
            <button
              type="button"
              class="filter-option"
              :class="{ 'is-on': !collection }"
              @click="chooseCollection('')"
            >
              {{ t('allCollections') }}
            </button>
          </li>
          <li v-for="tag in collections" :key="tag.id">
            <button
              type="button"
              class="filter-option"
              :class="{ 'is-on': collection === tag.id }"
              @click="chooseCollection(tag.id)"
            >
              {{ label(tag) }}
            </button>
          </li>
        </ul>
      </div>

      <p class="eyebrow">{{ t('recordsCount', { count: total }) }}</p>
    </aside>

    <section class="gallery-main" aria-label="Corpus records">
      <p v-if="!loading && !total" class="emptiness">
        <span class="emptiness-title">{{ t('noRecords') }}</span>
      </p>

      <ul v-else class="corpus-grid">
        <li v-for="record in records" :key="record.id">
          <button class="corpus-card" type="button" @click="open(record)">
            <span class="corpus-frame">
              <img
                v-if="imageUrl(record)"
                :src="imageUrl(record)!"
                :alt="record.source.note ?? record.id"
                loading="lazy"
              />
              <span v-else class="corpus-empty">{{ t('noImage') }}</span>
            </span>
            <span class="corpus-text">{{ excerpt(record.prompt, 110) }}</span>
            <span class="corpus-meta">
              {{ record.tags.slice(0, 3).map(tagLabel).join(' · ') || record.id }}
            </span>
          </button>
        </li>
      </ul>

      <div v-if="pages > 1" class="pager">
        <button class="btn" type="button" :disabled="page <= 0" @click="step(-1)">
          {{ t('previousPage') }}
        </button>
        <span class="eyebrow">{{ t('pageStatus', { page: page + 1, pages }) }}</span>
        <button class="btn" type="button" :disabled="page >= pages - 1" @click="step(1)">
          {{ t('nextPage') }}
        </button>
      </div>
    </section>

    <div v-if="openRecord" class="scrim" @click.self="close">
      <article
        ref="drawer"
        class="drawer"
        role="dialog"
        aria-modal="true"
        tabindex="-1"
        aria-labelledby="record-heading"
      >
        <header class="drawer-head">
          <h2 id="record-heading">{{ t('recordHeading') }}</h2>
          <button class="btn-quiet" type="button" @click="close">{{ t('close') }}</button>
        </header>

        <img
          v-if="imageUrl(openRecord)"
          class="drawer-image"
          :src="imageUrl(openRecord)!"
          :alt="openRecord.source.note ?? openRecord.id"
        />

        <p v-if="openRecord.source.note" class="hint">{{ openRecord.source.note }}</p>

        <div class="row" style="margin-top: 10px">
          <button class="btn" type="button" @click="copyPrompt(openRecord)">
            {{ t('copyPrompt') }}
          </button>
          <a
            v-if="imageUrl(openRecord)"
            class="btn-quiet"
            :href="imageUrl(openRecord)!"
            target="_blank"
            rel="noopener"
          >
            {{ t('download') }}
          </a>
        </div>

        <p class="field" style="margin-top: 16px">{{ t('promptHeading') }}</p>
        <pre class="proof-text">{{ openRecord.prompt }}</pre>

        <template v-if="openRecord.negative_prompt">
          <p class="field" style="margin-top: 12px">{{ t('negativePrompt') }}</p>
          <pre class="proof-text">{{ openRecord.negative_prompt }}</pre>
        </template>

        <p class="field" style="margin-top: 12px">{{ t('labelsHeading') }}</p>
        <p class="hint">{{ openRecord.tags.map(tagLabel).join(' · ') || '—' }}</p>

        <template v-if="openRecord.image">
          <p class="field" style="margin-top: 12px">{{ t('outputSize') }}</p>
          <p class="hint">
            {{ openRecord.image.width ?? '?' }} × {{ openRecord.image.height ?? '?' }}
          </p>
        </template>

        <template v-if="openRecord.source.url">
          <p class="field" style="margin-top: 12px">{{ t('sourceLabel') }}</p>
          <a :href="openRecord.source.url" target="_blank" rel="noopener" class="hint">
            {{ openRecord.source.url }}
          </a>
        </template>
      </article>
    </div>
  </div>
</template>
