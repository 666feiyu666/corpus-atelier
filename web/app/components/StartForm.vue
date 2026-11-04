<script setup lang="ts">
import type { TaskDetail } from '~/types'

const { t, settings, api, report, loadTasks } = useAtelier()

const mode = ref<'prompt' | 'image'>('prompt')
const prompt = ref('')
const references = ref<File[]>([])
const source = ref<File | null>(null)
const busy = ref(false)

const textModel = ref('')
const reasoning = ref('')
const imageModel = ref('')
const quality = ref('medium')
const ratio = ref('16:9')

const textProfiles = computed(() => settings.value?.text_models ?? [])
const imageProfiles = computed(() => settings.value?.image_models ?? [])
const ratios = computed(() => settings.value?.ratios ?? [])
const qualities = computed(() => {
  const profile = imageProfiles.value.find((item) => item.model === imageModel.value)
  const all = settings.value?.qualities ?? []
  return profile?.supports_max_quality ? all : all.filter((item) => item !== 'xhigh' && item !== 'max')
})
const efforts = computed(
  () => textProfiles.value.find((item) => item.model === textModel.value)?.reasoning_efforts ?? [],
)

watchEffect(() => {
  const value = settings.value
  if (!value) return
  if (!textModel.value) {
    textModel.value = value.text_models[0]?.model ?? ''
    reasoning.value = value.text_models[0]?.default_reasoning_effort ?? 'medium'
  }
  if (!imageModel.value) imageModel.value = value.image_models[0]?.model ?? ''
  if (!ratios.value.some((item) => item.join(':') === ratio.value)) {
    ratio.value = (ratios.value[0] ?? [1, 1]).join(':')
  }
})

watch(textModel, () => {
  const profile = textProfiles.value.find((item) => item.model === textModel.value)
  if (profile && !profile.reasoning_efforts.includes(reasoning.value)) {
    reasoning.value = profile.default_reasoning_effort
  }
})

watch(qualities, (list) => {
  if (list.length && !list.includes(quality.value)) quality.value = 'medium'
})

function toBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = String(reader.result ?? '')
      resolve(result.slice(result.indexOf(',') + 1))
    }
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

function onReferences(event: Event): void {
  const input = event.target as HTMLInputElement
  references.value = [...(input.files ?? [])]
}

function onSource(event: Event): void {
  const input = event.target as HTMLInputElement
  source.value = input.files?.[0] ?? null
}

async function start(generateNow: boolean): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    const payload: Record<string, unknown> = {
      entry_mode: mode.value,
      settings: {
        image_quality: quality.value,
        aspect_ratio: ratio.value.split(':').map(Number),
      },
      models: {
        text_model: textModel.value,
        reasoning_effort: reasoning.value,
        image_model: imageModel.value,
        image_quality: quality.value,
      },
    }
    if (mode.value === 'prompt') {
      payload.prompt_text = prompt.value
      payload.submit_generate = generateNow
      payload.references = await Promise.all(
        references.value.map(async (file) => ({
          name: file.name,
          data_base64: await toBase64(file),
        })),
      )
    } else {
      if (!source.value) return
      payload.image = { name: source.value.name, data_base64: await toBase64(source.value) }
    }
    const created = await api.post<TaskDetail>('/api/v1/tasks', payload)
    await loadTasks()
    await navigateTo(`/tasks/${created.task.run_id}`)
  } catch (error) {
    report(error)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div>
    <h1>{{ t('startHeading') }}</h1>
    <p class="hint" style="margin-top: 6px; margin-bottom: 18px">{{ t('startHint') }}</p>

    <div class="row" role="tablist" style="margin-bottom: 16px">
      <button
        class="btn"
        type="button"
        role="tab"
        :aria-selected="mode === 'prompt'"
        :style="mode === 'prompt' ? 'border-color: var(--indigo); color: var(--indigo)' : ''"
        @click="mode = 'prompt'"
      >
        {{ t('modePrompt') }}
      </button>
      <button
        class="btn"
        type="button"
        role="tab"
        :aria-selected="mode === 'image'"
        :style="mode === 'image' ? 'border-color: var(--indigo); color: var(--indigo)' : ''"
        @click="mode = 'image'"
      >
        {{ t('modeImage') }}
      </button>
    </div>

    <template v-if="mode === 'prompt'">
      <label class="field" for="start-prompt">{{ t('promptLabel') }}</label>
      <textarea
        id="start-prompt"
        v-model="prompt"
        rows="6"
        :placeholder="t('promptPlaceholder')"
        :disabled="busy"
      />
      <p class="hint" style="margin-top: 6px">{{ t('promptExactHint') }}</p>

      <div style="margin-top: 16px">
        <label class="field" for="start-references">{{ t('referenceImages') }}</label>
        <input
          id="start-references"
          type="file"
          accept="image/png,image/jpeg,image/webp"
          multiple
          :disabled="busy"
          @change="onReferences"
        />
        <p class="hint" style="margin-top: 6px">{{ t('referenceHint') }}</p>
      </div>

      <div class="row" style="margin-top: 18px">
        <button
          class="btn btn-primary"
          type="button"
          :disabled="busy || !prompt.trim()"
          @click="start(true)"
        >
          {{ t('generateNow') }}
        </button>
        <button class="btn" type="button" :disabled="busy || !prompt.trim()" @click="start(false)">
          {{ t('saveOnly') }}
        </button>
      </div>
    </template>

    <template v-else>
      <label class="field" for="start-source">{{ t('sourceImage') }}</label>
      <input
        id="start-source"
        type="file"
        accept="image/png,image/jpeg,image/webp"
        :disabled="busy"
        @change="onSource"
      />
      <p class="hint" style="margin-top: 6px">{{ t('extractHint') }}</p>
      <div class="row" style="margin-top: 18px">
        <button class="btn btn-primary" type="button" :disabled="busy || !source" @click="start(false)">
          {{ t('extractPrompt') }}
        </button>
      </div>
    </template>

    <details style="margin-top: 26px">
      <summary class="dim" style="cursor: pointer; font-size: 13.5px">
        {{ t('taskSettings') }}
      </summary>
      <div class="stack" style="margin-top: 12px; max-width: 520px">
        <div>
          <label class="field" for="start-text-model">{{ t('textModel') }}</label>
          <select id="start-text-model" v-model="textModel" :disabled="busy">
            <option v-for="profile in textProfiles" :key="profile.model" :value="profile.model">
              {{ profile.label }}
            </option>
          </select>
        </div>
        <div>
          <label class="field" for="start-reasoning">{{ t('reasoning') }}</label>
          <select id="start-reasoning" v-model="reasoning" :disabled="busy">
            <option v-for="effort in efforts" :key="effort" :value="effort">{{ effort }}</option>
          </select>
        </div>
        <div>
          <label class="field" for="start-image-model">{{ t('imageModel') }}</label>
          <select id="start-image-model" v-model="imageModel" :disabled="busy">
            <option v-for="profile in imageProfiles" :key="profile.model" :value="profile.model">
              {{ profile.label }}
            </option>
          </select>
        </div>
        <div>
          <label class="field" for="start-quality">{{ t('quality') }}</label>
          <select id="start-quality" v-model="quality" :disabled="busy">
            <option v-for="item in qualities" :key="item" :value="item">{{ item }}</option>
          </select>
        </div>
        <div>
          <label class="field" for="start-ratio">{{ t('aspectRatio') }}</label>
          <select id="start-ratio" v-model="ratio" :disabled="busy">
            <option v-for="item in ratios" :key="item.join(':')" :value="item.join(':')">
              {{ item.join(':') }}
            </option>
          </select>
        </div>
        <p class="hint">{{ t('settingsHint') }}</p>
      </div>
    </details>
  </div>
</template>
