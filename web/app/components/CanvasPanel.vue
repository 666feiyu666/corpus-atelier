<script setup lang="ts">
import type { Session, Task } from '~/types'

const props = defineProps<{ task: Task; session: Session; busy: boolean }>()
const emit = defineEmits<{ changed: [] }>()

const { t, settings, api, report } = useAtelier()

const working = ref(false)
const chosen = ref('')

const ratios = computed(() => settings.value?.ratios ?? [])
const sourceCanvas = computed(() => props.session.settings.source_canvas ?? null)
const size = computed(() => props.session.settings.size ?? null)
const origin = computed(() => props.session.settings.canvas_origin ?? 'default')
const note = computed(() => props.session.settings.canvas_note ?? null)

watchEffect(() => {
  if (!chosen.value) {
    const ratio = props.session.settings.aspect_ratio ?? [1, 1]
    chosen.value = ratio.join(':')
  }
})

function canvasText(value: { width: number; height: number } | null): string {
  return value ? `${value.width} × ${value.height}` : '—'
}

async function apply(): Promise<void> {
  working.value = true
  try {
    await api.post(`/api/v1/tasks/${props.task.run_id}/canvas`, {
      ratio: chosen.value.split(':').map(Number),
    })
    emit('changed')
  } catch (error) {
    report(error)
  } finally {
    working.value = false
  }
}

async function restore(): Promise<void> {
  working.value = true
  try {
    await api.post(`/api/v1/tasks/${props.task.run_id}/canvas`, { ratio: null })
    emit('changed')
  } catch (error) {
    report(error)
  } finally {
    working.value = false
  }
}

const disabled = computed(() => props.busy || working.value)
</script>

<template>
  <section class="panel" aria-labelledby="canvas-heading">
    <div class="panel-head">
      <h2 id="canvas-heading">{{ t('canvasHeading') }}</h2>
      <span class="eyebrow">
        <template v-if="sourceCanvas">{{ t('sourceCanvas') }} {{ canvasText(sourceCanvas) }}</template>
        <template v-if="size"> · {{ t('outputSize') }} {{ size }}</template>
      </span>
    </div>

    <p v-if="!size" class="notice" data-tone="warn">
      {{ note || t('noOutputSize') }}
    </p>

    <div class="row">
      <label class="field" style="margin: 0" for="canvas-ratio">{{ t('chooseRatio') }}</label>
      <select id="canvas-ratio" v-model="chosen" :disabled="disabled" style="width: 120px">
        <option v-for="item in ratios" :key="item.join(':')" :value="item.join(':')">
          {{ item.join(':') }}
        </option>
      </select>
      <button class="btn" type="button" :disabled="disabled" @click="apply">
        {{ t('applyRatio') }}
      </button>
      <button
        v-if="origin === 'user' && sourceCanvas"
        class="btn-quiet"
        type="button"
        :disabled="disabled"
        @click="restore"
      >
        {{ t('restoreSource') }}
      </button>
    </div>
  </section>
</template>
