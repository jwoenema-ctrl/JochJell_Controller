(function (global) {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  function create({ request, context, onChange, openConnection }) {
    const dialog = document.createElement('dialog');
    dialog.id = 'turnout-connectors-editor';
    dialog.className = 'modal feedback-mapping-modal';
    dialog.setAttribute('aria-labelledby', 'turnout-connectors-title');
    dialog.innerHTML = `<form id="turnout-connector-form" class="modal-card">
      <div class="modal-heading"><div><p class="eyebrow">TRACK SWITCH CONNECTIONS</p><h2 id="turnout-connectors-title">Map track switches</h2></div><button type="button" class="icon-button" id="turnout-connector-close" aria-label="Close track switch mapping">×</button></div>
      <div class="modal-body"><p class="feedback-intro">Choose the connection used to move each physical switch. Computer-connected switches share the USB / network bridge with occupancy detectors.</p>
      <div class="field-grid"><div class="field"><label for="connector-turnout">Track switch</label><select id="connector-turnout"></select></div><div class="field"><label for="connector-source">Control connection</label><select id="connector-source"><option value="command_station">Command station</option><option value="computer">Computer USB / network bridge</option></select></div></div>
      <p id="connector-station-note" class="editor-note"></p>
      <section id="connector-computer-fields" hidden><div class="field-grid"><div class="field"><label for="connector-module">Bridge module</label><input id="connector-module" type="number" min="1" max="65535" step="1" value="1"></div><div class="field"><label for="connector-output">Switch output</label><input id="connector-output" type="number" min="1" max="65535" step="1" value="1"></div><div class="field"><label for="connector-pulse">Pulse duration (ms)</label><input id="connector-pulse" type="number" min="50" max="1000" step="1" value="250"></div><div class="field"><label for="connector-inverted">Wiring direction</label><select id="connector-inverted"><option value="false">Normal</option><option value="true">Swap straight / diverging</option></select></div></div>
      <p class="editor-note">The bridge must limit each output pulse itself, including if the app disconnects. An acknowledgement confirms the command was accepted; it does not measure the switch blades.</p>
      <button type="button" class="button button-soft" id="connector-connection">USB / network connection settings</button><p id="connector-bridge-status" class="settings-status" role="status" aria-live="polite"></p></section>
      <p id="connector-power-note" class="feedback-power-note"></p>
      <div class="feedback-connection-actions"><button type="button" class="button button-soft" id="connector-straight">Set straight</button><button type="button" class="button button-soft" id="connector-diverging">Set diverging</button></div>
      <p class="editor-note">Simulation changes digital switches only. After connecting physical hardware, set each computer-mapped switch to confirm its command before driving trains. Route-locked switches cannot move.</p>
      <p id="connector-save-status" class="settings-status" role="status" aria-live="polite"></p></div>
      <div class="modal-actions"><button type="button" class="button button-soft" id="connector-discard">Discard edits</button><button type="submit" class="button button-primary" id="connector-save">Save switch connection</button></div></form>`;
    document.body.appendChild(dialog);
    const $ = selector => dialog.querySelector(selector);
    let data = null, dirty = false, busy = false, selected = '';
    const status = message => { $('#connector-save-status').textContent = message; };
    const canDiscard = () => !dirty || window.confirm('Discard unsaved switch connection edits?');
    const close = () => { if (!busy && canDiscard()) { dirty = false; dialog.close(); } };
    $('#turnout-connector-close').addEventListener('click', close);
    dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
    function updateControls() {
      const state = context(), computer = (state.ready && state.triggers.computer_feedback) || data?.computer_feedback;
      const row = data?.turnouts.find(row => row.id === selected);
      const live = state.turnouts.find((item, index) => (index === 0 && item.id === 'to1' ? data?.turnouts[0]?.id : String(item.id).toUpperCase()) === selected);
      const locked = state.ready && live ? live.lockedBy : row?.locked_by;
      const physical = data?.physical ?? state.physical;
      const powerLocked = physical && (data?.track_power ?? state.track_power);
      const isComputer = $('#connector-source').value === 'computer';
      $('#connector-computer-fields').hidden = !isComputer;
      $('#connector-station-note').hidden = isComputer;
      $('#connector-station-note').textContent = `Uses the turnout's command-station accessory address${row?.address != null ? ' ' + row.address : ' (not configured)'}. Edit the turnout asset to change this address.`;
      $('#connector-turnout').disabled = busy || !data;
      $('#connector-save').disabled = busy || !data || !selected || powerLocked || !!locked;
      $('#connector-discard').disabled = busy || !dirty;
      $('#connector-source').disabled = busy || !data || powerLocked || !!locked;
      $('#connector-computer-fields').querySelectorAll('input, select').forEach(input => { input.disabled = busy || powerLocked || !!locked || !isComputer; input.required = isComputer; });
      const saved = data?.assignments.find(row => row.turnout_id === selected);
      const canMove = physical && !busy && !dirty && row && !locked && (!saved || computer?.connected);
      $('#connector-straight').disabled = !canMove;
      $('#connector-diverging').disabled = !canMove;
      $('#connector-connection').disabled = busy;
      $('#connector-power-note').textContent = locked ? 'Switch locked by ' + locked + '. Stop and release the route before editing or moving it.' : powerLocked ? 'Switch physical track power off before changing connections. Saved switches can still be operated when their routes are unlocked.' : 'Connections are saved immediately. Saving and connecting a bridge never moves a switch.';
      if (computer) {
        const confirmation = computer.switch_states?.[selected];
        $('#connector-bridge-status').textContent = !computer.connected ? 'Computer bridge disconnected' : confirmation ? `Bridge connected · last accepted command: ${confirmation}` : 'Bridge connected · switch command unconfirmed';
      }
    }
    function renderSelection() {
      selected = $('#connector-turnout').value;
      const row = data.assignments.find(row => row.turnout_id === selected);
      $('#connector-source').value = row ? 'computer' : 'command_station';
      $('#connector-module').value = row?.module || 1; $('#connector-output').value = row?.output || 1;
      $('#connector-pulse').value = row?.pulse_ms || 250; $('#connector-inverted').value = String(row?.inverted || false);
      dirty = false; updateControls();
    }
    async function load() {
      data = null; busy = true; updateControls(); status('Loading switch connections…');
      try {
        data = await request('/api/turnout-connectors');
        const options = data.turnouts.map(row => ({ id: row.id, name: row.name }));
        for (const row of data.assignments) if (!options.some(option => option.id === row.turnout_id)) options.push({ id: row.turnout_id, name: 'Missing from layout' });
        $('#connector-turnout').innerHTML = options.map(row => `<option value="${esc(row.id)}">${esc(row.id)} · ${esc(row.name)}</option>`).join('');
        $('#connector-turnout').value = options.some(row => row.id === selected) ? selected : options[0]?.id || '';
        renderSelection(); status('Switch connections loaded.'); return true;
      } catch (error) { status('Unable to load switch connections: ' + error.message); }
      finally { busy = false; updateControls(); }
    }
    async function open() { dirty = false; dialog.showModal(); await load(); }
    document.querySelector('#open-turnout-connectors').addEventListener('click', open);
    $('#connector-turnout').addEventListener('change', () => { if (!canDiscard()) { $('#connector-turnout').value = selected; return; } renderSelection(); status('Switch connections loaded.'); });
    $('#turnout-connector-form').addEventListener('input', event => { if (event.target.id === 'connector-turnout') return; dirty = true; status('Unsaved switch connection'); updateControls(); });
    $('#connector-discard').addEventListener('click', () => { renderSelection(); status('Edits discarded.'); });
    $('#connector-connection').addEventListener('click', () => { if (!busy && canDiscard()) { dirty = false; dialog.close(); openConnection(); } });
    $('#turnout-connector-form').addEventListener('submit', async event => {
      event.preventDefault(); if ($('#connector-save').disabled) return;
      const assignment = $('#connector-source').value === 'computer' ? { module: Number($('#connector-module').value), output: Number($('#connector-output').value), pulse_ms: Number($('#connector-pulse').value), inverted: $('#connector-inverted').value === 'true' } : null;
      busy = true; updateControls(); status('Saving switch connection…');
      try {
        onChange(await request('/api/commands', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type: 'set_turnout_connector', turnout_id: selected, assignment }) }));
        dirty = false; if (await load()) status('Switch connection saved.'); else status('Switch connection saved; reopen to reload it.');
      } catch (error) { status('Not saved: ' + error.message); }
      finally { busy = false; updateControls(); }
    });
    async function move(position) {
      if (busy || dirty) return;
      busy = true; updateControls(); status('Waiting for switch command confirmation…');
      try {
        onChange(await request('/api/commands', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type: 'set_turnout', turnout_id: selected, state: position }) }));
        if (await load()) status('Switch command accepted: ' + position + '.');
      } catch (error) { status('Switch command failed: ' + error.message); }
      finally { busy = false; updateControls(); }
    }
    $('#connector-straight').addEventListener('click', () => move('straight'));
    $('#connector-diverging').addEventListener('click', () => move('diverging'));
    function update() {
      const count = (context().triggers.computer_turnouts || []).length;
      document.querySelector('#turnout-connector-summary').textContent = `${count} switch${count === 1 ? '' : 'es'} assigned to the computer bridge. Other switches use command-station accessory addresses.`;
      if (dialog.open) {
        const state = context();
        if (data && state.ready) { data.physical = state.physical; data.track_power = state.track_power; }
        updateControls();
      }
    }
    update(); return { open, update };
  }
  global.TurnoutConnectors = { create };
})(typeof window !== 'undefined' ? window : globalThis);
