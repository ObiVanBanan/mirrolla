const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const workspace = require('../../ui/dataset_workspace.js');

function createMemoryStorage(initial = {}) {
  const map = new Map(Object.entries(initial));
  return {
    getItem(key) {
      return map.has(key) ? map.get(key) : null;
    },
    setItem(key, value) {
      map.set(key, String(value));
    }
  };
}

function createApi(overrides = {}) {
  return {
    getDefaultWorkspace: async () => ({id: 'default'}),
    listDatasets: async () => ({datasets: []}),
    getDatasetVersion: async () => ({id: 'version-1', dataset_id: 'dataset-1', status: 'ready'}),
    getDatasetProfile: async () => ({version_id: 'version-1', status: 'ready', profile: {sheets: []}, issues: []}),
    deleteDatasetVersion: async () => ({}),
    uploadDataset: async () => ({version: {id: 'version-1'}}),
    ...overrides
  };
}

function createCore(options = {}) {
  return workspace.createDatasetWorkspaceCore({
    api: createApi(options.api || {}),
    storage: options.storage || createMemoryStorage(),
    delay: options.delay || (async () => {}),
    createUploadId: options.createUploadId,
    onStateChange: options.onStateChange
  });
}

function file(name, size = 32) {
  return {name, size};
}

async function waitFor(predicate, attempts = 20) {
  for (let index = 0; index < attempts; index += 1) {
    if (predicate()) return;
    await Promise.resolve();
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.fail('Condition was not met');
}

test('dynamic dataset markup has no inline handlers', () => {
  const state = workspace.createInitialDatasetWorkspaceState({
    initialized: true,
    datasets: [{
      id: 'dataset-1',
      display_name: 'Sales',
      source_type: 'upload',
      versions: [{
        id: 'version-1',
        dataset_id: 'dataset-1',
        original_filename: 'sales.csv',
        format: 'csv',
        size_bytes: 32,
        status: 'ready'
      }]
    }],
    draftSelectedVersionIds: ['version-1']
  });

  const html = [
    workspace.renderUploadList(state),
    workspace.renderDatasetListMarkup(state),
    workspace.renderComposerMarkup(state)
  ].join('\n');

  assert.equal(/onclick=|onchange=|oninput=|onerror=/i.test(html), false);
});

test('static dataset html has no inline handlers in workspace section', () => {
  const html = fs.readFileSync(path.join(__dirname, '../../ui/mirrolla_assistant.html'), 'utf-8');
  const start = html.indexOf('<button class="dataset-launcher"');
  const end = html.indexOf('<div class="content" id="content">', start);
  const snippet = html.slice(start, end);

  assert.equal(/onclick=|onchange=|oninput=|onerror=/i.test(snippet), false);
});

test('display_name with quotes is escaped and not turned into script code', () => {
  const html = workspace.renderDatasetCardMarkup(
    {
      id: 'dataset-1',
      display_name: `bad" name '</script><script>alert(1)</script>`,
      source_type: 'upload',
      versions: []
    },
    {
      draftSelectedVersionIds: [],
      viewedAnalysisVersionIds: [],
      selectionMode: 'draft',
      profileCache: new Map(),
      retryableVersionIds: new Set()
    }
  );

  assert.match(html, /&quot;/);
  assert.equal(html.includes('onclick='), false);
  assert.equal(html.includes('<script>alert(1)</script>'), false);
});

test('one version creates only one polling loop', async () => {
  let callCount = 0;
  let resolveFetch;
  const gate = new Promise(resolve => { resolveFetch = resolve; });
  const core = createCore({
    api: {
      getDatasetVersion: async () => {
        callCount += 1;
        await gate;
        return {id: 'version-1', dataset_id: 'dataset-1', status: 'ready'};
      }
    }
  });

  const first = core.startMonitoring('version-1');
  const second = core.startMonitoring('version-1');

  assert.equal(first, second);
  assert.equal(core.versionPolls.size, 1);

  resolveFetch();
  await first;
  assert.equal(callCount, 1);
  assert.equal(core.versionPolls.size, 0);
});

test('upload item becomes done after ready', async () => {
  let versionCalls = 0;
  const core = createCore({
    api: {
      listDatasets: async () => ({
        datasets: [{
          id: 'dataset-1',
          display_name: 'Sales',
          source_type: 'upload',
          versions: [{
            id: 'version-1',
            dataset_id: 'dataset-1',
            original_filename: 'sales.csv',
            format: 'csv',
            size_bytes: 32,
            status: 'profiling'
          }]
        }]
      }),
      uploadDataset: async () => ({version: {id: 'version-1'}}),
      getDatasetVersion: async () => {
        versionCalls += 1;
        return {id: 'version-1', dataset_id: 'dataset-1', original_filename: 'sales.csv', format: 'csv', size_bytes: 32, status: 'ready'};
      },
      getDatasetProfile: async () => ({version_id: 'version-1', status: 'ready', profile: {sheets: []}, issues: []})
    }
  });

  core.state.initialized = true;
  core.queueFiles([file('sales.csv')], {mode: 'upload'});

  await waitFor(() => core.state.uploads[0] && core.state.uploads[0].status === 'done');
  assert.equal(versionCalls >= 1, true);
});

test('temporary polling error does not terminate monitoring', async () => {
  let calls = 0;
  const core = createCore({
    api: {
      getDatasetVersion: async () => {
        calls += 1;
        if (calls === 1) {
          throw new Error('temporary');
        }
        return {id: 'version-1', dataset_id: 'dataset-1', status: 'ready'};
      }
    }
  });

  await core.startMonitoring('version-1');
  assert.equal(calls, 2);
  assert.equal(core.state.retryableVersionIds.has('version-1'), false);
});

test('five polling errors mark version retryable', async () => {
  let calls = 0;
  const core = createCore({
    api: {
      getDatasetVersion: async () => {
        calls += 1;
        throw new Error('down');
      }
    }
  });

  await core.startMonitoring('version-1');
  assert.equal(calls, workspace.MAX_CONSECUTIVE_POLL_ERRORS);
  assert.equal(core.state.retryableVersionIds.has('version-1'), true);
});

test('cancel queued upload does not start upload call', async () => {
  let uploadCalls = 0;
  let release;
  const blocker = new Promise(resolve => { release = resolve; });
  const core = createCore({
    api: {
      uploadDataset: async () => {
        uploadCalls += 1;
        await blocker;
        return {version: {id: `version-${uploadCalls}`}};
      }
    }
  });

  core.state.initialized = true;
  core.queueFiles([file('a.csv'), file('b.csv'), file('c.csv'), file('d.csv')], {mode: 'upload'});
  const queued = core.state.uploads.find(item => item.status === 'queued');
  assert.ok(queued);
  core.cancelUpload(queued.id);
  release();
  await Promise.resolve();
  assert.equal(core.state.uploads.some(item => item.id === queued.id), false);
  assert.equal(uploadCalls, 3);
});

test('cancel uploading aborts xhr', async () => {
  let aborted = 0;
  const core = createCore({
    api: {
      uploadDataset: async ({signal}) => new Promise((resolve, reject) => {
        signal.addEventListener('abort', () => {
          aborted += 1;
          reject(new Error('Загрузка отменена.'));
        }, {once: true});
      })
    }
  });

  core.state.initialized = true;
  core.queueFiles([file('sales.csv')], {mode: 'upload'});
  await waitFor(() => core.state.uploads[0] && core.state.uploads[0].status === 'uploading');
  core.cancelUpload(core.state.uploads[0].id);
  await waitFor(() => aborted === 1);
  assert.equal(aborted, 1);
});

test('profiling upload does not show cancel button', () => {
  const html = workspace.renderUploadMarkup({
    id: 'upload-1',
    file: file('sales.csv'),
    displayName: 'Sales',
    progress: 100,
    status: 'profiling',
    message: 'Профилирование выполняется',
    retryable: false
  });

  assert.equal(html.includes('data-action="cancel-upload"'), false);
});

test('opening analysis does not mutate draft selection', () => {
  const core = createCore();
  core.state.initialized = true;
  core.state.datasets = [{
    id: 'dataset-1',
    display_name: 'Sales',
    versions: [
      {id: 'draft-version', dataset_id: 'dataset-1', status: 'ready'},
      {id: 'analysis-version', dataset_id: 'dataset-1', status: 'ready'}
    ]
  }];
  core.state.draftSelectedVersionIds = ['draft-version'];

  core.showAnalysisSelection(['analysis-version']);

  assert.deepEqual(core.state.draftSelectedVersionIds, ['draft-version']);
  assert.deepEqual(core.getSubmissionVersionIds(), ['draft-version']);
});

test('stale localStorage ids are not sent to API', () => {
  const core = createCore({
    storage: createMemoryStorage({
      [workspace.STORAGE_KEYS.draftSelectedVersionIds]: JSON.stringify(['missing-version'])
    })
  });
  core.state.initialized = true;
  core.state.datasets = [{
    id: 'dataset-1',
    display_name: 'Sales',
    versions: [{id: 'ready-version', dataset_id: 'dataset-1', status: 'ready'}]
  }];

  assert.deepEqual(core.getSubmissionVersionIds(), []);
});

test('non-ready version is not sent to API', () => {
  const core = createCore();
  core.state.initialized = true;
  core.state.datasets = [{
    id: 'dataset-1',
    display_name: 'Sales',
    versions: [{id: 'pending-version', dataset_id: 'dataset-1', status: 'uploaded'}]
  }];
  core.state.draftSelectedVersionIds = ['pending-version'];

  assert.deepEqual(core.getSubmissionVersionIds(), []);
});

test('multiple files for add-version are rejected', () => {
  const core = createCore();
  const accepted = core.queueFiles([file('a.csv'), file('b.csv')], {mode: 'add-version', datasetId: 'dataset-1'});

  assert.equal(accepted, false);
  assert.equal(core.state.uploads.length, 0);
  assert.match(core.state.bannerMessage, /один файл/i);
});

test('multiple ordinary files create separate upload items', () => {
  const core = createCore({
    api: {
      uploadDataset: async () => new Promise(() => {})
    }
  });
  core.state.initialized = true;
  core.queueFiles([file('a.csv'), file('b.csv')], {mode: 'upload'});

  assert.equal(core.state.uploads.length, 2);
});

test('inline dropzone is present in html and script is served from root path', () => {
  const html = fs.readFileSync(path.join(__dirname, '../../ui/mirrolla_assistant.html'), 'utf-8');

  assert.match(html, /id="inlineDatasetUpload"/);
  assert.match(html, /id="inlineDatasetDropzone"/);
  assert.match(html, /src="\/dataset_workspace\.js"/);
});

test('inline upload status and drawer use the same upload state', () => {
  const state = workspace.createInitialDatasetWorkspaceState({
    initialized: true,
    uploads: [{
      id: 'upload-1',
      file: file('sales.csv'),
      displayName: 'sales',
      progress: 64,
      status: 'uploading',
      message: 'Uploading',
      retryable: false
    }]
  });

  const inlineHtml = workspace.renderInlineUploadStatus(state);
  const drawerHtml = workspace.renderUploadList(state);

  assert.match(inlineHtml, /sales\.csv/);
  assert.match(drawerHtml, /sales\.csv/);
});

test('csv files are accepted for upload queue', () => {
  const core = createCore({
    api: {
      uploadDataset: async () => new Promise(() => {})
    }
  });
  core.state.initialized = true;

  const accepted = core.queueFiles([file('sales.csv')], {mode: 'upload'});

  assert.equal(accepted, true);
  assert.equal(core.state.uploads.length, 1);
});

test('xlsx files are accepted for upload queue', () => {
  const core = createCore({
    api: {
      uploadDataset: async () => new Promise(() => {})
    }
  });
  core.state.initialized = true;

  const accepted = core.queueFiles([file('sales.xlsx')], {mode: 'upload'});

  assert.equal(accepted, true);
  assert.equal(core.state.uploads.length, 1);
});

test('json files are accepted for upload queue', () => {
  const core = createCore({
    api: {
      uploadDataset: async () => new Promise(() => {})
    }
  });
  core.state.initialized = true;

  const accepted = core.queueFiles([file('sales.json')], {mode: 'upload'});

  assert.equal(accepted, true);
  assert.equal(core.state.uploads.length, 1);
});

test('unsupported extension is rejected', () => {
  const core = createCore();
  core.state.initialized = true;

  const accepted = core.queueFiles([file('notes.txt')], {mode: 'upload'});

  assert.equal(accepted, false);
  assert.equal(core.state.uploads.length, 0);
  assert.match(core.state.bannerMessage, /\.csv, \.xlsx/i);
});

test('ready upload is automatically selected for draft analysis', async () => {
  const core = createCore({
    api: {
      listDatasets: async () => ({
        datasets: [{
          id: 'dataset-1',
          display_name: 'Sales',
          source_type: 'upload',
          versions: [{
            id: 'version-1',
            dataset_id: 'dataset-1',
            original_filename: 'sales.csv',
            format: 'csv',
            size_bytes: 32,
            status: 'profiling'
          }]
        }]
      }),
      uploadDataset: async () => ({version: {id: 'version-1'}}),
      getDatasetVersion: async () => ({
        id: 'version-1',
        dataset_id: 'dataset-1',
        original_filename: 'sales.csv',
        format: 'csv',
        size_bytes: 32,
        status: 'ready'
      }),
      getDatasetProfile: async () => ({version_id: 'version-1', status: 'ready', profile: {sheets: []}, issues: []})
    }
  });

  core.state.initialized = true;
  core.queueFiles([file('sales.csv')], {mode: 'upload'});

  await waitFor(() => core.state.draftSelectedVersionIds.includes('version-1'));
  assert.deepEqual(core.getSubmissionVersionIds(), ['version-1']);
});

test('remove chip behavior clears ready version from draft selection', () => {
  const core = createCore();
  core.state.initialized = true;
  core.state.datasets = [{
    id: 'dataset-1',
    display_name: 'Sales',
    versions: [{id: 'ready-version', dataset_id: 'dataset-1', status: 'ready'}]
  }];
  core.state.draftSelectedVersionIds = ['ready-version'];

  core.toggleDraftSelection('ready-version', false);

  assert.deepEqual(core.state.draftSelectedVersionIds, []);
  assert.deepEqual(core.getSubmissionVersionIds(), []);
});
