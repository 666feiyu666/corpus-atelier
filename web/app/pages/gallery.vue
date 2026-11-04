<script setup lang="ts">
import type { CorpusFacet, CorpusSearch, CorpusTag } from '~/types'

const { t, api, report, locale } = useAtelier()

const PAGE_SIZE = 12

const query = ref('')
const collection = ref('')
const page = ref(0)
const payload = ref<CorpusSearch | null>(null)
const facets = ref<CorpusFacet[]>([])
const loading = ref(false)
const expanded = ref<string | null>(null)

const collections = computed(
  () => facets.value.find((facet) => facet.id === 'collection')?.tags ?? [],
)
const total = computed(() => payload.value?.total ?? 0)
const pages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

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

watch(collection, () => {
  page.value = 0
  load()
})

onMounted(async () => {
  await loadTaxonomy()
  await load()
})
</script>

<template>
  <div class="work-main" style="max-width: 1180px">
    <h1>{{ t('galleryHeading') }}</h1>
    <p class="hint" style="margin-top: 6px">{{ t('galleryHint') }}</p>

    <form class="row" style="margin-top: 16px" @submit.prevent="search">
      <input
        v-model="query"
        type="text"
        :placeholder="t('searchPlaceholder')"
        :aria-label="t('searchPlaceholder')"
        style="max-width: 320px"
      />
      <select v-model="collection" style="width: 220px" :aria-label="t('allCollections')">
        <option value="">{{ t('allCollections') }}</option>
        <option v-for="tag in collections" :key="tag.id" :value="tag.id">
          {{ label(tag) }}
        </option>
      </select>
      <button class="btn" type="submit" :disabled="loading">{{ t('search') }}</button>
      <span class="eyebrow">{{ t('recordsCount', { count: total }) }}</span>
    </form>

    <p v-if="!loading && !total" class="notice" data-tone="quiet" style="margin-top: 22px">
      {{ t('noRecords') }}
    </p>

    <div v-else class="results" style="margin-top: 20px">
      <article v-for="record in payload?.records ?? []" :key="record.id" class="result">
        <img
          v-if="record.image"
          :src="api.absolute(record.image.media_url)"
          :alt="record.source.note ?? record.id"
        />
        <p class="meta">{{ record.source.note ?? record.id }}</p>
        <p style="font-size: 13px; margin: 0">{{ excerpt(record.prompt) }}</p>
        <p class="meta">{{ record.tags.map(tagLabel).join('  ') }}</p>
        <div class="row">
          <button
            class="btn-quiet"
            type="button"
            @click="expanded = expanded === record.id ? null : record.id"
          >
            {{ expanded === record.id ? '−' : '+' }}
          </button>
          <span v-if="record.image" class="meta">
            {{ record.image.width ?? '?' }} × {{ record.image.height ?? '?' }}
          </span>
        </div>
        <pre v-if="expanded === record.id" class="proof-text">{{ record.prompt }}</pre>
        <pre v-if="expanded === record.id && record.negative_prompt" class="proof-text">{{ record.negative_prompt }}</pre>
      </article>
    </div>

    <div v-if="pages > 1" class="row" style="margin-top: 22px">
      <button class="btn" type="button" :disabled="page <= 0" @click="step(-1)">
        {{ t('previousPage') }}
      </button>
      <span class="eyebrow">{{ t('pageStatus', { page: page + 1, pages }) }}</span>
      <button class="btn" type="button" :disabled="page >= pages - 1" @click="step(1)">
        {{ t('nextPage') }}
      </button>
    </div>
  </div>
</template>
