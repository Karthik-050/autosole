<template>
  <div class="output-panel" v-if="store.activeTab">
    <div class="panel-header">
      <span>Output</span>
      <div class="header-actions">
        <button
          class="run-btn"
          :disabled="store.running || !store.activeTab"
          @click="run"
        >
          {{ store.running ? 'Running...' : '▶ Run' }}
        </button>
        <button class="icon-btn" @click="store.output = null" title="Clear output">×</button>
      </div>
    </div>
    <div class="output-body" v-if="store.output">
      <div class="output-line stdout" v-if="store.output.stdout">{{ store.output.stdout }}</div>
      <div class="output-line stderr" v-if="store.output.stderr">{{ store.output.stderr }}</div>
      <div class="output-line exit-info" v-if="store.output.exit_code !== 0">
        Exit code: {{ store.output.exit_code }}
      </div>
    </div>
    <div class="output-body empty-state" v-else-if="!store.running">
      Click Run to execute
    </div>
  </div>
</template>

<script setup>
import { useWorkspaceStore } from '../stores/workspace'
const store = useWorkspaceStore()

async function run() {
  if (!store.activeTab) return
  await store.saveFile(store.activeTab)
  await store.runFile(store.activeTab)
}
</script>
