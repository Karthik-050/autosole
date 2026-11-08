import axios from 'axios'

const api = axios.create({ baseURL: '/' })

// Backward-compatible original APIs
export const workspaceApi = {
  list: () => api.get('/workspaces').then(r => r.data.workspaces),
  create: () => api.post('/workspaces').then(r => r.data),
  delete: (id) => api.delete(`/workspaces/${id}`),
}

export const fileApi = {
  list: (wsId) => api.get(`/workspaces/${wsId}/files`).then(r => r.data.files),
  create: (wsId, name) => api.post(`/workspaces/${wsId}/files`, null, { params: { filename: name } }),
  read: (wsId, name) => api.get(`/workspaces/${wsId}/read`, { params: { filename: name } }).then(r => r.data.content),
  write: (wsId, name, content) => api.post(`/workspaces/${wsId}/write`, null, { params: { filename: name, content } }),
  delete: (wsId, name) => api.delete(`/workspaces/${wsId}/files`, { params: { filename: name } }),
}

export const runApi = {
  file: (wsId, name) => api.post(`/workspaces/${wsId}/run`, null, { params: { filename: name } }).then(r => r.data),
}

// ----------------- MODULAR UNIFIED APIS -----------------

export const dashboardApi = {
  getStats: (projectId) => api.get('/api/dashboard/stats', { params: { project_id: projectId } }).then(r => r.data),
}

export const projectApi = {
  list: () => api.get('/api/projects').then(r => r.data.projects),
  create: (name, template) => api.post('/api/projects', { name, template }).then(r => r.data),
  get: (id) => api.get(`/api/projects/${id}`).then(r => r.data.project),
  delete: (id) => api.delete(`/api/projects/${id}`),
  importAutomatorTest: () => api.post('/api/projects/import-automator-test').then(r => r.data),
}

export const gitApi = {
  getStatus: (projectId) => api.get(`/api/git/${projectId}/status`).then(r => r.data.status),
  init: (projectId) => api.post(`/api/git/${projectId}/init`).then(r => r.data),
  connectRepository: (url, branch, accessToken) => api.post('/api/git/connect', { url, branch, access_token: accessToken || undefined }).then(r => r.data),
  commit: (projectId, message, author) => api.post(`/api/git/${projectId}/commit`, { message, author }).then(r => r.data),
  push: (projectId, accessToken) => api.post(`/api/git/${projectId}/push`, { access_token: accessToken || undefined }).then(r => r.data),
  getHistory: (projectId, limit = 20) => api.get(`/api/git/${projectId}/history`, { params: { limit } }).then(r => r.data.history),
  getDiff: (projectId, file) => api.get(`/api/git/${projectId}/diff`, { params: { file_path: file } }).then(r => r.data.diff),
}

export const validationApi = {
  scan: (projectId) => api.get(`/api/validation/${projectId}/scan`).then(r => r.data.validation),
  validateFile: (projectId, filename, content) => api.post(`/api/validation/${projectId}/validate-file`, { filename, content }).then(r => r.data.validation),
}

export const dockerApi = {
  getStatus: () => api.get('/api/docker/status').then(r => r.data.status),
  getImages: () => api.get('/api/docker/images').then(r => r.data.images),
  getContainers: () => api.get('/api/docker/containers').then(r => r.data.containers),
  getDockerfile: (projectId) => api.get(`/api/docker/${projectId}/dockerfile`).then(r => r.data),
  saveDockerfile: (projectId, content, projectType) => api.post(`/api/docker/${projectId}/dockerfile`, { content, project_type: projectType }).then(r => r.data),
  buildImage: (projectId, tag) => api.post(`/api/docker/${projectId}/build`, { tag }).then(r => r.data),
  runContainer: (projectId, payload) => api.post(`/api/docker/${projectId}/run`, payload).then(r => r.data),
  stopContainer: (containerId) => api.post('/api/docker/container/stop', { container_id: containerId }).then(r => r.data),
  removeContainer: (containerId) => api.post('/api/docker/container/remove', { container_id: containerId }).then(r => r.data),
}

export const jenkinsApi = {
  getStatus: () => api.get('/api/jenkins/status').then(r => r.data.status),
  getJobs: () => api.get('/api/jenkins/jobs').then(r => r.data.jobs),
  createJob: (jobName, pipelineScript) => api.post('/api/jenkins/jobs/create', { job_name: jobName, pipeline_script: pipelineScript }).then(r => r.data),
  triggerJob: (jobName) => api.post(`/api/jenkins/jobs/${jobName}/trigger`).then(r => r.data),
  getLatestBuild: (jobName) => api.get(`/api/jenkins/jobs/${jobName}/builds/latest`).then(r => r.data.build),
  getConsoleLogs: (jobName, buildNumber) => api.get(`/api/jenkins/jobs/${jobName}/builds/${buildNumber}/console`).then(r => r.data.console),
}

export const pipelineApi = {
  getRuns: (projectId) => api.get('/api/pipeline/runs', { params: { project_id: projectId } }).then(r => r.data.runs),
  getRun: (runId) => api.get(`/api/pipeline/runs/${runId}`).then(r => r.data.run),
  trigger: (payload) => api.post('/api/pipeline/trigger', payload).then(r => r.data),
}

export const deploymentApi = {
  list: () => api.get('/api/deployments').then(r => r.data.deployments),
  get: (id) => api.get(`/api/deployments/${id}`).then(r => r.data.deployment),
  checkHealth: (id) => api.post(`/api/deployments/${id}/health`).then(r => r.data),
  stop: (id) => api.post(`/api/deployments/${id}/stop`).then(r => r.data),
}

export const settingsApi = {
  get: () => api.get('/api/settings').then(r => r.data.settings),
  update: (settings) => api.post('/api/settings', settings).then(r => r.data),
  testDocker: () => api.post('/api/settings/test-docker').then(r => r.data.status),
  testJenkins: () => api.post('/api/settings/test-jenkins').then(r => r.data.status),
}
