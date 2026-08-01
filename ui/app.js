(() => {
  'use strict';

  const config = window.MIRROLLA_CONFIG || {};
  const apiBase = String(config.apiBase || '').replace(/\/$/, '');
  const analysisPollMs = 1500;

  const refs = {};
  const state = {
    activeAnalysisId: null,
    activeAnalysis: null,
    waiting: false,
    historyIds: loadHistory(),
    analysisPollAbort: false
  };

  document.addEventListener('DOMContentLoaded', init);

  function init() {
    Object.assign(refs, {
      sidebar: byId('sidebar'),
      historyList: byId('historyList'),
      conversationTitle: byId('conversationTitle'),
      welcomeView: byId('welcomeView'),
      messageStream: byId('messageStream'),
      composerForm: byId('composerForm'),
      questionInput: byId('questionInput'),
      sendButton: byId('sendButton'),
      inlineDropzone: byId('inlineDropzone'),
      inlineFileInput: byId('inlineFileInput'),
      inlineUploadSummary: byId('inlineUploadSummary'),
      composerFileInput: byId('composerFileInput'),
      attachmentStrip: byId('attachmentStrip'),
      selectedCount: byId('selectedCount'),
      datasetCount: byId('datasetCount'),
      dataDrawer: byId('dataDrawer'),
      drawerDropzone: byId('drawerDropzone'),
      drawerFileInput: byId('drawerFileInput'),
      uploadQueue: byId('uploadQueue'),
      datasetList: byId('datasetList'),
      toastRegion: byId('toastRegion')
    });

    window.DatasetWorkspace.init(refs);
    window.DatasetWorkspace.subscribe(snapshot => {
      refs.selectedCount.textContent = String(snapshot.selectedVersions.length);
      refs.sendButton.disabled = state.waiting || !refs.questionInput.value.trim();
    });

    document.addEventListener('click', handleGlobalClick);
    refs.composerForm.addEventListener('submit', handleSubmit);
    refs.questionInput.addEventListener('input', handleQuestionInput);
    refs.questionInput.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        if (!refs.sendButton.disabled) refs.composerForm.requestSubmit();
      }
    });
    refs.messageStream.addEventListener('click', handleMessageAction);
    refs.historyList.addEventListener('click', event => {
      const button = event.target.closest('[data-analysis-id]');
      if (button) openAnalysis(button.dataset.analysisId);
    });
    document.querySelectorAll('[data-example]').forEach(button => button.addEventListener('click', () => {
      refs.questionInput.value = button.dataset.example;
      handleQuestionInput();
      refs.questionInput.focus();
    }));

    renderHistory();
    autoResizeTextarea();
  }

  function handleGlobalClick(event) {
    const action = event.target.closest('[data-action]')?.dataset.action;
    switch (action) {
      case 'new-chat': resetConversation(); break;
      case 'open-datasets': window.DatasetWorkspace.openDrawer(); break;
      case 'close-datasets': window.DatasetWorkspace.closeDrawer(); break;
      case 'refresh-datasets': window.DatasetWorkspace.refresh(); break;
      case 'pick-inline-files': refs.inlineFileInput.click(); break;
      case 'pick-composer-files': refs.composerFileInput.click(); break;
      case 'open-sidebar': document.body.classList.add('sidebar-open'); break;
      case 'close-sidebar': document.body.classList.remove('sidebar-open'); break;
      default: break;
    }
  }

  function handleQuestionInput() {
    autoResizeTextarea();
    refs.sendButton.disabled = state.waiting || !refs.questionInput.value.trim();
  }

  function autoResizeTextarea() {
    refs.questionInput.style.height = 'auto';
    refs.questionInput.style.height = `${Math.min(refs.questionInput.scrollHeight, 180)}px`;
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const question = refs.questionInput.value.trim();
    if (!question || state.waiting) return;

    const versionIds = window.DatasetWorkspace.getReadyVersionIds();
    state.waiting = true;
    refs.sendButton.disabled = true;
    refs.questionInput.value = '';
    autoResizeTextarea();
    showConversation();
    appendUserMessage(question);
    const loadingId = appendLoading('Формирую план анализа…');

    try {
      const analysis = await api('/api/v1/analyses', {
        method: 'POST',
        body: JSON.stringify({ question, dataset_version_ids: versionIds })
      });
      removeMessage(loadingId);
      state.activeAnalysis = analysis;
      state.activeAnalysisId = analysis.id || analysis.analysis_id;
      rememberAnalysis(state.activeAnalysisId);
      updateTitle(question);
      renderAnalysisState(analysis);
      if (needsPolling(analysis.status)) pollAnalysis(state.activeAnalysisId);
    } catch (error) {
      removeMessage(loadingId);
      appendAssistantMessage(`Не удалось создать анализ: ${safeMessage(error)}`, { error: true });
    } finally {
      state.waiting = false;
      handleQuestionInput();
    }
  }

  async function openAnalysis(analysisId) {
    if (!analysisId) return;
    state.analysisPollAbort = true;
    showConversation();
    refs.messageStream.innerHTML = '';
    const loadingId = appendLoading('Загружаю анализ…');
    try {
      const analysis = await api(`/api/v1/analyses/${encodeURIComponent(analysisId)}`);
      removeMessage(loadingId);
      state.activeAnalysisId = analysisId;
      state.activeAnalysis = analysis;
      updateTitle(analysis.question || 'Анализ');
      if (analysis.question) appendUserMessage(analysis.question);
      renderAnalysisState(analysis);
      if (needsPolling(analysis.status)) pollAnalysis(analysisId);
      renderHistory();
      document.body.classList.remove('sidebar-open');
    } catch (error) {
      removeMessage(loadingId);
      appendAssistantMessage(`Не удалось открыть анализ: ${safeMessage(error)}`, { error: true });
    }
  }

  function renderAnalysisState(analysis) {
    const status = String(analysis.status || '').toLowerCase();
    if (['planning'].includes(status)) {
      appendLoading('Формирую план анализа…', 'analysis-status');
      return;
    }
    if (['awaiting_approval', 'planned', 'pending_approval'].includes(status)) {
      removeMessage('analysis-status');
      renderPlan(analysis);
      return;
    }
    if (['queued'].includes(status)) {
      replaceStatus('Анализ поставлен в очередь…');
      return;
    }
    if (['executing', 'running', 'approved'].includes(status)) {
      replaceStatus('Выполняю расчёты по выбранным данным…');
      return;
    }
    removeMessage('analysis-status');
    if (['completed', 'partial', 'not_enough_data', 'done'].includes(status)) {
      const result = analysis.result || analysis.execution_result || analysis.report || analysis.answer;
      appendAssistantMessage(renderResult(result, analysis), { html: true, id: 'analysis-result' });
      return;
    }
    if (status === 'rejected') {
      appendAssistantMessage('Анализ отклонён.', { id: 'analysis-result' });
      return;
    }
    if (status === 'failed' || status === 'error') {
      appendAssistantMessage(`Анализ завершился ошибкой: ${escapeHtml(errorText(analysis))}`, { html: true, error: true, id: 'analysis-result' });
    }
  }

  function renderPlan(analysis) {
    if (document.getElementById('analysis-plan')) return;
    const plan = analysis.plan || analysis.analysis_plan || {};
    const steps = extractPlanSteps(plan);
    const limitations = plan.limitations || plan.constraints || [];
    const files = analysis.dataset_attachments || analysis.attachments || [];
    const html = `
      <div class="plan-card">
        <div class="plan-head">
          <strong>План анализа</strong>
          <span>Проверьте подход перед запуском</span>
        </div>
        <div class="plan-body">
          ${steps.length ? `<ol>${steps.map(step => `<li>${escapeHtml(step)}</li>`).join('')}</ol>` : `<pre>${escapeHtml(JSON.stringify(plan, null, 2))}</pre>`}
          ${files.length ? `<p><strong>Файлы:</strong> ${files.map(item => escapeHtml(item.original_filename || item.display_name || item.name || 'Файл')).join(', ')}</p>` : ''}
          ${limitations.length ? `<p><strong>Ограничения:</strong></p><ul>${limitations.map(item => `<li>${escapeHtml(typeof item === 'string' ? item : JSON.stringify(item))}</li>`).join('')}</ul>` : ''}
        </div>
        <div class="plan-actions">
          <button class="primary-button" type="button" data-plan-action="approve">Запустить анализ</button>
          <button class="ghost-button" type="button" data-plan-action="revise">Изменить план</button>
          <button class="danger-button" type="button" data-plan-action="reject">Отклонить</button>
        </div>
        <div class="revision-box" id="revisionBox">
          <textarea id="revisionInput" placeholder="Что нужно изменить в плане?"></textarea>
          <div><button class="primary-button" type="button" data-plan-action="submit-revision">Отправить изменения</button></div>
        </div>
      </div>
    `;
    appendAssistantMessage(html, { html: true, id: 'analysis-plan' });
  }

  async function handleMessageAction(event) {
    const action = event.target.closest('[data-plan-action]')?.dataset.planAction;
    if (!action || !state.activeAnalysisId) return;
    if (action === 'revise') {
      byId('revisionBox')?.classList.toggle('open');
      byId('revisionInput')?.focus();
      return;
    }
    if (action === 'submit-revision') {
      const feedback = byId('revisionInput')?.value.trim();
      if (!feedback) return;
      await transition('revise', { feedback });
      return;
    }
    if (action === 'approve') await transition('approve');
    if (action === 'reject') await transition('reject');
  }

  async function transition(action, payload = null) {
    disablePlanButtons(true);
    try {
      const analysis = await api(`/api/v1/analyses/${encodeURIComponent(state.activeAnalysisId)}/${action}`, {
        method: 'POST',
        body: payload ? JSON.stringify(payload) : undefined
      });
      state.activeAnalysis = analysis;
      removeMessage('analysis-plan');
      renderAnalysisState(analysis);
      if (needsPolling(analysis.status)) pollAnalysis(state.activeAnalysisId);
    } catch (error) {
      window.DatasetWorkspace.toast(`Не удалось выполнить действие: ${safeMessage(error)}`, 'error');
      disablePlanButtons(false);
    }
  }

  function disablePlanButtons(disabled) {
    refs.messageStream.querySelectorAll('[data-plan-action]').forEach(button => button.disabled = disabled);
  }

  async function pollAnalysis(analysisId) {
    state.analysisPollAbort = true;
    await Promise.resolve();
    state.analysisPollAbort = false;
    let failures = 0;
    while (!state.analysisPollAbort && state.activeAnalysisId === analysisId) {
      await sleep(analysisPollMs);
      try {
        const analysis = await api(`/api/v1/analyses/${encodeURIComponent(analysisId)}`);
        failures = 0;
        state.activeAnalysis = analysis;
        renderAnalysisState(analysis);
        if (!needsPolling(analysis.status)) return;
      } catch (_) {
        failures += 1;
        if (failures >= 5) {
          replaceStatus('Связь с сервером временно потеряна. Откройте анализ из истории, чтобы повторить проверку.');
          return;
        }
      }
    }
  }

  function needsPolling(status) {
    return ['planning', 'queued', 'executing', 'running', 'approved'].includes(String(status || '').toLowerCase());
  }

  function replaceStatus(text) {
    removeMessage('analysis-status');
    appendLoading(text, 'analysis-status');
  }

  function renderResult(result, analysis) {
    if (!result) return '<p>Анализ завершён, но сервер не вернул текст результата.</p>';
    if (typeof result === 'string') return simpleMarkdown(result);
    const answer = result.answer || result.report || result.summary || result.final_answer || analysis.answer;
    const findings = result.findings || result.items || [];
    const limitations = result.limitations || [];
    let html = answer ? simpleMarkdown(String(answer)) : '';
    if (Array.isArray(findings) && findings.length) {
      html += '<h3>Основные выводы</h3><ul>' + findings.map(item => `<li>${escapeHtml(findingText(item))}</li>`).join('') + '</ul>';
    }
    if (Array.isArray(limitations) && limitations.length) {
      html += '<h3>Ограничения</h3><ul>' + limitations.map(item => `<li>${escapeHtml(typeof item === 'string' ? item : JSON.stringify(item))}</li>`).join('') + '</ul>';
    }
    if (!html) html = `<pre>${escapeHtml(JSON.stringify(result, null, 2))}</pre>`;
    return html;
  }

  function findingText(item) {
    if (typeof item === 'string') return item;
    return item.reason || item.description || item.title || item.message || JSON.stringify(item);
  }

  function extractPlanSteps(plan) {
    const candidates = plan.steps || plan.hypotheses || plan.actions || plan.methodology || [];
    if (!Array.isArray(candidates)) return [];
    return candidates.map(item => {
      if (typeof item === 'string') return item;
      return item.description || item.hypothesis || item.title || item.action || item.method || JSON.stringify(item);
    });
  }

  function appendUserMessage(text) {
    return appendMessage('user', `<div class="user-bubble">${escapeHtml(text)}</div>`);
  }

  function appendAssistantMessage(content, options = {}) {
    return appendMessage('assistant', options.html ? content : `<p>${escapeHtml(content)}</p>`, options);
  }

  function appendLoading(text, id = null) {
    return appendMessage('assistant', `<div class="status-line"><span class="spinner"></span><span>${escapeHtml(text)}</span></div>`, { id });
  }

  function appendMessage(role, html, options = {}) {
    if (options.id && document.getElementById(options.id)) return options.id;
    const id = options.id || `message-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const element = document.createElement('article');
    element.className = `message ${role}`;
    element.id = id;
    element.innerHTML = `
      <div class="message-avatar">${role === 'user' ? 'Вы' : 'M'}</div>
      <div class="message-content">${html}</div>
    `;
    if (options.error) element.querySelector('.message-content').style.color = 'var(--danger)';
    refs.messageStream.appendChild(element);
    element.scrollIntoView({ behavior: 'smooth', block: 'end' });
    return id;
  }

  function removeMessage(id) { document.getElementById(id)?.remove(); }

  function showConversation() {
    refs.welcomeView.hidden = true;
    refs.messageStream.hidden = false;
  }

  function resetConversation() {
    state.analysisPollAbort = true;
    state.activeAnalysisId = null;
    state.activeAnalysis = null;
    refs.messageStream.innerHTML = '';
    refs.messageStream.hidden = true;
    refs.welcomeView.hidden = false;
    refs.questionInput.value = '';
    updateTitle('Новый анализ');
    renderHistory();
    handleQuestionInput();
    document.body.classList.remove('sidebar-open');
  }

  function updateTitle(value) {
    const title = String(value || 'Новый анализ').trim();
    refs.conversationTitle.textContent = title.length > 72 ? `${title.slice(0, 69)}…` : title;
  }

  function rememberAnalysis(id) {
    if (!id) return;
    state.historyIds = [id, ...state.historyIds.filter(item => item !== id)].slice(0, 30);
    localStorage.setItem('mirrolla_analysis_history', JSON.stringify(state.historyIds));
    renderHistory();
  }

  function loadHistory() {
    try {
      const value = JSON.parse(localStorage.getItem('mirrolla_analysis_history') || '[]');
      return Array.isArray(value) ? value.filter(item => typeof item === 'string') : [];
    } catch (_) { return []; }
  }

  function renderHistory() {
    if (!state.historyIds.length) {
      refs.historyList.innerHTML = '<div class="empty-state">История появится после первого анализа</div>';
      return;
    }
    refs.historyList.innerHTML = '<div class="history-label">Недавние</div>' + state.historyIds.map((id, index) => `
      <button class="history-item ${state.activeAnalysisId === id ? 'active' : ''}" type="button" data-analysis-id="${escapeHtml(id)}">
        ${index === 0 ? 'Последний анализ' : `Анализ ${id.slice(0, 8)}`}
      </button>
    `).join('');
  }

  async function api(path, options = {}) {
    const key = window.MIRROLLA_API_KEY || localStorage.getItem('mirrolla_api_key');
    const response = await fetch(`${apiBase}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(key ? { 'X-API-Key': key } : {}),
        ...(options.headers || {})
      }
    });
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try {
        const payload = await response.json();
        detail = payload.detail || payload.message || detail;
      } catch (_) {}
      throw new Error(detail);
    }
    return response.status === 204 ? null : response.json();
  }

  function simpleMarkdown(text) {
    const escaped = escapeHtml(text);
    return escaped
      .replace(/^### (.+)$/gm, '<h3>$1</h3>')
      .replace(/^## (.+)$/gm, '<h2>$1</h2>')
      .replace(/^# (.+)$/gm, '<h2>$1</h2>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/^[-•] (.+)$/gm, '<li>$1</li>')
      .replace(/(?:<li>.*<\/li>\n?)+/g, match => `<ul>${match}</ul>`)
      .replace(/\n{2,}/g, '</p><p>')
      .replace(/\n/g, '<br>')
      .replace(/^/, '<p>')
      .replace(/$/, '</p>');
  }

  function errorText(analysis) {
    const value = analysis.error || analysis.error_message || analysis.result?.error;
    if (typeof value === 'string') return value;
    return value?.message || value?.code || 'Неизвестная ошибка';
  }

  function safeMessage(error) {
    const value = String(error?.message || 'Неизвестная ошибка');
    return value.length > 240 ? `${value.slice(0, 237)}…` : value;
  }

  function escapeHtml(value) {
    return window.DatasetWorkspace?.escapeHtml(value) || String(value ?? '').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char]);
  }

  function byId(id) { return document.getElementById(id); }
  function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
})();
