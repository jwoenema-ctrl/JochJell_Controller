/*
 * JochJell Controller
 * A dependency-free browser client. The API adapters are intentionally small so
 * the dashboard is served by the local controller. File launches open that server.
 */
(function () {
  'use strict';

  const SAMPLE_STATE = {
    mode: 'manual',
    track_power: true,
    connection: { connected: false, simulated: true, label: 'Simulation fallback', detail: 'Local sample state' },
    feedback: { healthy: true, error: '', mapped_contacts: 0 },
    simulation: { running: true, rate: 1, clock: '10:42:16', world_clock: '00:00', date: 'Tuesday · 14 May' },
    layout: {
      name: 'West yard',
      blocks: [
        { id: 'b01', name: 'A-01', x: 62, y: 62, width: 126, height: 56, status: 'free', station: 'Amsterdam C.' },
        { id: 'b02', name: 'A-02', x: 222, y: 62, width: 126, height: 56, status: 'free', station: 'Amsterdam C.' },
        { id: 'b03', name: 'A-03', x: 382, y: 62, width: 126, height: 56, status: 'route', station: 'West junction' },
        { id: 'b04', name: 'A-04', x: 542, y: 62, width: 126, height: 56, status: 'occupied', trainId: 't1', station: 'West junction' },
        { id: 'b05', name: 'A-05', x: 702, y: 62, width: 126, height: 56, status: 'free', station: 'Utrecht line' },
        { id: 'b06', name: 'B-01', x: 62, y: 224, width: 126, height: 56, status: 'free', station: 'Platform 3' },
        { id: 'b07', name: 'B-02', x: 222, y: 224, width: 126, height: 56, status: 'occupied', trainId: 't2', station: 'Platform 3' },
        { id: 'b08', name: 'B-03', x: 382, y: 224, width: 126, height: 56, status: 'free', station: 'Platform 2' },
        { id: 'b09', name: 'B-04', x: 542, y: 224, width: 126, height: 56, status: 'route', station: 'Platform 2' },
        { id: 'b10', name: 'B-05', x: 702, y: 224, width: 126, height: 56, status: 'free', station: 'Utrecht line' },
        { id: 'b11', name: 'TURN-1', x: 326, y: 143, width: 126, height: 45, status: 'free', station: 'West junction' },
        { id: 'b12', name: 'TURN-2', x: 566, y: 143, width: 126, height: 45, status: 'free', station: 'West junction' }
      ],
      edges: [
        { from: 'b01', to: 'b02', status: 'free' }, { from: 'b02', to: 'b03', status: 'free' },
        { from: 'b03', to: 'b04', status: 'occupied' }, { from: 'b04', to: 'b05', status: 'free' },
        { from: 'b06', to: 'b07', status: 'free' }, { from: 'b07', to: 'b08', status: 'occupied' },
        { from: 'b08', to: 'b09', status: 'route' }, { from: 'b09', to: 'b10', status: 'route' },
        { from: 'b03', to: 'b11', status: 'route' }, { from: 'b11', to: 'b08', status: 'route' },
        { from: 'b04', to: 'b12', status: 'occupied' }, { from: 'b12', to: 'b09', status: 'route' },
        { from: 'b11', to: 'b12', status: 'free' }
      ],
      turnouts: [
        { id: 'to1', name: 'WJ-01', state: 'straight' }, { id: 'to2', name: 'WJ-02', state: 'diverging' },
        { id: 'to3', name: 'PF-01', state: 'straight' }, { id: 'to4', name: 'PF-02', state: 'straight' }
      ],
      platforms: [
        { id: 'p1', name: 'Platform 1', blockIds: ['b01', 'b02', 'b03'] },
        { id: 'p2', name: 'Platform 2', blockIds: ['b08', 'b09'] },
        { id: 'p3', name: 'Platform 3', blockIds: ['b06', 'b07'] }
      ],
      routes: [
        { id: 'r1', name: 'West approach to Central', source_block_id: 'B01', target_block_id: 'B02', node_ids: ['B01', 'B02'], algorithm: 'a_star', enabled: true },
        { id: 'r2', name: 'East platform to Yard', source_block_id: 'B03', target_block_id: 'B04', node_ids: ['B03', 'B04'], algorithm: 'a_star', enabled: true }
      ]
    },
    trains: [
      { id: 't1', number: '184', name: 'IC 184 Aurora', class: 'Intercity', status: 'Running', speed: 74, position: 'A-04', origin: 'Amsterdam Centraal', destination: 'Utrecht', direction: 'Eastbound', decoder: 'Z21-184-A', length: 152, maxSpeed: 140, consist: [{ type: 'locomotive', name: 'NS 186 001', detail: 'Traxx electric · 6,400 kW' }, { type: 'coach', name: 'I11 A 50 88', detail: '1st class · 26.4 m' }, { type: 'coach', name: 'I11 B 50 88', detail: '2nd class · 26.4 m' }, { type: 'coach', name: 'I11 B 50 88', detail: '2nd class · 26.4 m' }] },
      { id: 't2', number: '2916', name: 'Sprinter 2916', class: 'EMU', status: 'Boarding', speed: 0, position: 'B-02', origin: 'Utrecht', destination: 'Amsterdam Centraal', direction: 'Westbound', decoder: 'Z21-2916-S', length: 120, maxSpeed: 140, consist: [{ type: 'multiple unit', name: 'NS SNG 2316', detail: '3-car electric multiple unit' }] },
      { id: 't3', number: '638', name: 'Cargo 638', class: 'Freight', status: 'Waiting', speed: 0, position: 'A-01', origin: 'Rotterdam Maasvlakte', destination: 'Amersfoort', direction: 'Eastbound', decoder: 'Z21-638-C', length: 281, maxSpeed: 100, consist: [{ type: 'locomotive', name: 'NS 189 091', detail: 'Vectron electric · 6,400 kW' }, { type: 'wagon', name: 'Eanos 31 84', detail: 'Open wagon · 22.5 t' }, { type: 'wagon', name: 'Eanos 31 84', detail: 'Open wagon · 22.5 t' }] },
      { id: 't4', number: '421', name: 'Nightjet 421', class: 'International', status: 'Route set', speed: 46, position: 'B-04', origin: 'Amsterdam Centraal', destination: 'Wien Hbf', direction: 'Eastbound', decoder: 'Z21-421-N', length: 231, maxSpeed: 120, consist: [{ type: 'locomotive', name: 'ÖBB 1116 195', detail: 'Taurus electric · 6,400 kW' }, { type: 'sleeper', name: 'WLABmz 71 81', detail: 'Night coach · 26.4 m' }] },
      { id: 't5', number: '73', name: 'Regional 73', class: 'Regional', status: 'Ready', speed: 0, position: 'B-08', origin: 'Utrecht', destination: 'Arnhem', direction: 'Eastbound', decoder: 'Z21-73-R', length: 78, maxSpeed: 120, consist: [{ type: 'multiple unit', name: 'NS FLIRT 3', detail: '3-car electric multiple unit' }] }
    ],
    schedules: [
      { id: 's1', time: '10:45', service: 'IC 184 Aurora', number: '184', route: 'Amsterdam C.  →  Utrecht', platform: '1', state: 'On time' },
      { id: 's2', time: '10:48', service: 'Sprinter 2916', number: '2916', route: 'Utrecht  →  Amsterdam C.', platform: '3', state: 'Boarding' },
      { id: 's3', time: '10:55', service: 'Cargo 638', number: '638', route: 'Maasvlakte  →  Amersfoort', platform: '—', state: 'Path set' },
      { id: 's4', time: '11:02', service: 'Nightjet 421', number: '421', route: 'Amsterdam C.  →  Wien Hbf', platform: '2', state: 'Delayed' },
      { id: 's5', time: '11:06', service: 'Regional 73', number: '73', route: 'Utrecht  →  Arnhem', platform: '2', state: 'On time' }
    ],
    scans: [
      { id: 'sample-yard', label: 'West yard overview', description: 'Perspective placeholder for the first local photo scan.', image: null, anchor: { x: 0.5, y: 0.48 } }
    ]
  };

  const clone = (value) => JSON.parse(JSON.stringify(value));

  const AUTOMATION_BLOCK_DEFS = {
    drive: { label: 'Drive', description: 'Set speed and hold it', color: 'blue' },
    speed_ramp: { label: 'Speed staircase', description: 'Ramp between two speeds', color: 'orange' },
    travel: { label: 'Travel distance', description: 'Move a calibrated distance', color: 'green' },
    wait: { label: 'Wait', description: 'Pause before the next action', color: 'violet' },
    direction: { label: 'Direction', description: 'Forward or reverse', color: 'orange' },
    function: { label: 'Function', description: 'Lighting or decoder function', color: 'green' },
    stop: { label: 'Stop', description: 'Bring the train to a safe stop', color: 'red' }
  };


  const app = {
    state: clone(SAMPLE_STATE),
    trainDatabase: [],
    source: 'sample',
    selectedTrainId: 't1',
    selectedBlockId: 'b04',
    controlMode: 'manual',
    workspace: 'dispatch',
    trainSection: 'overview',
    layoutView: 'graph',
    editorTab: 'datasheet',
    simRate: 1,
    zoom: 1,
    layoutViewports: { graph: null, pinboard: null },
    layoutViewportManual: { graph: false, pinboard: false },
    panDrag: null,
    panKeyDown: false,
    suppressCanvasClickUntil: 0,
    filter: '',
    consistDraft: null,
    editingBlockId: null,
    editingScheduleId: null,
    editingRouteId: null,
    routeEditorDirty: false,
    routeFlow: [],
    editingTrainData: null,
    scanViewer: null,
    selectedScanId: 'sample-yard',
    trainDatabaseRevision: null,
    trainDatabaseIndex: null,
    scanObjectUrls: {},
    layoutEditing: false,
    layoutDrag: null,
    waypointDrag: null,
    selectedSplineSection: null,
    selectedWaypointId: null,
    splineHandleDrag: null,
    splineSpeedDirty: false,
    pendingBlockPlacementId: null,
    pendingWaypointPlacementId: null,
    nextConsistItemNumber: 1,
    layoutAssetEditing: null,
    pinboardCursor: null,
    pendingPinboardTrain: null,
    pinboardPlacementSelection: '',
    pinboardTrainDrag: null,
    automationDraft: { id: null, name: 'New train routine', trainId: '', blocks: [] },
    automationSelectedBlockId: null,
    automationPrograms: [],
    automationRunPending: false,
    worldClockSample: null,
    stateMutationRevision: 0,
    routeFlowSelectedId: null
  };
  const pendingRouteDeletes = new Set();

  app.state.trains.forEach((train) => {
    if (train.length_mm == null && Number.isFinite(Number(train.length))) train.length_mm = Number(train.length) * 1000;
  });

  function rollingStockCatalogue() {
    const inventory = app.state.rollingStockInventory || {};
    const persisted = Array.isArray(inventory.items) && inventory.items.length
      ? inventory.items
      : Array.isArray(inventory.catalogue) ? inventory.catalogue : [];
    const source = persisted.length ? persisted : (app.state.trains || []).flatMap((train) => train.consist || []);
    const seen = new Set();
    return source.reduce((items, raw, index) => {
      const item = raw || {};
      const id = String(item.id || item.item_id || item.catalogue_id || item.rolling_stock_id || item.name || `rolling-stock-${index + 1}`);
      if (seen.has(id)) return items;
      seen.add(id);
      const type = String(item.vehicle_type || item.type || 'vehicle');
      const name = String(item.name || item.model || id);
      const detail = item.detail || [item.manufacturer, item.model].filter(Boolean).join(' · ') || type;
      const hasQuantity = item.count != null || item.quantity != null;
      items.push({
        id,
        type,
        name,
        detail,
        manufacturer: item.manufacturer || '',
        model: item.model || '',
        length_mm: item.length_mm,
        mass_g: item.mass_g,
        count: hasQuantity ? Number(item.count ?? item.quantity) : 1,
      });
      return items;
    }, []);
  }

  // A dial draft is separate from measured speed: requesting zero is not proof
  // that a locomotive has stopped. Only acknowledged state unlocks direction.
  let speedTimer = null;
  let speedEpoch = 0;
  let speedDraft = null;
  let speedInFlight = Promise.resolve();
  const speedChoices = new Map();
  const motionSamples = new Map();
  let workspaceLayout = null;

  function cancelSpeedDraft() {
    clearTimeout(speedTimer);
    speedTimer = null;
    speedDraft = null;
    speedEpoch += 1;
  }

  function queueSpeed(value, immediate = false) {
    const train = selectedTrain();
    if (!train || app.source !== 'api' || app.state.track_power === false || app.nativeModePending || app.powerPending || app.controlPending) return;
    const speed = Math.max(0, Math.min(Number(train.maxSpeed || 140), Number(value) || 0));
    speedChoices.set(train.id, speed);
    speedDraft = { trainId: train.id, mode: trainControlMode(train), speed, epoch: speedEpoch };
    $('#speed-readout').textContent = String(Math.round(speed));
    clearTimeout(speedTimer);
    if (immediate) flushSpeedDraft(); else speedTimer = setTimeout(flushSpeedDraft, 250);
  }

  function flushSpeedDraft() {
    clearTimeout(speedTimer);
    const draft = speedDraft;
    speedDraft = null;
    if (!draft) return;
    speedInFlight = speedInFlight.then(async () => {
      const train = selectedTrain();
      if (draft.epoch !== speedEpoch || !train || train.id !== draft.trainId || trainControlMode(train) !== draft.mode || app.state.track_power === false || app.source !== 'api') return;
      app.speedSending = true;
      renderSidebar();
      try {
        const response = await fetchJson('/api/commands', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type: 'set_speed', train_id: draft.trainId, speed_kmh: draft.speed }) });
        if (draft.epoch === speedEpoch) { mergePayload(response); renderAll(); }
        $('#speed-command-status').textContent = `Requested ${Math.round(draft.speed)} km/h`;
      } catch (error) {
        cancelSpeedDraft();
        $('#speed-command-status').textContent = 'Speed not confirmed';
        showToast(error.message, 'warning');
      } finally { app.speedSending = false; renderSidebar(); }
    });
  }

  const DEFAULT_SETTINGS = { theme: 'system', interface: { density: 'comfortable', show_connection_detail: true, reduce_motion: false }, operations: { confirm_power_actions: false, default_simulation_rate: 1, connected_blocks: true, world_day_minutes: 24 }, z21_host: '192.168.0.111', z21_port: 21105, z21_wlan_enabled: false, ui_refresh_ms: 5000, routing: { adaptive: true, busy_interval_ms: 1000, idle_interval_ms: 5000 } };
  app.settings = clone(DEFAULT_SETTINGS);
  app.settingsDirty = false;
  app.settingsLoaded = false;
  app.settingsRuntime = null;
  app.pollTimer = null;
  let updateNativeControls = () => {};

  const LAYOUT_ASSET_DEFINITIONS = {
    station: {
      label: 'Station', collection: 'stations', plural: 'Stations', prefix: 'ST',
      fields: [
        { key: 'id', id: 'asset-id', label: 'Asset ID', required: true, placeholder: 'ST01' },
        { key: 'name', id: 'asset-name', label: 'Name', placeholder: 'Central station' },
        { key: 'blockIds', id: 'asset-block-ids', label: 'Block IDs', wide: true, placeholder: 'b01, b02' },
        { key: 'platformIds', id: 'asset-platform-ids', label: 'Platform IDs', wide: true, placeholder: 'p01, p02' },
        { key: 'waypointIds', id: 'asset-waypoint-ids', label: 'Waypoint IDs', wide: true, placeholder: 'wp01' }
      ]
    },
    signal: {
      label: 'Signal', collection: 'signals', plural: 'Signals', prefix: 'S',
      fields: [
        { key: 'id', id: 'asset-id', label: 'Asset ID', required: true, placeholder: 'S01' },
        { key: 'name', id: 'asset-name', label: 'Name', placeholder: 'West departure' },
        { key: 'address', id: 'asset-address', label: 'Decoder address', type: 'number', min: 0, step: 1 },
        { key: 'block_id', id: 'asset-block-id', label: 'Mounted block', placeholder: 'b01' },
        { key: 'protects_block_id', id: 'asset-protects-block-id', label: 'Protects block', placeholder: 'b02' },
        { key: 'aspect', id: 'asset-aspect', label: 'Aspect', type: 'select', options: [['red', 'Red'], ['yellow', 'Yellow'], ['green', 'Green']] }
      ]
    },
    turnout: {
      label: 'Turnout', collection: 'turnouts', plural: 'Turnouts', prefix: 'T',
      fields: [
        { key: 'id', id: 'asset-id', label: 'Asset ID', required: true, placeholder: 'T01' },
        { key: 'name', id: 'asset-name', label: 'Name', placeholder: 'Central turnout' },
        { key: 'address', id: 'asset-address', label: 'Decoder address', type: 'number', min: 0, step: 1 },
        { key: 'from', id: 'asset-from', label: 'Entry block', placeholder: 'b02' },
        { key: 'to', id: 'asset-to', label: 'Straight block', placeholder: 'b03' },
        { key: 'alternate', id: 'asset-alternate', label: 'Diverging block', placeholder: 'b04' },
        { key: 'state', id: 'asset-state', label: 'State', type: 'select', options: [['straight', 'Straight'], ['diverging', 'Diverging']] }
      ]
    },
    waypoint: {
      label: 'Waypoint', collection: 'waypoints', plural: 'Waypoints', prefix: 'WP',
      fields: [
        { key: 'id', id: 'asset-id', label: 'Asset ID', required: true, placeholder: 'WP01' },
        { key: 'name', id: 'asset-name', label: 'Name', placeholder: 'Central throat' },
        { key: 'x', id: 'asset-x', label: 'Canvas X', type: 'number', min: 0, step: 1 },
        { key: 'y', id: 'asset-y', label: 'Canvas Y', type: 'number', min: 0, step: 1 },
        { key: 'connected_node_ids', id: 'asset-connected-node-ids', label: 'Connected node IDs', wide: true, placeholder: 'b02, b04' }
      ]
    },
    turntable: {
      label: 'Turntable', collection: 'turntables', plural: 'Turntables', prefix: 'TT',
      fields: [
        { key: 'id', id: 'asset-id', label: 'Asset ID', required: true, placeholder: 'TT01' },
        { key: 'name', id: 'asset-name', label: 'Name', placeholder: 'Yard turntable' },
        { key: 'address', id: 'asset-address', label: 'Decoder address', type: 'number', min: 0, step: 1 },
        { key: 'connected_block_ids', id: 'asset-connected-block-ids', label: 'Connected block IDs', wide: true, placeholder: 'b04, b05' },
        { key: 'aligned_block_id', id: 'asset-aligned-block-id', label: 'Aligned block', placeholder: 'b04' },
        { key: 'x', id: 'asset-x', label: 'Canvas X', type: 'number', min: 0, step: 1 },
        { key: 'y', id: 'asset-y', label: 'Canvas Y', type: 'number', min: 0, step: 1 }
      ]
    },
    platform: {
      label: 'Platform', collection: 'platforms', plural: 'Platforms', prefix: 'P',
      fields: [
        { key: 'id', id: 'asset-id', label: 'Asset ID', required: true, placeholder: 'P01' },
        { key: 'name', id: 'asset-name', label: 'Name', placeholder: 'Central station 1' },
        { key: 'stationId', id: 'asset-station-id', label: 'Station ID', placeholder: 'ST01' },
        { key: 'blockId', id: 'asset-block-id', label: 'Block ID', placeholder: 'b02' },
        { key: 'lengthMm', id: 'asset-length-mm', label: 'Length (mm)', type: 'number', min: 0, step: 1 }
      ]
    }
  };

  const ASSET_FIELD_ALIASES = {
    blockIds: ['blockIds', 'block_ids'], platformIds: ['platformIds', 'platform_ids'], waypointIds: ['waypointIds', 'waypoint_ids'],
    stationId: ['stationId', 'station_id'], blockId: ['blockId', 'block_id'], lengthMm: ['lengthMm', 'length_mm']
  };

  const LAYOUT_ASSET_COMMANDS = {
    station: { add: 'add_station', update: 'update_station', remove: 'remove_station' },
    signal: { add: 'add_signal', update: 'update_signal', remove: 'remove_signal' },
    turnout: { add: 'add_turnout', update: 'update_turnout', remove: 'remove_turnout' },
    waypoint: { add: 'add_waypoint', update: 'update_waypoint', remove: 'remove_waypoint' },
    turntable: { add: 'add_turntable', update: 'update_turntable', remove: 'remove_turntable' },
    platform: { add: 'add_platform', update: 'update_platform', remove: 'remove_platform' }
  };

  const TRAIN_CONTROL_MODES = [
    { value: 'manual', label: 'Manual' },
    { value: 'automatic', label: 'Automatic' },
    { value: 'stopped', label: 'Stopped / Safe' }
  ];

  const $ = (selector, root) => (root || document).querySelector(selector);
  const $$ = (selector, root) => Array.from((root || document).querySelectorAll(selector));
  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#039;', '"': '&quot;' }[character]));
  }
  function formatLengthMm(value) {
    if (value == null || value === '') return '-';
    const numeric = Number(value);
    return Number.isFinite(numeric) ? String(value) : '-';
  }

  function formatTime(value) {
    if (!value) return '—';
    return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  function nowTime() {
    return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  function showToast(message, tone) {
    const region = $('#toast-region');
    const toast = document.createElement('div');
    toast.className = `toast ${tone || ''}`;
    toast.textContent = message;
    region.appendChild(toast);
    window.setTimeout(() => toast.remove(), 3600);
  }

  function unwrap(payload) {
    if (!payload) return null;
    if (payload.data && typeof payload.data === 'object') return payload.data;
    if (payload.state && typeof payload.state === 'object') return payload.state;
    return payload;
  }

  function sameSequence(left, right, equals = (a, b) => a === b) {
    if (left === right) return true;
    return Array.isArray(left) && Array.isArray(right) && left.length === right.length
      && left.every((item, index) => equals(item, right[index]));
  }

  function samePoints(left, right) {
    return sameSequence(left, right, (a, b) => a && b && a.x === b.x && a.y === b.y);
  }

  function sameLayoutGeometry(left, right) {
    const sameRows = (key, equals) => sameSequence(left[key] || [], right[key] || [], equals);
    const sameValues = (a, b) => sameSequence(a, b);
    return sameRows('blocks', (a, b) => a.id === b.id && a.x === b.x && a.y === b.y && a.width === b.width && a.height === b.height)
      && sameRows('edges', (a, b) =>
        (a.from || a.source || a.from_block_id || a.source_block_id) === (b.from || b.source || b.from_block_id || b.source_block_id)
        && (a.to || a.target || a.to_block_id || a.target_block_id) === (b.to || b.target || b.to_block_id || b.target_block_id)
        && samePoints(a.control_points || a.controlPoints, b.control_points || b.controlPoints)
        && JSON.stringify(a.bezier_segments || []) === JSON.stringify(b.bezier_segments || []))
      && sameRows('waypoints', (a, b) => a.id === b.id && a.x === b.x && a.y === b.y
        && sameValues(a.connected_node_ids || a.connectedNodeIds, b.connected_node_ids || b.connectedNodeIds))
      && sameRows('turntables', (a, b) => a.id === b.id && a.x === b.x && a.y === b.y && a.width === b.width && a.height === b.height
        && sameValues(a.connected_block_ids || a.connectedBlockIds, b.connected_block_ids || b.connectedBlockIds))
      && sameRows('turnouts', (a, b) => a.id === b.id && (a.from || a.entry_block_id) === (b.from || b.entry_block_id)
        && (a.to || a.straight_block_id) === (b.to || b.straight_block_id)
        && (a.alternate || a.diverging_block_id) === (b.alternate || b.diverging_block_id));
  }

  function resetAutomaticLayoutViewports() {
    ['graph', 'pinboard'].forEach((key) => {
      if (!app.layoutViewportManual[key]) app.layoutViewports[key] = null;
    });
  }

  function mergePayload(payload) {
    const value = unwrap(payload);
    if (!value || typeof value !== 'object') return;
    if (value.layout) {
      const nextLayout = { ...app.state.layout, ...value.layout };
      if (!sameLayoutGeometry(app.state.layout, nextLayout)) resetAutomaticLayoutViewports();
      app.state.layout = nextLayout;
    }
    if (value.layout_info) app.state.layout_info = value.layout_info;
    if (Array.isArray(value.blocks)) app.state.layout.blocks = value.blocks;
    if (Array.isArray(value.edges)) app.state.layout.edges = value.edges;
    if (Array.isArray(value.turnouts)) app.state.layout.turnouts = value.turnouts;
    if (Array.isArray(value.signals)) app.state.layout.signals = value.signals;
    if (Array.isArray(value.waypoints)) app.state.layout.waypoints = value.waypoints;
    if (Array.isArray(value.turntables)) app.state.layout.turntables = value.turntables;
    if (Array.isArray(value.stations)) app.state.layout.stations = value.stations;
    if (Array.isArray(value.platforms)) app.state.layout.platforms = value.platforms;
    if (Array.isArray(value.routes)) app.state.routes = value.routes;
    if (value.layout && Array.isArray(value.layout.routes)) app.state.routes = value.layout.routes;
    if (Array.isArray(value.trains)) {
      const previous = selectedTrain();
      const next = previous && value.trains.find((train) => train.id === previous.id);
      if (previous && (!next || trainControlMode(previous) !== trainControlMode(next))) {
        cancelSpeedDraft();
        speedChoices.delete(previous.id);
      }
      app.state.trains = value.trains;
      const now = performance.now();
      value.trains.forEach((train) => {
        const motion = train.motion;
        if (!motion) { motionSamples.delete(train.id); return; }
        const signature = JSON.stringify(motion);
        if (motionSamples.get(train.id)?.signature !== signature) motionSamples.set(train.id, { signature, receivedAt: now });
      });
    }
    if (Array.isArray(value.trainDatabase)) {
      mergeTrainDatabaseRecords(value.trainDatabase);
      if (value.train_database_revision != null) app.trainDatabaseRevision = value.train_database_revision;
    } else if (Array.isArray(value.trains) && Array.isArray(app.state.trainDatabase)) {
      mergeTrainDatabaseRecords(app.state.trainDatabase);
    }
    if (Array.isArray(value.trains) && value.trains.length && value.trains[0] && value.trains[0].train_id) mergeTrainDatabaseRecords(value.trains);
    if (Array.isArray(value.schedules)) app.state.schedules = value.schedules;
    if (Array.isArray(value.scans)) app.state.scans = value.scans;
    if (typeof value.track_power === 'boolean') {
      if (!value.track_power) { cancelSpeedDraft(); speedChoices.clear(); }
      app.state.track_power = value.track_power;
    }
    if (value.feedback) app.state.feedback = { ...app.state.feedback, ...value.feedback };
    if (value.simulation) app.state.simulation = { ...app.state.simulation, ...value.simulation };
    if (value.connection) app.state.connection = { ...app.state.connection, ...value.connection };
    if (value.mode) app.state.mode = value.mode;
    if (value.calibration) app.state.calibration = value.calibration;
    if (value.presence) app.state.presence = value.presence;
    if (value.rollingStockInventory) app.state.rollingStockInventory = value.rollingStockInventory;
    if (value.programming) app.state.programming = value.programming;
    if (value.recording) app.state.recording = value.recording;
    if (Array.isArray(value.automationPrograms)) app.automationPrograms = value.automationPrograms;
    if (Array.isArray(value.automationPlayback)) app.state.automationPlayback = value.automationPlayback;
    if (value.coordinate_execution !== undefined) app.state.coordinate_execution = value.coordinate_execution;
    if (value.simulation) syncWorldClock(value);
  }

  function worldClockSeconds(now = performance.now()) {
    const sample = app.worldClockSample;
    if (!sample) {
      const seconds = Number(app.state.simulation.world_clock_seconds);
      if (Number.isFinite(seconds)) return seconds;
      const [hours, minutes] = String(app.state.simulation.world_clock || '00:00').split(':').map(Number);
      return ((hours || 0) * 60 + (minutes || 0)) * 60;
    }
    const age = Math.min(sample.maxAgeSeconds, Math.max(0, (now - sample.receivedAt) / 1000));
    return sample.seconds + (sample.running ? age * sample.rate : 0);
  }

  function syncWorldClock(payload, now = performance.now()) {
    const simulation = payload.simulation;
    const seconds = Number(simulation.world_clock_display_seconds ?? simulation.world_clock_seconds);
    if (!Number.isFinite(seconds)) { app.worldClockSample = null; return; }
    const simulated = Boolean(app.state.connection?.simulated || app.state.mode === 'simulation');
    const running = typeof simulation.world_clock_running === 'boolean'
      ? simulation.world_clock_running
      : Boolean(payload.motion_clock?.running && app.state.track_power && (!simulated || simulation.running));
    const previous = app.worldClockSample;
    const predicted = worldClockSeconds(now);
    const session = simulation.world_clock_session ?? null;
    const rate = Number(simulation.world_clock_rate) || (1440 / (Number(app.settings.operations.world_day_minutes) || 24));
    // Small response-time differences must not make a running clock count
    // backwards. A new controller session or clock edit resets the anchor.
    const continuous = previous?.running && running && previous.session === session && previous.rate === rate
      && (session !== null || seconds >= predicted - 120);
    app.worldClockSample = {
      seconds: continuous ? Math.max(seconds, predicted) : seconds,
      receivedAt: now,
      running,
      rate,
      session,
      // Stop extrapolating if the next dashboard request never completes.
      maxAgeSeconds: Math.max(5, Number(app.settings.ui_refresh_ms) / 1000 + 5)
    };
    renderWorldClock(now);
  }

  function freezeWorldClock(now = performance.now()) {
    if (!app.worldClockSample) return;
    app.worldClockSample = { ...app.worldClockSample, seconds: worldClockSeconds(now), receivedAt: now, running: false };
    renderWorldClock(now);
  }

  function renderWorldClock(now = performance.now()) {
    const dayMinutes = Number(app.state.simulation.world_day_minutes ?? app.settings.operations.world_day_minutes) || 24;
    const rateElement = $('#world-clock-rate');
    if (rateElement) {
      const rateText = dayMinutes === 1440 ? '24 real hours = 1 world day' : `${dayMinutes} real min = 1 world day`;
      if (rateElement.textContent !== rateText) rateElement.textContent = rateText;
    }
    const minutes = Math.floor(Math.max(0, worldClockSeconds(now)) / 60) % 1440;
    const text = String(Math.floor(minutes / 60)).padStart(2, '0') + ':' + String(minutes % 60).padStart(2, '0');
    ['#world-clock', '#settings-world-clock-current'].forEach((selector) => {
      const element = $(selector);
      if (element && element.textContent !== text) element.textContent = text;
    });
  }

  function mergeTrainDatabaseRecords(records) {
    const nextRecords = Array.isArray(records) ? records : [];
    if (app.state.trainDatabase !== nextRecords || !app.trainDatabaseIndex) {
      const byId = Object.fromEntries(nextRecords.map((record) => [String(record.train_id), record]));
      const byAddress = new Map();
      nextRecords.forEach((record) => {
        if (record.decoder_address == null || record.decoder_address === '') return;
        const address = String(record.decoder_address);
        if (!byAddress.has(address)) byAddress.set(address, record);
      });
      app.state.trainDatabase = nextRecords;
      app.trainDatabaseIndex = { byId, byAddress };
    }
    const { byId, byAddress } = app.trainDatabaseIndex;
    app.state.trains = (app.state.trains || []).map((train) => {
      const match = byId[String(train.id)]
        || byAddress.get(String(train.number || ''));
      if (!match) return train;
      const rollingStock = Array.isArray(match.rolling_stock) ? match.rolling_stock : [];
      return {
        ...train,
        database: match,
        decoder_functions: match.decoder_functions || [],
        maintenance_records: match.maintenance_records || [],
        rolling_stock: rollingStock,
        consist: train.consist && train.consist.length ? train.consist : rollingStock.map((item) => ({
          id: item.vehicle_id || item.rolling_stock_id,
          type: item.vehicle_type,
          name: item.name,
          detail: [item.manufacturer, item.model].filter(Boolean).join(' · '),
          length_mm: item.length_mm,
          mass_g: item.mass_g,
        }))
      };
    });
  }

  async function fetchJson(endpoint, options) {
    const controller = new AbortController();
    const mutation = options && options.method && options.method !== 'GET';
    const timer = window.setTimeout(() => controller.abort(), mutation ? 15000 : 4200);
    try {
      const response = await fetch(endpoint, { ...options, signal: controller.signal, headers: { Accept: 'application/json', ...(options && options.headers) } });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.error || `${response.status} ${response.statusText}`);
      }
      return await response.json();
    } catch (error) {
      if (error.name === 'AbortError') throw new Error(mutation
        ? 'The controller did not acknowledge this command in time. It may already have started. Check the train and routine status before sending it again.'
        : 'The controller took too long to respond. Check its connection and routine status.');
      if (error instanceof TypeError) throw new Error('Cannot reach the Python controller at ' + window.location.origin + '. Check that it is running and open the dashboard from its printed URL.');
      throw error;
    } finally {
      window.clearTimeout(timer);
    }
  }

  async function bootstrap() {
    loadAppSettings();
    const endpoints = ['/api/state'];
    const results = await Promise.allSettled(endpoints.map((endpoint) => fetchJson(endpoint)));
    let successCount = 0;
    results.forEach((result, index) => {
      if (result.status !== 'fulfilled') return;
      successCount += 1;
      mergePayload(result.value);
    });

    app.source = successCount ? 'api' : 'sample';
    if (successCount) {
      const simulated = Boolean(app.state.connection && (app.state.connection.simulated || app.state.connection.mode === 'simulation'));
      app.state.connection = simulated
        ? { ...app.state.connection, connected: false, simulated: true, label: 'Simulation online', detail: 'No physical trains connected' }
        : { ...app.state.connection, connected: Boolean(app.state.connection.connected), simulated: false, label: app.state.connection.connected ? 'Z21 connected' : 'Z21 disconnected', detail: app.state.connection.detail || 'Controller state loaded' };
    } else {
      freezeWorldClock();
      app.state.connection = { connected: false, simulated: true, label: 'Simulation fallback', detail: 'Local sample state' };
    }
    renderAll();
    const simulated = Boolean(app.state.connection && app.state.connection.simulated);
    updateSync(successCount ? `${simulated ? 'Simulation API online' : 'Connected to controller'} · state loaded` : 'API unavailable · running embedded sample state', successCount ? 'success' : 'warning');
  }

  function pollController() {
    if (document.visibilityState === 'hidden') return Promise.resolve();
    if (!app.pollRequest) {
      app.pollRequest = refreshController().finally(() => { app.pollRequest = null; });
    }
    return app.pollRequest;
  }

  async function refreshController() {
    const revision = app.stateMutationRevision;
    const results = await Promise.allSettled(['/api/live'].map((endpoint) => fetchJson(endpoint)));
    // A command or manual simulation tick may complete while this refresh is
    // in flight. Do not let an older snapshot restore the clock or pause state.
    if (revision !== app.stateMutationRevision) return;
    const stateResult = results[0];
    if (stateResult.status === 'fulfilled') {
      mergePayload(stateResult.value);
      const live = unwrap(stateResult.value) || {};
      const databaseRevision = live.train_database_revision;
      if (databaseRevision != null && databaseRevision !== app.trainDatabaseRevision) {
        try {
          const database = unwrap(await fetchJson('/api/train-database')) || {};
          if (revision !== app.stateMutationRevision) return;
          if (Array.isArray(database.trains)) {
            mergeTrainDatabaseRecords(database.trains);
            app.trainDatabaseRevision = databaseRevision;
          }
        } catch (_) {
          // Keep the last complete catalogue and retry when the revision is seen again.
        }
      }
      renderTrainList();
      renderSchedules();
      renderInventory();
      renderProgramming();
      updateSync('Controller state refreshed', 'success');
    } else {
      freezeWorldClock();
      app.state.layout_info = null;
      app.state.connection = { connected: false, simulated: false, label: 'Controller unavailable', detail: 'Check the local server' };
    }
    if (stateResult.status === 'fulfilled') showSettingsRuntime(unwrap(stateResult.value)?.runtime);
    renderConnection(); renderSidebar(); renderGraph(); renderSystematicView(); renderStats(); renderAutomationPlayback();
  }

  function applyTheme(theme) {
    const resolved = theme === 'system' ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : theme;
    document.documentElement.dataset.theme = resolved;
    document.documentElement.style.colorScheme = resolved;
    $('meta[name="theme-color"]').content = resolved === 'dark' ? '#212121' : '#ffffff';
  }

  function applyInterfaceSettings(settings) {
    const interfaceSettings = settings?.interface || DEFAULT_SETTINGS.interface;
    document.body.dataset.density = interfaceSettings.density || 'comfortable';
    document.body.dataset.connectionDetail = interfaceSettings.show_connection_detail === false ? 'hidden' : 'visible';
    document.documentElement.dataset.reduceMotion = interfaceSettings.reduce_motion ? 'true' : 'false';
  }

  function schedulePolling() {
    window.clearTimeout(app.pollTimer);
    app.pollTimer = window.setTimeout(async () => {
      try { await pollController(); } finally { schedulePolling(); }
    }, app.settings.ui_refresh_ms);
  }

  function renderSettings() {
    const settings = app.settings;
    $('#setting-theme').value = settings.theme;
    $('#setting-ui-refresh').value = settings.ui_refresh_ms / 1000;
    $('#setting-interface-density').value = settings.interface.density;
    $('#setting-show-connection-detail').checked = settings.interface.show_connection_detail;
    $('#setting-reduce-motion').checked = settings.interface.reduce_motion;
    $('#setting-confirm-power-actions').checked = settings.operations.confirm_power_actions;
    $('#setting-connected-blocks').checked = settings.operations.connected_blocks;
    $('#setting-default-simulation-rate').value = String(settings.operations.default_simulation_rate);
    $('#setting-world-day-minutes').value = String(settings.operations.world_day_minutes);
    app.simRate = Number(settings.operations.default_simulation_rate) || 1;
    applyInterfaceSettings(settings);
    $('#setting-z21-host').value = settings.z21_host;
    $('#setting-z21-port').value = settings.z21_port;
    $('#setting-z21-wlan').checked = Boolean(settings.z21_wlan_enabled);
    $('#setting-routing-adaptive').checked = settings.routing.adaptive;
    $('#setting-routing-busy').value = settings.routing.busy_interval_ms / 1000;
    $('#setting-routing-idle').value = settings.routing.idle_interval_ms / 1000;
    $('#setting-routing-idle').disabled = !settings.routing.adaptive;
    renderWlanPresentation(app.settingsRuntime);
    updateNativeControls();
    renderScanLibrary();
  }

  function selectedWlanProfile() {
    const checkbox = $('#setting-z21-wlan');
    return checkbox ? checkbox.checked : Boolean(app.settings.z21_wlan_enabled);
  }

  function runtimeTransportProfile(runtime) {
    if (!runtime || typeof runtime !== 'object') return null;
    const transport = runtime.transport && typeof runtime.transport === 'object' ? runtime.transport : {};
    const raw = runtime.transport_profile ?? runtime.z21_transport_profile ?? runtime.connection_profile ?? transport.profile;
    if (raw == null) return null;
    if (typeof raw === 'object') return String(raw.id ?? raw.mode ?? raw.name ?? raw.label ?? '').trim() || null;
    return String(raw).trim() || null;
  }

  function runtimeConnectionCheck(runtime) {
    if (!runtime || typeof runtime !== 'object') return null;
    const transport = runtime.transport && typeof runtime.transport === 'object' ? runtime.transport : {};
    const connection = runtime.connection && typeof runtime.connection === 'object' ? runtime.connection : {};
    return runtime.transport_status ?? runtime.connection_check ?? runtime.transport_check ?? transport.check ?? connection.check ?? null;
  }

  function profileUsesWlan(profile) {
    return profile != null && /wlan|wi-?fi|10814/i.test(String(profile));
  }

  function transportProfileLabel(profile) {
    if (/simulation/i.test(String(profile))) return 'simulation';
    return profileUsesWlan(profile) ? 'Roco 10814 WLAN' : 'direct LAN';
  }

  function connectionCheckSummary(check) {
    if (check == null) return null;
    if (typeof check === 'string' || typeof check === 'number') return { text: String(check), tone: '' };
    if (typeof check === 'boolean') return { text: check ? 'available' : 'not available', tone: check ? 'ok' : 'warning' };
    if (typeof check !== 'object') return null;
    const text = check.message ?? check.detail ?? check.status ?? check.label;
    const ok = check.ok ?? check.ready ?? check.healthy ?? check.available ?? check.connected;
    if (text == null && ok == null) return null;
    return { text: String(text ?? (ok ? 'available' : 'not available')), tone: ok === true ? 'ok' : ok === false ? 'warning' : '' };
  }

  function renderWlanPresentation(runtime) {
    const enabled = selectedWlanProfile();
    const host = ($('#setting-z21-host') && $('#setting-z21-host').value.trim()) || app.settings.z21_host || DEFAULT_SETTINGS.z21_host;
    const port = Number(($('#setting-z21-port') && $('#setting-z21-port').value) || app.settings.z21_port || DEFAULT_SETTINGS.z21_port);
    const profile = runtimeTransportProfile(runtime);
    const activeWlan = profile == null ? null : profileUsesWlan(profile);
    const check = connectionCheckSummary(runtimeConnectionCheck(runtime));
    const status = $('#settings-transport-status');
    if (!status) return;
    const selected = enabled ? 'Roco 10814 WLAN' : 'direct LAN';
    const parts = [`Selected profile: ${selected} · UDP ${host}:${port}.`];
    if (profile != null) parts.push(`Controller profile: ${transportProfileLabel(profile)}.`);
    if (runtime && runtime.restart_required && !/simulation/i.test(String(profile)) && activeWlan !== enabled) parts.push('Save and reconnect to apply this profile.');
    if (check) parts.push(`Connection check: ${check.text}.`);
    status.textContent = parts.join(' ');
    status.dataset.profile = enabled ? 'wlan' : 'lan';
    status.dataset.check = check && check.tone || '';
    const connectButton = $('#settings-connect-z21');
    if (connectButton) {
      connectButton.textContent = enabled ? 'Connect via WLAN' : 'Connect to real Z21';
      connectButton.setAttribute('aria-label', enabled ? 'Connect to real Z21 via Roco 10814 WLAN' : 'Connect to real Z21');
    }
  }

  function renderScanLibrary() {
    const scans = (app.state.scans || []).filter((scan) => scan.image);
    $('#settings-scan-library').innerHTML = scans.length ? scans.map((scan) => `<div class="scan-library-item"><div><strong>${escapeHtml(scan.label || scan.id)}</strong><p class="settings-help">${escapeHtml(scan.description || 'Layout photo')}</p></div><button type="button" class="button button-soft" data-view-scan="${escapeHtml(scan.id)}">Open viewer</button></div>`).join('') : '<p class="settings-help">Your photo library is empty. Add your first layout photograph above.</p>';
  }

  function showSettingsRuntime(runtime) {
    if (!runtime) return;
    app.settingsRuntime = runtime;
    $('#settings-connection-note').textContent = (runtime.connection_message || 'Saving never activates hardware. Connection changes take effect at the next explicit Z21 startup.') + (runtime.z21_environment_override ? ' An environment setting currently overrides the saved address or port.' : '');
    renderWlanPresentation(runtime);
    const routing = runtime.routing;
    if (routing) $('#settings-routing-status').textContent = routing.error
      ? `Route refresh needs attention: ${routing.error}`
      : `Layout ${routing.activity || 'idle'} · ${Number(routing.effective_interval_ms || 0) / 1000}s refresh · ${routing.refresh_count || 0} planning cycles. Route refresh never sends movement commands.`;
  }

  async function loadAppSettings() {
    try {
      const response = await fetchJson('/api/settings');
      app.settings = { ...clone(DEFAULT_SETTINGS), ...response.settings, interface: { ...DEFAULT_SETTINGS.interface, ...(response.settings || {}).interface }, operations: { ...DEFAULT_SETTINGS.operations, ...(response.settings || {}).operations }, routing: { ...DEFAULT_SETTINGS.routing, ...(response.settings || {}).routing } };
      mergePayload(response);
      app.settingsLoaded = true;
      workspaceLayout?.receiveSettings(response.settings);
      if (!app.settingsDirty) {
        renderSettings(); applyTheme(app.settings.theme); applyInterfaceSettings(app.settings);
        $('#settings-save-status').textContent = 'Preferences are up to date.';
      }
      showSettingsRuntime(response.runtime);
      schedulePolling();
    } catch (error) {
      $('#settings-save-status').textContent = 'Settings unavailable. Check the controller connection and try Refresh.';
    }
  }

  async function saveAppSettings(event) {
    event.preventDefault();
    const button = $('#settings-save');
    const settings = {
      theme: $('#setting-theme').value,
      z21_host: $('#setting-z21-host').value.trim(),
      z21_port: Number($('#setting-z21-port').value),
      z21_wlan_enabled: $('#setting-z21-wlan').checked,
      ui_refresh_ms: Number($('#setting-ui-refresh').value) * 1000,
      interface: { density: $('#setting-interface-density').value, show_connection_detail: $('#setting-show-connection-detail').checked, reduce_motion: $('#setting-reduce-motion').checked },
      operations: { confirm_power_actions: $('#setting-confirm-power-actions').checked, default_simulation_rate: Number($('#setting-default-simulation-rate').value), connected_blocks: $('#setting-connected-blocks').checked, world_day_minutes: Number($('#setting-world-day-minutes').value) },
      routing: { adaptive: $('#setting-routing-adaptive').checked, busy_interval_ms: Number($('#setting-routing-busy').value) * 1000, idle_interval_ms: Number($('#setting-routing-idle').value) * 1000 }
    };
    button.disabled = true;
    $('#settings-save-status').textContent = 'Saving preferences…';
    try {
      const response = await fetchJson('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(settings) });
      app.settings = { ...clone(DEFAULT_SETTINGS), ...response.settings, interface: { ...DEFAULT_SETTINGS.interface, ...(response.settings || {}).interface }, operations: { ...DEFAULT_SETTINGS.operations, ...(response.settings || {}).operations }, routing: { ...DEFAULT_SETTINGS.routing, ...(response.settings || {}).routing } };
      app.stateMutationRevision += 1;
      mergePayload(response);
      workspaceLayout?.receiveSettings(response.settings);
      app.settingsLoaded = true; app.settingsDirty = false;
      applyTheme(app.settings.theme); applyInterfaceSettings(app.settings); renderSettings(); schedulePolling(); showSettingsRuntime(response.runtime);
      $('#settings-save-status').textContent = 'Saved on this controller.';
      showToast('Settings saved', 'success');
    } catch (error) {
      $('#settings-save-status').textContent = `Not saved: ${error.message}`;
    } finally { button.disabled = false; }
  }

  async function uploadScan(file) {
    if (!file || !['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) throw new Error('Choose a PNG, JPEG or WebP photograph.');
    if (file.size > 10 * 1024 * 1024) throw new Error('Choose a photograph smaller than 10 MB.');
    const data = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(',')[1]);
      reader.onerror = () => reject(new Error('This photograph could not be read.'));
      reader.readAsDataURL(file);
    });
    const response = await fetchJson('/api/scans/upload', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filename: file.name, label: file.name.replace(/\.[^.]+$/, ''), mime_type: file.type, data }) });
    if (Array.isArray(response.scans)) app.state.scans = response.scans;
    else if (response.scan) app.state.scans.push(response.scan);
    if (response.scan) app.selectedScanId = response.scan.id;
    renderScanLibrary();
    if (['layout', 'scans'].includes(app.workspace)) renderScans();
    return response;
  }

  function updateSync(message, tone) {
    $('#sync-message').textContent = message;
    $('#sync-time').textContent = `Updated ${nowTime()}`;
    $('#footer-sync').textContent = nowTime();
    $('#sync-ribbon').dataset.tone = tone || '';
  }

  function selectedTrain() {
    return app.state.trains.find((train) => train.id === app.selectedTrainId) || app.state.trains[0] || null;
  }

  function selectedBlock() {
    return app.state.layout.blocks.find((block) => block.id === app.selectedBlockId) || app.state.layout.blocks[0] || null;
  }

  function trainControlMode(train) {
    const mode = String(train.mode || '').trim().toLowerCase();
    if (mode === 'automatic') return 'automatic';
    if (mode === 'stopped' || mode === 'stop' || mode === 'safe') return 'stopped';
    if (String(train.class || '').trim().toLowerCase() === 'automatic') return 'automatic';
    if (String(train.class || '').trim().toLowerCase() === 'stopped') return 'stopped';
    return 'manual';
  }

  function trainStatusForMode(train, mode) {
    return mode === 'stopped' ? 'Stopped' : Number(train.speed) > 0 ? 'Running' : 'Ready';
  }

  function layoutAssetDefinition(kind) {
    return LAYOUT_ASSET_DEFINITIONS[kind] || LAYOUT_ASSET_DEFINITIONS.station;
  }

  function layoutAssetCollection(kind) {
    const definition = layoutAssetDefinition(kind);
    if (!Array.isArray(app.state.layout[definition.collection])) app.state.layout[definition.collection] = [];
    return app.state.layout[definition.collection];
  }

  function assetIdsMatch(left, right) {
    return String(left || '').toLowerCase() === String(right || '').toLowerCase();
  }

  function assetFieldValue(record, key) {
    const aliases = ASSET_FIELD_ALIASES[key] || [key];
    const source = aliases.find((alias) => record && record[alias] != null);
    return source ? record[source] : '';
  }

  function assetFieldText(record, key) {
    const value = assetFieldValue(record, key);
    return Array.isArray(value) ? value.join(', ') : String(value == null ? '' : value);
  }

  function assetFieldTarget(record, key) {
    const aliases = ASSET_FIELD_ALIASES[key] || [key];
    return aliases.find((alias) => record && Object.prototype.hasOwnProperty.call(record, alias)) || key;
  }

  function assetFieldIsList(key) {
    return ['blockIds', 'platformIds', 'waypointIds', 'connected_node_ids', 'connected_block_ids'].includes(key);
  }

  function nextLayoutAssetId(kind) {
    const definition = layoutAssetDefinition(kind);
    const records = layoutAssetCollection(kind);
    let number = records.length + 1;
    let id = `${definition.prefix}${String(number).padStart(2, '0')}`;
    while (records.some((record) => assetIdsMatch(record.id, id))) {
      number += 1;
      id = `${definition.prefix}${String(number).padStart(2, '0')}`;
    }
    return id;
  }

  function newLayoutAsset(kind) {
    const firstBlock = (app.state.layout.blocks || [])[0];
    const secondBlock = (app.state.layout.blocks || [])[1] || firstBlock;
    const firstStation = (app.state.layout.stations || [])[0];
    const id = nextLayoutAssetId(kind);
    const defaults = { id, name: `${layoutAssetDefinition(kind).label} ${id}` };
    if (kind === 'station') Object.assign(defaults, { blockIds: [], platformIds: [], waypointIds: [] });
    if (kind === 'signal') Object.assign(defaults, { address: '', block_id: firstBlock ? firstBlock.id : '', protects_block_id: secondBlock ? secondBlock.id : '', aspect: 'red' });
    if (kind === 'turnout') Object.assign(defaults, { address: '', from: firstBlock ? firstBlock.id : '', to: secondBlock ? secondBlock.id : '', alternate: (app.state.layout.blocks || [])[2]?.id || '', state: 'straight' });
    if (kind === 'waypoint') Object.assign(defaults, { x: 490, y: 175, connected_node_ids: [] });
    if (kind === 'turntable') Object.assign(defaults, { address: '', connected_block_ids: firstBlock ? [firstBlock.id] : [], aligned_block_id: firstBlock ? firstBlock.id : '', x: 490, y: 175 });
    if (kind === 'platform') Object.assign(defaults, { stationId: firstStation ? firstStation.id : '', blockId: firstBlock ? firstBlock.id : '', lengthMm: 0 });
    return defaults;
  }

  function renderLayoutAssetForm(record) {
    const kind = $('#layout-asset-kind').value;
    const definition = layoutAssetDefinition(kind);
    const current = record || newLayoutAsset(kind);
    $('#layout-asset-form-title').textContent = `${app.layoutAssetEditing ? 'Edit' : 'Add'} ${definition.label.toLowerCase()}`;
    $('#layout-asset-form-state').textContent = app.layoutAssetEditing ? 'Editing' : 'New';
    $('#save-layout-asset').textContent = app.layoutAssetEditing ? 'Save changes' : 'Create record';
    $('#layout-asset-fields').innerHTML = definition.fields.map((field) => {
      const value = assetFieldText(current, field.key);
      const classes = field.wide ? 'field field-wide' : 'field';
      const required = field.required ? ' required' : '';
      const input = field.type === 'select'
        ? `<select id="${field.id}" data-asset-field="${field.key}"${required}>${field.options.map(([optionValue, label]) => `<option value="${optionValue}"${String(value || 'red') === optionValue ? ' selected' : ''}>${label}</option>`).join('')}</select>`
        : `<input id="${field.id}" data-asset-field="${field.key}" type="${field.type || 'text'}"${field.min != null ? ` min="${field.min}"` : ''}${field.step != null ? ` step="${field.step}"` : ''}${required} value="${escapeHtml(value)}" placeholder="${escapeHtml(field.placeholder || '')}">`;
      return `<div class="${classes}"><label for="${field.id}">${field.label}${field.required ? ' *' : ''}</label>${input}</div>`;
    }).join('');
  }

  function layoutAssetSummary(kind, record) {
    const values = {
      station: [assetFieldText(record, 'blockIds'), assetFieldText(record, 'platformIds')].filter(Boolean).join(' · '),
      signal: [assetFieldText(record, 'aspect') || 'red', assetFieldText(record, 'block_id')].filter(Boolean).join(' · '),
      waypoint: [`${assetFieldText(record, 'x') || 0}, ${assetFieldText(record, 'y') || 0}`],
      turntable: [assetFieldText(record, 'aligned_block_id') ? `aligned ${assetFieldText(record, 'aligned_block_id')}` : '', assetFieldText(record, 'connected_block_ids')].filter(Boolean).join(' · '),
      platform: [assetFieldText(record, 'stationId'), assetFieldText(record, 'blockId')].filter(Boolean).join(' · ')
    };
    values.turnout = [assetFieldText(record, 'from'), assetFieldText(record, 'to'), assetFieldText(record, 'alternate')].filter(Boolean).join(' -> ') || assetFieldText(record, 'state') || 'No references configured';
    const summary = values[kind];
    return (Array.isArray(summary) ? summary.join('') : '') || 'No references configured';
  }

  function renderLayoutAssetInspector() {
    const kindSelect = $('#layout-asset-kind');
    const list = $('#layout-asset-list');
    if (!kindSelect || !list) return;
    const kind = kindSelect.value;
    const definition = layoutAssetDefinition(kind);
    const records = layoutAssetCollection(kind);
    $('#layout-asset-list-title').textContent = definition.plural;
    $('#layout-asset-count').textContent = records.length;
    list.innerHTML = records.length ? records.map((record) => {
      const id = String(record.id || '');
      const name = record.name || id || `Unnamed ${definition.label.toLowerCase()}`;
      const editing = app.layoutAssetEditing && app.layoutAssetEditing.kind === kind && assetIdsMatch(app.layoutAssetEditing.id, id);
      return `<div class="asset-row${editing ? ' is-editing' : ''}"><div class="asset-row-main"><strong><span class="asset-row-id">${escapeHtml(id)}</span>${escapeHtml(name)}</strong><small>${escapeHtml(layoutAssetSummary(kind, record))}</small></div><div class="asset-row-actions"><button type="button" class="icon-button asset-edit" data-asset-action="edit" data-asset-id="${escapeHtml(id)}" aria-label="Edit ${escapeHtml(name)}">✎</button><button type="button" class="icon-button asset-remove" data-asset-action="remove" data-asset-id="${escapeHtml(id)}" aria-label="Remove ${escapeHtml(name)}">×</button></div></div>`;
    }).join('') : `<div class="asset-empty">No ${definition.plural.toLowerCase()} configured. Use <strong>Add asset</strong> to create the first record.</div>`;
    if (!app.layoutAssetEditing && !$('#layout-assets-editor').open) renderLayoutAssetForm(newLayoutAsset(kind));
  }

  function openLayoutAssetsEditor(kind, record) {
    const editor = $('#layout-assets-editor');
    if (!editor) return;
    $('#layout-asset-kind').value = kind || $('#layout-asset-kind').value || 'station';
    app.layoutAssetEditing = record ? { kind: $('#layout-asset-kind').value, id: record.id } : null;
    try {
      renderLayoutAssetInspector();
      renderLayoutAssetForm(record || newLayoutAsset($('#layout-asset-kind').value));
    } catch (error) {
      // Keep the inspector usable even when a partially configured record has
      // a malformed optional field; the backend remains the validation source.
      showToast('Some layout asset data needs attention.', 'warning');
    }
    if (typeof editor.showModal === 'function') editor.showModal();
    else editor.setAttribute('open', 'open');
    const firstField = $(`#${app.layoutAssetEditing ? 'asset-name' : 'asset-id'}`);
    if (firstField) firstField.focus();
  }

  function closeLayoutAssetsEditor() {
    app.layoutAssetEditing = null;
    const editor = $('#layout-assets-editor');
    if (editor && typeof editor.close === 'function') editor.close();
    else if (editor) editor.removeAttribute('open');
  }

  function assetFormValue(field) {
    const input = $(`#${field.id}`);
    if (!input) return '';
    if (assetFieldIsList(field.key)) return input.value.split(',').map((value) => value.trim()).filter(Boolean).filter((value, index, values) => values.indexOf(value) === index);
    if (field.type === 'number') return input.value.trim() === '' ? null : Number(input.value);
    return input.value.trim();
  }

  function setAssetRecordField(record, field, value) {
    const aliases = ASSET_FIELD_ALIASES[field.key] || [field.key];
    const target = assetFieldTarget(record, field.key);
    aliases.forEach((alias) => { if (alias !== target) delete record[alias]; });
    record[target] = value;
  }

  async function saveLayoutAsset(event) {
    event.preventDefault();
    const form = $('#layout-asset-form');
    if (!form.reportValidity()) return;
    const kind = $('#layout-asset-kind').value;
    const definition = layoutAssetDefinition(kind);
    const editing = app.layoutAssetEditing;
    const records = layoutAssetCollection(kind);
    const existing = editing ? records.find((record) => assetIdsMatch(record.id, editing.id)) : null;
    const record = existing ? { ...existing } : {};
    definition.fields.forEach((field) => setAssetRecordField(record, field, assetFormValue(field)));
    record.id = String(record.id || '').trim();
    if (!record.id) return;
    if (!existing && records.some((item) => assetIdsMatch(item.id, record.id))) {
      showToast(`${definition.label} ID already exists.`, 'warning');
      return;
    }
    if (!record.name) record.name = record.id;
    if (existing) records[records.indexOf(existing)] = record;
    else records.push(record);
    renderAll();
    closeLayoutAssetsEditor();
    const command = { type: LAYOUT_ASSET_COMMANDS[kind][existing ? 'update' : 'add'], [kind]: record };
    if (existing) command[`${kind}_id`] = existing.id;
    await sendCommand(command);
    showToast(`${record.name} ${existing ? 'updated' : 'added'}`, 'success');
  }

  async function removeLayoutAsset(kind, id) {
    const definition = layoutAssetDefinition(kind);
    const records = layoutAssetCollection(kind);
    const index = records.findIndex((record) => assetIdsMatch(record.id, id));
    if (index < 0) return;
    const record = records[index];
    if (!window.confirm(`Remove ${record.name || record.id || definition.label}?`)) return;
    records.splice(index, 1);
    if (app.layoutAssetEditing && app.layoutAssetEditing.kind === kind && assetIdsMatch(app.layoutAssetEditing.id, id)) closeLayoutAssetsEditor();
    renderAll();
    await sendCommand({ type: LAYOUT_ASSET_COMMANDS[kind].remove, [`${kind}_id`]: id });
    showToast(`${record.name || record.id || definition.label} removed`, 'success');
  }

  function renderAll() {
    renderConnection();
    renderSidebar();
    renderGraph();
    renderPinboardTrainPicker();
    renderSystematicView();
    if (['layout', 'scans'].includes(app.workspace)) renderScans();
    renderScanLibrary();
    renderTrainList();
    renderEditor();
    renderSchedules();
    renderRoutes();
    renderAssembler();
    renderCalibration();
    renderInventory();
    renderProgramming();
    renderRecording();
    renderAutomationStudio();
    renderStats();
    renderConnectionEditor();
    renderLayoutAssetInspector();
    updateWorkspaceVisibility();
  }

  function renderCalibration() {
    const select = $('#calibration-train-select');
    if (!select) return;
    const trains = app.state.trains || [];
    select.innerHTML = trains.map((train) => '<option value="' + escapeHtml(train.id) + '">' + escapeHtml(train.name || ('Train ' + (train.number || train.id))) + ' · #' + escapeHtml(train.number || '—') + '</option>').join('');
    if (trains.some((train) => train.id === app.selectedTrainId)) select.value = app.selectedTrainId;
    const state = app.state.calibration || {};
    const active = state.active;
    const runStatus = active ? String(active.status || 'running') : 'ready';
    $('#calibration-state').textContent = active ? runStatus.toUpperCase() : 'Ready';
    $('#calibration-status').textContent = active
      ? (active.error ? 'Calibration failed: ' + active.error : active.status === 'recorded' ? 'Measurement stored.' : 'Run ' + active.run_id + ' · ' + active.status + '.')
      : 'No calibration run yet.';
    $('#start-calibration').disabled = Boolean(active && active.status === 'running') || !trains.length || app.state.track_power === false;
    $('#cancel-calibration').disabled = !(active && active.status === 'running');
    $('#record-calibration').disabled = !(active && active.status === 'completed');
    const history = Array.isArray(state.history) ? state.history : [];
    $('#calibration-history').innerHTML = history.length
      ? '<small>Recent measurements</small>' + history.slice(0, 4).map((item) => '<div><span>' + escapeHtml(item.train_id) + '</span><strong>' + escapeHtml(String(item.measured_distance_mm)) + ' mm</strong><small>' + escapeHtml(String(item.speed_kmh)) + ' km/h · ' + escapeHtml(String(item.duration_ms)) + ' ms</small></div>').join('')
      : '<small>No stored measurements for this controller yet.</small>';
  }

  function renderInventory() {
    const host = $('#inventory-list');
    if (!host) return;
    const inventory = app.state.rollingStockInventory || {};
    const items = rollingStockCatalogue();
    const total = inventory.total != null ? inventory.total : items.reduce((sum, item) => sum + Number(item.count || 0), 0);
    $('#inventory-summary').textContent = `${total} vehicle${total === 1 ? '' : 's'}`;
    const query = String($('#inventory-search')?.value || '').trim().toLowerCase();
    const filtered = items.filter((item) => !query || [item.id, item.name, item.type, item.manufacturer, item.model, item.length_mm].some((value) => String(value ?? '').toLowerCase().includes(query)));
    host.innerHTML = filtered.length ? filtered.map((item) => `<div class="inventory-row" data-inventory-id="${escapeHtml(item.id)}"><span><strong>${escapeHtml(item.name || item.id || 'Rolling stock')}</strong><small>${escapeHtml(item.manufacturer || '')}${item.model ? ` · ${escapeHtml(item.model)}` : ''}${item.length_mm ? ` · ${escapeHtml(item.length_mm)} mm` : ''}</small></span><span class="inventory-type">${escapeHtml(item.type || 'rolling stock')}</span><span class="inventory-stepper"><button type="button" class="icon-button small" data-inventory-adjust="-1" aria-label="Decrease quantity">−</button><span class="inventory-count">×${escapeHtml(Number(item.count || 0))}</span><button type="button" class="icon-button small" data-inventory-adjust="1" aria-label="Increase quantity">+</button></span></div>`).join('') : `<div class="empty-state">${query ? 'No catalogue entries match that search.' : 'No rolling stock is assigned to a saved consist yet.'}</div>`;
  }

  async function saveInventory() {
    const itemId = $('#inventory-id').value.trim();
    const name = $('#inventory-name').value.trim();
    const quantity = Number($('#inventory-quantity').value);
    const length = Number($('#inventory-length').value);
    if (!itemId || !name || !Number.isInteger(quantity) || quantity < 0 || !Number.isFinite(length) || length < 0) {
      showToast('Enter a catalogue ID, name, length, and non-negative whole quantity.', 'warning');
      return;
    }
    await sendCommand({ type: 'upsert_rolling_stock_inventory', item_id: itemId, name, vehicle_type: $('#inventory-type').value, quantity, length_mm: length });
  }

  function renderRecording() {
    const select = $('#recording-train-select');
    const status = $('#recording-status');
    if (!select || !status) return;
    const trains = app.state.trains || [];
    select.innerHTML = trains.map((train) => `<option value="${escapeHtml(train.id)}">${escapeHtml(train.name || train.id)}</option>`).join('');
    if (trains.some((train) => train.id === app.selectedTrainId)) select.value = app.selectedTrainId;
    const state = app.state.recording || {};
    const active = state.active;
    $('#start-recording').disabled = Boolean(active);
    $('#stop-recording').disabled = !active;
    $('#play-recording').disabled = !Array.isArray(state.history) || !state.history.length || Boolean(active);
    status.textContent = active
      ? `Recording ${active.train_id} · ${active.actions.length} action${active.actions.length === 1 ? '' : 's'}`
      : state.history && state.history.length ? `${state.history.length} saved plan${state.history.length === 1 ? '' : 's'} · ready to play` : 'No recording yet.';
    $('#recording-live-indicator')?.classList.toggle('is-active', Boolean(active));
  }

  async function startRecording() {
    const trainId = $('#recording-train-select').value;
    if (trainId) await sendCommand({ type: 'start_recording', train_id: trainId });
  }

  async function stopRecording() { await sendCommand({ type: 'stop_recording' }); }

  async function playRecording() {
    if (!window.confirm('Play the last recorded train actions now? The train will be stopped when playback finishes.')) return;
    await sendCommand({ type: 'play_recording', index: Math.max(0, ((app.state.recording || {}).history || []).length - 1), confirm: true, automatic: true });
  }

  function automationNewBlock(type) {
    const id = `automation-block-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
    if (type === 'drive') return { id, type, speed_kmh: 10, duration_s: 12 };
    if (type === 'speed_ramp') return { id, type, start_speed_kmh: 0, end_speed_kmh: 20, duration_s: 5 };
    if (type === 'travel') return { id, type, distance_cm: 20, speed_kmh: 10 };
    if (type === 'wait') return { id, type, duration_s: 2 };
    if (type === 'direction') return { id, type, direction: 'forward' };
    if (type === 'function') return { id, type, function_number: 0, enabled: false };
    return { id, type: 'stop' };
  }

  function automationBlockSummary(block) {
    if (block.type === 'drive') return `Drive at ${Number(block.speed_kmh || 0)} km/h for ${Number(block.duration_s || 0)} s`;
    if (block.type === 'speed_ramp') return `Ramp from ${Number(block.start_speed_kmh || 0)} to ${Number(block.end_speed_kmh || 0)} km/h over ${Number(block.duration_s || 0)} s`;
    if (block.type === 'travel') {
      const record = ((app.state.calibration || {}).history || []).find((item) => item.train_id === app.automationDraft.trainId);
      const distance = Number(block.distance_cm || 0);
      const speed = Number(block.speed_kmh || 0);
      const duration = record && distance > 0 && speed > 0 && Number(record.measured_distance_mm) > 0
        ? distance * 10 * Number(record.duration_ms) * Number(record.speed_kmh) / (Number(record.measured_distance_mm) * speed * 1000)
        : null;
      return `Travel ${distance} cm at ${speed} km/h${duration == null ? '' : ` · ${duration.toFixed(2)} s`}`;
    }
    if (block.type === 'wait') return `Wait for ${Number(block.duration_s || 0)} s`;
    if (block.type === 'direction') return `Set direction to ${block.direction || 'forward'}`;
    if (block.type === 'function') return `Function F${Number(block.function_number || 0)} ${block.enabled ? 'on' : 'off'}`;
    return 'Stop the train';
  }

  function automationBlockFields(block, index) {
    const field = (label, name, value, type = 'number', extra = '') => `<label>${label}<input type="${type}" data-automation-index="${index}" data-automation-field="${name}" value="${escapeHtml(value)}" ${extra}></label>`;
    if (block.type === 'drive') return field('Speed km/h', 'speed_kmh', Number(block.speed_kmh || 0), 'number', 'min="0" step="0.1"') + field('Duration seconds', 'duration_s', Number(block.duration_s || 0), 'number', 'min="0" step="0.1"');
    if (block.type === 'speed_ramp') return field('Start speed km/h', 'start_speed_kmh', Number(block.start_speed_kmh || 0), 'number', 'min="0" step="0.1"') + field('End speed km/h', 'end_speed_kmh', Number(block.end_speed_kmh || 0), 'number', 'min="0" step="0.1"') + field('Ramp time seconds', 'duration_s', Number(block.duration_s || 0), 'number', 'min="0" step="0.1"');
    if (block.type === 'travel') return field('Distance cm', 'distance_cm', Number(block.distance_cm || 0), 'number', 'min="0.1" step="0.1"') + field('Speed km/h', 'speed_kmh', Number(block.speed_kmh || 0), 'number', 'min="0.1" step="0.1"') + `<span class="automation-calibration-note">${escapeHtml(automationTravelCalibrationNote(block))}</span>`;
    if (block.type === 'wait') return field('Duration seconds', 'duration_s', Number(block.duration_s || 0), 'number', 'min="0" step="0.1"');
    if (block.type === 'direction') return `<label>Direction<select data-automation-index="${index}" data-automation-field="direction"><option value="forward" ${block.direction === 'forward' ? 'selected' : ''}>Forward</option><option value="reverse" ${block.direction === 'reverse' ? 'selected' : ''}>Reverse</option></select></label>`;
    if (block.type === 'function') return field('Function number', 'function_number', Number(block.function_number || 0), 'number', 'min="0" max="31" step="1"') + `<label>State<select data-automation-index="${index}" data-automation-field="enabled"><option value="false" ${!block.enabled ? 'selected' : ''}>Off</option><option value="true" ${block.enabled ? 'selected' : ''}>On</option></select></label>`;
    return '<span class="automation-stop-note">The controller will command a full stop here.</span>';
  }

  function automationTravelCalibrationNote(block) {
    const record = ((app.state.calibration || {}).history || []).find((item) => item.train_id === app.automationDraft.trainId);
    if (!record) return 'Record motion calibration for this train first.';
    const distance = Number(block.distance_cm || 0);
    const speed = Number(block.speed_kmh || 0);
    if (!(distance > 0) || !(speed > 0) || !(Number(record.measured_distance_mm) > 0) || !(Number(record.speed_kmh) > 0)) return 'Enter a distance and speed to estimate time.';
    const seconds = distance * 10 * Number(record.duration_ms) * Number(record.speed_kmh) / (Number(record.measured_distance_mm) * speed * 1000);
    return `Estimated movement: ${seconds.toFixed(2)} s using ${record.speed_kmh} km/h calibration.`;
  }

  function renderAutomationStudio() {
    const trainSelect = $('#automation-train-select');
    const list = $('#automation-block-list');
    if (!trainSelect || !list) return;
    const trains = app.state.trains || [];
    const draft = app.automationDraft;
    if (!trains.some((train) => train.id === draft.trainId)) draft.trainId = (trains.find((train) => train.id === app.selectedTrainId) || trains[0] || {}).id || '';
    trainSelect.innerHTML = trains.map((train) => `<option value="${escapeHtml(train.id)}">${escapeHtml(train.name || train.id)} · #${escapeHtml(train.number || '—')}</option>`).join('');
    trainSelect.value = draft.trainId;
    $('#automation-program-name').value = draft.name || 'New train routine';
    $('#automation-program-title').textContent = draft.name || 'New train routine';
    $('#automation-block-count').textContent = `${draft.blocks.length} block${draft.blocks.length === 1 ? '' : 's'}`;
    list.innerHTML = draft.blocks.map((block, index) => {
      const definition = AUTOMATION_BLOCK_DEFS[block.type] || AUTOMATION_BLOCK_DEFS.stop;
      return `<article class="automation-code-block automation-code-${definition.color} ${app.automationSelectedBlockId === block.id ? 'is-selected' : ''}" data-automation-block-id="${escapeHtml(block.id)}"><div class="automation-block-head"><span class="automation-block-index">${index + 1}</span><div><strong>${escapeHtml(definition.label)}</strong><small>${escapeHtml(automationBlockSummary(block))}</small></div><div class="automation-block-actions"><button type="button" class="icon-button small" data-automation-action="up" data-automation-index="${index}" aria-label="Move block up">Up</button><button type="button" class="icon-button small" data-automation-action="down" data-automation-index="${index}" aria-label="Move block down">Down</button><button type="button" class="icon-button small" data-automation-action="delete" data-automation-index="${index}" aria-label="Delete block">X</button></div></div><div class="automation-block-fields">${automationBlockFields(block, index)}</div></article>`;
    }).join('<div class="automation-connector" aria-hidden="true"></div>');
    $('#automation-empty-state').classList.toggle('is-hidden', draft.blocks.length > 0);
    const programList = $('#automation-program-list');
    programList.innerHTML = app.automationPrograms.length
      ? app.automationPrograms.map((program) => `<div class="automation-program-row" data-automation-program-id="${escapeHtml(program.id)}"><span><strong>${escapeHtml(program.name || program.id)}</strong><small>${escapeHtml(String(program.train_id || ''))} · ${escapeHtml(String((program.blocks || []).length))} blocks · ${escapeHtml(String(program.duration_s || 0))} s</small></span><span class="automation-program-row-actions"><button type="button" class="text-button" data-automation-program-action="load">Load</button><button type="button" class="text-button" data-automation-program-action="run">Run</button><button type="button" class="text-button danger-text" data-automation-program-action="delete">Delete</button></span></div>`).join('')
      : '<p class="settings-help">No saved routines yet. Build one and save it here.</p>';
    renderAutomationPlayback();
  }

  function renderAutomationPlayback() {
    const status = $('#automation-playback-status');
    if (!status) return;
    const runs = app.state.automationPlayback || [];
    const run = runs.find((item) => item.train_id === app.automationDraft.trainId);
    const running = run && run.status === 'running';
    $('#automation-run-program').disabled = Boolean(running || app.automationRunPending);
    $('#automation-stop-program').disabled = !running;
    $$('#automation-program-list [data-automation-program-action="run"]').forEach((button) => {
      const id = button.closest('[data-automation-program-id]').dataset.automationProgramId;
      const program = app.automationPrograms.find((item) => item.id === id);
      button.disabled = app.automationRunPending || runs.some((item) => item.status === 'running' && item.train_id === program?.train_id);
    });
    status.classList.toggle('is-hidden', !run && !app.automationRunPending);
    if (app.automationRunPending && !running) {
      status.textContent = 'Starting routine…';
    } else if (run) {
      const elapsed = Number(run.elapsed_s || 0).toFixed(1);
      const duration = Number(run.duration_s || 0).toFixed(1);
      if (running) status.textContent = `Routine running · ${run.completed_actions} / ${run.action_count} actions · ${elapsed} / ${duration} s. Stop routine to cancel.`;
      else if (run.status === 'completed') status.textContent = 'Routine completed. Stop command sent to the train.';
      else if (run.status === 'failed') status.textContent = `Routine failed: ${run.detail || 'Controller rejected an action.'}`;
      else status.textContent = `Routine cancelled. ${run.detail || ''}`;
    }
  }

  function addAutomationBlock(type) {
    if (!AUTOMATION_BLOCK_DEFS[type]) return;
    const block = automationNewBlock(type);
    app.automationDraft.blocks.push(block);
    app.automationSelectedBlockId = block.id;
    renderAutomationStudio();
  }

  function updateAutomationBlockField(event) {
    const input = event.target.closest('[data-automation-field]');
    if (!input) return;
    const index = Number(input.dataset.automationIndex);
    const block = app.automationDraft.blocks[index];
    if (!block) return;
    const field = input.dataset.automationField;
    if (field === 'enabled') block[field] = input.value === 'true';
    else if (input.type === 'number') block[field] = Number(input.value);
    else block[field] = input.value;
    renderAutomationStudio();
  }

  function automationBlockAction(action, index) {
    const blocks = app.automationDraft.blocks;
    if (!blocks[index]) return;
    if (action === 'delete') blocks.splice(index, 1);
    if (action === 'up' && index > 0) [blocks[index - 1], blocks[index]] = [blocks[index], blocks[index - 1]];
    if (action === 'down' && index < blocks.length - 1) [blocks[index + 1], blocks[index]] = [blocks[index], blocks[index + 1]];
    renderAutomationStudio();
  }

  function importLastRecording() {
    const history = (app.state.recording || {}).history || [];
    const plan = history[history.length - 1];
    if (!plan) { showToast('Record a train routine first.', 'warning'); return; }
    const train = app.state.trains.find((item) => item.id === app.automationDraft.trainId) || selectedTrain();
    const maximum = Math.max(1, Number(train?.maxSpeed || 140));
    const actions = plan.actions || [];
    app.automationDraft.trainId = app.state.trains.some((item) => item.id === plan.train_id) ? plan.train_id : app.automationDraft.trainId;
    app.automationDraft.blocks = actions.map((action, index) => {
      if (action.operation === 'speed') {
        const next = actions[index + 1];
        const duration = next && next.timestamp != null ? Math.max(0, Number(next.timestamp) - Number(action.timestamp)) : 0;
        const speed = Number(action.speed || 0) * maximum;
        return speed > 0 ? { ...automationNewBlock('drive'), speed_kmh: Number(speed.toFixed(1)), duration_s: Number(duration.toFixed(1)) } : automationNewBlock('stop');
      }
      if (action.operation === 'direction') return { ...automationNewBlock('direction'), direction: action.direction || 'forward' };
      return { ...automationNewBlock('function'), function_number: Number(action.function_number || 0), enabled: Boolean(action.enabled) };
    });
    $('#automation-status').textContent = `Imported ${app.automationDraft.blocks.length} blocks from the last recording.`;
    renderAutomationStudio();
  }

  async function saveAutomationProgram() {
    const draft = app.automationDraft;
    draft.name = ($('#automation-program-name').value || '').trim() || 'New train routine';
    if (!draft.trainId || !draft.blocks.length) { $('#automation-status').textContent = 'Choose a train and add at least one action block.'; return false; }
    const id = draft.id || `program-${Date.now()}`;
    const response = await sendCommand({ type: 'save_automation_program', program: { id, name: draft.name, train_id: draft.trainId, blocks: draft.blocks } });
    if (!response) return false;
    draft.id = id;
    $('#automation-status').textContent = `Saved ${draft.name}.`;
    return true;
  }

  async function runAutomationProgram() {
    if (app.automationRunPending || (app.state.automationPlayback || []).some((run) => run.train_id === app.automationDraft.trainId && run.status === 'running')) return;
    app.automationRunPending = true;
    renderAutomationPlayback();
    try {
      if (!app.automationDraft.id && !(await saveAutomationProgram())) return;
      if (!window.confirm('Run this train routine now? The train will be stopped when the routine finishes.')) return;
      await sendCommand({ type: 'play_automation_program', program_id: app.automationDraft.id, confirm: true, automatic: true });
    } finally {
      app.automationRunPending = false;
      renderAutomationPlayback();
    }
  }

  async function stopAutomationProgram() {
    const run = (app.state.automationPlayback || []).find((item) => item.train_id === app.automationDraft.trainId && item.status === 'running');
    if (!run) return;
    await sendCommand({ type: 'stop_automation_playback', train_id: run.train_id });
  }

  function loadAutomationProgram(id) {
    const program = app.automationPrograms.find((item) => item.id === id);
    if (!program) return;
    app.automationDraft = { id: program.id, name: program.name || 'Train routine', trainId: program.train_id || '', blocks: clone(program.blocks || []) };
    app.automationSelectedBlockId = null;
    renderAutomationStudio();
    $('#automation-status').textContent = `Loaded ${app.automationDraft.name}.`;
  }

  async function deleteAutomationProgram(id) {
    const program = app.automationPrograms.find((item) => item.id === id);
    if (!program || !window.confirm(`Delete ${program.name || id}?`)) return;
    await sendCommand({ type: 'delete_automation_program', program_id: id });
    if (app.automationDraft.id === id) app.automationDraft = { id: null, name: 'New train routine', trainId: app.selectedTrainId, blocks: [] };
  }

  function clearAutomationProgram() {
    app.automationDraft = { id: null, name: 'New train routine', trainId: app.selectedTrainId, blocks: [] };
    app.automationSelectedBlockId = null;
    renderAutomationStudio();
  }

  function renderProgramming() {
    const select = $('#programming-train-select');
    if (!select) return;
    const trains = app.state.trains || [];
    select.innerHTML = trains.map((train) => `<option value="${escapeHtml(train.id)}">${escapeHtml(train.name || `Train ${train.number || train.id}`)} · #${escapeHtml(train.number || '—')}</option>`).join('');
    if (trains.some((train) => train.id === app.selectedTrainId)) select.value = app.selectedTrainId;
    const train = trains.find((item) => item.id === select.value) || selectedTrain();
    if (train && $('#programming-address')) $('#programming-address').value = train.address || train.number || '';
    if (train && $('#programming-new-address')) $('#programming-new-address').value = train.address || train.number || '';
    const state = app.state.programming || {};
    const last = state.last_request;
    const lastAddress = state.last_address_request;
    $('#programming-state').textContent = state.supported ? 'Ready' : state.detail || 'Transport unavailable';
    $('#programming-status').textContent = lastAddress
      ? `DCC address ${lastAddress.address} → ${lastAddress.new_address} on ${lastAddress.target === 'programming_track' ? 'programming track' : 'main track'} · ${lastAddress.status || 'request validated'}.`
      : last
      ? `CV${last.cv}=${last.value} for #${last.address} on ${last.target === 'programming_track' ? 'programming track' : 'main track'} · ${last.status || 'request validated'}.`
      : state.detail || 'No programming request validated.';
  }

  async function validateProgramming() {
    const trainId = $('#programming-train-select').value;
    if (!trainId) return;
    const command = {
      type: 'validate_programming',
      train_id: trainId,
      address: Number($('#programming-address').value),
      target: $('#programming-target').value,
      cv: Number($('#programming-cv').value),
      value: Number($('#programming-value').value),
    };
    if (![command.address, command.cv, command.value].every(Number.isFinite)) {
      showToast('Enter a valid DCC address, CV, and value.', 'warning');
      return;
    }
    await sendCommand(command);
  }

  function programmingCommand(type) {
    return {
      type,
      train_id: $('#programming-train-select').value,
      address: Number($('#programming-address').value),
      target: $('#programming-target').value,
      cv: Number($('#programming-cv').value),
      value: Number($('#programming-value').value),
    };
  }

  async function writeProgramming() {
    const command = programmingCommand('program_decoder');
    const target = command.target === 'programming_track' ? 'programming track' : 'main track';
    const message = `Write CV${command.cv}=${command.value} to DCC address ${command.address} on the ${target}? This can change decoder settings.`;
    if (!command.train_id || ![command.address, command.cv, command.value].every(Number.isFinite) || !window.confirm(message)) return;
    await sendCommand({ ...command, confirm: true });
  }

  async function readProgramming() {
    const command = programmingCommand('read_decoder_cv');
    if (!command.train_id || ![command.address, command.cv].every(Number.isFinite)) {
      showToast('Enter a valid train, DCC address, and CV first.', 'warning');
      return;
    }
    await sendCommand(command);
  }

  async function programDccAddress() {
    const trainId = $('#programming-train-select').value;
    const address = Number($('#programming-address').value);
    const newAddress = Number($('#programming-new-address').value);
    const target = $('#programming-target').value;
    if (!trainId || ![address, newAddress].every(Number.isInteger) || address < 1 || newAddress < 1) {
      showToast('Enter the current and new DCC addresses first.', 'warning');
      return;
    }
    const targetLabel = target === 'programming_track' ? 'programming track' : 'main track';
    if (!window.confirm(`Program DCC address ${newAddress} for decoder ${address} on the ${targetLabel}? The locomotive will use the new address after programming.`)) return;
    await sendCommand({ type: 'program_dcc_address', train_id: trainId, address, new_address: newAddress, target, confirm: true });
  }

  async function startCalibration() {
    const trainId = $('#calibration-train-select').value;
    if (!trainId) return;
    await sendCommand({ type: 'start_calibration', train_id: trainId, speed_kmh: 10, duration_ms: 100 });
  }

  async function recordCalibration() {
    const input = $('#calibration-distance');
    if (!input.value || !input.checkValidity()) { input.reportValidity(); return; }
    await sendCommand({ type: 'record_calibration', distance_mm: Number(input.value), notes: $('#calibration-notes').value.trim() });
    input.value = '';
    $('#calibration-notes').value = '';
  }

  function renderConnection() {
    const connection = app.state.connection || {};
    const dot = $('#connection-dot');
    dot.className = `status-dot ${connection.connected ? '' : connection.simulated ? 'is-simulated' : 'is-offline'}`;
    const runtimeProfile = runtimeTransportProfile(app.settingsRuntime);
    const connectedViaWlan = connection.connected && (runtimeProfile == null ? Boolean(app.settings.z21_wlan_enabled) : profileUsesWlan(runtimeProfile));
    const genericLabel = !connection.label || /^(Z21 connected|Controller online)$/i.test(connection.label);
    $('#connection-label').textContent = connectedViaWlan && genericLabel ? 'Z21 via WLAN' : connection.label || (connection.connected ? 'Controller online' : 'Simulation fallback');
    $('#connection-detail').textContent = connection.detail || '';
    $('#connection-detail').hidden = app.settings.interface.show_connection_detail === false;
    const feedback = app.state.feedback || {};
    const feedbackFailed = feedback.healthy === false;
    $('#health-score').textContent = feedbackFailed ? 'Check' : connection.simulated ? 'Simulation' : connection.connected ? 'Online' : 'Offline';
    $('#feedback-health').textContent = feedbackFailed ? 'Unavailable' : connection.connected ? 'Live feedback' : connection.simulated ? 'Simulated' : 'Unknown';
    $('#checker-health').textContent = feedbackFailed ? 'Safe stop required' : connection.connected ? 'Verified' : 'Standby';
    $('#footer-source').textContent = feedbackFailed ? 'Feedback unavailable · safe stop' : connection.connected ? 'Z21 API connected' : connection.simulated ? 'Simulation API' : 'Embedded sample state';
    $('.footer-indicator').style.background = feedbackFailed ? 'var(--red)' : connection.connected ? 'var(--green)' : 'var(--yellow)';
  }

  function renderSidebar() {
    renderWorldClock();
    const train = selectedTrain();
    if (!train) return;
    const selectedMode = trainControlMode(train);
    app.controlMode = selectedMode === 'stopped' ? 'safe' : selectedMode;
    const direction = String(train.direction || '').toLowerCase();
    const directionLocked = app.directionPending || app.speedSending || (speedDraft && speedDraft.speed > 0) || Number(train.speed) > 0 || Number(train.actual_speed_kmh) > 0 || Number(train.motion && train.motion.requested_speed) > 0 || trainControlMode(train) === 'automatic' || app.source !== 'api';
    ['forward', 'reverse'].forEach((value) => {
      const button = $(`#direction-${value}`);
      button.setAttribute('aria-pressed', String(direction === value));
      button.disabled = Boolean(directionLocked);
    });
    $('#direction-status').textContent = app.directionPending ? 'Sending direction…' : app.speedSending ? 'Waiting for speed confirmation…' : trainControlMode(train) === 'automatic' ? 'Switch this train to manual to change direction.' : Number(train.speed) > 0 || Number(train.actual_speed_kmh) > 0 ? 'Stop and wait for the train to halt before reversing.' : 'Choose decoder direction. Speed stays at zero.';
    $('#selected-train-name').textContent = train.name || `Train ${train.number || ''}`;
    $('#selected-train-badge').textContent = train.number || '—';
    $('#selected-train-origin').textContent = train.origin || 'Origin';
    $('#selected-train-destination').textContent = train.destination || 'Destination';
    const dialSpeed = speedChoices.has(train.id) ? speedChoices.get(train.id) : Number(train.speed) || 0;
    $('#speed-readout').textContent = Math.round(dialSpeed);
    $('#speed-slider').max = Number(train.maxSpeed || 140);
    $('#speed-slider').value = Math.round(dialSpeed);
    $('#speed-slider').disabled = app.source !== 'api' || app.state.track_power === false || app.nativeModePending || app.powerPending || app.controlPending;
    $('#speed-command-status').textContent = `${train.actual_speed_kmh == null ? 'Commanded' : 'Actual'} ${Math.round(Number(train.actual_speed_kmh ?? train.speed) || 0)} km/h${train.speed_limit_kmh == null ? '' : ` · limit ${train.speed_limit_kmh} km/h`} · auto-applies`;
    renderSelectedTrainFunctions(train);
    $('#simulation-clock').textContent = app.state.simulation.clock || '00:00:00';
    $('#simulation-date').textContent = app.state.simulation.date || 'Simulation date';
    $('#simulation-rate').textContent = !app.state.connection.simulated || app.simRate === 1 ? 'Real time' : `Real time · ${app.simRate}× step`;
    $('#simulation-state').textContent = app.state.simulation.running ? 'RUNNING' : 'PAUSED';
    $('#simulation-toggle').textContent = app.state.simulation.running ? 'Pause' : 'Resume';
    $('#track-power-toggle').textContent = app.powerPending ? 'Changing power…' : app.state.track_power === false ? 'Power on' : 'Power off';
    $('#track-power-toggle').disabled = Boolean(app.powerPending);
    $('#layout-power-toggle').onclick = toggleTrackPower;
    $('#simulation-rate-select').value = String(app.simRate);
    $('#simulation-rate-select').disabled = !app.state.connection.simulated;
    $('#simulation-tick').title = 'Advance one real minute of model time. Scheduled departures crossed by this step may start trains.';
    $$('.control-mode').forEach((button) => button.classList.toggle('is-active', button.dataset.controlMode === app.controlMode));
    $$('.mode-tab').forEach((button) => button.classList.toggle('is-active', button.dataset.workspace === app.workspace));
  }

  function renderSelectedTrainFunctions(train) {
    const grid = $('#selected-train-functions');
    const status = $('#selected-train-function-status');
    const count = $('#selected-train-function-count');
    if (!grid || !status || !count) return;
    const assigned = (Array.isArray(train.decoder_functions) ? train.decoder_functions : [])
      .filter((item) => item && item.enabled !== false && Number.isInteger(Number(item.function_number)))
      .filter((item) => Number(item.function_number) >= 0 && Number(item.function_number) <= 31)
      .sort((left, right) => Number(left.function_number) - Number(right.function_number));
    const states = train.decoder_function_states && typeof train.decoder_function_states === 'object' ? train.decoder_function_states : {};
    count.textContent = `${assigned.length} assigned`;
    status.classList.toggle('is-hidden', assigned.length > 0);
    grid.innerHTML = assigned.map((item) => {
      const number = Number(item.function_number);
      const enabled = Boolean(states[String(number)]);
      const label = item.name || item.function_name || item.description || `Function F${number}`;
      const momentary = item.momentary ? ' - momentary' : '';
      const disabled = app.source !== 'api' || app.state.track_power === false;
      return `<button type="button" class="button button-soft train-function-button${enabled ? ' is-on' : ''}" data-train-function="${number}" aria-pressed="${enabled}" title="F${number}: ${escapeHtml(label)}${momentary}"${disabled ? ' disabled' : ''}><span class="train-function-main"><strong>F${number}</strong><small>${escapeHtml(label)}</small></span><em>${enabled ? 'ON' : 'OFF'}</em></button>`;
    }).join('');
  }

  function blockCenter(block) {
    return { x: Number(block.x || 0) + Number(block.width || 100) / 2, y: Number(block.y || 0) + Number(block.height || 50) / 2 };
  }

  function edgeControlPoints(from, to, edge) {
    const controls = Array.isArray(edge && (edge.control_points || edge.controlPoints))
      ? (edge.control_points || edge.controlPoints).map((point) => {
        const anchor = (app.state.layout.waypoints || []).find((item) => String(item.id).toUpperCase() === String(point.id).toUpperCase()) || point;
        return { id: point.id, x: Number(anchor.x), y: Number(anchor.y) };
      }).filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y))
      : [];
    const points = [{ ...blockCenter(from), id: from.id }, ...controls, { ...blockCenter(to), id: to.id }];
    points.segments = edge && edge.bezier_segments || points.slice(0, -1).map((point, index) => ({
      start_anchor_id: String(point.id || '').toUpperCase(), end_anchor_id: String(points[index + 1].id || '').toUpperCase() }));
    return points;
  }

  function reverseSplineEdge(edge) {
    return { ...edge, control_points: [...(edge.control_points || edge.controlPoints || [])].reverse(),
      bezier_segments: edge.bezier_segments && [...edge.bezier_segments].reverse().map((section) => ({ ...section,
        start_anchor_id: section.end_anchor_id, end_anchor_id: section.start_anchor_id,
        control1: section.control2, control2: section.control1 })) };
  }

  function splineControls(points, index) {
    const start = points[index]; const end = points[index + 1];
    const previous = points[index - 1] || start; const next = points[index + 2] || end;
    const section = (points.segments || [])[index] || {};
    const middleX = (start.x + end.x) / 2;
    let c1 = points.length === 2 ? { x: middleX, y: start.y } : { x: start.x + (end.x - previous.x) / 6, y: start.y + (end.y - previous.y) / 6 };
    let c2 = points.length === 2 ? { x: middleX, y: end.y } : { x: end.x - (next.x - start.x) / 6, y: end.y - (next.y - start.y) / 6 };
    if (section.control1) c1 = { x: start.x + Number(section.control1.x), y: start.y + Number(section.control1.y) };
    if (section.control2) c2 = { x: end.x + Number(section.control2.x), y: end.y + Number(section.control2.y) };
    const drag = app.splineHandleDrag;
    if (drag && [section.start_anchor_id, section.end_anchor_id].every((id) => [drag.section.start_anchor_id, drag.section.end_anchor_id].includes(id))) {
      if (section.start_anchor_id === drag.anchorId) c1 = drag.point;
      else c2 = drag.point;
    }
    return { c1, c2 };
  }

  function splineSegmentPath(points, index) {
    const start = points[index]; const end = points[index + 1];
    const { c1, c2 } = splineControls(points, index);
    return `M ${start.x} ${start.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${end.x} ${end.y}`;
  }

  function splinePath(points) {
    if (points.length < 2) return '';
    let path = `M ${points[0].x} ${points[0].y}`;
    for (let index = 0; index < points.length - 1; index += 1) {
      const start = points[index]; const end = points[index + 1];
      const { c1, c2 } = splineControls(points, index);
      path += ` C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${end.x} ${end.y}`;
    }
    return path;
  }

  function splinePointAt(points, index, progress) {
    const start = points[index]; const end = points[index + 1];
    const { c1, c2 } = splineControls(points, index);
    const u = Math.max(0, Math.min(1, progress)); const v = 1 - u;
    return {
      x: v * v * v * start.x + 3 * v * v * u * c1.x + 3 * v * u * u * c2.x + u * u * u * end.x,
      y: v * v * v * start.y + 3 * v * v * u * c1.y + 3 * v * u * u * c2.y + u * u * u * end.y
    };
  }

  function splinePointAtProgress(points, progress) {
    if (points.length < 2) return { x: 0, y: 0, dx: 1, dy: 0 };
    const samples = [];
    let total = 0;
    for (let index = 0; index < points.length - 1; index += 1) {
      const segment = [{ point: splinePointAt(points, index, 0), distance: 0 }];
      for (let step = 1; step <= 24; step += 1) {
        const point = splinePointAt(points, index, step / 24);
        const previous = segment[segment.length - 1].point;
        const distance = Math.hypot(point.x - previous.x, point.y - previous.y);
        total += distance;
        segment.push({ point, distance });
      }
      samples.push(segment);
    }
    if (total <= 0) return { x: points[0].x, y: points[0].y, dx: 1, dy: 0 };
    let remaining = Math.max(0, Math.min(1, progress)) * total;
    for (let index = 0; index < samples.length; index += 1) {
      const segment = samples[index];
      const segmentLength = segment.reduce((sum, item) => sum + item.distance, 0);
      if (remaining > segmentLength && index < samples.length - 1) { remaining -= segmentLength; continue; }
      let travelled = 0;
      for (let sample = 1; sample < segment.length; sample += 1) {
        const step = segment[sample];
        if (travelled + step.distance >= remaining || sample === segment.length - 1) {
          const local = step.distance > 0 ? Math.max(0, Math.min(1, (remaining - travelled) / step.distance)) : 0;
          const previous = segment[sample - 1].point;
          const x = previous.x + (step.point.x - previous.x) * local;
          const y = previous.y + (step.point.y - previous.y) * local;
          return { x, y, dx: step.point.x - previous.x, dy: step.point.y - previous.y };
        }
        travelled += step.distance;
      }
      return { ...segment[segment.length - 1].point, dx: 1, dy: 0 };
    }
    return { ...points[points.length - 1], dx: 1, dy: 0 };
  }

  function edgePath(from, to, edge) {
    const points = edgeControlPoints(from, to, edge);
    return splinePath(points);
  }

  function edgeEndpoints(edge) {
    if (!edge) return { from: '', to: '' };
    return {
      from: edge.from || edge.source || edge.from_block_id || edge.source_block_id || edge.start || '',
      to: edge.to || edge.target || edge.to_block_id || edge.target_block_id || edge.end || ''
    };
  }

  function blockIdLookup(blocks) {
    return Object.fromEntries(blocks.map((block) => [String(block.id || '').toLowerCase(), block.id]));
  }

  function normalizedEdges(layout, blocks) {
    const lookup = blockIdLookup(blocks);
    const rawEdges = Array.isArray(layout.edges) && layout.edges.length ? layout.edges : blocks.flatMap((block) => {
      const from = block.id;
      return (block.neighborIds || block.neighbor_ids || []).map((to) => ({ from, to }));
    });
    return rawEdges.map((edge) => {
      const endpoints = edgeEndpoints(edge);
      return {
        ...edge,
        from: lookup[String(endpoints.from).toLowerCase()],
        to: lookup[String(endpoints.to).toLowerCase()]
      };
    }).filter((edge) => edge.from && edge.to);
  }

  function fitGraphViewport() {
    const layout = app.state.layout;
    const key = app.layoutView === 'pinboard' ? 'pinboard' : 'graph';
    if (key === 'pinboard') {
      const items = [...(layout.blocks || []), ...(layout.waypoints || []), ...(layout.turntables || [])];
      const blocks = layout.blocks || [];
      const blockMap = Object.fromEntries(blocks.map((block) => [block.id, block]));
      normalizedEdges(layout, blocks).forEach((edge) => {
        const points = edgeControlPoints(blockMap[edge.from], blockMap[edge.to], edge);
        points.slice(0, -1).forEach((_, index) => { const { c1, c2 } = splineControls(points, index); items.push(c1, c2); });
      });
      if (!items.length) app.layoutViewports.pinboard = { x: 0, y: 0, width: 980, height: 350 };
      else {
        const left = Math.min(...items.map((item) => Number(item.x) || 0)) - 90;
        const top = Math.min(...items.map((item) => Number(item.y) || 0)) - 70;
        const right = Math.max(...items.map((item) => (Number(item.x) || 0) + (Number(item.width) || 0))) + 90;
        const bottom = Math.max(...items.map((item) => (Number(item.y) || 0) + (Number(item.height) || 0))) + 70;
        app.layoutViewports.pinboard = { x: left, y: top, width: Math.max(980, right - left), height: Math.max(350, bottom - top) };
      }
      app.layoutViewportManual.pinboard = false;
      applyLayoutViewport();
      return;
    }
    const items = [...(layout.blocks || []), ...(layout.waypoints || []), ...(layout.turntables || [])];
    if (!items.length) {
      app.layoutViewports.graph = { x: 0, y: 0, width: 980, height: 350 };
      app.layoutViewportManual.graph = false;
      applyLayoutViewport();
      return;
    }
    const left = Math.min(...items.map((item) => Number(item.x) || 0)) - 70;
    const top = Math.min(...items.map((item) => Number(item.y) || 0)) - 80;
    const right = Math.max(...items.map((item) => (Number(item.x) || 0) + (Number(item.width) || 140))) + 70;
    const bottom = Math.max(...items.map((item) => (Number(item.y) || 0) + (Number(item.height) || 56))) + 65;
    app.layoutViewports.graph = { x: left, y: top, width: Math.max(320, right - left), height: Math.max(220, bottom - top) };
    app.layoutViewportManual.graph = false;
    applyLayoutViewport();
  }

  function applyLayoutViewport() {
    const key = app.layoutView === 'pinboard' ? 'pinboard' : 'graph';
    if (!app.layoutViewports[key]) { fitGraphViewport(); return; }
    const view = app.layoutViewports[key];
    $('#layout-svg').setAttribute('viewBox', `${view.x} ${view.y} ${view.width} ${view.height}`);
  }

  function renderGraph() {
    const layout = app.state.layout;
    $('#layout-panel').classList.toggle('is-editing', app.layoutEditing);
    $('#toggle-layout-edit').textContent = app.layoutEditing ? 'Finish editing' : 'Edit layout';
    if (app.layoutView === 'pinboard') {
      renderPinboard();
      return;
    }
    $('#layout-svg').setAttribute('aria-label', 'Track block node graph');
    const stageMode = $('#map-stage-mode');
    if (stageMode) stageMode.textContent = 'LIVE BLOCK GRAPH';
    const blocks = layout.blocks || [];
    const blockMap = Object.fromEntries(blocks.flatMap((block) => [[block.id, block], [String(block.id || '').toLowerCase(), block]]));
    const edges = normalizedEdges(layout, blocks);
    const edgeMarkup = edges.map((edge) => {
      const path = edgePath(blockMap[edge.from], blockMap[edge.to], edge);
      const status = edge.status || blockMap[edge.from].status || 'free';
      return `<path class="track-edge-outline" d="${path}"></path><path class="track-edge edge-${escapeHtml(status)}" d="${path}"></path>`;
    }).join('');
    const nodeMarkup = blocks.map((block) => {
      const status = block.status || 'free';
      const width = Number(block.width || 126); const height = Number(block.height || 56);
      const train = block.trainId ? app.state.trains.find((item) => item.id === block.trainId) : null;
      const label = block.name || block.id;
      return `<g class="block-node is-${escapeHtml(status)} ${block.id === app.selectedBlockId ? 'is-selected' : ''}" data-block-id="${escapeHtml(block.id)}" tabindex="0" role="button" aria-label="Block ${escapeHtml(label)}">
        <rect x="${block.x}" y="${block.y}" width="${width}" height="${height}" rx="8"></rect>
        <circle class="node-light" cx="${Number(block.x) + 14}" cy="${Number(block.y) + 16}" r="4"></circle>
        <text class="label" x="${Number(block.x) + 26}" y="${Number(block.y) + 20}">${escapeHtml(label)}</text>
        <text class="meta" x="${Number(block.x) + 14}" y="${Number(block.y) + height - 15}">${escapeHtml(train ? train.name : block.station || status.toUpperCase())}</text>
        <title>${escapeHtml(label)}${train ? ` · ${escapeHtml(train.name)} #${escapeHtml(train.number)}` : ''}</title>
      </g>`;
    }).join('');
    const turnoutMarkup = (layout.turnouts || []).slice(0, 4).map((turnout, index) => {
      const block = blockMap[turnout.from] || blocks.find((item) => item.id === ['b11', 'b12', 'b07', 'b09'][index]);
      if (!block) return '';
      const center = blockCenter(block);
      center.y += Number(block.height || 56) / 2 + 16;
      const locked = turnout.lockedBy ? ` · locked by ${turnout.lockedBy}` : '';
      return `<g class="turnout-node ${turnout.lockedBy ? 'is-locked' : ''}" data-turnout-id="${escapeHtml(turnout.id)}" tabindex="0" role="button" aria-label="Toggle turnout ${escapeHtml(turnout.name)}${escapeHtml(locked)}"><path class="turnout-marker" d="M ${center.x} ${center.y - 10} L ${center.x + 10} ${center.y} L ${center.x} ${center.y + 10} L ${center.x - 10} ${center.y} Z"></path><text class="meta" text-anchor="middle" x="${center.x}" y="${center.y + 25}">${escapeHtml(turnout.name || 'TO')}${turnout.lockedBy ? ' · LOCKED' : ''}</text></g>`;
    }).join('');
    const signalMarkup = (layout.signals || []).map((signal) => {
      const block = blockMap[String(signal.block_id || '').toLowerCase()];
      if (!block) return '';
      const center = blockCenter(block); const aspect = String(signal.aspect || 'red').toLowerCase();
      const color = aspect === 'green' ? 'var(--green)' : aspect === 'yellow' ? 'var(--yellow)' : 'var(--red)';
      return `<g class="signal-node signal-${escapeHtml(aspect)}" data-signal-id="${escapeHtml(signal.id)}" tabindex="0" role="button" aria-label="Set signal ${escapeHtml(signal.name || signal.id)}"><line x1="${center.x - 31}" y1="${center.y - 25}" x2="${center.x - 31}" y2="${center.y - 7}"></line><circle cx="${center.x - 31}" cy="${center.y - 28}" r="5" style="fill:${color}"></circle><text class="meta" x="${center.x - 48}" y="${center.y - 36}">${escapeHtml(signal.name || signal.id)}</text></g>`;
    }).join('');
    const waypointMarkup = (layout.waypoints || []).map((waypoint) => {
      const x = Number(waypoint.x || 0); const y = Number(waypoint.y || 0);
      return `<g class="waypoint-node" data-waypoint-id="${escapeHtml(waypoint.id)}" aria-label="Waypoint ${escapeHtml(waypoint.name || waypoint.id)}"><circle cx="${x}" cy="${y}" r="5"></circle><text class="meta" x="${x + 9}" y="${y + 3}">${escapeHtml(waypoint.name || waypoint.id)}</text></g>`;
    }).join('');
    const turntableMarkup = (layout.turntables || []).map((turntable) => {
      const x = Number(turntable.x || 0); const y = Number(turntable.y || 0);
      return `<g class="turntable-node" data-turntable-id="${escapeHtml(turntable.id)}" tabindex="0" role="button" aria-label="Align turntable ${escapeHtml(turntable.name || turntable.id)}"><circle cx="${x}" cy="${y}" r="18"></circle><line x1="${x - 13}" y1="${y}" x2="${x + 13}" y2="${y}"></line><text class="meta" x="${x + 23}" y="${y + 3}">${escapeHtml(turntable.name || turntable.id)}</text></g>`;
    }).join('');
    const markers = app.state.trains.filter((train) => train.graph_enabled !== false).map((train) => {
      const motion = train.motion || {};
      const from = blockMap[String(motion.from_block_id || motion.block_id || train.position || '').toLowerCase()];
      if (!from) return '';
      const to = blockMap[String(motion.to_block_id || '').toLowerCase()];
      const point = blockCenter(from);
      const label = String(train.name || train.id);
      const labelWidth = Math.min(210, Math.max(52, label.length * 6 + 16));
      return `<g class="graph-train-marker" data-motion-train-id="${escapeHtml(train.id)}" data-position-source="${escapeHtml(motion.source || 'unknown')}" transform="translate(${point.x} ${point.y})"><path class="marker-leader" d="M 0 -8 L 0 -37 L 12 -37"></path><circle r="7"></circle><rect class="marker-label" x="9" y="-57" width="${labelWidth}" height="22" rx="7"></rect><text x="17" y="-42">${escapeHtml(label.length > 31 ? label.slice(0, 30) + '…' : label)}</text><title>${escapeHtml(label)} · ${motion.source === 'simulation' ? 'Simulation position; interpolation between updates' : 'Reported block only; exact real position unknown'}</title></g>${to ? `<path class="motion-path" data-motion-path-id="${escapeHtml(train.id)}" d="${edgePath(from, to)}" fill="none" stroke="none"></path>` : ''}`;
    }).join('');
    $('#layout-svg').innerHTML = `<g class="graph-layer" style="transform-origin: 490px 175px;">${edgeMarkup}${nodeMarkup}${waypointMarkup}${turntableMarkup}${turnoutMarkup}${signalMarkup}${markers}</g>`;
    $('#graph-motion-note').textContent = app.state.connection.simulated ? 'Simulation positions · estimated interpolation between updates, capped at 2 seconds. Block boundaries wait for controller confirmation.' : 'Real trains: reported block only. Exact within-block positions are unknown; no movement is invented.';
    updateMotionMarkers(performance.now());
    if (!app.layoutDrag) applyLayoutViewport();
    $$('[data-block-id]', $('#layout-svg')).forEach((node) => {
      node.addEventListener('click', () => selectBlock(node.dataset.blockId));
      node.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') selectBlock(node.dataset.blockId); });
      node.addEventListener('pointerdown', (event) => beginBlockDrag(event, node.dataset.blockId));
    });
    $$('[data-turnout-id]', $('#layout-svg')).forEach((node) => node.addEventListener('click', () => toggleTurnout(node.dataset.turnoutId)));
    $$('[data-signal-id]', $('#layout-svg')).forEach((node) => node.addEventListener('click', () => toggleSignal(node.dataset.signalId)));
    $$('[data-turntable-id]', $('#layout-svg')).forEach((node) => node.addEventListener('click', () => alignTurntable(node.dataset.turntableId)));
  }

  function pinboardPointFromEvent(event) {
    const svg = $('#layout-svg');
    return svgPoint(event);
  }

  function formatPinboardCoordinate(point) {
    return 'X ' + Number(point.x).toFixed(1) + ' · Y ' + Number(point.y).toFixed(1);
  }

  function parsePinboardCoordinate(value) {
    const text = String(value || '').trim();
    const match = text.match(/x\s*[:=]?\s*(-?\d+(?:\.\d+)?)\s*(?:[,;·|]\s*|\s+)y\s*[:=]?\s*(-?\d+(?:\.\d+)?)/i)
      || text.match(/^\s*(-?\d+(?:\.\d+)?)\s*[,; ]\s*(-?\d+(?:\.\d+)?)\s*$/);
    if (!match) return null;
    const x = Number(match[1]); const y = Number(match[2]);
    return Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null;
  }

  function projectPinboardPoint(points, point) {
    if (!Array.isArray(points) || points.length < 2) return null;
    const lengths = points.map((item, index) => index === points.length - 1 ? 0 : Math.hypot(points[index + 1].x - item.x, points[index + 1].y - item.y));
    const total = lengths.reduce((sum, value) => sum + value, 0);
    if (total <= 0) return null;
    let travelled = 0;
    let best = null;
    lengths.forEach((length, index) => {
      if (length <= 0) return;
      const start = points[index]; const end = points[index + 1];
      const dx = end.x - start.x; const dy = end.y - start.y;
      const local = Math.max(0, Math.min(1, ((point.x - start.x) * dx + (point.y - start.y) * dy) / (length * length)));
      const x = start.x + dx * local; const y = start.y + dy * local;
      const candidate = { x, y, distance: Math.hypot(point.x - x, point.y - y), progress: (travelled + length * local) / total, dx, dy };
      if (!best || candidate.distance < best.distance) best = candidate;
      travelled += length;
    });
    return best;
  }

  function nearestPinboardCoordinate(point) {
    const blocks = app.state.layout.blocks || [];
    const blockMap = Object.fromEntries(blocks.map((block) => [String(block.id || '').toLowerCase(), block]));
    let best = null;
    normalizedEdges(app.state.layout, blocks).forEach((edge) => {
      const from = blockMap[String(edge.from).toLowerCase()];
      const to = blockMap[String(edge.to).toLowerCase()];
      if (!from || !to) return;
      const projected = projectPinboardPoint(pinboardPathSamples(edgeControlPoints(from, to, edge)), point);
      if (projected && (!best || projected.distance < best.distance)) {
        best = { ...projected, from_node: String(edge.from).toLowerCase(), to_node: String(edge.to).toLowerCase() };
      }
    });
    return best && best.distance <= 32 ? best : null;
  }

  function pinboardPathSamples(points) {
    const samples = [];
    for (let index = 0; index < points.length - 1; index += 1) {
      const steps = 32;
      for (let step = index === 0 ? 0 : 1; step <= steps; step += 1) {
        const point = splinePointAt(points, index, step / steps);
        const previous = samples[samples.length - 1];
        samples.push({ ...point, distance: previous ? previous.distance + Math.hypot(point.x - previous.x, point.y - previous.y) : 0 });
      }
    }
    return samples;
  }

  function pinboardPointAtDistance(samples, distance) {
    if (!samples.length) return { x: 0, y: 0, dx: 1, dy: 0 };
    const target = Math.max(0, Math.min(samples[samples.length - 1].distance, distance));
    let index = 1;
    while (index < samples.length - 1 && samples[index].distance < target) index += 1;
    const start = samples[index - 1]; const end = samples[index];
    const span = end.distance - start.distance;
    const progress = span > 0 ? (target - start.distance) / span : 0;
    return { x: start.x + (end.x - start.x) * progress, y: start.y + (end.y - start.y) * progress, dx: end.x - start.x, dy: end.y - start.y };
  }

  function pinboardVehicleLengthsMm(train, consist) {
    const declaredTotal = Number(train.length_mm != null ? train.length_mm : Number(train.length || 0) * 1000);
    // Data-sheet train totals are prototype lengths; small values are already H0 model millimetres.
    const totalModelLength = Number.isFinite(declaredTotal) && declaredTotal > 0
      ? declaredTotal / (declaredTotal > 10000 ? 87 : 1)
      : 0;
    const known = consist.map((item) => Number(item.length_mm) > 0 ? Number(item.length_mm) : 0);
    const missingCount = known.filter((length) => !length).length;
    const remaining = totalModelLength > known.reduce((sum, length) => sum + length, 0)
      ? totalModelLength - known.reduce((sum, length) => sum + length, 0)
      : totalModelLength;
    const inferred = missingCount && remaining > 0 ? remaining / missingCount : 220;
    return consist.map((item, index) => known[index] || inferred);
  }

  function renderPinboardTrainPicker() {
    const select = $('#pinboard-train-select');
    if (!select) return;
    const trains = app.state.trains || [];
    const trainOptions = trains.map((train) => `<option value="train:${escapeHtml(train.id)}">Train - ${escapeHtml(train.name || train.id)} - #${escapeHtml(train.number || '-')}</option>`).join('');
    const inventory = rollingStockCatalogue();
    const locomotiveRows = inventory.filter((item) => /loco|engine/i.test(String(item.type || '')));
    const fallbackLocomotives = locomotiveRows.length ? locomotiveRows : trains.map((train) => ({
      id: `train-locomotive:${train.id}`,
      name: `${train.name || train.id} locomotive`,
      type: 'locomotive',
      length_mm: train.length_mm || 220,
      mass_g: train.mass_g,
      model: train.model_number || ''
    }));
    const locomotiveOptions = fallbackLocomotives.map((item) => `<option value="stock:${escapeHtml(item.id)}">Locomotive - ${escapeHtml(item.name || item.id)}</option>`).join('');
    const rollingOptions = inventory.filter((item) => !/loco|engine/i.test(String(item.type || ''))).map((item) => `<option value="stock:${escapeHtml(item.id)}">Rolling stock - ${escapeHtml(item.name || item.id)}</option>`).join('');
    const value = app.pinboardPlacementSelection || select.value;
    select.innerHTML = `<option value="">Choose a train or locomotive</option><optgroup label="Trains">${trainOptions || '<option value="" disabled>No train profiles</option>'}</optgroup><optgroup label="Locomotives">${locomotiveOptions || '<option value="" disabled>No locomotives</option>'}</optgroup>${rollingOptions ? `<optgroup label="Rolling stock">${rollingOptions}</optgroup>` : ''}`;
    if ([...select.options].some((option) => option.value === value)) select.value = value;
    app.pinboardPlacementSelection = select.value;
    const button = $('#place-pinboard-train');
    if (button) button.disabled = !select.value;
    const removeButton = $("#remove-pinboard-train");
    const selectedTrain = (trains || []).find((train) => train.id === String(select.value || "").replace(/^train:/, ""));
    if (removeButton) removeButton.disabled = !selectedTrain || selectedTrain.graph_enabled === false;
    const status = $('#pinboard-placement-status');
    if (status) status.textContent = app.pendingPinboardTrain ? 'Click a rail to place the selected vehicle.' : 'Choose a train or locomotive, then click a rail.';
  }

  function pinboardStockFromSelection(selection) {
    if (!selection || !selection.startsWith('stock:')) return null;
    const id = selection.slice(6);
    const found = rollingStockCatalogue().find((item) => item.id === id);
    if (found) return found;
    const fallbackTrainId = id.startsWith('train-locomotive:') ? id.slice('train-locomotive:'.length) : '';
    const train = app.state.trains.find((item) => item.id === fallbackTrainId);
    return train ? { id, name: `${train.name || train.id} locomotive`, type: 'locomotive', length_mm: train.length_mm || 220, mass_g: train.mass_g, model: train.model_number || '' } : null;
  }

  function safePinboardId(value) {
    const slug = String(value || 'vehicle').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 28) || 'vehicle';
    return `pinboard-${slug}-${Date.now()}`;
  }

  function beginPinboardTrainPlacement() {
    const selection = $('#pinboard-train-select')?.value || app.pinboardPlacementSelection;
    if (!selection) {
      showToast('Choose a train or locomotive first.', 'warning');
      return;
    }
    app.pinboardPlacementSelection = selection;
    app.pendingPinboardTrain = selection;
    renderPinboardTrainPicker();
    showToast('Click a rail to place the selected vehicle.', 'success');
  }

  async function removeSelectedTrainFromGraph() {
    const selection = $("#pinboard-train-select")?.value || app.pinboardPlacementSelection;
    const trainId = selection && selection.startsWith("train:") ? selection.slice(6) : "";
    if (!trainId) {
      showToast("Choose a registered train first.", "warning");
      return;
    }
    const train = (app.state.trains || []).find((item) => item.id === trainId);
    if (!train) return;
    if (train.graph_enabled === false) {
      showToast("That train is already registry-only.", "warning");
      return;
    }
    if (!window.confirm("Remove " + (train.name || train.id) + " from the node graph? It will stay in the train registry.")) return;
    const response = await sendCommand({ type: "set_train_graph_membership", train_id: trainId, enabled: false });
    if (response) {
      app.pendingPinboardTrain = null;
      renderPinboardTrainPicker();
      showToast((train.name || train.id) + " removed from the node graph.", "success");
    }
  }

  async function placePinboardTrainAtPoint(coordinate) {
    const selection = app.pendingPinboardTrain;
    if (!selection || !coordinate) {
      if (selection) showToast('Drop the vehicle on a configured rail.', 'warning');
      return;
    }
    const selectedTrainId = selection.startsWith('train:') ? selection.slice(6) : '';
    const block = (app.state.layout.blocks || []).find((item) => String(item.id).toLowerCase() === coordinate.from_node);
    const occupant = block && (block.trainId || block.occupied_by);
    if (occupant && occupant !== selectedTrainId) {
      showToast(`${block.name || block.id} is occupied. Choose a free track section.`, 'warning');
      return;
    }
    let trainId = selectedTrainId;
    if (!trainId) {
      const item = pinboardStockFromSelection(selection);
      if (!item) { app.pendingPinboardTrain = null; renderPinboardTrainPicker(); return; }
      trainId = safePinboardId(item.name || item.id);
      const response = await sendCommand({ type: 'add_train', train: {
        id: trainId,
        name: item.name || 'Locomotive',
        number: '',
        address: null,
        mode: 'stopped',
        speed: 0,
        requested_speed_kmh: 0,
        direction: 'forward',
        block_id: coordinate.from_node.toUpperCase(),
        length_mm: Number(item.length_mm) || 220,
        mass_g: item.mass_g == null ? null : Number(item.mass_g),
        maxSpeed: 120,
        model_number: item.model || '',
        consist: [{ id: item.id, type: item.type || 'locomotive', name: item.name || 'Locomotive', length_mm: Number(item.length_mm) || 220, mass_g: item.mass_g == null ? null : Number(item.mass_g) }]
      }});
      if (!response) { app.pendingPinboardTrain = null; renderPinboardTrainPicker(); return; }
      app.pinboardPlacementSelection = `train:${trainId}`;
    }
    const response = await sendCommand({ type: 'place_train_on_track', train_id: trainId, x: coordinate.x, y: coordinate.y });
    if (response) showToast(`${trainId} placed on the track.`, 'success');
    app.pendingPinboardTrain = null;
    renderPinboardTrainPicker();
  }

  function selectedSplineGeometry() {
    const selected = app.selectedSplineSection;
    if (!selected) return null;
    const blocks = app.state.layout.blocks || [];
    const blockMap = Object.fromEntries(blocks.map((block) => [String(block.id).toLowerCase(), block]));
    for (const edge of normalizedEdges(app.state.layout, blocks)) {
      if (![edge.from, edge.to].every((id) => [selected.from, selected.to].includes(id))) continue;
      const points = edgeControlPoints(blockMap[edge.from], blockMap[edge.to], edge);
      const index = points.segments.findIndex((section) => [section.start_anchor_id, section.end_anchor_id]
        .every((id) => [selected.start_anchor_id, selected.end_anchor_id].includes(id)));
      if (index >= 0) return { edge, points, index, section: points.segments[index], ...splineControls(points, index) };
    }
    return null;
  }

  function selectSplineSection(edge, points, index) {
    const section = points.segments[index];
    app.selectedSplineSection = { from: edge.from, to: edge.to, start_anchor_id: section.start_anchor_id, end_anchor_id: section.end_anchor_id };
    app.selectedWaypointId = null;
    app.splineSpeedDirty = false;
    const from = $('#connection-from'); const to = $('#connection-to');
    if (from && to) { from.value = edge.from; to.value = edge.to; loadConnectionLimit(); }
    renderGraph();
  }

  function selectSplinePoint(waypointId) {
    app.selectedWaypointId = waypointId;
    if (app.layoutEditing) {
      const geometry = selectedSplineGeometry();
      if (!geometry || ![geometry.section.start_anchor_id, geometry.section.end_anchor_id].includes(String(waypointId).toUpperCase())) {
        const blocks = app.state.layout.blocks || [];
        const blockMap = Object.fromEntries(blocks.map((block) => [block.id, block]));
        for (const edge of normalizedEdges(app.state.layout, blocks)) {
          const points = edgeControlPoints(blockMap[edge.from], blockMap[edge.to], edge);
          const index = points.segments.findIndex((section) => [section.start_anchor_id, section.end_anchor_id].includes(String(waypointId).toUpperCase()));
          if (index < 0) continue;
          selectSplineSection(edge, points, index);
          app.selectedWaypointId = waypointId;
          break;
        }
      }
    }
    renderGraph();
  }

  function renderSplineSectionEditor() {
    const editor = $('#spline-section-editor');
    const geometry = selectedSplineGeometry();
    const visible = app.workspace === 'layout' && app.layoutView === 'pinboard' && app.layoutEditing;
    editor.classList.toggle('is-hidden', !visible);
    $('#spline-section-name').textContent = geometry
      ? `${app.selectedWaypointId ? `${app.selectedWaypointId} · ` : ''}${geometry.section.start_anchor_id} → ${geometry.section.end_anchor_id}` : 'Select a spline section';
    const input = $('#spline-section-speed');
    if (!app.splineSpeedDirty) input.value = geometry && geometry.section.speed_limit_kmh != null ? String(geometry.section.speed_limit_kmh) : '';
    input.disabled = !geometry;
    $('#save-spline-section-speed').disabled = !geometry;
    $('#spline-section-status').textContent = geometry
      ? 'Drag either pull point to shape this curve. Blank removes its maximum speed. Save layout to keep changes.'
      : 'Click a rail section to show its pull points and maximum speed.';
  }

  async function saveSplineSectionSpeed() {
    const selected = app.selectedSplineSection;
    const input = $('#spline-section-speed');
    if (!selected || !input.checkValidity()) { input.reportValidity(); return; }
    const response = await sendCommand({ type: 'set_track_section', ...selected,
      speed_limit_kmh: input.value.trim() === '' ? null : Number(input.value) });
    if (response) { app.splineSpeedDirty = false; renderSplineSectionEditor(); showToast('Section speed applied. Save layout to keep it.', 'success'); }
  }

  function beginSplineHandleDrag(event, handle) {
    const geometry = selectedSplineGeometry();
    if (!geometry || !app.layoutEditing || event.button !== 0) return;
    event.preventDefault(); event.stopPropagation();
    const view = app.layoutViewports.pinboard;
    if (view) app.layoutViewportManual.pinboard = true;
    const anchor = handle === 'control1' ? geometry.points[geometry.index] : geometry.points[geometry.index + 1];
    app.splineHandleDrag = { pointerId: event.pointerId, section: { ...app.selectedSplineSection },
      handle, anchorId: handle === 'control1' ? geometry.section.start_anchor_id : geometry.section.end_anchor_id,
      anchor, point: handle === 'control1' ? geometry.c1 : geometry.c2, moved: false };
    window.addEventListener('pointermove', moveSplineHandleDrag);
    window.addEventListener('pointerup', endSplineHandleDrag);
    window.addEventListener('pointercancel', endSplineHandleDrag);
  }

  function moveSplineHandleDrag(event) {
    const drag = app.splineHandleDrag;
    if (!drag || event.pointerId !== drag.pointerId) return;
    drag.point = svgPoint(event); drag.moved = true;
    event.preventDefault(); renderGraph();
  }

  async function endSplineHandleDrag(event) {
    const drag = app.splineHandleDrag;
    if (!drag || event.pointerId !== drag.pointerId) return;
    window.removeEventListener('pointermove', moveSplineHandleDrag);
    window.removeEventListener('pointerup', endSplineHandleDrag);
    window.removeEventListener('pointercancel', endSplineHandleDrag);
    if (event.type !== 'pointercancel' && drag.moved) {
      app.suppressCanvasClickUntil = Date.now() + 350;
      const key = drag.anchorId === drag.section.start_anchor_id ? 'control1' : 'control2';
      await sendCommand({ type: 'set_track_section', ...drag.section,
        [key]: { x: drag.point.x - drag.anchor.x, y: drag.point.y - drag.anchor.y } });
    }
    app.splineHandleDrag = null; renderGraph();
  }

  function renderPinboard() {
    const layout = app.state.layout;
    const blocks = layout.blocks || [];
    const blockMap = Object.fromEntries(blocks.flatMap((block) => [[block.id, block], [String(block.id || '').toLowerCase(), block], [String(block.name || '').toLowerCase(), block]]));
    const edges = normalizedEdges(layout, blocks);
    const edgeMarkup = edges.map((edge, edgeIndex) => {
      const from = blockMap[String(edge.from).toLowerCase()]; const to = blockMap[String(edge.to).toLowerCase()];
      if (!from || !to) return '';
      const points = edgeControlPoints(from, to, edge);
      const occupied = [from, to].find((block) => block.status === 'occupied' || block.occupied_by || block.trainId) || (edge.status === 'occupied' ? to : null);
      const routed = [from, to].find((block) => block.status === 'route') || (edge.status === 'route' ? to : null);
      const section = occupied || routed || to;
      const status = occupied ? 'occupied' : routed || edge.status === 'route' ? 'route' : 'free';
      const point = splinePointAtProgress(points, .5);
      const label = escapeHtml(section.name || section.id);
      const sections = points.slice(0, -1).map((_, index) => {
        const path = splineSegmentPath(points, index); const section = points.segments[index];
        const selected = app.selectedSplineSection;
        const active = selected && [edge.from, edge.to].every((id) => [selected.from, selected.to].includes(id))
          && [section.start_anchor_id, section.end_anchor_id].every((id) => [selected.start_anchor_id, selected.end_anchor_id].includes(id));
        const maximum = section.speed_limit_kmh == null ? '' : ` · maximum ${section.speed_limit_kmh} km/h`;
        return `<g class="pinboard-track-section${active && app.layoutEditing ? ' is-selected' : ''}" data-spline-edge="${edgeIndex}" data-spline-index="${index}"${app.layoutEditing ? ' tabindex="0" role="button"' : ''} aria-label="Spline ${section.start_anchor_id} to ${section.end_anchor_id}${maximum}"><path class="pinboard-section-selection" d="${path}"></path><path class="pinboard-rail-bed" d="${path}"></path><path class="pinboard-rail is-${status}" d="${path}"><title>${label} · ${status}${maximum}</title></path><path class="pinboard-section-hit" d="${path}"></path></g>`;
      }).join('');
      return sections + '<text class="pinboard-section-label" x="' + point.x + '" y="' + (point.y - 9) + '">' + label + '</text>';
    }).join('');
    const nodeMarkup = blocks.map((block) => {
      const point = blockCenter(block);
      const selected = block.id === app.selectedBlockId ? ' is-selected' : '';
      return '<g class="pinboard-node' + selected + '" data-block-id="' + escapeHtml(block.id) + '" tabindex="0" role="button" aria-label="Track node ' + escapeHtml(block.name || block.id) + '"><circle cx="' + point.x + '" cy="' + point.y + '" r="9"></circle><text x="' + (point.x + 14) + '" y="' + (point.y + 4) + '">' + escapeHtml(block.name || block.id) + '</text><title>' + escapeHtml(block.name || block.id) + ' · X ' + point.x.toFixed(1) + ' · Y ' + point.y.toFixed(1) + '</title></g>';
    }).join('');
    const splinePointMarkup = (layout.waypoints || []).map((waypoint) => {
      const x = Number(waypoint.x || 0); const y = Number(waypoint.y || 0);
      return '<g class="pinboard-spline-point' + (waypoint.id === app.selectedWaypointId ? ' is-selected' : '') + '" data-waypoint-id="' + escapeHtml(waypoint.id) + '" tabindex="0" role="button" aria-pressed="' + (waypoint.id === app.selectedWaypointId) + '" aria-label="Spline control point ' + escapeHtml(waypoint.id) + '"><circle cx="' + x + '" cy="' + y + '" r="7"></circle><text x="' + (x + 11) + '" y="' + (y - 9) + '">' + escapeHtml(waypoint.name || waypoint.id) + '</text><title>' + escapeHtml(waypoint.name || waypoint.id) + ' · X ' + x.toFixed(1) + ' · Y ' + y.toFixed(1) + '</title></g>';
    }).join('');
    const degree = new Map();
    edges.forEach((edge) => { degree.set(String(edge.from).toLowerCase(), (degree.get(String(edge.from).toLowerCase()) || 0) + 1); degree.set(String(edge.to).toLowerCase(), (degree.get(String(edge.to).toLowerCase()) || 0) + 1); });
    const junctions = blocks.filter((block) => (degree.get(String(block.id).toLowerCase()) || 0) > 2);
    const turnoutMarkup = (layout.turnouts || []).map((turnout, index) => {
      const anchor = blockMap[String(turnout.from || '').toLowerCase()] || junctions[index % Math.max(1, junctions.length)];
      if (!anchor) return '';
      const center = blockCenter(anchor);
      const point = { x: center.x - 16, y: center.y - 17 };
      const state = String(turnout.state || 'straight').toLowerCase() === 'diverging' ? 'diverging' : 'straight';
      const glyph = state === 'straight' ? '→' : '↗';
      const locked = turnout.lockedBy ? ' · locked by ' + escapeHtml(turnout.lockedBy) : '';
      return '<g class="pinboard-turnout is-' + state + (turnout.lockedBy ? ' is-locked' : '') + '" data-turnout-id="' + escapeHtml(turnout.id) + '" tabindex="0" role="button" aria-label="Switch ' + escapeHtml(turnout.name || turnout.id) + ' ' + state + locked + '"><circle class="pinboard-switch-dot" cx="' + point.x + '" cy="' + point.y + '" r="13"></circle><text class="pinboard-switch-state" x="' + point.x + '" y="' + (point.y + 4) + '">' + glyph + '</text><title>' + escapeHtml(turnout.name || turnout.id) + ' · ' + state + locked + '</title></g>';
    }).join('');
    const targetMarkup = (app.state.trains || []).map((train) => {
      const target = train.target_coordinate;
      if (!target || target.x == null || target.y == null || !Number.isFinite(Number(target.x)) || !Number.isFinite(Number(target.y))) return '';
      const x = Number(target.x); const y = Number(target.y); const label = escapeHtml(train.name || train.id);
      return '<g class="pinboard-destination"><circle cx="' + x + '" cy="' + y + '" r="10"></circle><circle class="pinboard-destination-center" cx="' + x + '" cy="' + y + '" r="3"></circle><text x="' + (x + 14) + '" y="' + (y - 10) + '">DEST</text><title>' + label + ' destination</title></g>';
    }).join('');
    const trainMarkup = app.state.trains.filter((train) => train.graph_enabled !== false).map((train) => {
      const motion = train.motion || {};
      const from = blockMap[String(motion.from_block_id || motion.block_id || train.position || '').toLowerCase()];
      if (!from) return '';
      const to = blockMap[String(motion.to_block_id || '').toLowerCase()];
      const matching = edges.find((edge) => to
        ? ((String(edge.from).toLowerCase() === String(from.id).toLowerCase() && String(edge.to).toLowerCase() === String(to.id).toLowerCase()) || (String(edge.to).toLowerCase() === String(from.id).toLowerCase() && String(edge.from).toLowerCase() === String(to.id).toLowerCase()))
        : (String(edge.from).toLowerCase() === String(from.id).toLowerCase() || String(edge.to).toLowerCase() === String(from.id).toLowerCase()));
      const previous = matching && !to ? blockMap[(String(matching.from).toLowerCase() === String(from.id).toLowerCase() ? String(matching.to) : String(matching.from)).toLowerCase()] : null;
      const start = to ? from : (previous || from); const end = to || from;
      const orientedEdge = matching && String(matching.from).toLowerCase() !== String(start.id).toLowerCase()
        ? reverseSplineEdge(matching) : matching;
      const points = matching ? edgeControlPoints(start, end, orientedEdge) : [blockCenter(from), { x: blockCenter(from).x + 100, y: blockCenter(from).y }];
      const samples = pinboardPathSamples(points);
      const totalLength = samples.length ? samples[samples.length - 1].distance : 0;
      const progress = !to && !matching ? .5 : to && motion.source === 'simulation' && Number.isFinite(Number(motion.position)) ? Math.max(0, Math.min(.98, Number(motion.position))) : to ? 0 : 1;
      const leadDistance = progress * totalLength;
      const consist = Array.isArray(train.consist) && train.consist.length ? train.consist : [{ type: 'locomotive', name: train.name }];
      const vehicleLengths = pinboardVehicleLengthsMm(train, consist);
      let offset = 0;
      const vehicles = consist.map((item, index) => {
        const length = Math.max(4, vehicleLengths[index] / 8);
        const centerDistance = leadDistance - offset - length / 2;
        const point = pinboardPointAtDistance(samples, centerDistance);
        const angle = Math.atan2(point.dy, point.dx) * 180 / Math.PI;
        const value = '<g class="pinboard-vehicle-position" data-distance-behind="' + (offset + length / 2) + '" transform="translate(' + point.x + ' ' + point.y + ') rotate(' + angle + ')"><rect class="pinboard-vehicle ' + (index === 0 ? 'is-locomotive' : 'is-rolling-stock') + '" x="' + (-length / 2) + '" y="-7" width="' + length + '" height="14" rx="2"><title>' + escapeHtml(item.name || item.type || 'Rolling stock') + '</title></rect></g>';
        offset += length + 3;
        return value;
      }).join('');
      const label = escapeHtml(train.name || train.id);
      const point = pinboardPointAtDistance(samples, leadDistance);
      return '<g class="pinboard-train' + (train.id === app.selectedTrainId ? ' is-selected' : '') + '" data-pinboard-train-id="' + escapeHtml(train.id) + '" data-from-block="' + escapeHtml(from.id) + '" data-to-block="' + escapeHtml(to ? to.id : '') + '" data-anchor-x="' + point.x + '" data-anchor-y="' + point.y + '" tabindex="0" role="button" aria-label="Train ' + label + ' · drag to set destination on the track">' + vehicles + '<text class="pinboard-train-label" x="' + (point.x + 10) + '" y="' + (point.y - 14) + '">' + label + '</text></g>';
    }).join('');
    const dragPreview = '<g id="pinboard-drag-preview" class="pinboard-drag-preview" visibility="hidden"><circle cx="0" cy="0" r="11"></circle><circle class="pinboard-drag-preview-center" cx="0" cy="0" r="3"></circle><text x="14" y="-10">DEST</text></g>';
    const selectedGeometry = app.layoutEditing && selectedSplineGeometry();
    const handleMarkup = selectedGeometry ? ['control1', 'control2'].map((handle, index) => {
      const anchor = selectedGeometry.points[selectedGeometry.index + index]; const point = index === 0 ? selectedGeometry.c1 : selectedGeometry.c2;
      return `<g class="pinboard-bezier-control"><line x1="${anchor.x}" y1="${anchor.y}" x2="${point.x}" y2="${point.y}"></line><circle class="pinboard-bezier-handle" data-bezier-handle="${handle}" cx="${point.x}" cy="${point.y}" r="7" tabindex="0" role="button" aria-label="Bezier pull point ${index + 1}. Drag to shape the selected curve."><title>Drag pull point ${index + 1}</title></circle></g>`;
    }).join('') : '';
    if (!app.layoutViewports.pinboard) fitGraphViewport();
    applyLayoutViewport();
    $('#layout-svg').setAttribute('aria-label', 'Top-down train visualizer with block-colored track, clickable switches, and trains following the track spline');
    $('#layout-svg').setAttribute('role', 'group');
    $('#layout-svg').innerHTML = '<g class="pinboard-layer">' + edgeMarkup + targetMarkup + nodeMarkup + turnoutMarkup + splinePointMarkup + trainMarkup + dragPreview + handleMarkup + '</g>';
    renderSplineSectionEditor();
    const stageMode = $('#map-stage-mode');
    if (stageMode) stageMode.textContent = 'TRAIN VISUALIZER';
    $('#graph-motion-note').textContent = app.layoutEditing ? 'Select a rail section to drag its Bézier pull points or set its maximum speed. Add a spline point to split the selected curve, then drag the new point into place.' : 'Drag a stopped train to a rail section to set its destination. Movement uses calibration; real trains ask for confirmation. Cars follow the spline at H0 scale.';
    const stage = $('#map-stage');
    stage.onpointermove = (event) => {
      const point = pinboardPointFromEvent(event);
      app.pinboardCursor = point;
      const display = $('#pinboard-coordinate');
      if (display) display.textContent = formatPinboardCoordinate(point);
    };
    stage.onpointerleave = () => {
      const display = $('#pinboard-coordinate');
      if (display) display.textContent = 'Move over the board to read coordinates';
    };
    stage.onclick = (event) => {
      if (Date.now() < app.suppressCanvasClickUntil) return;
      if (event.target.closest('.pinboard-node, .pinboard-train, .pinboard-turnout, .pinboard-spline-point, .pinboard-bezier-handle')) return;
      const point = pinboardPointFromEvent(event);
      const coordinate = nearestPinboardCoordinate(point);
      if (app.pendingPinboardTrain) {
        void placePinboardTrainAtPoint(coordinate);
        return;
      }
      if (!app.layoutEditing) return;
      if (app.pendingWaypointPlacementId) {
        const waypoint = (app.state.layout.waypoints || []).find((item) => item.id === app.pendingWaypointPlacementId);
        if (!waypoint) { app.pendingWaypointPlacementId = null; return; }
        waypoint.x = Math.max(0, Math.round(point.x));
        waypoint.y = Math.max(0, Math.round(point.y));
        const waypointId = waypoint.id;
        app.pendingWaypointPlacementId = null;
        renderGraph();
        sendCommand({ type: 'update_waypoint', waypoint_id: waypointId, waypoint: { x: waypoint.x, y: waypoint.y } });
        showToast(`${waypointId} placed as a spline control point.`, 'success');
        return;
      }
      if (!app.pendingBlockPlacementId) return;
      const block = app.state.layout.blocks.find((item) => item.id === app.pendingBlockPlacementId);
      if (!block) { app.pendingBlockPlacementId = null; return; }
      block.x = Math.max(0, Math.round(point.x - Number(block.width || 126) / 2));
      block.y = Math.max(0, Math.round(point.y - Number(block.height || 56) / 2));
      const blockId = block.id;
      app.pendingBlockPlacementId = null;
      renderGraph();
      sendCommand({ type: 'move_block', block_id: blockId, x: block.x, y: block.y });
      showToast(`${blockId} placed on the pinboard.`, 'success');
    };
    $$('[data-block-id]', $('#layout-svg')).forEach((node) => {
      node.addEventListener('click', () => selectBlock(node.dataset.blockId));
      node.addEventListener('pointerdown', (event) => beginBlockDrag(event, node.dataset.blockId));
    });
    $$('[data-turnout-id]', $('#layout-svg')).forEach((node) => {
      node.addEventListener('click', () => { if (!node.classList.contains('is-locked')) void toggleTurnout(node.dataset.turnoutId); });
      node.addEventListener('keydown', (event) => { if ((event.key === 'Enter' || event.key === ' ') && !node.classList.contains('is-locked')) { event.preventDefault(); void toggleTurnout(node.dataset.turnoutId); } });
    });
    $$('[data-pinboard-train-id]', $('#layout-svg')).forEach((node) => {
      node.addEventListener('click', () => selectTrain(node.dataset.pinboardTrainId));
      node.addEventListener('pointerdown', (event) => beginPinboardTrainDrag(event, node.dataset.pinboardTrainId));
    });
    $$('[data-waypoint-id]', $('#layout-svg')).forEach((node) => {
      node.addEventListener('pointerdown', (event) => beginWaypointDrag(event, node.dataset.waypointId));
      node.addEventListener('click', () => { if (Date.now() >= app.suppressCanvasClickUntil) selectSplinePoint(node.dataset.waypointId); });
      node.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectSplinePoint(node.dataset.waypointId); } });
    });
    $$('[data-spline-edge]', $('#layout-svg')).forEach((node) => {
      const select = () => {
        if (!app.layoutEditing || app.pendingBlockPlacementId || app.pendingWaypointPlacementId || app.pendingPinboardTrain || Date.now() < app.suppressCanvasClickUntil) return;
        const edge = edges[Number(node.dataset.splineEdge)];
        selectSplineSection(edge, edgeControlPoints(blockMap[edge.from], blockMap[edge.to], edge), Number(node.dataset.splineIndex));
      };
      node.addEventListener('click', select);
      node.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(); } });
    });
    $$('[data-bezier-handle]', $('#layout-svg')).forEach((node) => {
      node.addEventListener('pointerdown', (event) => beginSplineHandleDrag(event, node.dataset.bezierHandle));
    });
  }

  function beginWaypointDrag(event, waypointId) {
    if (!app.layoutEditing || event.button !== 0) return;
    const waypoint = (app.state.layout.waypoints || []).find((item) => item.id === waypointId);
    if (!waypoint) return;
    const point = svgPoint(event);
    app.waypointDrag = {
      waypointId,
      pointerId: event.pointerId,
      start: point,
      original: { x: Number(waypoint.x) || 0, y: Number(waypoint.y) || 0 },
      startClient: { x: event.clientX, y: event.clientY }, moved: false
    };
    window.addEventListener('pointermove', moveWaypointDrag);
    window.addEventListener('pointerup', endWaypointDrag);
    window.addEventListener('pointercancel', endWaypointDrag);
    event.preventDefault();
    event.stopPropagation();
    app.selectedWaypointId = waypointId;
  }

  function moveWaypointDrag(event) {
    if (!app.waypointDrag || (app.waypointDrag.pointerId != null && event.pointerId !== app.waypointDrag.pointerId)) return;
    const drag = app.waypointDrag;
    if (!drag.moved && Math.hypot(event.clientX - drag.startClient.x, event.clientY - drag.startClient.y) < 4) return;
    if (!drag.moved) selectSplinePoint(drag.waypointId);
    drag.moved = true;
    const waypoint = (app.state.layout.waypoints || []).find((item) => item.id === app.waypointDrag.waypointId);
    if (!waypoint) return;
    const point = svgPoint(event);
    waypoint.x = Math.max(0, Math.round(app.waypointDrag.original.x + point.x - app.waypointDrag.start.x));
    waypoint.y = Math.max(0, Math.round(app.waypointDrag.original.y + point.y - app.waypointDrag.start.y));
    renderGraph();
  }

  async function endWaypointDrag(event) {
    if (!app.waypointDrag) return;
    if (event && app.waypointDrag.pointerId != null && event.pointerId !== app.waypointDrag.pointerId) return;
    const drag = app.waypointDrag;
    const waypoint = (app.state.layout.waypoints || []).find((item) => item.id === drag.waypointId);
    app.waypointDrag = null;
    window.removeEventListener('pointermove', moveWaypointDrag);
    window.removeEventListener('pointerup', endWaypointDrag);
    window.removeEventListener('pointercancel', endWaypointDrag);
    if (!waypoint) return;
    if (!drag.moved) {
      app.suppressCanvasClickUntil = Date.now() + 350;
      selectSplinePoint(waypoint.id);
      return;
    }
    if (event && event.type === 'pointercancel') { Object.assign(waypoint, drag.original); renderGraph(); return; }
    app.suppressCanvasClickUntil = Date.now() + 350;
    const response = await sendCommand({ type: 'update_waypoint', waypoint_id: waypoint.id, waypoint: { x: waypoint.x, y: waypoint.y } });
    if (response) showToast(`${waypoint.id} moved. Save layout to keep it.`, 'success');
    else { Object.assign(waypoint, drag.original); renderGraph(); }
  }

  function beginPinboardTrainDrag(event, trainId) {
    if (event.button !== 0) return;
    event.preventDefault();
    const pointerId = event.pointerId;
    const trainNode = $$('[data-pinboard-train-id]', $('#layout-svg')).find((node) => node.dataset.pinboardTrainId === trainId);
    app.pinboardTrainDrag = { trainId, pointerId, startX: event.clientX, startY: event.clientY, moved: false, node: trainNode, anchorX: Number(trainNode && trainNode.dataset.anchorX) || 0, anchorY: Number(trainNode && trainNode.dataset.anchorY) || 0 };
    const move = (current) => {
      const drag = app.pinboardTrainDrag;
      if (!drag || (drag.pointerId != null && current.pointerId !== drag.pointerId)) return;
      if (Math.hypot(current.clientX - drag.startX, current.clientY - drag.startY) > 5) drag.moved = true;
      const raw = pinboardPointFromEvent(current);
      const trackTarget = nearestPinboardCoordinate(raw);
      const next = trackTarget || raw;
      app.pinboardCursor = next;
      if (drag.moved) {
        const currentNode = drag.node && drag.node.isConnected ? drag.node : $$('[data-pinboard-train-id]', $('#layout-svg')).find((node) => node.dataset.pinboardTrainId === trainId);
        if (currentNode) {
          drag.node = currentNode;
          currentNode.classList.add('is-dragging');
          currentNode.setAttribute('transform', 'translate(' + (next.x - drag.anchorX) + ' ' + (next.y - drag.anchorY) + ')');
        }
      }
      const preview = $('#pinboard-drag-preview');
      if (preview) {
        preview.setAttribute('visibility', drag.moved && trackTarget ? 'visible' : 'hidden');
        preview.setAttribute('transform', 'translate(' + next.x + ' ' + next.y + ')');
      }
      const display = $('#pinboard-coordinate');
      if (display) display.textContent = formatPinboardCoordinate(next);
    };
    const finish = async (current) => {
      if (current && current.pointerId != null && current.pointerId !== pointerId) return;
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', finish);
      window.removeEventListener('pointercancel', finish);
      const moved = app.pinboardTrainDrag && app.pinboardTrainDrag.moved;
      if (app.pinboardTrainDrag && app.pinboardTrainDrag.node) {
        app.pinboardTrainDrag.node.classList.remove('is-dragging');
        app.pinboardTrainDrag.node.removeAttribute('transform');
      }
      const preview = $('#pinboard-drag-preview');
      if (preview) preview.setAttribute('visibility', 'hidden');
      app.pinboardTrainDrag = null;
      if (!current || current.type !== 'pointerup') return;
      if (!moved) { selectTrain(trainId); return; }
      app.suppressCanvasClickUntil = Date.now() + 350;
      const raw = pinboardPointFromEvent(current);
      const target = nearestPinboardCoordinate(raw);
      if (!target) {
        showToast('Drop the train on a configured rail.', 'warning');
        return;
      }
      const simulated = Boolean(app.state.connection && (app.state.connection.simulated || app.state.connection.mode === 'simulation'));
      const response = await sendCommand({ type: 'move_train_to_coordinate', train_id: trainId, x: target.x, y: target.y });
      if (!response) return;
      const train = (response.trains || []).find((item) => item.id === trainId);
      const coordinate = train && train.target_coordinate;
      const routeBlocks = coordinate && Array.isArray(coordinate.route_node_ids) ? coordinate.route_node_ids : [];
      const route = routeBlocks.length ? ': ' + routeBlocks.map((block) => String(block).toUpperCase()).join(' → ') : '';
      if (simulated) {
        const started = await sendCommand({ type: 'execute_coordinate_move', train_id: trainId, confirm: true });
        if (started) showToast(`${trainId} moving to its destination${route}.`, 'success');
        return;
      }
      const durationMs = Number(coordinate && coordinate.estimated_duration_ms);
      const duration = Number.isFinite(durationMs) && durationMs > 0 ? ` · ~${Math.ceil(durationMs / 1000)} s` : '';
      showToast('Destination set for ' + trainId + route + duration, 'success');
      if (window.confirm('Move this train to the marked destination now?')) {
        await sendCommand({ type: 'execute_coordinate_move', train_id: trainId, confirm: true });
      }
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', finish);
    window.addEventListener('pointercancel', finish);
    move(event);
  }

  function updateMotionMarkers(now) {
    const markers = $$('.graph-train-marker', $('#layout-svg'));
    markers.forEach((marker) => {
      const train = app.state.trains.find((item) => item.id === marker.dataset.motionTrainId);
      const motion = train && train.motion;
      if (!motion || motion.source !== 'simulation' || motion.position == null || !Number.isFinite(Number(motion.position))) return;
      const path = $$('.motion-path', $('#layout-svg')).find((item) => item.dataset.motionPathId === train.id);
      if (!path) return;
      const sample = motionSamples.get(train.id);
      const age = sample ? Math.max(0, (now - sample.receivedAt) / 1000) : 0;
      const elapsed = app.state.simulation.running && app.state.track_power && app.source === 'api' ? Math.min(age, 2) : 0;
      const position = Math.max(0, Math.min(1, Number(motion.position)));
      // Never cross a block boundary on an estimate. Repeated stale samples do
      // not reset the clock, and hardware never enters this interpolation path.
      const progress = Math.max(position, Math.min(.98, position + Math.max(0, Number(motion.speed) || 0) * elapsed));
      const point = path.getPointAtLength(path.getTotalLength() * progress);
      marker.setAttribute('transform', `translate(${point.x} ${point.y})`);
      marker.dataset.progress = String(progress);
      marker.dataset.estimated = String(elapsed > 0 && Number(motion.speed) > 0);
    });
    updatePinboardTrainMarkers(now);
  }

  function updatePinboardTrainMarkers(now) {
    if (app.layoutView !== 'pinboard') return;
    const blocks = app.state.layout.blocks || [];
    const blockMap = Object.fromEntries(blocks.flatMap((block) => [[String(block.id).toLowerCase(), block], [String(block.name || '').toLowerCase(), block]]));
    const edges = normalizedEdges(app.state.layout, blocks);
    $$('.pinboard-train[data-pinboard-train-id]', $('#layout-svg')).forEach((group) => {
      const train = app.state.trains.find((item) => String(item.id) === group.dataset.pinboardTrainId);
      const from = blockMap[String(group.dataset.fromBlock || '').toLowerCase()];
      const to = blockMap[String(group.dataset.toBlock || '').toLowerCase()];
      if (!train || !from) return;
      const edge = to && edges.find((item) => (String(item.from).toLowerCase() === String(from.id).toLowerCase() && String(item.to).toLowerCase() === String(to.id).toLowerCase()) || (String(item.to).toLowerCase() === String(from.id).toLowerCase() && String(item.from).toLowerCase() === String(to.id).toLowerCase()));
      const previous = edge || to ? null : edges.find((item) => String(item.from).toLowerCase() === String(from.id).toLowerCase() || String(item.to).toLowerCase() === String(from.id).toLowerCase());
      const prior = previous && blockMap[(String(previous.from).toLowerCase() === String(from.id).toLowerCase() ? String(previous.to) : String(previous.from)).toLowerCase()];
      const start = to ? from : prior || from; const end = to || from;
      const connection = edge || previous;
      const reversed = connection && String(connection.from).toLowerCase() !== String(start.id).toLowerCase();
      const oriented = reversed ? reverseSplineEdge(connection) : connection;
      const points = connection ? edgeControlPoints(start, end, oriented) : [blockCenter(from), { x: blockCenter(from).x + 100, y: blockCenter(from).y }];
      const samples = pinboardPathSamples(points);
      const total = samples.length ? samples[samples.length - 1].distance : 0;
      const motion = train.motion || {};
      let progress = !to && !connection ? .5 : to && motion.source === 'simulation' && Number.isFinite(Number(motion.position)) ? Math.max(0, Math.min(.98, Number(motion.position))) : to ? 0 : 1;
      const sample = motionSamples.get(train.id);
      const age = sample ? Math.max(0, (now - sample.receivedAt) / 1000) : 0;
      const elapsed = app.state.simulation.running && app.state.track_power && app.source === 'api' ? Math.min(age, 2) : 0;
      if (to && motion.source === 'simulation' && Number(motion.speed) > 0) progress = Math.max(progress, Math.min(.98, progress + Number(motion.speed) * elapsed));
      const leadDistance = progress * total;
      $$('.pinboard-vehicle-position', group).forEach((vehicle) => {
        const point = pinboardPointAtDistance(samples, leadDistance - Number(vehicle.dataset.distanceBehind || 0));
        vehicle.setAttribute('transform', 'translate(' + point.x + ' ' + point.y + ') rotate(' + (Math.atan2(point.dy, point.dx) * 180 / Math.PI) + ')');
      });
      const label = $('.pinboard-train-label', group);
      const lead = pinboardPointAtDistance(samples, leadDistance);
      if (label) { label.setAttribute('x', String(lead.x + 10)); label.setAttribute('y', String(lead.y - 14)); }
    });
  }

  function animateTrainMarkers(now) {
    if (!document.hidden) {
      renderWorldClock(now);
      if (['dispatch', 'layout'].includes(app.workspace)) updateMotionMarkers(now);
    }
    window.requestAnimationFrame(animateTrainMarkers);
  }

  function renderSystematicView() {
    const blocks = app.state.layout.blocks || [];
    const platforms = app.state.layout.platforms || [];
    const blockMap = Object.fromEntries(blocks.map((block) => [String(block.id || '').toLowerCase(), block]));
    const blockIdsByKey = blockIdLookup(blocks);
    const edges = normalizedEdges(app.state.layout, blocks).map((edge) => ({ ...edge, from: String(edge.from || '').toLowerCase(), to: String(edge.to || '').toLowerCase() }));
    const configuredGroups = platforms.length ? platforms : [{ id: 'main-line', name: 'Main line', blockIds: blocks.map((block) => block.id) }];
    const assignedBlockIds = new Set(configuredGroups.flatMap((group) => (group.blockIds || group.block_ids || []).map((id) => blockIdsByKey[String(id).toLowerCase()]).filter(Boolean).map((id) => String(id).toLowerCase())));
    const groups = platforms.length && blocks.some((block) => !assignedBlockIds.has(String(block.id || '').toLowerCase()))
      ? configuredGroups.concat([{ id: 'junctions', name: 'Junctions / sidings', blockIds: blocks.filter((block) => !assignedBlockIds.has(String(block.id || '').toLowerCase())).map((block) => block.id) }])
      : configuredGroups;
    const groupByBlock = {};
    groups.forEach((group, groupIndex) => (group.blockIds || group.block_ids || []).forEach((id) => {
      const canonicalId = blockMap[id] ? id : blockIdsByKey[String(id).toLowerCase()];
      if (canonicalId) groupByBlock[String(canonicalId).toLowerCase()] = group.id || group.name || `group-${groupIndex}`;
    }));

    const orderGroupBlocks = (group) => {
      const listed = Array.from(new Set((group.blockIds || group.block_ids || []).map((id) => String(id || '').toLowerCase()).filter((id) => blockMap[id]))).map((id) => blockMap[id]);
      const listedIds = new Set(listed.map((block) => String(block.id).toLowerCase()));
      const neighbours = Object.fromEntries(listed.map((block) => [String(block.id).toLowerCase(), new Set()]));
      edges.forEach((edge) => {
        if (listedIds.has(edge.from) && listedIds.has(edge.to) && edge.from !== edge.to) {
          neighbours[edge.from].add(edge.to);
          neighbours[edge.to].add(edge.from);
        }
      });
      listed.forEach((block) => (block.neighborIds || block.neighbor_ids || []).forEach((id) => {
        const left = String(block.id).toLowerCase();
        const right = String(id || '').toLowerCase();
        if (listedIds.has(left) && listedIds.has(right) && left !== right) { neighbours[left].add(right); neighbours[right].add(left); }
      }));
      const listedOrder = new Map(listed.map((block, index) => [String(block.id).toLowerCase(), index]));
      const remaining = new Set(listedIds);
      const ordered = [];
      while (remaining.size) {
        const start = Array.from(remaining).sort((left, right) => {
          const leftDegree = Array.from(neighbours[left]).filter((id) => remaining.has(id)).length;
          const rightDegree = Array.from(neighbours[right]).filter((id) => remaining.has(id)).length;
          return (leftDegree <= 1 ? 0 : 1) - (rightDegree <= 1 ? 0 : 1) || listedOrder.get(left) - listedOrder.get(right);
        })[0];
        let current = start;
        while (current && remaining.has(current)) {
          ordered.push(blockMap[current]);
          remaining.delete(current);
          current = Array.from(neighbours[current]).filter((id) => remaining.has(id)).sort((left, right) => listedOrder.get(left) - listedOrder.get(right))[0] || null;
        }
      }
      return ordered;
    };

    const edgeBetween = (from, to) => edges.find((edge) => edge.from === from && edge.to === to) || edges.find((edge) => edge.from === to && edge.to === from);
    const routeIds = (train) => {
      const route = Array.isArray(train && train.route) ? train.route : train && train.route && (train.route.blocks || train.route.block_ids);
      return Array.isArray(route) ? route.map((id) => String(id || '').toLowerCase()) : [];
    };
    const directionSymbol = (from, to, train) => {
      const route = routeIds(train);
      const fromIndex = route.indexOf(from);
      const toIndex = route.indexOf(to);
      if (fromIndex !== -1 && toIndex !== -1 && Math.abs(fromIndex - toIndex) === 1) return toIndex > fromIndex ? '→' : '←';
      const trainDirection = String(train && train.direction || '').toLowerCase();
      if (trainDirection.includes('reverse') || trainDirection.includes('westbound') || trainDirection.includes('back')) return '←';
      if (trainDirection.includes('forward') || trainDirection.includes('eastbound') || trainDirection.includes('right')) return '→';
      const edge = edgeBetween(from, to);
      if (!edge) return '·';
      const reversible = ['both', 'bidirectional', 'reversible', 'two-way'].includes(String(edge.direction || edge.travel_direction || '').toLowerCase());
      if (reversible) return '↔';
      if (!edge.direction && !edge.travel_direction && edge.bidirectional == null && edge.one_way == null) return '↔';
      return edge.from === from ? '→' : '←';
    };
    const crossLinks = edges.filter((edge) => groupByBlock[edge.from] && groupByBlock[edge.to] && groupByBlock[edge.from] !== groupByBlock[edge.to]);
    const groupMarkup = groups.map((group, groupIndex) => {
      const groupBlocks = orderGroupBlocks(group);
      const groupIds = new Set(groupBlocks.map((block) => String(block.id || '').toLowerCase()));
      const occupied = groupBlocks.some((block) => block.status === 'occupied');
      const route = groupBlocks.filter((block) => block.status === 'route').length;
      const exits = crossLinks.filter((edge) => groupIds.has(edge.from) || groupIds.has(edge.to));
      const linkedGroupNames = [...new Set(exits.map((edge) => {
        const otherId = groupIds.has(edge.from) ? edge.to : edge.from;
        const linkedGroup = groups.find((candidate, candidateIndex) => (candidate.id || candidate.name || `group-${candidateIndex}`) === groupByBlock[otherId]);
        return linkedGroup && (linkedGroup.name || linkedGroup.id);
      }).filter(Boolean))];
      const groupTrain = groupBlocks.map((block) => block.trainId && app.state.trains.find((train) => train.id === block.trainId)).find(Boolean)
        || app.state.trains.find((train) => {
          const ids = new Set(groupIds);
          return ids.has(String(train.position || train.block_id || '').toLowerCase()) || routeIds(train).some((id) => ids.has(id));
        });
      const stateText = occupied ? 'Occupied' : route ? 'Route set' : 'Clear';
      const stateDetail = groupTrain ? `${directionSymbol(String(groupBlocks[0] && groupBlocks[0].id).toLowerCase(), String(groupBlocks[1] && groupBlocks[1].id).toLowerCase(), groupTrain)} ${groupTrain.direction || 'Train direction'}` : occupied ? 'Movement protected' : exits.length ? `Junction → ${linkedGroupNames.join(', ') || 'connected graph'}` : 'Continuous block path';
      const trackMarkup = groupBlocks.map((block, index) => {
        const next = groupBlocks[index + 1];
        const blockId = String(block.id || '').toLowerCase();
        const nextId = next && String(next.id || '').toLowerCase();
        const graphLink = next && edgeBetween(blockId, nextId);
        const train = block.trainId && app.state.trains.find((item) => item.id === block.trainId);
        const symbol = graphLink ? directionSymbol(blockId, nextId, train || groupTrain) : '·';
        const connector = next ? `<span class="systematic-link ${graphLink ? 'is-connected' : 'is-gap'}" aria-label="${escapeHtml(graphLink ? `Track continuity ${symbol}` : 'No direct graph edge')}" title="${escapeHtml(graphLink ? `Graph direction ${symbol}` : 'No direct graph edge')}">${symbol}</span>` : '';
        const title = `${block.name || block.id} · ${block.status || 'free'}${train ? ` · ${train.name || 'train'} · ${train.direction || ''}` : ''}`;
        return `<button class="systematic-block ${escapeHtml(block.status || 'free')} ${block.id === app.selectedBlockId ? 'is-selected' : ''}" data-block-id="${escapeHtml(block.id)}" title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}">${escapeHtml(block.name || block.id)}</button>${connector}`;
      }).join('');
      return `<div class="systematic-row" data-systematic-group="${escapeHtml(group.id || group.name || `group-${groupIndex}`)}"><div class="systematic-label"><strong>${escapeHtml(group.name || group.id || 'Track group')}</strong><small>${groupBlocks.length} blocks · ${escapeHtml(group.direction || 'graph order')}</small></div><div class="systematic-track" aria-label="${escapeHtml(`${group.name || 'Track group'} in graph order`)}">${trackMarkup || '<span class="empty-state">No blocks in this group.</span>'}</div><div class="systematic-status"><strong class="${occupied ? 'is-occupied' : route ? 'is-route' : ''}">${stateText}</strong><span>${escapeHtml(stateDetail)}</span></div></div>`;
    }).join('');
    const topologyNote = crossLinks.length ? `${groups.length} lanes · ${edges.length} graph edges · ${crossLinks.length} junction${crossLinks.length === 1 ? '' : 's'}` : `${groups.length} lanes · ${edges.length} graph edges`;
    $('#systematic-view').innerHTML = `<div class="systematic-legend"><span><b>Graph order</b> · ↔ adjacency · arrows when direction is provided</span><span>${escapeHtml(topologyNote)}</span></div>${groupMarkup}`;
    const panelAction = $('.systematic-panel .panel-action');
    if (panelAction) panelAction.textContent = topologyNote;
    $$('[data-block-id]', $('#systematic-view')).forEach((button) => button.addEventListener('click', () => selectBlock(button.dataset.blockId)));
  }

  function renderScans() {
    const host = $('#scan-viewer-host');
    const select = $('#scan-select');
    if (!host || !select) return;
    const scans = Array.isArray(app.state.scans) ? app.state.scans : [];
    if (!scans.length) {
      select.innerHTML = '<option value="">No scans configured</option>';
      if (app.scanViewer) { app.scanViewer.destroy(); app.scanViewer = null; }
      host.innerHTML = '<div class="scan-empty"><div><strong>Your layout, in perspective</strong>Add a layout photograph in Settings to begin.</div></div>';
      $('#scan-title').textContent = 'No photo selected';
      $('#scan-description').textContent = 'Upload a photograph from Settings.';
      return;
    }
    select.innerHTML = scans.map((scan) => `<option value="${escapeHtml(scan.id)}">${escapeHtml(scan.label || scan.id)}</option>`).join('');
    if (!scans.some((scan) => scan.id === app.selectedScanId)) app.selectedScanId = scans[0].id;
    select.value = app.selectedScanId;
    const selected = scans.find((scan) => scan.id === app.selectedScanId) || scans[0];
    $('#scan-title').textContent = selected.label || selected.id;
    $('#scan-description').textContent = selected.description || 'Photo-scan anchor for the current layout.';
    if (window.ScanViewer) {
      if (!app.scanViewer) app.scanViewer = new window.ScanViewer(host, { manifest: scans, onSelect: (id) => { app.selectedScanId = id; renderScans(); } });
      else app.scanViewer.setManifest(scans);
      app.scanViewer.setSelected(app.selectedScanId);
    } else if (!host.querySelector('canvas')) {
      host.innerHTML = '<div class="scan-empty"><div><strong>3D viewer module unavailable</strong>The manifest is valid, but the viewer script did not load.</div></div>';
    }
  }

  function renderTrainList() {
    const query = app.filter.trim().toLowerCase();
    const locomotiveView = app.workspace === 'trains' && app.trainSection === 'locomotives';
    const source = locomotiveView ? app.state.trains.filter((train) => {
      const type = String(train.vehicle_type || train.type || '').trim().toLowerCase();
      return !type || ['locomotive', 'loco', 'engine'].includes(type);
    }) : app.state.trains;
    const trains = source.filter((train) => !query || [train.name, train.number, train.position, train.status, train.destination, train.destination_block_id, train.class].join(' ').toLowerCase().includes(query));
    const heading = $('#train-panel .panel-heading h2');
    if (heading) heading.textContent = locomotiveView ? 'Locomotives' : 'Train overview';
    const eyebrow = $('#train-panel .panel-heading .eyebrow');
    if (eyebrow) eyebrow.textContent = locomotiveView ? 'LOCOMOTIVE FLEET' : 'FLEET & POSITIONS';
    const empty = locomotiveView ? 'No locomotive records match the current filter.' : `No trains match “${escapeHtml(app.filter)}”.`;
    $('#train-list').innerHTML = trains.length ? trains.map((train) => {
      const destination = train.next_destination || train.destination || train.destination_block_id;
      const mode = train.mode === 'automatic' || train.class === 'Automatic' ? 'Automatic' : train.mode === 'manual' || train.class === 'Manual' ? 'Manual' : train.class || 'Stopped';
      return `<button class="train-row ${train.id === app.selectedTrainId ? 'is-selected' : ''}" data-train-id="${escapeHtml(train.id)}"><span class="train-cell-main"><strong>${escapeHtml(train.name || `Train ${train.number}`)}</strong><small>${escapeHtml(mode)} · #${escapeHtml(train.number || '—')}${destination ? ` · → ${escapeHtml(destination)}` : ''}</small></span><span class="train-position">${escapeHtml(train.position || '—')}</span><span class="train-status ${train.status === 'Delayed' ? 'warning' : ''}"><i class="signal-dot ${train.status === 'Delayed' ? 'yellow' : 'green'}"></i>${escapeHtml(train.status || 'Unknown')}</span><span class="train-speed">${Math.round(Number(train.speed) || 0)}<small> km/h</small></span></button>`;
    }).join('') : `<div class="empty-state">${empty}</div>`;
    $$('.train-row', $('#train-list')).forEach((row) => row.addEventListener('click', () => selectTrain(row.dataset.trainId)));
    const presence = app.state.presence || {};
    const summary = presence.summary || {};
    const stationKnown = (presence.results || []).filter((item) => item.response && item.response.known_to_station).length;
    $('#train-presence-status').textContent = presence.running
      ? 'Scanning saved DCC IDs… the controller remains responsive.'
      : summary.total
      ? summary.detected + ' detected · ' + summary.unknown + ' unknown · ' + summary.errors + ' errors.' + (stationKnown ? ` ${stationKnown} known to Z21 only; RailCom is required for physical detection.` : ' Presence is based on available track feedback.')
      : 'No train presence scan run yet.';
  }

  function trainDataCollections(train) {
    const database = train.database || {};
    if (!Array.isArray(train.decoder_functions)) train.decoder_functions = Array.isArray(database.decoder_functions) ? clone(database.decoder_functions) : [];
    if (!Array.isArray(train.maintenance_records)) train.maintenance_records = Array.isArray(database.maintenance_records) ? clone(database.maintenance_records) : [];
    return { decoderFunctions: train.decoder_functions, maintenance: train.maintenance_records };
  }

  async function exportTrainCatalogue() {
    try {
      const response = await fetch('/api/train-catalogue?format=json');
      if (!response.ok) throw new Error('Catalogue export failed');
      const payload = await response.json();
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'h0-train-catalogue.json';
      link.click();
      URL.revokeObjectURL(url);
      showToast('Train catalogue exported', 'success');
    } catch (error) {
      showToast(error.message || 'Catalogue export failed', 'warning');
    }
  }

  function catalogueFormatForFile(file) {
    if (!file) return null;
    const name = String(file.name || '').toLowerCase();
    if (name.endsWith('.json') || String(file.type || '').toLowerCase() === 'application/json') return 'json';
    if (name.endsWith('.csv') || String(file.type || '').toLowerCase() === 'text/csv') return 'csv';
    return null;
  }

  function updateCatalogueFileStatus(event) {
    const file = event && event.target && event.target.files ? event.target.files[0] : null;
    const status = $('#train-catalogue-file-status');
    if (!status) return;
    if (!file) {
      status.textContent = 'No file selected.';
      return;
    }
    const format = catalogueFormatForFile(file);
    status.textContent = format ? `${file.name} · ${format.toUpperCase()} catalogue` : `${file.name} · choose a .json or .csv file`;
  }

  function openTrainCatalogueImport() {
    const dialog = $('#train-catalogue-import');
    if (!dialog || app.importingTrainCatalogue) return;
    const fileInput = $('#train-catalogue-file');
    if (fileInput) fileInput.value = '';
    const status = $('#train-catalogue-file-status');
    if (status) status.textContent = 'No file selected.';
    const importStatus = $('#train-catalogue-import-status');
    if (importStatus) importStatus.textContent = '';
    if (!dialog.open) dialog.showModal();
  }

  function closeTrainCatalogueImport() {
    const dialog = $('#train-catalogue-import');
    if (!dialog) return;
    if (dialog.open) dialog.close();
  }

  function importSummary(result) {
    const imported = Array.isArray(result.imported) ? result.imported.length : 0;
    const updated = Array.isArray(result.updated) ? result.updated.length : 0;
    const skipped = Array.isArray(result.skipped) ? result.skipped.length : 0;
    return `${imported} added · ${updated} updated · ${skipped} skipped`;
  }

  async function importTrainCatalogue(event) {
    event.preventDefault();
    if (app.importingTrainCatalogue) return;
    const fileInput = $('#train-catalogue-file');
    const file = fileInput && fileInput.files ? fileInput.files[0] : null;
    const format = catalogueFormatForFile(file);
    const importStatus = $('#train-catalogue-import-status');
    if (!file) {
      if (importStatus) importStatus.textContent = 'Select a JSON or CSV file first.';
      showToast('Select a JSON or CSV catalogue file first.', 'warning');
      return;
    }
    if (!format) {
      if (importStatus) importStatus.textContent = 'Only JSON and CSV catalogue files are supported.';
      showToast('Choose a .json or .csv catalogue file.', 'warning');
      return;
    }

    const policySelect = $('#train-catalogue-conflict');
    const onConflict = policySelect && ['error', 'skip', 'replace'].includes(policySelect.value) ? policySelect.value : 'error';
    const submit = $('#submit-train-catalogue');
    app.importingTrainCatalogue = true;
    if (submit) {
      submit.disabled = true;
      submit.setAttribute('aria-busy', 'true');
      submit.textContent = 'Importing…';
    }
    if (importStatus) importStatus.textContent = `Reading ${file.name}…`;

    try {
      const content = await file.text();
      if (!content.trim()) throw new Error('The selected catalogue file is empty.');
      const response = await fetch('/api/train-catalogue', {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ format, content, on_conflict: onConflict })
      });
      const responseText = await response.text();
      let payload = null;
      if (responseText) {
        try { payload = JSON.parse(responseText); } catch (error) { /* handled below */ }
      }
      if (!response.ok) {
        const detail = payload && payload.error ? payload.error : `${response.status} ${response.statusText}`;
        throw new Error(detail || 'Catalogue import failed');
      }
      if (!payload || !payload.state || typeof payload.state !== 'object') throw new Error('The controller returned no updated state.');
      mergePayload(payload.state);
      app.source = 'api';
      renderAll();
      closeTrainCatalogueImport();
      showToast(`Catalogue imported · ${importSummary(payload.result || {})}`, 'success');
    } catch (error) {
      if (importStatus) importStatus.textContent = error.message || 'Catalogue import failed.';
      showToast(error.message || 'Catalogue import failed', 'warning');
    } finally {
      app.importingTrainCatalogue = false;
      if (submit) {
        submit.disabled = false;
        submit.removeAttribute('aria-busy');
        submit.textContent = 'Import catalogue';
      }
      if (fileInput) fileInput.value = '';
    }
  }

  function renderTrainDataManager(train) {
    const { decoderFunctions, maintenance } = trainDataCollections(train);
    const functionRows = decoderFunctions.map((item, index) => {
      const number = Number(item.function_number);
      const label = Number.isFinite(number) ? `F${number}` : 'F—';
      const state = [item.momentary ? 'Momentary' : 'Latch', item.enabled === false ? 'Disabled' : 'Enabled'].join(' · ');
      return `<div class="record-row"><div class="record-main"><strong><span class="record-code">${label}</span>${escapeHtml(item.name || 'Unnamed function')}</strong><small>${escapeHtml(item.description || state)}</small></div><span class="record-meta">${escapeHtml(item.description ? state : '')}</span><span class="record-actions"><button class="icon-button small edit-decoder-function" data-record-index="${index}" title="Edit decoder function" aria-label="Edit decoder function">✎</button><button class="icon-button small record-delete" data-record-index="${index}" title="Delete decoder function" aria-label="Delete decoder function">×</button></span></div>`;
    }).join('');
    const maintenanceRows = maintenance.map((item, index) => {
      const date = item.service_date || 'Undated';
      const detail = [item.performed_by, item.mileage_km != null ? `${item.mileage_km} km` : '', item.cost != null ? `€${item.cost}` : ''].filter(Boolean).join(' · ');
      return `<div class="record-row"><div class="record-main"><strong>${escapeHtml(date)} · ${escapeHtml(item.service_type || 'Service')}</strong><small>${escapeHtml(item.description || detail || 'No service notes')}</small></div><span class="record-meta">${escapeHtml(detail)}</span><span class="record-actions"><button class="icon-button small edit-maintenance" data-record-index="${index}" title="Edit maintenance record" aria-label="Edit maintenance record">✎</button><button class="icon-button small record-delete" data-record-index="${index}" title="Delete maintenance record" aria-label="Delete maintenance record">×</button></span></div>`;
    }).join('');
    return `<div class="data-sheet"><div class="data-item"><span>Manufacturer / model</span><span>${escapeHtml([train.manufacturer, train.model_number].filter(Boolean).join(' · ') || '—')}</span></div><div class="data-item"><span>Era / scale</span><span>${escapeHtml(train.era || '—')} · H0</span></div><div class="data-item"><span>Decoder address / protocol</span><span>${escapeHtml(train.number || '—')} · ${escapeHtml(train.decoder_protocol || 'DCC')}</span></div><div class="data-item"><span>Train category</span><span>${escapeHtml(train.class || '—')}</span></div><div class="data-item"><span>Overall length / mass</span><span>${escapeHtml(train.length || '—')} m · ${escapeHtml(train.mass_g || '—')} g</span></div><div class="data-item"><span>Maximum speed</span><span>${escapeHtml(train.maxSpeed || '—')} km/h</span></div><div class="data-item"><span>Direction / block</span><span>${escapeHtml(train.direction || '—')} · ${escapeHtml(train.position || '—')}</span></div><div class="data-item"><span>Route target</span><span>${escapeHtml(train.destination_block_id || '—')}</span></div></div><div class="record-manager"><section class="record-section"><div class="record-section-heading"><div><p class="eyebrow">DECODER</p><h3>Function mappings <span>${decoderFunctions.length}</span></h3></div><button type="button" class="text-button" id="add-decoder-function">＋ Add</button></div><div class="record-list">${functionRows || '<div class="record-empty">No decoder functions mapped.</div>'}</div></section><section class="record-section"><div class="record-section-heading"><div><p class="eyebrow">SERVICE LOG</p><h3>Maintenance records <span>${maintenance.length}</span></h3></div><button type="button" class="text-button" id="add-maintenance">＋ Add</button></div><div class="record-list">${maintenanceRows || '<div class="record-empty">No maintenance records logged.</div>'}</div></section></div><div class="button-row catalogue-actions"><button type="button" class="button button-soft" id="export-train-catalogue">Export catalogue</button><button type="button" class="button button-soft" id="open-train-catalogue-import" aria-haspopup="dialog" aria-controls="train-catalogue-import">Import catalogue</button></div><p class="editor-note">Function mappings and service history are saved for the selected train profile.</p>`;
  }

  function openTrainDataEditor(kind, record, index) {
    const editor = $('#train-data-editor');
    if (!editor) return;
    app.editingTrainData = { kind, index: Number.isInteger(index) ? index : null };
    const isDecoder = kind === 'decoder';
    $('#train-data-editor-kicker').textContent = isDecoder ? 'DECODER FUNCTION MAP' : 'MAINTENANCE LOG';
    $('#train-data-editor-title').textContent = record ? (isDecoder ? 'Edit decoder function' : 'Edit maintenance record') : (isDecoder ? 'Add decoder function' : 'Add maintenance record');
    if (isDecoder) {
      const current = record || { function_number: '', name: '', description: '', momentary: false, enabled: true };
      $('#train-data-editor-body').innerHTML = `<div class="field-grid"><div class="field"><label for="data-function-number">Function number</label><input id="data-function-number" type="number" min="0" max="31" step="1" required value="${escapeHtml(current.function_number)}"></div><div class="field"><label for="data-function-name">Function name</label><input id="data-function-name" required value="${escapeHtml(current.name || current.function_name || '')}" placeholder="Cab lights"></div><div class="field field-wide"><label for="data-function-description">Description</label><input id="data-function-description" value="${escapeHtml(current.description || '')}" placeholder="Front and rear marker lights"></div><label class="check-field"><input id="data-function-momentary" type="checkbox"${current.momentary ? ' checked' : ''}><span>Momentary action</span></label><label class="check-field"><input id="data-function-enabled" type="checkbox"${current.enabled !== false ? ' checked' : ''}><span>Enabled in control desk</span></label></div>`;
      if (typeof editor.showModal === 'function') editor.showModal(); else editor.setAttribute('open', 'open');
      $('#data-function-name').focus();
      return;
    }
    const current = record || { service_date: new Date().toISOString().slice(0, 10), service_type: '', description: '', mileage_km: '', cost: '', performed_by: '', next_service_date: '' };
    $('#train-data-editor-body').innerHTML = `<div class="field-grid"><div class="field"><label for="data-service-date">Service date</label><input id="data-service-date" type="date" required value="${escapeHtml(current.service_date || '')}"></div><div class="field"><label for="data-service-type">Service type</label><input id="data-service-type" required value="${escapeHtml(current.service_type || '')}" placeholder="Routine service"></div><div class="field"><label for="data-mileage">Mileage (km)</label><input id="data-mileage" type="number" min="0" step="1" value="${escapeHtml(current.mileage_km == null ? '' : current.mileage_km)}"></div><div class="field"><label for="data-cost">Cost</label><input id="data-cost" type="number" min="0" step="0.01" value="${escapeHtml(current.cost == null ? '' : current.cost)}"></div><div class="field"><label for="data-performed-by">Performed by</label><input id="data-performed-by" value="${escapeHtml(current.performed_by || '')}" placeholder="Workshop or technician"></div><div class="field"><label for="data-next-service-date">Next service date</label><input id="data-next-service-date" type="date" value="${escapeHtml(current.next_service_date || '')}"></div><div class="field field-wide"><label for="data-service-description">Notes</label><textarea id="data-service-description" rows="3" placeholder="Work completed, parts replaced…">${escapeHtml(current.description || '')}</textarea></div></div>`;
    if (typeof editor.showModal === 'function') editor.showModal(); else editor.setAttribute('open', 'open');
    $('#data-service-date').focus();
  }

  function closeTrainDataEditor() {
    app.editingTrainData = null;
    const editor = $('#train-data-editor');
    if (editor && typeof editor.close === 'function') editor.close();
    else if (editor) editor.removeAttribute('open');
  }

  async function saveTrainDataEditor(event) {
    event.preventDefault();
    const train = selectedTrain();
    const editing = app.editingTrainData;
    if (!train || !editing) return;
    const { decoderFunctions, maintenance } = trainDataCollections(train);
    if (editing.kind === 'decoder') {
      const functionNumber = Number($('#data-function-number').value);
      const name = $('#data-function-name').value.trim();
      if (!Number.isInteger(functionNumber) || functionNumber < 0 || !name) {
        showToast('Enter a function number and name.', 'warning');
        return;
      }
      const existing = editing.index == null ? null : decoderFunctions[editing.index];
      const mapping = { ...(existing || {}), train_id: train.id, function_number: functionNumber, name, description: $('#data-function-description').value.trim(), momentary: $('#data-function-momentary').checked, enabled: $('#data-function-enabled').checked };
      if (existing) decoderFunctions.splice(editing.index, 1, mapping); else decoderFunctions.push(mapping);
      closeTrainDataEditor();
      renderEditor();
      await sendCommand({ type: 'update_decoder_function', train_id: train.id, function: clone(mapping) });
      showToast(`${name} ${existing ? 'updated' : 'added'}`, 'success');
      return;
    }
    const serviceDate = $('#data-service-date').value;
    const serviceType = $('#data-service-type').value.trim();
    if (!serviceDate || !serviceType) {
      showToast('Enter a service date and type.', 'warning');
      return;
    }
    const existing = editing.index == null ? null : maintenance[editing.index];
    const numberOrNull = (value) => value === '' ? null : Number(value);
    const record = { ...(existing || {}), train_id: train.id, service_date: serviceDate, service_type: serviceType, description: $('#data-service-description').value.trim(), mileage_km: numberOrNull($('#data-mileage').value), cost: numberOrNull($('#data-cost').value), performed_by: $('#data-performed-by').value.trim(), next_service_date: $('#data-next-service-date').value || null };
    if (existing) maintenance.splice(editing.index, 1, record); else maintenance.unshift(record);
    closeTrainDataEditor();
    renderEditor();
    const maintenancePayload = clone(record);
    if (maintenancePayload.record_id == null) delete maintenancePayload.record_id;
    await sendCommand({ type: 'upsert_maintenance', train_id: train.id, maintenance: maintenancePayload });
    showToast(`Maintenance record ${existing ? 'updated' : 'added'}`, 'success');
  }

  async function deleteDecoderFunction(index) {
    const train = selectedTrain();
    if (!train) return;
    const { decoderFunctions } = trainDataCollections(train);
    const mapping = decoderFunctions[index];
    if (!mapping || !window.confirm(`Delete F${mapping.function_number} ${mapping.name || 'function'}?`)) return;
    decoderFunctions.splice(index, 1);
    renderEditor();
    await sendCommand({ type: 'delete_decoder_function', train_id: train.id, function_number: Number(mapping.function_number) });
    showToast('Decoder function deleted', 'success');
  }

  async function deleteMaintenance(index) {
    const train = selectedTrain();
    if (!train) return;
    const { maintenance } = trainDataCollections(train);
    const record = maintenance[index];
    if (!record || !window.confirm(`Delete ${record.service_type || 'maintenance'} from ${record.service_date || 'this train'}?`)) return;
    maintenance.splice(index, 1);
    renderEditor();
    await sendCommand({ type: 'delete_maintenance', train_id: train.id, record_id: record.record_id });
    showToast('Maintenance record deleted', 'success');
  }

  const DEFAULT_FUNCTION_NAMES = { 0: 'Headlights', 1: 'Horn', 2: 'Whistle', 3: 'Shunting mode', 4: 'Coupler', 5: 'Sound', 6: 'Cab lights', 7: 'Auxiliary' };

  function decoderFunctionRows(train) {
    const mappings = Array.isArray(train.decoder_functions) ? train.decoder_functions : [];
    const byNumber = new Map(mappings.map((item) => [Number(item.function_number), item]));
    const states = train.decoder_function_states && typeof train.decoder_function_states === 'object' ? train.decoder_function_states : {};
    return Array.from({ length: 32 }, (_, number) => {
      const mapping = byNumber.get(number) || {};
      const active = Boolean(states[String(number)]);
      const available = mapping.enabled !== false;
      const label = mapping.name || DEFAULT_FUNCTION_NAMES[number] || 'Function ' + number;
      return '<button type="button" class="function-toggle' + (active ? ' is-on' : '') + '" data-function-number="' + number + '" aria-pressed="' + active + '"' + (available ? '' : ' disabled') + '><strong>F' + number + '</strong><span>' + escapeHtml(label) + '</span><small>' + (active ? 'ON' : 'OFF') + '</small></button>';
    }).join('');
  }

  function renderFunctionControls(train, compact) {
    return '<section class="function-control-panel' + (compact ? ' is-compact' : '') + '"><div class="record-section-heading"><div><p class="eyebrow">DECODER CONTROL</p><h3>Functions <span>F0–F31</span></h3></div><span class="settings-help">Changes are sent to the selected decoder</span></div><div class="function-toggle-grid">' + decoderFunctionRows(train) + '</div></section>';
  }

  function bindFunctionControls(root) {
    $$('.function-toggle', root).forEach((button) => button.addEventListener('click', () => toggleTrainFunction(Number(button.dataset.functionNumber), button.getAttribute('aria-pressed') !== 'true')));
  }

  async function toggleTrainFunction(functionNumber, enabled) {
    const train = selectedTrain();
    if (!train || !Number.isInteger(functionNumber)) return;
    const states = train.decoder_function_states && typeof train.decoder_function_states === 'object' ? train.decoder_function_states : {};
    const previous = Boolean(states[String(functionNumber)]);
    train.decoder_function_states = { ...states, [String(functionNumber)]: Boolean(enabled) };
    renderSidebar();
    renderEditor();
    renderAssembler();
    const response = await sendCommand({ type: 'set_train_function', train_id: train.id, function_number: functionNumber, enabled: Boolean(enabled) });
    if (!response) {
      train.decoder_function_states[String(functionNumber)] = previous;
      renderSidebar();
      renderEditor();
      renderAssembler();
    } else showToast('F' + functionNumber + (enabled ? ' enabled' : ' disabled'), 'success');
  }

  function renderEditor() {
    const train = selectedTrain();
    const content = $('#editor-content');
    if (!train) { content.innerHTML = '<div class="empty-state">No train selected.</div>'; return; }
    if (app.editorTab === 'settings') {
      const blocks = app.state.layout.blocks || [];
      const selectedDestination = String(train.destination_block_id || (blocks[blocks.length - 1] && blocks[blocks.length - 1].id) || '').toUpperCase();
      const destinationOptions = blocks.map((block) => { const id = String(block.id || '').toUpperCase(); const selected = id === selectedDestination ? ' selected' : ''; return `<option value="${escapeHtml(id)}"${selected}>${escapeHtml(block.name || id)} · ${escapeHtml(id)}</option>`; }).join('');
      const mass = train.mass_g == null ? '' : train.mass_g;
      const lengthMm = train.length_mm == null ? (Number(train.length) || 0) : train.length_mm;
      const controlMode = trainControlMode(train);
      const controlModeOptions = TRAIN_CONTROL_MODES.map((option) => `<option value="${option.value}"${option.value === controlMode ? ' selected' : ''}>${option.label}</option>`).join('');
      content.innerHTML = `<div class="field-grid"><div class="field"><label for="editor-name">Service name</label><input id="editor-name" value="${escapeHtml(train.name || '')}"></div><div class="field"><label for="editor-number">DCC address / service no.</label><input id="editor-number" inputmode="numeric" value="${escapeHtml(train.number || '')}"></div><div class="field"><label for="editor-origin">Origin</label><input id="editor-origin" value="${escapeHtml(train.origin || '')}"></div><div class="field"><label for="editor-destination">Destination</label><input id="editor-destination" value="${escapeHtml(train.destination || '')}"></div><div class="field"><label for="editor-destination-block">Destination block</label><select id="editor-destination-block">${destinationOptions || '<option value="">No blocks configured</option>'}</select></div><div class="field train-control-mode-field"><label for="editor-control-mode">Control mode</label><select id="editor-control-mode">${controlModeOptions}</select></div><div class="field"><label for="editor-manufacturer">Manufacturer</label><input id="editor-manufacturer" value="${escapeHtml(train.manufacturer || '')}"></div><div class="field"><label for="editor-model">Model / catalogue no.</label><input id="editor-model" value="${escapeHtml(train.model_number || '')}"></div><div class="field"><label for="editor-era">Railway era</label><input id="editor-era" value="${escapeHtml(train.era || '')}"></div><div class="field"><label for="editor-protocol">Decoder protocol</label><select id="editor-protocol"><option value="DCC"${String(train.decoder_protocol || 'DCC').toUpperCase() === 'DCC' ? ' selected' : ''}>DCC</option><option value="MM"${String(train.decoder_protocol || '').toUpperCase() === 'MM' ? ' selected' : ''}>Motorola</option><option value="SX"${String(train.decoder_protocol || '').toUpperCase() === 'SX' ? ' selected' : ''}>Selectrix</option></select></div><div class="field"><label for="editor-mass">Mass (g)</label><input id="editor-mass" type="number" min="0" step="1" value="${escapeHtml(mass)}"></div><div class="field"><label for="editor-length">Length (mm)</label><input id="editor-length" type="number" min="0" step="any" value="${escapeHtml(lengthMm)}"></div><div class="field"><label for="editor-max-speed">Maximum speed (km/h)</label><input id="editor-max-speed" type="number" min="0" step="1" value="${escapeHtml(train.maxSpeed || 140)}"></div></div><p class="editor-note">Changes are held in the dashboard until saved to the controller. The same profile can drive manual, automatic, and schedule simulation modes.</p><div class="button-row" style="padding: 12px 0 0"><button class="button button-primary" id="save-train-settings">Save profile</button><button class="button button-soft" id="route-selected">Plan route</button></div>`;
      content.insertAdjacentHTML('beforeend', renderFunctionControls(train, false));
      bindFunctionControls(content);
      $('#save-train-settings').addEventListener('click', saveTrainSettings);
      $('#editor-control-mode').addEventListener('change', (event) => setTrainMode(event.target.value));
      $('#route-selected').addEventListener('click', () => sendCommand({ type: 'plan_route', train_id: train.id, destination_block_id: $('#editor-destination-block').value }));
    } else if (app.editorTab === 'datasheet') {
      const database = train.database || {};
      const decoderFunctions = train.decoder_functions || database.decoder_functions || [];
      const maintenance = train.maintenance_records || database.maintenance_records || [];
      const rollingStock = train.rolling_stock || database.rolling_stock || [];
      content.innerHTML = renderTrainDataManager(train);
      $('#export-train-catalogue').addEventListener('click', exportTrainCatalogue);
      $('#open-train-catalogue-import').addEventListener('click', openTrainCatalogueImport);
      $('#add-decoder-function').addEventListener('click', () => openTrainDataEditor('decoder'));
      $('#add-maintenance').addEventListener('click', () => openTrainDataEditor('maintenance'));
      $$('.edit-decoder-function', content).forEach((button) => button.addEventListener('click', () => {
        const index = Number(button.dataset.recordIndex);
        const item = trainDataCollections(train).decoderFunctions[index];
        if (item) openTrainDataEditor('decoder', item, index);
      }));
      $$('.record-section:first-child .record-delete', content).forEach((button) => button.addEventListener('click', () => deleteDecoderFunction(Number(button.dataset.recordIndex))));
      $$('.edit-maintenance', content).forEach((button) => button.addEventListener('click', () => {
        const index = Number(button.dataset.recordIndex);
        const item = trainDataCollections(train).maintenance[index];
        if (item) openTrainDataEditor('maintenance', item, index);
      }));
      $$('.record-section:last-child .record-delete', content).forEach((button) => button.addEventListener('click', () => deleteMaintenance(Number(button.dataset.recordIndex))));
    } else {
      const consist = train.consist || [];
      content.innerHTML = `<div class="consist-summary"><span>Formation</span><strong>${consist.length} vehicles · ${escapeHtml(train.length || '—')} m</strong></div><div class="consist-list">${consist.map((item, index) => `<div class="consist-item"><span class="consist-icon">${index === 0 ? '▣' : '▤'}</span><span><strong>${escapeHtml(item.name || item.type || 'Vehicle')}</strong><small>${escapeHtml(item.detail || item.type || 'Rolling stock')}</small></span><span>${index === 0 ? 'Front' : `${index + 1}/${consist.length}`}</span></div>`).join('')}</div>`;
    }
    const dataLengthRow = $$('.data-item', content).find((row) => row.firstElementChild && row.firstElementChild.textContent === 'Overall length / mass');
    if (dataLengthRow && dataLengthRow.lastElementChild) {
      dataLengthRow.lastElementChild.textContent = formatLengthMm(train.length_mm) + ' mm · ' + (train.mass_g == null || train.mass_g === '' ? '-' : train.mass_g) + ' g';
    }
    const formationSummary = $('.consist-summary strong', content);
    if (formationSummary) formationSummary.textContent = (train.consist || []).length + ' vehicles · ' + formatLengthMm(train.length_mm) + ' mm';
    $$('.editor-tab').forEach((button) => button.classList.toggle('is-active', button.dataset.editorTab === app.editorTab));
  }

  function renderSchedules() {
    $('#schedule-list').innerHTML = app.state.schedules.map((schedule) => `<div class="schedule-row"><span class="schedule-time">${escapeHtml(schedule.time || '—')}</span><span class="schedule-service"><strong>${escapeHtml(schedule.service || 'Service')}</strong><small>#${escapeHtml(schedule.number || '—')}</small></span><span class="schedule-route">${escapeHtml(schedule.route || '—')}</span><span class="platform-tag">${escapeHtml(schedule.platform || '—')}</span><span class="schedule-state ${schedule.state === 'Delayed' ? 'delayed' : ''}">${escapeHtml(schedule.state || 'Planned')}</span><span class="schedule-actions"><button class="icon-button small schedule-menu" data-schedule-id="${escapeHtml(schedule.id)}" title="Edit service" aria-label="Edit service">⋯</button><button class="icon-button small schedule-delete danger-text" data-schedule-id="${escapeHtml(schedule.id)}" title="Remove service" aria-label="Remove service">×</button></span></div>`).join('');
    $$('.schedule-menu', $('#schedule-list')).forEach((button) => button.addEventListener('click', () => {
      const schedule = app.state.schedules.find((item) => item.id === button.dataset.scheduleId);
      if (!schedule) return;
      openScheduleEditor(schedule);
    }));
    $$('.schedule-delete', $('#schedule-list')).forEach((button) => button.addEventListener('click', () => deleteSchedule(button.dataset.scheduleId)));
  }

  async function deleteSchedule(scheduleId) {
    const schedule = app.state.schedules.find((item) => item.id === scheduleId);
    if (!schedule || !window.confirm(`Remove ${schedule.service || schedule.id} from the timetable? This cannot be undone.`)) return;
    const response = await sendCommand({ type: 'remove_schedule', schedule_id: scheduleId });
    if (!response) return;
    if (app.editingScheduleId === scheduleId) {
      app.editingScheduleId = null;
      $('#schedule-editor')?.close();
    }
    showToast(`${schedule.service || schedule.id} removed`, 'success');
  }

  function routeGraphNodes() {
    const sources = [
      ...(app.state.layout.blocks || []),
      ...(app.state.layout.waypoints || []),
      ...(app.state.layout.turntables || [])
    ];
    const seen = new Set();
    return sources.reduce((items, item) => {
      const id = String(item.id || '').trim().toUpperCase();
      if (!id || seen.has(id)) return items;
      seen.add(id);
      items.push({ value: id, label: `${item.name || id} · ${id}` });
      return items;
    }, []);
  }

  function routeFlowBlock(type, value) {
    const id = `route-flow-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
    if (type === 'routine') return { id, type, program_id: value };
    if (type === 'sync') return { id, type, locomotive_id: value };
    return { id, type: 'node', node_id: String(value || '').toUpperCase() };
  }

  function routeFlowNodeIds(flow = app.routeFlow) {
    return (Array.isArray(flow) ? flow : [])
      .filter((block) => (block.type || block.kind) === 'node')
      .map((block) => String(block.node_id || block.value || '').trim().toUpperCase())
      .filter(Boolean);
  }

  function routePickerMarkup(id, type, title, placeholder, options) {
    const enabled = options.length > 0;
    return `<p class="eyebrow">${escapeHtml(title)}</p><div class="route-picker"><select id="${escapeHtml(id)}" aria-label="${escapeHtml(title)}" ${enabled ? '' : 'disabled'}><option value="">${escapeHtml(enabled ? placeholder : `No ${title.toLowerCase()} configured`)}</option>${options.join('')}</select><button type="button" class="button button-soft route-picker-add" data-route-picker-type="${escapeHtml(type)}" data-route-picker-id="${escapeHtml(id)}" ${enabled ? '' : 'disabled'}>Add</button></div>`;
  }

  function addRoutePickerSelection(type, selectId) {
    const select = $(`#${selectId}`);
    if (!select || !select.value) return;
    addRouteFlowBlock(type, select.value);
  }

  function renderRouteFlow() {
    const nodeCatalogue = $('#route-node-catalogue');
    const routineCatalogue = $('#route-routine-catalogue');
    const syncCatalogue = $('#route-sync-catalogue');
    const flow = $('#route-flow');
    const empty = $('#route-flow-empty');
    const count = $('#route-flow-count');
    if (!nodeCatalogue || !routineCatalogue || !syncCatalogue || !flow) return;
    const nodes = routeGraphNodes();
    const trains = Array.isArray(app.state.trains) ? app.state.trains : [];
    const nodeOptions = nodes.map((node) => `<option value="${escapeHtml(node.value)}">${escapeHtml(node.label)}</option>`);
    const routineOptions = app.automationPrograms.map((program) => `<option value="${escapeHtml(program.id)}">${escapeHtml(program.name || program.id)} · ${escapeHtml(String((program.blocks || []).length))} action blocks</option>`);
    const syncOptions = trains.map((train) => `<option value="${escapeHtml(train.id)}">${escapeHtml(train.name || train.id)} · #${escapeHtml(train.number || '—')}</option>`);
    nodeCatalogue.innerHTML = routePickerMarkup('route-node-picker', 'node', 'Track node', 'Choose a track node…', nodeOptions);
    routineCatalogue.innerHTML = routePickerMarkup('route-routine-picker', 'routine', 'Routine', 'Choose a saved routine…', routineOptions);
    syncCatalogue.innerHTML = routePickerMarkup('route-sync-picker', 'sync', 'Sync locomotive', 'Choose a locomotive…', syncOptions);
    flow.innerHTML = (app.routeFlow || []).map((block, index) => {
      const kind = block.type || block.kind;
      const isRoutine = kind === 'routine' || kind === 'program';
      const isSync = kind === 'sync' || kind === 'sync_locomotive';
      const program = isRoutine ? app.automationPrograms.find((item) => item.id === (block.program_id || block.id)) : null;
      const syncTrain = isSync ? trains.find((item) => String(item.id) === String(block.locomotive_id || block.train_id || block.value)) : null;
      const node = !isRoutine && !isSync ? nodes.find((item) => item.value === String(block.node_id || block.value || '').toUpperCase()) : null;
      const label = isRoutine ? (block.name || program?.name || block.program_id || 'Routine') : isSync ? `Sync ${syncTrain?.name || block.locomotive_id || 'locomotive'}` : (node?.label?.split(' · ')[0] || block.node_id || 'Track node');
      const detail = isRoutine ? `Routine · ${program ? `${(program.blocks || []).length} blocks` : 'reference'}` : isSync ? 'Add locomotive to the active consist' : `Track node · ${String(block.node_id || block.value || '').toUpperCase()}`;
      const flowKind = isRoutine ? 'routine' : isSync ? 'sync' : 'node';
      return `<article class="route-flow-block" data-route-flow-index="${index}" data-route-flow-kind="${escapeHtml(flowKind)}" draggable="true"><span class="route-flow-index">${index + 1}</span><div class="route-flow-copy"><strong>${escapeHtml(label)}</strong><small>${escapeHtml(detail)}</small></div><div class="route-flow-actions"><button type="button" class="icon-button small" data-route-flow-action="up" data-route-flow-index="${index}" aria-label="Move block up">Up</button><button type="button" class="icon-button small" data-route-flow-action="down" data-route-flow-index="${index}" aria-label="Move block down">Down</button><button type="button" class="icon-button small" data-route-flow-action="delete" data-route-flow-index="${index}" aria-label="Remove block">Delete</button></div></article>`;
    }).join('<div class="route-flow-connector" aria-hidden="true"></div>');
    if (empty) empty.classList.toggle('is-hidden', Boolean(app.routeFlow.length));
    if (count) count.textContent = `${app.routeFlow.length} block${app.routeFlow.length === 1 ? '' : 's'}`;
    const nodeIds = routeFlowNodeIds();
    if (nodeIds.length) {
      const source = $('#route-source');
      const target = $('#route-target');
      if (source) source.value = nodeIds[0];
      if (target) target.value = nodeIds[nodeIds.length - 1];
    }
  }

  function addRouteFlowBlock(type, value) {
    if (!value || !['node', 'routine', 'sync'].includes(type)) return;
    app.routeFlow.push(routeFlowBlock(type, value));
    app.routeEditorDirty = true;
    renderRouteFlow();
  }

  function routeFlowAction(action, index) {
    const blocks = app.routeFlow;
    if (!blocks[index]) return;
    if (action === 'delete') blocks.splice(index, 1);
    if (action === 'up' && index > 0) [blocks[index - 1], blocks[index]] = [blocks[index], blocks[index - 1]];
    if (action === 'down' && index < blocks.length - 1) [blocks[index + 1], blocks[index]] = [blocks[index], blocks[index + 1]];
    app.routeEditorDirty = true;
    renderRouteFlow();
  }
  function clearRouteEditor() {
    app.editingRouteId = null;
    app.routeEditorDirty = false;
    app.routeFlow = [];
    app.routeFlowSelectedId = null;
    $('#route-id').value = '';
    $('#route-id').disabled = false;
    $('#route-name').value = '';
    $('#route-algorithm').value = 'a_star';
    const nodes = routeGraphNodes();
    fillScheduleSelect($('#route-source'), nodes, nodes[0]?.value || '', 'No graph nodes configured');
    fillScheduleSelect($('#route-target'), nodes, nodes[1]?.value || nodes[0]?.value || '', 'No graph nodes configured');
    $('#route-status').textContent = 'Create a reusable route flow. It will be bound to a train in a later step.';
    renderRouteFlow();
  }

  function openRouteEditor(route) {
    const current = route || {};
    app.editingRouteId = current.id || null;
    app.routeEditorDirty = false;
    app.routeFlow = Array.isArray(current.flow) && current.flow.length
      ? clone(current.flow)
      : (Array.isArray(current.node_ids) ? current.node_ids : [current.source_block_id || current.source, current.target_block_id || current.target]).filter(Boolean).map((nodeId) => routeFlowBlock('node', nodeId));
    $('#route-id').value = current.id || '';
    $('#route-id').disabled = Boolean(current.id);
    $('#route-name').value = current.name || '';
    const nodes = routeGraphNodes();
    fillScheduleSelect($('#route-source'), nodes, current.source_block_id || current.source || nodes[0]?.value || '', 'No graph nodes configured');
    fillScheduleSelect($('#route-target'), nodes, current.target_block_id || current.target || nodes[1]?.value || nodes[0]?.value || '', 'No graph nodes configured');
    $('#route-algorithm').value = current.algorithm || 'a_star';
    $('#route-status').textContent = current.id ? `Editing ${current.name || current.id}.` : 'Create a reusable route flow. It will be bound to a train in a later step.';
  }

  function renderRoutes() {
    const list = $('#route-list');
    if (!list) return;
    const routes = (Array.isArray(app.state.routes) ? app.state.routes : []).filter((route) => !pendingRouteDeletes.has(route.id));
    const nodes = routeGraphNodes();
    fillScheduleSelect($('#route-source'), nodes, $('#route-source').value, 'No graph nodes configured');
    fillScheduleSelect($('#route-target'), nodes, $('#route-target').value, 'No graph nodes configured');
    if (!app.routeEditorDirty && !app.editingRouteId && !$('#route-name').value) clearRouteEditor();
    renderRouteFlow();
    list.innerHTML = routes.length ? routes.map((route) => {
      const path = Array.isArray(route.node_ids) && route.node_ids.length ? route.node_ids.join(' → ') : (Array.isArray(route.flow) && route.flow.length ? route.flow.map((block) => block.type === 'sync' ? `Sync ${block.locomotive_id || 'locomotive'}` : block.type === 'routine' ? `Routine ${block.program_id || 'reference'}` : block.node_id || 'Block').join(' → ') : 'Stationary · current block');
      return `<div class="route-row" data-route-id="${escapeHtml(route.id)}"><span class="route-row-main"><strong>${escapeHtml(route.name || route.id)}</strong><small>${escapeHtml(route.id)} · ${escapeHtml(path)}</small></span><span class="route-row-meta">${escapeHtml(route.algorithm || 'a_star')}${route.enabled === false ? ' · disabled' : ''}</span><span class="route-row-actions"><button type="button" class="icon-button small" data-route-action="edit" title="Edit route">✎</button><button type="button" class="icon-button small" data-route-action="delete" title="Delete route">×</button></span></div>`;
    }).join('') : '<div class="empty-state">No saved route plans. Create one from the graph nodes above.</div>';
  }

  async function saveRouteEditor() {
    const id = $('#route-id').value.trim();
    const name = $('#route-name').value.trim();
    const flow = Array.isArray(app.routeFlow) ? app.routeFlow : [];
    const flowNodes = routeFlowNodeIds();
    const source = flowNodes[0] || null;
    const target = flowNodes[flowNodes.length - 1] || null;
    if (!id || !name || !flow.length) {
      $('#route-status').textContent = 'Route ID, name, and at least one flow block are required.';
      showToast('Add a route name and at least one flow block first.', 'warning');
      return;
    }
    const route = {
      id,
      name,
      source_block_id: source,
      target_block_id: target,
      node_ids: flowNodes,
      flow: flow.map((block) => { const { id: _blockId, ...savedBlock } = block; return savedBlock; }),
      algorithm: flowNodes.length ? $('#route-algorithm').value : 'stationary',
      enabled: true
    };
    const editing = app.editingRouteId;
    if (editing) {
      const existing = app.state.routes.find((item) => item.id === editing);
      const previous = existing ? clone(existing) : null;
      if (existing) Object.assign(existing, route, { id: editing, enabled: existing.enabled !== false });
      const response = await sendCommand({ type: 'update_route', route_id: editing, route });
      if (!response) {
        if (existing && previous) Object.assign(existing, previous);
        renderRoutes();
        return;
      }
      $('#route-status').textContent = `${name} updated.`;
      showToast(`${name} updated`, 'success');
    } else {
      const response = await sendCommand({ type: 'add_route', route });
      if (!response) {
        renderRoutes();
        return;
      }
      $('#route-status').textContent = `${name} saved.`;
      showToast(`${name} saved`, 'success');
    }
    app.routeEditorDirty = false;
    renderRoutes();
  }
  async function deleteRoute(routeId) {
    const route = app.state.routes.find((item) => item.id === routeId);
    if (!route || !window.confirm(`Delete ${route.name || route.id}?`)) return;
    if (pendingRouteDeletes.has(routeId)) return;
    pendingRouteDeletes.add(routeId);
    const previousRoutes = app.state.routes;
    app.state.routes = app.state.routes.filter((item) => item.id !== routeId);
    if (app.editingRouteId === routeId) clearRouteEditor();
    renderRoutes();
    const response = await sendCommand({ type: 'remove_route', route_id: routeId });
    pendingRouteDeletes.delete(routeId);
    if (!response) {
      app.state.routes = previousRoutes;
      renderRoutes();
      return;
    }
    app.state.routes = app.state.routes.filter((item) => item.id !== routeId);
    renderRoutes();
    showToast(`${route.name || route.id} deleted`, 'success');
  }

  function fillScheduleSelect(select, options, selected, emptyLabel) {
    if (!select) return;
    const values = options.length ? options : [{ value: '', label: emptyLabel }];
    select.innerHTML = values.map((option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`).join('');
    select.value = selected == null ? '' : String(selected);
  }

  function scheduleTimeSeconds(value) {
    const parts = String(value || '00:00').split(':').map(Number);
    return Math.max(0, ((parts[0] || 0) % 24) * 3600 + Math.max(0, Math.min(59, parts[1] || 0)) * 60);
  }

  function scheduleRouteLabel(route) {
    if (!route) return '';
    const name = String(route.name || route.id || '').trim();
    const path = Array.isArray(route.node_ids) ? route.node_ids.filter(Boolean).join('  →  ') : '';
    return name || path;
  }

  function updateScheduleDispatchFields() {
    const mode = $('#schedule-dispatch-mode')?.value || 'display';
    const routeField = $('#schedule-route-field');
    const coordinateField = $('#schedule-coordinate-field');
    if (routeField) routeField.classList.toggle('is-hidden', mode !== 'route');
    if (coordinateField) coordinateField.classList.toggle('is-hidden', mode !== 'coordinate');
  }

  function openScheduleEditor(schedule) {
    const editor = $('#schedule-editor');
    if (!editor) return;
    const current = schedule || { id: null, time: '11:15', service: 'New service', number: '', origin: '', destination: '', route: '', platform: '', state: 'Draft' };
    app.editingScheduleId = current.id || null;
    $('#schedule-editor-title').textContent = current.id ? 'Edit timetable service' : 'New timetable service';
    $('#schedule-time').value = current.time || '11:15';
    $('#schedule-service').value = current.service || '';
    $('#schedule-number').value = current.number || '';
    $('#schedule-origin').value = current.origin || '';
    $('#schedule-destination').value = current.destination || '';
    $('#schedule-coordinate').value = current.destination_coordinate ? formatPinboardCoordinate(current.destination_coordinate) : '';
    $('#schedule-state').value = current.state || 'Draft';
    const trains = (app.state.trains || []).map((train) => ({ value: train.id, label: `${train.name || `Train ${train.number || train.id}`} · #${train.number || '—'}` }));
    const linkedTrain = current.train_id || ((app.state.trains || []).find((train) => String(train.number || '') === String(current.number || '')) || {}).id || '';
    fillScheduleSelect($('#schedule-train'), trains, linkedTrain, 'No trains configured');
    const routes = (app.state.routes || []).map((route) => ({ value: route.id, label: `${scheduleRouteLabel(route)}${route.enabled === false ? ' · disabled' : ''}` }));
    fillScheduleSelect($('#schedule-route-id'), routes, current.route_id || '', routes.length ? 'Choose a saved route' : 'No saved routes configured');
    const selectedRoute = (app.state.routes || []).find((route) => route.id === current.route_id);
    $('#schedule-route').value = current.route || scheduleRouteLabel(selectedRoute) || '';
    const inferredMode = current.dispatch_mode || (current.route_id ? 'route' : current.destination_coordinate ? 'coordinate' : (current.id ? 'display' : (routes.length ? 'route' : 'coordinate')));
    $('#schedule-dispatch-mode').value = ['route', 'coordinate', 'display'].includes(inferredMode) ? inferredMode : 'display';
    updateScheduleDispatchFields();
    const stations = (app.state.layout.stations || []).map((station) => ({ value: station.id, label: station.name || station.id }));
    const firstStop = Array.isArray(current.stops) && current.stops[0] ? current.stops[0] : {};
    fillScheduleSelect($('#schedule-station'), stations, current.station_id || firstStop.station_id || '', 'No stations configured');
    const platforms = (app.state.layout.platforms || []).map((platform) => ({ value: platform.id, label: platform.name || platform.id }));
    fillScheduleSelect($('#schedule-platform'), platforms, current.platform || firstStop.platform_id || '', 'No platforms configured');
    if (typeof editor.showModal === 'function') editor.showModal();
    else editor.setAttribute('open', 'open');
    $('#schedule-service').focus();
  }

  async function saveScheduleEditor(event) {
    event.preventDefault();
    const service = $('#schedule-service').value.trim();
    if (!service) {
      showToast('A service name is required.', 'warning');
      return;
    }
    const trainId = $('#schedule-train').value;
    const origin = $('#schedule-origin').value.trim();
    const destination = $('#schedule-destination').value.trim();
    const dispatchMode = $('#schedule-dispatch-mode').value || 'display';
    const routeId = $('#schedule-route-id').value || '';
    const coordinateText = $('#schedule-coordinate').value.trim();
    let destinationCoordinate;
    if (dispatchMode === 'coordinate' && !coordinateText) {
      showToast('Enter a destination coordinate for coordinate dispatch.', 'warning');
      return;
    }
    if (dispatchMode === 'route' && !routeId) {
      showToast('Choose a saved route for route dispatch.', 'warning');
      return;
    }
    if (dispatchMode !== 'display' && !trainId && !$('#schedule-number').value.trim()) {
      showToast('Assign a train or enter its decoder number before dispatching.', 'warning');
      return;
    }
    if (dispatchMode === 'coordinate' && coordinateText) {
      const parsedCoordinate = parsePinboardCoordinate(coordinateText);
      const projectedCoordinate = parsedCoordinate && nearestPinboardCoordinate(parsedCoordinate);
      if (!projectedCoordinate) {
        showToast('Destination coordinate is not on the configured track.', 'warning');
        return;
      }
      destinationCoordinate = { x: Number(projectedCoordinate.x.toFixed(2)), y: Number(projectedCoordinate.y.toFixed(2)), from_node: projectedCoordinate.from_node, to_node: projectedCoordinate.to_node, progress: Number(projectedCoordinate.progress.toFixed(6)) };
    }
    const route = $('#schedule-route').value.trim() || [origin, destination].filter(Boolean).join('  →  ');
    const stationId = $('#schedule-station').value;
    const platformId = $('#schedule-platform').value;
    const arrivalSeconds = scheduleTimeSeconds($('#schedule-time').value);
    const fields = {
      time: $('#schedule-time').value || '00:00',
      service,
      number: $('#schedule-number').value.trim(),
      train_id: trainId || undefined,
      dispatch_mode: dispatchMode,
      route_id: dispatchMode === 'route' ? routeId : null,
      origin,
      destination,
      station_id: stationId || undefined,
      platform: platformId || '',
      route,
      destination_coordinate: dispatchMode === 'coordinate' ? destinationCoordinate : null,
      stops: stationId ? [{ station_id: stationId, platform_id: platformId || null, arrival_seconds: arrivalSeconds, departure_seconds: arrivalSeconds + 60 }] : [],
      state: $('#schedule-state').value || 'Draft'
    };
    const id = app.editingScheduleId;
    if (id) {
      const schedule = app.state.schedules.find((item) => item.id === id);
      if (!schedule) return;
      const previous = clone(schedule);
      Object.assign(schedule, fields);
      renderSchedules();
      const response = await sendCommand({ type: 'update_schedule', schedule_id: id, schedule: fields });
      if (!response) {
        Object.assign(schedule, previous);
        renderSchedules();
        return;
      }
      $('#schedule-editor').close();
      showToast(`${service} updated`, 'success');
    } else {
      const schedule = { id: `local-${Date.now()}`, ...fields };
      app.state.schedules.push(schedule);
      renderSchedules();
      const response = await sendCommand({ type: 'add_schedule', schedule });
      if (!response) {
        app.state.schedules = app.state.schedules.filter((item) => item.id !== schedule.id);
        renderSchedules();
        return;
      }
      $('#schedule-editor').close();
      showToast(`${service} added to dispatcher timetable`, 'success');
    }
    app.editingScheduleId = null;
  }

  function consistForTrain(train, createDraft) {
    if (!train) return [];
    if (app.consistDraft && app.consistDraft.trainId === train.id) return app.consistDraft.consist;
    const consist = clone(train.consist || []);
    if (createDraft) app.consistDraft = { trainId: train.id, consist, locomotiveIds: clone(train.locomotive_ids || []) };
    return consist;
  }

  function locomotiveIdsForTrain(train, createDraft = false) {
    if (!train) return [];
    if (app.consistDraft && app.consistDraft.trainId === train.id) return app.consistDraft.locomotiveIds || (app.consistDraft.locomotiveIds = []);
    const locomotiveIds = clone(train.locomotive_ids || []);
    if (createDraft) {
      app.consistDraft = { trainId: train.id, consist: clone(train.consist || []), locomotiveIds };
      return app.consistDraft.locomotiveIds;
    }
    return locomotiveIds;
  }

  function consistLengthMm(consist) {
    let unknownLength = false;
    const length = consist.reduce((total, item) => {
      const declared = Number(item.length_mm);
      if (Number.isFinite(declared) && declared > 0) return total + declared;
      const catalogueItem = rollingStockCatalogue().find((entry) => entry.id === item.catalogue_id || entry.name === item.name);
      const catalogueLength = Number(catalogueItem && catalogueItem.length_mm);
      if (Number.isFinite(catalogueLength) && catalogueLength > 0) return total + catalogueLength;
      unknownLength = true;
      return total;
    }, 0);
    return unknownLength ? null : length;
  }

  function addRollingStock() {
    const train = selectedTrain();
    const catalogueSelect = $('#rolling-stock-select');
    const item = rollingStockCatalogue().find((entry) => entry.id === (catalogueSelect && catalogueSelect.value));
    if (!train || !item) {
      showToast('Choose a rolling-stock entry first.', 'warning');
      return;
    }
    const consist = consistForTrain(train, true);
    const instanceId = `${item.id}-${app.nextConsistItemNumber++}`;
    const { count, ...catalogueData } = item;
    consist.push({ ...clone(catalogueData), id: instanceId, catalogue_id: item.id });
    renderAssembler();
    showToast(`${item.name} added to draft consist`, 'success');
  }

  function addLocomotiveToConsist() {
    const train = selectedTrain();
    const select = $('#assembler-locomotive-select');
    const memberId = select && select.value;
    const member = app.state.trains.find((item) => item.id === memberId);
    if (!train || !member) {
      showToast('Choose a locomotive to pair first.', 'warning');
      return;
    }
    const locomotiveIds = locomotiveIdsForTrain(train, true);
    if (member.id === train.id || locomotiveIds.includes(member.id)) return;
    locomotiveIds.push(member.id);
    renderAssembler();
    showToast(`${member.name || member.id} paired with ${train.name || train.id}`, 'success');
  }

  function removeLocomotiveFromConsist(memberId) {
    const train = selectedTrain();
    if (!train) return;
    const locomotiveIds = locomotiveIdsForTrain(train, true);
    const index = locomotiveIds.indexOf(memberId);
    if (index < 0) return;
    locomotiveIds.splice(index, 1);
    renderAssembler();
  }

  function changeConsistItem(index, direction) {
    const train = selectedTrain();
    if (!train) return;
    const consist = consistForTrain(train, true);
    const nextIndex = index + direction;
    if (index < 0 || index >= consist.length || nextIndex < 0 || nextIndex >= consist.length) return;
    [consist[index], consist[nextIndex]] = [consist[nextIndex], consist[index]];
    renderAssembler();
  }

  function removeConsistItem(index) {
    const train = selectedTrain();
    if (!train) return;
    const consist = consistForTrain(train, true);
    if (index < 0 || index >= consist.length) return;
    const removed = consist.splice(index, 1)[0];
    renderAssembler();
    showToast(`${removed.name || removed.type || 'Rolling stock'} removed from draft`, 'success');
  }

  async function saveConsist() {
    if (!app.consistDraft) {
      showToast('No consist changes to save', 'warning');
      return;
    }
    const train = app.state.trains.find((item) => item.id === app.consistDraft.trainId);
    if (!train) return;
    train.consist = clone(app.consistDraft.consist);
    train.locomotive_ids = clone(app.consistDraft.locomotiveIds || []);
    const lengthMm = consistLengthMm(train.consist);
    if (lengthMm != null) {
      train.length_mm = lengthMm;
      train.length = lengthMm;
    }
    const savedConsist = clone(train.consist);
    const savedLocomotiveIds = clone(train.locomotive_ids);
    app.consistDraft = null;
    renderAll();
    await sendCommand({ type: 'update_consist', train_id: train.id, consist: savedConsist, locomotive_ids: savedLocomotiveIds, length_mm: train.length_mm });
  }

  function renderAssembler() {
    const select = $('#assembler-train-select');
    const catalogueSelect = $('#rolling-stock-select');
    if (!catalogueSelect) {
      $('#add-car').insertAdjacentHTML('beforebegin', '<label class="rolling-stock-label" for="rolling-stock-select">Add from catalogue</label><select id="rolling-stock-select" class="rolling-stock-select" aria-label="Rolling stock catalogue"></select>');
      $('#rolling-stock-select').addEventListener('change', (event) => { event.target.dataset.selected = event.target.value; });
    }
    const stockSelect = $('#rolling-stock-select');
    const catalogue = rollingStockCatalogue();
    stockSelect.innerHTML = catalogue.length
      ? catalogue.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)} · ${escapeHtml(item.type)}${item.count != null ? ` · ×${escapeHtml(item.count)}` : ''}</option>`).join('')
      : '<option value="">No rolling stock in inventory</option>';
    stockSelect.disabled = !catalogue.length;
    const selectedCatalogueId = catalogue.some((item) => item.id === stockSelect.dataset.selected)
      ? stockSelect.dataset.selected
      : catalogue[0]?.id || '';
    stockSelect.value = selectedCatalogueId;
    stockSelect.dataset.selected = stockSelect.value;
    select.innerHTML = app.state.trains.map((train) => `<option value="${escapeHtml(train.id)}">${escapeHtml(train.name || `Train ${train.number}`)} · #${escapeHtml(train.number || '—')}</option>`).join('');
    select.value = (app.consistDraft && app.consistDraft.trainId) || app.selectedTrainId;
    const train = app.state.trains.find((item) => item.id === select.value) || selectedTrain();
    const locomotiveSelect = $('#assembler-locomotive-select');
    const locomotiveList = $('#assembler-locomotive-list');
    const locomotiveIds = train ? locomotiveIdsForTrain(train, false) : [];
    const availableLocomotives = app.state.trains.filter((item) => item.id !== (train && train.id) && !locomotiveIds.includes(item.id));
    if (locomotiveSelect) {
      locomotiveSelect.innerHTML = availableLocomotives.length
        ? availableLocomotives.map((item) => '<option value="' + escapeHtml(item.id) + '">' + escapeHtml(item.name || item.id) + ' - #' + escapeHtml(item.number || '-') + '</option>').join('')
        : '<option value="">All configured locomotives are already paired</option>';
      locomotiveSelect.disabled = !availableLocomotives.length;
    }
    const addLocomotiveButton = $('#add-locomotive');
    if (addLocomotiveButton) addLocomotiveButton.disabled = !availableLocomotives.length;
    if (locomotiveList) {
      const leadMarkup = train
        ? '<div class="locomotive-consist-item is-lead"><span class="consist-icon">L</span><span><strong>' + escapeHtml(train.name || train.id) + '</strong><small>Lead locomotive - decoder #' + escapeHtml(train.number || '-') + '</small></span><span class="consist-position">Lead</span></div>'
        : '';
      const helperMarkup = locomotiveIds.map((memberId, index) => {
        const member = app.state.trains.find((item) => item.id === memberId);
        if (!member) return '';
        return '<div class="locomotive-consist-item"><span class="consist-icon">L</span><span><strong>' + escapeHtml(member.name || member.id) + '</strong><small>Paired locomotive - decoder #' + escapeHtml(member.number || '-') + '</small></span><span class="consist-position">Helper ' + (index + 1) + '</span><button type="button" class="icon-button small" data-remove-locomotive="' + escapeHtml(member.id) + '" aria-label="Remove ' + escapeHtml(member.name || member.id) + '">x</button></div>';
      }).join('');
      locomotiveList.innerHTML = leadMarkup + helperMarkup || '<div class="empty-state">No locomotive selected.</div>';
    }
    const consist = (app.consistDraft && app.consistDraft.trainId === (train && train.id)) ? app.consistDraft.consist : (train && train.consist) || [];
    const draftStatus = $('.assembler-panel .tiny-status');
    if (draftStatus) draftStatus.textContent = app.consistDraft && app.consistDraft.trainId === (train && train.id) ? '● Draft' : '● Stored';
    $('#consist-list').innerHTML = consist.length ? consist.map((item, index) => `<div class="consist-item"><span class="consist-icon">${index === 0 ? '▣' : '▤'}</span><span><strong>${escapeHtml(item.name || item.type || 'Vehicle')}</strong><small>${escapeHtml(item.detail || item.type || 'Rolling stock')}</small></span><span class="consist-position">${index === 0 ? 'Front' : `${index + 1}/${consist.length}`}</span><span class="consist-actions"><button type="button" class="icon-button small consist-action" data-consist-action="up" data-consist-index="${index}" aria-label="Move ${escapeHtml(item.name || 'vehicle')} forward"${index === 0 ? ' disabled' : ''}>↑</button><button type="button" class="icon-button small consist-action" data-consist-action="down" data-consist-index="${index}" aria-label="Move ${escapeHtml(item.name || 'vehicle')} backward"${index === consist.length - 1 ? ' disabled' : ''}>↓</button><button type="button" class="icon-button small consist-action" data-consist-action="remove" data-consist-index="${index}" aria-label="Remove ${escapeHtml(item.name || 'vehicle')}">×</button></span></div>`).join('') : '<div class="empty-state">No rolling stock assigned. Choose an entry below to start the consist.</div>';
    $$('.consist-action', $('#consist-list')).forEach((button) => button.addEventListener('click', () => {
      const index = Number(button.dataset.consistIndex);
      if (button.dataset.consistAction === 'remove') removeConsistItem(index);
      else changeConsistItem(index, button.dataset.consistAction === 'up' ? -1 : 1);
    }));
  }

  function renderStats() {
    const blocks = app.state.layout.blocks || [];
    $('#block-count').textContent = blocks.length;
    $('#turnout-count').textContent = (app.state.layout.turnouts || []).length;
    $('#free-count').textContent = blocks.filter((block) => block.status === 'free').length;
    const info = app.state.layout_info;
    $('#route-count').textContent = info ? info.active_routes : '—';
    const power = info && info.power || {};
    const metrics = [
      ['Track power', !info ? 'Unknown' : power.available ? (power.track_power ? 'On' : 'Off') : (app.state.track_power ? 'On' : 'Off'), power.available ? 'Z21 reported' : app.state.connection.simulated ? 'Simulation' : 'Commanded state'],
      ['Consumption', power.available ? power.estimated_watts.toFixed(1) + ' W' : 'Unavailable', power.available ? 'Estimated track load' : power.reason || 'No readings'],
      ['Current / voltage', power.available ? power.current_a.toFixed(2) + ' A / ' + power.voltage_v.toFixed(1) + ' V' : '—', power.short_circuit ? 'Short circuit detected' : 'Z21 measurements'],
      ['Trains on track', info ? info.train_count : '—', 'Assigned positions'],
      ['Blocks occupied', info ? info.occupied_blocks + ' / ' + info.block_count : '—', 'Occupied / total'],
      ['Manual trains', info ? info.manual_trains : '—', 'Manual control'],
      ['Automatic trains', info ? info.automatic_trains : '—', 'Automatic control'],
      ['Route operations', info ? info.active_routes : '—', 'Executing or waiting for clearance']
    ];
    $('#layout-info-metrics').innerHTML = metrics.map(([label, value, note]) => '<div><small>' + escapeHtml(label) + '</small><strong>' + escapeHtml(String(value)) + '</strong><small>' + escapeHtml(note) + '</small></div>').join('');
    $('#layout-info-trains').textContent = info ? (info.trains.length ? info.trains.map(t => t.name + ' · ' + t.block_id + ' (' + t.mode + ')').join('  |  ') : 'No trains assigned to the track.') : 'Waiting for controller information.';
    $('#layout-info-note').textContent = (info ? info.stopped_trains + ' stopped · ' : '') + 'Positions are controller assignments, with occupancy feedback where available. Power readings are not mains energy usage.';
    $('#layout-power-toggle').textContent = app.powerPending ? 'Changing power…' : app.state.track_power ? 'Power off' : 'Power on';
    $('#layout-power-toggle').disabled = Boolean(app.powerPending);
    const block = selectedBlock();
    if (block) {
      const train = block.trainId ? app.state.trains.find((item) => item.id === block.trainId) : null;
      $('#map-selected-note').textContent = `${block.name || block.id} · ${block.status || 'free'}${train ? ` · ${train.name}` : ''}`;
    }
  }

  function renderConnectionEditor() {
    const from = $('#connection-from');
    const to = $('#connection-to');
    if (!from || !to) return;
    const blocks = app.state.layout.blocks || [];
    const options = blocks.map((block) => `<option value="${escapeHtml(block.id)}">${escapeHtml(block.name || block.id)} · ${escapeHtml(String(block.id).toUpperCase())}</option>`).join('');
    const previousFrom = from.value || app.selectedBlockId;
    const previousTo = to.value || (blocks.find((block) => block.id !== previousFrom) || {}).id;
    from.innerHTML = options;
    to.innerHTML = options;
    if (blocks.some((block) => block.id === previousFrom)) from.value = previousFrom;
    if (blocks.some((block) => block.id === previousTo)) to.value = previousTo;
    const trainSelect = $('#connection-limit-train');
    const previousTrain = trainSelect.value;
    trainSelect.innerHTML = '<option value="">All trains (default)</option>' + app.state.trains.map((train) => `<option value="${escapeHtml(train.id)}">${escapeHtml(train.name || train.id)}</option>`).join('');
    trainSelect.value = previousTrain;
    if (!app.connectionLimitDirty) loadConnectionLimit();
  }

  function loadConnectionLimit() {
    app.connectionLimitDirty = false;
    const from = $('#connection-from').value.toLowerCase();
    const to = $('#connection-to').value.toLowerCase();
    const trainId = $('#connection-limit-train').value;
    const connection = (app.state.layout.connections || []).find((item) => String(item.from).toLowerCase() === from && String(item.to).toLowerCase() === to);
    const limit = connection && (trainId ? (connection.train_speed_limits || {})[trainId] : connection.speed_limit_kmh);
    $('#connection-limit-speed').value = limit == null ? '' : String(limit);
    $('#connection-limit-speed').placeholder = trainId ? 'Inherit default' : 'No default limit';
    $('#save-connection-limit').disabled = !connection;
    $('#connection-limit-status').textContent = connection ? `${from.toUpperCase()} → ${to.toUpperCase()} · ${trainId ? 'Train override; blank inherits default' : 'All trains; blank removes default'}${connection.speed_limit_kmh == null ? '' : ` · default ${connection.speed_limit_kmh} km/h`}` : 'Select an existing directed connection before editing its limit.';
  }

  async function saveConnectionLimit() {
    const input = $('#connection-limit-speed');
    if (!input.checkValidity()) { input.reportValidity(); return; }
    const value = input.value.trim();
    const command = { type: 'set_connection_speed_limit', from: $('#connection-from').value, to: $('#connection-to').value, speed_limit_kmh: value === '' ? null : Number(value) };
    const trainId = $('#connection-limit-train').value;
    if (trainId) command.train_id = trainId;
    $('#save-connection-limit').disabled = true;
    try {
      const response = await fetchJson('/api/commands', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(command) });
      app.connectionLimitDirty = false;
      mergePayload(response); renderAll();
      $('#connection-limit-status').textContent = 'Limit applied. Save layout to keep it after restart.';
    } catch (error) { $('#connection-limit-status').textContent = `Not saved: ${error.message}`; }
    finally { $('#save-connection-limit').disabled = false; }
  }

  function editConnection(action) {
    const from = $('#connection-from').value;
    const to = $('#connection-to').value;
    if (!from || !to || from === to) {
      showToast('Choose two different blocks for a connection.', 'warning');
      return;
    }
    sendCommand({ type: action, from_block_id: from, to_block_id: to });
  }

  function updateWorkspaceVisibility() {
    const page = app.workspace;
    const trackPage = ['dispatch', 'layout'].includes(page);
    document.body.dataset.workspace = page;
    $('.dashboard').classList.toggle('is-hidden', page === 'settings');
    $('#settings-page').classList.toggle('is-hidden', page !== 'settings');
    $('.sidebar').classList.toggle('is-hidden', !['dispatch', 'trains'].includes(page));
    $('#systematic-panel').classList.toggle('is-hidden', !trackPage || app.layoutView !== 'systematic');
    $('#layout-panel').classList.toggle('is-hidden', !trackPage);
    $('#automation-studio-panel').classList.toggle('is-hidden', page !== 'layout');
    $('#layout-info-panel').classList.toggle('is-hidden', !trackPage);
    $('#layout-panel').classList.toggle('systematic-only', app.layoutView === 'systematic');
    $('#map-stage').classList.toggle('is-hidden', app.layoutView === 'systematic');
    $('.map-summary').classList.toggle('is-hidden', app.layoutView === 'systematic');
    $('#graph-editor-tools').classList.toggle('is-hidden', page !== 'layout' || !app.layoutEditing || !['editor', 'pinboard'].includes(app.layoutView));
    $('#pinboard-placement-tools').classList.toggle('is-hidden', !trackPage || app.layoutView !== 'pinboard');
    $('#connection-limit-editor').classList.toggle('is-hidden', page !== 'layout' || app.layoutView !== 'editor');
    renderSplineSectionEditor();
    $$('.map-legend .editor-action').forEach((button) => button.classList.toggle('is-hidden', page !== 'layout'));
    $('#add-layout-block').textContent = app.layoutView === 'pinboard' ? '＋ Place node' : '＋ Block';
    $('#scan-panel').classList.toggle('is-hidden', !['layout', 'scans'].includes(page));
    $('#route-panel').classList.toggle('is-hidden', page !== 'layout');
    $('.lower-grid').classList.toggle('is-hidden', !['dispatch', 'trains'].includes(page));
    const trainSection = page === 'trains' ? app.trainSection : null;
    $('#train-panel').classList.toggle('is-hidden', page === 'trains' ? !['overview', 'locomotives'].includes(trainSection) : page !== 'dispatch');
    // Keep the selected train editor available on the default overview for
    // existing workflows; the Locomotives tab simply focuses the same module.
    $('#train-editor-panel').classList.toggle('is-hidden', page !== 'trains');
    $('.bottom-grid').classList.toggle('is-hidden', !['dispatch', 'layout', 'trains', 'timetable'].includes(page));
    $('#timetable-panel').classList.toggle('is-hidden', !['dispatch', 'layout', 'timetable'].includes(page));
    $('#rolling-stock-panel').classList.toggle('is-hidden', page !== 'trains' || trainSection !== 'rolling-stock');
    $('#programming-panel').classList.toggle('is-hidden', page !== 'trains' || trainSection !== 'programming');
    $('#calibration-panel').classList.toggle('is-hidden', page !== 'trains' || trainSection !== 'programming');
    $('#assembler-panel').classList.toggle('is-hidden', page !== 'trains' || trainSection !== 'assembler');
    $$('.trains-subnav-link').forEach((link) => {
      const active = page === 'trains' && link.dataset.trainSection === trainSection;
      link.classList.toggle('is-active', active);
      if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    });
    $('#fit-layout').classList.toggle('is-hidden', !trackPage);
    $('.search-box').classList.toggle('is-hidden', !['dispatch', 'trains'].includes(page));
    const titles = { dispatch: 'Home', layout: 'Automation', trains: 'Your trains', timetable: 'Timetable', scans: '3D workspace' };
    $('#workspace-title').textContent = titles[page] || 'Settings';
    $('#workspace-context').textContent = `${app.state.layout.blocks.length} blocks · ${app.state.trains.length} trains`;
    $$('.mode-tab').forEach((button) => {
      const active = button.dataset.workspace === page;
      button.classList.toggle('is-active', active);
      if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
    });
    $$('.toolbar-tab').forEach((button) => button.classList.toggle('is-active', button.id === 'toggle-layout-edit' ? app.layoutEditing : button.dataset.layoutView === app.layoutView));
    workspaceLayout?.setPage(app.workspace);
  }

  function navigateWorkspace(page) {
    app.workspace = page;
    if (page === 'layout') { app.layoutView = 'graph'; app.layoutEditing = false; }
    else { app.layoutEditing = false; if (page === 'dispatch' && app.layoutView === 'editor') app.layoutView = 'graph'; }
    renderGraph();
    updateWorkspaceVisibility();
    if (['layout', 'scans'].includes(page)) { renderScans(); window.requestAnimationFrame(() => app.scanViewer && app.scanViewer.resize()); }
    if (page === 'settings') { renderScanLibrary(); if (!app.settingsDirty) renderSettings(); }
    window.history.replaceState(null, '', `#${page}`);
    window.scrollTo({ top: 0, behavior: 'instant' });
    $(page === 'settings' ? '#settings-title' : '#workspace-title').focus({ preventScroll: true });
  }

  function selectTrain(id) {
    if (!app.state.trains.some((train) => train.id === id)) return;
    cancelSpeedDraft();
    app.selectedTrainId = id;
    app.consistDraft = null;
    renderSidebar(); renderTrainList(); renderEditor(); renderAssembler();
    if (app.workspace === 'dispatch') navigateWorkspace('trains');
    showToast(`${selectedTrain().name} selected`, 'success');
  }

  function selectBlock(id) {
    if (!app.state.layout.blocks.some((block) => block.id === id)) return;
    app.selectedBlockId = id;
    $$('.block-node', $('#layout-svg')).forEach((node) => node.classList.toggle('is-selected', node.dataset.blockId === id));
    renderSystematicView(); renderStats();
    const block = selectedBlock();
    showToast(`${block.name || block.id}: ${block.status || 'free'} block`, 'success');
  }

  function openBlockEditor(block) {
    const current = block || selectedBlock();
    if (!current) {
      showToast('Select a block before opening the editor.', 'warning');
      return;
    }
    app.editingBlockId = current.id;
    $('#block-id').value = current.id;
    $('#block-name').value = current.name || current.id;
    $('#block-length').value = current.length_mm == null ? '' : current.length_mm;
    $('#block-station').value = current.station || '';
    const editor = $('#block-editor');
    if (typeof editor.showModal === 'function') editor.showModal();
    else editor.setAttribute('open', 'open');
    $('#block-name').focus();
  }

  async function saveBlockEditor(event) {
    event.preventDefault();
    const block = app.state.layout.blocks.find((item) => item.id === app.editingBlockId);
    if (!block) return;
    try {
      const id = $('#block-id').value.trim().toUpperCase();
      const response = await fetchJson('/api/commands', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type: 'update_block', block_id: block.id, block: { id, name: $('#block-name').value.trim() || id, length_mm: Math.max(0, Number($('#block-length').value) || 0), station: $('#block-station').value.trim() } }) });
      mergePayload(response);
      app.selectedBlockId = id.toLowerCase();
      app.editingBlockId = null;
      $('#block-editor').close();
      renderAll();
      showToast(id + ' updated. Save layout to keep your changes.', 'success');
    } catch (error) { showToast(error.message, 'warning'); }
  }

  async function addLayoutBlock() {
    const index = app.state.layout.blocks.length;
    const block = {
      x: 62 + (index % 5) * 160,
      y: 224 + (Math.floor(index / 5) % 2) * 78,
      width: 126,
      height: 56,
      status: 'free',
      station: 'New section'
    };
    app.layoutEditing = true;
    try {
      const previousIds = new Set(app.state.layout.blocks.map(item => item.id));
      const response = await fetchJson('/api/commands', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type: 'add_block', block }) });
      mergePayload(response);
      const added = app.state.layout.blocks.find(item => !previousIds.has(item.id));
      if (added) app.selectedBlockId = added.id;
      if (added && app.layoutView === 'pinboard') app.pendingBlockPlacementId = added.id;
      renderAll();
      showToast(app.layoutView === 'pinboard' ? 'New node added. Click the pinboard to place it.' : 'Block added. Save layout to keep your changes.', 'success');
    } catch (error) { showToast(error.message, 'warning'); }
  }

  async function addSplinePoint() {
    if (app.workspace !== 'layout') return;
    app.layoutView = 'pinboard'; app.layoutEditing = true;
    renderGraph(); updateWorkspaceVisibility();
    let geometry = selectedSplineGeometry();
    const from = String($('#connection-from').value || '').trim().toUpperCase();
    const to = String($('#connection-to').value || '').trim().toUpperCase();
    if (!geometry) {
      const blocks = app.state.layout.blocks || [];
      const edge = normalizedEdges(app.state.layout, blocks).find((item) => [item.from, item.to].every((id) => [from, to].includes(String(id).toUpperCase())));
      if (edge) {
        const points = edgeControlPoints(blocks.find((item) => item.id === edge.from), blocks.find((item) => item.id === edge.to), edge);
        selectSplineSection(edge, points, 0); geometry = selectedSplineGeometry();
      }
    }
    if (!geometry) {
      showToast('Select a rail section or choose two connected nodes to add a spline point.', 'warning');
      return;
    }
    const used = new Set([...(app.state.layout.waypoints || []), ...(app.state.layout.blocks || [])].map((item) => String(item.id || '').toUpperCase()));
    let sequence = (app.state.layout.waypoints || []).length + 1;
    let id = `WP${String(sequence).padStart(2, '0')}`;
    while (used.has(id)) id = `WP${String(++sequence).padStart(2, '0')}`;
    const selected = { ...app.selectedSplineSection };
    const response = await sendCommand({ type: 'add_spline_point', ...selected, waypoint_id: id });
    if (response) {
      app.selectedSplineSection = { ...selected, end_anchor_id: id };
      app.selectedWaypointId = id;
      app.splineSpeedDirty = false;
      renderAll();
      showToast('Spline point added on the curve. Drag it to move it. Save layout to keep changes.', 'success');
    }
  }

  function svgPoint(event) {
    const svg = $('#layout-svg');
    const point = svg.createSVGPoint();
    point.x = event.clientX; point.y = event.clientY;
    return point.matrixTransform(svg.getScreenCTM().inverse());
  }

  function beginLayoutPan(event) {
    if (!['dispatch', 'layout'].includes(app.workspace) || !['graph', 'pinboard', 'editor'].includes(app.layoutView)) return;
    if (event.button !== 0 && event.button !== 1) return;
    const forcePan = event.button === 1 || app.panKeyDown || event.altKey;
    const interactive = event.target.closest('.block-node, .pinboard-node, .pinboard-train, .pinboard-spline-point, .pinboard-turnout, .pinboard-bezier-handle, .signal-node, .turntable-node')
      || (app.layoutEditing && !app.pendingBlockPlacementId && event.target.closest('.pinboard-track-section'));
    if (interactive && !forcePan) return;
    const svg = $('#layout-svg');
    const view = app.layoutViewports[app.layoutView === 'pinboard' ? 'pinboard' : 'graph'] || svg.viewBox.baseVal;
    app.panDrag = {
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      startPoint: svgPoint(event),
      screenToSvg: svg.getScreenCTM().inverse(),
      view: { x: view.x, y: view.y, width: view.width, height: view.height },
      moved: false
    };
    $('#map-stage').classList.add('is-panning');
    event.preventDefault();
    event.stopPropagation();
    window.addEventListener('pointermove', moveLayoutPan);
    window.addEventListener('pointerup', endLayoutPan);
    window.addEventListener('pointercancel', endLayoutPan);
  }

  function moveLayoutPan(event) {
    const drag = app.panDrag;
    if (!drag || event.pointerId !== drag.pointerId) return;
    const svg = $('#layout-svg');
    const pointer = svg.createSVGPoint();
    pointer.x = event.clientX; pointer.y = event.clientY;
    const point = pointer.matrixTransform(drag.screenToSvg);
    const dx = point.x - drag.startPoint.x; const dy = point.y - drag.startPoint.y;
    if (Math.abs(event.clientX - drag.startClientX) + Math.abs(event.clientY - drag.startClientY) > 3) drag.moved = true;
    const view = { ...drag.view, x: drag.view.x - dx, y: drag.view.y - dy };
    const key = app.layoutView === 'pinboard' ? 'pinboard' : 'graph';
    app.layoutViewports[key] = view;
    app.layoutViewportManual[key] = true;
    svg.setAttribute('viewBox', `${view.x} ${view.y} ${view.width} ${view.height}`);
    event.preventDefault();
  }

  function endLayoutPan(event) {
    if (!app.panDrag || (event && event.pointerId !== app.panDrag.pointerId)) return;
    if (app.panDrag.moved) app.suppressCanvasClickUntil = Date.now() + 350;
    app.panDrag = null;
    $('#map-stage').classList.remove('is-panning');
    window.removeEventListener('pointermove', moveLayoutPan);
    window.removeEventListener('pointerup', endLayoutPan);
    window.removeEventListener('pointercancel', endLayoutPan);
  }

  function beginBlockDrag(event, blockId) {
    if (!app.layoutEditing || event.button !== 0) return;
    const block = app.state.layout.blocks.find((item) => item.id === blockId);
    if (!block) return;
    const point = svgPoint(event);
    app.layoutDrag = { blockId, pointerId: event.pointerId, start: point, original: { x: Number(block.x) || 0, y: Number(block.y) || 0 } };
    window.addEventListener('pointermove', moveBlockDrag);
    window.addEventListener('pointerup', endBlockDrag);
    window.addEventListener('pointercancel', endBlockDrag);
    event.preventDefault();
  }

  function moveBlockDrag(event) {
    if (!app.layoutDrag || (app.layoutDrag.pointerId != null && event.pointerId !== app.layoutDrag.pointerId)) return;
    const block = app.state.layout.blocks.find((item) => item.id === app.layoutDrag.blockId);
    if (!block) return;
    const point = svgPoint(event);
    block.x = Math.max(0, Math.round(app.layoutDrag.original.x + point.x - app.layoutDrag.start.x));
    block.y = Math.max(0, Math.round(app.layoutDrag.original.y + point.y - app.layoutDrag.start.y));
    renderGraph();
  }

  function endBlockDrag(event) {
    if (!app.layoutDrag) return;
    if (event && app.layoutDrag.pointerId != null && event.pointerId !== app.layoutDrag.pointerId) return;
    const block = app.state.layout.blocks.find((item) => item.id === app.layoutDrag.blockId);
    if (block) sendCommand({ type: 'move_block', block_id: block.id, x: block.x, y: block.y });
    app.layoutDrag = null;
    window.removeEventListener('pointermove', moveBlockDrag);
    window.removeEventListener('pointerup', endBlockDrag);
    window.removeEventListener('pointercancel', endBlockDrag);
  }

  async function deleteSelectedBlock() {
    if (app.workspace !== 'layout' || !app.layoutEditing || !['editor', 'pinboard'].includes(app.layoutView)) {
      showToast('Switch to layout edit mode before deleting a block.', 'warning');
      return;
    }
    const block = selectedBlock();
    if (!block) {
      showToast('Select a block before deleting it.', 'warning');
      return;
    }
    if (!window.confirm(`Delete ${block.name || block.id}? This cannot be undone.`)) return;
    const response = await sendCommand({ type: 'remove_block', block_id: block.id });
    if (!response) return;
    app.layoutDrag = null;
    app.waypointDrag = null;
    app.pendingBlockPlacementId = null;
    app.selectedBlockId = app.state.layout.blocks[0]?.id || null;
    renderAll();
    showToast(`${block.name || block.id} deleted`, 'success');
  }

  function saveTrainSettings() {
    const train = selectedTrain();
    if (!train) return;
    train.name = $('#editor-name').value.trim() || train.name;
    train.number = $('#editor-number').value.trim() || train.number;
    train.origin = $('#editor-origin').value.trim() || train.origin;
    train.destination = $('#editor-destination').value.trim() || train.destination;
    train.destination_block_id = $('#editor-destination-block').value || train.destination_block_id || null;
    train.manufacturer = $('#editor-manufacturer').value.trim();
    train.model_number = $('#editor-model').value.trim();
    train.era = $('#editor-era').value.trim();
    train.decoder_protocol = $('#editor-protocol').value;
    const mass = Number($('#editor-mass').value);
    const lengthMm = Number($('#editor-length').value);
    const maxSpeed = Number($('#editor-max-speed').value);
    train.mass_g = Number.isFinite(mass) && mass >= 0 ? mass : null;
    train.length_mm = Number.isFinite(lengthMm) && lengthMm >= 0 ? lengthMm : 0;
    train.length = train.length_mm;
    train.maxSpeed = Number.isFinite(maxSpeed) && maxSpeed >= 0 ? maxSpeed : train.maxSpeed;
    renderAll();
    sendCommand({ type: 'update_train', train_id: train.id, train: { name: train.name, number: train.number, origin: train.origin, destination: train.destination, destination_block_id: train.destination_block_id, manufacturer: train.manufacturer, model_number: train.model_number, era: train.era, decoder_protocol: train.decoder_protocol, mass_g: train.mass_g, length_mm: train.length_mm, maxSpeed: train.maxSpeed } });
  }

  async function removeSelectedTrain() {
    const train = selectedTrain();
    if (!train) {
      showToast('Select a train before removing it.', 'warning');
      return;
    }
    if (!window.confirm(`Remove ${train.name || train.id} from the fleet? This deletes its profile and stored calibration data.`)) return;
    const response = await sendCommand({ type: 'remove_train', train_id: train.id });
    if (!response) return;
    app.selectedTrainId = app.state.trains[0]?.id || null;
    app.consistDraft = null;
    app.pendingPinboardTrain = null;
    app.pinboardPlacementSelection = '';
    renderAll();
    showToast(`${train.name || train.id} removed from the fleet`, 'success');
  }

  function setTrainMode(mode) {
    const train = selectedTrain();
    if (!train || !TRAIN_CONTROL_MODES.some((option) => option.value === mode)) return;
    cancelSpeedDraft();
    speedChoices.delete(train.id);
    train.mode = mode;
    train.status = trainStatusForMode(train, mode);
    renderSidebar();
    renderTrainList();
    renderEditor();
    sendCommand({ type: 'set_train_mode', train_id: train.id, mode });
  }

  async function sendCommand(command) {
    app.stateMutationRevision += 1;
    const changesControl = ['set_train_mode', 'set_mode', 'track_power', 'emergency_stop', 'stop_all', 'stop_train', 'stop', 'remove_train'].includes(command.type);
    let releaseControl = null;
    if (changesControl) {
      app.controlPending = (app.controlPending || 0) + 1;
      cancelSpeedDraft();
      speedChoices.clear();
      renderSidebar();
      const previous = speedInFlight;
      const gate = new Promise((resolve) => { releaseControl = resolve; });
      speedInFlight = previous.then(() => gate);
      await previous;
    }
    try {
      const response = await fetchJson('/api/commands', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(command) });
      mergePayload(response);
      app.source = 'api';
      const simulated = Boolean(app.state.connection && (app.state.connection.simulated || app.state.connection.mode === 'simulation'));
      app.state.connection = { ...app.state.connection, connected: !simulated, simulated, label: simulated ? 'Simulation API online' : 'Z21 controller online', detail: 'Command acknowledged' };
      updateSync('Command acknowledged by controller', 'success');
      renderAll();
      showToast('Controller command accepted', 'success');
      return response;
    } catch (error) {
      updateSync('Command not accepted by controller', 'warning');
      showToast(error.message, 'warning');
      return null;
    } finally { if (changesControl) { app.controlPending -= 1; releaseControl(); renderSidebar(); } }
  }

  function setSpeed(speed) {
    const train = selectedTrain();
    if (!train) return;
    cancelSpeedDraft();
    if (Number(speed) === 0) {
      // Stop remains actionable while an earlier mode/speed request is pending.
      // It targets the explicitly selected train, even if selection then changes.
      speedChoices.set(train.id, 0);
      speedInFlight = speedInFlight.then(async () => {
        app.speedSending = true; renderSidebar();
        try {
          const response = await fetchJson('/api/commands', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type: 'stop_train', train_id: train.id }) });
          mergePayload(response); renderAll();
        } catch (error) { showToast(`Stop not confirmed: ${error.message}`, 'warning'); }
        finally { app.speedSending = false; renderSidebar(); }
      });
      renderSidebar();
      return;
    }
    queueSpeed(speed, true);
    renderSidebar();
  }

  async function setDirection(direction) {
    const train = selectedTrain();
    if (!train || app.directionPending || app.controlPending || Number(train.speed) > 0 || Number(train.actual_speed_kmh) > 0 || trainControlMode(train) === 'automatic' || app.source !== 'api') return;
    cancelSpeedDraft();
    const epoch = speedEpoch;
    app.directionPending = true; renderSidebar();
    try {
      await speedInFlight;
      if (epoch !== speedEpoch || selectedTrain()?.id !== train.id) return;
      const response = await fetchJson('/api/commands', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type: 'set_direction', train_id: train.id, direction }) });
      mergePayload(response); renderAll();
      showToast(`Direction set to ${direction}. Speed remains zero.`, 'success');
    } catch (error) { showToast(error.message, 'warning'); }
    finally { app.directionPending = false; renderSidebar(); }
  }

  async function setWorldClock(reset = false) {
    const input = $('#setting-world-clock-time');
    const setButton = $('#settings-world-clock-set');
    const resetButton = $('#settings-world-clock-reset');
    const status = $('#settings-world-clock-status');
    if (setButton.disabled || resetButton.disabled) return;
    const time = reset ? '00:00' : input.value;
    if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(time)) {
      status.textContent = 'Choose a time from 00:00 to 23:59.';
      input.focus();
      return;
    }
    input.disabled = setButton.disabled = resetButton.disabled = true;
    status.textContent = reset ? 'Resetting world clock…' : 'Setting world clock…';
    app.stateMutationRevision += 1;
    try {
      const response = await fetchJson(reset ? '/api/world-clock/reset' : '/api/world-clock/set', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(reset ? {} : { time })
      });
      app.stateMutationRevision += 1;
      mergePayload(response);
      app.source = 'api';
      input.value = time;
      status.textContent = `World clock ${reset ? 'reset' : 'set'} to ${time}. Timetable continues from this time.`;
      updateSync('World clock time acknowledged by controller', 'success');
      renderAll();
    } catch (error) {
      status.textContent = `World clock change was not acknowledged: ${error.message}`;
      showToast(error.message, 'warning');
    } finally {
      input.disabled = setButton.disabled = resetButton.disabled = false;
    }
  }

  async function tickSimulation() {
    const button = $('#simulation-tick');
    if (button) button.disabled = true;
    app.stateMutationRevision += 1;
    try {
      const simulated = Boolean(app.state.connection && (app.state.connection.simulated || app.state.connection.mode === 'simulation'));
      const response = await fetchJson(simulated ? '/api/simulation/tick' : '/api/world-clock/advance', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(simulated ? { seconds: 60, rate: app.simRate } : { seconds: 60 })
      });
      mergePayload(response);
      app.source = 'api';
      app.state.connection = { ...app.state.connection, simulated, detail: simulated ? 'Simulation tick acknowledged' : 'World clock advance acknowledged' };
      updateSync(simulated ? 'Simulation tick acknowledged by controller' : 'World clock advanced by controller', 'success');
      renderAll();
    } catch (error) {
      updateSync('Clock advance was not acknowledged by the controller', 'warning');
      showToast(error.message, 'warning');
    } finally {
      if (button) button.disabled = false;
      renderSidebar();
    }
  }

  async function toggleSimulation() {
    const button = $('#simulation-toggle');
    const wasRunning = Boolean(app.state.simulation.running);
    const shouldRun = !wasRunning;
    freezeWorldClock();
    app.state.simulation.running = shouldRun;
    renderSidebar();
    if (button) button.disabled = true;
    try {
      const response = await sendCommand({ type: shouldRun ? 'resume_simulation' : 'pause_simulation' });
      if (!response) {
        app.state.simulation.running = wasRunning;
        renderSidebar();
      }
    } finally {
      if (button) button.disabled = false;
      renderSidebar();
    }
  }

  async function saveLayout() {
    try {
      await fetchJson('/api/layouts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ layout_id: 'default', name: app.state.layout.name || 'H0 layout' }) });
      updateSync('Layout saved to controller storage', 'success');
      showToast('Layout saved', 'success');
    } catch (error) {
      showToast('Layout could not be saved while the controller is offline.', 'warning');
    }
  }

  async function loadSavedLayout() {
    try {
      app.stateMutationRevision += 1;
      const response = await fetchJson('/api/commands', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type: 'load_layout', layout_id: 'default' }) });
      app.selectedWaypointId = null;
      app.selectedSplineSection = null;
      app.splineSpeedDirty = false;
      mergePayload(response);
      renderAll();
      updateSync('Saved layout loaded from controller storage', 'success');
      showToast('Saved layout loaded', 'success');
    } catch (error) {
      showToast('No saved default layout is available yet.', 'warning');
    }
  }

  function simulateNextScheduleEvent() {
    sendCommand({ type: 'simulate_schedule' });
  }

  async function linkScan() {
    const image = window.prompt('Photo-scan image URL or relative path');
    if (!image || !image.trim()) return;
    const fallbackLabel = image.trim().split('/').pop() || `Scan ${app.state.scans.length + 1}`;
    const label = window.prompt('Scan name', fallbackLabel) || fallbackLabel;
    await sendCommand({ type: 'add_scan', scan: { id: `scan-${Date.now()}`, label: label.trim() || fallbackLabel, description: 'Linked photo scan', image: image.trim(), anchor: { x: 0.5, y: 0.48 } } });
  }

  async function useLocalScan(event) {
    const file = event.target.files && event.target.files[0];
    event.target.value = '';
    if (!file) return;
    try { await uploadScan(file); showToast('Photo saved on this controller.', 'success'); }
    catch (error) { showToast(error.message, 'warning'); }
  }

  async function toggleTurnout(id) {
    const turnout = (app.state.layout.turnouts || []).find((item) => item.id === id);
    if (!turnout) return;
    turnout.state = turnout.state === 'straight' ? 'diverging' : 'straight';
    renderGraph();
    await sendCommand({ type: 'set_turnout', turnout_id: id, state: turnout.state });
  }

  async function toggleTrackPower() {
    if (app.powerPending) return;
    if (app.settings.operations.confirm_power_actions) {
      const nextState = app.state.track_power === false ? 'on' : 'off';
      if (!window.confirm('Change track power ' + nextState + '? This affects every train on the layout.')) return;
    }
    cancelSpeedDraft();
    const enabled = app.state.track_power === false;
    app.powerPending = true;
    renderSidebar(); renderStats();
    try { await sendCommand({ type: 'track_power', enabled }); }
    finally { app.powerPending = false; renderSidebar(); renderStats(); }
  }

  async function toggleSignal(id) {
    const signal = (app.state.layout.signals || []).find((item) => item.id === id);
    if (!signal) return;
    const next = { red: 'green', green: 'yellow', yellow: 'red' }[String(signal.aspect || 'red').toLowerCase()] || 'red';
    signal.aspect = next;
    renderGraph();
    await sendCommand({ type: 'set_signal', signal_id: id, aspect: next });
  }

  async function alignTurntable(id) {
    const turntable = (app.state.layout.turntables || []).find((item) => item.id === id);
    if (!turntable) return;
    const connected = turntable.connected_block_ids || turntable.connected || [];
    if (!connected.length) return;
    const current = String(turntable.aligned_block_id || '').toUpperCase();
    const next = connected.find((item) => String(item).toUpperCase() !== current) || connected[0];
    turntable.aligned_block_id = next;
    renderGraph();
    await sendCommand({ type: 'align_turntable', turntable_id: id, block_id: next });
  }

  function setupEvents() {
    const mapStage = $('#map-stage');
    mapStage.addEventListener('pointerdown', beginLayoutPan, true);
    document.addEventListener('keydown', (event) => {
      if (event.code !== 'Space' || event.repeat || event.target.closest('input, textarea, select, button, [contenteditable="true"]')) return;
      if (mapStage.matches(':hover') || document.activeElement === mapStage) { app.panKeyDown = true; event.preventDefault(); }
    });
    document.addEventListener('keyup', (event) => { if (event.code === 'Space') app.panKeyDown = false; });
    updateNativeControls = (preserveStatus = false) => {
      const available = Boolean(window.pywebview && window.pywebview.api && typeof window.pywebview.api.switch_mode === 'function');
      const wlan = selectedWlanProfile();
      renderWlanPresentation(app.settingsRuntime);
      $('#settings-connect-z21').disabled = !available || Boolean(app.nativeModePending) || Boolean(app.settingsDirty);
      $('#settings-use-simulation').disabled = !available || Boolean(app.nativeModePending);
      if (preserveStatus || app.nativeModePending) return;
      if (app.settingsDirty) $('#settings-native-status').textContent = `Save or discard your settings changes before ${wlan ? 'connecting via WLAN' : 'connecting to Z21'}.`;
      else if (available) $('#settings-native-status').textContent = wlan
        ? 'Desktop controls ready. Connect Windows to the Z21 Wi-Fi before choosing Connect via WLAN.'
        : 'Desktop connection controls ready.';
      else $('#settings-native-status').textContent = wlan
        ? 'Connect via WLAN is available in the standalone Windows app. This browser cannot switch controller mode.'
        : 'Available in the standalone Windows app. Browser users must restart the controller to change connection mode.';
    };
    const switchNativeMode = async (mode) => {
      if (app.nativeModePending || !window.pywebview || !window.pywebview.api) return;
      if (app.settingsDirty) { $('#settings-native-status').textContent = 'Save or discard your settings changes before switching mode.'; return; }
      const wlan = mode === 'z21' && selectedWlanProfile();
      cancelSpeedDraft();
      speedChoices.clear();
      app.nativeModePending = true;
      updateNativeControls(); renderSidebar();
      $('#settings-native-status').textContent = wlan ? 'Waiting for confirmation to connect via WLAN…' : 'Waiting for desktop confirmation…';
      try {
        await speedInFlight;
        const result = await window.pywebview.api.switch_mode(mode);
        if (result && (result.error || result.ok === false || result.accepted === false)) throw new Error(result.error || result.message || (result.cancelled ? 'Connection change cancelled.' : 'Connection mode was not changed.'));
        if (result && (result.transport_profile != null || result.transport_status != null)) {
          app.settingsRuntime = { ...(app.settingsRuntime || {}), ...(result.transport_profile == null ? {} : { transport_profile: result.transport_profile }), ...(result.transport_status == null ? {} : { transport_status: result.transport_status }) };
          renderWlanPresentation(app.settingsRuntime);
        }
        $('#settings-native-status').textContent = result && (result.message || result.status) || (wlan ? 'WLAN connection requested. Windows must already be connected to the Z21 Wi-Fi.' : 'Connection mode change requested.');
      } catch (error) { $('#settings-native-status').textContent = error.message || 'Connection change failed.'; }
      finally {
        app.nativeModePending = false;
        updateNativeControls(true);
        renderSidebar();
      }
    };
    updateNativeControls();
    window.addEventListener('pywebviewready', updateNativeControls);
    $('#settings-connect-z21').addEventListener('click', () => switchNativeMode('z21'));
    $('#settings-use-simulation').addEventListener('click', () => switchNativeMode('simulation'));
    $('#layout-svg').addEventListener('dblclick', (event) => {
      const node = event.target.closest('.block-node');
      if (!node) return;
      event.preventDefault();
      app.layoutDrag = null;
      app.selectedBlockId = node.dataset.blockId;
      openBlockEditor();
    });
    document.addEventListener('keydown', (event) => {
      if (!['Delete', 'Backspace'].includes(event.key)
        || (event.target && typeof event.target.closest === 'function' && event.target.closest('input, textarea, select, [contenteditable="true"]'))
        || app.workspace !== 'layout' || !app.layoutEditing
        || !['editor', 'pinboard'].includes(app.layoutView)) return;
      event.preventDefault();
      void deleteSelectedBlock();
    });
    $$('.mode-tab').forEach((button) => button.addEventListener('click', () => navigateWorkspace(button.dataset.workspace)));
    $$('.trains-subnav-link').forEach((link) => link.addEventListener('click', (event) => {
      event.preventDefault();
      app.trainSection = link.dataset.trainSection || 'overview';
      if (app.workspace !== 'trains') navigateWorkspace('trains');
      else updateWorkspaceVisibility();
      renderTrainList();
      const target = document.querySelector(link.getAttribute('href'));
      const navigation = document.querySelector('.trains-subnav');
      if (!target || !navigation) return;
      requestAnimationFrame(() => {
        const targetTop = target.getBoundingClientRect().top + window.scrollY;
        const navigationOffset = navigation.getBoundingClientRect().height + 20;
        const reducedMotion = app.settings?.interface?.reduce_motion === true;
        window.scrollTo({ top: Math.max(0, targetTop - navigationOffset), behavior: reducedMotion ? 'auto' : 'smooth' });
      });
    }));
    $('#app-settings-form').addEventListener('submit', saveAppSettings);
    $('#app-settings-form').addEventListener('input', (event) => { if (event.target.id === 'setting-world-clock-time') return; app.settingsDirty = true; $('#settings-save-status').textContent = 'Unsaved changes'; renderWlanPresentation(app.settingsRuntime); updateNativeControls(); });
    $('#settings-world-clock-set').addEventListener('click', () => setWorldClock());
    $('#settings-world-clock-reset').addEventListener('click', () => setWorldClock(true));
    $('#setting-world-clock-time').addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); setWorldClock(); } });
    $('#setting-theme').addEventListener('change', (event) => applyTheme(event.target.value));
    const previewInterface = () => applyInterfaceSettings({ interface: { density: $('#setting-interface-density').value, show_connection_detail: $('#setting-show-connection-detail').checked, reduce_motion: $('#setting-reduce-motion').checked } });
    $('#setting-interface-density').addEventListener('change', previewInterface);
    $('#setting-show-connection-detail').addEventListener('change', previewInterface);
    $('#setting-reduce-motion').addEventListener('change', previewInterface);
    $('#setting-routing-adaptive').addEventListener('change', (event) => { $('#setting-routing-idle').disabled = !event.target.checked; });
    $('#settings-discard').addEventListener('click', () => { app.settingsDirty = false; renderSettings(); applyTheme(app.settings.theme); $('#settings-save-status').textContent = app.settingsLoaded ? 'Changes discarded.' : 'Controller settings have not loaded yet.'; });
    $('#settings-scan-library').addEventListener('click', (event) => {
      const button = event.target.closest('[data-view-scan]');
      if (button) { app.selectedScanId = button.dataset.viewScan; navigateWorkspace('scans'); }
    });
    $('#settings-upload-scan').addEventListener('click', async () => {
      const button = $('#settings-upload-scan');
      button.disabled = true;
      $('#settings-upload-status').textContent = 'Uploading photograph…';
      try {
        await uploadScan($('#settings-scan-file').files[0]);
        $('#settings-scan-file').value = '';
        $('#settings-upload-status').textContent = 'Photo saved. Open it from your library below.';
      } catch (error) { $('#settings-upload-status').textContent = error.message; }
      finally { button.disabled = false; }
    });
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      if ($('#setting-theme').value === 'system') applyTheme('system');
    });
    $('#open-layout-assets').addEventListener('click', () => openLayoutAssetsEditor($('#layout-asset-kind').value));
    $('#close-layout-assets').addEventListener('click', closeLayoutAssetsEditor);
    $('#cancel-layout-asset').addEventListener('click', closeLayoutAssetsEditor);
    $('#add-layout-asset').addEventListener('click', () => openLayoutAssetsEditor($('#layout-asset-kind').value));
    $('#layout-asset-kind').addEventListener('change', (event) => {
      app.layoutAssetEditing = null;
      renderLayoutAssetInspector();
      renderLayoutAssetForm(newLayoutAsset(event.target.value));
    });
    $('#layout-asset-form').addEventListener('submit', saveLayoutAsset);
    $('#layout-asset-list').addEventListener('click', (event) => {
      const button = event.target.closest('[data-asset-action]');
      if (!button) return;
      const kind = $('#layout-asset-kind').value;
      const record = layoutAssetCollection(kind).find((item) => assetIdsMatch(item.id, button.dataset.assetId));
      if (!record) return;
      if (button.dataset.assetAction === 'edit') openLayoutAssetsEditor(kind, record);
      if (button.dataset.assetAction === 'remove') removeLayoutAsset(kind, record.id);
    });
    $('#scan-select').addEventListener('change', (event) => { app.selectedScanId = event.target.value; renderScans(); });
    $('#link-scan').addEventListener('click', linkScan);
    $('#use-local-scan').addEventListener('click', () => $('#scan-file').click());
    $('#scan-file').addEventListener('change', useLocalScan);
    $('#add-layout-block').addEventListener('click', addLayoutBlock);
    $('#add-spline-point').addEventListener('click', addSplinePoint);
    $('#spline-section-speed').addEventListener('input', () => { app.splineSpeedDirty = true; });
    $('#save-spline-section-speed').addEventListener('click', saveSplineSectionSpeed);
    $('#pinboard-train-select').addEventListener('change', (event) => { app.pinboardPlacementSelection = event.target.value; app.pendingPinboardTrain = null; renderPinboardTrainPicker(); });
    $('#place-pinboard-train').addEventListener('click', beginPinboardTrainPlacement);
    $('#edit-selected-block').addEventListener('click', () => openBlockEditor());
    $('#delete-selected-block').addEventListener('click', deleteSelectedBlock);
    $('#block-editor-form').addEventListener('submit', saveBlockEditor);
    $('#cancel-block-editor').addEventListener('click', () => { app.editingBlockId = null; $('#block-editor').close(); });
    $('#close-block-editor').addEventListener('click', () => { app.editingBlockId = null; $('#block-editor').close(); });
    $('#connect-blocks').addEventListener('click', () => editConnection('connect_blocks'));
    $('#disconnect-blocks').addEventListener('click', () => editConnection('disconnect_blocks'));
    ['#connection-from', '#connection-to'].forEach((selector) => $(selector).addEventListener('change', () => {
      app.selectedSplineSection = null; app.splineSpeedDirty = false;
      loadConnectionLimit(); renderGraph();
    }));
    $('#connection-limit-train').addEventListener('change', loadConnectionLimit);
    $('#connection-limit-speed').addEventListener('input', () => { app.connectionLimitDirty = true; });
    $('#save-connection-limit').addEventListener('click', saveConnectionLimit);
    $('#save-layout').addEventListener('click', saveLayout);
    $('#load-layout').addEventListener('click', loadSavedLayout);
    $$('.control-mode').forEach((button) => button.addEventListener('click', () => {
      const requestedMode = button.dataset.controlMode;
      const train = selectedTrain();
      if (requestedMode === 'safe') {
        // Safe stop remains the explicit fleet-wide emergency action.
        app.controlMode = 'safe';
        renderSidebar();
        void sendCommand({ type: 'set_mode', mode: 'stopped' });
        return;
      }
      if (requestedMode === 'simulation') {
        showToast('Simulation is controlled by the simulation clock below.', 'warning');
        return;
      }
      if (!train || !['manual', 'automatic'].includes(requestedMode)) return;
      app.controlMode = requestedMode;
      train.mode = requestedMode;
      train.status = trainStatusForMode(train, requestedMode);
      renderSidebar();
      void sendCommand({ type: 'set_train_mode', train_id: train.id, mode: requestedMode });
    }));
    $$('.toolbar-tab').forEach((button) => button.addEventListener('click', () => {
      if (button.id === 'toggle-layout-edit') {
        if (app.workspace !== 'layout') {
          const view = app.layoutView;
          navigateWorkspace('layout'); app.layoutView = view;
        }
        app.layoutEditing = !app.layoutEditing;
        if (app.layoutView !== 'pinboard') app.layoutView = app.layoutEditing ? 'editor' : 'graph';
      } else {
        app.layoutView = button.dataset.layoutView;
        if (app.workspace !== 'layout') app.layoutEditing = false;
      }
      renderGraph(); updateWorkspaceVisibility();
    }));
    $$('.editor-tab').forEach((button) => button.addEventListener('click', () => { app.editorTab = button.dataset.editorTab; renderEditor(); }));
    $('#speed-slider').addEventListener('input', (event) => queueSpeed(event.target.value));
    $('#speed-slider').addEventListener('change', flushSpeedDraft);
    $('#speed-slider').addEventListener('pointerup', flushSpeedDraft);
    $('#speed-slider').addEventListener('pointercancel', cancelSpeedDraft);
    $('#calibration-train-select').addEventListener('change', (event) => { app.selectedTrainId = event.target.value; renderSidebar(); renderTrainList(); renderEditor(); renderAssembler(); renderCalibration(); renderProgramming(); });
    $('#programming-train-select').addEventListener('change', (event) => { app.selectedTrainId = event.target.value; renderSidebar(); renderTrainList(); renderEditor(); renderAssembler(); renderCalibration(); renderProgramming(); });
    $('#validate-programming').addEventListener('click', validateProgramming);
    $('#write-programming').addEventListener('click', writeProgramming);
    $('#read-programming').addEventListener('click', readProgramming);
    $('#program-dcc-address').addEventListener('click', programDccAddress);
    $('#save-inventory').addEventListener('click', saveInventory);
    $('#inventory-search').addEventListener('input', renderInventory);
    $('#inventory-list').addEventListener('click', (event) => {
      const button = event.target.closest('[data-inventory-adjust]');
      const row = event.target.closest('[data-inventory-id]');
      if (!button || !row) return;
      sendCommand({ type: 'adjust_rolling_stock_inventory', item_id: row.dataset.inventoryId, delta: Number(button.dataset.inventoryAdjust) });
    });
    $('#recording-train-select').addEventListener('change', (event) => { app.selectedTrainId = event.target.value; renderSidebar(); renderTrainList(); renderEditor(); renderRecording(); });
    $('#start-recording').addEventListener('click', startRecording);
    $('#stop-recording').addEventListener('click', stopRecording);
    $('#play-recording').addEventListener('click', playRecording);
    $('#automation-train-select').addEventListener('change', (event) => { app.automationDraft.trainId = event.target.value; app.selectedTrainId = event.target.value; renderSidebar(); renderAutomationStudio(); });
    $('#automation-program-name').addEventListener('input', (event) => { app.automationDraft.name = event.target.value; $('#automation-program-title').textContent = event.target.value || 'New train routine'; });
    $('#automation-catalogue').addEventListener('click', (event) => { const button = event.target.closest('[data-action-block]'); if (button) addAutomationBlock(button.dataset.actionBlock); });
    $('#automation-catalogue').addEventListener('dragstart', (event) => { const button = event.target.closest('[data-action-block]'); if (button) event.dataTransfer.setData('text/plain', button.dataset.actionBlock); });
    $('#automation-dropzone').addEventListener('dragover', (event) => { event.preventDefault(); $('#automation-dropzone').classList.add('is-dragging'); });
    $('#automation-dropzone').addEventListener('dragleave', () => $('#automation-dropzone').classList.remove('is-dragging'));
    $('#automation-dropzone').addEventListener('drop', (event) => { event.preventDefault(); $('#automation-dropzone').classList.remove('is-dragging'); addAutomationBlock(event.dataTransfer.getData('text/plain')); });
    $('#automation-block-list').addEventListener('change', updateAutomationBlockField);
    $('#automation-block-list').addEventListener('click', (event) => { const button = event.target.closest('[data-automation-action]'); if (button) automationBlockAction(button.dataset.automationAction, Number(button.dataset.automationIndex)); else if (!event.target.closest('input, select, textarea, button')) { const block = event.target.closest('[data-automation-block-id]'); if (block) { app.automationSelectedBlockId = block.dataset.automationBlockId; renderAutomationStudio(); } } });
    $('#automation-program-list').addEventListener('click', (event) => { const button = event.target.closest('[data-automation-program-action]'); const row = event.target.closest('[data-automation-program-id]'); if (!button || !row) return; const id = row.dataset.automationProgramId; if (button.dataset.automationProgramAction === 'load') loadAutomationProgram(id); if (button.dataset.automationProgramAction === 'run') { loadAutomationProgram(id); runAutomationProgram(); } if (button.dataset.automationProgramAction === 'delete') deleteAutomationProgram(id); });
    $('#automation-import-recording').addEventListener('click', importLastRecording);
    $('#automation-clear-program').addEventListener('click', clearAutomationProgram);
    $('#automation-save-program').addEventListener('click', saveAutomationProgram);
    $('#automation-run-program').addEventListener('click', runAutomationProgram);
    $('#automation-stop-program').addEventListener('click', stopAutomationProgram);
    $('#start-calibration').addEventListener('click', startCalibration);
    $('#cancel-calibration').addEventListener('click', () => sendCommand({ type: 'cancel_calibration' }));
    $('#record-calibration').addEventListener('click', recordCalibration);
    document.addEventListener('keydown', (event) => {
      if (!event.ctrlKey || event.key.toLowerCase() !== 'c' || !app.pinboardCursor || app.layoutView !== 'pinboard') return;
      const text = formatPinboardCoordinate(app.pinboardCursor);
      navigator.clipboard?.writeText(text).then(() => showToast('Coordinate copied: ' + text, 'success')).catch(() => showToast(text, 'warning'));
    });
    window.addEventListener('pagehide', cancelSpeedDraft);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) {
        window.clearTimeout(app.pollTimer);
        renderWorldClock();
        void pollController().finally(schedulePolling);
      }
    });
    $('#stop-train').addEventListener('click', () => setSpeed(0));
    $('#direction-forward').addEventListener('click', () => setDirection('forward'));
    $('#direction-reverse').addEventListener('click', () => setDirection('reverse'));
    $('#selected-train-functions').addEventListener('click', (event) => {
      const button = event.target.closest('[data-train-function]');
      if (!button || button.disabled) return;
      const functionNumber = Number(button.dataset.trainFunction);
      void toggleTrainFunction(functionNumber, button.getAttribute('aria-pressed') !== 'true');
    });
    $('#simulation-toggle').addEventListener('click', () => { void toggleSimulation(); });
    $('#simulation-tick').addEventListener('click', tickSimulation);
    $('#track-power-toggle').addEventListener('click', toggleTrackPower);
    $('#simulation-rate-select').addEventListener('change', (event) => { app.simRate = Number(event.target.value) || 1; renderSidebar(); showToast(`Fast-forward multiplier set to ${app.simRate}×; live clock remains real time.`, 'success'); });
    $('#refresh-button').addEventListener('click', () => { showToast('Refreshing controller state…', 'success'); bootstrap(); });
    $('#train-search').addEventListener('input', (event) => { app.filter = event.target.value; renderTrainList(); });
    $('#scan-train-presence').addEventListener('click', async () => {
      const button = $('#scan-train-presence');
      button.disabled = true;
      button.textContent = 'Scanning…';
      try { await sendCommand({ type: 'scan_train_presence' }); }
      finally { button.disabled = false; button.textContent = '⌁ Ping saved DCC IDs'; }
    });
    $('#fit-layout').addEventListener('click', () => { app.zoom = 1; $('#layout-svg').style.transform = 'scale(1)'; $('#layout-zoom-label').textContent = '100%'; fitGraphViewport(); showToast('Layout fitted to workspace', 'success'); });
    $('#layout-zoom-in').addEventListener('click', () => changeZoom(.1));
    $('#layout-zoom-out').addEventListener('click', () => changeZoom(-.1));
    $('#open-settings').addEventListener('click', () => navigateWorkspace('settings'));
    $('#add-train').addEventListener('click', () => {
      const id = `local-${Date.now()}`;
      const train = { id, number: '', name: 'New service', class: 'Manual', status: 'Ready', speed: 0, position: 'B04', block_id: 'B04', origin: 'Origin', destination: 'Destination', direction: 'Eastbound', decoder: 'Not assigned', length: 0, length_mm: 0, maxSpeed: 120, consist: [] };
      app.state.trains.push(train);
      selectTrain(id);
      sendCommand({ type: 'add_train', train });
      showToast('New train profile added to the controller', 'success');
    });
    $('#add-schedule').addEventListener('click', () => {
      openScheduleEditor();
    });
    $('#new-route').addEventListener('click', clearRouteEditor);
    $('#save-route').addEventListener('click', saveRouteEditor);
    $('#cancel-route').addEventListener('click', clearRouteEditor);

    ['#route-id', '#route-name', '#route-source', '#route-target', '#route-algorithm'].forEach((selector) => $(selector).addEventListener('input', () => { app.routeEditorDirty = true; }));
    ['#route-node-catalogue', '#route-routine-catalogue', '#route-sync-catalogue'].forEach((selector) => $(selector).addEventListener('click', (event) => {
      const button = event.target.closest('[data-route-picker-type]');
      if (button) addRoutePickerSelection(button.dataset.routePickerType, button.dataset.routePickerId);
    }));
    $('#route-flow-dropzone').addEventListener('dragover', (event) => { event.preventDefault(); $('#route-flow-dropzone').classList.add('is-dragging'); });
    $('#route-flow-dropzone').addEventListener('dragleave', () => $('#route-flow-dropzone').classList.remove('is-dragging'));
    $('#route-flow-dropzone').addEventListener('drop', (event) => { event.preventDefault(); $('#route-flow-dropzone').classList.remove('is-dragging'); const raw = event.dataTransfer.getData('application/x-route-flow'); if (!raw) return; try { const item = JSON.parse(raw); addRouteFlowBlock(item.type, item.value); } catch { showToast('That flow block could not be added.', 'warning'); } });
    $('#route-flow').addEventListener('click', (event) => { const button = event.target.closest('[data-route-flow-action]'); if (button) routeFlowAction(button.dataset.routeFlowAction, Number(button.dataset.routeFlowIndex)); });
    $('#route-list').addEventListener('click', (event) => {
      const row = event.target.closest('[data-route-id]');
      const action = event.target.closest('[data-route-action]')?.dataset.routeAction;
      if (!row || !action) return;
      const route = app.state.routes.find((item) => item.id === row.dataset.routeId);
      if (!route) return;
      if (action === 'edit') { openRouteEditor(route); renderRoutes(); }
      if (action === 'delete') deleteRoute(route.id);
    });
    $('#simulate-schedule').addEventListener('click', simulateNextScheduleEvent);
    $('#schedule-editor-form').addEventListener('submit', saveScheduleEditor);
    $('#schedule-dispatch-mode').addEventListener('change', updateScheduleDispatchFields);
    $('#schedule-route-id').addEventListener('change', (event) => {
      const route = (app.state.routes || []).find((item) => item.id === event.target.value);
      if (route) $('#schedule-route').value = scheduleRouteLabel(route);
    });
    $('#cancel-schedule-editor').addEventListener('click', () => { app.editingScheduleId = null; $('#schedule-editor').close(); });
    $('#close-schedule-editor').addEventListener('click', () => { app.editingScheduleId = null; $('#schedule-editor').close(); });
    $('#train-data-editor-form').addEventListener('submit', saveTrainDataEditor);
    $('#cancel-train-data-editor').addEventListener('click', closeTrainDataEditor);
    $('#close-train-data-editor').addEventListener('click', closeTrainDataEditor);
    $('#train-catalogue-import-form').addEventListener('submit', importTrainCatalogue);
    $('#train-catalogue-file').addEventListener('change', updateCatalogueFileStatus);
    $('#cancel-train-catalogue-import').addEventListener('click', closeTrainCatalogueImport);
    $('#close-train-catalogue-import').addEventListener('click', closeTrainCatalogueImport);
    $('#schedule-train').addEventListener('change', (event) => {
      const train = app.state.trains.find((item) => item.id === event.target.value);
      if (!train) return;
      if (!$('#schedule-number').value) $('#schedule-number').value = train.number || '';
      if (!$('#schedule-service').value || $('#schedule-service').value === 'New service') $('#schedule-service').value = train.name || '';
    });
    $('#assembler-train-select').addEventListener('change', (event) => { cancelSpeedDraft(); app.selectedTrainId = event.target.value; app.consistDraft = null; renderSidebar(); renderTrainList(); renderEditor(); renderAssembler(); });
    $('#add-car').addEventListener('click', addRollingStock);
    $('#add-locomotive').addEventListener('click', addLocomotiveToConsist);
    $('#assembler-locomotive-list').addEventListener('click', (event) => {
      const button = event.target.closest('[data-remove-locomotive]');
      if (button) removeLocomotiveFromConsist(button.dataset.removeLocomotive);
    });
    $('#save-consist').addEventListener('click', saveConsist);
    $('#remove-train').addEventListener('click', removeSelectedTrain);
    $('#close-editor').addEventListener('click', () => { $('#train-editor-panel').classList.toggle('is-collapsed'); showToast($('#train-editor-panel').classList.contains('is-collapsed') ? 'Train profile collapsed' : 'Train profile expanded', 'success'); });
  }

  function changeZoom(amount) {
    app.zoom = Math.max(.75, Math.min(1.35, app.zoom + amount));
    app.layoutViewportManual[app.layoutView === 'pinboard' ? 'pinboard' : 'graph'] = true;
    $('#layout-svg').style.transform = `scale(${app.zoom})`;
    $('#layout-zoom-label').textContent = `${Math.round(app.zoom * 100)}%`;
  }

  function applyDynamicStyles() {
    const style = document.createElement('style');
    style.textContent = '.is-collapsed .editor-tabs, .is-collapsed .editor-content { display: none; } .is-collapsed { min-height: 0 !important; } .empty-state { padding: 24px 18px; color: var(--faint); font-size: 10px; } #sync-ribbon[data-tone="warning"] .ribbon-icon { color: var(--yellow); } #sync-ribbon[data-tone="success"] .ribbon-icon { color: var(--green); } .systematic-legend { display: flex; justify-content: space-between; gap: 12px; padding: 0 18px 7px; color: var(--faint); font-size: 9px; } .systematic-legend b { color: var(--cyan); font-weight: 600; } .systematic-track { overflow-x: auto; } .systematic-block { flex: 1 1 0; min-width: 52px; padding: 0 5px; white-space: nowrap; } .systematic-block.is-selected { border-color: var(--blue-bright); box-shadow: 0 0 0 1px rgba(92,157,255,.25); color: var(--text); } .systematic-link { position: relative; z-index: 2; flex: 0 0 17px; color: var(--cyan); font-size: 12px; line-height: 1; text-align: center; } .systematic-link.is-gap { color: var(--faint); opacity: .65; } .systematic-status strong.is-occupied { color: var(--orange); } .systematic-status strong.is-route { color: var(--violet); } .rolling-stock-label { display: block; margin: 8px 18px 0; color: var(--faint); font-size: 9px; } .rolling-stock-select { width: calc(100% - 36px); min-height: 28px; margin: 4px 18px 0; padding: 0 8px; border: 1px solid var(--line); border-radius: 6px; background: #0d192a; color: var(--text); font-size: 10px; } #consist-list .consist-item { grid-template-columns: 25px minmax(0, 1fr) auto auto; } .consist-position { color: var(--faint); font-size: 9px; white-space: nowrap; } .consist-actions { display: inline-flex; gap: 3px; } .consist-actions .icon-button { width: 22px; height: 22px; font-size: 13px; } .consist-actions .icon-button:disabled { cursor: default; opacity: .3; }';
    style.textContent += ' .function-control-panel { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--line); } .function-control-panel .record-section-heading { padding: 0 0 8px; } .function-toggle-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; } .function-toggle { min-height: 48px; padding: 6px; border: 1px solid var(--line); border-radius: 7px; background: #0d192a; color: var(--text); text-align: left; cursor: pointer; } .function-toggle:hover { border-color: var(--blue-bright); } .function-toggle.is-on { border-color: var(--cyan); background: rgba(0, 198, 217, .13); box-shadow: inset 0 0 0 1px rgba(0, 198, 217, .16); } .function-toggle:disabled { opacity: .35; cursor: not-allowed; } .function-toggle strong, .function-toggle span, .function-toggle small { display: block; } .function-toggle strong { color: var(--cyan); font-size: 10px; } .function-toggle span { overflow: hidden; margin-top: 2px; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; } .function-toggle small { margin-top: 4px; color: var(--faint); font-size: 8px; letter-spacing: .08em; } .function-toggle.is-on small { color: var(--cyan); } .function-control-panel.is-compact { margin: 12px 18px 0; } .function-control-panel.is-compact .record-section-heading { display: block; } .function-control-panel.is-compact .settings-help { display: block; margin-top: 4px; }';
    style.textContent += ' .pinboard-layer { font-family: inherit; } .pinboard-rail-bed, .pinboard-rail { fill: none; stroke-linecap: round; } .pinboard-rail-bed { stroke: rgba(6,11,20,.92); stroke-width: 11; } .pinboard-rail { stroke: rgba(115,148,184,.68); stroke-width: 6; } .pinboard-rail.is-occupied { stroke: var(--orange); filter: drop-shadow(0 0 5px rgba(239,170,109,.48)); } .pinboard-rail.is-route { stroke: var(--violet); filter: drop-shadow(0 0 4px rgba(174,154,255,.4)); } .pinboard-rail.is-free { stroke: var(--cyan); opacity: .62; } .pinboard-rail:hover { stroke-width: 8; } .pinboard-section-label { fill: var(--text); font-size: 10px; font-weight: 700; text-anchor: middle; paint-order: stroke; stroke: #09111f; stroke-width: 4; stroke-linejoin: round; pointer-events: none; } .pinboard-node { cursor: pointer; } .pinboard-node circle { fill: #10233a; stroke: var(--blue-bright); stroke-width: 2; } .pinboard-node text { fill: var(--text); font-size: 11px; font-weight: 600; } .pinboard-node.is-selected circle { fill: var(--cyan); stroke: #fff; } .pinboard-node.is-selected text { fill: var(--cyan); } .pinboard-turnout { cursor: pointer; } .pinboard-switch-dot { fill: #0e1a2a; stroke: var(--cyan); stroke-width: 3; filter: drop-shadow(0 0 5px rgba(87,212,223,.45)); } .pinboard-turnout.is-diverging .pinboard-switch-dot { stroke: var(--orange); filter: drop-shadow(0 0 5px rgba(239,170,109,.48)); } .pinboard-switch-state { fill: var(--cyan); font-size: 12px; font-weight: 700; text-anchor: middle; pointer-events: none; } .pinboard-turnout.is-diverging .pinboard-switch-state { fill: var(--orange); } .pinboard-turnout.is-locked { opacity: .65; cursor: not-allowed; } .pinboard-turnout:focus .pinboard-switch-dot { stroke-width: 4; } .pinboard-train { cursor: grab; } .pinboard-train:hover .pinboard-vehicle { stroke: #fff; stroke-width: 2.5; filter: drop-shadow(0 0 5px var(--cyan)); } .pinboard-train:active { cursor: grabbing; } .pinboard-vehicle { stroke: #08111e; stroke-width: 1.5; fill: var(--orange); } .pinboard-vehicle.is-locomotive { fill: var(--cyan); } .pinboard-train.is-selected .pinboard-vehicle { stroke: #fff; stroke-width: 2; } .pinboard-train-label { fill: var(--text); font-size: 10px; font-weight: 700; paint-order: stroke; stroke: #09111f; stroke-width: 3; stroke-linejoin: round; pointer-events: none; } .calibration-form, .calibration-record { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; padding: 0 18px; } .calibration-record { grid-template-columns: 1fr 1.5fr auto; margin-top: 10px; align-items: end; } .calibration-form label, .calibration-record label { display: grid; gap: 4px; color: var(--faint); font-size: 9px; } .calibration-form input, .calibration-form select, .calibration-record input { min-width: 0; min-height: 30px; padding: 0 7px; border: 1px solid var(--line); border-radius: 6px; background: #0d192a; color: var(--text); font: inherit; } .calibration-panel > .settings-help, .calibration-panel > .settings-status { margin-left: 18px; margin-right: 18px; } .calibration-actions { padding: 0 18px; margin-top: 10px; } .calibration-history { margin: 12px 18px 0; border-top: 1px solid var(--line); padding-top: 8px; } .calibration-history > small { color: var(--faint); } .calibration-history > div { display: grid; grid-template-columns: 1fr auto auto; gap: 8px; padding-top: 5px; color: var(--faint); font-size: 9px; } .calibration-history strong { color: var(--cyan); }';
    style.textContent += ' .route-editor { padding: 0 18px 14px; border-bottom: 1px solid var(--line); } .route-editor .field-grid { padding: 0; } .route-editor .button-row { padding: 10px 0 0; } .route-panel .settings-status { margin: 9px 0 0; } .route-list { padding: 0 18px 12px; } .route-row { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 10px; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--line); } .route-row-main, .route-row-main strong, .route-row-main small { display: block; min-width: 0; } .route-row-main strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .route-row-main small, .route-row-meta { color: var(--faint); font-size: 9px; } .route-row-meta { white-space: nowrap; } .route-row-actions { display: inline-flex; gap: 4px; } .pinboard-spline-point { cursor: grab; } .pinboard-spline-point circle { fill: var(--violet); stroke: #fff; stroke-width: 1.5; } .pinboard-spline-point text { fill: var(--violet); font-size: 9px; font-weight: 700; paint-order: stroke; stroke: #09111f; stroke-width: 3; }';
    document.head.appendChild(style);
  }

  document.addEventListener('DOMContentLoaded', () => {
    // A file:// page cannot call /api/commands. Use the controller's origin
    // for the dashboard and API together, preserving the requested workspace.
    if (window.location.protocol === 'file:') {
      window.location.replace('http://127.0.0.1:8080/' + window.location.hash);
      return;
    }
    applyDynamicStyles();
    setupEvents();
    if (window.WorkspaceLayout) workspaceLayout = window.WorkspaceLayout.create({ root: document, request: fetchJson });
    document.addEventListener('workspace-layout-saved', (event) => { app.settings = event.detail; });
    window.requestAnimationFrame(animateTrainMarkers);
    renderSettings(); applyTheme(app.settings.theme);
    renderAll();
    const initialPage = window.location.hash.slice(1);
    if (['dispatch', 'layout', 'trains', 'timetable', 'scans', 'settings'].includes(initialPage)) navigateWorkspace(initialPage);
    bootstrap();
    schedulePolling();
  });
})();
