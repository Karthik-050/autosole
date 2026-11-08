<template>
  <div class="view-container">
    <div class="view-header">
      <div>
        <h2 class="view-title">Jenkins Automation & Pipelines</h2>
        <p class="view-subtitle">Manage Jenkins CI/CD jobs, trigger remote builds, monitor pipeline execution stages, and stream console output.</p>
      </div>
      <div class="view-actions">
        <button class="btn secondary" @click="refreshJenkins">&#x21bb; Refresh</button>
      </div>
    </div>

    <!-- Jenkins Server Status Banner -->
    <div class="status-banner" :class="store.jenkinsStatus.available ? 'online' : 'offline'">
      <div class="banner-icon">⚙️</div>
      <div class="banner-info">
        <span class="banner-title">
          Jenkins Controller: {{ store.jenkinsStatus.available ? 'Connected' : 'Offline / Unreachable' }}
        </span>
        <span class="banner-sub" v-if="store.jenkinsStatus.available">
          Server URL: {{ store.jenkinsStatus.url }} | Version: {{ store.jenkinsStatus.version }} | User: {{ store.jenkinsStatus.user }}
        </span>
        <span class="banner-sub" v-else>
          {{ store.jenkinsStatus.error || 'Check Jenkins URL and API credentials in Settings.' }}
        </span>
      </div>
    </div>

    <div class="jenkins-layout">
      <!-- Left Column: Configured Jobs & Trigger -->
      <div class="jenkins-column">
        <!-- Jobs List -->
        <div class="card">
          <div class="card-header">
            <h3>Configured Jenkins Jobs ({{ store.jenkinsJobs.length }})</h3>
            <button class="btn primary sm" :disabled="!store.jenkinsStatus.available" @click="showCreateJobModal = true">+ Create Job</button>
          </div>
          <div class="card-body p-0" v-if="store.jenkinsJobs.length">
            <div
              v-for="j in store.jenkinsJobs"
              :key="j.name"
              class="job-item"
              :class="{ selected: selectedJob === j.name }"
              @click="selectJob(j.name)"
            >
              <div class="job-item-left">
                <span class="job-status-dot" :class="j.color"></span>
                <span class="job-name">{{ j.name }}</span>
              </div>
              <div class="job-item-right">
                <button
                  class="btn primary sm"
                  :disabled="triggeringJob === j.name"
                  @click.stop="triggerJob(j.name)"
                >
                  {{ triggeringJob === j.name ? 'Triggering...' : '▶ Trigger' }}
                </button>
              </div>
            </div>
          </div>
          <div class="card-body empty-state" v-else>
            {{ store.jenkinsStatus.available ? 'No Jenkins jobs found. Click "+ Create Job" above.' : 'Jenkins server is offline.' }}
          </div>
        </div>

        <!-- Latest Build Details Card -->
        <div class="card" v-if="currentBuildInfo">
          <div class="card-header">
            <h3>Latest Build Status: {{ selectedJob }}</h3>
            <span class="badge" :class="buildBadgeClass(currentBuildInfo.status)">
              {{ currentBuildInfo.status }}
            </span>
          </div>
          <div class="card-body">
            <div class="meta-row">
              <span class="meta-label">Build Number:</span>
              <span class="meta-val">#{{ currentBuildInfo.build_number }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">Result:</span>
              <span class="meta-val">{{ currentBuildInfo.result || 'IN PROGRESS' }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">Duration:</span>
              <span class="meta-val">{{ Math.round(currentBuildInfo.duration_ms / 1000) }}s</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">Started:</span>
              <span class="meta-val">{{ new Date(currentBuildInfo.timestamp).toLocaleTimeString() }}</span>
            </div>
            <div class="card-footer-actions">
              <button class="btn secondary sm" @click="loadConsole(selectedJob, currentBuildInfo.build_number)">
                Fetch Console Logs
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Right Column: Console Log Viewer -->
      <div class="jenkins-column">
        <div class="card console-card">
          <div class="card-header">
            <h3>Jenkins Build Console Output</h3>
            <span class="console-label">{{ selectedJob ? `${selectedJob} console` : 'Select a job' }}</span>
          </div>
          <div class="card-body console-body">
            <pre v-if="consoleOutput" class="console-text">{{ consoleOutput }}</pre>
            <div v-else class="empty-state">
              Select a job and click "Fetch Console Logs" to stream Jenkins output.
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Create Job Modal -->
    <div v-if="showCreateJobModal" class="modal-backdrop" @click.self="showCreateJobModal = false">
      <div class="modal-box">
        <h3>Create Jenkins Pipeline Job</h3>
        <div class="form-group">
          <label>Job Name</label>
          <input v-model="newJobName" placeholder="e.g. automator-deploy" />
        </div>
        <div class="form-group">
          <label>Pipeline Script (Groovy CPS)</label>
          <textarea v-model="newJobScript" rows="8" class="code-textarea"></textarea>
        </div>
        <div class="modal-actions">
          <button class="btn secondary" @click="showCreateJobModal = false">Cancel</button>
          <button class="btn primary" @click="submitCreateJob">Create Job</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useWorkspaceStore } from '../stores/workspace'
import { jenkinsApi } from '../api'

const store = useWorkspaceStore()
const selectedJob = ref('')
const currentBuildInfo = ref(null)
const consoleOutput = ref('')
const triggeringJob = ref('')

const showCreateJobModal = ref(false)
const newJobName = ref('automator-deploy')
const newJobScript = ref(`pipeline {
    agent any
    stages {
        stage('Check Project') {
            steps { echo "Checking project..." }
        }
        stage('Build & Test') {
            steps { echo "Running tests..." }
        }
    }
}`)

onMounted(async () => {
  await refreshJenkins()
})

async function refreshJenkins() {
  await store.loadJenkinsSubsystem()
  if (store.jenkinsJobs.length && !selectedJob.value) {
    selectJob(store.jenkinsJobs[0].name)
  }
}

async function selectJob(name) {
  selectedJob.value = name
  try {
    currentBuildInfo.value = await jenkinsApi.getLatestBuild(name)
  } catch {
    currentBuildInfo.value = null
  }
}

async function triggerJob(name) {
  triggeringJob.value = name
  try {
    const res = await jenkinsApi.triggerJob(name)
    store.showNotification(`Build triggered for ${name} (Queue #${res.queue_id})`, 'success')
    await selectJob(name)
  } catch (e) {
    store.showNotification(`Trigger failed: ${e.message}`, 'error')
  } finally {
    triggeringJob.value = ''
  }
}

async function loadConsole(jobName, buildNum) {
  try {
    consoleOutput.value = await jenkinsApi.getConsoleLogs(jobName, buildNum)
  } catch (e) {
    consoleOutput.value = `Error loading console: ${e.message}`
  }
}

async function submitCreateJob() {
  if (!newJobName.value.trim()) return
  try {
    await jenkinsApi.createJob(newJobName.value.trim(), newJobScript.value)
    store.showNotification(`Job ${newJobName.value} created successfully`, 'success')
    showCreateJobModal.value = false
    await refreshJenkins()
  } catch (e) {
    store.showNotification(`Failed to create job: ${e.message}`, 'error')
  }
}

function buildBadgeClass(status) {
  if (status === 'SUCCESS') return 'success'
  if (status === 'FAILURE') return 'danger'
  if (status === 'RUNNING') return 'info'
  return 'neutral'
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

.status-banner {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
  border-radius: 8px;
  border: 1px solid transparent;
}

.status-banner.online {
  background: #064e3b22;
  border-color: #059669;
}

.status-banner.offline {
  background: #450a0a22;
  border-color: #7f1d1d;
}

.banner-icon { font-size: 28px; }
.banner-info { display: flex; flex-direction: column; }
.banner-title { font-size: 14px; font-weight: 700; color: #f4f4f5; }
.banner-sub { font-size: 12px; color: #a1a1aa; margin-top: 2px; }

.jenkins-layout {
  display: grid;
  grid-template-columns: 1fr 1.2fr;
  gap: 16px;
}

@media (max-width: 960px) {
  .jenkins-layout { grid-template-columns: 1fr; }
}

.jenkins-column {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.card {
  background: #27272a;
  border: 1px solid #3f3f46;
  border-radius: 8px;
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

.card-body { padding: 16px; }
.p-0 { padding: 0 !important; }

.job-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid #323238;
  cursor: pointer;
}

.job-item:hover { background: #323238; }
.job-item.selected { background: #1e293b; border-left: 3px solid #3b82f6; }

.job-item-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.job-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #a1a1aa;
}

.job-status-dot.blue { background: #10b981; }
.job-status-dot.red { background: #ef4444; }
.job-status-dot.anime { background: #3b82f6; }

.job-name {
  font-size: 13px;
  font-weight: 600;
  color: #f4f4f5;
}

.meta-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px solid #323238;
  font-size: 12px;
}

.meta-label { color: #a1a1aa; }
.meta-val { color: #f4f4f5; font-weight: 600; }

.card-footer-actions {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}

.console-card {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.console-label {
  font-size: 11px;
  color: #a1a1aa;
  font-family: monospace;
}

.console-body {
  flex: 1;
  background: #18181b;
  overflow-y: auto;
  max-height: 480px;
}

.console-text {
  font-family: monospace;
  font-size: 11px;
  color: #d4d4d8;
  white-space: pre-wrap;
  margin: 0;
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

.btn {
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  border: none;
  cursor: pointer;
  transition: all 0.15s;
}

.btn.primary { background: #2563eb; color: white; }
.btn.primary:hover:not(:disabled) { background: #1d4ed8; }
.btn.primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn.secondary { background: #3f3f46; color: #f4f4f5; }
.btn.secondary:hover { background: #52525b; }
.btn.sm { padding: 3px 8px; font-size: 11px; }

.empty-state {
  text-align: center;
  color: #71717a;
  padding: 24px;
  font-size: 12px;
}

/* Modal */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 999;
}

.modal-box {
  background: #18181b;
  border: 1px solid #3f3f46;
  border-radius: 10px;
  padding: 22px;
  width: 500px;
  max-width: 90vw;
}

.modal-box h3 {
  font-size: 16px;
  color: #f4f4f5;
  margin-bottom: 12px;
}

.form-group {
  margin-bottom: 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group label {
  font-size: 12px;
  color: #d4d4d8;
  font-weight: 500;
}

.form-group input {
  background: #27272a;
  border: 1px solid #3f3f46;
  color: #f4f4f5;
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 13px;
}

.code-textarea {
  background: #27272a;
  border: 1px solid #3f3f46;
  color: #f4f4f5;
  padding: 8px 10px;
  border-radius: 6px;
  font-family: monospace;
  font-size: 12px;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 16px;
}
</style>
