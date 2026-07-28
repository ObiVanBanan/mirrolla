(function (global) {
  'use strict';

  const DEFAULT_WORKSPACE_ID = 'default';
  const MAX_PARALLEL_UPLOADS = 3;
  const MAX_CONSECUTIVE_POLL_ERRORS = 5;
  const DEFAULT_POLL_INTERVAL_MS = 2000;
  const STORAGE_KEYS = {
    draftSelectedVersionIds: 'mirrolla.dataset.draftSelectedVersionIds',
    workspaceId: 'mirrolla.dataset.workspaceId'
  };

  function escapeHtml(value) {
    if (value == null) return '';
    return String(value).replace(/[&<>"']/g, character => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    })[character]);
  }

  function escapeAttribute(value) {
    return escapeHtml(value).replace(/`/g, '&#96;');
  }

  function pluralize(number, one, few, many) {
    const mod10 = number % 10;
    const mod100 = number % 100;
    if (mod10 === 1 && mod100 !== 11) return one;
    if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return few;
    return many;
  }

  function formatBytes(value) {
    const bytes = Number(value || 0);
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function stemFilename(name) {
    return String(name || 'dataset').replace(/\.[^.]+$/, '') || 'dataset';
  }

  function normalizeVersionIdList(values) {
    if (!Array.isArray(values)) return [];
    const seen = new Set();
    const ids = [];
    values.forEach(value => {
      if (typeof value !== 'string') return;
      if (seen.has(value)) return;
      seen.add(value);
      ids.push(value);
    });
    return ids;
  }

  function loadStoredDraftSelection(storage) {
    try {
      const raw = storage?.getItem(STORAGE_KEYS.draftSelectedVersionIds);
      return normalizeVersionIdList(raw ? JSON.parse(raw) : []);
    } catch (_) {
      return [];
    }
  }

  function loadStoredWorkspaceId(storage) {
    try {
      return storage?.getItem(STORAGE_KEYS.workspaceId) || DEFAULT_WORKSPACE_ID;
    } catch (_) {
      return DEFAULT_WORKSPACE_ID;
    }
  }

  function saveStoredDraftSelection(storage, ids) {
    try {
      storage?.setItem(STORAGE_KEYS.draftSelectedVersionIds, JSON.stringify(ids));
    } catch (_) {
      // Ignore localStorage quota failures.
    }
  }

  function saveStoredWorkspaceId(storage, workspaceId) {
    try {
      storage?.setItem(STORAGE_KEYS.workspaceId, workspaceId || DEFAULT_WORKSPACE_ID);
    } catch (_) {
      // Ignore localStorage quota failures.
    }
  }

  function createInitialDatasetWorkspaceState(options = {}) {
    return {
      workspaceId: options.workspaceId || DEFAULT_WORKSPACE_ID,
      initialized: false,
      initializationError: null,
      datasets: Array.isArray(options.datasets) ? options.datasets : [],
      draftSelectedVersionIds: normalizeVersionIdList(options.draftSelectedVersionIds),
      viewedAnalysisVersionIds: normalizeVersionIdList(options.viewedAnalysisVersionIds),
      selectionMode: options.selectionMode === 'analysis' ? 'analysis' : 'draft',
      uploads: Array.isArray(options.uploads) ? options.uploads : [],
      profileCache: options.profileCache instanceof Map ? options.profileCache : new Map(),
      drawerOpen: Boolean(options.drawerOpen),
      filePickerContext: null,
      bannerMessage: '',
      retryableVersionIds: new Set()
    };
  }

  function buildVersionIndex(datasets) {
    const index = new Map();
    (datasets || []).forEach(dataset => {
      (dataset.versions || []).forEach(version => {
        index.set(version.id, {dataset, version});
      });
    });
    return index;
  }

  function getVersionEntriesByIds(datasets, ids) {
    const index = buildVersionIndex(datasets);
    return normalizeVersionIdList(ids)
      .map(id => index.get(id))
      .filter(Boolean);
  }

  function getDraftReadyVersionIds(state) {
    if (!state.initialized || state.initializationError) {
      return [];
    }

    return getVersionEntriesByIds(state.datasets, state.draftSelectedVersionIds)
      .filter(entry => entry.version.status === 'ready')
      .map(entry => entry.version.id);
  }

  function shouldShowCancel(upload) {
    return upload && (upload.status === 'queued' || upload.status === 'uploading');
  }

  function createUploadItems(files, context = null, createId = defaultCreateUploadId) {
    const safeFiles = Array.from(files || []);
    if (!safeFiles.length) {
      return {items: [], error: ''};
    }

    if (context?.mode === 'add-version' && safeFiles.length !== 1) {
      return {items: [], error: 'Для новой версии выберите один файл.'};
    }

    return {
      items: safeFiles.map(file => ({
        id: createId(),
        file,
        datasetId: context?.datasetId || null,
        displayName: stemFilename(file.name),
        progress: 0,
        status: 'queued',
        message: 'Ожидает свободный слот',
        abortController: null,
        versionId: null,
        retryable: false,
        canceled: false
      })),
      error: ''
    };
  }

  function defaultCreateUploadId() {
    return `upload_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  }

  function sanitizeUploadError(status, detail) {
    if (status === 413) {
      return 'Файл превышает допустимый размер загрузки.';
    }
    if (status === 415) {
      return 'Поддерживаются только файлы .csv, .json и .xlsx.';
    }
    if (status === 400 && typeof detail === 'string' && detail.toLowerCase().includes('empty')) {
      return 'Файл пустой. Нужны данные хотя бы с одной строкой.';
    }
    if (status === 404) {
      return 'Workspace или версия набора не найдены.';
    }
    if (typeof detail === 'string' && detail) {
      return detail;
    }
    return `Не удалось загрузить файл (${status})`;
  }

  function describeVersionStatus(status) {
    switch (status) {
      case 'ready':
        return 'Файл готов к анализу';
      case 'invalid':
        return 'Файл не прошёл проверку';
      case 'deleted':
        return 'Версия удалена';
      default:
        return 'Профилирование выполняется';
    }
  }

  function describeDatasetIssue(issue) {
    const code = String(issue?.code || '').toLowerCase();
    switch (code) {
      case 'dataset_has_no_rows':
        return 'В файле нет строк данных';
      case 'dataset_has_no_object_rows':
        return 'JSON не содержит объектных записей';
      case 'dataset_has_no_sheets':
        return 'В XLSX нет заполненных листов';
      case 'profile_runtime_error':
        return 'Профилирование завершилось ошибкой';
      default:
        return issue?.message || issue?.code || 'Ошибка профиля';
    }
  }

  function formatVersionStatusLabel(status) {
    switch (status) {
      case 'receiving':
      case 'uploaded':
      case 'profiling':
      case 'ready':
      case 'invalid':
      case 'deleted':
        return status;
      default:
        return status || 'unknown';
    }
  }

  function renderUploadMarkup(upload) {
    const actions = [];
    if (shouldShowCancel(upload)) {
      actions.push(`
        <button class="dataset-btn" type="button" data-action="cancel-upload" data-upload-id="${escapeAttribute(upload.id)}">
          Отменить
        </button>
      `);
    }
    if (upload.retryable && upload.versionId) {
      actions.push(`
        <button class="dataset-btn" type="button" data-action="retry-version-status" data-version-id="${escapeAttribute(upload.versionId)}" data-upload-id="${escapeAttribute(upload.id)}">
          Повторить проверку
        </button>
      `);
    }

    return `
      <div class="upload-card">
        <div class="upload-head">
          <div>
            <div class="upload-name">${escapeHtml(upload.file?.name || 'Файл')}</div>
            <div class="upload-meta">${escapeHtml(upload.displayName || stemFilename(upload.file?.name || 'dataset'))} · ${escapeHtml(formatBytes(upload.file?.size || 0))}</div>
          </div>
          <div class="dataset-card-actions">${actions.join('')}</div>
        </div>
        <div class="upload-progress">
          <div class="upload-progress-bar" style="width:${Number(upload.progress || 0)}%"></div>
        </div>
        <div class="upload-status ${escapeAttribute(upload.status || 'queued')}">${escapeHtml(upload.message || '')}</div>
      </div>
    `;
  }

  function renderUploadList(state) {
    if (!state.uploads.length) {
      return '<div class="dataset-muted">Загрузки появятся здесь после выбора файлов.</div>';
    }
    return state.uploads.map(renderUploadMarkup).join('');
  }

  function renderVersionProfile(profilePayload, version) {
    if (!profilePayload) {
      if (version.status === 'profiling') {
        return '<div class="dataset-muted" style="margin-top:10px;">Профиль строится. Версия станет доступной для выбора после статуса ready.</div>';
      }
      return '';
    }

    const sheets = Array.isArray(profilePayload.profile?.sheets) ? profilePayload.profile.sheets : [];
    const warnings = Array.isArray(profilePayload.profile?.warnings) ? profilePayload.profile.warnings : [];
    const allWarnings = warnings.concat(
      sheets.flatMap(sheet => Array.isArray(sheet.warnings) ? sheet.warnings : [])
    );

    return `
      <div style="margin-top:12px;">
        ${sheets.length ? `
          <div class="profile-sheet-list">
            ${sheets.map(sheet => `
              <div class="version-sheet">
                <strong>${escapeHtml(sheet.name || '__root__')}</strong>
                <div class="version-sheet-meta">
                  ${escapeHtml(`${sheet.row_count || 0} ${pluralize(sheet.row_count || 0, 'строка', 'строки', 'строк')}`)}
                  · ${escapeHtml(`${(sheet.columns || []).length} ${pluralize((sheet.columns || []).length, 'колонка', 'колонки', 'колонок')}`)}
                  ${sheet.sampled ? ' · sampled' : ''}
                </div>
                ${(sheet.columns || []).length ? `
                  <div class="version-chip-row" style="margin-top:8px;">
                    ${(sheet.columns || []).slice(0, 6).map(column => `<span class="version-chip">${escapeHtml(column.name)}</span>`).join('')}
                  </div>
                ` : ''}
              </div>
            `).join('')}
          </div>
        ` : ''}
        ${allWarnings.length ? `
          <div class="version-issues" style="margin-top:10px;">
            ${allWarnings.map(warning => `<span class="issue-chip warning">${escapeHtml(warning)}</span>`).join('')}
          </div>
        ` : ''}
      </div>
    `;
  }

  function renderDatasetVersionMarkup(dataset, version, options) {
    const profile = options.profileCache.get(version.id);
    const selectedIds = options.selectionMode === 'analysis'
      ? options.viewedAnalysisVersionIds
      : options.draftSelectedVersionIds;
    const checked = selectedIds.includes(version.id);
    const canSelect = options.selectionMode === 'draft' && version.status === 'ready';
    const issues = Array.isArray(profile?.issues) ? profile.issues : [];
    const retryButton = version.status === 'profiling' && options.retryableVersionIds.has(version.id)
      ? `
        <button class="dataset-btn" type="button" data-action="retry-version-status" data-version-id="${escapeAttribute(version.id)}">
          Повторить проверку
        </button>
      `
      : '';

    return `
      <div class="version-row">
        <div class="version-row-head">
          <label class="version-select">
            <input
              type="checkbox"
              data-action="toggle-version-selection"
              data-version-id="${escapeAttribute(version.id)}"
              ${checked ? 'checked' : ''}
              ${canSelect ? '' : 'disabled'}
            >
            <div class="version-copy">
              <div class="version-title">${escapeHtml(version.original_filename || dataset.display_name || 'Файл')}</div>
              <div class="version-meta">${escapeHtml((version.format || 'unknown').toUpperCase())} · ${escapeHtml(formatBytes(version.size_bytes || 0))} · ${escapeHtml(formatVersionStatusLabel(version.status))}</div>
            </div>
          </label>
          <div class="version-actions">
            <span class="dataset-status ${escapeAttribute(version.status)}">${escapeHtml(formatVersionStatusLabel(version.status))}</span>
            ${retryButton}
            <button class="dataset-btn danger" type="button" data-action="delete-version" data-version-id="${escapeAttribute(version.id)}">Удалить</button>
          </div>
        </div>
        ${renderVersionProfile(profile, version)}
        ${issues.length ? `
          <div class="version-issues" style="margin-top:10px;">
            ${issues.map(issue => `<span class="issue-chip ${escapeAttribute(issue.severity || 'error')}" title="${escapeAttribute(issue.message || '')}">${escapeHtml(describeDatasetIssue(issue))}</span>`).join('')}
          </div>
        ` : ''}
      </div>
    `;
  }

  function renderDatasetCardMarkup(dataset, options) {
    const versions = Array.isArray(dataset.versions) ? dataset.versions : [];
    return `
      <article class="dataset-card">
        <div class="dataset-card-head">
          <div>
            <div class="dataset-card-title">${escapeHtml(dataset.display_name || 'Dataset')}</div>
            <div class="dataset-card-meta">${versions.length} ${pluralize(versions.length, 'версия', 'версии', 'версий')} · ${escapeHtml(dataset.source_type || 'upload')}</div>
          </div>
          <div class="dataset-card-actions">
            <button class="dataset-btn" type="button" data-action="add-version" data-dataset-id="${escapeAttribute(dataset.id)}">
              Новая версия
            </button>
          </div>
        </div>
        <div class="dataset-card-body">
          ${versions.map(version => renderDatasetVersionMarkup(dataset, version, options)).join('')}
        </div>
      </article>
    `;
  }

  function renderDatasetListMarkup(state) {
    if (!state.datasets.length) {
      return `
        <div class="dataset-card">
          <div class="dataset-muted">
            В workspace пока нет загруженных файлов. Добавьте CSV, JSON или XLSX, затем выберите ready-версию для анализа.
          </div>
        </div>
      `;
    }

    const options = {
      draftSelectedVersionIds: state.draftSelectedVersionIds,
      viewedAnalysisVersionIds: state.viewedAnalysisVersionIds,
      selectionMode: state.selectionMode,
      profileCache: state.profileCache,
      retryableVersionIds: state.retryableVersionIds
    };
    return state.datasets.map(dataset => renderDatasetCardMarkup(dataset, options)).join('');
  }

  function renderComposerMarkup(state) {
    const note = `
      <div class="composer-empty-datasets">
        Файлы будут прикреплены к анализу. Использование загруженных данных при выполнении подключается отдельно.
      </div>
    `;

    if (!state.initialized && !state.initializationError) {
      return `${note}<div class="composer-empty-datasets">Workspace загружается. Анализ можно отправить и без файлов.</div>`;
    }

    if (state.initializationError) {
      return `
        ${note}
        <div class="composer-empty-datasets">
          Не удалось загрузить workspace. Анализ можно отправить без файлов.
          <button class="dataset-inline-link" type="button" data-action="retry-workspace">Повторить</button>
        </div>
      `;
    }

    const ids = state.selectionMode === 'analysis'
      ? state.viewedAnalysisVersionIds
      : state.draftSelectedVersionIds;
    const entries = getVersionEntriesByIds(state.datasets, ids)
      .filter(entry => entry.version.status === 'ready');

    if (!entries.length) {
      return `
        ${note}
        <div class="composer-empty-datasets">
          Файлы не выбраны.
          <button class="dataset-inline-link" type="button" data-action="open-drawer">Добавить данные</button>
        </div>
      `;
    }

    return `
      ${note}
      ${entries.map(entry => `
        <span class="composer-file-chip">
          ${escapeHtml(entry.dataset.display_name)} · ${escapeHtml(entry.version.original_filename)}
          ${state.selectionMode === 'draft'
            ? `<button type="button" aria-label="Убрать файл" data-action="remove-draft-selection" data-version-id="${escapeAttribute(entry.version.id)}">×</button>`
            : '<span class="dataset-muted">read-only</span>'}
        </span>
      `).join('')}
    `;
  }

  function upsertVersionInDatasets(datasets, versionUpdate) {
    if (!versionUpdate || !versionUpdate.dataset_id) {
      return datasets;
    }

    return (datasets || []).map(dataset => {
      if (dataset.id !== versionUpdate.dataset_id) {
        return dataset;
      }

      const versions = Array.isArray(dataset.versions) ? dataset.versions.slice() : [];
      const index = versions.findIndex(version => version.id === versionUpdate.id);
      if (index >= 0) {
        versions[index] = {...versions[index], ...versionUpdate};
      } else {
        versions.unshift(versionUpdate);
      }
      return {...dataset, versions};
    });
  }

  function createDatasetWorkspaceCore(options) {
    const state = createInitialDatasetWorkspaceState({
      workspaceId: loadStoredWorkspaceId(options.storage),
      draftSelectedVersionIds: loadStoredDraftSelection(options.storage)
    });
    const activeUploads = new Map();
    const versionPolls = new Map();
    const delayFn = options.delay || (ms => new Promise(resolve => setTimeout(resolve, ms)));

    function emit() {
      if (typeof options.onStateChange === 'function') {
        options.onStateChange(state);
      }
    }

    function persistDraftSelection() {
      saveStoredDraftSelection(options.storage, state.draftSelectedVersionIds);
    }

    function persistWorkspace() {
      saveStoredWorkspaceId(options.storage, state.workspaceId);
    }

    function pruneDraftSelection() {
      const readyIds = new Set(
        state.datasets.flatMap(dataset =>
          (dataset.versions || [])
            .filter(version => version.status === 'ready')
            .map(version => version.id)
        )
      );
      state.draftSelectedVersionIds = state.draftSelectedVersionIds.filter(id => readyIds.has(id));
      persistDraftSelection();
    }

    async function refreshWorkspace() {
      const payload = await options.api.listDatasets(state.workspaceId || DEFAULT_WORKSPACE_ID);
      state.datasets = Array.isArray(payload.datasets) ? payload.datasets : [];
      state.initialized = true;
      state.initializationError = null;
      pruneDraftSelection();
      emit();
      return state.datasets;
    }

    async function hydrateProfiles() {
      const pending = [];
      state.datasets.forEach(dataset => {
        (dataset.versions || []).forEach(version => {
          if (['ready', 'invalid'].includes(version.status) && !state.profileCache.has(version.id)) {
            pending.push(
              options.api.getDatasetProfile(version.id)
                .then(profile => {
                  state.profileCache.set(version.id, profile);
                })
                .catch(() => {})
            );
          }
        });
      });
      if (pending.length) {
        await Promise.all(pending);
        emit();
      }
    }

    async function initWorkspace() {
      try {
        const workspace = await options.api.getDefaultWorkspace();
        state.workspaceId = workspace.id || DEFAULT_WORKSPACE_ID;
        persistWorkspace();
        await refreshWorkspace();
        await hydrateProfiles();
      } catch (_) {
        state.initializationError = 'Не удалось загрузить workspace.';
        state.initialized = false;
        emit();
      }
    }

    function showDraftSelection() {
      state.selectionMode = 'draft';
      emit();
    }

    function showAnalysisSelection(versionIds) {
      state.selectionMode = 'analysis';
      state.viewedAnalysisVersionIds = normalizeVersionIdList(versionIds);
      emit();
    }

    function openDrawer() {
      state.drawerOpen = true;
      emit();
    }

    function closeDrawer() {
      state.drawerOpen = false;
      emit();
    }

    function setBannerMessage(message) {
      state.bannerMessage = message || '';
      emit();
    }

    function clearBannerMessage() {
      if (!state.bannerMessage) return;
      state.bannerMessage = '';
      emit();
    }

    function queueFiles(files, context = null) {
      const result = createUploadItems(files, context, options.createUploadId || defaultCreateUploadId);
      if (result.error) {
        state.bannerMessage = result.error;
        emit();
        return false;
      }

      state.bannerMessage = '';
      result.items.reverse().forEach(item => {
        state.uploads.unshift(item);
      });
      emit();
      pumpUploads();
      return true;
    }

    function pumpUploads() {
      while (activeUploads.size < MAX_PARALLEL_UPLOADS) {
        const nextUpload = state.uploads.find(item => item.status === 'queued');
        if (!nextUpload) break;
        startUpload(nextUpload);
      }
    }

    async function startUpload(upload) {
      if (!upload || upload.status !== 'queued') return;
      upload.status = 'uploading';
      upload.message = 'Загрузка файла';
      upload.abortController = new AbortController();
      activeUploads.set(upload.id, upload);
      emit();

      try {
        const response = await options.api.uploadDataset({
          workspaceId: state.workspaceId || DEFAULT_WORKSPACE_ID,
          file: upload.file,
          displayName: upload.displayName,
          datasetId: upload.datasetId,
          signal: upload.abortController.signal,
          onProgress(progress) {
            if (upload.canceled) return;
            upload.progress = progress;
            emit();
          }
        });

        if (upload.canceled) {
          return;
        }

        upload.progress = 100;
        upload.status = 'profiling';
        upload.message = 'Профилирование запущено';
        upload.versionId = response.version?.id || null;
        upload.retryable = false;
        emit();
        await refreshWorkspace();
        await hydrateProfiles();

        if (upload.versionId) {
          startMonitoring(upload.versionId, {uploadId: upload.id});
        }
      } catch (error) {
        if (upload.canceled) {
          return;
        }
        upload.status = 'error';
        upload.message = error?.message || 'Загрузка завершилась ошибкой';
        emit();
      } finally {
        activeUploads.delete(upload.id);
        emit();
        pumpUploads();
      }
    }

    function updateUploadStatus(uploadId, status, message, retryable) {
      const upload = state.uploads.find(item => item.id === uploadId);
      if (!upload || upload.canceled) return;
      upload.status = status;
      upload.message = message;
      upload.retryable = Boolean(retryable);
      emit();
    }

    function startMonitoring(versionId, optionsForVersion = {}) {
      if (!versionId) return null;
      const existing = versionPolls.get(versionId);
      if (existing) {
        if (optionsForVersion.uploadId) existing.uploadIds.add(optionsForVersion.uploadId);
        return existing.promise;
      }

      state.retryableVersionIds.delete(versionId);
      emit();

      const entry = {
        uploadIds: new Set(optionsForVersion.uploadId ? [optionsForVersion.uploadId] : []),
        promise: null
      };

      entry.promise = (async () => {
        let consecutiveErrors = 0;

        while (true) {
          try {
            const version = await options.api.getDatasetVersion(versionId);
            consecutiveErrors = 0;
            state.datasets = upsertVersionInDatasets(state.datasets, version);

            if (['ready', 'invalid', 'deleted'].includes(version.status)) {
              if (version.status !== 'deleted') {
                try {
                  const profile = await options.api.getDatasetProfile(versionId);
                  state.profileCache.set(versionId, profile);
                } catch (_) {
                  // Keep terminal status even if profile fetch fails.
                }
              }

              entry.uploadIds.forEach(uploadId => {
                updateUploadStatus(
                  uploadId,
                  version.status === 'ready' ? 'done' : version.status,
                  describeVersionStatus(version.status),
                  false
                );
              });

              state.retryableVersionIds.delete(versionId);
              emit();
              return version;
            }

            entry.uploadIds.forEach(uploadId => {
              updateUploadStatus(uploadId, 'profiling', 'Профилирование выполняется', false);
            });

            emit();
            await delayFn(DEFAULT_POLL_INTERVAL_MS);
          } catch (_) {
            consecutiveErrors += 1;

            if (consecutiveErrors >= MAX_CONSECUTIVE_POLL_ERRORS) {
              state.retryableVersionIds.add(versionId);
              entry.uploadIds.forEach(uploadId => {
                updateUploadStatus(
                  uploadId,
                  'error',
                  'Не удалось получить статус обработки файла.',
                  true
                );
              });
              emit();
              return null;
            }

            await delayFn(Math.min(4000, 500 * (2 ** (consecutiveErrors - 1))));
          }
        }
      })().finally(() => {
        versionPolls.delete(versionId);
      });

      versionPolls.set(versionId, entry);
      return entry.promise;
    }

    function retryMonitoring(versionId, uploadId) {
      if (!versionId) return;
      state.retryableVersionIds.delete(versionId);
      if (uploadId) {
        updateUploadStatus(uploadId, 'profiling', 'Профилирование выполняется', false);
      }
      startMonitoring(versionId, {uploadId});
    }

    function cancelUpload(uploadId) {
      const upload = state.uploads.find(item => item.id === uploadId);
      if (!upload) return;

      if (upload.status === 'queued') {
        state.uploads = state.uploads.filter(item => item.id !== uploadId);
        emit();
        return;
      }

      if (upload.status === 'uploading') {
        upload.canceled = true;
        upload.status = 'canceled';
        upload.message = 'Загрузка отменена';
        upload.retryable = false;
        upload.abortController?.abort();
        emit();
      }
    }

    async function deleteVersion(versionId) {
      try {
        await options.api.deleteDatasetVersion(versionId);
        state.profileCache.delete(versionId);
        state.draftSelectedVersionIds = state.draftSelectedVersionIds.filter(id => id !== versionId);
        state.viewedAnalysisVersionIds = state.viewedAnalysisVersionIds.filter(id => id !== versionId);
        persistDraftSelection();
        await refreshWorkspace();
        await hydrateProfiles();
      } catch (_) {
        state.bannerMessage = 'Не удалось удалить версию файла.';
        emit();
      }
    }

    function toggleDraftSelection(versionId, checked) {
      if (state.selectionMode !== 'draft') return;
      const index = buildVersionIndex(state.datasets).get(versionId);
      if (!index || index.version.status !== 'ready') return;

      const next = new Set(state.draftSelectedVersionIds);
      if (checked) next.add(versionId);
      else next.delete(versionId);
      state.draftSelectedVersionIds = Array.from(next);
      persistDraftSelection();
      emit();
    }

    function removeDraftSelection(versionId) {
      state.draftSelectedVersionIds = state.draftSelectedVersionIds.filter(id => id !== versionId);
      persistDraftSelection();
      emit();
    }

    return {
      state,
      versionPolls,
      initWorkspace,
      refreshWorkspace,
      hydrateProfiles,
      showDraftSelection,
      showAnalysisSelection,
      openDrawer,
      closeDrawer,
      setBannerMessage,
      clearBannerMessage,
      queueFiles,
      cancelUpload,
      startMonitoring,
      retryMonitoring,
      deleteVersion,
      toggleDraftSelection,
      removeDraftSelection,
      getSubmissionVersionIds() {
        return getDraftReadyVersionIds(state);
      }
    };
  }

  function createBrowserApi(options) {
    const apiBase = options.apiBase;
    const fetchImpl = options.fetchImpl || global.fetch.bind(global);
    const xhrFactory = options.xhrFactory || (() => new global.XMLHttpRequest());

    async function fetchJson(url, init, message) {
      const response = await fetchImpl(url, init);
      if (!response.ok) {
        throw new Error(`${message} (${response.status})`);
      }
      return response.json();
    }

    return {
      getDefaultWorkspace() {
        return fetchJson(`${apiBase}/workspaces/default`, undefined, 'Не удалось получить workspace');
      },
      listDatasets(workspaceId) {
        return fetchJson(`${apiBase}/workspaces/${encodeURIComponent(workspaceId)}/datasets`, undefined, 'Не удалось получить список файлов');
      },
      getDatasetVersion(versionId) {
        return fetchJson(`${apiBase}/dataset-versions/${encodeURIComponent(versionId)}`, undefined, 'Не удалось получить статус файла');
      },
      getDatasetProfile(versionId) {
        return fetchJson(`${apiBase}/dataset-versions/${encodeURIComponent(versionId)}/profile`, undefined, 'Не удалось получить профиль файла');
      },
      async deleteDatasetVersion(versionId) {
        const response = await fetchImpl(`${apiBase}/dataset-versions/${encodeURIComponent(versionId)}`, {
          method: 'DELETE'
        });
        if (!response.ok) {
          throw new Error('Не удалось удалить версию файла.');
        }
        return response.json();
      },
      uploadDataset({workspaceId, file, displayName, datasetId, signal, onProgress}) {
        return new Promise((resolve, reject) => {
          const xhr = xhrFactory();
          xhr.open('POST', `${apiBase}/workspaces/${encodeURIComponent(workspaceId)}/datasets`);
          xhr.responseType = 'json';

          xhr.upload.addEventListener('progress', event => {
            if (event.lengthComputable && typeof onProgress === 'function') {
              onProgress(Math.max(0, Math.min(100, Math.round((event.loaded / event.total) * 100))));
            }
          });

          xhr.onload = async () => {
            if (xhr.status >= 200 && xhr.status < 300) {
              resolve(xhr.response);
              return;
            }

            const detail = xhr.response?.detail;
            reject(new Error(sanitizeUploadError(xhr.status, detail)));
          };

          xhr.onerror = () => reject(new Error('Не удалось загрузить файл. Проверьте сеть и повторите попытку.'));
          xhr.onabort = () => reject(new Error('Загрузка отменена.'));

          signal?.addEventListener('abort', () => xhr.abort(), {once: true});

          const body = new global.FormData();
          body.append('file', file, file.name);
          if (displayName) body.append('display_name', displayName);
          if (datasetId) body.append('dataset_id', datasetId);
          xhr.send(body);
        });
      }
    };
  }

  function createDatasetWorkspaceController(options) {
    const root = options.root;
    const api = options.api || createBrowserApi({
      apiBase: options.apiBase,
      fetchImpl: options.fetchImpl,
      xhrFactory: options.xhrFactory
    });
    const fileInput = root.querySelector('#datasetFileInput');
    const dropzone = root.querySelector('#datasetDropzone');
    const elements = {
      drawer: root.querySelector('#datasetDrawer'),
      backdrop: root.querySelector('#datasetBackdrop'),
      uploadList: root.querySelector('#uploadList'),
      uploadQueueSummary: root.querySelector('#uploadQueueSummary'),
      datasetList: root.querySelector('#datasetList'),
      datasetWorkspaceSummary: root.querySelector('#datasetWorkspaceSummary'),
      composerDatasets: root.querySelector('#composerDatasets'),
      datasetLauncherCount: root.querySelector('#datasetLauncherCount'),
      drawerError: root.querySelector('#datasetDrawerError')
    };

    const core = createDatasetWorkspaceCore({
      api,
      storage: options.storage || global.localStorage,
      delay: options.delay,
      createUploadId: options.createUploadId,
      onStateChange: render
    });

    function render() {
      const state = core.state;
      elements.drawer.classList.toggle('open', state.drawerOpen);
      elements.backdrop.classList.toggle('visible', state.drawerOpen);
      elements.uploadQueueSummary.textContent = `${state.uploads.length} ${pluralize(state.uploads.length, 'файл', 'файла', 'файлов')}`;
      elements.uploadList.innerHTML = renderUploadList(state);
      elements.datasetList.innerHTML = renderDatasetListMarkup(state);
      elements.datasetWorkspaceSummary.textContent = `${state.datasets.length} ${pluralize(state.datasets.length, 'набор', 'набора', 'наборов')}`;
      elements.datasetLauncherCount.textContent = String(getDraftReadyVersionIds(state).length);
      elements.composerDatasets.innerHTML = renderComposerMarkup(state);
      elements.drawerError.hidden = !state.bannerMessage;
      elements.drawerError.textContent = state.bannerMessage || '';
    }

    function handleFileInputChange(files) {
      const context = core.state.filePickerContext;
      core.state.filePickerContext = null;
      fileInput.value = '';
      core.queueFiles(files, context);
    }

    function handleClick(event) {
      const actionTarget = event.target.closest('[data-action]');
      if (!actionTarget) return;

      const action = actionTarget.dataset.action;
      const datasetId = actionTarget.dataset.datasetId || null;
      const versionId = actionTarget.dataset.versionId || null;
      const uploadId = actionTarget.dataset.uploadId || null;

      switch (action) {
        case 'open-drawer':
          core.openDrawer();
          break;
        case 'close-drawer':
          core.closeDrawer();
          break;
        case 'pick-files':
          core.state.filePickerContext = {mode: 'upload', datasetId: null};
          fileInput.multiple = true;
          fileInput.click();
          break;
        case 'add-version':
          core.state.filePickerContext = {mode: 'add-version', datasetId};
          fileInput.multiple = true;
          fileInput.click();
          break;
        case 'cancel-upload':
          core.cancelUpload(uploadId);
          break;
        case 'delete-version':
          core.deleteVersion(versionId);
          break;
        case 'remove-draft-selection':
          core.removeDraftSelection(versionId);
          break;
        case 'retry-workspace':
          core.setBannerMessage('');
          core.initWorkspace();
          break;
        case 'retry-version-status':
          core.retryMonitoring(versionId, uploadId || undefined);
          break;
      }
    }

    function handleChange(event) {
      const target = event.target;
      if (target === fileInput) {
        handleFileInputChange(Array.from(target.files || []));
        return;
      }

      const action = target.dataset.action;
      if (action === 'toggle-version-selection') {
        core.toggleDraftSelection(target.dataset.versionId, target.checked);
      }
    }

    ['dragenter', 'dragover'].forEach(eventName => {
      dropzone.addEventListener(eventName, event => {
        event.preventDefault();
        dropzone.classList.add('dragover');
      });
    });

    ['dragleave', 'dragend', 'drop'].forEach(eventName => {
      dropzone.addEventListener(eventName, event => {
        event.preventDefault();
        dropzone.classList.remove('dragover');
      });
    });

    dropzone.addEventListener('drop', event => {
      const files = Array.from(event.dataTransfer?.files || []);
      if (files.length) {
        core.queueFiles(files, {mode: 'upload', datasetId: null});
      }
    });

    root.addEventListener('click', handleClick);
    root.addEventListener('change', handleChange);
    render();

    return {
      init: () => core.initWorkspace(),
      openDrawer: () => core.openDrawer(),
      closeDrawer: () => core.closeDrawer(),
      showDraftSelection: () => core.showDraftSelection(),
      setViewedAnalysisVersionIds: ids => core.showAnalysisSelection(ids),
      getSubmissionVersionIds: () => core.getSubmissionVersionIds(),
      getState: () => core.state
    };
  }

  const DatasetWorkspace = {
    DEFAULT_WORKSPACE_ID,
    MAX_PARALLEL_UPLOADS,
    MAX_CONSECUTIVE_POLL_ERRORS,
    STORAGE_KEYS,
    escapeHtml,
    escapeAttribute,
    pluralize,
    formatBytes,
    stemFilename,
    normalizeVersionIdList,
    createInitialDatasetWorkspaceState,
    buildVersionIndex,
    getVersionEntriesByIds,
    getDraftReadyVersionIds,
    createUploadItems,
    shouldShowCancel,
    renderUploadMarkup,
    renderUploadList,
    renderDatasetCardMarkup,
    renderDatasetListMarkup,
    renderComposerMarkup,
    createDatasetWorkspaceCore,
    createDatasetWorkspaceController
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = DatasetWorkspace;
  }

  global.DatasetWorkspace = DatasetWorkspace;
})(typeof window !== 'undefined' ? window : globalThis);
