<script setup lang="ts">
import type { Session, Task, Upload } from '~/types'

const props = defineProps<{
  task: Task
  session: Session
  busy: boolean
}>()
const emit = defineEmits<{ changed: [] }>()

const { t, label, api, report } = useAtelier()

const ROLE_KEYS = ['subject', 'composition', 'palette', 'style'] as const

const selected = ref<string[]>([])
const roles = ref<Record<string, string>>({})
const instruction = ref('')
const mask = ref('')
const maskFailed = ref(false)
const working = ref('')

const workingAny = computed(() => props.busy || Boolean(working.value))

const candidates = computed(() => [
  ...props.session.image_results.map((item) => ({
    id: item.id,
    text: `${item.label} · ${item.id.slice(-4)}`,
    url: api.absolute(item.media_url),
  })),
  ...props.session.uploads
    .filter((item) => item.role !== 'mask')
    .map((item) => ({
      id: item.id,
      text: `${item.name} · ${label(`upload_role_${item.role}`)}`,
      url: api.absolute(item.media_url),
    })),
])

const chosenEdit = ref<string>('')

const masks = computed(() => props.session.uploads.filter((item) => item.role === 'mask'))

const sourceImageId = computed(() => {
  const revision = props.session.prompt_revisions.find(
    (item) => item.id === props.session.current_prompt_revision_id,
  )
  return revision?.source_image_id ?? null
})

// The mask is composited over its source so the kept/regenerated areas are visible.
const previewUrl = computed(() => {
  if (!mask.value || !chosenEdit.value) return ''
  return api.absolute(
    `/api/v1/tasks/${props.task.run_id}/mask-preview?mask_id=${mask.value}&source_id=${chosenEdit.value}`,
  )
})

watch([mask, chosenEdit], () => {
  maskFailed.value = false
})

watch(
  () => candidates.value,
  (list) => {
    const last = list[list.length - 1]
    if (!chosenEdit.value && last) chosenEdit.value = last.id
    selected.value = selected.value.filter((id) => list.some((item) => item.id === id))
    for (const id of selected.value) {
      if (!roles.value[id]) roles.value[id] = ROLE_KEYS[0]
    }
  },
  { immediate: true },
)

function toggle(id: string): void {
  if (selected.value.includes(id)) {
    selected.value = selected.value.filter((item) => item !== id)
    return
  }
  if (selected.value.length >= 3) {
    report(new Error('too many references'), 'tooManyReferences')
    return
  }
  selected.value = [...selected.value, id]
  if (!roles.value[id]) roles.value[id] = ROLE_KEYS[0]
}

async function upload(event: Event, role: 'reference' | 'mask'): Promise<void> {
  const input = event.target as HTMLInputElement
  const files = [...(input.files ?? [])]
  if (!files.length) return
  working.value = 'upload'
  try {
    for (const file of files) {
      await api.post(`/api/v1/tasks/${props.task.run_id}/uploads`, {
        name: file.name,
        data_base64: await fileToBase64(file),
        role,
      })
    }
    emit('changed')
  } catch (error) {
    report(error)
  } finally {
    input.value = ''
    working.value = ''
  }
}

async function prepare(action: 'generate' | 'edit'): Promise<void> {
  working.value = action
  try {
    const body: Record<string, unknown> = {
      action,
      expected_revision: props.session.current_prompt_revision_id,
      reference_image_ids: action === 'edit' ? [chosenEdit.value, ...selected.value] : [...selected.value],
      reference_roles: Object.fromEntries(
        Object.entries(roles.value).filter(([id]) => selected.value.includes(id) || id === chosenEdit.value),
      ),
    }
    if (action === 'edit') {
      body.source_image_id = chosenEdit.value
      body.edit_instruction = instruction.value
      body.mask_image_id = mask.value || null
    }
    await api.post(`/api/v1/tasks/${props.task.run_id}/image-attempts`, body)
    emit('changed')
  } catch (error) {
    report(error)
  } finally {
    working.value = ''
  }
}

function uploadRole(item: Upload): string {
  return label(`upload_role_${item.role}`)
}
</script>

<template>
  <section class="panel" aria-labelledby="images-heading">
    <div class="panel-head">
      <h2 id="images-heading">{{ t('imagesHeading') }}</h2>
    </div>
    <p class="hint">{{ t('imagesHint') }}</p>

    <details class="tool-body">
      <summary>{{ t('toolsHeading') }}</summary>

    <div v-if="session.uploads.length" style="margin-bottom: 16px">
      <p class="hint" style="margin-bottom: 6px">
        {{ t('sessionImages') }} · {{ session.uploads.length }}
      </p>
      <div class="strip">
        <figure v-for="item in session.uploads" :key="item.id" class="reference">
          <img :src="api.absolute(item.media_url)" :alt="item.name" />
          <figcaption>
            {{ item.name }} · {{ label(`upload_role_${item.role}`) }}<template
              v-if="item.id === sourceImageId"
            > · {{ t('promptSource') }}</template>
          </figcaption>
        </figure>
      </div>
    </div>

    <div class="row">
      <label class="btn" style="cursor: pointer">
        {{ t('addImages') }}
        <input
          type="file"
          accept="image/png,image/jpeg,image/webp"
          multiple
          hidden
          :disabled="workingAny"
          @change="upload($event, 'reference')"
        />
      </label>
      <span v-if="session.uploads.length" class="eyebrow">
        {{ session.uploads.map(uploadRole).join(' · ') }}
      </span>
    </div>

    <div v-if="candidates.length" style="margin-top: 14px">
      <p class="hint" style="margin-bottom: 6px">{{ t('referencesLabel') }}</p>
      <div class="stack" style="gap: 6px">
        <div v-for="item in candidates" :key="item.id" class="row" style="gap: 8px">
          <label class="row" style="gap: 8px; flex: 1; font-size: 13.5px">
            <input
              type="checkbox"
              :checked="selected.includes(item.id)"
              :disabled="workingAny"
              @change="toggle(item.id)"
            />
            <img
              :src="item.url"
              alt=""
              style="width: 34px; height: 34px; object-fit: cover; border: 1px solid var(--rule)"
            />
            <span>{{ item.text }}</span>
          </label>
          <select
            v-if="selected.includes(item.id)"
            v-model="roles[item.id]"
            :disabled="workingAny"
            style="width: 128px"
            :aria-label="t('referencesLabel')"
          >
            <option v-for="key in ROLE_KEYS" :key="key" :value="key">{{ label(`role_${key}`) }}</option>
          </select>
        </div>
      </div>
    </div>

    <div class="row" style="margin-top: 14px">
      <button
        class="btn"
        type="button"
        :disabled="workingAny || !session.current_prompt_revision_id"
        @click="prepare('generate')"
      >
        {{ t('prepareGenerate') }}
      </button>
    </div>

    <hr class="rule" />

    <p class="hint" style="margin-bottom: 6px">{{ t('editSource') }}</p>
    <select v-model="chosenEdit" :disabled="workingAny" style="max-width: 340px">
      <option v-for="item in candidates" :key="item.id" :value="item.id">{{ item.text }}</option>
    </select>

    <div style="margin-top: 10px">
      <label class="field" for="edit-instruction">{{ t('editInstruction') }}</label>
      <textarea
        id="edit-instruction"
        v-model="instruction"
        rows="3"
        :disabled="workingAny"
        :placeholder="t('editPlaceholder')"
      />
    </div>

    <div class="row" style="margin-top: 10px">
      <label class="btn" style="cursor: pointer">
        {{ t('addMask') }}
        <input
          type="file"
          accept="image/png"
          hidden
          :disabled="workingAny"
          @change="upload($event, 'mask')"
        />
      </label>
      <select v-if="masks.length" v-model="mask" :disabled="workingAny" style="width: 190px">
        <option value="">{{ t('noMask') }}</option>
        <option v-for="item in masks" :key="item.id" :value="item.id">{{ item.name }}</option>
      </select>
      <span class="eyebrow">{{ t('maskHint') }}</span>
    </div>

    <figure v-if="previewUrl && !maskFailed" style="margin: 10px 0 0">
      <img
        :src="previewUrl"
        :alt="t('maskPreview')"
        style="max-width: 220px; border: 1px solid var(--rule); display: block"
        @error="maskFailed = true"
      />
      <figcaption class="hint" style="margin-top: 4px">{{ t('maskPreview') }}</figcaption>
    </figure>

    <div class="row" style="margin-top: 14px">
      <button
        class="btn"
        type="button"
        :disabled="workingAny || !chosenEdit || !instruction.trim()"
        @click="prepare('edit')"
      >
        {{ t('prepareEdit') }}
      </button>
    </div>
    </details>
  </section>
</template>
