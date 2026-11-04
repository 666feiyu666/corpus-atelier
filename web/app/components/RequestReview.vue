<script setup lang="ts">
import type { Attempt, Session, Task } from '~/types'

const props = defineProps<{
  task: Task
  session: Session
  attempt: Attempt
  busy: boolean
}>()
const emit = defineEmits<{ changed: []; close: [] }>()

const { t, label, api, report } = useAtelier()

const working = ref(false)
const disabled = computed(() => props.busy || working.value)

const stale = computed(
  () => props.attempt.prompt_revision_id !== props.session.current_prompt_revision_id,
)

const roles = computed(() => {
  const map = new Map<string, string>()
  for (const item of props.attempt.reference_roles) {
    map.set(item.image_id, item.role)
  }
  return map
})

const references = computed(() =>
  props.attempt.reference_image_ids.map((id, index) => ({
    id,
    url: api.absolute(props.attempt.reference_media_urls[index] ?? ''),
    role: roles.value.get(id) ?? 'subject',
  })),
)

async function submit(): Promise<void> {
  working.value = true
  try {
    await api.post(
      `/api/v1/tasks/${props.task.run_id}/image-attempts/${props.attempt.id}/submit`,
      { expected_digest: props.attempt.request_digest },
    )
    emit('changed')
    emit('close')
  } catch (error) {
    report(error)
  } finally {
    working.value = false
  }
}

async function discard(): Promise<void> {
  working.value = true
  try {
    await api.del(`/api/v1/tasks/${props.task.run_id}/image-attempts/${props.attempt.id}`)
    emit('changed')
    emit('close')
  } catch (error) {
    report(error)
  } finally {
    working.value = false
  }
}
</script>

<template>
  <div class="scrim" @click.self="emit('close')">
    <article
      class="dialog proof"
      role="dialog"
      aria-modal="true"
      aria-labelledby="request-heading"
    >
      <header class="proof-head">
        <h2 id="request-heading">{{ t('requestHeading') }}</h2>
        <span class="eyebrow">{{ label(`action_${attempt.action}`) }}</span>
      </header>

      <p class="hint">{{ t('requestHint') }}</p>

      <p class="field">{{ t('exactRequest') }}</p>
      <pre class="proof-text">{{ attempt.request_text }}</pre>

      <dl class="proof-facts">
        <div>
          <dt>{{ t('imageModel') }}</dt>
          <dd>{{ attempt.settings.model ?? '—' }}</dd>
        </div>
        <div>
          <dt>{{ t('outputSize') }}</dt>
          <dd>{{ attempt.settings.size ?? '—' }}</dd>
        </div>
        <div>
          <dt>{{ t('quality') }}</dt>
          <dd>{{ attempt.settings.quality ?? '—' }}</dd>
        </div>
        <div v-if="attempt.mask_media_url">
          <dt>{{ t('maskLabel') }}</dt>
          <dd>{{ t('maskIncluded') }}</dd>
        </div>
      </dl>

      <div v-if="references.length" class="proof-references">
        <p class="field">{{ t('referencesHeading') }}</p>
        <div class="strip">
          <figure v-for="(item, index) in references" :key="item.id" class="reference">
            <img :src="item.url" :alt="`${index + 1}. ${label(`role_${item.role}`)}`" />
            <figcaption>{{ index + 1 }}. {{ label(`role_${item.role}`) }}</figcaption>
          </figure>
        </div>
      </div>

      <div v-if="attempt.mask_media_url" class="proof-references">
        <p class="field">{{ t('maskLabel') }}</p>
        <img :src="api.absolute(attempt.mask_media_url)" :alt="t('maskLabel')" class="proof-mask" />
        <p class="hint">{{ t('maskHint') }}</p>
      </div>

      <p v-if="stale" class="notice" data-tone="warn">{{ t('staleRequest') }}</p>

      <footer class="proof-foot">
        <span class="proof-digest">
          {{ t('digest', { digest: attempt.request_digest.slice(0, 12) }) }}
        </span>
        <button class="btn btn-primary" type="button" :disabled="disabled || stale" @click="submit">
          {{ t('submitRequest') }}
        </button>
        <button class="btn-quiet" type="button" :disabled="disabled" @click="discard">
          {{ t('discardRequest') }}
        </button>
        <button class="btn-quiet" type="button" :disabled="disabled" @click="emit('close')">
          {{ t('laterReview') }}
        </button>
      </footer>
    </article>
  </div>
</template>
