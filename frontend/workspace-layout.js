/* Panel preferences only: never sends train, simulation, or hardware commands.
 * Integration: load this file before app.js; call create once and setPage after
 * the application has updated page visibility. See the public API below.
 */
(function (global) {
  'use strict';
  const PANELS = {
    'layout-info': ['Layout information', '#layout-info-panel'],
    'node-graph': ['Node graph', '#layout-panel'],
    systematic: ['Schematic track view', '#systematic-panel'],
    trains: ['Train overview', '#train-panel'],
    'train-profile': ['Train profile', '#train-editor-panel'],
    assembler: ['Train assembler', '#assembler-panel'],
    'rolling-stock': ['Rolling stock inventory', '#rolling-stock-panel'],
    programming: ['DCC programming', '#programming-panel'],
    calibration: ['Motion calibration', '#calibration-panel'],
    timetable: ['Timetable', '#timetable-panel'],
    scans: ['3D track viewer', '#scan-panel'],
    'control-center': ['Control center', '.control-panel'],
    'selected-train': ['Selected train', '.selected-train-panel'],
    simulation: ['Simulation', '.simulation-panel'],
    'connection-health': ['Connection health', '.health-panel']
  };
  const PAGE_LABELS = { dispatch: 'Dispatch', layout: 'Layout editor', trains: 'Trains', timetable: 'Timetable', scans: '3D scans' };
  const MAIN = {
    dispatch: ['layout-info', 'node-graph', 'systematic', 'trains'],
    layout: ['layout-info', 'node-graph', 'systematic'],
    trains: ['trains', 'train-profile', 'rolling-stock', 'programming', 'calibration', 'assembler'], timetable: ['timetable'], scans: ['scans']
  };
  const SIDEBAR = ['control-center', 'selected-train', 'simulation', 'connection-health'];
  const copy = value => JSON.parse(JSON.stringify(value));
  function defaults() {
    return { pages: Object.fromEntries(Object.entries(MAIN).map(([page, order]) => [page, {
      order: [...order], sidebar_order: ['dispatch', 'trains'].includes(page) ? [...SIDEBAR] : [], sidebar_side: 'left'
    }])) };
  }
  function normalize(value) {
    const result = defaults();
    for (const [page, preference] of Object.entries(result.pages)) {
      const candidate = value?.pages?.[page];
      if (!candidate) continue;
      for (const key of ['order', 'sidebar_order']) {
        const order = candidate[key];
        if (Array.isArray(order) && order.length === preference[key].length && new Set(order).size === order.length
            && order.every(id => preference[key].includes(id))) preference[key] = [...order];
      }
      if (['left', 'right'].includes(candidate.sidebar_side)) preference.sidebar_side = candidate.sidebar_side;
    }
    return result;
  }
  async function defaultRequest(url, options) {
    const response = await fetch(url, options);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `Controller returned ${response.status}`);
    return payload;
  }

  function create({ root = document, request = defaultRequest } = {}) {
    const existing = root.querySelector('#workspace-layout-settings');
    if (existing) throw new Error('WorkspaceLayout.create must only be called once');
    const doc = root.ownerDocument || root;
    const workspace = root.querySelector('.workspace');
    const sidebar = root.querySelector('.sidebar');
    const dashboard = root.querySelector('.dashboard');
    const host = root.querySelector('#settings-page');
    if (!workspace || !sidebar || !dashboard || !host) throw new Error('Workspace layout requires the controller page DOM');
    const nodes = Object.fromEntries(Object.entries(PANELS).map(([id, [, selector]]) => [id, root.querySelector(selector)]));
    let saved = defaults(), draft = defaults(), activePage = 'dispatch', editingPage = 'dispatch';
    let loaded = false, dirty = false, busy = false, disposed = false;
    const section = doc.createElement('section');
    section.id = 'workspace-layout-settings';
    section.className = 'settings-section workspace-layout-settings';
    section.setAttribute('aria-labelledby', 'workspace-layout-heading');
    section.innerHTML = `<div class="settings-section-heading"><h3 id="workspace-layout-heading">Panel arrangement</h3><p>Choose a panel order for each page. Changes preview immediately; save to keep them on this controller.</p></div>
      <div class="settings-row"><div><label for="workspace-layout-page">Page to arrange</label><p class="settings-help">Only panels available on this page are listed. The schematic view appears when selected.</p></div><div class="settings-control"><select id="workspace-layout-page"></select></div></div>
      <div class="settings-row" data-sidebar-placement><div><label for="workspace-layout-side">Control panels position</label><p class="settings-help">On narrow screens, panels stack in reading order.</p></div><div class="settings-control"><select id="workspace-layout-side"><option value="left">Left of workspace</option><option value="right">Right of workspace</option></select></div></div>
      <h4>Main panels — top to bottom</h4><ol class="workspace-panel-order" data-panel-list="order"></ol>
      <div data-sidebar-order><h4>Control panels — top to bottom</h4><ol class="workspace-panel-order" data-panel-list="sidebar_order"></ol></div>
      <div class="workspace-layout-actions"><button type="button" class="button button-soft" data-layout-action="reset-page">Reset this page</button><button type="button" class="button button-soft" data-layout-action="reset-all">Reset all pages</button><button type="button" class="button button-soft" data-layout-action="discard">Discard arrangement changes</button><button type="button" class="button button-primary" data-layout-action="save">Save arrangement</button></div>
      <p id="workspace-layout-status" class="settings-status" role="status" aria-live="polite">Loading panel arrangement…</p><button type="button" class="button button-soft" data-layout-retry hidden>Retry loading arrangement</button>`;
    // Outside the application's settings form: independent draft/save lifecycle.
    host.insertBefore(section, root.querySelector('.settings-upload'));
    const query = selector => section.querySelector(selector);
    const status = query('#workspace-layout-status');
    for (const [page, label] of Object.entries(PAGE_LABELS)) {
      const option = doc.createElement('option'); option.value = page; option.textContent = label;
      query('#workspace-layout-page').append(option);
    }
    // Flatten the two old panel groups, leaving their containers in place for
    // existing visibility code. Real nodes keep all state and event listeners.
    for (const id of new Set(Object.values(MAIN).flat())) if (nodes[id]) workspace.append(nodes[id]);
    dashboard.classList.add('workspace-layout-enabled');
    function reorder(parent, items, anchor = null) {
      for (const item of items) {
        if (!item) continue;
        const next = anchor ? anchor.nextSibling : parent.firstChild;
        if (next !== item) parent.insertBefore(item, next);
        anchor = item;
      }
    }
    function setPage(page) {
      activePage = page;
      const preference = draft.pages[page];
      if (!preference || disposed) return;
      dashboard.dataset.controlSide = preference.sidebar_side;
      // DOM order follows visual order, including keyboard navigation.
      reorder(dashboard, preference.sidebar_side === 'right' ? [workspace, sidebar] : [sidebar, workspace]);
      reorder(workspace, preference.order.map(id => nodes[id]), workspace.querySelector('.workspace-heading'));
      reorder(sidebar, preference.sidebar_order.map(id => nodes[id]));
      // This panel previously inherited visibility from .lower-grid.
      nodes.trains?.classList.toggle('is-hidden', !MAIN[page].includes('trains'));
    }
    function renderControls(focusKey) {
      const preference = draft.pages[editingPage];
      query('#workspace-layout-page').value = editingPage;
      query('#workspace-layout-side').value = preference.sidebar_side;
      query('[data-sidebar-placement]').hidden = !preference.sidebar_order.length;
      query('[data-sidebar-order]').hidden = !preference.sidebar_order.length;
      for (const key of ['order', 'sidebar_order']) {
        const list = query(`[data-panel-list="${key}"]`); list.replaceChildren();
        preference[key].forEach((id, index, order) => {
          const item = doc.createElement('li');
          const label = doc.createElement('span'); label.textContent = `${index + 1}. ${PANELS[id][0]}`; item.append(label);
          for (const [direction, offset] of [['up', -1], ['down', 1]]) {
            const button = doc.createElement('button'); button.type = 'button'; button.className = 'button button-soft';
            button.textContent = direction === 'up' ? 'Move up' : 'Move down';
            button.setAttribute('aria-label', `Move ${PANELS[id][0]} ${direction}`);
            button.dataset.move = String(offset); button.dataset.panel = id; button.dataset.list = key;
            button.dataset.focusKey = `${id}-${direction}`;
            button.disabled = !loaded || busy || index + offset < 0 || index + offset >= order.length;
            item.append(button);
          }
          list.append(item);
        });
      }
      query('#workspace-layout-side').disabled = !loaded || busy;
      query('#workspace-layout-page').disabled = busy;
      section.querySelectorAll('[data-layout-action]').forEach(button => {
        button.disabled = !loaded || busy || (['save', 'discard'].includes(button.dataset.layoutAction) && !dirty);
      });
      if (focusKey) {
        const button = [...section.querySelectorAll('[data-focus-key]')].find(item => item.dataset.focusKey === focusKey);
        if (button && !button.disabled) button.focus();
        else button?.parentElement.querySelector('button:not(:disabled)')?.focus();
      }
    }
    function changed(message = 'Arrangement changed. Save to keep it, or discard to restore the saved arrangement.') {
      dirty = JSON.stringify(draft) !== JSON.stringify(saved);
      status.textContent = message; setPage(activePage); renderControls();
    }
    async function save() {
      if (!loaded || busy || !dirty) return false;
      busy = true; renderControls(); status.textContent = 'Saving panel arrangement…';
      try {
        const payload = await request('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace_layout: draft }) });
        if (!payload?.settings?.workspace_layout) throw new Error('Controller did not confirm panel preferences');
        saved = normalize(payload.settings.workspace_layout); draft = copy(saved); dirty = false;
        status.textContent = 'Panel arrangement saved on this controller.'; setPage(activePage);
        section.dispatchEvent(new CustomEvent('workspace-layout-saved', { bubbles: true, detail: copy(payload.settings) }));
        return true;
      } catch (error) { status.textContent = `Arrangement not saved: ${error.message}. Your changes are still here; try saving again.`; return false; }
      finally { busy = false; renderControls(); }
    }
    function receiveSettings(settings) {
      if (busy || disposed) return;
      saved = normalize(settings?.workspace_layout); loaded = true;
      if (!dirty) { draft = copy(saved); status.textContent = 'Panel arrangement is up to date.'; setPage(activePage); }
      renderControls();
    }
    async function reload() {
      query('[data-layout-retry]').hidden = true;
      try {
        const payload = await request('/api/settings');
        if (!payload?.settings?.workspace_layout) throw new Error('Controller does not provide panel preferences');
        receiveSettings(payload.settings); return true;
      } catch (error) {
        status.textContent = `Panel preferences unavailable: ${error.message}. Retry when the controller is available.`;
        query('[data-layout-retry]').hidden = false; return false;
      }
    }
    section.addEventListener('change', event => {
      if (event.target.id === 'workspace-layout-page') { editingPage = event.target.value; renderControls(); }
      if (event.target.id === 'workspace-layout-side' && loaded && !busy) { draft.pages[editingPage].sidebar_side = event.target.value; changed(); }
    });
    section.addEventListener('click', event => {
      const button = event.target.closest('button'); if (!button || button.disabled || busy) return;
      if (button.hasAttribute('data-layout-retry')) { void reload(); }
      else if (button.dataset.move) {
        const order = draft.pages[editingPage][button.dataset.list], index = order.indexOf(button.dataset.panel), target = index + Number(button.dataset.move);
        if (target < 0 || target >= order.length) return;
        [order[index], order[target]] = [order[target], order[index]];
        changed(`${PANELS[button.dataset.panel][0]} moved to position ${target + 1}. Arrangement not yet saved.`);
        renderControls(button.dataset.focusKey);
      } else if (button.dataset.layoutAction === 'save') { void save(); }
      else if (button.dataset.layoutAction === 'discard') { draft = copy(saved); changed('Arrangement changes discarded.'); }
      else if (button.dataset.layoutAction === 'reset-page') { draft.pages[editingPage] = defaults().pages[editingPage]; changed('Default arrangement restored for this page. Save to keep it.'); }
      else if (button.dataset.layoutAction === 'reset-all') { draft = defaults(); changed('Default arrangements restored for all pages. Save to keep them.'); }
    });
    renderControls();
    const ready = reload();
    return {
      ready, setPage, receiveSettings, reload, save,
      getPreferences: () => copy(draft),
      isDirty: () => dirty,
      // Call only when the entire application is being torn down.
      destroy: () => { disposed = true; section.remove(); }
    };
  }
  const api = { create, defaults, normalize };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.WorkspaceLayout = api;
})(typeof window !== 'undefined' ? window : globalThis);
