/*
 * H0 Control Desk
 * A dependency-free browser client. The API adapters are intentionally small so
 * the dashboard can be served by the local controller or opened with sample data.
 */
(function () {
  'use strict';

  const SAMPLE_STATE = {
    mode: 'manual',
    track_power: true,
    connection: { connected: false, simulated: true, label: 'Simulation fallback', detail: 'Local sample state' },
    feedback: { healthy: true, error: '', mapped_contacts: 0 },
    simulation: { running: true, rate: 1, clock: '10:42:16', date: 'Tuesday · 14 May' },
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

  // The assembler deliberately stays small and local: these entries are UI
  // templates, while the saved consist remains the source of truth.
  const ROLLING_STOCK_CATALOGUE = [
    { id: 'ns-186-001', type: 'locomotive', name: 'NS 186 001', detail: 'Traxx electric · 6,400 kW', length_mm: 216, mass_g: 86000 },
    { id: 'obb-1116-195', type: 'locomotive', name: 'ÖBB 1116 195', detail: 'Taurus electric · 6,400 kW', length_mm: 225, mass_g: 87000 },
    { id: 'i11-a-50-88', type: 'coach', name: 'I11 A 50 88', detail: '1st class · 26.4 m', length_mm: 264, mass_g: 44000 },
    { id: 'i11-b-50-88', type: 'coach', name: 'I11 B 50 88', detail: '2nd class · 26.4 m', length_mm: 264, mass_g: 42000 },
    { id: 'eanos-31-84', type: 'wagon', name: 'Eanos 31 84', detail: 'Open wagon · 22.5 t', length_mm: 156, mass_g: 22000 },
    { id: 'ns-sng-2316', type: 'multiple unit', name: 'NS SNG 2316', detail: '3-car electric multiple unit', length_mm: 594, mass_g: 132000 }
  ];

  const app = {
    state: clone(SAMPLE_STATE),
    trainDatabase: [],
    source: 'sample',
    selectedTrainId: 't1',
    selectedBlockId: 'b04',
    controlMode: 'manual',
    workspace: 'dispatch',
    layoutView: 'graph',
    editorTab: 'settings',
    simRate: 1,
    zoom: 1,
    filter: '',
    consistDraft: null,
    editingBlockId: null,
    editingScheduleId: null,
    editingTrainData: null,
    scanViewer: null,
    selectedScanId: 'sample-yard',
    scanObjectUrls: {},
    layoutEditing: false,
    nextBlockNumber: 13,
    layoutDrag: null,
    nextConsistItemNumber: 1,
    layoutAssetEditing: null
  };

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

  function mergePayload(payload) {
    const value = unwrap(payload);
    if (!value || typeof value !== 'object') return;
    if (value.layout) app.state.layout = { ...app.state.layout, ...value.layout };
    if (Array.isArray(value.blocks)) app.state.layout.blocks = value.blocks;
    if (Array.isArray(value.edges)) app.state.layout.edges = value.edges;
    if (Array.isArray(value.turnouts)) app.state.layout.turnouts = value.turnouts;
    if (Array.isArray(value.signals)) app.state.layout.signals = value.signals;
    if (Array.isArray(value.waypoints)) app.state.layout.waypoints = value.waypoints;
    if (Array.isArray(value.turntables)) app.state.layout.turntables = value.turntables;
    if (Array.isArray(value.stations)) app.state.layout.stations = value.stations;
    if (Array.isArray(value.platforms)) app.state.layout.platforms = value.platforms;
    if (Array.isArray(value.trains)) app.state.trains = value.trains;
    if (Array.isArray(value.trainDatabase)) mergeTrainDatabaseRecords(value.trainDatabase);
    if (Array.isArray(value.trains) && value.trains.length && value.trains[0] && value.trains[0].train_id) mergeTrainDatabaseRecords(value.trains);
    if (Array.isArray(value.schedules)) app.state.schedules = value.schedules;
    if (Array.isArray(value.scans)) app.state.scans = value.scans;
    if (typeof value.track_power === 'boolean') app.state.track_power = value.track_power;
    if (value.feedback) app.state.feedback = { ...app.state.feedback, ...value.feedback };
    if (value.simulation) app.state.simulation = { ...app.state.simulation, ...value.simulation };
    if (value.connection) app.state.connection = { ...app.state.connection, ...value.connection };
    if (value.mode) app.state.mode = value.mode;
  }

  function mergeTrainDatabaseRecords(records) {
    app.state.trainDatabase = Array.isArray(records) ? records : [];
    const byId = Object.fromEntries(app.state.trainDatabase.map((record) => [String(record.train_id), record]));
    app.state.trains = (app.state.trains || []).map((train) => {
      const match = byId[String(train.id)]
        || app.state.trainDatabase.find((record) => String(record.decoder_address || '') === String(train.number || ''));
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
    const timer = window.setTimeout(() => controller.abort(), 4200);
    try {
      const response = await fetch(endpoint, { ...options, signal: controller.signal, headers: { Accept: 'application/json', ...(options && options.headers) } });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      return await response.json();
    } finally {
      window.clearTimeout(timer);
    }
  }

  async function bootstrap() {
    const endpoints = ['/api/state', '/api/layout', '/api/trains', '/api/train-database'];
    const results = await Promise.allSettled(endpoints.map((endpoint) => fetchJson(endpoint)));
    let successCount = 0;
    results.forEach((result, index) => {
      if (result.status !== 'fulfilled') return;
      successCount += 1;
      if (index === 1) app.state.layout = { ...app.state.layout, ...unwrap(result.value) };
      else if (index === 2) app.state.trains = Array.isArray(result.value) ? result.value : (unwrap(result.value).trains || app.state.trains);
      else if (index === 3) mergeTrainDatabaseRecords(unwrap(result.value).trains || []);
      else mergePayload(result.value);
    });

    app.source = successCount ? 'api' : 'sample';
    if (successCount) {
      const simulated = Boolean(app.state.connection && (app.state.connection.simulated || app.state.connection.mode === 'simulation'));
      app.state.connection = simulated
        ? { ...app.state.connection, connected: false, simulated: true, label: 'Simulation API online', detail: `${successCount}/${endpoints.length} endpoints responding` }
        : { ...app.state.connection, connected: true, simulated: false, label: 'Z21 controller online', detail: `${successCount}/${endpoints.length} endpoints responding` };
    } else {
      app.state.connection = { connected: false, simulated: true, label: 'Simulation fallback', detail: 'Local sample state' };
    }
    renderAll();
    const simulated = Boolean(app.state.connection && app.state.connection.simulated);
    updateSync(successCount ? `${simulated ? 'Simulation API online' : 'Connected to controller'} · ${successCount}/${endpoints.length} endpoints responding` : 'API unavailable · running embedded sample state', successCount ? 'success' : 'warning');
  }

  async function pollController() {
    if (document.visibilityState === 'hidden') return;
    const results = await Promise.allSettled(['/api/connection', '/api/feedback'].map((endpoint) => fetchJson(endpoint)));
    const connectionResult = results[0];
    if (connectionResult && connectionResult.status === 'fulfilled') {
      const connection = unwrap(connectionResult.value) || {};
      const simulated = Boolean(connection.simulated || connection.mode === 'simulation');
      app.state.connection = { ...app.state.connection, ...connection, simulated, connected: simulated ? false : Boolean(connection.connected), label: simulated ? 'Simulation API online' : 'Z21 controller online', detail: simulated ? 'Live simulation status' : 'Live connection check' };
    }
    const feedbackResult = results[1];
    if (feedbackResult && feedbackResult.status === 'fulfilled') {
      const feedback = unwrap(feedbackResult.value) || {};
      if (typeof feedback.healthy === 'boolean' || feedback.error || feedback.mapped_contacts != null) {
        app.state.feedback = { ...app.state.feedback, ...feedback };
      }
      const occupancy = feedback.occupied_blocks || {};
      if (Object.keys(occupancy).length) {
        app.state.layout.blocks = (app.state.layout.blocks || []).map((block) => {
          const occupants = occupancy[block.id] || occupancy[String(block.id).toUpperCase()] || [];
          return occupants.length ? { ...block, status: 'occupied' } : block;
        });
      }
    }
    renderConnection();
    renderGraph();
    renderSystematicView();
    renderStats();
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
    renderSystematicView();
    renderScans();
    renderTrainList();
    renderEditor();
    renderSchedules();
    renderAssembler();
    renderStats();
    renderConnectionEditor();
    renderLayoutAssetInspector();
    updateWorkspaceVisibility();
  }

  function renderConnection() {
    const connection = app.state.connection || {};
    const dot = $('#connection-dot');
    dot.className = `status-dot ${connection.connected ? '' : connection.simulated ? 'is-simulated' : 'is-offline'}`;
    $('#connection-label').textContent = connection.label || (connection.connected ? 'Controller online' : 'Simulation fallback');
    $('#connection-detail').textContent = connection.detail || '';
    const feedback = app.state.feedback || {};
    const feedbackFailed = feedback.healthy === false;
    $('#feedback-health').textContent = feedbackFailed ? 'Unavailable' : connection.connected ? 'Live feedback' : 'Simulated';
    $('#checker-health').textContent = feedbackFailed ? 'Safe stop required' : connection.connected ? 'Verified' : 'Standby';
    $('#footer-source').textContent = feedbackFailed ? 'Feedback unavailable · safe stop' : connection.connected ? 'Z21 API connected' : connection.simulated ? 'Simulation API' : 'Embedded sample state';
    $('.footer-indicator').style.background = feedbackFailed ? 'var(--red)' : connection.connected ? 'var(--green)' : 'var(--yellow)';
  }

  function renderSidebar() {
    const train = selectedTrain();
    if (!train) return;
    $('#selected-train-name').textContent = train.name || `Train ${train.number || ''}`;
    $('#selected-train-badge').textContent = train.number || '—';
    $('#selected-train-origin').textContent = train.origin || 'Origin';
    $('#selected-train-destination').textContent = train.destination || 'Destination';
    $('#speed-readout').textContent = Math.round(Number(train.speed) || 0);
    $('#speed-slider').value = Math.round(Number(train.speed) || 0);
    $('#simulation-clock').textContent = app.state.simulation.clock || '00:00:00';
    $('#simulation-date').textContent = app.state.simulation.date || 'Simulation date';
    $('#simulation-rate').textContent = app.simRate === 1 ? 'Real time' : `${app.simRate}× accelerated`;
    $('#simulation-state').textContent = app.state.simulation.running ? 'RUNNING' : 'PAUSED';
    $('#simulation-toggle').textContent = app.state.simulation.running ? 'Pause' : 'Resume';
    $('#track-power-toggle').textContent = app.state.track_power === false ? 'Power on' : 'Power off';
    $('#simulation-rate-select').value = String(app.simRate);
    $$('.control-mode').forEach((button) => button.classList.toggle('is-active', button.dataset.controlMode === app.controlMode));
    $$('.mode-tab').forEach((button) => button.classList.toggle('is-active', button.dataset.workspace === app.workspace));
  }

  function blockCenter(block) {
    return { x: Number(block.x || 0) + Number(block.width || 100) / 2, y: Number(block.y || 0) + Number(block.height || 50) / 2 };
  }

  function edgePath(from, to) {
    const start = blockCenter(from); const end = blockCenter(to);
    if (Math.abs(start.y - end.y) < 8) return `M ${start.x} ${start.y} L ${end.x} ${end.y}`;
    const middleX = (start.x + end.x) / 2;
    return `M ${start.x} ${start.y} C ${middleX} ${start.y}, ${middleX} ${end.y}, ${end.x} ${end.y}`;
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

  function renderGraph() {
    const layout = app.state.layout;
    $('#layout-panel').classList.toggle('is-editing', app.layoutEditing);
    $('#toggle-layout-edit').textContent = app.layoutEditing ? 'Editing on' : 'Edit layout';
    const blocks = layout.blocks || [];
    const blockMap = Object.fromEntries(blocks.flatMap((block) => [[block.id, block], [String(block.id || '').toLowerCase(), block]]));
    const edges = normalizedEdges(layout, blocks);
    const edgeMarkup = edges.map((edge) => {
      const path = edgePath(blockMap[edge.from], blockMap[edge.to]);
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
        ${train ? `<text class="meta" x="${Number(block.x) + width - 31}" y="${Number(block.y) + 20}">#${escapeHtml(train.number)}</text>` : ''}
      </g>`;
    }).join('');
    const turnoutMarkup = (layout.turnouts || []).slice(0, 4).map((turnout, index) => {
      const block = blockMap[turnout.from] || blocks.find((item) => item.id === ['b11', 'b12', 'b07', 'b09'][index]);
      if (!block) return '';
      const center = blockCenter(block);
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
    $('#layout-svg').innerHTML = `<g class="graph-layer" style="transform-origin: 490px 175px;">${edgeMarkup}${nodeMarkup}${waypointMarkup}${turntableMarkup}${turnoutMarkup}${signalMarkup}</g>`;
    $$('[data-block-id]', $('#layout-svg')).forEach((node) => {
      node.addEventListener('click', () => selectBlock(node.dataset.blockId));
      node.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') selectBlock(node.dataset.blockId); });
      node.addEventListener('pointerdown', (event) => beginBlockDrag(event, node.dataset.blockId));
    });
    $$('[data-turnout-id]', $('#layout-svg')).forEach((node) => node.addEventListener('click', () => toggleTurnout(node.dataset.turnoutId)));
    $$('[data-signal-id]', $('#layout-svg')).forEach((node) => node.addEventListener('click', () => toggleSignal(node.dataset.signalId)));
    $$('[data-turntable-id]', $('#layout-svg')).forEach((node) => node.addEventListener('click', () => alignTurntable(node.dataset.turntableId)));
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
      host.innerHTML = '<div class="scan-empty"><div><strong>No photo scans configured</strong>Add entries to the scan manifest to anchor the 3D viewer to your layout.</div></div>';
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
    const trains = app.state.trains.filter((train) => !query || [train.name, train.number, train.position, train.status].join(' ').toLowerCase().includes(query));
    $('#train-list').innerHTML = trains.length ? trains.map((train) => `<button class="train-row ${train.id === app.selectedTrainId ? 'is-selected' : ''}" data-train-id="${escapeHtml(train.id)}"><span class="train-cell-main"><strong>${escapeHtml(train.name || `Train ${train.number}`)}</strong><small>${escapeHtml(train.class || 'Rolling stock')} · #${escapeHtml(train.number || '—')}</small></span><span class="train-position">${escapeHtml(train.position || '—')}</span><span class="train-status ${train.status === 'Delayed' ? 'warning' : ''}"><i class="signal-dot ${train.status === 'Delayed' ? 'yellow' : 'green'}"></i>${escapeHtml(train.status || 'Unknown')}</span><span class="train-speed">${Math.round(Number(train.speed) || 0)}<small> km/h</small></span></button>`).join('') : `<div class="empty-state">No trains match “${escapeHtml(app.filter)}”.</div>`;
    $$('.train-row', $('#train-list')).forEach((row) => row.addEventListener('click', () => selectTrain(row.dataset.trainId)));
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
    return `<div class="data-sheet"><div class="data-item"><span>Manufacturer / model</span><span>${escapeHtml([train.manufacturer, train.model_number].filter(Boolean).join(' · ') || '—')}</span></div><div class="data-item"><span>Era / scale</span><span>${escapeHtml(train.era || '—')} · H0</span></div><div class="data-item"><span>Decoder address / protocol</span><span>${escapeHtml(train.number || '—')} · ${escapeHtml(train.decoder_protocol || 'DCC')}</span></div><div class="data-item"><span>Train category</span><span>${escapeHtml(train.class || '—')}</span></div><div class="data-item"><span>Overall length / mass</span><span>${escapeHtml(train.length || '—')} m · ${escapeHtml(train.mass_g || '—')} g</span></div><div class="data-item"><span>Maximum speed</span><span>${escapeHtml(train.maxSpeed || '—')} km/h</span></div><div class="data-item"><span>Direction / block</span><span>${escapeHtml(train.direction || '—')} · ${escapeHtml(train.position || '—')}</span></div><div class="data-item"><span>Route target</span><span>${escapeHtml(train.destination_block_id || '—')}</span></div></div><div class="record-manager"><section class="record-section"><div class="record-section-heading"><div><p class="eyebrow">DECODER</p><h3>Function mappings <span>${decoderFunctions.length}</span></h3></div><button class="text-button" id="add-decoder-function">＋ Add</button></div><div class="record-list">${functionRows || '<div class="record-empty">No decoder functions mapped.</div>'}</div></section><section class="record-section"><div class="record-section-heading"><div><p class="eyebrow">SERVICE LOG</p><h3>Maintenance records <span>${maintenance.length}</span></h3></div><button class="text-button" id="add-maintenance">＋ Add</button></div><div class="record-list">${maintenanceRows || '<div class="record-empty">No maintenance records logged.</div>'}</div></section></div><div class="button-row catalogue-actions"><button class="button button-soft" id="export-train-catalogue">Export catalogue</button></div><p class="editor-note">Function mappings and service history are saved for the selected train profile.</p>`;
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

  function renderEditor() {
    const train = selectedTrain();
    const content = $('#editor-content');
    if (!train) { content.innerHTML = '<div class="empty-state">No train selected.</div>'; return; }
    if (app.editorTab === 'settings') {
      const blocks = app.state.layout.blocks || [];
      const selectedDestination = String(train.destination_block_id || (blocks[blocks.length - 1] && blocks[blocks.length - 1].id) || '').toUpperCase();
      const destinationOptions = blocks.map((block) => { const id = String(block.id || '').toUpperCase(); const selected = id === selectedDestination ? ' selected' : ''; return `<option value="${escapeHtml(id)}"${selected}>${escapeHtml(block.name || id)} · ${escapeHtml(id)}</option>`; }).join('');
      const mass = train.mass_g == null ? '' : train.mass_g;
      const lengthMm = train.length_mm == null ? Math.round((Number(train.length) || 0) * 1000) : train.length_mm;
      const controlMode = trainControlMode(train);
      const controlModeOptions = TRAIN_CONTROL_MODES.map((option) => `<option value="${option.value}"${option.value === controlMode ? ' selected' : ''}>${option.label}</option>`).join('');
      content.innerHTML = `<div class="field-grid"><div class="field"><label for="editor-name">Service name</label><input id="editor-name" value="${escapeHtml(train.name || '')}"></div><div class="field"><label for="editor-number">DCC address / service no.</label><input id="editor-number" inputmode="numeric" value="${escapeHtml(train.number || '')}"></div><div class="field"><label for="editor-origin">Origin</label><input id="editor-origin" value="${escapeHtml(train.origin || '')}"></div><div class="field"><label for="editor-destination">Destination</label><input id="editor-destination" value="${escapeHtml(train.destination || '')}"></div><div class="field"><label for="editor-destination-block">Destination block</label><select id="editor-destination-block">${destinationOptions || '<option value="">No blocks configured</option>'}</select></div><div class="field train-control-mode-field"><label for="editor-control-mode">Control mode</label><select id="editor-control-mode">${controlModeOptions}</select></div><div class="field"><label for="editor-manufacturer">Manufacturer</label><input id="editor-manufacturer" value="${escapeHtml(train.manufacturer || '')}"></div><div class="field"><label for="editor-model">Model / catalogue no.</label><input id="editor-model" value="${escapeHtml(train.model_number || '')}"></div><div class="field"><label for="editor-era">Railway era</label><input id="editor-era" value="${escapeHtml(train.era || '')}"></div><div class="field"><label for="editor-protocol">Decoder protocol</label><select id="editor-protocol"><option value="DCC"${String(train.decoder_protocol || 'DCC').toUpperCase() === 'DCC' ? ' selected' : ''}>DCC</option><option value="MM"${String(train.decoder_protocol || '').toUpperCase() === 'MM' ? ' selected' : ''}>Motorola</option><option value="SX"${String(train.decoder_protocol || '').toUpperCase() === 'SX' ? ' selected' : ''}>Selectrix</option></select></div><div class="field"><label for="editor-mass">Mass (g)</label><input id="editor-mass" type="number" min="0" step="1" value="${escapeHtml(mass)}"></div><div class="field"><label for="editor-length">Length (mm)</label><input id="editor-length" type="number" min="0" step="1" value="${escapeHtml(lengthMm)}"></div><div class="field"><label for="editor-max-speed">Maximum speed (km/h)</label><input id="editor-max-speed" type="number" min="0" step="1" value="${escapeHtml(train.maxSpeed || 140)}"></div></div><p class="editor-note">Changes are held in the dashboard until saved to the controller. The same profile can drive manual, automatic, and schedule simulation modes.</p><div class="button-row" style="padding: 12px 0 0"><button class="button button-primary" id="save-train-settings">Save profile</button><button class="button button-soft" id="route-selected">Plan route</button></div>`;
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
    $$('.editor-tab').forEach((button) => button.classList.toggle('is-active', button.dataset.editorTab === app.editorTab));
  }

  function renderSchedules() {
    $('#schedule-list').innerHTML = app.state.schedules.map((schedule) => `<div class="schedule-row"><span class="schedule-time">${escapeHtml(schedule.time || '—')}</span><span class="schedule-service"><strong>${escapeHtml(schedule.service || 'Service')}</strong><small>#${escapeHtml(schedule.number || '—')}</small></span><span class="schedule-route">${escapeHtml(schedule.route || '—')}</span><span class="platform-tag">${escapeHtml(schedule.platform || '—')}</span><span class="schedule-state ${schedule.state === 'Delayed' ? 'delayed' : ''}">${escapeHtml(schedule.state || 'Planned')}</span><button class="icon-button small schedule-menu" data-schedule-id="${escapeHtml(schedule.id)}" title="Edit service">⋯</button></div>`).join('');
    $$('.schedule-menu', $('#schedule-list')).forEach((button) => button.addEventListener('click', () => {
      const schedule = app.state.schedules.find((item) => item.id === button.dataset.scheduleId);
      if (!schedule) return;
      openScheduleEditor(schedule);
    }));
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
    $('#schedule-route').value = current.route || '';
    $('#schedule-state').value = current.state || 'Draft';
    const trains = (app.state.trains || []).map((train) => ({ value: train.id, label: `${train.name || `Train ${train.number || train.id}`} · #${train.number || '—'}` }));
    const linkedTrain = current.train_id || ((app.state.trains || []).find((train) => String(train.number || '') === String(current.number || '')) || {}).id || '';
    fillScheduleSelect($('#schedule-train'), trains, linkedTrain, 'No trains configured');
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
    const route = $('#schedule-route').value.trim() || [origin, destination].filter(Boolean).join('  →  ');
    const stationId = $('#schedule-station').value;
    const platformId = $('#schedule-platform').value;
    const arrivalSeconds = scheduleTimeSeconds($('#schedule-time').value);
    const fields = {
      time: $('#schedule-time').value || '00:00',
      service,
      number: $('#schedule-number').value.trim(),
      train_id: trainId || undefined,
      origin,
      destination,
      station_id: stationId || undefined,
      platform: platformId || '',
      route,
      stops: stationId ? [{ station_id: stationId, platform_id: platformId || null, arrival_seconds: arrivalSeconds, departure_seconds: arrivalSeconds + 60 }] : [],
      state: $('#schedule-state').value || 'Draft'
    };
    const id = app.editingScheduleId;
    if (id) {
      const schedule = app.state.schedules.find((item) => item.id === id);
      if (!schedule) return;
      Object.assign(schedule, fields);
      renderSchedules();
      $('#schedule-editor').close();
      await sendCommand({ type: 'update_schedule', schedule_id: id, schedule: fields });
      showToast(`${service} updated`, 'success');
    } else {
      const schedule = { id: `local-${Date.now()}`, ...fields };
      app.state.schedules.push(schedule);
      renderSchedules();
      $('#schedule-editor').close();
      await sendCommand({ type: 'add_schedule', schedule });
      showToast(`${service} added to dispatcher timetable`, 'success');
    }
    app.editingScheduleId = null;
  }

  function consistForTrain(train, createDraft) {
    if (!train) return [];
    if (app.consistDraft && app.consistDraft.trainId === train.id) return app.consistDraft.consist;
    const consist = clone(train.consist || []);
    if (createDraft) app.consistDraft = { trainId: train.id, consist };
    return consist;
  }

  function consistLengthMm(consist) {
    let unknownLength = false;
    const length = consist.reduce((total, item) => {
      const declared = Number(item.length_mm);
      if (Number.isFinite(declared) && declared > 0) return total + declared;
      const catalogueItem = ROLLING_STOCK_CATALOGUE.find((entry) => entry.id === item.catalogue_id || entry.name === item.name);
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
    const item = ROLLING_STOCK_CATALOGUE.find((entry) => entry.id === (catalogueSelect && catalogueSelect.value));
    if (!train || !item) {
      showToast('Choose a rolling-stock entry first.', 'warning');
      return;
    }
    const consist = consistForTrain(train, true);
    const instanceId = `${item.id}-${app.nextConsistItemNumber++}`;
    consist.push({ ...clone(item), id: instanceId, catalogue_id: item.id });
    renderAssembler();
    showToast(`${item.name} added to draft consist`, 'success');
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
    const lengthMm = consistLengthMm(train.consist);
    if (lengthMm != null) {
      train.length_mm = Math.round(lengthMm);
      train.length = Math.round(lengthMm) / 1000;
    }
    const savedConsist = clone(train.consist);
    app.consistDraft = null;
    renderAll();
    await sendCommand({ type: 'update_consist', train_id: train.id, consist: savedConsist });
  }

  function renderAssembler() {
    const select = $('#assembler-train-select');
    const catalogueSelect = $('#rolling-stock-select');
    if (!catalogueSelect) {
      $('#add-car').insertAdjacentHTML('beforebegin', '<label class="rolling-stock-label" for="rolling-stock-select">Add from catalogue</label><select id="rolling-stock-select" class="rolling-stock-select" aria-label="Rolling stock catalogue"></select>');
      $('#rolling-stock-select').addEventListener('change', (event) => { event.target.dataset.selected = event.target.value; });
    }
    const stockSelect = $('#rolling-stock-select');
    stockSelect.innerHTML = ROLLING_STOCK_CATALOGUE.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)} · ${escapeHtml(item.type)}</option>`).join('');
    const selectedCatalogueId = stockSelect.dataset.selected || ROLLING_STOCK_CATALOGUE[0].id;
    stockSelect.value = selectedCatalogueId;
    stockSelect.dataset.selected = stockSelect.value;
    select.innerHTML = app.state.trains.map((train) => `<option value="${escapeHtml(train.id)}">${escapeHtml(train.name || `Train ${train.number}`)} · #${escapeHtml(train.number || '—')}</option>`).join('');
    select.value = (app.consistDraft && app.consistDraft.trainId) || app.selectedTrainId;
    const train = app.state.trains.find((item) => item.id === select.value) || selectedTrain();
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
    $('#route-count').textContent = blocks.filter((block) => block.status === 'route').length;
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
    $('#systematic-panel').classList.toggle('is-hidden', app.layoutView !== 'systematic');
    $('#layout-panel').classList.toggle('is-hidden', app.layoutView === 'systematic');
    $('#scan-panel').classList.toggle('is-hidden', app.workspace !== 'scans');
    $$('.toolbar-tab').forEach((button) => button.classList.toggle('is-active', button.dataset.layoutView === app.layoutView));
    if (app.workspace === 'timetable') $('#timetable-panel').scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    if (app.workspace === 'scans') $('#scan-panel').scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  function selectTrain(id) {
    if (!app.state.trains.some((train) => train.id === id)) return;
    app.selectedTrainId = id;
    app.consistDraft = null;
    renderSidebar(); renderTrainList(); renderEditor(); renderAssembler();
    showToast(`${selectedTrain().name} selected`, 'success');
  }

  function selectBlock(id) {
    if (!app.state.layout.blocks.some((block) => block.id === id)) return;
    app.selectedBlockId = id;
    renderGraph(); renderSystematicView(); renderStats();
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
    block.name = $('#block-name').value.trim() || block.id;
    block.length_mm = Math.max(0, Number($('#block-length').value) || 0);
    block.station = $('#block-station').value.trim();
    renderAll();
    $('#block-editor').close();
    await sendCommand({ type: 'update_block', block_id: block.id, block: { name: block.name, length_mm: block.length_mm, station: block.station } });
    app.editingBlockId = null;
    showToast(`${block.name} updated`, 'success');
  }

  function addLayoutBlock() {
    const index = app.state.layout.blocks.length;
    const number = app.nextBlockNumber++;
    const id = `b${String(number).padStart(2, '0')}`;
    const block = {
      id,
      name: `NEW-${number}`,
      x: 62 + (index % 5) * 160,
      y: 224 + (Math.floor(index / 5) % 2) * 78,
      width: 126,
      height: 56,
      status: 'free',
      station: 'New section'
    };
    app.layoutEditing = true;
    app.state.layout.blocks.push(block);
    app.selectedBlockId = id;
    renderAll();
    sendCommand({ type: 'add_block', block });
    showToast(`${block.name} added to the layout editor`, 'success');
  }

  function svgPoint(event) {
    const svg = $('#layout-svg');
    const rect = svg.getBoundingClientRect();
    const viewBox = svg.viewBox.baseVal;
    return {
      x: (event.clientX - rect.left) * viewBox.width / rect.width,
      y: (event.clientY - rect.top) * viewBox.height / rect.height
    };
  }

  function beginBlockDrag(event, blockId) {
    if (!app.layoutEditing || event.button !== 0) return;
    const block = app.state.layout.blocks.find((item) => item.id === blockId);
    if (!block) return;
    const point = svgPoint(event);
    app.layoutDrag = { blockId, start: point, original: { x: Number(block.x) || 0, y: Number(block.y) || 0 } };
    event.preventDefault();
  }

  function moveBlockDrag(event) {
    if (!app.layoutDrag) return;
    const block = app.state.layout.blocks.find((item) => item.id === app.layoutDrag.blockId);
    if (!block) return;
    const point = svgPoint(event);
    block.x = Math.max(0, Math.min(840, Math.round(app.layoutDrag.original.x + point.x - app.layoutDrag.start.x)));
    block.y = Math.max(0, Math.min(290, Math.round(app.layoutDrag.original.y + point.y - app.layoutDrag.start.y)));
    renderGraph();
  }

  function endBlockDrag() {
    if (!app.layoutDrag) return;
    const block = app.state.layout.blocks.find((item) => item.id === app.layoutDrag.blockId);
    if (block) sendCommand({ type: 'move_block', block_id: block.id, x: block.x, y: block.y });
    app.layoutDrag = null;
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
    train.length = Math.round(train.length_mm) / 1000;
    train.maxSpeed = Number.isFinite(maxSpeed) && maxSpeed >= 0 ? maxSpeed : train.maxSpeed;
    renderAll();
    sendCommand({ type: 'update_train', train_id: train.id, train: { name: train.name, number: train.number, origin: train.origin, destination: train.destination, destination_block_id: train.destination_block_id, manufacturer: train.manufacturer, model_number: train.model_number, era: train.era, decoder_protocol: train.decoder_protocol, mass_g: train.mass_g, length_mm: train.length_mm, maxSpeed: train.maxSpeed } });
  }

  function setTrainMode(mode) {
    const train = selectedTrain();
    if (!train || !TRAIN_CONTROL_MODES.some((option) => option.value === mode)) return;
    train.mode = mode;
    if (mode === 'stopped') train.speed = 0;
    train.status = trainStatusForMode(train, mode);
    renderSidebar();
    renderTrainList();
    renderEditor();
    sendCommand({ type: 'set_train_mode', train_id: train.id, mode });
  }

  async function sendCommand(command) {
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
      app.state.connection = { connected: false, simulated: true, label: 'Simulation fallback', detail: 'Command staged locally' };
      updateSync('Controller unavailable · command staged locally', 'warning');
      renderConnection();
      showToast('Controller unavailable; change kept in local simulation.', 'warning');
      return null;
    }
  }

  function setSpeed(speed) {
    const train = selectedTrain();
    if (!train) return;
    train.speed = Math.max(0, Math.min(Number(train.maxSpeed || 140), Number(speed) || 0));
    renderSidebar(); renderTrainList();
    sendCommand({ type: 'set_speed', train_id: train.id, speed_kmh: train.speed });
  }

  function localTick() {
    const parts = String(app.state.simulation.clock || '00:00:00').split(':').map(Number);
    let seconds = (parts[0] * 3600) + (parts[1] * 60) + parts[2] + (60 * app.simRate);
    seconds %= 86400;
    const hours = String(Math.floor(seconds / 3600)).padStart(2, '0');
    const minutes = String(Math.floor((seconds % 3600) / 60)).padStart(2, '0');
    const remainder = String(seconds % 60).padStart(2, '0');
    app.state.simulation.clock = `${hours}:${minutes}:${remainder}`;
    app.state.schedules.slice(0, 1).forEach((schedule) => { if (schedule.state === 'Boarding') schedule.state = 'Departing'; });
    renderSidebar(); renderSchedules();
  }

  async function tickSimulation() {
    try {
      const response = await fetchJson('/api/simulation/tick', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ seconds: 60, rate: app.simRate }) });
      mergePayload(response);
      app.source = 'api';
      const simulated = Boolean(app.state.connection && (app.state.connection.simulated || app.state.connection.mode === 'simulation'));
      app.state.connection = { ...app.state.connection, connected: !simulated, simulated, label: simulated ? 'Simulation API online' : 'Z21 controller online', detail: 'Simulation tick acknowledged' };
      updateSync('Simulation tick acknowledged by controller', 'success');
      renderAll();
    } catch (error) {
      localTick();
      updateSync('Simulation tick applied locally', 'warning');
      showToast('Simulation advanced locally; API is unavailable.', 'warning');
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
      const response = await fetchJson('/api/layouts/default');
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

  function useLocalScan(event) {
    const file = event.target.files && event.target.files[0];
    event.target.value = '';
    if (!file || !file.type.startsWith('image/')) {
      showToast('Choose an image file for the photo-scan viewer.', 'warning');
      return;
    }
    const id = `local-scan-${Date.now()}`;
    const image = URL.createObjectURL(file);
    app.scanObjectUrls[id] = image;
    app.state.scans.push({ id, label: file.name, description: 'Local browser preview · not yet persisted', image, anchor: { x: 0.5, y: 0.48 } });
    app.selectedScanId = id;
    renderScans();
    showToast('Local photo scan loaded for this browser session.', 'success');
  }

  async function toggleTurnout(id) {
    const turnout = (app.state.layout.turnouts || []).find((item) => item.id === id);
    if (!turnout) return;
    turnout.state = turnout.state === 'straight' ? 'diverging' : 'straight';
    renderGraph();
    await sendCommand({ type: 'set_turnout', turnout_id: id, state: turnout.state });
  }

  async function toggleTrackPower() {
    const enabled = app.state.track_power === false;
    const previous = app.state.track_power;
    app.state.track_power = enabled;
    renderSidebar();
    const response = await sendCommand({ type: 'track_power', enabled });
    if (!response) {
      app.state.track_power = previous;
      renderSidebar();
    }
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
    $$('.mode-tab').forEach((button) => button.addEventListener('click', () => { app.workspace = button.dataset.workspace; renderSidebar(); updateWorkspaceVisibility(); if (app.workspace === 'layout') $('#layout-panel').scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }));
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
    $('#toggle-layout-edit').addEventListener('click', () => { app.layoutEditing = !app.layoutEditing; renderGraph(); showToast(app.layoutEditing ? 'Layout editor enabled' : 'Layout editor locked', app.layoutEditing ? 'success' : 'warning'); });
    $('#add-layout-block').addEventListener('click', addLayoutBlock);
    $('#edit-selected-block').addEventListener('click', () => openBlockEditor());
    $('#block-editor-form').addEventListener('submit', saveBlockEditor);
    $('#cancel-block-editor').addEventListener('click', () => { app.editingBlockId = null; $('#block-editor').close(); });
    $('#close-block-editor').addEventListener('click', () => { app.editingBlockId = null; $('#block-editor').close(); });
    $('#connect-blocks').addEventListener('click', () => editConnection('connect_blocks'));
    $('#disconnect-blocks').addEventListener('click', () => editConnection('disconnect_blocks'));
    $('#save-layout').addEventListener('click', saveLayout);
    $('#load-layout').addEventListener('click', loadSavedLayout);
    $('#layout-svg').addEventListener('pointermove', moveBlockDrag);
    $('#layout-svg').addEventListener('pointerup', endBlockDrag);
    $('#layout-svg').addEventListener('pointerleave', endBlockDrag);
    $$('.control-mode').forEach((button) => button.addEventListener('click', () => {
      app.controlMode = button.dataset.controlMode;
      app.state.mode = app.controlMode;
      renderSidebar();
      sendCommand({ type: 'set_mode', mode: app.controlMode === 'safe' ? 'stopped' : app.controlMode });
    }));
    $$('.toolbar-tab').forEach((button) => button.addEventListener('click', () => { app.layoutView = button.dataset.layoutView; updateWorkspaceVisibility(); }));
    $$('.editor-tab').forEach((button) => button.addEventListener('click', () => { app.editorTab = button.dataset.editorTab; renderEditor(); }));
    $('#speed-slider').addEventListener('input', (event) => { $('#speed-readout').textContent = event.target.value; });
    $('#apply-speed').addEventListener('click', () => setSpeed($('#speed-slider').value));
    $('#stop-train').addEventListener('click', () => setSpeed(0));
    $('#simulation-toggle').addEventListener('click', () => { app.state.simulation.running = !app.state.simulation.running; renderSidebar(); sendCommand({ type: app.state.simulation.running ? 'resume_simulation' : 'pause_simulation' }); });
    $('#simulation-tick').addEventListener('click', tickSimulation);
    $('#track-power-toggle').addEventListener('click', toggleTrackPower);
    $('#simulation-rate-select').addEventListener('change', (event) => { app.simRate = Number(event.target.value) || 1; renderSidebar(); showToast(`Simulation rate set to ${app.simRate}×`, 'success'); });
    $('#refresh-button').addEventListener('click', () => { showToast('Refreshing controller state…', 'success'); bootstrap(); });
    $('#train-search').addEventListener('input', (event) => { app.filter = event.target.value; renderTrainList(); });
    $('#fit-layout').addEventListener('click', () => { app.zoom = 1; $('#layout-svg').style.transform = 'scale(1)'; $('#layout-zoom-label').textContent = '100%'; showToast('Layout fitted to workspace', 'success'); });
    $('#layout-zoom-in').addEventListener('click', () => changeZoom(.1));
    $('#layout-zoom-out').addEventListener('click', () => changeZoom(-.1));
    $('#open-settings').addEventListener('click', () => { app.editorTab = 'settings'; renderEditor(); $('#train-editor-panel').scrollIntoView({ block: 'nearest', behavior: 'smooth' }); });
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
    $('#simulate-schedule').addEventListener('click', simulateNextScheduleEvent);
    $('#schedule-editor-form').addEventListener('submit', saveScheduleEditor);
    $('#cancel-schedule-editor').addEventListener('click', () => { app.editingScheduleId = null; $('#schedule-editor').close(); });
    $('#close-schedule-editor').addEventListener('click', () => { app.editingScheduleId = null; $('#schedule-editor').close(); });
    $('#train-data-editor-form').addEventListener('submit', saveTrainDataEditor);
    $('#cancel-train-data-editor').addEventListener('click', closeTrainDataEditor);
    $('#close-train-data-editor').addEventListener('click', closeTrainDataEditor);
    $('#schedule-train').addEventListener('change', (event) => {
      const train = app.state.trains.find((item) => item.id === event.target.value);
      if (!train) return;
      if (!$('#schedule-number').value) $('#schedule-number').value = train.number || '';
      if (!$('#schedule-service').value || $('#schedule-service').value === 'New service') $('#schedule-service').value = train.name || '';
    });
    $('#assembler-train-select').addEventListener('change', (event) => { app.selectedTrainId = event.target.value; app.consistDraft = null; renderSidebar(); renderTrainList(); renderEditor(); renderAssembler(); });
    $('#add-car').addEventListener('click', addRollingStock);
    $('#save-consist').addEventListener('click', saveConsist);
    $('#close-editor').addEventListener('click', () => { $('#train-editor-panel').classList.toggle('is-collapsed'); showToast($('#train-editor-panel').classList.contains('is-collapsed') ? 'Train profile collapsed' : 'Train profile expanded', 'success'); });
  }

  function changeZoom(amount) {
    app.zoom = Math.max(.75, Math.min(1.35, app.zoom + amount));
    $('#layout-svg').style.transform = `scale(${app.zoom})`;
    $('#layout-zoom-label').textContent = `${Math.round(app.zoom * 100)}%`;
  }

  function applyDynamicStyles() {
    const style = document.createElement('style');
    style.textContent = '.is-collapsed .editor-tabs, .is-collapsed .editor-content { display: none; } .is-collapsed { min-height: 0 !important; } .empty-state { padding: 24px 18px; color: var(--faint); font-size: 10px; } #sync-ribbon[data-tone="warning"] .ribbon-icon { color: var(--yellow); } #sync-ribbon[data-tone="success"] .ribbon-icon { color: var(--green); } .systematic-legend { display: flex; justify-content: space-between; gap: 12px; padding: 0 18px 7px; color: var(--faint); font-size: 9px; } .systematic-legend b { color: var(--cyan); font-weight: 600; } .systematic-track { overflow-x: auto; } .systematic-block { flex: 1 1 0; min-width: 52px; padding: 0 5px; white-space: nowrap; } .systematic-block.is-selected { border-color: var(--blue-bright); box-shadow: 0 0 0 1px rgba(92,157,255,.25); color: var(--text); } .systematic-link { position: relative; z-index: 2; flex: 0 0 17px; color: var(--cyan); font-size: 12px; line-height: 1; text-align: center; } .systematic-link.is-gap { color: var(--faint); opacity: .65; } .systematic-status strong.is-occupied { color: var(--orange); } .systematic-status strong.is-route { color: var(--violet); } .rolling-stock-label { display: block; margin: 8px 18px 0; color: var(--faint); font-size: 9px; } .rolling-stock-select { width: calc(100% - 36px); min-height: 28px; margin: 4px 18px 0; padding: 0 8px; border: 1px solid var(--line); border-radius: 6px; background: #0d192a; color: var(--text); font-size: 10px; } #consist-list .consist-item { grid-template-columns: 25px minmax(0, 1fr) auto auto; } .consist-position { color: var(--faint); font-size: 9px; white-space: nowrap; } .consist-actions { display: inline-flex; gap: 3px; } .consist-actions .icon-button { width: 22px; height: 22px; font-size: 13px; } .consist-actions .icon-button:disabled { cursor: default; opacity: .3; }';
    document.head.appendChild(style);
  }

  document.addEventListener('DOMContentLoaded', () => {
    applyDynamicStyles();
    setupEvents();
    renderAll();
    bootstrap();
    window.setInterval(pollController, 5000);
  });
})();
