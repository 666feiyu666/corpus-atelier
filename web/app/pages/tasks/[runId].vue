<script setup lang="ts">
const route = useRoute()
const runId = computed(() => String(route.params.runId ?? ''))

const { t, api, report, loadTasks } = useAtelier()
const { task, session, loading, failure, live, refresh } = useLiveTask(runId.value)

const reviewOpen = ref(false)

const prepared = computed(
  () => session.value?.image_attempts.find((item) => item.status === 'prepared') ?? null,
)

// A frozen request is the moment that needs a decision. Open the review as soon
// as one exists; polling refreshes the session, so compare ids rather than the
// object, and let a dismissed review stay closed until the next request.
watch(
  () => prepared.value?.id ?? null,
  (id) => {
    if (id) reviewOpen.value = true
  },
  { immediate: true },
)

async function reload(): Promise<void> {
  await refresh()
  await loadTasks()
}

async function removeTask(): Promise<void> {
  if (!window.confirm(t('deleteConfirm'))) return
  try {
    await api.del(`/api/v1/tasks/${runId.value}`)
    await loadTasks()
    await navigateTo('/')
  } catch (error) {
    report(error)
  }
}
</script>

<template>
  <div class="workspace">
    <TaskLedger :current="runId" />

    <section class="work-main">
      <p v-if="loading" class="hint">{{ t('loading') }}</p>
      <p v-else-if="failure" class="notice" data-tone="warn">{{ failure }}</p>

      <template v-else-if="task && session">
        <header class="work-head">
          <h1>{{ task.title }}</h1>
          <StatusLine :status="task.status" :running="task.running" />
          <button class="btn-danger" type="button" @click="removeTask">
            {{ t('deleteTask') }}
          </button>
        </header>

        <div v-if="live" class="working" style="margin: 12px 0 0" role="progressbar" />

        <p v-if="task.status === 'outcome_unknown'" class="notice" data-tone="warn">
          {{ t('outcomeUnknown') }}
        </p>
        <p v-else-if="task.status === 'failed'" class="notice" data-tone="warn">
          {{ t('failureNotice') }}<template v-if="task.error"> {{ task.error }}</template>
        </p>

        <PromptPanel :task="task" :session="session" :busy="live" @changed="reload" />
        <ResultsWall :task="task" :session="session" :busy="live" @changed="reload" />
        <ImageActionsPanel :task="task" :session="session" :busy="live" @changed="reload" />
        <CanvasPanel :task="task" :session="session" :busy="live" @changed="reload" />
      </template>

      <p v-else class="hint">{{ t('readOnlyDone') }}</p>
    </section>

    <ChatPanel
      v-if="task && session"
      :task="task"
      :session="session"
      :busy="live"
      @changed="reload"
    />

    <RequestReview
      v-if="prepared && reviewOpen"
      :task="task!"
      :session="session!"
      :attempt="prepared"
      :busy="live"
      @changed="reload"
      @close="reviewOpen = false"
    />
  </div>
</template>
