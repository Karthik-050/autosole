<template>
  <div class="view-container">
    <div class="view-header">
      <div>
        <h2 class="view-title">Unified Dashboard</h2>
        <p class="view-subtitle">Real-time status of workspace projects, validation gates, Docker workloads, and CI/CD pipelines.</p>
      </div>
      <div class="view-actions">
        <button class="btn secondary" @click="refreshAll">&#x21bb; Refresh</button>
      </div>
    </div>

    <!-- Metric Stat Cards -->
    <div class="metrics-grid">
      <div class="metric-card">
        <div class="metric-icon">📁</div>
        <div class="metric-content">
          <span class="metric-label">Total Projects</span>
          <span class="metric-value">{{ store.projectsDetailed.length || store.workspaces.length }}</span>
          <span class="metric-sub">{{ store.currentProjectDetails ? store.currentProjectDetails.name : 'No project active' }}</span>
        </div>
      </div>

      <div class="metric-card">
        <div class="metric-icon">🛡️</div>
        <div class="metric-content">
          <span class="metric-label">Validation Score</span>
          <span class="metric-value" :class="scoreClass">
            {{ store.validationResult ? store.validationResult.score : '--' }}<small v-if="store.validationResult">/100</small>
          </span>
          <span class="metric-sub">
            {{ store.validationResult ? (store.validationResult.mandatory_checks_passed ? 'Gate Passed' : 'Blocked on Errors') : 'Not scanned' }}
          </span>
        </div>
      </div>

      <div class="metric-card">
        <div class="metric-icon">🐳</div>
        <div class="metric-content">
          <span class="metric-label">Docker Containers</span>
          <span class="metric-value">{{ containersRunning }}<small>/{{ containersTotal }}</small></span>
          <span class="metric-sub" :class="store.dockerStatus.available ? 'text-success' : 'text-danger'">
            {{ store.dockerStatus.available ? 'Daemon Active' : 'Daemon Offline' }}
          </span>
        </div>
      </div>

      <div class="metric-card">
        <div class="metric-icon">⚙️</div>
        <div class="metric-content">
          <span class="metric-label">Jenkins Pipelines</span>
          <span class="metric-value">{{ store.jenkinsJobs.length || (store.jenkinsStatus.available ? 'Online' : 'Offline') }}</span>
          <span class="metric-sub" :class="store.jenkinsStatus.available ? 'text-success' : 'text-danger'">
            {{ store.jenkinsStatus.available ? 'Controller Connected' : 'Controller Offline' }}
          </span>
        </div>
      </div>
    </div>

    <div class="dash-grid">
      <!-- Active Project Overview -->
      <div class="card">
        <div class="card-header">
          <h3>Active Project Overview</h3>
          <span v-if="store.currentProjectDetails" class="badge info">{{ store.currentProjectDetails.project_type.toUpperCase() }}</span>
        </div>
        <div class="card-body" v-if="store.currentProjectDetails">
          <div class="meta-row">
            <span class="meta-label">Project Name:</span>
            <span class="meta-val highlight">{{ store.currentProjectDetails.name }}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">ID / Path:</span>
            <span class="meta-val code">{{ store.currentProjectDetails.id }}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Runtime / Framework:</span>
            <span class="meta-val">{{ store.currentProjectDetails.framework || store.currentProjectDetails.project_type }}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Files Count:</span>
            <span class="meta-val">{{ store.currentProjectDetails.files_count }} files</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Git Status:</span>
            <span class="meta-val" v-if="store.gitStatus && store.gitStatus.is_repo">
              Branch: <strong>{{ store.gitStatus.branch }}</strong> ({{ store.gitStatus.clean ? 'Clean' : 'Modified changes' }})
            </span>
            <span class="meta-val text-muted" v-else>Uninitialized repository</span>
          </div>

          <div class="card-footer-actions">
            <button class="btn primary" @click="store.currentView = 'workspace'">Open Workspace</button>
            <button class="btn secondary" @click="store.currentView = 'validation'">View Validation</button>
            <button class="btn secondary" @click="store.currentView = 'docker'">Docker Settings</button>
          </div>
        </div>
        <div class="card-body empty-state" v-else>
          Select or create a project in the top header to inspect.
        </div>
      </div>

      <!-- Active / Recent Pipeline Execution Status -->
      <div class="card">
        <div class="card-header">
          <h3>CI/CD Pipeline Execution</h3>
          <span v-if="latestPipelineRun" class="badge" :class="statusBadgeClass(latestPipelineRun.status)">
            {{ latestPipelineRun.status.toUpperCase() }}
          </span>
        </div>
        <div class="card-body" v-if="latestPipelineRun">
          <div class="run-header">
            <div>
              <span class="run-id">{{ latestPipelineRun.run_id }}</span>
              <span class="run-date">{{ formatDate(latestPipelineRun.started_at) }}</span>
            </div>
            <span v-if="latestPipelineRun.status === 'running'" class="pulse-text">In Progress...</span>
          </div>

          <!-- Stage Progress Indicators -->
          <div class="stages-timeline">
            <div
              v-for="stage in latestPipelineRun.stages"
              :key="stage.name"
              class="stage-node"
              :class="stage.status"
            >
              <div class="stage-bubble">
                <span v-if="stage.status === 'success'">✓</span>
                <span v-else-if="stage.status === 'failed'">✕</span>
                <span v-else-if="stage.status === 'running'">●</span>
                <span v-else-if="stage.status === 'skipped'">-</span>
                <span v-else>○</span>
              </div>
              <span class="stage-name">{{ stage.label }}</span>
            </div>
          </div>

          <div v-if="latestPipelineRun.error" class="error-banner">
            <strong>Pipeline Halted:</strong> {{ latestPipelineRun.error }}
          </div>

          <div class="stage-log-box" v-if="activeStageLogs">
            <div class="stage-log-header">Latest Stage Output:</div>
            <pre class="stage-log-content">{{ activeStageLogs }}</pre>
          </div>
        </div>
        <div class="card-body empty-state" v-else>
          No pipeline runs recorded yet. Click <strong>"Run Pipeline"</strong> in the top header to execute the end-to-end workflow.
        </div>
      </div>
    </div>

    <!-- Recent Deployments & Recent History -->
    <div class="card full-width">
      <div class="card-header">
        <h3>Active Container Deployments</h3>
        <button class="btn secondary sm" @click="store.loadDeployments">Refresh</button>
      </div>
      <div class="card-body" v-if="store.deployments.length">
        <table class="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Project</th>
              <th>Container</th>
              <th>Image</th>
              <th>URL / Endpoint</th>
              <th>Health Status</th>
              <th>Deployed</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in store.deployments" :key="d.id">
              <td class="code">{{ d.id }}</td>
              <td><strong>{{ d.project_name }}</strong></td>
              <td>{{ d.container_name }}</td>
              <td class="code sm">{{ d.image_name }}</td>
              <td>
                <a :href="d.url" target="_blank" class="port-link">{{ d.url }} ↗</a>
              </td>
              <td>
                <span class="badge" :class="d.status === 'healthy' ? 'success' : (d.status === 'stopped' ? 'neutral' : 'danger')">
                  {{ d.status }}
                </span>
              </td>
              <td class="date-col">{{ formatDate(d.timestamp) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="card-body empty-state" v-else>
        No application containers currently deployed. Run the pipeline to deploy to local port.
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useWorkspaceStore } from '../stores/workspace'

const store = useWorkspaceStore()

onMounted(async () => {
  await store.refreshDashboard()
  await store.loadDeployments()
  await store.loadPipelineRuns()
  await store.loadDockerSubsystem()
  await store.loadJenkinsSubsystem()
})

async function refreshAll() {
  await store.refreshDashboard()
  await store.loadDeployments()
  await store.loadPipelineRuns()
  await store.checkServicesStatus()
}

const scoreClass = computed(() => {
  if (!store.validationResult) return ''
  const s = store.validationResult.score
  if (s >= 90) return 'text-success'
  if (s >= 70) return 'text-warning'
  return 'text-danger'
})

const containersTotal = computed(() => {
  return store.dashboardStats?.containers_summary?.total || store.dockerContainers.length || 0
})

const containersRunning = computed(() => {
  return store.dashboardStats?.containers_summary?.running || store.dockerContainers.filter(c => c.running).length || 0
})

const latestPipelineRun = computed(() => {
  return store.activePipelineRun || store.pipelineRuns[0] || null
})

const activeStageLogs = computed(() => {
  if (!latestPipelineRun.value) return ''
  const runningStage = latestPipelineRun.value.stages.find(s => s.status === 'running')
  if (runningStage && runningStage.logs) return runningStage.logs
  const failedStage = latestPipelineRun.value.stages.find(s => s.status === 'failed')
  if (failedStage && failedStage.logs) return failedStage.logs
  const lastSuccess = [...latestPipelineRun.value.stages].reverse().find(s => s.status === 'success' && s.logs)
  return lastSuccess ? lastSuccess.logs : ''
})

function statusBadgeClass(status) {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'running') return 'info'
  return 'neutral'
}

function formatDate(isoStr) {
  if (!isoStr) return ''
  try {
    const d = new Date(isoStr)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return isoStr
  }
}
</script>

<style scoped>
.view-container {
  padding: 20px 24px;
  overflow-y: auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.view-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.view-title {
  font-size: 20px;
  font-weight: 700;
  color: #f4f4f5;
  margin-bottom: 4px;
}

.view-subtitle {
  font-size: 13px;
  color: #a1a1aa;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
}

.metric-card {
  background: #27272a;
  border: 1px solid #3f3f46;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  align-items: center;
  gap: 14px;
}

.metric-icon {
  font-size: 26px;
  background: #18181b;
  width: 48px;
  height: 48px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.metric-content {
  display: flex;
  flex-direction: column;
}

.metric-label {
  font-size: 11px;
  color: #a1a1aa;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.metric-value {
  font-size: 22px;
  font-weight: 700;
  color: #f4f4f5;
  margin: 2px 0;
}

.metric-value small {
  font-size: 14px;
  color: #71717a;
}

.metric-sub {
  font-size: 11px;
  color: #a1a1aa;
}

.dash-grid {
  display: grid;
  grid-template-columns: 1fr 1.2fr;
  gap: 16px;
}

@media (max-width: 900px) {
  .dash-grid {
    grid-template-columns: 1fr;
  }
}

.card {
  background: #27272a;
  border: 1px solid #3f3f46;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
}

.card.full-width {
  width: 100%;
}

.card-header {
  padding: 12px 16px;
  border-bottom: 1px solid #3f3f46;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-header h3 {
  font-size: 14px;
  font-weight: 600;
  color: #f4f4f5;
}

.card-body {
  padding: 16px;
  flex: 1;
}

.meta-row {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid #323238;
  font-size: 12.5px;
}

.meta-label {
  color: #a1a1aa;
}

.meta-val {
  color: #f4f4f5;
  font-weight: 500;
}

.meta-val.code {
  font-family: monospace;
  font-size: 11px;
  background: #18181b;
  padding: 2px 6px;
  border-radius: 4px;
}

.meta-val.highlight {
  color: #60a5fa;
  font-weight: 600;
}

.card-footer-actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
}

.run-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}

.run-id {
  font-family: monospace;
  font-weight: 600;
  color: #60a5fa;
  margin-right: 8px;
}

.run-date {
  font-size: 11px;
  color: #71717a;
}

.pulse-text {
  font-size: 12px;
  color: #34d399;
  animation: pulse 1.5s infinite;
}

@keyframes pulse {
  0% { opacity: 0.6; }
  50% { opacity: 1; }
  100% { opacity: 0.6; }
}

.stages-timeline {
  display: flex;
  justify-content: space-between;
  margin: 14px 0 16px 0;
  position: relative;
}

.stage-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  flex: 1;
  text-align: center;
}

.stage-bubble {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  background: #3f3f46;
  color: #a1a1aa;
}

.stage-node.success .stage-bubble {
  background: #059669;
  color: white;
}

.stage-node.failed .stage-bubble {
  background: #dc2626;
  color: white;
}

.stage-node.running .stage-bubble {
  background: #2563eb;
  color: white;
  animation: pulse 1s infinite;
}

.stage-node.skipped .stage-bubble {
  background: #3f3f46;
  color: #71717a;
}

.stage-name {
  font-size: 10px;
  color: #a1a1aa;
  max-width: 65px;
  line-height: 1.2;
}

.error-banner {
  background: #450a0a;
  border: 1px solid #7f1d1d;
  color: #fca5a5;
  padding: 10px 12px;
  border-radius: 6px;
  font-size: 12px;
  margin-bottom: 12px;
}

.stage-log-box {
  background: #18181b;
  border: 1px solid #3f3f46;
  border-radius: 6px;
  padding: 10px;
  font-size: 11px;
  font-family: monospace;
}

.stage-log-header {
  color: #a1a1aa;
  font-weight: 600;
  margin-bottom: 4px;
}

.stage-log-content {
  color: #d4d4d8;
  white-space: pre-wrap;
  max-height: 120px;
  overflow-y: auto;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.data-table th, .data-table td {
  padding: 8px 12px;
  text-align: left;
  border-bottom: 1px solid #323238;
}

.data-table th {
  color: #a1a1aa;
  font-weight: 600;
  font-size: 11px;
  text-transform: uppercase;
}

.port-link {
  color: #60a5fa;
  text-decoration: none;
  font-weight: 500;
}

.port-link:hover {
  text-decoration: underline;
}

.badge {
  padding: 3px 8px;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 700;
}

.badge.success { background: #064e3b; color: #34d399; }
.badge.danger { background: #450a0a; color: #f87171; }
.badge.info { background: #1e3a8a; color: #93c5fd; }
.badge.neutral { background: #3f3f46; color: #a1a1aa; }

.text-success { color: #10b981 !important; }
.text-warning { color: #f59e0b !important; }
.text-danger { color: #ef4444 !important; }
.text-muted { color: #71717a !important; }

.btn {
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
}

.btn.primary { background: #2563eb; color: white; }
.btn.primary:hover { background: #1d4ed8; }

.btn.secondary { background: #3f3f46; color: #f4f4f5; }
.btn.secondary:hover { background: #52525b; }

.btn.sm { padding: 3px 8px; font-size: 11px; }

.empty-state {
  text-align: center;
  color: #71717a;
  padding: 24px;
  font-size: 12px;
}
</style>
