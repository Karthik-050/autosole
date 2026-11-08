<template>
  <div class="view-container">
    <div class="view-header">
      <div>
        <h2 class="view-title">Automator CI/CD</h2>
        <p class="view-subtitle">Run and monitor the selected workspace’s Git, validation, build, and deployment pipeline.</p>
      </div>
      <div class="header-actions">
        <button class="btn secondary" @click="store.currentView = 'git'">← Git & Versioning</button>
        <button class="btn secondary" :disabled="loading" @click="refreshRuns">↻ Refresh</button>
      </div>
    </div>

    <section class="card project-card">
      <div class="project-summary">
        <div class="project-icon">🚀</div>
        <div>
          <div class="eyebrow">ACTIVE PROJECT</div>
          <h3>{{ store.currentProjectDetails?.name || 'No project selected' }}</h3>
          <p>{{ store.currentWorkspace || 'Select a project from the top bar to configure its pipeline.' }}</p>
        </div>
      </div>
      <div class="run-controls">
        <label class="toggle-row"><input v-model="options.auto_commit" type="checkbox" /> Commit workspace changes before the run</label>
        <label v-if="options.auto_commit" class="field-label">Commit message
          <input v-model="options.commit_message" class="text-input" placeholder="Automated pipeline run" />
        </label>
        <label class="field-label">Build engine
          <select v-model="options.use_jenkins" class="text-input">
            <option :value="false">Local Docker engine</option>
            <option :value="true">Jenkins pipeline</option>
          </select>
        </label>
        <label class="toggle-row"><input v-model="options.deploy_container" type="checkbox" /> Deploy container after a successful build</label>
        <label v-if="options.deploy_container" class="field-label">Host port
          <input v-model.number="options.target_port" class="text-input" type="number" min="1024" max="65535" />
        </label>
        <button class="btn primary start-button" :disabled="!store.currentWorkspace || running" @click="startPipeline">
          {{ running ? 'Pipeline running…' : '▶ Start Automator CI/CD' }}
        </button>
      </div>
      <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>
    </section>

    <section v-if="latestRun" class="card run-card">
      <div class="section-heading">
        <div>
          <div class="eyebrow">{{ latestRun.run_id }}</div>
          <h3>Latest pipeline run</h3>
        </div>
        <span class="status-pill" :class="latestRun.status">{{ latestRun.status }}</span>
      </div>
      <div class="run-meta">Started {{ formatDate(latestRun.started_at) }}<span v-if="latestRun.finished_at"> · Finished {{ formatDate(latestRun.finished_at) }}</span></div>
      <div class="stages">
        <div v-for="stage in latestRun.stages || []" :key="stage.name" class="stage" :class="stage.status">
          <span class="stage-mark">{{ stageMark(stage.status) }}</span>
          <span>{{ stage.label || stage.name }}</span>
        </div>
      </div>
      <p v-if="latestRun.error" class="error-message">{{ latestRun.error }}</p>
      <details v-for="stage in latestRun.stages || []" :key="`${latestRun.run_id}-${stage.name}`" class="stage-log" :open="stage.status === 'failed' || stage.status === 'running'">
        <summary>{{ stage.label || stage.name }} <span :class="stage.status">{{ stage.status }}</span></summary>
        <pre>{{ stage.logs || 'No output yet.' }}</pre>
      </details>
    </section>

    <section class="card history-card">
      <div class="section-heading">
        <div><div class="eyebrow">PROJECT HISTORY</div><h3>Previous runs</h3></div>
        <span class="count-pill">{{ projectRuns.length }}</span>
      </div>
      <div v-if="loading" class="empty-state">Loading pipeline runs…</div>
      <div v-else-if="!projectRuns.length" class="empty-state">No CI/CD runs for this project yet. Start a run above.</div>
      <button v-for="run in projectRuns" :key="run.run_id" class="history-row" @click="selectRun(run)">
        <span class="history-status" :class="run.status">{{ stageMark(run.status) }}</span>
        <span class="history-id">{{ run.run_id }}</span>
        <span class="history-date">{{ formatDate(run.started_at) }}</span>
        <span class="status-pill small" :class="run.status">{{ run.status }}</span>
      </button>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useWorkspaceStore } from '../stores/workspace'
import { pipelineApi } from '../api'

const store = useWorkspaceStore()
const options = reactive({
  auto_commit: true,
  commit_message: 'Automated pipeline run',
  use_jenkins: false,
  deploy_container: true,
  target_port: 5001,
})
const projectRuns = ref([])
const selectedRunId = ref('')
const loading = ref(false)
const starting = ref(false)
const errorMessage = ref('')
const latestRun = computed(() => {
  if (selectedRunId.value) {
    if (store.activePipelineRun?.run_id === selectedRunId.value) return store.activePipelineRun
    const selected = projectRuns.value.find(run => run.run_id === selectedRunId.value)
    if (selected) return selected
  }
  return store.activePipelineRun?.project_id === store.currentWorkspace
    ? store.activePipelineRun
    : projectRuns.value[0] || null
})
const running = computed(() => starting.value || latestRun.value?.status === 'running')

onMounted(refreshRuns)
watch(() => store.currentWorkspace, refreshRuns)

async function refreshRuns() {
  if (!store.currentWorkspace) {
    projectRuns.value = []
    return
  }
  loading.value = true
  try {
    projectRuns.value = await pipelineApi.getRuns(store.currentWorkspace)
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || 'Could not load pipeline history.'
  } finally {
    loading.value = false
  }
}

async function startPipeline() {
  if (!store.currentWorkspace || running.value) return
  starting.value = true
  errorMessage.value = ''
  try {
    const run = await store.triggerUnifiedPipeline({ ...options, keepView: true })
    selectedRunId.value = run?.run_id || ''
    await refreshRuns()
  } finally {
    starting.value = false
  }
}

function selectRun(run) {
  selectedRunId.value = run.run_id
  store.activePipelineRun = run
}

function stageMark(status) {
  return ({ success: '✓', failed: '×', running: '●', skipped: '–', pending: '○' })[status] || '○'
}

function formatDate(value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}
</script>

<style scoped>
.view-container{height:100%;overflow-y:auto;padding:22px 26px;display:flex;flex-direction:column;gap:18px;color:#f4f4f5}.view-header,.section-heading,.project-summary,.header-actions{display:flex;align-items:center}.view-header,.section-heading{justify-content:space-between;gap:16px}.view-title{margin:0 0 5px;font-size:21px}.view-subtitle,.project-summary p,.run-meta{color:#a1a1aa;font-size:12px;margin:0}.header-actions{gap:8px}.card{background:#27272a;border:1px solid #3f3f46;border-radius:9px;padding:18px}.project-card{display:grid;grid-template-columns:minmax(220px,1fr) minmax(280px,1.1fr);gap:18px}.project-summary{align-items:flex-start;gap:12px}.project-icon{font-size:22px;background:#172554;border:1px solid #1d4ed8;border-radius:9px;padding:9px}.project-summary h3,.section-heading h3{margin:4px 0 6px;font-size:15px}.project-summary p{overflow-wrap:anywhere}.eyebrow{color:#71717a;font-size:10px;font-weight:700;letter-spacing:.09em}.run-controls{display:grid;gap:12px}.toggle-row,.field-label{display:grid;gap:6px;color:#d4d4d8;font-size:12px}.toggle-row{display:flex;align-items:center;gap:8px}.toggle-row input{accent-color:#2563eb}.text-input{width:100%;border:1px solid #52525b;background:#18181b;color:#f4f4f5;border-radius:6px;padding:9px 10px;font:inherit}.btn{border:0;border-radius:6px;padding:9px 13px;font-size:12px;font-weight:650;cursor:pointer}.btn:disabled{opacity:.5;cursor:not-allowed}.btn.primary{background:#2563eb;color:white}.btn.secondary{background:#3f3f46;color:#f4f4f5}.start-button{justify-self:start}.run-card{padding:18px}.status-pill,.count-pill{padding:4px 9px;border-radius:999px;background:#3f3f46;color:#d4d4d8;font-size:11px;font-weight:700;text-transform:uppercase}.status-pill.success{background:#064e3b;color:#6ee7b7}.status-pill.running{background:#1e3a8a;color:#93c5fd}.status-pill.failed{background:#450a0a;color:#fca5a5}.status-pill.small{font-size:9px}.run-meta{margin:8px 0 14px}.stages{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:8px;margin-bottom:14px}.stage{display:flex;align-items:center;gap:8px;border:1px solid #3f3f46;border-radius:7px;padding:10px;color:#a1a1aa;font-size:11px}.stage-mark{font-size:14px;color:#71717a}.stage.success .stage-mark,.history-status.success{color:#34d399}.stage.running .stage-mark,.history-status.running{color:#60a5fa}.stage.failed .stage-mark,.history-status.failed{color:#f87171}.stage-log{border-top:1px solid #3f3f46;padding:9px 0;font-size:12px}.stage-log summary{cursor:pointer;color:#d4d4d8}.stage-log summary span{float:right;color:#a1a1aa}.stage-log pre{margin:10px 0 0;padding:12px;border-radius:6px;background:#18181b;color:#c4c4cc;white-space:pre-wrap;overflow-wrap:anywhere;font:11px/1.5 ui-monospace,monospace;max-height:260px;overflow:auto}.error-message{color:#fca5a5;font-size:12px}.history-card{padding:18px}.count-pill{background:#3f3f46}.empty-state{padding:22px 8px;text-align:center;color:#a1a1aa;font-size:12px}.history-row{width:100%;display:grid;grid-template-columns:28px 1fr minmax(145px,auto) auto;gap:10px;align-items:center;text-align:left;border:0;border-top:1px solid #3f3f46;background:transparent;color:#e4e4e7;padding:11px 3px;cursor:pointer}.history-row:hover{background:#303035}.history-status{font-size:16px}.history-id{font:12px ui-monospace,monospace}.history-date{font-size:11px;color:#a1a1aa}@media(max-width:760px){.view-container{padding:16px}.view-header{align-items:flex-start;flex-direction:column}.project-card{grid-template-columns:1fr}.history-row{grid-template-columns:24px 1fr auto}.history-date{display:none}}
</style>
