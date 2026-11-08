<template>
  <div class="view-container">
    <div class="view-header">
      <div>
        <h2 class="view-title">Code Validation & Quality Gate</h2>
        <p class="view-subtitle">Syntax checking, PEP8 naming audit, security vulnerability scanning, and automated tests for the active project.</p>
      </div>
      <div class="view-actions">
        <button
          class="btn primary"
          :disabled="!store.currentWorkspace || store.validating"
          @click="runScan"
        >
          {{ store.validating ? 'Running Scan...' : '🛡️ Run Full Validation' }}
        </button>
      </div>
    </div>

    <!-- Summary Overview Card -->
    <div class="card" v-if="store.validationResult">
      <div class="summary-grid">
        <div class="score-box">
          <div class="score-circle" :class="scoreClass">
            <span class="score-num">{{ store.validationResult.score }}</span>
            <span class="score-denom">/100</span>
          </div>
          <span class="score-label">Quality Score</span>
        </div>

        <div class="gate-status-box">
          <span class="gate-title">Mandatory Quality Gate</span>
          <span
            class="gate-badge"
            :class="store.validationResult.mandatory_checks_passed ? 'passed' : 'blocked'"
          >
            {{ store.validationResult.mandatory_checks_passed ? '✓ GATE PASSED' : '⛔ DEPLOYMENT BLOCKED' }}
          </span>
          <span class="gate-desc">
            {{ store.validationResult.mandatory_checks_passed
              ? 'No fatal syntax errors or high-severity vulnerabilities detected.'
              : `${store.validationResult.summary?.errors} fatal error(s) must be resolved prior to pipeline deployment.`
            }}
          </span>
        </div>

        <div class="counts-box">
          <div class="count-item danger">
            <span class="count-num">{{ store.validationResult.summary?.errors || 0 }}</span>
            <span class="count-label">Errors</span>
          </div>
          <div class="count-item warning">
            <span class="count-num">{{ store.validationResult.summary?.warnings || 0 }}</span>
            <span class="count-label">Warnings</span>
          </div>
          <div class="count-item info">
            <span class="count-num">{{ store.validationResult.summary?.info || 0 }}</span>
            <span class="count-label">Info</span>
          </div>
          <div class="count-item success">
            <span class="count-num">{{ store.validationResult.test_results?.total || 0 }}</span>
            <span class="count-label">Tests</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Automated Tests Panel if tests exist -->
    <div class="card" v-if="store.validationResult && store.validationResult.test_results?.executed">
      <div class="card-header">
        <h3>Automated Tests Execution</h3>
        <span class="badge" :class="store.validationResult.test_results.failed === 0 ? 'success' : 'danger'">
          {{ store.validationResult.test_results.passed }} Passed / {{ store.validationResult.test_results.failed }} Failed
        </span>
      </div>
      <div class="card-body">
        <pre class="test-details-log">{{ store.validationResult.test_results.details }}</pre>
      </div>
    </div>

    <!-- Structured Issues List -->
    <div class="card issues-card" v-if="store.validationResult">
      <div class="card-header">
        <h3>Detected Issues & Recommendations ({{ filteredIssues.length }})</h3>
        <div class="filter-pills">
          <button
            v-for="cat in categories"
            :key="cat.id"
            class="filter-pill"
            :class="{ active: activeFilter === cat.id }"
            @click="activeFilter = cat.id"
          >
            {{ cat.label }}
          </button>
        </div>
      </div>

      <div class="card-body p-0" v-if="filteredIssues.length">
        <table class="issues-table">
          <thead>
            <tr>
              <th>Severity</th>
              <th>Rule & Category</th>
              <th>File & Location</th>
              <th>Description</th>
              <th>Suggested Fix</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="issue in filteredIssues" :key="issue.id + issue.file_path + issue.line">
              <td>
                <span class="severity-pill" :class="issue.severity">
                  {{ issue.severity.toUpperCase() }}
                </span>
              </td>
              <td>
                <span class="rule-id">{{ issue.rule }}</span>
                <span class="cat-tag">{{ issue.category }}</span>
              </td>
              <td>
                <span class="location-badge">
                  {{ issue.file_path }}:{{ issue.line }}:{{ issue.col }}
                </span>
              </td>
              <td>
                <div class="issue-msg">{{ issue.message }}</div>
                <div v-if="issue.code_snippet" class="issue-code">
                  <code>{{ issue.code_snippet }}</code>
                </div>
              </td>
              <td>
                <div class="fix-tip">💡 {{ issue.suggested_fix }}</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="card-body empty-state" v-else>
        🎉 No issues matching the selected filter. Clean code!
      </div>
    </div>

    <!-- Empty State if no project or scan -->
    <div v-else class="card empty-card">
      <p>Click "Run Full Validation" above to scan the active project for errors and security risks.</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useWorkspaceStore } from '../stores/workspace'

const store = useWorkspaceStore()
const activeFilter = ref('all')

const categories = [
  { id: 'all', label: 'All Issues' },
  { id: 'error', label: 'Errors Only' },
  { id: 'syntax', label: 'Syntax' },
  { id: 'security', label: 'Security' },
  { id: 'naming', label: 'Naming & PEP8' },
  { id: 'lint', label: 'Linting' },
]

onMounted(async () => {
  if (store.currentWorkspace && !store.validationResult) {
    await store.loadValidationData(store.currentWorkspace)
  }
})

async function runScan() {
  if (store.currentWorkspace) {
    await store.loadValidationData(store.currentWorkspace)
  }
}

const scoreClass = computed(() => {
  if (!store.validationResult) return ''
  const s = store.validationResult.score
  if (s >= 90) return 'high'
  if (s >= 70) return 'mid'
  return 'low'
})

const filteredIssues = computed(() => {
  if (!store.validationResult || !store.validationResult.issues) return []
  const all = store.validationResult.issues
  if (activeFilter.value === 'all') return all
  if (activeFilter.value === 'error') return all.filter(i => i.severity === 'error')
  return all.filter(i => i.category === activeFilter.value)
})
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

.summary-grid {
  display: grid;
  grid-template-columns: 140px 1.5fr 1fr;
  padding: 20px;
  gap: 20px;
  align-items: center;
}

@media (max-width: 900px) {
  .summary-grid {
    grid-template-columns: 1fr;
  }
}

.score-box {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.score-circle {
  width: 90px;
  height: 90px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 4px solid #3f3f46;
  background: #18181b;
}

.score-circle.high { border-color: #10b981; color: #10b981; }
.score-circle.mid { border-color: #f59e0b; color: #f59e0b; }
.score-circle.low { border-color: #ef4444; color: #ef4444; }

.score-num { font-size: 26px; font-weight: 700; }
.score-denom { font-size: 14px; color: #71717a; }
.score-label { font-size: 11px; color: #a1a1aa; margin-top: 6px; text-transform: uppercase; font-weight: 600; }

.gate-status-box {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.gate-title {
  font-size: 11px;
  color: #a1a1aa;
  text-transform: uppercase;
  font-weight: 600;
}

.gate-badge {
  font-size: 14px;
  font-weight: 700;
  padding: 6px 14px;
  border-radius: 6px;
  width: fit-content;
}

.gate-badge.passed {
  background: #064e3b;
  border: 1px solid #059669;
  color: #34d399;
}

.gate-badge.blocked {
  background: #450a0a;
  border: 1px solid #b91c1c;
  color: #fca5a5;
}

.gate-desc {
  font-size: 12px;
  color: #a1a1aa;
  line-height: 1.4;
}

.counts-box {
  display: flex;
  gap: 12px;
}

.count-item {
  flex: 1;
  background: #18181b;
  border-radius: 6px;
  padding: 10px;
  text-align: center;
  display: flex;
  flex-direction: column;
}

.count-num {
  font-size: 20px;
  font-weight: 700;
}

.count-label {
  font-size: 10px;
  color: #a1a1aa;
  text-transform: uppercase;
}

.count-item.danger .count-num { color: #ef4444; }
.count-item.warning .count-num { color: #f59e0b; }
.count-item.info .count-num { color: #60a5fa; }
.count-item.success .count-num { color: #10b981; }

.filter-pills {
  display: flex;
  gap: 6px;
}

.filter-pill {
  background: #18181b;
  border: 1px solid #3f3f46;
  color: #a1a1aa;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
}

.filter-pill.active {
  background: #2563eb;
  border-color: #2563eb;
  color: white;
  font-weight: 600;
}

.p-0 { padding: 0 !important; }

.issues-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.issues-table th, .issues-table td {
  padding: 10px 14px;
  border-bottom: 1px solid #323238;
  vertical-align: top;
}

.issues-table th {
  color: #a1a1aa;
  font-weight: 600;
  font-size: 11px;
  text-transform: uppercase;
  background: #202024;
}

.severity-pill {
  font-size: 9px;
  font-weight: 700;
  padding: 3px 6px;
  border-radius: 4px;
}

.severity-pill.error { background: #7f1d1d; color: #fca5a5; }
.severity-pill.warning { background: #78350f; color: #fcd34d; }
.severity-pill.info { background: #1e3a8a; color: #93c5fd; }

.rule-id {
  display: block;
  font-family: monospace;
  font-size: 11px;
  color: #f4f4f5;
  font-weight: 600;
}

.cat-tag {
  font-size: 10px;
  color: #a1a1aa;
  text-transform: capitalize;
}

.location-badge {
  font-family: monospace;
  font-size: 11px;
  color: #93c5fd;
  background: #18181b;
  padding: 2px 6px;
  border-radius: 4px;
  white-space: nowrap;
}

.issue-msg {
  color: #f4f4f5;
  font-weight: 500;
  margin-bottom: 4px;
}

.issue-code {
  background: #18181b;
  border: 1px solid #3f3f46;
  border-radius: 4px;
  padding: 4px 8px;
  font-size: 11px;
  color: #fca5a5;
  font-family: monospace;
  white-space: pre-wrap;
}

.fix-tip {
  color: #34d399;
  font-size: 11.5px;
  background: #064e3b22;
  padding: 4px 8px;
  border-radius: 4px;
}

.test-details-log {
  background: #18181b;
  padding: 10px;
  border-radius: 6px;
  font-family: monospace;
  font-size: 11px;
  color: #d4d4d8;
  white-space: pre-wrap;
}

.empty-card {
  text-align: center;
  padding: 40px;
  color: #71717a;
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
.btn.primary:hover:not(:disabled) { background: #1d4ed8; }
.btn.primary:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
