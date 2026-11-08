<template>
  <div class="view-container">
    <div class="view-header">
      <div>
        <h2 class="view-title">Docker Management & Containers</h2>
        <p class="view-subtitle">Generate optimized Dockerfiles, build project container images, monitor workloads, and manage containers.</p>
      </div>
      <div class="view-actions">
        <button class="btn secondary" @click="refreshDocker">&#x21bb; Refresh</button>
      </div>
    </div>

    <!-- Daemon Status Banner -->
    <div class="status-banner" :class="store.dockerStatus.available ? 'online' : 'offline'">
      <div class="banner-icon">🐳</div>
      <div class="banner-info">
        <span class="banner-title">
          Docker Daemon: {{ store.dockerStatus.available ? 'Connected & Running' : 'Offline / Daemon Not Detected' }}
        </span>
        <span class="banner-sub" v-if="store.dockerStatus.available">
          Engine Version: {{ store.dockerStatus.server_version }} | Total Containers: {{ store.dockerStatus.containers_total }} ({{ store.dockerStatus.containers_running }} Running)
        </span>
        <span class="banner-sub" v-else>
          {{ store.dockerStatus.error || 'Ensure Docker Desktop is started and the engine is responsive.' }}
        </span>
      </div>
    </div>

    <div class="docker-layout">
      <!-- Left Column: Dockerfile Generator & Build -->
      <div class="docker-column">
        <!-- Dockerfile Editor / Generator -->
        <div class="card">
          <div class="card-header">
            <h3>Dockerfile Configuration</h3>
            <div class="header-tools">
              <select v-model="selectedRuntime" class="runtime-select">
                <option value="python">Python 3.12</option>
                <option value="node">Node.js 22</option>
                <option value="java-maven">Java Maven 21</option>
                <option value="java-gradle">Java Gradle 21</option>
              </select>
              <button class="btn secondary sm" @click="generateDockerfile">⚡ Generate</button>
            </div>
          </div>
          <div class="card-body">
            <textarea
              v-model="store.dockerfileContent"
              class="dockerfile-editor"
              rows="12"
              placeholder="FROM python:3.12-slim..."
            ></textarea>
            <div class="card-footer-row">
              <span class="hint-text">Saved in root of active project as <code>Dockerfile</code></span>
              <button class="btn primary sm" @click="saveDockerfile">Save Dockerfile</button>
            </div>
          </div>
        </div>

        <!-- Build Docker Image -->
        <div class="card">
          <div class="card-header">
            <h3>Build Docker Image</h3>
          </div>
          <div class="card-body">
            <div class="build-form">
              <div class="input-row">
                <label>Image Tag:</label>
                <input v-model="imageTag" class="tag-input" placeholder="e.g. automator-app:latest" />
                <button
                  class="btn primary"
                  :disabled="!store.dockerStatus.available || buildingImage || !imageTag"
                  @click="doBuildImage"
                >
                  {{ buildingImage ? 'Building Image...' : '🔨 Build Image' }}
                </button>
              </div>

              <div v-if="buildLogs" class="build-log-panel">
                <div class="log-header">Build Logs:</div>
                <pre class="log-content">{{ buildLogs }}</pre>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Right Column: Images & Running Containers -->
      <div class="docker-column">
        <!-- Active Containers Table -->
        <div class="card">
          <div class="card-header">
            <h3>Active & Recent Containers ({{ store.dockerContainers.length }})</h3>
          </div>
          <div class="card-body p-0" v-if="store.dockerContainers.length">
            <table class="data-table">
              <thead>
                <tr>
                  <th>Name / ID</th>
                  <th>Image</th>
                  <th>Status</th>
                  <th>Ports</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="c in store.dockerContainers" :key="c.id">
                  <td>
                    <strong>{{ c.name }}</strong>
                    <div class="code sm">{{ c.id.slice(0, 10) }}</div>
                  </td>
                  <td class="code sm">{{ c.image }}</td>
                  <td>
                    <span class="badge" :class="c.running ? 'success' : 'neutral'">
                      {{ c.status }}
                    </span>
                  </td>
                  <td class="code sm">{{ c.ports || '--' }}</td>
                  <td>
                    <div class="table-actions">
                      <button v-if="c.running" class="action-link text-warning" @click="stopContainer(c.id)">Stop</button>
                      <button class="action-link text-danger" @click="removeContainer(c.id)">Remove</button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="card-body empty-state" v-else>
            {{ store.dockerStatus.available ? 'No containers found.' : 'Docker daemon offline.' }}
          </div>
        </div>

        <!-- Local Images Table -->
        <div class="card">
          <div class="card-header">
            <h3>Local Docker Images ({{ store.dockerImages.length }})</h3>
          </div>
          <div class="card-body p-0" v-if="store.dockerImages.length">
            <table class="data-table">
              <thead>
                <tr>
                  <th>Repository / Tag</th>
                  <th>Image ID</th>
                  <th>Size</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="img in store.dockerImages.slice(0, 8)" :key="img.id + img.tag">
                  <td class="highlight-text">{{ img.tag }}</td>
                  <td class="code sm">{{ img.id.slice(0, 12) }}</td>
                  <td>{{ img.size }}</td>
                  <td class="date-col">{{ img.created }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="card-body empty-state" v-else>
            {{ store.dockerStatus.available ? 'No images found.' : 'Docker daemon offline.' }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useWorkspaceStore } from '../stores/workspace'
import { dockerApi } from '../api'

const store = useWorkspaceStore()
const selectedRuntime = ref('python')
const imageTag = ref('')
const buildingImage = ref(false)
const buildLogs = ref('')

onMounted(async () => {
  await refreshDocker()
  if (store.currentProjectDetails) {
    const safe = store.currentProjectDetails.name.toLowerCase().replace(/\s+/g, '-')
    imageTag.value = `app-${safe}:latest`
  }
})

async function refreshDocker() {
  await store.loadDockerSubsystem()
  if (store.currentWorkspace) {
    await store.loadDockerfile(store.currentWorkspace)
  }
}

async function generateDockerfile() {
  if (!store.currentWorkspace) return
  try {
    const res = await dockerApi.saveDockerfile(store.currentWorkspace, '', selectedRuntime.value)
    store.dockerfileContent = res.content || ''
    store.showNotification('Dockerfile generated for ' + selectedRuntime.value, 'success')
  } catch (e) {
    store.showNotification(`Failed to generate: ${e.message}`, 'error')
  }
}

async function saveDockerfile() {
  if (!store.currentWorkspace) return
  try {
    await dockerApi.saveDockerfile(store.currentWorkspace, store.dockerfileContent)
    store.showNotification('Dockerfile saved successfully', 'success')
  } catch (e) {
    store.showNotification(`Failed to save: ${e.message}`, 'error')
  }
}

async function doBuildImage() {
  if (!store.currentWorkspace || !imageTag.value.trim()) return
  buildingImage.value = true
  buildLogs.value = ''
  try {
    const res = await dockerApi.buildImage(store.currentWorkspace, imageTag.value.trim())
    buildLogs.value = res.stdout + '\n' + (res.stderr || '')
    if (res.success) {
      store.showNotification(`Image ${imageTag.value} built successfully!`, 'success')
      await store.loadDockerSubsystem()
    } else {
      store.showNotification('Docker image build failed', 'error')
    }
  } catch (e) {
    buildLogs.value = e.message
    store.showNotification(`Build error: ${e.message}`, 'error')
  } finally {
    buildingImage.value = false
  }
}

async function stopContainer(id) {
  try {
    await dockerApi.stopContainer(id)
    store.showNotification('Container stopped', 'info')
    await store.loadDockerSubsystem()
  } catch (e) {
    store.showNotification(`Error: ${e.message}`, 'error')
  }
}

async function removeContainer(id) {
  try {
    await dockerApi.removeContainer(id)
    store.showNotification('Container removed', 'info')
    await store.loadDockerSubsystem()
  } catch (e) {
    store.showNotification(`Error: ${e.message}`, 'error')
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

.docker-layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

@media (max-width: 960px) {
  .docker-layout { grid-template-columns: 1fr; }
}

.docker-column {
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

.header-tools {
  display: flex;
  gap: 8px;
}

.runtime-select {
  background: #18181b;
  color: #f4f4f5;
  border: 1px solid #3f3f46;
  border-radius: 4px;
  font-size: 11px;
  padding: 3px 6px;
}

.card-body { padding: 16px; }
.p-0 { padding: 0 !important; }

.dockerfile-editor {
  width: 100%;
  background: #18181b;
  border: 1px solid #3f3f46;
  border-radius: 6px;
  color: #f4f4f5;
  font-family: monospace;
  font-size: 12px;
  padding: 10px;
  box-sizing: border-box;
  resize: vertical;
}

.card-footer-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
}

.hint-text {
  font-size: 11px;
  color: #71717a;
}

.hint-text code {
  color: #60a5fa;
}

.input-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.input-row label {
  font-size: 12px;
  color: #a1a1aa;
}

.tag-input {
  flex: 1;
  background: #18181b;
  border: 1px solid #3f3f46;
  color: #f4f4f5;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12px;
}

.build-log-panel {
  background: #18181b;
  border: 1px solid #3f3f46;
  border-radius: 6px;
  padding: 10px;
  margin-top: 8px;
}

.log-header {
  font-size: 11px;
  font-weight: 600;
  color: #a1a1aa;
  margin-bottom: 4px;
}

.log-content {
  color: #d4d4d8;
  font-family: monospace;
  font-size: 11px;
  max-height: 180px;
  overflow-y: auto;
  white-space: pre-wrap;
  margin: 0;
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

.code.sm {
  font-family: monospace;
  font-size: 11px;
  color: #93c5fd;
}

.highlight-text {
  font-weight: 600;
  color: #f4f4f5;
}

.badge {
  padding: 3px 8px;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 700;
}

.badge.success { background: #064e3b; color: #34d399; }
.badge.neutral { background: #3f3f46; color: #a1a1aa; }

.table-actions {
  display: flex;
  gap: 8px;
}

.action-link {
  background: none;
  border: none;
  font-size: 11px;
  cursor: pointer;
  text-decoration: underline;
}

.text-warning { color: #f59e0b !important; }
.text-danger { color: #ef4444 !important; }

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
</style>
