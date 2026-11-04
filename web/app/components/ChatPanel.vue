<script setup lang="ts">
import type { Message, Session, Task } from '~/types'

const props = defineProps<{ task: Task; session: Session; busy: boolean }>()
const emit = defineEmits<{ changed: [] }>()

const { t, api, report } = useAtelier()

const text = ref('')
const files = ref<File[]>([])
const working = ref(false)
const open = ref<string | null>(null)

const pending = computed(() => props.session.pending_turn)
const disabled = computed(() => props.busy || working.value || Boolean(pending.value))

function mediaUrl(imageId: string): string | null {
  const upload = props.session.uploads.find((item) => item.id === imageId)
  if (upload) return api.absolute(upload.media_url)
  const result = props.session.image_results.find((item) => item.id === imageId)
  if (result) return api.absolute(result.media_url)
  return null
}

function onFiles(event: Event): void {
  const input = event.target as HTMLInputElement
  files.value = [...(input.files ?? [])]
}

async function send(): Promise<void> {
  if (disabled.value) return
  if (!text.value.trim() && !files.value.length) return
  working.value = true
  try {
    await api.post(`/api/v1/tasks/${props.task.run_id}/messages`, {
      text: text.value,
      attachments: await filesToBase64(files.value),
    })
    text.value = ''
    files.value = []
    emit('changed')
  } catch (error) {
    report(error)
  } finally {
    working.value = false
  }
}

async function retry(): Promise<void> {
  working.value = true
  try {
    await api.post(`/api/v1/tasks/${props.task.run_id}/continue`)
    emit('changed')
  } catch (error) {
    report(error)
  } finally {
    working.value = false
  }
}

function toggle(message: Message): void {
  open.value = open.value === message.id ? null : message.id
}
</script>

<template>
  <aside class="work-chat" :aria-label="t('assistantHeading')">
    <h2>{{ t('assistantHeading') }}</h2>
    <p class="hint" style="margin-top: 6px">{{ t('assistantHint') }}</p>

    <div class="turns" style="margin-top: 14px">
      <p v-if="!session.messages.length" class="hint">{{ t('chatEmpty') }}</p>

      <article
        v-for="message in session.messages"
        :key="message.id"
        class="turn"
        :data-role="message.role"
      >
        <p v-if="message.text" class="turn-text">{{ message.text }}</p>

        <template v-for="imageId in message.attachment_ids" :key="imageId">
          <img v-if="mediaUrl(imageId)" :src="mediaUrl(imageId) ?? ''" alt="" />
        </template>

        <ul v-if="message.discrepancies.length" style="margin: 6px 0 0 16px; font-size: 12.5px">
          <li v-for="(item, index) in message.discrepancies" :key="index">{{ item }}</li>
        </ul>

        <p v-if="message.conflict" class="notice" data-tone="warn" style="margin: 8px 0 0">
          {{ t('conflict') }}
        </p>

        <div v-if="message.proposed_prompt" style="margin-top: 6px">
          <button class="btn-quiet" type="button" @click="toggle(message)">
            {{ t('proposalHeading') }}
          </button>
          <pre v-if="open === message.id" class="proof-text" style="margin-top: 4px">{{ message.proposed_prompt }}</pre>
        </div>
      </article>
    </div>

    <p v-if="pending" class="notice" data-tone="quiet" style="margin-top: 12px">
      {{ t('pendingTurn') }}
    </p>
    <button
      v-if="task.status === 'failed'"
      class="btn"
      type="button"
      :disabled="working"
      style="margin-top: 8px"
      @click="retry"
    >
      {{ t('retryReply') }}
    </button>

    <div style="margin-top: 14px">
      <textarea
        v-model="text"
        rows="3"
        :placeholder="t('chatPlaceholder')"
        :disabled="disabled"
        :aria-label="t('chatPlaceholder')"
        @keydown.ctrl.enter.prevent="send"
        @keydown.meta.enter.prevent="send"
      />
      <div class="row" style="margin-top: 8px">
        <label class="btn" style="cursor: pointer">
          + {{ files.length || '' }}
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            multiple
            hidden
            :disabled="disabled"
            @change="onFiles"
          />
        </label>
        <button
          class="btn btn-primary"
          type="button"
          :disabled="disabled || (!text.trim() && !files.length)"
          @click="send"
        >
          {{ t('send') }}
        </button>
      </div>
    </div>
  </aside>
</template>
