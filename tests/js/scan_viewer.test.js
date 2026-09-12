// Run from the repository root: node --test tests/js/scan_viewer.test.js
// The host models a bordered, auto-height viewport so the old in-flow canvas
// enlarges it by two pixels on every ResizeObserver callback. No DOM package
// or GPU is required; actual rendering calls are recorded by small test doubles.
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../frontend/scan_viewer.js'), 'utf8');

function fixture(options = {}) {
  const canvases = [];
  const images = [];
  const observers = [];
  const calls = { frames: 0, transforms: [], deleted: [], glFrames: 0 };
  const listeners = new Map();
  let resourceId = 0;
  const gl = new Proxy({
    createProgram: () => ({ program: ++resourceId }),
    createShader: () => ({ shader: ++resourceId }),
    createBuffer: () => ({ buffer: ++resourceId }),
    createTexture: () => ({ texture: ++resourceId }),
    getShaderParameter: () => !options.shaderFailure,
    getShaderInfoLog: () => 'Test shader failure',
    getProgramParameter: () => true,
    getAttribLocation: () => 0,
    getUniformLocation: () => ({}),
    deleteShader: (value) => calls.deleted.push(value),
    deleteProgram: (value) => calls.deleted.push(value),
    deleteBuffer: (value) => calls.deleted.push(value),
    deleteTexture: (value) => calls.deleted.push(value),
    drawArrays: () => { calls.glFrames += 1; }
  }, { get: (target, property) => property in target ? target[property] : (String(property).toUpperCase() === property ? property : () => {}) });
  const context = new Proxy({
    clearRect: () => { calls.frames += 1; },
    setTransform: (...args) => calls.transforms.push(args),
    createLinearGradient: () => ({ addColorStop() {} })
  }, { get: (target, property) => property in target ? target[property] : () => {} });

  class Element {
    constructor(tag) {
      this.tagName = tag;
      this.style = {};
      this.children = [];
      this.listeners = new Map();
      this.parentNode = null;
    }
    setAttribute() {}
    appendChild(child) { this.children.push(child); child.parentNode = this; }
    remove() {
      if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
      this.parentNode = null;
    }
    contains(child) { return this === child || this.children.some((item) => item.contains(child)); }
    set innerHTML(value) { this.children.forEach((child) => { child.parentNode = null; }); this.children = []; this.html = value; }
    addEventListener(name, fn) {
      if (!this.listeners.has(name)) this.listeners.set(name, new Set());
      this.listeners.get(name).add(fn);
    }
    removeEventListener(name, fn) { this.listeners.get(name)?.delete(fn); }
  }
  class Canvas extends Element {
    constructor() { super('canvas'); this._width = 300; this._height = 150; this.writes = 0; }
    set width(value) { this.writes += 1; this._width = value; }
    get width() { return this._width; }
    set height(value) { this.writes += 1; this._height = value; }
    get height() { return this._height; }
    getContext(type) {
      if (type === '2d') return options.noCanvas ? null : context;
      return options.webgl ? gl : null;
    }
  }
  class Host extends Element {
    constructor() { super('div'); this.hidden = Boolean(options.hidden); this.viewportWidth = 638; this.viewportHeight = 360; }
    get clientWidth() { return this.hidden ? 0 : this.viewportWidth; }
    get clientHeight() {
      if (this.hidden) return 0;
      const canvas = this.children.find((child) => child.tagName === 'canvas' && child.style.position !== 'absolute');
      const contentHeight = canvas ? (parseFloat(canvas.style.height) || canvas.height) : 0;
      return Math.max(this.viewportHeight, contentHeight);
    }
    getBoundingClientRect() { return this.hidden ? { width: 0, height: 0 } : { width: this.clientWidth + 2, height: this.clientHeight + 2 }; }
  }
  const host = new Host();
  const window = {
    devicePixelRatio: options.ratio || 1,
    document: { createElement(tag) { const element = tag === 'canvas' ? new Canvas() : new Element(tag); if (tag === 'canvas') canvases.push(element); return element; } },
    getComputedStyle: (element) => ({ position: element.style.position || 'static' }),
    addEventListener(name, fn) { if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(fn); },
    removeEventListener(name, fn) { listeners.get(name)?.delete(fn); },
    ResizeObserver: class {
      constructor(callback) { this.callback = callback; this.targets = new Set(); observers.push(this); }
      observe(element) { this.targets.add(element); }
      disconnect() { this.targets.clear(); }
    },
    Image: class { constructor() { this.width = 100; this.height = 50; images.push(this); } }
  };
  vm.runInNewContext(source, { window });
  const manifest = options.manifest || [{ id: 'scan-1', label: 'Test scan' }];
  const viewer = new window.ScanViewer(host, { manifest });
  return { viewer, host, window, canvases, images, observers, calls, listeners, gl, manifest };
}

test('100 resize/manifest refreshes cannot enlarge a bordered host or reset the canvas', () => {
  const { viewer, host, canvases, calls, observers, manifest } = fixture();
  const canvas = viewer.canvas;
  const writes = canvas.writes;
  const frames = calls.frames;
  for (let i = 0; i < 100; i += 1) {
    observers[0].callback();
    viewer.setManifest(JSON.parse(JSON.stringify(manifest)));
    viewer.setSelected('scan-1');
    assert.equal(host.getBoundingClientRect().height, 362);
  }
  assert.equal(canvas.style.position, 'absolute');
  assert.equal(canvas.style.height, '100%');
  assert.equal(canvas.width, 638);
  assert.equal(canvas.height, 360);
  assert.equal(canvas.writes, writes);
  assert.equal(calls.frames, frames);
  assert.equal(canvases.length, 1);
});

test('hidden construction allocates no backing size and draws once when revealed', () => {
  const { viewer, host, calls, observers, manifest } = fixture({ hidden: true });
  assert.equal(viewer.canvas.writes, 0);
  assert.equal(calls.frames, 0);
  viewer.setManifest(manifest);
  assert.equal(calls.frames, 0);
  host.hidden = false;
  viewer.setManifest(manifest);
  assert.equal(viewer.canvas.height, 360);
  assert.equal(calls.frames, 1);
  observers[0].callback();
  assert.equal(calls.frames, 1);
  host.hidden = true;
  observers[0].callback();
  viewer.draw();
  assert.equal(calls.frames, 1);
  host.hidden = false;
  observers[0].callback();
  assert.equal(calls.frames, 2);
});

test('responsive and DPR changes update only backing pixels, including narrow viewports', () => {
  const { viewer, host, window, calls } = fixture();
  host.viewportWidth = 240;
  host.viewportHeight = 280;
  window.devicePixelRatio = 1.25;
  assert.equal(viewer.resize(), true);
  assert.equal(viewer.width, 240);
  assert.equal(viewer.height, 280);
  assert.equal(viewer.canvas.width, 300);
  assert.equal(viewer.canvas.height, 350);
  assert.deepEqual(calls.transforms.at(-1), [1.25, 0, 0, 1.25, 0, 0]);
  const writes = viewer.canvas.writes;
  assert.equal(viewer.resize(), false);
  assert.equal(viewer.canvas.writes, writes);
  window.devicePixelRatio = 3;
  viewer.resize();
  assert.equal(viewer.canvas.width, 480);
});

test('empty manifests keep one viewer and unavailable canvas does not retry every refresh', () => {
  const normal = fixture({ manifest: [] });
  for (let i = 0; i < 20; i += 1) normal.viewer.setManifest([]);
  assert.equal(normal.canvases.length, 1);
  assert.equal(normal.calls.frames, 1);
  const unavailable = fixture({ noCanvas: true, manifest: [] });
  for (let i = 0; i < 20; i += 1) unavailable.viewer.setManifest([]);
  assert.equal(unavailable.canvases.length, 1);
  assert.equal(unavailable.listeners.get('resize')?.size || 0, 0);
});

test('removed images and destroyed viewers ignore late async image completions', () => {
  const { viewer, images, manifest, calls, listeners, observers } = fixture({ manifest: [{ id: 'scan-1', image: '/scan.png' }] });
  const lateLoad = images[0].onload;
  for (let i = 0; i < 20; i += 1) viewer.setManifest(manifest);
  assert.equal(images.length, 1);
  viewer.setManifest([]);
  assert.equal(images[0].onload, null);
  lateLoad();
  assert.equal(viewer.imageCache.size, 0);
  viewer.setManifest(manifest);
  const afterDestroy = images[1].onload;
  viewer.destroy();
  const frames = calls.frames;
  afterDestroy();
  viewer.setManifest(manifest);
  viewer.resize();
  viewer.destroy();
  assert.equal(calls.frames, frames);
  assert.equal(viewer.pendingImages.size, 0);
  assert.equal(viewer.imageCache.size, 0);
  assert.equal(listeners.get('resize').size, 0);
  assert.equal(observers[0].targets.size, 0);
});

test('reattaching a viewer keeps a single observer/listener and cleans old canvas handlers', () => {
  const { viewer, host, listeners, observers, manifest } = fixture();
  const oldCanvas = viewer.canvas;
  host.innerHTML = 'External empty state';
  viewer.setManifest(manifest);
  assert.notEqual(viewer.canvas, oldCanvas);
  assert.equal(listeners.get('resize').size, 1);
  assert.equal(observers.length, 1);
  assert.equal(observers[0].targets.size, 1);
  assert.equal([...oldCanvas.listeners.values()].reduce((sum, set) => sum + set.size, 0), 0);
});

test('WebGL retains depth surfaces and context loss switches to a sized, usable 2D canvas', () => {
  const data = { id: 'scan-1', label: 'Depth scan', image: '/scan.png', depthMap: { width: 2, height: 2, values: [0, 0.2, 0.6, 1] } };
  const { viewer, images, calls, gl, listeners } = fixture({ webgl: true, manifest: [data] });
  assert.equal(viewer.renderer, 'webgl');
  images[0].onload();
  assert.equal(viewer.currentSurface.hasDepth, true);
  assert.equal(viewer.currentSurface.count, 6);
  const program = viewer.glProgram;
  const buffers = [viewer.glPositionBuffer, viewer.glUvBuffer];
  const texture = viewer.textureCache.get('/scan.png');
  const canvas = viewer.canvas;
  let prevented = false;
  viewer._onWebglLost({ preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(viewer.renderer, '2d');
  assert.notEqual(viewer.canvas, canvas);
  assert.equal(viewer.canvas.style.position, 'absolute');
  assert.equal(viewer.canvas.height, 360);
  assert.equal(calls.frames, 1);
  assert.equal(listeners.get('resize').size, 1);
  for (const resource of [program, ...buffers, texture]) assert.ok(calls.deleted.includes(resource));
  assert.equal(viewer.gl, null);
});

test('shader failure frees partial GL resources and uses a fresh fallback canvas', () => {
  const { viewer, canvases, calls } = fixture({ webgl: true, shaderFailure: true });
  assert.equal(viewer.renderer, '2d');
  assert.equal(canvases.length, 2);
  assert.equal(calls.frames, 1);
  assert.ok(calls.deleted.some((resource) => resource.shader));
  assert.ok(calls.deleted.some((resource) => resource.program));
});
