(() => {
  'use strict';

  const config = window.MIRROLLA_CONFIG || {};
  const apiBase = String(config.apiBase || '').replace(/\/$/, '');
  const workspaceId = config.workspaceId || 'default';
  const maxParallelUploads = Number(config.maxParallelUploads || 3);
  const maxUploadBytes = Number(config.maxUploadBytes || 200 * 1024 * 1024);
  const pollIntervalMs = Number(config.pollIntervalMs || 1500);
  const allowedExtensions = new Set(['csv', 'xlsx', 'json']);
  const terminalStatuses = new Set(['ready', 'invalid', 'deleted']);

  const state = {
    initialized: false,
    loading: false,
    datasets: [],
    versionsById: new Map(),
    draftSelectedVersionIds: loadSelectedIds(),
    uploadQueue: [],
    activeUploads: 0,
    pollers: new Map(),
    listeners: new Set()
  };

  const endpoints = {
    listDatasets: [
      `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/datasets`,
      `/api/v1/datasets?workspace_id=${encodeURIComponent(workspaceId)}`
    ],
    upload: [
      `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/datasets`,
      `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/datasets/upload`,
      '/api/v1/datasets/upload'
    ],
    getVersion: id => [`/api/v1/dataset-versions/${encodeURIComponent(id)}`],
    getProfile: id => [`/api/v1/dataset-versions/${encodeURIComponent(id)}/profile`],
    deleteVersion: id => [`/api/v1/dataset-versions/${encodeURIComponent(id)}`]
  };

  let refs = null;

  function authHeaders() {
    const key = window.MIRROLLA_API_KEY || localStorage.getItem('mirrolla_api_key');
    return key ? { 'X-API-Key': key } : {};
  }

  async function requestCandidates(candidates, options = {}) {
    let lastError = null;
    for (const path of candidates) {
      const response = await fetch(`${apiBase}${path}`, {
        ...options,
        headers: { ...authHeaders(), ...(options.headers || {}) }
      });
      if ((response.status === 404 || response.status === 405) && candidates.length > 1) {
        lastError = new Error(`Endpoint unavailable: ${path}`);
        continue;
      }
      if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try {
          const payload = await response.json();
          detail = payload.detail || payload.message || detail;
        } catch (_) {}
        const error = new Error(detail);
        error.status = response.status;
        throw error;
      }
      if (response.status === 204) return null;
      return response.json();
    }
    throw lastError || new Error('Dataset API endpoint is unavailable');
  }

  function loadSelectedIds() {
    try {
      const value = JSON.parse(localStorage.getItem('mirrolla_selected_dataset_versions') || '[]');
      return Array.isArray(value) ? [...new Set(value.filter(item => typeof item === 'string'))] : [];
    } catch (_) {
      return [];
    }
  }

  function persistSelection() {
    localStorage.setItem('mirrolla_selected_dataset_versions', JSON.stringify(state.draftSelectedVersionIds));
  }

  function notify() {
    const snapshot = getSnapshot();
    state.listeners.forEach(listener => listener(snapshot));
    window.dispatchEvent(new CustomEvent('mirrolla:datasets-changed', { detail: snapshot }));
  }

  function getSnapshot() {
    return {
      initialized: state.initialized,
      loading: state.loading,
      datasets: state.datasets,
      selectedVersions: getSelectedVersions(),
      uploads: state.uploadQueue.slice()
    };
  }

  function subscribe(listener) {
    state.listeners.add(listener);
    listener(getSnapshot());
    return () => state.listeners.delete(listener);
  }

  function extensionOf(name) {
    const parts = String(name || '').toLowerCase().split('.');
    return parts.length > 1 ? parts.pop() : '';
  }

  function readableBytes(bytes) {
    const value = Number(bytes || 0);
    if (!Number.isFinite(value) || value <= 0) return '0 Б';
    const units = ['Б', 'КБ', 'МБ', 'ГБ'];
    const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
    return `${(value / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
  }

  function normalizeVersion(raw, dataset) {
    if (!raw) return null;
    const version = raw.version || raw.dataset_version || raw;
    return {
      ...version,
      id: String(version.id || version.version_id || ''),
      dataset_id: String(version.dataset_id || dataset?.id || ''),
      original_filename: version.original_filename || version.filename || dataset?.display_name || 'Файл',
      format: String(version.format || extensionOf(version.original_filename || '') || '').toLowerCase(),
      status: String(version.status || 'uploaded').toLowerCase(),
      size_bytes: Number(version.size_bytes || version.size || 0),
      issues: Array.isArray(version.issues) ? version.issues : []
    };
  }

  function normalizeDatasets(payload) {
    const source = Array.isArray(payload) ? payload : payload?.datasets || payload?.items || [];
    return source.map(raw => {
      const dataset = raw.dataset || raw;
      const versionsSource = raw.versions || dataset.versions || (raw.latest_version ? [raw.latest_version] : []);
      const normalized = {
        ...dataset,
        id: String(dataset.id || dataset.dataset_id || ''),
        display_name: dataset.display_name || dataset.name || 'Без названия',
        versions: versionsSource.map(item => normalizeVersion(item, dataset)).filter(item => item?.id)
      };
      return normalized;
    }).filter(dataset => dataset.id);
  }

  function rebuildVersionIndex() {
    state.versionsById = new Map();
    state.datasets.forEach(dataset => dataset.versions.forEach(version => state.versionsById.set(version.id, { dataset, version })));
    state.draftSelectedVersionIds = state.draftSelectedVersionIds.filter(id => state.versionsById.get(id)?.version.status === 'ready');
    persistSelection();
  }

  async function refresh() {
    if (state.loading) return;
    state.loading = true;
    notify();
    try {
      const payload = await requestCandidates(endpoints.listDatasets);
      state.datasets = normalizeDatasets(payload);
      rebuildVersionIndex();
      state.initialized = true;
      render();
      startPollsForPendingVersions();
    } catch (error) {
      toast(`Не удалось загрузить список файлов: ${safeMessage(error)}`, 'error');
    } finally {
      state.loading = false;
      notify();
    }
  }

  function validateFiles(fileList) {
    const accepted = [];
    const rejected = [];
    for (const file of Array.from(fileList || [])) {
      const ext = extensionOf(file.name);
      if (!allowedExtensions.has(ext)) {
        rejected.push(`${file.name}: поддерживаются CSV, XLSX и JSON`);
      } else if (file.size <= 0) {
        rejected.push(`${file.name}: файл пустой`);
      } else if (file.size > maxUploadBytes) {
        rejected.push(`${file.name}: превышен лимит ${readableBytes(maxUploadBytes)}`);
      } else {
        accepted.push(file);
      }
    }
    rejected.forEach(message => toast(message, 'error'));
    return accepted;
  }

  function queueFiles(fileList, options = {}) {
    const files = validateFiles(fileList);
    if (options.datasetId && files.length > 1) {
      toast('Для новой версии выберите один файл.', 'error');
      return [];
    }
    const items = files.map(file => ({
      localId: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`,
      file,
      datasetId: options.datasetId || null,
      status: 'queued',
      progress: 0,
      versionId: null,
      error: null,
      xhr: null
    }));
    state.uploadQueue.push(...items);
    renderUploads();
    notify();
    pumpQueue();
    return items;
  }

  function pumpQueue() {
    while (state.activeUploads < maxParallelUploads) {
      const item = state.uploadQueue.find(candidate => candidate.status === 'queued');
      if (!item) break;
      uploadItem(item);
    }
  }

  function uploadItem(item) {
    item.status = 'uploading';
    state.activeUploads += 1;
    renderUploads();
    notify();

    const form = new FormData();
    form.append('file', item.file, item.file.name);
    form.append('workspace_id', workspaceId);
    form.append('display_name', item.file.name.replace(/\.[^.]+$/, ''));
    if (item.datasetId) form.append('dataset_id', item.datasetId);

    uploadWithCandidates(endpoints.upload, form, progress => {
      item.progress = progress;
      renderUploads();
    }, item).then(payload => {
      const version = normalizeVersion(payload?.version || payload?.dataset_version || payload, payload?.dataset);
      if (!version?.id) throw new Error('API не вернул идентификатор версии');
      item.versionId = version.id;
      mergeVersion(version);
      item.status = version.status === 'ready' ? 'ready' : 'profiling';
      item.progress = 100;
      if (version.status === 'ready') selectVersion(version.id, true);
      return monitorVersion(version.id, item);
    }).catch(error => {
      if (item.status !== 'canceled') {
        item.status = 'error';
        item.error = safeMessage(error);
        toast(`${item.file.name}: ${item.error}`, 'error');
      }
    }).finally(() => {
      state.activeUploads -= 1;
      item.xhr = null;
      renderUploads();
      notify();
      pumpQueue();
    });
  }

  async function uploadWithCandidates(candidates, form, onProgress, uploadItemRef) {
    let lastError = null;
    for (const path of candidates) {
      try {
        return await xhrUpload(`${apiBase}${path}`, form, onProgress, uploadItemRef);
      } catch (error) {
        if (error.status === 404 || error.status === 405) {
          lastError = error;
          continue;
        }
        throw error;
      }
    }
    throw lastError || new Error('Upload endpoint is unavailable');
  }

  function xhrUpload(url, form, onProgress, uploadItemRef) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', url);
      Object.entries(authHeaders()).forEach(([name, value]) => xhr.setRequestHeader(name, value));
      if (uploadItemRef) uploadItemRef.xhr = xhr;

      xhr.upload.addEventListener('progress', event => {
        if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
      });
      xhr.addEventListener('load', () => {
        let payload = null;
        try { payload = xhr.responseText ? JSON.parse(xhr.responseText) : null; } catch (_) {}
        if (xhr.status >= 200 && xhr.status < 300) resolve(payload);
        else {
          const error = new Error(payload?.detail || payload?.message || `HTTP ${xhr.status}`);
          error.status = xhr.status;
          reject(error);
        }
      });
      xhr.addEventListener('error', () => reject(new Error('Сетевая ошибка при загрузке')));
      xhr.addEventListener('abort', () => reject(new Error('Загрузка отменена')));
      xhr.send(form);
    });
  }

  async function monitorVersion(versionId, uploadItemRef = null) {
    if (state.pollers.has(versionId)) return state.pollers.get(versionId);
    const task = (async () => {
      let consecutiveErrors = 0;
      while (true) {
        try {
          const payload = await requestCandidates(endpoints.getVersion(versionId));
          const version = normalizeVersion(payload?.version || payload);
          consecutiveErrors = 0;
          mergeVersion(version);
          if (uploadItemRef) {
            uploadItemRef.status = version.status;
            renderUploads();
          }
          if (version.status === 'ready') {
            selectVersion(version.id, true);
            toast(`${version.original_filename}: готов к анализу`);
          }
          if (terminalStatuses.has(version.status)) break;
        } catch (error) {
          consecutiveErrors += 1;
          if (consecutiveErrors >= 5) {
            if (uploadItemRef) {
              uploadItemRef.status = 'error';
              uploadItemRef.error = 'Не удалось получить статус обработки';
            }
            toast('Не удалось получить статус обработки файла. Обновите список данных.', 'error');
            break;
          }
        }
        await sleep(Math.min(pollIntervalMs * Math.max(1, consecutiveErrors), 5000));
      }
    })().finally(() => {
      state.pollers.delete(versionId);
      refresh().catch(() => {});
    });
    state.pollers.set(versionId, task);
    return task;
  }

  function mergeVersion(incoming) {
    if (!incoming?.id) return;
    const existing = state.versionsById.get(incoming.id);
    if (existing) {
      Object.assign(existing.version, incoming);
    } else {
      let dataset = state.datasets.find(item => item.id === incoming.dataset_id);
      if (!dataset) {
        dataset = {
          id: incoming.dataset_id || `upload-${incoming.id}`,
          display_name: incoming.original_filename || 'Загруженный файл',
          versions: []
        };
        state.datasets.unshift(dataset);
      }
      dataset.versions.unshift(incoming);
      rebuildVersionIndex();
    }
    render();
    notify();
  }

  function startPollsForPendingVersions() {
    state.versionsById.forEach(({ version }) => {
      if (['uploaded', 'profiling'].includes(version.status)) monitorVersion(version.id);
    });
  }

  function cancelUpload(localId) {
    const item = state.uploadQueue.find(candidate => candidate.localId === localId);
    if (!item || !['queued', 'uploading'].includes(item.status)) return;
    if (item.status === 'uploading' && item.xhr) item.xhr.abort();
    item.status = 'canceled';
    renderUploads();
    notify();
  }

  function selectVersion(versionId, selected = true) {
    const entry = state.versionsById.get(versionId);
    if (!entry && selected) return false;
    if (selected && entry.version.status !== 'ready') return false;
    const set = new Set(state.draftSelectedVersionIds);
    selected ? set.add(versionId) : set.delete(versionId);
    state.draftSelectedVersionIds = [...set];
    persistSelection();
    render();
    notify();
    return true;
  }

  function getSelectedVersions() {
    return state.draftSelectedVersionIds.map(id => state.versionsById.get(id)).filter(entry => entry?.version.status === 'ready');
  }

  function getReadyVersionIds() {
    return getSelectedVersions().map(entry => entry.version.id);
  }

  async function deleteVersion(versionId) {
    if (!confirm('Скрыть эту версию файла из рабочего пространства?')) return;
    try {
      await requestCandidates(endpoints.deleteVersion(versionId), { method: 'DELETE' });
      selectVersion(versionId, false);
      await refresh();
    } catch (error) {
      toast(`Не удалось удалить файл: ${safeMessage(error)}`, 'error');
    }
  }

  function openDrawer() {
    document.body.classList.add('drawer-open');
    refs?.dataDrawer?.setAttribute('aria-hidden', 'false');
    refresh().catch(() => {});
  }

  function closeDrawer() {
    document.body.classList.remove('drawer-open');
    refs?.dataDrawer?.setAttribute('aria-hidden', 'true');
  }

  function bindDropzone(element, input, options = {}) {
    if (!element || !input) return;
    const openPicker = event => {
      if (event?.target?.closest('button')) return;
      input.click();
    };
    element.addEventListener('click', openPicker);
    element.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        input.click();
      }
    });
    ['dragenter', 'dragover'].forEach(name => element.addEventListener(name, event => {
      event.preventDefault();
      element.classList.add('dragover');
    }));
    ['dragleave', 'drop'].forEach(name => element.addEventListener(name, event => {
      event.preventDefault();
      element.classList.remove('dragover');
    }));
    element.addEventListener('drop', event => queueFiles(event.dataTransfer.files, options));
    input.addEventListener('change', () => {
      queueFiles(input.files, options);
      input.value = '';
    });
  }

  function init(domRefs) {
    refs = domRefs;
    bindDropzone(refs.inlineDropzone, refs.inlineFileInput);
    bindDropzone(refs.drawerDropzone, refs.drawerFileInput);
    refs.composerFileInput?.addEventListener('change', () => {
      queueFiles(refs.composerFileInput.files);
      refs.composerFileInput.value = '';
    });
    refs.datasetList?.addEventListener('click', event => {
      const row = event.target.closest('[data-version-id]');
      const action = event.target.closest('[data-action]')?.dataset.action;
      if (!row) return;
      const versionId = row.dataset.versionId;
      if (action === 'delete-version') {
        event.stopPropagation();
        deleteVersion(versionId);
      } else if (row.classList.contains('selectable')) {
        selectVersion(versionId, !state.draftSelectedVersionIds.includes(versionId));
      }
    });
    refs.uploadQueue?.addEventListener('click', event => {
      const button = event.target.closest('[data-cancel-upload]');
      if (button) cancelUpload(button.dataset.cancelUpload);
    });
    refresh().catch(() => {});
    render();
  }

  function render() {
    renderDatasets();
    renderUploads();
    renderAttachments();
    if (refs?.datasetCount) refs.datasetCount.textContent = String(state.versionsById.size);
    if (refs?.selectedCount) refs.selectedCount.textContent = String(getSelectedVersions().length);
  }

  function renderDatasets() {
    if (!refs?.datasetList) return;
    if (state.loading && !state.initialized) {
      refs.datasetList.innerHTML = '<div class="empty-state">Загрузка…</div>';
      return;
    }
    if (!state.datasets.length) {
      refs.datasetList.innerHTML = '<div class="empty-state">Загруженных файлов пока нет</div>';
      return;
    }
    refs.datasetList.innerHTML = state.datasets.map(dataset => `
      <article class="dataset-card">
        <div class="dataset-card-head">
          <div class="file-icon">DATA</div>
          <div class="dataset-card-name" title="${escapeHtml(dataset.display_name)}">${escapeHtml(dataset.display_name)}</div>
        </div>
        <div class="dataset-card-versions">
          ${dataset.versions.map(version => renderVersion(version)).join('') || '<div class="empty-state">Нет активных версий</div>'}
        </div>
      </article>
    `).join('');
  }

  function renderVersion(version) {
    const selected = state.draftSelectedVersionIds.includes(version.id);
    const selectable = version.status === 'ready';
    const statusText = ({ ready: 'Готов', profiling: 'Обработка', uploaded: 'В очереди', invalid: 'Ошибка', deleted: 'Удалён' })[version.status] || version.status;
    return `
      <div class="version-row ${selectable ? 'selectable' : ''} ${selected ? 'selected' : ''}" data-version-id="${escapeHtml(version.id)}">
        <span class="version-check">${selected ? '✓' : ''}</span>
        <div class="file-info">
          <span class="file-name" title="${escapeHtml(version.original_filename)}">${escapeHtml(version.original_filename)}</span>
          <span class="file-meta">${escapeHtml(version.format.toUpperCase())} · ${readableBytes(version.size_bytes)}</span>
        </div>
        <span class="version-status ${escapeHtml(version.status)}">${escapeHtml(statusText)}</span>
        ${version.status !== 'deleted' ? '<button class="icon-button" type="button" data-action="delete-version" aria-label="Удалить"><svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13M10 11v5m4-5v5"/></svg></button>' : ''}
      </div>
    `;
  }

  function renderUploads() {
    const activeItems = state.uploadQueue.filter(item => !['canceled'].includes(item.status)).slice(-8).reverse();
    const html = activeItems.map(item => {
      const statusText = ({ queued: 'В очереди', uploading: `Загрузка ${item.progress}%`, profiling: 'Профилирование', ready: 'Готов', invalid: 'Ошибка обработки', error: item.error || 'Ошибка' })[item.status] || item.status;
      return `
        <div class="upload-row">
          <div class="upload-row-main">
            <div class="file-icon">${escapeHtml(extensionOf(item.file.name).toUpperCase())}</div>
            <div class="file-info">
              <span class="file-name">${escapeHtml(item.file.name)}</span>
              <span class="file-meta">${escapeHtml(statusText)}</span>
            </div>
            ${['queued', 'uploading'].includes(item.status) ? `<button class="text-button" type="button" data-cancel-upload="${escapeHtml(item.localId)}">Отмена</button>` : ''}
          </div>
          ${item.status === 'uploading' ? `<div class="progress-track"><div class="progress-bar" style="width:${Math.max(0, Math.min(100, item.progress))}%"></div></div>` : ''}
        </div>
      `;
    }).join('');
    if (refs?.uploadQueue) refs.uploadQueue.innerHTML = html;
    if (refs?.inlineUploadSummary) refs.inlineUploadSummary.innerHTML = html;
  }

  function renderAttachments() {
    if (!refs?.attachmentStrip) return;
    const entries = getSelectedVersions();
    refs.attachmentStrip.hidden = entries.length === 0;
    refs.attachmentStrip.innerHTML = entries.map(({ version }) => `
      <span class="file-chip">
        <span class="file-chip-name" title="${escapeHtml(version.original_filename)}">${escapeHtml(version.original_filename)}</span>
        <button type="button" data-remove-version="${escapeHtml(version.id)}" aria-label="Убрать файл">
          <svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>
        </button>
      </span>
    `).join('');
    refs.attachmentStrip.querySelectorAll('[data-remove-version]').forEach(button => button.addEventListener('click', () => selectVersion(button.dataset.removeVersion, false)));
  }

  function toast(message, type = 'info') {
    const region = refs?.toastRegion || document.getElementById('toastRegion');
    if (!region) return;
    const element = document.createElement('div');
    element.className = `toast ${type}`;
    element.textContent = message;
    region.appendChild(element);
    setTimeout(() => element.remove(), 4200);
  }

  function safeMessage(error) {
    const value = String(error?.message || 'Неизвестная ошибка');
    return value.length > 240 ? `${value.slice(0, 237)}…` : value;
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char]);
  }

  function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

  const DatasetWorkspace = {
    init,
    refresh,
    subscribe,
    queueFiles,
    selectVersion,
    getSelectedVersions,
    getReadyVersionIds,
    openDrawer,
    closeDrawer,
    toast,
    escapeHtml,
    readableBytes
  };
  window.DatasetWorkspace = DatasetWorkspace;
})();
