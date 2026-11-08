import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  workspaceApi,
  fileApi,
  runApi,
  projectApi,
  dashboardApi,
  gitApi,
  validationApi,
  dockerApi,
  jenkinsApi,
  pipelineApi,
  deploymentApi,
  settingsApi,
} from '../api'

export const useWorkspaceStore = defineStore('workspace', () => {
  // Navigation & View state
  const currentView = ref('dashboard') // dashboard, workspace, git, validation, docker, jenkins, deployments, settings

  // Workspaces / Projects
  const workspaces = ref([])
  const projectsDetailed = ref([])
  const currentWorkspace = ref(null)
  const currentProjectDetails = computed(() => {
    return projectsDetailed.value.find(p => p.id === currentWorkspace.value) || null
  })

  // File management
  const files = ref([])
  const openTabs = ref([])
  const activeTab = ref(null)
  const fileContents = ref({})
  const output = ref(null)
  const running = ref(false)

  // Subsystems Status
  const dockerStatus = ref({ available: false, status: 'checking', error: null })
  const jenkinsStatus = ref({ available: false, status: 'checking', error: null })
  const dashboardStats = ref(null)

  // Git state
  const gitStatus = ref(null)
  const gitHistory = ref([])
  const gitDiff = ref('')

  // Validation state
  const validationResult = ref(null)
  const validating = ref(false)

  // Docker & Jenkins state
  const dockerImages = ref([])
  const dockerContainers = ref([])
  const dockerfileContent = ref('')
  const jenkinsJobs = ref([])
  const latestBuild = ref(null)
  const jenkinsConsole = ref('')

  // Pipeline Orchestration state
  const pipelineRuns = ref([])
  const activePipelineRun = ref(null)
  const pipelinePollingInterval = ref(null)

  // Deployments state
  const deployments = ref([])

  // Notifications
  const notification = ref(null)
  function showNotification(message, type = 'info') {
    notification.value = { message, type }
    setTimeout(() => {
      if (notification.value && notification.value.message === message) {
        notification.value = null
      }
    }, 4000)
  }

  // ---------------- LOAD ALL BASE DATA ----------------
  async function loadInitialData() {
    await Promise.allSettled([
      loadProjects(),
      checkServicesStatus(),
      loadDeployments(),
      loadPipelineRuns(),
    ])
  }

  async function checkServicesStatus() {
    try {
      dockerStatus.value = await dockerApi.getStatus()
    } catch (e) {
      dockerStatus.value = { available: false, status: 'error', error: e.message }
    }
    try {
      jenkinsStatus.value = await jenkinsApi.getStatus()
    } catch (e) {
      jenkinsStatus.value = { available: false, status: 'error', error: e.message }
    }
  }

  async function loadProjects() {
    try {
      const projs = await projectApi.list()
      projectsDetailed.value = projs
      workspaces.value = projs.map(p => p.id)

      if (!currentWorkspace.value && projs.length > 0) {
        await selectWorkspace(projs[0].id)
      }
    } catch (e) {
      // Fallback to legacy workspaceApi
      workspaces.value = await workspaceApi.list()
      if (!currentWorkspace.value && workspaces.value.length > 0) {
        await selectWorkspace(workspaces.value[0])
      }
    }
    await refreshDashboard()
  }

  async function loadWorkspaces() {
    await loadProjects()
  }

  async function createWorkspace(name, template = 'python') {
    try {
      const res = await projectApi.create(name, template)
      await loadProjects()
      await selectWorkspace(res.project.id)
      showNotification(`Created project "${res.project.name}"`, 'success')
      return res.project.id
    } catch (e) {
      showNotification(`Failed to create project: ${e.message}`, 'error')
    }
  }

  async function importAutomatorProject() {
    try {
      const res = await projectApi.importAutomatorTest()
      await loadProjects()
      await selectWorkspace(res.project.id)
      showNotification('Automator test project imported successfully!', 'success')
    } catch (e) {
      showNotification(`Failed to import Automator project: ${e.message}`, 'error')
    }
  }

  async function deleteWorkspace(id) {
    try {
      await workspaceApi.delete(id)
      if (currentWorkspace.value === id) {
        currentWorkspace.value = null
        files.value = []
        openTabs.value = []
        activeTab.value = null
        fileContents.value = {}
      }
      await loadProjects()
      showNotification('Project deleted', 'info')
    } catch (e) {
      showNotification(`Failed to delete project: ${e.message}`, 'error')
    }
  }

  async function selectWorkspace(id) {
    currentWorkspace.value = id
    openTabs.value = []
    activeTab.value = null
    fileContents.value = {}
    output.value = null

    try {
      files.value = await fileApi.list(id)
    } catch {
      files.value = []
    }

    // Load active project subsystem data
    await Promise.allSettled([
      loadGitData(id),
      loadValidationData(id),
      loadDockerfile(id),
      refreshDashboard(),
    ])
  }

  async function refreshFiles() {
    if (!currentWorkspace.value) return
    files.value = await fileApi.list(currentWorkspace.value)
  }

  async function openFile(filename) {
    if (!currentWorkspace.value) return

    const existing = openTabs.value.find(t => t.name === filename)
    if (existing) {
      activeTab.value = filename
      return
    }

    const content = await fileApi.read(currentWorkspace.value, filename)
    fileContents.value[filename] = content
    openTabs.value.push({ name: filename, modified: false })
    activeTab.value = filename
  }

  function closeTab(filename) {
    const idx = openTabs.value.findIndex(t => t.name === filename)
    if (idx !== -1) {
      openTabs.value.splice(idx, 1)
      delete fileContents.value[filename]
      if (activeTab.value === filename) {
        activeTab.value = openTabs.value.length > 0
          ? openTabs.value[Math.min(idx, openTabs.value.length - 1)].name
          : null
      }
    }
  }

  function updateContent(filename, content) {
    fileContents.value[filename] = content
    const tab = openTabs.value.find(t => t.name === filename)
    if (tab) tab.modified = true
  }

  async function saveFile(filename) {
    if (!currentWorkspace.value) return
    await fileApi.write(currentWorkspace.value, filename, fileContents.value[filename])
    const tab = openTabs.value.find(t => t.name === filename)
    if (tab) tab.modified = false
    showNotification(`Saved ${filename}`, 'success')
    // Trigger background validation update
    loadValidationData(currentWorkspace.value)
    loadGitData(currentWorkspace.value)
  }

  async function createFile(filename) {
    if (!currentWorkspace.value) return
    await fileApi.create(currentWorkspace.value, filename)
    await refreshFiles()
    await openFile(filename)
    loadGitData(currentWorkspace.value)
  }

  async function deleteFile(filename) {
    if (!currentWorkspace.value) return
    await fileApi.delete(currentWorkspace.value, filename)
    closeTab(filename)
    await refreshFiles()
    loadGitData(currentWorkspace.value)
  }

  async function runFile(filename) {
    if (!currentWorkspace.value) return
    running.value = true
    output.value = null
    try {
      output.value = await runApi.file(currentWorkspace.value, filename)
    } catch (e) {
      output.value = { stdout: '', stderr: e.message, exit_code: -1 }
    } finally {
      running.value = false
    }
  }

  // ---------------- GIT OPS ----------------
  async function loadGitData(id) {
    const wsId = id || currentWorkspace.value
    if (!wsId) return
    try {
      gitStatus.value = await gitApi.getStatus(wsId)
      gitHistory.value = await gitApi.getHistory(wsId, 15)
    } catch {
      gitStatus.value = null
      gitHistory.value = []
    }
  }

  async function initGit() {
    if (!currentWorkspace.value) return
    try {
      await gitApi.init(currentWorkspace.value)
      await loadGitData(currentWorkspace.value)
      showNotification('Git repository initialized', 'success')
    } catch (e) {
      showNotification(`Git init failed: ${e.message}`, 'error')
    }
  }

  async function commitGit(message) {
    if (!currentWorkspace.value) return
    try {
      const res = await gitApi.commit(currentWorkspace.value, message)
      await loadGitData(currentWorkspace.value)
      showNotification(res.message, res.committed ? 'success' : 'info')
    } catch (e) {
      showNotification(`Commit failed: ${e.message}`, 'error')
    }
  }

  async function pushGit(accessToken) {
    if (!currentWorkspace.value) return
    try {
      const res = await gitApi.push(currentWorkspace.value, accessToken)
      await loadGitData(currentWorkspace.value)
      showNotification(res.message, res.pushed ? 'success' : 'info')
      return res
    } catch (e) {
      const detail = e.response?.data?.detail || e.message
      showNotification(`Push failed: ${detail}`, 'error')
      return null
    }
  }

  // ---------------- VALIDATION OPS ----------------
  async function loadValidationData(id) {
    const wsId = id || currentWorkspace.value
    if (!wsId) return
    validating.value = true
    try {
      validationResult.value = await validationApi.scan(wsId)
    } catch (e) {
      validationResult.value = null
    } finally {
      validating.value = false
    }
  }

  // ---------------- DOCKER OPS ----------------
  async function loadDockerfile(id) {
    const wsId = id || currentWorkspace.value
    if (!wsId) return
    try {
      const res = await dockerApi.getDockerfile(wsId)
      dockerfileContent.value = res.content || ''
    } catch {
      dockerfileContent.value = ''
    }
  }

  async function loadDockerSubsystem() {
    dockerStatus.value = await dockerApi.getStatus()
    if (dockerStatus.value.available) {
      dockerImages.value = await dockerApi.getImages()
      dockerContainers.value = await dockerApi.getContainers()
    }
  }

  // ---------------- JENKINS OPS ----------------
  async function loadJenkinsSubsystem() {
    jenkinsStatus.value = await jenkinsApi.getStatus()
    if (jenkinsStatus.value.available) {
      jenkinsJobs.value = await jenkinsApi.getJobs()
    }
  }

  // ---------------- PIPELINE ORCHESTRATION ----------------
  async function loadPipelineRuns() {
    try {
      pipelineRuns.value = await pipelineApi.getRuns()
      if (activePipelineRun.value) {
        const updated = await pipelineApi.getRun(activePipelineRun.value.run_id)
        activePipelineRun.value = updated
      }
    } catch {}
  }

  async function triggerUnifiedPipeline(options = {}) {
    if (!currentWorkspace.value) return
    try {
      const payload = {
        project_id: currentWorkspace.value,
        auto_commit: options.auto_commit !== false,
        commit_message: options.commit_message || 'Automated pipeline run',
        use_jenkins: options.use_jenkins || false,
        build_docker: options.build_docker !== false,
        deploy_container: options.deploy_container !== false,
        target_port: options.target_port || 5001,
      }
      const res = await pipelineApi.trigger(payload)
      activePipelineRun.value = res.run
      showNotification('Pipeline execution started!', 'info')
      if (!options.keepView) currentView.value = 'dashboard'

      // Start polling for pipeline progress
      startPipelinePolling(res.run.run_id)
      return res.run
    } catch (e) {
      showNotification(`Failed to trigger pipeline: ${e.message}`, 'error')
    }
  }

  function startPipelinePolling(runId) {
    if (pipelinePollingInterval.value) {
      clearInterval(pipelinePollingInterval.value)
    }

    pipelinePollingInterval.value = setInterval(async () => {
      try {
        const run = await pipelineApi.getRun(runId)
        activePipelineRun.value = run
        await loadPipelineRuns()
        await loadDeployments()

        if (run.status === 'success' || run.status === 'failed') {
          clearInterval(pipelinePollingInterval.value)
          pipelinePollingInterval.value = null
          if (run.status === 'success') {
            showNotification('Pipeline completed successfully!', 'success')
          } else {
            showNotification(`Pipeline failed: ${run.error || 'Check logs'}`, 'error')
          }
        }
      } catch {
        clearInterval(pipelinePollingInterval.value)
      }
    }, 1000)
  }

  // ---------------- DEPLOYMENTS ----------------
  async function loadDeployments() {
    try {
      deployments.value = await deploymentApi.list()
    } catch {}
  }

  // ---------------- DASHBOARD REFRESH ----------------
  async function refreshDashboard() {
    try {
      dashboardStats.value = await dashboardApi.getStats(currentWorkspace.value)
    } catch {}
  }

  const activeContent = computed(() => {
    if (!activeTab.value) return ''
    return fileContents.value[activeTab.value] ?? ''
  })

  return {
    currentView,
    workspaces,
    projectsDetailed,
    currentWorkspace,
    currentProjectDetails,
    files,
    openTabs,
    activeTab,
    fileContents,
    output,
    running,
    dockerStatus,
    jenkinsStatus,
    dashboardStats,
    gitStatus,
    gitHistory,
    gitDiff,
    validationResult,
    validating,
    dockerImages,
    dockerContainers,
    dockerfileContent,
    jenkinsJobs,
    latestBuild,
    jenkinsConsole,
    pipelineRuns,
    activePipelineRun,
    deployments,
    notification,
    activeContent,
    showNotification,
    loadInitialData,
    loadWorkspaces,
    loadProjects,
    createWorkspace,
    importAutomatorProject,
    deleteWorkspace,
    selectWorkspace,
    refreshFiles,
    openFile,
    closeTab,
    updateContent,
    saveFile,
    createFile,
    deleteFile,
    runFile,
    loadGitData,
    initGit,
    commitGit,
    pushGit,
    loadValidationData,
    loadDockerfile,
    loadDockerSubsystem,
    loadJenkinsSubsystem,
    loadPipelineRuns,
    triggerUnifiedPipeline,
    loadDeployments,
    refreshDashboard,
    checkServicesStatus,
  }
})
