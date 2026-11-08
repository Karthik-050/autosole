<template>
  <header class="top-header">
    <div class="header-left">
      <div class="project-selector-wrapper">
        <span class="label">Project:</span>
        <select
          class="project-select"
          :value="store.currentWorkspace"
          @change="onSelectProject($event.target.value)"
        >
          <option v-if="!store.workspaces.length" value="" disabled>No projects</option>
          <option
            v-for="p in store.projectsDetailed"
            :key="p.id"
            :value="p.id"
          >
            {{ p.name }} ({{ p.project_type }})
          </option>
          <option
            v-for="w in unlistedWorkspaces"
            :key="w"
            :value="w"
          >
            {{ w.slice(0, 8) }}
          </option>
        </select>
      </div>

      <button class="header-btn" @click="showNewProjectModal = true" title="Create New Project">
        + New
      </button>
      <button class="header-btn secondary" @click="store.importAutomatorProject()" title="Import Test Project from Automator">
        ⚡ Import Automator
      </button>
    </div>

    <div class="header-right">
      <!-- Service badges -->
      <div class="badge-group">
        <span
          class="status-pill"
          :class="store.dockerStatus.available ? 'online' : 'offline'"
          :title="store.dockerStatus.error || 'Docker Engine Connected'"
        >
          🐳 Docker: {{ store.dockerStatus.available ? 'Online' : 'Offline' }}
        </span>
        <span
          class="status-pill"
          :class="store.jenkinsStatus.available ? 'online' : 'offline'"
          :title="store.jenkinsStatus.error || 'Jenkins Connected'"
        >
          ⚙️ Jenkins: {{ store.jenkinsStatus.available ? 'Online' : 'Offline' }}
        </span>
      </div>

      <!-- Quick Actions -->
      <div class="action-buttons">
        <button
          class="action-btn validate-btn"
          :disabled="!store.currentWorkspace || store.validating"
          @click="runValidation"
        >
          {{ store.validating ? 'Scanning...' : '🛡️ Validate' }}
        </button>

        <button
          class="action-btn pipeline-btn"
          :disabled="!store.currentWorkspace || (store.activePipelineRun && store.activePipelineRun.status === 'running')"
          @click="showPipelineModal = true"
        >
          {{ (store.activePipelineRun && store.activePipelineRun.status === 'running') ? 'Running Pipeline...' : '▶ Run Pipeline' }}
        </button>

        <button
          v-if="store.currentView === 'workspace' && store.activeTab"
          class="action-btn save-btn"
          @click="store.saveFile(store.activeTab)"
          title="Save Active File (Ctrl+S)"
        >
          💾 Save
        </button>
      </div>
    </div>

    <!-- New Project Modal -->
    <div v-if="showNewProjectModal" class="modal-backdrop" @click.self="showNewProjectModal = false">
      <div class="modal-box">
        <h3>Create New Project</h3>
        <div class="form-group">
          <label>Project Name</label>
          <input v-model="newProjectName" placeholder="e.g. My Flask Service" @keydown.enter="submitNewProject" />
        </div>
        <div class="form-group">
          <label>Project Template</label>
          <select v-model="newProjectTemplate">
            <option value="python">Python (Flask / App)</option>
            <option value="fastapi">FastAPI Microservice</option>
            <option value="empty">Empty Project</option>
          </select>
        </div>
        <div class="modal-actions">
          <button class="header-btn secondary" @click="showNewProjectModal = false">Cancel</button>
          <button class="action-btn pipeline-btn" @click="submitNewProject">Create Project</button>
        </div>
      </div>
    </div>

    <!-- Pipeline Trigger Modal -->
    <div v-if="showPipelineModal" class="modal-backdrop" @click.self="showPipelineModal = false">
      <div class="modal-box">
        <h3>Trigger Unified CI/CD Pipeline</h3>
        <p class="modal-desc">
          Executes end-to-end workflow: Git tracking → Code Validation (Quality Gate) → Docker/Jenkins Build → Container Deployment → Health Probe.
        </p>

        <div class="form-group checkbox-row">
          <label>
            <input type="checkbox" v-model="pipelineOptions.auto_commit" />
            Auto-commit modified files before validation
          </label>
        </div>

        <div class="form-group" v-if="pipelineOptions.auto_commit">
          <label>Commit Message</label>
          <input v-model="pipelineOptions.commit_message" placeholder="Automated pipeline commit" />
        </div>

        <div class="form-group">
          <label>CI Build Engine</label>
          <select v-model="pipelineOptions.use_jenkins">
            <option :value="false">Local Docker Engine (Direct build)</option>
            <option :value="true">Jenkins Pipeline Job (automator-deploy)</option>
          </select>
        </div>

        <div class="form-group checkbox-row">
          <label>
            <input type="checkbox" v-model="pipelineOptions.deploy_container" />
            Deploy application container after build
          </label>
        </div>

        <div class="form-group" v-if="pipelineOptions.deploy_container">
          <label>Target Container Port</label>
          <input type="number" v-model.number="pipelineOptions.target_port" min="1024" max="65535" />
        </div>

        <div class="modal-actions">
          <button class="header-btn secondary" @click="showPipelineModal = false">Cancel</button>
          <button class="action-btn pipeline-btn" @click="confirmPipelineTrigger">Start Pipeline</button>
        </div>
      </div>
    </div>
  </header>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useWorkspaceStore } from '../stores/workspace'

const store = useWorkspaceStore()

const showNewProjectModal = ref(false)
const newProjectName = ref('')
const newProjectTemplate = ref('python')

const showPipelineModal = ref(false)
const pipelineOptions = ref({
  auto_commit: true,
  commit_message: 'Update and validate project',
  use_jenkins: false,
  deploy_container: true,
  target_port: 5001,
})

const unlistedWorkspaces = computed(() => {
  const detailedIds = new Set(store.projectsDetailed.map(p => p.id))
  return store.workspaces.filter(w => !detailedIds.has(w))
})

function onSelectProject(id) {
  if (id) {
    store.selectWorkspace(id)
  }
}

async function submitNewProject() {
  const name = newProjectName.value.trim() || 'New Project'
  await store.createWorkspace(name, newProjectTemplate.value)
  showNewProjectModal.value = false
  newProjectName.value = ''
}

async function runValidation() {
  if (store.currentWorkspace) {
    await store.loadValidationData(store.currentWorkspace)
    store.currentView = 'validation'
  }
}

async function confirmPipelineTrigger() {
  showPipelineModal.value = false
  await store.triggerUnifiedPipeline(pipelineOptions.value)
}
</script>

<style scoped>
.top-header {
  height: 48px;
  background: #1e1e24;
  border-bottom: 1px solid #27272a;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  flex-shrink: 0;
  z-index: 10;
}

.header-left, .header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.project-selector-wrapper {
  display: flex;
  align-items: center;
  gap: 8px;
}

.label {
  font-size: 12px;
  color: #a1a1aa;
  font-weight: 500;
}

.project-select {
  background: #27272a;
  color: #f4f4f5;
  border: 1px solid #3f3f46;
  padding: 5px 10px;
  border-radius: 6px;
  font-size: 12px;
  outline: none;
  min-width: 170px;
  cursor: pointer;
}

.header-btn {
  background: #27272a;
  color: #e4e4e7;
  border: 1px solid #3f3f46;
  padding: 5px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.header-btn:hover {
  background: #3f3f46;
  color: #fff;
}

.header-btn.secondary {
  color: #60a5fa;
  border-color: #1e3a8a;
  background: #172554;
}

.header-btn.secondary:hover {
  background: #1e40af;
  color: #fff;
}

.badge-group {
  display: flex;
  gap: 6px;
}

.status-pill {
  font-size: 11px;
  padding: 4px 8px;
  border-radius: 12px;
  font-weight: 500;
  background: #27272a;
  border: 1px solid #3f3f46;
  color: #a1a1aa;
}

.status-pill.online {
  border-color: #059669;
  background: #064e3b;
  color: #34d399;
}

.status-pill.offline {
  border-color: #7f1d1d;
  background: #450a0a;
  color: #f87171;
}

.action-buttons {
  display: flex;
  gap: 8px;
}

.action-btn {
  border: none;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.validate-btn {
  background: #4f46e5;
  color: white;
}

.validate-btn:hover:not(:disabled) {
  background: #4338ca;
}

.pipeline-btn {
  background: #059669;
  color: white;
}

.pipeline-btn:hover:not(:disabled) {
  background: #047857;
}

.save-btn {
  background: #3b82f6;
  color: white;
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Modals */
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
  width: 440px;
  max-width: 90vw;
  box-shadow: 0 10px 25px rgba(0,0,0,0.5);
}

.modal-box h3 {
  font-size: 16px;
  color: #f4f4f5;
  margin-bottom: 8px;
}

.modal-desc {
  font-size: 12px;
  color: #a1a1aa;
  margin-bottom: 16px;
  line-height: 1.4;
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

.form-group input, .form-group select {
  background: #27272a;
  border: 1px solid #3f3f46;
  color: #f4f4f5;
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 13px;
  outline: none;
}

.form-group input:focus, .form-group select:focus {
  border-color: #3b82f6;
}

.form-group.checkbox-row {
  flex-direction: row;
  align-items: center;
}

.form-group.checkbox-row label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}
</style>
