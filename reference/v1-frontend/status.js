// pistoncore/frontend/js/status.js
//
// Page 2 — Piston Status Page
// The hub for each individual piston. Loads piston, renders read-only script,
// log panel, quick facts, and action buttons.

const StatusPage = (() => {

  const container = document.getElementById('page-status');
  let _piston = null;

  // ── Load ─────────────────────────────────────────────────
  async function load(pistonId) {
    if (!container) return;
    container.innerHTML = `<div class="wizard-loading"><div class="spinner"></div> Loading...</div>`;

    try {
      _piston = await API.getPiston(pistonId);
      render(_piston);
    } catch (e) {
      // Load failed — render a minimal shell so the status page is still
      // functional. The error shows in the validation-banner slot and the
      // Delete button is available if the piston needs to be removed.
      _piston = { id: pistonId, name: 'Unknown', statements: [], variables: [],
                  triggers: [], conditions: [], restrictions: [],
                  enabled: false, mode: 'single', compile_target: 'Native HA Script',
                  logic_version: 2, ui_version: 1 };
      render(_piston);
      _showNotice(`Could not load piston: ${e.message}`, 'error');
    }
  }

  function render(piston) {
    if (!container) return;

    const enabled = piston.enabled !== false;
    const target = piston.compile_target || 'Native HA Script';
    const targetClass = target.toLowerCase().includes('pyscript') ? 'pyscript' : '';

    container.innerHTML = `
      <div class="status-back" id="status-back">← My Pistons</div>

      <div class="status-title">${_esc(piston.name || 'Untitled')}</div>

      <div class="status-meta">
        <div class="status-meta-item">
          <div class="status-active-dot" style="background: ${enabled ? 'var(--green)' : 'var(--text-muted)'}"></div>
          <span>${enabled ? 'Active' : 'Paused'}</span>
        </div>
        <div class="status-meta-item">
          Folder:
          <select id="status-folder-select" style="margin-left:4px; font-size:12px; padding:2px 6px">
            ${_folderOptions(piston.folder)}
          </select>
        </div>
        <button class="btn btn-ghost btn-sm" id="status-toggle-enabled">
          ${enabled ? 'Pause' : 'Resume'}
        </button>
      </div>

      <!-- Validation banner (populated after save) -->
      <div id="validation-banner"></div>

      <!-- Deployed vs saved notice -->
      <div id="deploy-notice"></div>

      <!-- Action buttons -->
      <div class="status-section">
        <div class="status-actions">
          <button class="btn btn-primary" id="btn-edit">✎ Edit</button>
          <button class="btn btn-danger" id="btn-test">▶ Test — Live Fire ⚠</button>
          <button class="btn" id="btn-snapshot" style="color:var(--green);border-color:var(--green-dim)">📷 Snapshot</button>
          <button class="btn" id="btn-backup" style="color:var(--red);border-color:var(--red-dim)">📷 Backup</button>
          <button class="btn" id="btn-duplicate">⧉ Duplicate</button>
          <button class="btn btn-danger" id="btn-delete">🗑 Delete</button>
        </div>
        <div class="status-actions" style="padding-top:0">
          <button class="btn btn-ghost btn-sm" id="btn-trace">Trace: ${piston.trace ? 'ON' : 'OFF'}</button>
          <button class="btn btn-ghost btn-sm" id="btn-notify">⚠ Notify: ${piston.notify ? 'ON' : 'OFF'}</button>
        </div>
      </div>

      <!-- Quick Facts -->
      <div class="status-section">
        <div class="status-section-header">Quick Facts</div>
        <div class="status-section-body">
          <div class="quick-facts">
            <div>
              <div class="fact-label">Compile target</div>
              <div class="fact-value">
                <span class="compile-target-badge ${targetClass}">${_esc(target)}</span>
              </div>
            </div>
            <div>
              <div class="fact-label">Last ran</div>
              <div class="fact-value">${_esc(piston.last_ran ? _formatTime(piston.last_ran) : 'Never')}</div>
            </div>
            <div>
              <div class="fact-label">Mode</div>
              <div class="fact-value">${_esc(piston.mode || 'single')}</div>
            </div>
            <div>
              <div class="fact-label">Triggers</div>
              <div class="fact-value">${(piston.triggers || []).length}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Piston Script (read-only) -->
      <div class="status-section">
        <div class="status-section-header">Piston Script (read-only)</div>
        <div class="script-panel" id="script-panel">
          ${renderScript(piston)}
        </div>
      </div>

      <!-- Log -->
      <div class="status-section">
        <div class="status-section-header">
          Log
          <div style="margin-left:auto; display:flex; gap:8px; align-items:center">
            <select id="log-level-select" style="font-size:11px; padding:2px 6px">
              <option value="full">Full</option>
              <option value="minimal">Minimal</option>
              <option value="none">None</option>
            </select>
            <button class="btn btn-ghost btn-sm" id="btn-clear-log">Clear Log</button>
          </div>
        </div>
        <div class="log-panel" id="log-panel">
          ${_renderLog(piston.log || [])}
        </div>
      </div>

      <!-- Variables from last run -->
      <div class="status-section" id="variables-section" style="display:${(piston.last_variables && Object.keys(piston.last_variables).length) ? 'block' : 'none'}">
        <div class="status-section-header">Variables (last run)</div>
        <div class="status-section-body">
          ${_renderVariables(piston.last_variables || {})}
        </div>
      </div>
    `;

    _wireButtons(piston);
    _renderValidation(piston);
    _renderDeployNotice(piston);
  }

  // ── Script rendering ─────────────────────────────────────
  function renderScript(piston) {
    const actions = piston.statements || [];
    const lines = [];
    let stmtNum = 1;

    lines.push(_scriptLine(null, '<span class="kw">execute</span>'));

    stmtNum = _renderScriptNodes(actions, lines, stmtNum, 1);

    lines.push(_scriptLine(null, '<span class="kw">end execute;</span>'));

    if (lines.length <= 2) {
      return '<div style="color:var(--text-muted); font-size:12px; font-style:italic">No actions defined.</div>';
    }

    return lines.join('');
  }

  function _renderScriptNodes(nodes, lines, stmtNum, depth) {
    const pad = `indent-${Math.min(depth, 5)}`;

    nodes.forEach(node => {
      const type = node.type;

      if (type === 'if') {
        lines.push(_scriptLine(stmtNum++, `<span class="${pad}"><span class="kw">if</span></span>`));
        (node.conditions || []).forEach(c => {
          lines.push(_scriptLine(stmtNum++, `<span class="indent-${Math.min(depth+1,5)}">${_esc(_conditionText(c))}</span>`));
        });
        lines.push(_scriptLine(null, `<span class="${pad}"><span class="kw">then</span></span>`));
        stmtNum = _renderScriptNodes(node.then || [], lines, stmtNum, depth + 1);
        if (node.else?.length) {
          lines.push(_scriptLine(null, `<span class="${pad}"><span class="kw">else</span></span>`));
          stmtNum = _renderScriptNodes(node.else, lines, stmtNum, depth + 1);
        }
        lines.push(_scriptLine(null, `<span class="${pad}"><span class="kw">end if;</span></span>`));

      } else if (type === 'action') {
        lines.push(_scriptLine(stmtNum++, `<span class="${pad}"><span class="kw">with</span></span>`));
        (node.devices || []).forEach(d => {
          lines.push(_scriptLine(null, `<span class="indent-${Math.min(depth+1,5)}">(${_esc(d)})</span>`));
        });
        lines.push(_scriptLine(null, `<span class="${pad}"><span class="kw">do</span></span>`));
        stmtNum = _renderScriptNodes(node.tasks || [], lines, stmtNum, depth + 1);
        lines.push(_scriptLine(null, `<span class="${pad}"><span class="kw">end with;</span></span>`));

      } else if (type === 'repeat') {
        lines.push(_scriptLine(stmtNum++, `<span class="${pad}"><span class="kw">repeat</span></span>`));
        lines.push(_scriptLine(null, `<span class="${pad}"><span class="kw">do</span></span>`));
        stmtNum = _renderScriptNodes(node.statements || [], lines, stmtNum, depth + 1);
        lines.push(_scriptLine(null, `<span class="${pad}"><span class="kw">until</span></span>`));
        (node.until_conditions || []).forEach(c => {
          lines.push(_scriptLine(null, `<span class="indent-${Math.min(depth+1,5)}">${_esc(_conditionText(c))}</span>`));
        });
        lines.push(_scriptLine(null, `<span class="${pad}"><span class="kw">end repeat;</span></span>`));

      } else if (type === 'for_each') {
        const varName = node.variable || '$item';
        const listName = node.list_role || '';
        lines.push(_scriptLine(stmtNum++, `<span class="${pad}"><span class="kw">for each</span> (${_esc(varName)} in {${_esc(listName)}})</span>`));
        lines.push(_scriptLine(null, `<span class="${pad}"><span class="kw">do</span></span>`));
        stmtNum = _renderScriptNodes(node.statements || [], lines, stmtNum, depth + 1);
        lines.push(_scriptLine(null, `<span class="${pad}"><span class="kw">end for each;</span></span>`));

      } else if (type === 'while') {
        lines.push(_scriptLine(stmtNum++, `<span class="${pad}"><span class="kw">while</span></span>`));
        stmtNum = _renderScriptNodes(node.statements || [], lines, stmtNum, depth + 1);
        lines.push(_scriptLine(null, `<span class="${pad}"><span class="kw">end while;</span></span>`));

      } else if (type === 'do') {
        lines.push(_scriptLine(stmtNum++, `<span class="${pad}"><span class="kw">do</span></span>`));
        stmtNum = _renderScriptNodes(node.statements || [], lines, stmtNum, depth + 1);
        lines.push(_scriptLine(null, `<span class="${pad}"><span class="kw">end do;</span></span>`));

      } else if (type === 'wait') {
        const waitText = _waitText(node);
        const tooltip = node.wait_type === 'time'
          ? `<span class="wait-tooltip-trigger"><span class="wait-info-icon">ⓘ</span>
               <span class="wait-tooltip">If this piston reaches this step after the target time has already passed today, it will wait until tomorrow. Make sure this step is always reached before the target time.</span>
             </span>` : '';
        lines.push(_scriptLine(stmtNum++, `<span class="${pad}">${_esc(waitText)}${tooltip};</span>`));

      } else if (type === 'action') {
        const task = (node.tasks || [])[0] || {};
        const desc = node.description || task.command || 'call service';
        lines.push(_scriptLine(stmtNum++, `<span class="${pad}">${_esc(desc)};</span>`));

      } else if (type === 'set_variable') {
        lines.push(_scriptLine(stmtNum++, `<span class="${pad}">Set ${_esc(node.variable || '')} = ${_esc(String(node.value?.data ?? node.value ?? ''))}</span>`));

      } else if (type === 'log_message') {
        lines.push(_scriptLine(stmtNum++, `<span class="${pad}">Log: ${_esc(node.message?.data || node.message || '')}</span>`));

      } else if (type === 'exit') {
        lines.push(_scriptLine(stmtNum++, `<span class="${pad}"><span class="kw">exit</span></span>`));

      } else {
        // Unknown node type — show type as fallback
        lines.push(_scriptLine(stmtNum++, `<span class="${pad}">[${_esc(type || 'unknown')}]</span>`));
      }
    });

    return stmtNum;
  }

  function _scriptLine(num, html) {
    const numHtml = num !== null
      ? `<span class="script-line-num">${num}</span>`
      : `<span class="script-line-num"></span>`;
    return `<div class="script-line">${numHtml}<span class="script-line-content">${html}</span></div>`;
  }

  function _conditionText(c) {
    if (!c) return '[condition]';
    const subject = c.subject?.role || c.subject?.type || '';
    const op = c.operator || '';
    const val = c.display_value || '';
    const trigger = c.type === 'trigger' ? ' ⚡' : '';
    return `${subject}${trigger} ${op} ${val}`.trim();
  }

  function _waitText(node) {
    if (node.wait_type === 'duration') {
      return `wait ${node.duration || ''}`;
    }
    if (node.wait_type === 'time') {
      return `wait until ${node.time || ''}`;
    }
    return 'wait';
  }

  // ── Log rendering ────────────────────────────────────────
  function _renderLog(entries) {
    if (!entries || entries.length === 0) {
      return '<div style="color:var(--text-muted); font-size:12px; font-style:italic">No log entries.</div>';
    }
    return entries.slice().reverse().map(e => `
      <div class="log-entry">
        <span class="log-entry-time">${_esc(e.time || '')}</span>
        <span class="log-entry-msg">${_esc(e.message || '')}</span>
        ${e.detail ? `<div class="log-entry-detail">${_esc(e.detail)}</div>` : ''}
      </div>
    `).join('');
  }

  function _renderVariables(vars) {
    if (!vars || Object.keys(vars).length === 0) return '';
    return Object.entries(vars).map(([k, v]) => `
      <div class="global-row">
        <div class="global-name">${_esc(k)}</div>
        <div class="global-value">${_esc(String(v))}</div>
      </div>
    `).join('');
  }

  // ── Validation and deploy notices ────────────────────────
  function _renderValidation(piston) {
    const el = document.getElementById('validation-banner');
    if (!el) return;

    const warnings = piston.compile_check?.warnings || [];
    const errors = piston.compile_check?.errors || [];
    const hasNoTriggers = !(piston.triggers?.length);

    const items = [];
    if (hasNoTriggers) items.push({ type: 'warn', msg: '⚠ This piston has no triggers. It will never run automatically.' });
    errors.forEach(e => items.push({ type: 'error', msg: `⚠ ${e}` }));
    warnings.forEach(w => items.push({ type: 'warn', msg: `⚠ ${w}` }));

    el.innerHTML = items.map(i =>
      `<div class="banner banner-${i.type === 'error' ? 'error' : 'warn'}">${_esc(i.msg)}</div>`
    ).join('');
  }

  function _renderDeployNotice(piston) {
    const el = document.getElementById('deploy-notice');
    if (!el) return;
    if (piston.stale) {
      el.innerHTML = `<div class="banner banner-warn">Unsaved changes — deploy to update HA.</div>`;
    } else if (!piston.deployed) {
      el.innerHTML = `<div class="banner banner-info">This piston has not been deployed to HA yet.</div>`;
    }
  }

  // ── Button wiring ────────────────────────────────────────
  function _wireButtons(piston) {
    document.getElementById('status-back')?.addEventListener('click', () => {
      App.navigate('list');
    });

    document.getElementById('btn-edit')?.addEventListener('click', () => {
      App.navigate('editor', { pistonId: piston.id });
    });

    document.getElementById('btn-test')?.addEventListener('click', () => {
      Dialog.confirm({
        title: 'Live Fire ⚠',
        message: 'This will execute real actions on your devices. Are you sure?',
        buttons: [
          { label: 'Yes, run it', value: 'yes', primary: true },
          { label: 'Cancel', value: 'cancel' },
        ],
        onClose: async (choice) => {
          if (choice === 'yes') {
            try {
              await API.compilePiston(piston.id);
              // Full test endpoint wired to deploy — placeholder until test endpoint is defined
              _showNotice('Piston fired. Check Home Assistant for results.', 'info');
            } catch (e) {
              _showNotice(`Test failed: ${e.message}`, 'error');
            }
          }
        },
      });
    });

    document.getElementById('btn-snapshot')?.addEventListener('click', () => {
      _exportPiston(piston, 'snapshot');
    });

    document.getElementById('btn-backup')?.addEventListener('click', () => {
      _exportPiston(piston, 'backup');
    });

    document.getElementById('btn-duplicate')?.addEventListener('click', async () => {
      try {
        const copy = JSON.parse(JSON.stringify(piston));
        delete copy.id;
        copy.name = (copy.name || 'Untitled') + ' (copy)';
        copy.deployed = false;
        copy.stale = false;
        const saved = await API.createPiston(copy);
        App.navigate('status', { pistonId: saved.id });
      } catch (e) {
        _showNotice(`Could not duplicate: ${e.message}`, 'error');
      }
    });

    document.getElementById('btn-delete')?.addEventListener('click', () => {
      Dialog.confirm({
        title: 'Delete piston?',
        message: `"${piston.name}" will be permanently deleted. Compiled files in HA are NOT removed automatically — you will need to remove them manually or via the companion.`,
        buttons: [
          { label: 'Delete', value: 'delete', danger: true },
          { label: 'Cancel', value: 'cancel' },
        ],
        onClose: async (choice) => {
          if (choice === 'delete') {
            try {
              await API.deletePiston(piston.id);
              App.navigate('list');
            } catch (e) {
              _showNotice(`Could not delete: ${e.message}`, 'error');
            }
          }
        },
      });
    });

    document.getElementById('status-toggle-enabled')?.addEventListener('click', async () => {
      try {
        const full = await API.getPiston(piston.id);
        full.enabled = !full.enabled;
        await API.savePiston(piston.id, full);
        load(piston.id);
      } catch (e) {
        _showNotice(`Could not update piston: ${e.message}`, 'error');
      }
    });

    document.getElementById('btn-trace')?.addEventListener('click', async () => {
      try {
        const full = await API.getPiston(piston.id);
        full.trace = !full.trace;
        await API.savePiston(piston.id, full);
        load(piston.id);
      } catch (e) {
        _showNotice(`Could not update trace setting: ${e.message}`, 'error');
      }
    });

    document.getElementById('btn-notify')?.addEventListener('click', async () => {
      try {
        const full = await API.getPiston(piston.id);
        full.notify = !full.notify;
        await API.savePiston(piston.id, full);
        load(piston.id);
      } catch (e) {
        _showNotice(`Could not update notify setting: ${e.message}`, 'error');
      }
    });

    document.getElementById('btn-clear-log')?.addEventListener('click', async () => {
      Dialog.confirm({
        title: 'Clear log?',
        message: 'All log entries for this piston will be cleared.',
        buttons: [
          { label: 'Clear', value: 'clear', danger: true },
          { label: 'Cancel', value: 'cancel' },
        ],
        onClose: async (choice) => {
          if (choice === 'clear') {
            try {
              const full = await API.getPiston(piston.id);
              full.log = [];
              await API.savePiston(piston.id, full);
              document.getElementById('log-panel').innerHTML = _renderLog([]);
            } catch (e) {
              _showNotice(`Could not clear log: ${e.message}`, 'error');
            }
          }
        },
      });
    });

    // Folder reassignment
    document.getElementById('status-folder-select')?.addEventListener('change', async (e) => {
      const newFolder = e.target.value;
      try {
        const full = await API.getPiston(piston.id);
        full.folder = newFolder;
        await API.savePiston(piston.id, full);
        _piston = full;
      } catch (err) {
        _showNotice(`Could not update folder: ${err.message}`, 'error');
      }
    });
  }

  // ── WebSocket messages ───────────────────────────────────
  function onWsMessage(msg) {
    if (!_piston) return;
    const logPanel = document.getElementById('log-panel');
    if (!logPanel) return;

    if (msg.type === 'run_complete' && msg.piston_id === _piston.id) {
      const entry = {
        time: new Date().toLocaleTimeString('en-US', { hour12: false }),
        message: msg.success ? 'Run completed ✅' : 'Run failed ❌',
        detail: msg.detail || '',
      };
      if (!_piston.log) _piston.log = [];
      _piston.log.push(entry);
      logPanel.innerHTML = _renderLog(_piston.log);
    }
  }

  // ── Export ───────────────────────────────────────────────
  function _exportPiston(piston, mode) {
    const copy = JSON.parse(JSON.stringify(piston));

    if (mode === 'snapshot') {
      // Anonymize: keep device_map role keys but strip entity IDs (empty arrays per spec)
      if (copy.device_map) {
        Object.keys(copy.device_map).forEach(role => { copy.device_map[role] = []; });
      }
      delete copy.device_map_meta;
      delete copy.id;
      delete copy.log;
      copy._export = 'snapshot';
    } else {
      copy._export = 'backup';
    }

    const json = JSON.stringify(copy, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${_slugify(piston.name || 'piston')}_${mode}.piston`;
    a.click();
    URL.revokeObjectURL(url);
  }

  // ── Helpers ──────────────────────────────────────────────
  function _esc(str) {
    return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _formatTime(iso) {
    try { return new Date(iso).toLocaleTimeString('en-US', { hour12: false }); }
    catch { return iso; }
  }

  function _slugify(str) {
    return str.toLowerCase().replace(/[^a-z0-9]+/g, '_').slice(0, 50);
  }

  function _folderOptions(current) {
    // Folders extracted from current piston list
    const folders = ['', ...new Set(
      (App.state.pistons || [])
        .map(p => p.folder)
        .filter(f => f && f.trim())
    )].sort();

    return folders.map(f => {
      const label = f || 'Uncategorized';
      const selected = f === (current || '') ? 'selected' : '';
      return `<option value="${_esc(f)}" ${selected}>${_esc(label)}</option>`;
    }).join('');
  }

  function _showNotice(msg, type) {
    const el = document.getElementById('validation-banner');
    if (!el) return;
    el.innerHTML = `<div class="banner banner-${type === 'error' ? 'error' : 'info'}">${_esc(msg)}</div>`;
    setTimeout(() => { if (el) el.innerHTML = ''; }, 6000);
  }

  return { load, onWsMessage };

})();
