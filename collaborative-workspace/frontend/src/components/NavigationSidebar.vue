<template>
  <aside class="nav-sidebar">
    <div class="nav-brand">
      <div class="brand-icon">⚡</div>
      <div class="brand-text">
        <span class="brand-title">Automator</span>
        <span class="brand-sub">Workspace</span>
      </div>
    </div>

    <nav class="nav-menu">
      <button
        v-for="item in navItems"
        :key="item.id"
        class="nav-item"
        :class="{ active: store.currentView === item.id }"
        @click="navigate(item.id)"
      >
        <span class="nav-icon">{{ item.icon }}</span>
        <span class="nav-label">{{ item.label }}</span>
        <span v-if="item.badge" class="nav-badge" :class="item.badgeClass">{{ item.badge }}</span>
      </button>
    </nav>

    <div class="nav-footer">
      <div class="status-indicator" :class="{ ok: store.dockerStatus.available }">
        <span class="dot"></span>
        <span class="text">Docker: {{ store.dockerStatus.available ? 'Ready' : 'Offline' }}</span>
      </div>
      <div class="status-indicator" :class="{ ok: store.jenkinsStatus.available }">
        <span class="dot"></span>
        <span class="text">Jenkins: {{ store.jenkinsStatus.available ? 'Ready' : 'Offline' }}</span>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { useWorkspaceStore } from '../stores/workspace'

const store = useWorkspaceStore()

const navItems = computed(() => [
  { id: 'dashboard', label: 'Dashboard', icon: '📊' },
  { id: 'workspace', label: 'Workspace', icon: '💻' },
  { id: 'git', label: 'Git & Versioning', icon: '🌿' },
  { id: 'automator-cicd', label: 'Automator CI/CD', icon: '🚀' },
  {
    id: 'validation',
    label: 'Code Validation',
    icon: '🛡️',
    badge: store.validationResult ? (store.validationResult.summary?.errors ? `${store.validationResult.summary.errors} err` : 'pass') : null,
    badgeClass: store.validationResult?.summary?.errors ? 'danger' : 'success'
  },
  { id: 'docker', label: 'Docker Engine', icon: '🐳' },
  { id: 'jenkins', label: 'Jenkins CI/CD', icon: '⚙️' },
  {
    id: 'deployments',
    label: 'Deployments',
    icon: '🚀',
    badge: store.deployments.length ? `${store.deployments.length}` : null,
    badgeClass: 'info'
  },
  { id: 'settings', label: 'Settings', icon: '🔧' },
])

function navigate(viewId) {
  if (viewId === 'automator-cicd') {
    const host = window.location.hostname || '127.0.0.1'
    window.open(`${window.location.protocol}//${host}:8001/`, '_blank', 'noopener')
    return
  }
  store.currentView = viewId
}
</script>

<style scoped>
.nav-sidebar {
  width: 220px;
  min-width: 200px;
  background: #18181b;
  border-right: 1px solid #27272a;
  display: flex;
  flex-direction: column;
  user-select: none;
  flex-shrink: 0;
}

.nav-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 14px;
  border-bottom: 1px solid #27272a;
}

.brand-icon {
  font-size: 20px;
  background: #3b82f6;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
}

.brand-text {
  display: flex;
  flex-direction: column;
}

.brand-title {
  font-size: 13px;
  font-weight: 700;
  color: #f4f4f5;
  letter-spacing: 0.5px;
}

.brand-sub {
  font-size: 10px;
  color: #71717a;
  text-transform: uppercase;
  letter-spacing: 1px;
}

.nav-menu {
  flex: 1;
  padding: 12px 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow-y: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: #a1a1aa;
  font-size: 12.5px;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
  transition: all 0.15s ease;
  width: 100%;
}

.nav-item:hover {
  background: #27272a;
  color: #fafafa;
}

.nav-item.active {
  background: #2563eb;
  color: #ffffff;
  font-weight: 600;
}

.nav-icon {
  font-size: 14px;
}

.nav-label {
  flex: 1;
}

.nav-badge {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 10px;
  font-weight: 600;
}

.nav-badge.danger {
  background: #ef4444;
  color: white;
}

.nav-badge.success {
  background: #10b981;
  color: white;
}

.nav-badge.info {
  background: #3f3f46;
  color: #e4e4e7;
}

.nav-footer {
  padding: 12px 14px;
  border-top: 1px solid #27272a;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 11px;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #71717a;
}

.status-indicator.ok {
  color: #10b981;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #ef4444;
}

.status-indicator.ok .dot {
  background: #10b981;
}
</style>
