<template>
  <div class="view-container">
    <div class="view-header">
      <div>
        <h2 class="view-title">Settings & System Configuration</h2>
        <p class="view-subtitle">Manage Jenkins CI credentials, Docker connection parameters, quality gate enforcement policies, and runtime defaults.</p>
      </div>
      <div class="view-actions">
        <button class="btn primary" @click="saveSettings">Save Configuration</button>
      </div>
    </div>

    <div class="settings-grid">
      <!-- Jenkins Automation Settings -->
      <div class="card">
        <div class="card-header">
          <h3>Jenkins Integration</h3>
          <button class="btn secondary sm" @click="testJenkins">Test Connection</button>
        </div>
        <div class="card-body">
          <div class="form-group">
            <label>Jenkins Server URL</label>
            <input v-model="form.jenkins_url" placeholder="http://localhost:8080" />
          </div>
          <div class="form-group">
            <label>Jenkins Username</label>
            <input v-model="form.jenkins_username" placeholder="admin" />
          </div>
          <div class="form-group">
            <label>Jenkins API Token / Password</label>
            <input
              type="password"
              v-model="form.jenkins_api_token"
              placeholder="Leave blank to preserve existing configured token"
            />
            <span class="hint-text" v-if="rawConfig?.jenkins_token_configured">
              ✓ An API token is currently configured on the server.
            </span>
          </div>

          <div v-if="jenkinsTestResult" class="test-feedback" :class="jenkinsTestResult.available ? 'success' : 'error'">
            {{ jenkinsTestResult.available ? `✓ Connected to Jenkins ${jenkinsTestResult.version} as ${jenkinsTestResult.user}` : `✕ Connection failed: ${jenkinsTestResult.error}` }}
          </div>
        </div>
      </div>

      <!-- Docker Settings -->
      <div class="card">
        <div class="card-header">
          <h3>Docker Engine Configuration</h3>
          <button class="btn secondary sm" @click="testDocker">Test Connection</button>
        </div>
        <div class="card-body">
          <div class="form-group">
            <label>Docker Host / Daemon Socket</label>
            <input v-model="form.docker_host" placeholder="Leave empty for local default socket / pipe" />
          </div>
          <div class="form-group">
            <label>Sandbox Runner Image</label>
            <input v-model="form.sandbox_image" placeholder="python:3.10-slim" />
          </div>
          <div class="form-group">
            <label>Default Deployment Port</label>
            <input type="number" v-model.number="form.default_deploy_port" min="1024" max="65535" />
          </div>

          <div v-if="dockerTestResult" class="test-feedback" :class="dockerTestResult.available ? 'success' : 'error'">
            {{ dockerTestResult.available ? `✓ Docker Engine ${dockerTestResult.server_version} connected` : `✕ Docker error: ${dockerTestResult.error}` }}
          </div>
        </div>
      </div>

      <!-- Validation Policy & Quality Gates -->
      <div class="card full-width">
        <div class="card-header">
          <h3>Code Validation & Quality Gate Policy</h3>
        </div>
        <div class="card-body">
          <div class="checkbox-setting">
            <input type="checkbox" id="gate-policy" v-model="form.enforce_mandatory_validation" />
            <label for="gate-policy">
              <strong>Enforce Mandatory Code Validation Before Deployment</strong>
              <p class="setting-desc">
                When enabled, the automated pipeline strictly blocks and halts build & deployment stages if fatal Python syntax errors, malformed JSON files, or high-risk security vulnerabilities are detected in the project.
              </p>
            </label>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useWorkspaceStore } from '../stores/workspace'
import { settingsApi } from '../api'

const store = useWorkspaceStore()
const rawConfig = ref(null)

const form = ref({
  jenkins_url: 'http://localhost:8080',
  jenkins_username: 'admin',
  jenkins_api_token: '',
  docker_host: '',
  sandbox_image: 'python:3.10-slim',
  default_deploy_port: 5001,
  enforce_mandatory_validation: true,
})

const jenkinsTestResult = ref(null)
const dockerTestResult = ref(null)

onMounted(async () => {
  await loadSettings()
})

async function loadSettings() {
  try {
    const data = await settingsApi.get()
    rawConfig.value = data
    form.value.jenkins_url = data.jenkins_url || 'http://localhost:8080'
    form.value.jenkins_username = data.jenkins_username || 'admin'
    form.value.docker_host = data.docker_host === 'local socket / pipe' ? '' : data.docker_host
    form.value.sandbox_image = data.sandbox_image || 'python:3.10-slim'
    form.value.default_deploy_port = data.default_deploy_port || 5001
    form.value.enforce_mandatory_validation = data.enforce_mandatory_validation !== false
  } catch (e) {
    store.showNotification(`Failed to load settings: ${e.message}`, 'error')
  }
}

async function saveSettings() {
  try {
    const payload = { ...form.value }
    if (!payload.jenkins_api_token) {
      delete payload.jenkins_api_token
    }
    const res = await settingsApi.update(payload)
    rawConfig.value = res.settings
    store.showNotification('Settings saved successfully', 'success')
    await store.checkServicesStatus()
  } catch (e) {
    store.showNotification(`Failed to save settings: ${e.message}`, 'error')
  }
}

async function testJenkins() {
  try {
    jenkinsTestResult.value = await settingsApi.testJenkins()
    if (jenkinsTestResult.value.available) {
      store.showNotification('Jenkins connection successful!', 'success')
    } else {
      store.showNotification('Jenkins connection failed', 'error')
    }
  } catch (e) {
    jenkinsTestResult.value = { available: false, error: e.message }
  }
}

async function testDocker() {
  try {
    dockerTestResult.value = await settingsApi.testDocker()
    if (dockerTestResult.value.available) {
      store.showNotification('Docker connection successful!', 'success')
    } else {
      store.showNotification('Docker connection failed', 'error')
    }
  } catch (e) {
    dockerTestResult.value = { available: false, error: e.message }
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

.settings-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

@media (max-width: 900px) {
  .settings-grid { grid-template-columns: 1fr; }
}

.card {
  background: #27272a;
  border: 1px solid #3f3f46;
  border-radius: 8px;
}

.card.full-width {
  grid-column: 1 / -1;
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
  background: #18181b;
  border: 1px solid #3f3f46;
  color: #f4f4f5;
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 13px;
  outline: none;
}

.form-group input:focus { border-color: #2563eb; }

.hint-text {
  font-size: 11px;
  color: #10b981;
}

.checkbox-setting {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.checkbox-setting input[type="checkbox"] {
  margin-top: 4px;
  width: 16px;
  height: 16px;
  cursor: pointer;
}

.checkbox-setting label {
  cursor: pointer;
  color: #f4f4f5;
  font-size: 13px;
}

.setting-desc {
  font-size: 12px;
  color: #a1a1aa;
  margin-top: 4px;
  line-height: 1.4;
}

.test-feedback {
  margin-top: 10px;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
}

.test-feedback.success {
  background: #064e3b22;
  color: #34d399;
  border: 1px solid #059669;
}

.test-feedback.error {
  background: #450a0a22;
  color: #fca5a5;
  border: 1px solid #7f1d1d;
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
.btn.primary:hover { background: #1d4ed8; }
.btn.secondary { background: #3f3f46; color: #f4f4f5; }
.btn.secondary:hover { background: #52525b; }
.btn.sm { padding: 3px 8px; font-size: 11px; }
</style>
