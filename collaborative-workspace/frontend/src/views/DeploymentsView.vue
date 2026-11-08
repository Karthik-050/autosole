<template>
  <div class="view-container">
    <div class="view-header">
      <div>
        <h2 class="view-title">Deployments & Runtime Services</h2>
        <p class="view-subtitle">Monitor deployed project containers, verified endpoint health probes, and application access URLs.</p>
      </div>
      <div class="view-actions">
        <button class="btn secondary" @click="store.loadDeployments">&#x21bb; Refresh</button>
      </div>
    </div>

    <!-- Active Deployments Table -->
    <div class="card">
      <div class="card-header">
        <h3>Deployment Records ({{ store.deployments.length }})</h3>
      </div>
      <div class="card-body p-0" v-if="store.deployments.length">
        <table class="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Project</th>
              <th>Container Name</th>
              <th>Git Revision</th>
              <th>Live Endpoint</th>
              <th>Health Status</th>
              <th>Deployed Time</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in store.deployments" :key="d.id" :class="{ selected: selectedDeployment?.id === d.id }">
              <td class="code">{{ d.id }}</td>
              <td><strong>{{ d.project_name }}</strong></td>
              <td>{{ d.container_name }}</td>
              <td>
                <span class="commit-pill">{{ d.git_commit.slice(0, 8) }}</span>
              </td>
              <td>
                <a :href="d.url" target="_blank" class="port-link">{{ d.url }} ↗</a>
              </td>
              <td>
                <span class="badge" :class="d.status === 'healthy' ? 'success' : (d.status === 'stopped' ? 'neutral' : 'danger')">
                  {{ d.status.toUpperCase() }}
                </span>
              </td>
              <td class="date-col">{{ formatDate(d.timestamp) }}</td>
              <td>
                <div class="table-actions">
                  <button class="btn secondary sm" @click="checkHealth(d)">Probe</button>
                  <button v-if="d.status !== 'stopped'" class="btn danger sm" @click="stopDeployment(d.id)">Stop</button>
                  <button class="btn secondary sm" @click="selectedDeployment = d">Logs</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="card-body empty-state" v-else>
        No deployments recorded yet. Trigger the unified pipeline to deploy a project container.
      </div>
    </div>

    <!-- Selected Deployment Logs -->
    <div class="card" v-if="selectedDeployment">
      <div class="card-header">
        <h3>Deployment Logs: {{ selectedDeployment.container_name }} ({{ selectedDeployment.id }})</h3>
        <button class="btn secondary sm" @click="selectedDeployment = null">Close</button>
      </div>
      <div class="card-body">
        <div class="meta-row">
          <span class="meta-label">Image Tag:</span>
          <span class="meta-val code">{{ selectedDeployment.image_name }}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Port Allocation:</span>
          <span class="meta-val">{{ selectedDeployment.port }}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Validation Status:</span>
          <span class="meta-val">{{ selectedDeployment.validation_status }}</span>
        </div>
        <div class="logs-box">
          <div class="logs-header">Health Probe & Launch Logs:</div>
          <pre class="logs-text">{{ selectedDeployment.logs || 'No additional logs captured.' }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useWorkspaceStore } from '../stores/workspace'
import { deploymentApi } from '../api'

const store = useWorkspaceStore()
const selectedDeployment = ref(null)

onMounted(async () => {
  await store.loadDeployments()
})

async function checkHealth(dep) {
  try {
    const res = await deploymentApi.checkHealth(dep.id)
    if (res.health.healthy) {
      store.showNotification(`Health check passed: ${res.health.message}`, 'success')
    } else {
      store.showNotification(`Health probe failed: ${res.health.message}`, 'error')
    }
    await store.loadDeployments()
  } catch (e) {
    store.showNotification(`Probe error: ${e.message}`, 'error')
  }
}

async function stopDeployment(id) {
  try {
    await deploymentApi.stop(id)
    store.showNotification('Deployment container stopped', 'info')
    await store.loadDeployments()
  } catch (e) {
    store.showNotification(`Error: ${e.message}`, 'error')
  }
}

function formatDate(isoStr) {
  if (!isoStr) return ''
  try {
    const d = new Date(isoStr)
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
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

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.data-table th, .data-table td {
  padding: 10px 14px;
  text-align: left;
  border-bottom: 1px solid #323238;
}

.data-table th {
  color: #a1a1aa;
  font-weight: 600;
  font-size: 11px;
  text-transform: uppercase;
}

.commit-pill {
  font-family: monospace;
  font-size: 11px;
  background: #18181b;
  color: #60a5fa;
  padding: 2px 6px;
  border-radius: 4px;
}

.port-link {
  color: #34d399;
  text-decoration: none;
  font-weight: 600;
}

.port-link:hover { text-decoration: underline; }

.badge {
  padding: 3px 8px;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 700;
}

.badge.success { background: #064e3b; color: #34d399; }
.badge.danger { background: #450a0a; color: #f87171; }
.badge.neutral { background: #3f3f46; color: #a1a1aa; }

.table-actions {
  display: flex;
  gap: 6px;
}

.meta-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px solid #323238;
  font-size: 12px;
}

.meta-label { color: #a1a1aa; }
.meta-val { color: #f4f4f5; }

.logs-box {
  margin-top: 14px;
  background: #18181b;
  border: 1px solid #3f3f46;
  border-radius: 6px;
  padding: 10px;
}

.logs-header {
  font-size: 11px;
  font-weight: 600;
  color: #a1a1aa;
  margin-bottom: 6px;
}

.logs-text {
  font-family: monospace;
  font-size: 11px;
  color: #d4d4d8;
  white-space: pre-wrap;
  margin: 0;
  max-height: 180px;
  overflow-y: auto;
}

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
.btn.secondary { background: #3f3f46; color: #f4f4f5; }
.btn.secondary:hover { background: #52525b; }
.btn.danger { background: #dc2626; color: white; }
.btn.danger:hover { background: #b91c1c; }
.btn.sm { padding: 3px 8px; font-size: 11px; }

.empty-state {
  text-align: center;
  color: #71717a;
  padding: 24px;
  font-size: 12px;
}
</style>
