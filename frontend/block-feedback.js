/* Physical detector assignments have their own save lifecycle. */
(function (global) {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const upper = value => String(value || '').toUpperCase();
  function create({ request, context, onChange }) {
    const dialog = document.createElement('dialog');
    dialog.id = 'block-feedback-editor';
    dialog.className = 'modal feedback-mapping-modal';
    dialog.setAttribute('aria-labelledby', 'feedback-editor-title');
    dialog.innerHTML = `<form id="block-feedback-form" class="modal-card">
      <div class="modal-heading"><div><p class="eyebrow">BLOCK OCCUPANCY</p><h2 id="feedback-editor-title">Map hardware blocks</h2></div><button type="button" class="icon-button" data-feedback-close aria-label="Close hardware block mapping">×</button></div>
      <div class="modal-body"><p class="feedback-intro">Choose inputs reported by your command station or by detectors connected directly to this computer. Several inputs can share one block; any occupied input makes that block occupied.</p>
      <div class="field-grid"><div class="field"><label for="feedback-system">Detector source</label><select id="feedback-system"></select></div><div class="field"><label for="feedback-block">Layout block</label><select id="feedback-block"></select></div></div>
      <section id="feedback-computer-connection" hidden aria-label="Computer detector connection">
        <h3>Computer bridge connection</h3>
        <p class="editor-note">The bridge receives occupancy and controls assigned track switches. Your command station continues to control trains. The bridge must support the JSON format in the <a href="/computer-feedback.html" target="_blank" rel="noopener">connection guide</a>.</p>
        <div class="field-grid"><div class="field"><label for="feedback-transport">Connection</label><select id="feedback-transport"><option value="serial">USB / serial</option><option value="tcp">Network TCP</option></select></div><div class="field"><label for="feedback-timeout">Reading timeout (seconds)</label><input id="feedback-timeout" type="number" min="0.5" max="60" step="0.5"></div></div>
        <div class="field-grid" id="feedback-serial-fields"><div class="field"><label for="feedback-serial-port">Serial port on this computer</label><input id="feedback-serial-port" placeholder="COM3 or /dev/ttyUSB0"></div><div class="field"><label for="feedback-baudrate">Baud rate</label><input id="feedback-baudrate" type="number" min="1200" max="2000000"></div></div>
        <div class="field-grid" id="feedback-tcp-fields" hidden><div class="field"><label for="feedback-host">Detector host / IP</label><input id="feedback-host" placeholder="192.168.1.50"></div><div class="field"><label for="feedback-port">TCP port</label><input id="feedback-port" type="number" min="1" max="65535"></div></div>
        <div class="feedback-connection-actions"><button type="button" class="button button-soft" id="feedback-connection-save">Save connection</button><button type="button" class="button button-soft" id="feedback-connect">Connect bridge</button><button type="button" class="button button-soft" id="feedback-disconnect">Disconnect bridge</button></div>
        <p class="settings-status" id="feedback-connection-status" role="status" aria-live="polite"></p>
        <p class="editor-note">Saved connections stay disconnected on startup. In simulation you can check incoming readings; they affect physical block protection when a command station is connected.</p>
      </section>
      <p class="editor-note" id="feedback-address-help"></p><p class="feedback-power-note" id="feedback-power-note"></p>
      <div class="feedback-section-heading"><h3>Assigned detector inputs</h3><button type="button" class="button button-soft" id="feedback-add-contact">Add input</button></div>
      <div id="feedback-contact-rows"></div><div id="feedback-inherited-rows"></div>
      <p class="editor-note">Saving applies detector assignments immediately and keeps them on this controller. Track-trigger and startup mappings are shown separately and managed at their source.</p>
      <details class="feedback-overview"><summary>All assignments for this detector source</summary><div id="feedback-overview-rows"></div></details>
      <p id="feedback-save-status" class="settings-status" role="status" aria-live="polite"></p></div>
      <div class="modal-actions"><button type="button" class="button button-soft" id="feedback-discard">Discard edits</button><button type="submit" class="button button-primary" id="feedback-save">Save assignments</button></div>
      </form>`;
    document.body.appendChild(dialog);
    const $ = selector => dialog.querySelector(selector);
    let data = null, dirty = false, connectionDirty = false, busy = false, revision = 0, selectedBlock = '', selectedSystem = '';
    function status(message) { $('#feedback-save-status').textContent = message; }
    function discardAllowed() { return !(dirty || connectionDirty) || window.confirm('Discard unsaved detector edits?'); }
    function close() { if (!busy && discardAllowed()) { dirty = false; dialog.close(); } }
    dialog.querySelector('[data-feedback-close]').addEventListener('click', close);
    dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
    function locked() {
      const state = context();
      return state.physical && state.track_power && (selectedSystem === 'computer' || (state.active_system || data?.active_system) === selectedSystem);
    }
    function updateControls() {
      const powerLocked = locked();
      $('#feedback-system').disabled = busy;
      $('#feedback-block').disabled = busy || !data;
      $('#feedback-save').disabled = busy || !data || !selectedBlock || powerLocked;
      $('#feedback-discard').disabled = busy || !(dirty || connectionDirty);
      $('#feedback-add-contact').disabled = busy || !data || !selectedBlock || powerLocked;
      $('#feedback-power-note').textContent = powerLocked ? 'Switch track power off before changing assignments or the detector connection.' : selectedSystem === 'computer' ? 'Computer detector assignments work with every command station. Missing or stale readings protect their blocks until fresh readings arrive.' : context().physical && (context().active_system || data?.active_system) === selectedSystem ? 'Changes apply to the connected system. Track power must stay off while editing.' : 'You can prepare these assignments now. They become active when this digital system is connected.';
      const computer = context().triggers.computer_feedback || data?.computer_feedback;
      $('#feedback-connect').disabled = busy || powerLocked || connectionDirty || !data || !!computer?.connected;
      $('#feedback-disconnect').disabled = busy || powerLocked || !computer?.connected;
      $('#feedback-connection-save').disabled = busy || !data || !!computer?.connected;
      $('#feedback-computer-connection').querySelectorAll('input, select').forEach(input => { input.disabled = busy || !!computer?.connected; });
      if (computer && selectedSystem === 'computer') $('#feedback-connection-status').textContent = connectionDirty ? 'Unsaved connection settings. Save before connecting.' : computer.connected ? computer.healthy ? `Receiving detector snapshots · ${computer.mapped_contacts} mapped inputs` : `Connected · ${computer.error}` : computer.error || 'Detectors disconnected';
    }
    function showTransport() {
      $('#feedback-serial-fields').hidden = $('#feedback-transport').value !== 'serial';
      $('#feedback-tcp-fields').hidden = $('#feedback-transport').value !== 'tcp';
    }
    function renderConnection() {
      $('#feedback-computer-connection').hidden = selectedSystem !== 'computer';
      const config = data?.computer_feedback?.config;
      if (config) {
        for (const [key, id] of Object.entries({ transport: 'transport', serial_port: 'serial-port', baudrate: 'baudrate', host: 'host', port: 'port', timeout_s: 'timeout' })) $('#feedback-' + id).value = config[key];
      }
      connectionDirty = false; showTransport();
    }
    $('#feedback-computer-connection').addEventListener('input', () => { connectionDirty = true; showTransport(); updateControls(); });
    async function connectionAction(type) {
      if (busy || !data) return;
      const config = { transport: $('#feedback-transport').value, serial_port: $('#feedback-serial-port').value, baudrate: Number($('#feedback-baudrate').value), host: $('#feedback-host').value, port: Number($('#feedback-port').value), timeout_s: Number($('#feedback-timeout').value) };
      busy = true; updateControls(); status('Updating detector connection…');
      try {
        const payload = await request('/api/commands', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type, ...(type === 'configure_computer_feedback' ? { config } : {}) }) });
        onChange(payload);
        const response = await request('/api/block-feedback?system=computer');
        data.computer_feedback = response.computer_feedback;
        if (type === 'configure_computer_feedback') renderConnection();
        status(type === 'configure_computer_feedback' ? 'Connection settings saved.' : type === 'connect_computer_feedback' ? 'Detectors connected. Waiting for fresh snapshots.' : 'Detectors disconnected. Mapped blocks remain protected.');
      } catch (error) { status('Detector connection: ' + error.message); }
      finally { busy = false; updateControls(); }
    }
    $('#feedback-connection-save').addEventListener('click', () => connectionAction('configure_computer_feedback'));
    $('#feedback-connect').addEventListener('click', () => connectionAction('connect_computer_feedback'));
    $('#feedback-disconnect').addEventListener('click', () => connectionAction('disconnect_computer_feedback'));
    function markDirty() { dirty = true; status('Unsaved detector assignments'); updateControls(); }
    function addContact(contact = {}) {
      $('#feedback-contact-rows .feedback-empty')?.remove();
      const limits = data.limits;
      const row = document.createElement('div');
      row.className = 'feedback-contact-row';
      row.innerHTML = `<label>Module<input type="number" data-feedback-module min="${limits.module_min}" max="${limits.module_max}" step="1" required value="${esc(contact.module)}"></label><label>Input<input type="number" data-feedback-input min="1" max="${limits.input_max}" step="1" required value="${esc(contact.input)}"></label><button type="button" class="button button-soft" aria-label="Remove detector input">Remove</button>`;
      row.querySelector('button').addEventListener('click', () => { row.remove(); markDirty(); });
      row.addEventListener('input', markDirty);
      $('#feedback-contact-rows').appendChild(row);
    }
    function renderBlock() {
      selectedBlock = $('#feedback-block').value;
      $('#feedback-contact-rows').innerHTML = '';
      const rows = data.assignments.filter(row => row.block_id === selectedBlock);
      const saved = rows.filter(row => row.sources.includes('block'));
      if (!saved.length) $('#feedback-contact-rows').innerHTML = '<p class="feedback-empty">No detector inputs assigned here yet.</p>';
      saved.forEach(addContact);
      const inherited = rows.filter(row => row.sources.some(source => source !== 'block'));
      $('#feedback-inherited-rows').innerHTML = inherited.map(row => `<p class="editor-note">Module ${row.module}, input ${row.input} — ${row.sources.includes('trigger') ? 'used by a track trigger' : 'startup configuration'}${row.sources.includes('block') ? '; also saved as a block assignment' : ''}. ${row.sources.includes('trigger') ? 'Edit the trigger to remove its mapping.' : 'Change the startup configuration to remove it.'}</p>`).join('');
      dirty = false; updateControls();
    }
    function renderOverview() {
      $('#feedback-overview-rows').innerHTML = data.assignments.length ? '<div class="feedback-overview-list">' + data.assignments.map(row => `<button type="button" class="feedback-overview-row" data-feedback-block="${esc(row.block_id)}"><strong>${esc(row.block_id)}</strong><span>Module ${row.module} · input ${row.input}</span><small>${!row.available ? 'Inactive — block missing or incompatible address' : row.active ? data.feedback_healthy ? 'Active' : 'Awaiting feedback' : 'Saved'} · ${row.sources.map(source => ({ block: 'Block assignment', trigger: 'Track trigger', environment: 'Startup' }[source])).join(', ')}</small></button>`).join('') + '</div>' : '<p class="feedback-empty">No assignments for this digital system.</p>';
    }
    async function load() {
      const token = ++revision;
      busy = true; data = null; updateControls(); status('Loading detector assignments…');
      $('#feedback-contact-rows').innerHTML = ''; $('#feedback-inherited-rows').innerHTML = ''; $('#feedback-overview-rows').innerHTML = '';
      try {
        const response = await request('/api/block-feedback?system=' + encodeURIComponent(selectedSystem));
        if (token !== revision) return;
        data = response;
        const blocks = new Map(context().blocks.map(block => [upper(block.id), block.name || block.id]));
        data.assignments.forEach(row => { if (!blocks.has(row.block_id)) blocks.set(row.block_id, row.block_id + ' (not in layout)'); });
        $('#feedback-block').innerHTML = [...blocks].map(([id, name]) => `<option value="${esc(id)}">${esc(id)} · ${esc(name)}</option>`).join('');
        $('#feedback-block').value = blocks.has(selectedBlock) ? selectedBlock : blocks.keys().next().value || '';
        const limits = data.limits;
        const addressType = selectedSystem === 'computer' ? 'Computer detector module/input' : ['z21', 'z21_white', 'z21_start', 'dr5000'].includes(selectedSystem) ? 'R-Bus module/input' : selectedSystem === 'ecos' ? 'ECoS feedback module/contact' : selectedSystem === 'xpressnet' ? 'XpressNet feedback module/input' : 'Märklin feedback device/contact';
        $('#feedback-address-help').textContent = `${addressType}: module ${limits.module_min}–${limits.module_max}, input 1–${limits.input_max}. Use the reported feedback addresses, not locomotive DCC addresses. Assignments are kept separately for each detector source.`;
        renderConnection(); renderBlock(); renderOverview(); status('Assignments loaded.');
        return true;
      } catch (error) { if (token === revision) status('Unable to load assignments: ' + error.message + '. Close and reopen to retry.'); }
      finally { if (token === revision) { busy = false; updateControls(); } }
    }
    async function open(blockId, source) {
      if (dialog.open) return;
      const state = context();
      const profiles = state.profiles.filter(profile => profile.id !== 'simulation');
      if (!profiles.length) { window.alert('Controller settings have not loaded. Refresh the controller and try again.'); return; }
      profiles.push({ id: 'computer', label: 'Computer-connected detectors (USB / network)' });
      selectedSystem = source || (state.physical ? state.active_system : state.system);
      if (!profiles.some(profile => profile.id === selectedSystem)) selectedSystem = 'z21';
      selectedBlock = upper(blockId);
      $('#feedback-system').innerHTML = profiles.map(profile => `<option value="${esc(profile.id)}">${esc(profile.label)}</option>`).join('');
      $('#feedback-system').value = selectedSystem;
      dirty = false; dialog.showModal(); await load();
    }
    $('#feedback-system').addEventListener('change', () => {
      if (!discardAllowed()) { $('#feedback-system').value = selectedSystem; return; }
      selectedSystem = $('#feedback-system').value; dirty = connectionDirty = false; load();
    });
    $('#feedback-block').addEventListener('change', () => {
      if (!discardAllowed()) { $('#feedback-block').value = selectedBlock; return; }
      renderBlock(); status('Assignments loaded.');
    });
    $('#feedback-add-contact').addEventListener('click', () => { addContact(); markDirty(); $('#feedback-contact-rows').lastElementChild.querySelector('input').focus(); });
    $('#feedback-discard').addEventListener('click', () => { renderConnection(); renderBlock(); status('Edits discarded.'); });
    $('#feedback-overview-rows').addEventListener('click', event => {
      const button = event.target.closest('[data-feedback-block]');
      if (button && discardAllowed()) { $('#feedback-block').value = button.dataset.feedbackBlock; renderBlock(); status('Assignments loaded.'); }
    });
    $('#block-feedback-form').addEventListener('submit', async event => {
      event.preventDefault();
      if (busy || !data || locked()) return;
      if (connectionDirty) { status('Save the connection settings before saving assignments, or discard the connection edits.'); return; }
      const contacts = [...$('#feedback-contact-rows').querySelectorAll('.feedback-contact-row')].map(row => ({ module: Number(row.querySelector('[data-feedback-module]').value), input: Number(row.querySelector('[data-feedback-input]').value) }));
      busy = true; updateControls(); status('Saving detector assignments…');
      try {
        const payload = await request('/api/commands', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type: 'set_block_feedback', system: selectedSystem, block_id: selectedBlock, contacts }) });
        dirty = false; onChange(payload);
        if (await load()) status('Assignments saved on this controller.');
        else status('Assignments saved, but reload failed. Close and reopen the editor to retry.');
      } catch (error) { status('Not saved: ' + error.message); }
      finally { busy = false; updateControls(); }
    });
    document.querySelector('#open-feedback-mapping').addEventListener('click', () => open());
    function describeBlock(id) {
      const state = context(), block = upper(id);
      const saved = (state.triggers.block_feedback || []).filter(row => row.block_id === block && (row.system === state.system || row.system === 'computer'));
      const inherited = (state.triggers.feedback_map || []).filter(row => upper(row.block_id) === block);
      document.querySelector('#block-feedback-summary').textContent = saved.length ? saved.map(row => `${row.system === 'computer' ? 'Computer · ' : ''}Module ${row.module} · input ${row.input}`).join('; ') : inherited.length ? 'Existing detector mapping available. Open assignments for details.' : 'No detector inputs assigned for the saved digital system.';
    }
    function update() {
      const state = context();
      const count = (state.triggers.block_feedback || []).length;
      document.querySelector('#feedback-mapping-summary').textContent = `${count} saved detector input${count === 1 ? '' : 's'}. Map command-station feedback or detectors connected to this computer by USB or network.`;
      if (dialog.open) updateControls();
    }
    update();
    return { open, update, describeBlock };
  }
  global.BlockFeedback = { create };
})(typeof window !== 'undefined' ? window : globalThis);
