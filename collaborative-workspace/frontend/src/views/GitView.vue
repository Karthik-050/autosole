<template>
  <div class="view-container">
    <div class="view-header">
      <div>
        <h2 class="view-title">Git & Version Control</h2>
        <p class="view-subtitle">Track repository status, inspect file diffs, create commits, and browse revision history for the active project.</p>
      </div>
      <div class="view-actions">
        <button class="btn primary" @click="openAutomatorCICD">🚀 Automator CI/CD</button>
        <button class="btn secondary" @click="refreshGit">&#x21bb; Refresh</button>
      </div>
    </div>

    <div class="card connect-card">
      <div class="card-header"><h3>Start From a GitHub Repository</h3></div>
      <div class="card-body">
        <p class="empty-text">Paste a GitHub HTTPS repository URL. Project K will create a new project from it, preserve your current project, and queue a Jenkins build. The pull token entered here is not saved; private repositories need a Jenkins credential before the first build.</p>
        <form class="connect-form" @submit.prevent="connectRepository">
          <input v-model="repositoryUrl" type="url" required placeholder="https://github.com/owner/repository" :disabled="connecting" />
          <input v-model="repositoryBranch" type="text" placeholder="Branch (optional; uses default branch)" :disabled="connecting" />
          <input v-model="repositoryToken" type="password" autocomplete="new-password" placeholder="GitHub token (private repositories)" :disabled="connecting" />
          <button class="btn primary" type="submit" :disabled="connecting || !repositoryUrl.trim()">
            {{ connecting ? 'Connecting…' : 'Pull Repository and Start Pipeline' }}
          </button>
        </form>
        <p v-if="connectError" class="connect-error">{{ connectError }}</p>
        <p v-if="pipelineRun" class="connect-success">
          Created project <strong>{{ connectedProjectName }}</strong> from branch <strong>{{ connectedRepository?.branch }}</strong>; Jenkins job <strong>{{ pipelineRun.job_name }}</strong> is queued (queue #{{ pipelineRun.queue_id }}).
        </p>
        <div v-if="webhookSetup" class="webhook-help">
          <strong>Push webhook:</strong>
          <span v-if="webhookSetup.callback_url">Set this URL in GitHub repository Settings → Webhooks: {{ webhookSetup.callback_url }}</span>
          <span v-else>Set PUBLIC_BASE_URL to a public HTTPS address for this app, then configure {{ webhookSetup.endpoint }} in GitHub repository Settings → Webhooks.</span>
          <span>Set GITHUB_WEBHOOK_SECRET in the app and use the same secret in GitHub. Select the push event.</span>
        </div>
      </div>
    </div>

    <!-- If Git is not initialized -->
    <div v-if="store.gitStatus && !store.gitStatus.is_repo" class="card empty-card">
      <div class="empty-icon">🌿</div>
      <h3>Git Repository Not Initialized</h3>
      <p>This workspace is not currently tracked by Git version control.</p>
      <button class="btn primary" @click="store.initGit()">Initialize Git Repository</button>
    </div>

    <!-- Git Active Dashboard -->
    <div v-else-if="store.gitStatus" class="git-layout">
      <!-- Left Column: Status, Changed Files, and Commit Form -->
      <div class="git-column left">
        <div class="card">
          <div class="card-header">
            <h3>Working Tree Status</h3>
            <span class="badge info">Branch: {{ store.gitStatus.branch || 'main' }}</span>
          </div>
          <div class="card-body">
            <div class="repo-meta-bar">
              <span>Total Commits: <strong>{{ store.gitStatus.commit_count }}</strong></span>
              <span :class="store.gitStatus.clean ? 'text-success' : 'text-warning'">
                {{ store.gitStatus.clean ? '✓ Working tree clean' : '● Uncommitted changes present' }}
              </span>
            </div>

            <!-- Changed Files List -->
            <div class="changes-list-section">
              <h4>Modified & Untracked Files</h4>
              <div v-if="store.gitStatus.clean" class="empty-text">
                No local changes detected.
              </div>
              <div v-else class="files-list">
                <div
                  v-for="f in store.gitStatus.unstaged"
                  :key="f.file"
                  class="file-row"
                  @click="inspectDiff(f.file)"
                >
                  <span class="file-tag mod">MOD</span>
                  <span class="file-path">{{ f.file }}</span>
                </div>
                <div
                  v-for="f in store.gitStatus.untracked"
                  :key="f"
                  class="file-row"
                  @click="inspectDiff(f)"
                >
                  <span class="file-tag new">NEW</span>
                  <span class="file-path">{{ f }}</span>
                </div>
              </div>
            </div>

            <!-- Commit Form -->
            <div class="commit-section">
              <h4>Commit Changes Locally</h4>
              <p class="push-token-help">A commit stays in this workspace until you push it to GitHub.</p>
              <textarea
                v-model="commitMessage"
                class="commit-input"
                placeholder="Write a clear commit message..."
                rows="3"
              ></textarea>
              <div class="commit-actions">
                <button
                  class="btn primary"
                  :disabled="store.gitStatus.clean || !commitMessage.trim()"
                  @click="doCommit"
                >
                  Commit locally to {{ store.gitStatus.branch || 'main' }}
                </button>
              </div>
              <div v-if="store.gitStatus.has_remote" class="push-section">
                <div class="push-status" :class="{ behind: store.gitStatus.behind > 0 }">
                  <template v-if="store.gitStatus.behind > 0">
                    Remote is {{ store.gitStatus.behind }} commit(s) ahead. Synchronize before pushing.
                  </template>
                  <template v-else-if="store.gitStatus.ahead > 0">
                    {{ store.gitStatus.ahead }} local commit(s) are ready to push.
                  </template>
                  <template v-else>
                    Local branch is synchronized with its remote.
                  </template>
                </div>
                <input
                  v-if="store.gitStatus.ahead > 0"
                  v-model="pushToken"
                  class="push-token-input"
                  type="password"
                  autocomplete="off"
                  spellcheck="false"
                  placeholder="GitHub token with repository Contents write access"
                  aria-label="GitHub token for pushing commits"
                />
                <p v-if="store.gitStatus.ahead > 0" class="push-token-help">Used only for this push. It is not saved by the Workspace.</p>
                <div class="commit-actions">
                  <button
                    class="btn secondary"
                    :disabled="pushing || store.gitStatus.ahead === 0 || store.gitStatus.behind > 0"
                    @click="doPush"
                  >
                    <template v-if="pushing">Pushing...</template>
                    <template v-else>Push {{ store.gitStatus.ahead }} commit(s) to GitHub</template>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Git Diff Viewer -->
        <div class="card diff-card">
          <div class="card-header">
            <h3>Working Tree Diff</h3>
            <span class="diff-file-label">{{ selectedDiffFile || 'All Files' }}</span>
          </div>
          <div class="card-body diff-body">
            <pre v-if="diffOutput" class="diff-content">{{ diffOutput }}</pre>
            <div v-else class="empty-text">No active diff to display.</div>
          </div>
        </div>
      </div>

      <!-- Right Column: Commit History -->
      <div class="git-column right">
        <div class="card history-card">
          <div class="card-header">
            <h3>Commit History (Log)</h3>
            <span class="badge neutral">{{ store.gitHistory.length }} recent</span>
          </div>
          <div class="card-body history-body" v-if="store.gitHistory.length">
            <div
              v-for="c in store.gitHistory"
              :key="c.hash"
              class="history-item"
            >
              <div class="history-item-top">
                <span class="commit-hash">{{ c.short_hash }}</span>
                <span class="commit-author">{{ c.author }}</span>
                <span class="commit-date">{{ formatDate(c.date) }}</span>
              </div>
              <div class="commit-msg">{{ c.message }}</div>
            </div>
          </div>
          <div class="card-body empty-state" v-else>
            No commit history available. Make your first commit above.
          </div>
        </div>
      </div>
    </div>

    <!-- If no workspace selected -->
    <div v-else class="card empty-card">
      <p>Select a project to view its Git version control status.</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useWorkspaceStore } from '../stores/workspace'
import { gitApi } from '../api'

const store = useWorkspaceStore()
const commitMessage = ref('')
const pushToken = ref('')
const pushing = ref(false)
const selectedDiffFile = ref('')
const diffOutput = ref('')
const repositoryUrl = ref('')
const repositoryBranch = ref('')
const repositoryToken = ref('')
const connecting = ref(false)
const connectError = ref('')
const pipelineRun = ref(null)
const connectedRepository = ref(null)
const connectedProjectName = ref('')
const webhookSetup = ref(null)

onMounted(async () => {
  await refreshGit()
})

async function refreshGit() {
  if (store.currentWorkspace) {
    await store.loadGitData(store.currentWorkspace)
    await loadDiff()
  }
}

async function loadDiff(file = '') {
  selectedDiffFile.value = file
  if (store.currentWorkspace) {
    try {
      diffOutput.value = await gitApi.getDiff(store.currentWorkspace, file)
    } catch {
      diffOutput.value = ''
    }
  }
}

function inspectDiff(file) {
  loadDiff(file)
}

async function doCommit() {
  if (!commitMessage.value.trim()) return
  await store.commitGit(commitMessage.value)
  commitMessage.value = ''
  await refreshGit()
}

async function doPush() {
  if (pushing.value || !store.gitStatus?.has_remote || !store.gitStatus.ahead) return
  pushing.value = true
  try {
    await store.pushGit(pushToken.value.trim())
  } finally {
    pushToken.value = ''
    pushing.value = false
  }
}

async function connectRepository() {
  if (!repositoryUrl.value.trim()) return
  connecting.value = true
  connectError.value = ''
  pipelineRun.value = null
  connectedRepository.value = null
  connectedProjectName.value = ''
  webhookSetup.value = null
  try {
    const result = await gitApi.connectRepository(
      repositoryUrl.value.trim(),
      repositoryBranch.value.trim() || undefined,
      repositoryToken.value || undefined,
    )
    connectedRepository.value = result.repository
    pipelineRun.value = result.pipeline
    webhookSetup.value = result.webhook || null
    await store.loadProjects()
    await store.selectWorkspace(result.project_id)
    connectedProjectName.value = store.currentProjectDetails?.name || result.project_id
    if (result.pipeline_error) connectError.value = `Repository pulled, but pipeline could not start: ${result.pipeline_error}`
    await refreshGit()
  } catch (error) {
    connectError.value = error.response?.data?.detail || error.message || 'Could not connect repository.'
  } finally {
    repositoryToken.value = ''
    connecting.value = false
  }
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr)
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return dateStr
  }
}

function openAutomatorCICD() {
  const host = window.location.hostname || '127.0.0.1'
  window.open(`${window.location.protocol}//${host}:8001/`, '_blank', 'noopener')
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

.git-layout {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 16px;
  flex: 1;
}

@media (max-width: 960px) {
  .git-layout {
    grid-template-columns: 1fr;
  }
}

.git-column {
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

.card-body {
  padding: 16px;
}

.repo-meta-bar {
  display: flex;
  justify-content: space-between;
  padding-bottom: 12px;
  border-bottom: 1px solid #323238;
  font-size: 12.5px;
}

.changes-list-section {
  margin: 14px 0;
}

.changes-list-section h4, .commit-section h4 {
  font-size: 12px;
  color: #a1a1aa;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}

.files-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 140px;
  overflow-y: auto;
}

.file-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 8px;
  background: #18181b;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  font-family: monospace;
}

.file-row:hover {
  background: #3f3f46;
}

.file-tag {
  font-size: 9px;
  font-weight: 700;
  padding: 2px 5px;
  border-radius: 3px;
}

.file-tag.mod { background: #d97706; color: white; }
.file-tag.new { background: #059669; color: white; }

.file-path {
  color: #f4f4f5;
  overflow: hidden;
  text-overflow: ellipsis;
}

.commit-section {
  margin-top: 14px;
  border-top: 1px solid #323238;
  padding-top: 12px;
}

.commit-input {
  width: 100%;
  background: #18181b;
  border: 1px solid #3f3f46;
  border-radius: 6px;
  color: #f4f4f5;
  padding: 8px 10px;
  font-size: 12.5px;
  outline: none;
  resize: vertical;
  font-family: inherit;
  box-sizing: border-box;
}

.commit-input:focus {
  border-color: #2563eb;
}

.commit-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}

.push-section {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #323238;
}

.push-status { color: #a1a1aa; font-size: 12px; margin-bottom: 8px; }
.push-status.behind { color: #fbbf24; }
.push-token-input { width: 100%; padding: 9px 10px; border-radius: 6px; border: 1px solid #3f3f46; background: #18181b; color: #f4f4f5; }
.push-token-help { margin: 5px 0 0; color: #71717a; font-size: 11px; }

.diff-card {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.diff-file-label {
  font-size: 11px;
  color: #a1a1aa;
  font-family: monospace;
}

.diff-body {
  flex: 1;
  background: #18181b;
  overflow-y: auto;
  max-height: 250px;
}

.diff-content {
  font-family: monospace;
  font-size: 11.5px;
  color: #d4d4d8;
  white-space: pre-wrap;
  margin: 0;
}

.history-card {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.history-body {
  overflow-y: auto;
  max-height: 520px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.history-item {
  background: #18181b;
  border: 1px solid #3f3f46;
  border-radius: 6px;
  padding: 10px 12px;
}

.history-item-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.commit-hash {
  font-family: monospace;
  font-weight: 700;
  color: #60a5fa;
  font-size: 11px;
  background: #1e3a8a;
  padding: 2px 6px;
  border-radius: 4px;
}

.commit-author {
  font-size: 11px;
  color: #d4d4d8;
  font-weight: 500;
}

.commit-date {
  font-size: 10px;
  color: #71717a;
  margin-left: auto;
}

.commit-msg {
  font-size: 12.5px;
  color: #f4f4f5;
}

.empty-card {
  text-align: center;
  padding: 40px;
}

.connect-card { margin-bottom: 16px; }
.connect-form { display: flex; gap: 8px; flex-wrap: wrap; }
.connect-form input { flex: 1 1 220px; min-width: 0; padding: 9px 10px; border-radius: 6px; border: 1px solid #3f3f46; background: #18181b; color: #f4f4f5; }
.connect-error { color: #f87171; margin-top: 10px; }
.connect-success { color: #4ade80; margin-top: 10px; }
.webhook-help { display: flex; flex-direction: column; gap: 5px; margin-top: 12px; padding: 10px; border: 1px solid #3f3f46; border-radius: 6px; color: #a1a1aa; font-size: 12px; overflow-wrap: anywhere; }

.empty-icon {
  font-size: 40px;
  margin-bottom: 12px;
}

.empty-text {
  font-size: 12px;
  color: #71717a;
  padding: 10px 0;
}

.badge {
  padding: 3px 8px;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 700;
}

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
</style>
