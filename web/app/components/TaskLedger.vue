<script setup lang="ts">
import type { Task } from '~/types'
import { statusText } from '~/i18n'

const props = defineProps<{ current?: string | null }>()
const { tasks, t, locale } = useAtelier()

interface Day {
  day: string
  items: Task[]
}

const days = computed<Day[]>(() => {
  const grouped = new Map<string, Task[]>()
  for (const task of tasks.value) {
    const stamp = task.updated_at || task.created_at || ''
    const day = stamp.slice(0, 10) || '—'
    const bucket = grouped.get(day)
    if (bucket) bucket.push(task)
    else grouped.set(day, [task])
  }
  return [...grouped.entries()].map(([day, items]) => ({ day, items }))
})

function clock(task: Task): string {
  const stamp = task.updated_at || task.created_at || ''
  return stamp.slice(11, 16)
}
</script>

<template>
  <aside class="ledger" :aria-label="t('tasksHeading')">
    <div class="ledger-head">
      <h2 style="font-size: 14px">{{ t('tasksHeading') }}</h2>
      <span class="eyebrow">{{ t('tasksCount', { count: tasks.length }) }}</span>
    </div>

    <p v-if="!tasks.length" class="hint">{{ t('noTasksHint') }}</p>
    <p v-else class="hint">{{ t('tasksHint') }}</p>

    <div v-for="group in days" :key="group.day">
      <p class="ledger-day">{{ group.day }}</p>
      <NuxtLink
        v-for="task in group.items"
        :key="task.run_id"
        :to="`/tasks/${task.run_id}`"
        class="ledger-row"
        :class="{ 'is-current': task.run_id === props.current }"
        :data-status="task.status"
        :title="task.title"
      >
        <span class="title">{{ task.title }}</span>
        <span class="meta">
          {{ statusText(locale, task.status) }}<template v-if="clock(task)"> · {{ clock(task) }}</template>
        </span>
      </NuxtLink>
    </div>
  </aside>
</template>
