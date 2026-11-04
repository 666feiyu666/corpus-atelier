<script setup lang="ts">
const { t, loadTasks } = useAtelier()

onMounted(loadTasks)
</script>

<template>
  <div class="workspace" style="grid-template-columns: 258px minmax(0, 1fr)">
    <TaskLedger :current="null" />
    <section class="work-main" style="max-width: 800px">
      <StartForm />

      <section class="panel" style="margin-top: 42px" aria-labelledby="how-heading">
        <h2 id="how-heading">{{ t('howItWorks') }}</h2>
        <ol style="margin: 10px 0 0 18px; font-size: 13.5px; line-height: 1.75">
          <li>{{ t('howOne') }}</li>
          <li>{{ t('howTwo') }}</li>
          <li>{{ t('howThree') }}</li>
        </ol>
      </section>
    </section>
  </div>
</template>
