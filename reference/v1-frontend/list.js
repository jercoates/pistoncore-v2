// pistoncore/frontend/js/list.js
//
// Page 1 — Piston List
// The home screen. Loads all pistons, groups by folder, renders rows.
// Handles search, new piston, import, folder creation.
//
// Session 45 (W-S6) — GAP-S43-1: Placeholder entity ID standard
// Import unmapped filter now treats entity IDs starting with "__placeholder_"
// as unmapped, same as empty arrays. AI-generated pistons should use
// __placeholder_<domain>__ (e.g. "__placeholder_light__") instead of
// invented entity IDs so the role mapping dialog appears on import.

const ListPage = (() => {

  const container = document.getElementById('page-list');

  // ── Render ───────────────────────────────────────────────
  async function load() {
    renderShell();
    await refresh();
  }

  function renderShell() {
    if (!container) return;
    container.innerHTML = `
      <div class="list-header">
        <h1>PistonCore</h1>
        <div class="header-spacer"></div>
        <div class="list-header-actions">
          <button class="btn btn-ghost btn-sm" id="btn-globals">⚙ Globals</button>
          <button class="btn btn-ghost btn-sm" id="btn-ai-prompt">📋 Copy AI Prompt</button>
          <button class="btn btn-primary btn-sm" id="btn-new-piston">+ New</button>
        </div>
      </div>

      <div class="list-search">
        <input type="text" id="piston-search" placeholder="Search pistons..." autocomplete="off" />
      </div>

      <div id="piston-list-body">
        <div class="wizard-loading"><div class="spinner"></div> Loading pistons...</div>
      </div>

      <div class="list-footer">
        <button class="btn btn-ghost btn-sm" id="btn-new-folder">+ New Folder</button>
        <button class="btn btn-ghost btn-sm" id="btn-import">Import</button>
      </div>

      <div class="mode-notice">
        PistonCore manages automations in its own subfolder.
        Automations created directly in Home Assistant are not visible or managed here.
      </div>
    `;

    // Wire buttons
    document.getElementById('btn-new-piston')?.addEventListener('click', createNewPiston);
    document.getElementById('btn-new-folder')?.addEventListener('click', showNewFolderInput);
    document.getElementById('btn-import')?.addEventListener('click', showImportDialog);
    document.getElementById('btn-globals')?.addEventListener('click', () => GlobalsDrawer.open());
    document.getElementById('btn-ai-prompt')?.addEventListener('click', copyAIPrompt);

    // Search
    let _searchTimer = null;
    document.getElementById('piston-search')?.addEventListener('input', (e) => {
      clearTimeout(_searchTimer);
      _searchTimer = setTimeout(() => renderList(e.target.value.trim()), 200);
    });
  }

  let _allPistons = [];

  async function refresh() {
    _allPistons = await App.loadPistons();
    renderList('');
  }

  // ── List rendering ────────────────────────────────────────
  function renderList(searchQuery) {
    const body = document.getElementById('piston-list-body');
    if (!body) return;

    let pistons = _allPistons;

    // Filter by search
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      pistons = pistons.filter(p =>
        (p.name || '').toLowerCase().includes(q) ||
        (p.folder || '').toLowerCase().includes(q)
      );
    }

    if (pistons.length === 0 && _allPistons.length === 0) {
      body.innerHTML = `
        <div style="text-align:center; padding: 48px 0; color: var(--text-muted); font-size:13px">
          No pistons yet.<br><br>
          <button class="btn btn-primary" onclick="ListPage.createNewPiston()">+ Create your first piston</button>
        </div>
      `;
      return;
    }

    if (pistons.length === 0) {
      body.innerHTML = `<div style="color:var(--text-muted); font-size:13px; padding: 16px 0">No pistons match your search.</div>`;
      return;
    }

    // Group by folder
    const folders = _groupByFolder(pistons);
    const folderNames = Object.keys(folders).sort((a, b) => {
      if (a === 'Uncategorized') return 1;
      if (b === 'Uncategorized') return -1;
      return a.localeCompare(b);
    });

    body.innerHTML = folderNames.map(folder => {
      const items = folders[folder];
      return `
        <div class="folder-section">
          <div class="folder-header">
            <span class="folder-name">${_esc(folder)}</span>
            <span class="folder-count">(${items.length})</span>
            <div class="folder-divider"></div>
          </div>
          ${items.map(renderPistonRow).join('')}
        </div>
      `;
    }).join('');

    // Wire row clicks
    body.querySelectorAll('.piston-row').forEach(row => {
      row.addEventListener('click', (e) => {
        if (e.target.closest('.piston-pause-btn')) return;
        const id = row.dataset.pistonId;
        App.navigate('status', { pistonId: id });
      });

      row.querySelector('.piston-pause-btn')?.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = row.dataset.pistonId;
        togglePause(id);
      });
    });
  }

  function renderPistonRow(piston) {
    const enabled = piston.enabled !== false;
    const result = _resultIcon(piston.last_result);
    const time = piston.last_ran ? _formatTime(piston.last_ran) : 'Never';
    const pauseLabel = enabled ? 'Pause' : 'Resume';

    return `
      <div class="piston-row" data-piston-id="${_esc(piston.id)}">
        <div class="piston-enabled-dot ${enabled ? 'enabled' : 'disabled'}"></div>
        <div class="piston-name">${_esc(piston.name || 'Untitled')}</div>
        <div class="piston-result">${result}</div>
        <div class="piston-time">${_esc(time)}</div>
        <button class="piston-pause-btn btn-ghost">${pauseLabel}</button>
      </div>
    `;
  }

  // ── Folder grouping ───────────────────────────────────────
  function _groupByFolder(pistons) {
    const folders = {};
    pistons.forEach(p => {
      const folder = p.folder && p.folder.trim() ? p.folder.trim() : 'Uncategorized';
      if (!folders[folder]) folders[folder] = [];
      folders[folder].push(p);
    });
    return folders;
  }

  // ── Actions ──────────────────────────────────────────────
  async function createNewPiston() {
    NewPistonModal.open();
  }

  async function togglePause(pistonId) {
    const piston = _allPistons.find(p => p.id === pistonId);
    if (!piston) return;
    try {
      const full = await API.getPiston(pistonId);
      full.enabled = !full.enabled;
      await API.savePiston(pistonId, full);
      piston.enabled = full.enabled;
      renderList(document.getElementById('piston-search')?.value || '');
    } catch (e) {
      showBanner('error', `Could not update piston: ${e.message}`);
    }
  }

  function showNewFolderInput() {
    const body = document.getElementById('piston-list-body');
    if (!body) return;
    // Remove any existing input
    document.getElementById('new-folder-row')?.remove();

    const row = document.createElement('div');
    row.id = 'new-folder-row';
    row.className = 'new-folder-row';
    row.innerHTML = `
      <input type="text" id="new-folder-input" placeholder="Folder name..." maxlength="64" autofocus />
      <button class="btn btn-sm btn-primary" id="new-folder-confirm">Create</button>
      <button class="btn btn-sm" id="new-folder-cancel">Cancel</button>
    `;

    const footer = container.querySelector('.list-footer');
    footer?.before(row);

    const input = document.getElementById('new-folder-input');
    input?.focus();

    document.getElementById('new-folder-confirm')?.addEventListener('click', () => {
      const name = input?.value.trim();
      if (name) {
        // Folder created — just shows in the list when a piston is assigned to it
        // Folders don't exist independently; they appear when pistons are in them
        row.remove();
        showBanner('info', `Folder "${name}" will appear when you assign a piston to it.`);
      }
    });

    document.getElementById('new-folder-cancel')?.addEventListener('click', () => {
      row.remove();
    });

    input?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') document.getElementById('new-folder-confirm')?.click();
      if (e.key === 'Escape') document.getElementById('new-folder-cancel')?.click();
    });
  }

  function showImportDialog() {
    _showImportPasteModal();
  }

  // ── Import flow — "Rebuild piston items" (DESIGN.md Section 6.3) ─────────
  //
  // Step 1: Paste modal — user pastes Snapshot JSON
  // Step 2: Role mapping modal — one dropdown per unmapped role
  //         Matches WebCoRE "Rebuild piston items" dialog exactly.
  //         Ignore → saves piston as-is, opens editor.
  //         Continue → saves populated device_map, opens editor.
  //
  // Unmapped detection (GAP-S43-1 fix):
  //   A role is considered unmapped if its device_map value is:
  //   - An empty array []
  //   - An array containing only placeholder entity IDs (strings starting with "__placeholder_")
  //   AI-generated pistons use __placeholder_<domain>__ format (e.g. "__placeholder_light__")
  //   so the role mapping dialog correctly fires on import.

  // Returns true if a device_map value array is unmapped (empty or all placeholders).
  function _isUnmapped(ids) {
    if (!Array.isArray(ids) || ids.length === 0) return true;
    return ids.every(id => typeof id === 'string' && id.startsWith('__placeholder_'));
  }

  function _showImportPasteModal() {
    document.getElementById('pc-import-modal')?.remove();
    document.getElementById('pc-import-backdrop')?.remove();

    const backdrop = document.createElement('div');
    backdrop.id = 'pc-import-backdrop';
    backdrop.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:2000;display:flex;align-items:center;justify-content:center';

    const modal = document.createElement('div');
    modal.id = 'pc-import-modal';
    modal.style.cssText = 'background:var(--bg-raised,#1e2430);border:1px solid var(--border-subtle,#333);border-radius:6px;padding:24px;width:540px;max-width:95vw;max-height:90vh;display:flex;flex-direction:column;gap:12px;z-index:2001';
    modal.innerHTML = `
      <div style="font-size:16px;font-weight:600;color:var(--text-primary)">Import piston</div>
      <div style="font-size:13px;color:var(--text-muted)">Paste the piston JSON below. This can be a Snapshot from the community, an AI-generated piston, or a backup.</div>
      <textarea id="pc-import-json" style="flex:1;min-height:220px;background:var(--bg-input,#12161f);border:1px solid var(--border-subtle,#333);border-radius:4px;color:var(--text-primary);font-family:monospace;font-size:12px;padding:10px;resize:vertical" placeholder='{ "name": "My Piston", "statements": [...] }'></textarea>
      <div id="pc-import-error" style="color:var(--red,#e74c3c);font-size:12px;display:none"></div>
      <div style="display:flex;justify-content:flex-end;gap:8px">
        <button class="btn btn-ghost btn-sm" id="pc-import-cancel">Cancel</button>
        <button class="btn btn-primary btn-sm" id="pc-import-next">Next →</button>
      </div>
    `;

    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);

    document.getElementById('pc-import-cancel').addEventListener('click', () => backdrop.remove());
    backdrop.addEventListener('click', e => { if (e.target === backdrop) backdrop.remove(); });

    document.getElementById('pc-import-next').addEventListener('click', async () => {
      const raw = document.getElementById('pc-import-json').value.trim();
      const errEl = document.getElementById('pc-import-error');
      errEl.style.display = 'none';

      let parsed;
      try {
        parsed = JSON.parse(raw);
      } catch {
        errEl.textContent = 'Invalid JSON — check for missing brackets or commas.';
        errEl.style.display = '';
        return;
      }

      if (typeof parsed !== 'object' || Array.isArray(parsed)) {
        errEl.textContent = 'JSON must be a piston object, not an array.';
        errEl.style.display = '';
        return;
      }

      const btn = document.getElementById('pc-import-next');
      btn.textContent = 'Saving...';
      btn.disabled = true;

      let saved;
      try {
        saved = await API.importPiston(parsed);
      } catch(e) {
        errEl.textContent = `Import failed: ${e.message}`;
        errEl.style.display = '';
        btn.textContent = 'Next →';
        btn.disabled = false;
        return;
      }

      backdrop.remove();

      // Unmapped = empty array OR all-placeholder entity IDs
      const unmapped = Object.entries(saved.device_map || {})
        .filter(([, ids]) => _isUnmapped(ids))
        .map(([role]) => role);

      if (unmapped.length > 0) {
        _showRoleMapModal(saved, unmapped);
      } else {
        App.navigate('editor', { pistonId: saved.id });
      }
    });
  }

  function _showRoleMapModal(piston, unmappedRoles) {
    document.getElementById('pc-rolemap-modal')?.remove();
    document.getElementById('pc-rolemap-backdrop')?.remove();

    const backdrop = document.createElement('div');
    backdrop.id = 'pc-rolemap-backdrop';
    backdrop.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:2000;display:flex;align-items:center;justify-content:center';

    const rowsHtml = unmappedRoles.map(role => `
      <div style="margin-bottom:10px">
        <div style="font-size:12px;color:var(--text-muted);margin-bottom:4px">Device: ${_esc(role)}</div>
        <div style="position:relative">
          <input type="text"
            class="pc-role-search"
            data-role="${_esc(role)}"
            placeholder="Nothing selected"
            autocomplete="off"
            style="width:100%;box-sizing:border-box;background:var(--teal,#1abc9c);color:#fff;border:none;border-radius:4px;padding:8px 10px;font-size:13px;cursor:pointer"
            readonly
          />
          <div class="pc-role-dropdown" data-role="${_esc(role)}"
            style="display:none;position:absolute;left:0;right:0;top:100%;background:var(--bg-raised,#1e2430);border:1px solid var(--border-subtle,#333);border-radius:4px;z-index:100;box-shadow:0 4px 16px rgba(0,0,0,.5)">
            <input type="text" class="pc-role-filter" data-role="${_esc(role)}" placeholder="Search..."
              style="width:100%;box-sizing:border-box;background:transparent;border:none;border-bottom:1px solid var(--border-subtle,#333);color:var(--text-primary);padding:8px 10px;font-size:13px;outline:none" />
            <div class="pc-role-list" data-role="${_esc(role)}" style="max-height:220px;overflow-y:auto"></div>
          </div>
        </div>
      </div>
    `).join('');

    const modal = document.createElement('div');
    modal.id = 'pc-rolemap-modal';
    modal.style.cssText = 'background:var(--bg-raised,#1e2430);border:1px solid var(--border-subtle,#333);border-radius:6px;padding:24px;width:540px;max-width:95vw;max-height:90vh;overflow-y:auto;display:flex;flex-direction:column;gap:12px;z-index:2001';
    modal.innerHTML = `
      <div style="font-size:16px;font-weight:600;color:var(--text-primary)">Rebuild piston items</div>
      <div style="font-size:13px;color:var(--text-muted)">This piston uses devices that are not yet mapped to your Home Assistant. Select an equivalent device for each item below. If you skip any items, you will have to fix them by manually editing that statement.</div>
      <div id="pc-rolemap-rows">${rowsHtml}</div>
      <div style="display:flex;justify-content:space-between;gap:8px;margin-top:4px">
        <button class="btn btn-ghost btn-sm" id="pc-rolemap-ignore">Ignore</button>
        <button class="btn btn-primary btn-sm" id="pc-rolemap-continue">Continue</button>
      </div>
    `;

    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);

    const selections = {};
    API.getDevices().then(data => {
      unmappedRoles.forEach(role => _wireRoleRow(role, data, selections));
    }).catch(() => {
      unmappedRoles.forEach(role => _wireRoleRow(role, null, selections));
    });

    document.getElementById('pc-rolemap-ignore').addEventListener('click', () => {
      backdrop.remove();
      App.navigate('editor', { pistonId: piston.id });
    });

    document.getElementById('pc-rolemap-continue').addEventListener('click', async () => {
      const updatedMap = { ...(piston.device_map || {}) };
      for (const [role, entityId] of Object.entries(selections)) {
        if (entityId) updatedMap[role] = [entityId];
      }
      const btn = document.getElementById('pc-rolemap-continue');
      btn.textContent = 'Saving...';
      btn.disabled = true;
      try {
        await API.savePiston(piston.id, { ...piston, device_map: updatedMap });
      } catch(e) {
        // Non-fatal — still open the editor
      }
      backdrop.remove();
      App.navigate('editor', { pistonId: piston.id });
    });
  }

  function _wireRoleRow(role, deviceData, selections) {
    const input = document.querySelector(`.pc-role-search[data-role="${CSS.escape(role)}"]`);
    const dropdown = document.querySelector(`.pc-role-dropdown[data-role="${CSS.escape(role)}"]`);
    const filter = document.querySelector(`.pc-role-filter[data-role="${CSS.escape(role)}"]`);
    const list = document.querySelector(`.pc-role-list[data-role="${CSS.escape(role)}"]`);
    if (!input || !dropdown || !filter || !list) return;

    const renderList = (q) => {
      const lq = (q || '').toLowerCase();
      const devices = (deviceData || []).filter(d =>
        !lq || d.friendly_name.toLowerCase().includes(lq) || d.entity_id.toLowerCase().includes(lq)
      );
      if (!devices.length) {
        list.innerHTML = `<div style="padding:8px 10px;font-size:12px;color:var(--text-muted)">No devices found.</div>`;
        return;
      }
      list.innerHTML = devices.slice(0, 150).map(d => `
        <div class="pc-role-option" data-id="${_esc(d.entity_id)}" data-label="${_esc(d.friendly_name)}"
          style="padding:7px 10px;cursor:pointer;font-size:13px;color:var(--text-primary);display:flex;justify-content:space-between;align-items:center">
          <span>${_esc(d.friendly_name)}</span>
          <span style="font-size:10px;color:var(--text-muted)">${_esc(d.entity_id)}</span>
        </div>
      `).join('');
      list.querySelectorAll('.pc-role-option').forEach(row => {
        row.addEventListener('mouseover', () => row.style.background = 'var(--teal,#1abc9c)');
        row.addEventListener('mouseout',  () => row.style.background = '');
        row.addEventListener('click', () => {
          selections[role] = row.dataset.id;
          input.value = `${row.dataset.label} (${row.dataset.id})`;
          dropdown.style.display = 'none';
        });
      });
    };

    input.addEventListener('click', () => {
      dropdown.style.display = dropdown.style.display === 'none' ? '' : 'none';
      if (dropdown.style.display !== 'none') {
        filter.value = '';
        renderList('');
        filter.focus();
      }
    });

    filter.addEventListener('input', e => renderList(e.target.value));

    document.addEventListener('click', e => {
      if (!input.contains(e.target) && !dropdown.contains(e.target)) {
        dropdown.style.display = 'none';
      }
    });
  }

  function copyAIPrompt() {
    // Placeholder — AI Prompt feature redesign pending (DESIGN.md Section 11)
    const msg = 'AI Prompt feature is being redesigned. Check DESIGN.md Section 11.';
    try {
      navigator.clipboard.writeText(msg);
      showBanner('info', 'AI Prompt copied to clipboard.');
    } catch {
      showBanner('info', msg);
    }
  }

  // ── Helpers ──────────────────────────────────────────────
  function _resultIcon(result) {
    if (result === true  || result === 'true'  || result === 'ok')    return '✅';
    if (result === false || result === 'false' || result === 'error') return '❌';
    return '—';
  }

  function _formatTime(iso) {
    try {
      const d = new Date(iso);
      return d.toLocaleTimeString('en-US', { hour12: false });
    } catch { return iso; }
  }

  function _esc(str) {
    return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function showBanner(type, message) {
    const body = document.getElementById('piston-list-body');
    if (!body) return;
    const existing = container.querySelector('.page-banner');
    existing?.remove();
    const b = document.createElement('div');
    b.className = `banner banner-${type} page-banner`;
    b.textContent = message;
    container.querySelector('.list-header')?.after(b);
    setTimeout(() => b.remove(), 5000);
  }

  return { load, refresh, createNewPiston };

})();
