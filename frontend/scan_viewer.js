/*
 * Dependency-free photo-scan viewer.
 *
 * The preferred renderer is a small WebGL textured surface. A manifest may
 * optionally add normalized depth samples or mesh vertices, which are drawn
 * as a triangulated, perspective surface. A 2D canvas renderer remains
 * available for browsers without WebGL (or when shader setup fails).
 */
(function (global) {
  'use strict';

  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

  function normalizeAnchor(anchor, index) {
    if (!anchor || typeof anchor !== 'object') return null;
    const x = Number(anchor.x);
    const y = Number(anchor.y);
    return {
      ...anchor,
      id: anchor.id || anchor.anchorId || `anchor-${index + 1}`,
      x: Number.isFinite(x) ? clamp(x, 0, 1) : 0.5,
      y: Number.isFinite(y) ? clamp(y, 0, 1) : 0.5
    };
  }

  function anchorsFor(scan) {
    if (!scan) return [];
    const source = Array.isArray(scan.anchors) ? scan.anchors : (scan.anchor ? [scan.anchor] : []);
    return source.map(normalizeAnchor).filter(Boolean);
  }

  function depthMapSource(depthMap) {
    if (typeof depthMap === 'string') return depthMap;
    if (!depthMap || typeof depthMap !== 'object') return null;
    return depthMap.image || depthMap.url || depthMap.src || null;
  }

  function depthSettings(depthMap) {
    const settings = depthMap && typeof depthMap === 'object' ? depthMap : {};
    const scale = Number(settings.scale != null ? settings.scale : settings.depthScale);
    const offset = Number(settings.offset != null ? settings.offset : settings.depthOffset);
    return {
      scale: Number.isFinite(scale) ? scale : 0.9,
      offset: Number.isFinite(offset) ? offset : -0.45,
      invert: settings.invert === true
    };
  }

  function finiteArray(values) {
    return Array.isArray(values) ? values.map((value) => Number(value)).filter((value) => Number.isFinite(value)) : [];
  }

  function multiplyMat4(a, b) {
    const result = new Float32Array(16);
    for (let column = 0; column < 4; column += 1) {
      for (let row = 0; row < 4; row += 1) {
        result[column * 4 + row] =
          a[row] * b[column * 4] +
          a[4 + row] * b[column * 4 + 1] +
          a[8 + row] * b[column * 4 + 2] +
          a[12 + row] * b[column * 4 + 3];
      }
    }
    return result;
  }

  function perspectiveMat4(fieldOfView, aspect, near, far) {
    const f = 1 / Math.tan(fieldOfView / 2);
    const inverseRange = 1 / (near - far);
    const result = new Float32Array(16);
    result[0] = f / aspect;
    result[5] = f;
    result[10] = (far + near) * inverseRange;
    result[11] = -1;
    result[14] = 2 * far * near * inverseRange;
    return result;
  }

  function lookAtMat4(eye, center, up) {
    let zx = eye[0] - center[0];
    let zy = eye[1] - center[1];
    let zz = eye[2] - center[2];
    const zLength = Math.hypot(zx, zy, zz) || 1;
    zx /= zLength; zy /= zLength; zz /= zLength;

    let xx = up[1] * zz - up[2] * zy;
    let xy = up[2] * zx - up[0] * zz;
    let xz = up[0] * zy - up[1] * zx;
    const xLength = Math.hypot(xx, xy, xz) || 1;
    xx /= xLength; xy /= xLength; xz /= xLength;

    const yx = zy * xz - zz * xy;
    const yy = zz * xx - zx * xz;
    const yz = zx * xy - zy * xx;
    const result = new Float32Array(16);
    result[0] = xx; result[1] = yx; result[2] = zx;
    result[4] = xy; result[5] = yy; result[6] = zy;
    result[8] = xz; result[9] = yz; result[10] = zz;
    result[12] = -(xx * eye[0] + xy * eye[1] + xz * eye[2]);
    result[13] = -(yx * eye[0] + yy * eye[1] + yz * eye[2]);
    result[14] = -(zx * eye[0] + zy * eye[1] + zz * eye[2]);
    result[15] = 1;
    return result;
  }

  function projectPoint(matrix, x, y, z, width, height) {
    const clipX = matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12];
    const clipY = matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13];
    const clipW = matrix[3] * x + matrix[7] * y + matrix[11] * z + matrix[15];
    if (clipW <= 0) return null;
    const normalizedX = clipX / clipW;
    const normalizedY = clipY / clipW;
    return {
      x: (normalizedX * 0.5 + 0.5) * width,
      y: (1 - (normalizedY * 0.5 + 0.5)) * height,
      visible: normalizedX >= -1.15 && normalizedX <= 1.15 && normalizedY >= -1.15 && normalizedY <= 1.15
    };
  }

  class ScanViewer {
    constructor(host, options) {
      this.host = typeof host === 'string' ? global.document && global.document.querySelector(host) : host;
      this.options = options || {};
      this.manifest = Array.isArray(this.options.manifest) ? this.options.manifest.slice() : [];
      this.selectedId = this.manifest[0] && this.manifest[0].id;
      this.yaw = 0;
      this.pitch = 0.12;
      this.zoom = 1;
      this.panX = 0;
      this.panY = 0;
      this.dragging = false;
      this.lastPointer = null;
      this.imageCache = new Map();
      this.textureCache = new Map();
      this.depthFieldCache = new Map();
      this.projectedAnchors = [];
      this.currentSurface = null;
      this.renderer = null;
      this.force2d = Boolean(this.options.force2d);
      this._onResize = () => this.resize();
      this._onPointerDown = (event) => this.pointerDown(event);
      this._onPointerMove = (event) => this.pointerMove(event);
      this._onPointerUp = (event) => this.pointerUp(event);
      this._onWheel = (event) => this.wheel(event);
      this._onContextMenu = (event) => event.preventDefault();
      this._onWebglLost = (event) => {
        event.preventDefault();
        this.switchTo2D();
      };
      this.resizeObserver = global.ResizeObserver ? new global.ResizeObserver(() => this.resize()) : null;
      this.build();
    }

    build() {
      if (!this.host || !global.document || !global.document.createElement) return;
      this.removeCanvasListeners();
      if (this.gl) this.textureCache.forEach((texture) => { if (texture) this.gl.deleteTexture(texture); });
      this.textureCache.clear();
      this.gl = null;
      this.glProgram = null;
      this.glPositionBuffer = null;
      this.glUvBuffer = null;
      this.context = null;
      this.host.innerHTML = '';
      this.canvas = global.document.createElement('canvas');
      this.canvas.setAttribute('aria-label', 'Interactive photo-scan track viewer');
      this.canvas.style.touchAction = 'none';
      this.host.appendChild(this.canvas);

      let webglAttempted = false;
      if (!this.force2d) {
        try {
          const webgl = this.canvas.getContext('webgl', { alpha: false, antialias: true }) || this.canvas.getContext('experimental-webgl');
          if (webgl) {
            webglAttempted = true;
            this.initWebGL(webgl);
          }
        } catch (error) {
          this.glProgram = null;
        }
      }
      if (!this.glProgram) {
        // A canvas cannot switch from a failed WebGL context to 2D. Replace
        // it so shader/context failures still have a genuine 2D fallback.
        if (webglAttempted) {
          this.canvas.remove();
          this.canvas = global.document.createElement('canvas');
          this.canvas.setAttribute('aria-label', 'Interactive photo-scan track viewer');
          this.canvas.style.touchAction = 'none';
          this.host.appendChild(this.canvas);
        }
        this.context = this.canvas.getContext('2d');
        this.renderer = this.context ? '2d' : null;
      } else {
        this.renderer = 'webgl';
      }
      if (!this.renderer) {
        this.host.innerHTML = '<div class="scan-empty"><div><strong>Canvas is unavailable</strong>Use a browser with canvas support to view the photo scan.</div></div>';
        return;
      }

      this.buildOverlay();
      this.overlay.style.display = this.renderer === 'webgl' ? 'block' : 'none';
      this.canvas.addEventListener('pointerdown', this._onPointerDown);
      this.canvas.addEventListener('pointermove', this._onPointerMove);
      this.canvas.addEventListener('pointerup', this._onPointerUp);
      this.canvas.addEventListener('pointercancel', this._onPointerUp);
      this.canvas.addEventListener('wheel', this._onWheel, { passive: false });
      this.canvas.addEventListener('contextmenu', this._onContextMenu);
      if (this.renderer === 'webgl') this.canvas.addEventListener('webglcontextlost', this._onWebglLost);
      global.addEventListener('resize', this._onResize);
      if (this.resizeObserver) this.resizeObserver.observe(this.host);
      this.manifest.forEach((scan) => this.loadImage(scan));
      this.resize();
    }

    initWebGL(gl) {
      const vertexSource = `
        attribute vec3 aPosition;
        attribute vec2 aUv;
        uniform mat4 uMvp;
        varying vec2 vUv;
        void main() {
          gl_Position = uMvp * vec4(aPosition, 1.0);
          vUv = aUv;
        }
      `;
      const fragmentSource = `
        precision mediump float;
        uniform sampler2D uTexture;
        uniform bool uUseTexture;
        uniform vec4 uColor;
        varying vec2 vUv;
        void main() {
          gl_FragColor = uUseTexture ? texture2D(uTexture, vUv) : uColor;
        }
      `;
      const compile = (type, source) => {
        const shader = gl.createShader(type);
        gl.shaderSource(shader, source);
        gl.compileShader(shader);
        if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader) || 'WebGL shader compilation failed');
        return shader;
      };
      const program = gl.createProgram();
      gl.attachShader(program, compile(gl.VERTEX_SHADER, vertexSource));
      gl.attachShader(program, compile(gl.FRAGMENT_SHADER, fragmentSource));
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program) || 'WebGL program linking failed');

      this.gl = gl;
      this.glProgram = program;
      this.glPosition = gl.getAttribLocation(program, 'aPosition');
      this.glUv = gl.getAttribLocation(program, 'aUv');
      this.glMvp = gl.getUniformLocation(program, 'uMvp');
      this.glTexture = gl.getUniformLocation(program, 'uTexture');
      this.glUseTexture = gl.getUniformLocation(program, 'uUseTexture');
      this.glColor = gl.getUniformLocation(program, 'uColor');
      this.glPositionBuffer = gl.createBuffer();
      this.glUvBuffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, this.glPositionBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 0, 1, -1, 0, -1, 1, 0, 1, 1, 0]), gl.STATIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.glUvBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 1, 1, 1, 0, 0, 1, 0]), gl.STATIC_DRAW);
      gl.useProgram(program);
      gl.enableVertexAttribArray(this.glPosition);
      gl.enableVertexAttribArray(this.glUv);
      gl.enable(gl.DEPTH_TEST);
      gl.depthFunc(gl.LEQUAL);
    }

    buildOverlay() {
      this.overlay = global.document.createElement('div');
      this.overlay.className = 'scan-viewer-overlay';
      Object.assign(this.overlay.style, { position: 'absolute', inset: '0', pointerEvents: 'none', overflow: 'hidden' });
      this.anchorLayer = global.document.createElement('div');
      Object.assign(this.anchorLayer.style, { position: 'absolute', inset: '0', pointerEvents: 'none' });
      this.hud = global.document.createElement('div');
      Object.assign(this.hud.style, { position: 'absolute', top: '14px', left: '14px', maxWidth: '280px', padding: '10px 12px', color: '#edf5ff', background: 'rgba(4, 11, 21, .76)', font: '600 12px system-ui, sans-serif', pointerEvents: 'none' });
      this.hudTitle = global.document.createElement('div');
      this.hudMeta = global.document.createElement('div');
      Object.assign(this.hudMeta.style, { marginTop: '5px', color: '#9fb3cb', font: '10px system-ui, sans-serif' });
      this.hud.appendChild(this.hudTitle);
      this.hud.appendChild(this.hudMeta);
      this.message = global.document.createElement('div');
      Object.assign(this.message.style, { position: 'absolute', inset: '0', display: 'none', placeContent: 'center', padding: '30px', color: '#edf5ff', textAlign: 'center', font: '600 14px system-ui, sans-serif', pointerEvents: 'none' });
      this.overlay.appendChild(this.anchorLayer);
      this.overlay.appendChild(this.hud);
      this.overlay.appendChild(this.message);
      if (global.getComputedStyle && global.getComputedStyle(this.host).position === 'static') this.host.style.position = 'relative';
      this.host.appendChild(this.overlay);
    }

    setManifest(manifest) {
      if (!this.canvas || !this.host || !this.host.contains(this.canvas)) this.build();
      this.manifest = Array.isArray(manifest) ? manifest.slice() : [];
      if (!this.manifest.some((scan) => scan.id === this.selectedId)) this.selectedId = this.manifest[0] && this.manifest[0].id;
      const urls = new Set(this.manifest.reduce((all, scan) => {
        if (!scan) return all;
        if (scan.image) all.push(scan.image);
        const depthUrl = depthMapSource(scan.depthMap);
        if (depthUrl) all.push(depthUrl);
        return all;
      }, []));
      this.textureCache.forEach((texture, url) => {
        if (!urls.has(url)) {
          if (this.gl && texture) this.gl.deleteTexture(texture);
          this.textureCache.delete(url);
          this.imageCache.delete(url);
          this.depthFieldCache.delete(url);
        }
      });
      this.imageCache.forEach((image, url) => {
        if (!urls.has(url)) {
          this.imageCache.delete(url);
          this.depthFieldCache.delete(url);
        }
      });
      this.manifest.forEach((scan) => this.loadImage(scan));
      this.draw();
    }

    setSelected(id) {
      if (this.manifest.some((scan) => scan.id === id)) this.selectedId = id;
      this.draw();
    }

    selected() {
      return this.manifest.find((scan) => scan.id === this.selectedId) || null;
    }

    resize() {
      if (!this.canvas || !this.renderer) return;
      const rect = this.host.getBoundingClientRect();
      const ratio = Math.max(1, Math.min(2, global.devicePixelRatio || 1));
      this.width = Math.max(320, Math.round(rect.width || 640));
      this.height = Math.max(260, Math.round(rect.height || 360));
      this.canvas.width = this.width * ratio;
      this.canvas.height = this.height * ratio;
      this.canvas.style.width = `${this.width}px`;
      this.canvas.style.height = `${this.height}px`;
      if (this.renderer === '2d') this.context.setTransform(ratio, 0, 0, ratio, 0, 0);
      this.draw();
    }

    loadImage(scan) {
      if (!scan || !global.Image) return;
      this.loadImageUrl(scan.image, scan, false);
      const depthUrl = depthMapSource(scan.depthMap);
      this.loadImageUrl(depthUrl, scan, true);
    }

    loadImageUrl(url, scan, isDepth) {
      if (!url || this.imageCache.has(url) || !global.Image) return;
      // Mark the URL before starting the async request so redraws do not
      // create duplicate Image objects while the first request is pending.
      this.imageCache.set(url, null);
      const image = new global.Image();
      if (scan.crossOrigin !== false) image.crossOrigin = scan.crossOrigin || 'anonymous';
      image.onload = () => {
        this.imageCache.set(url, image);
        if (isDepth) this.depthFieldCache.delete(url);
        this.draw();
      };
      image.onerror = () => { this.imageCache.set(url, null); this.draw(); };
      image.src = url;
    }

    depthFieldFromImage(url, image, settings) {
      if (!image || !global.document || !global.document.createElement) return null;
      if (this.depthFieldCache.has(url)) return this.depthFieldCache.get(url);
      let field = null;
      try {
        const canvas = global.document.createElement('canvas');
        const sourceWidth = image.naturalWidth || image.width;
        const sourceHeight = image.naturalHeight || image.height;
        if (!sourceWidth || !sourceHeight) return null;
        const columns = Math.floor(clamp(Number(settings.samplesX) || Math.min(64, Math.max(2, sourceWidth)), 2, 64));
        const rows = Math.floor(clamp(Number(settings.samplesY) || Math.min(64, Math.max(2, sourceHeight)), 2, 64));
        canvas.width = columns;
        canvas.height = rows;
        const context = canvas.getContext('2d', { willReadFrequently: true });
        if (!context) return null;
        context.drawImage(image, 0, 0, columns, rows);
        const pixels = context.getImageData(0, 0, columns, rows).data;
        const values = new Array(columns * rows);
        for (let index = 0; index < values.length; index += 1) {
          const pixel = index * 4;
          let value = pixels[pixel] / 255;
          if (settings.invert) value = 1 - value;
          values[index] = value * settings.scale + settings.offset;
        }
        field = { columns, rows, values };
      } catch (error) {
        // A cross-origin depth image may not be readable by a canvas. Keep
        // the scan usable and let the caller render its flat surface.
        field = null;
      }
      this.depthFieldCache.set(url, field);
      return field;
    }

    resampleField(values, width, height) {
      const columns = Math.min(width, 64);
      const rows = Math.min(height, 64);
      const sampled = [];
      for (let row = 0; row < rows; row += 1) {
        const sourceRow = Math.min(height - 1, Math.round(row * (height - 1) / (rows - 1)));
        for (let column = 0; column < columns; column += 1) {
          const sourceColumn = Math.min(width - 1, Math.round(column * (width - 1) / (columns - 1)));
          sampled.push(values[sourceRow * width + sourceColumn] || 0);
        }
      }
      return { columns, rows, values: sampled };
    }

    depthFieldFromValues(depthMap, settings) {
      if (!depthMap || (typeof depthMap !== 'object' && typeof depthMap !== 'string')) return null;
      const width = Math.floor(Number(depthMap.width || depthMap.columns || depthMap.samplesX));
      const height = Math.floor(Number(depthMap.height || depthMap.rows || depthMap.samplesY));
      const source = Array.isArray(depthMap.data) ? depthMap.data : (Array.isArray(depthMap.values) ? depthMap.values : null);
      if (!Number.isFinite(width) || !Number.isFinite(height) || width < 2 || height < 2 || !source || source.length < width * height) return null;
      const values = finiteArray(source.slice(0, width * height));
      if (values.length !== width * height) return null;
      const maximum = values.reduce((current, value) => Math.max(current, Math.abs(value)), 0);
      const divisor = maximum > 1 ? 255 : 1;
      return this.resampleField(values.map((value) => ((settings.invert ? 1 - value / divisor : value / divisor) * settings.scale) + settings.offset), width, height);
    }

    fieldValue(field, x, y) {
      if (!field || !field.values || field.columns < 2 || field.rows < 2) return 0;
      const px = clamp(x, 0, 1) * (field.columns - 1);
      const py = clamp(y, 0, 1) * (field.rows - 1);
      const x0 = Math.floor(px); const y0 = Math.floor(py);
      const x1 = Math.min(field.columns - 1, x0 + 1); const y1 = Math.min(field.rows - 1, y0 + 1);
      const tx = px - x0; const ty = py - y0;
      const at = (column, row) => field.values[row * field.columns + column] || 0;
      return at(x0, y0) * (1 - tx) * (1 - ty) + at(x1, y0) * tx * (1 - ty) + at(x0, y1) * (1 - tx) * ty + at(x1, y1) * tx * ty;
    }

    meshField(scan) {
      const grid = scan && (scan.meshGrid || scan.mesh);
      if (!grid || typeof grid !== 'object') return null;
      if (Array.isArray(grid.vertices) && grid.vertices.length >= 4) return grid;
      const nested = Array.isArray(grid.depths) && Array.isArray(grid.depths[0]) ? grid.depths : (Array.isArray(grid.depth) && Array.isArray(grid.depth[0]) ? grid.depth : null);
      const source = nested ? nested.reduce((all, row) => all.concat(row), []) : (Array.isArray(grid.depths) ? grid.depths : grid.depth);
      const columns = Math.floor(Number(grid.columns || grid.cols || (nested && nested[0] && nested[0].length)));
      const rows = Math.floor(Number(grid.rows || (nested && nested.length)));
      if (!Number.isFinite(columns) || !Number.isFinite(rows) || columns < 2 || rows < 2 || !Array.isArray(source) || source.length < columns * rows) return null;
      const settings = depthSettings(grid);
      const values = finiteArray(source.slice(0, columns * rows));
      if (values.length !== columns * rows) return null;
      const maximum = values.reduce((current, value) => Math.max(current, Math.abs(value)), 0);
      const divisor = maximum > 1 ? 255 : 1;
      return this.resampleField(values.map((value) => ((settings.invert ? 1 - value / divisor : value / divisor) * settings.scale) + settings.offset), columns, rows);
    }

    depthField(scan) {
      if (!scan) return null;
      const mesh = this.meshField(scan);
      if (mesh) return mesh;
      const depthMap = scan.depthMap;
      if (!depthMap || (typeof depthMap !== 'object' && typeof depthMap !== 'string')) return null;
      const settings = depthSettings(depthMap);
      const inline = this.depthFieldFromValues(depthMap, settings);
      if (inline) return inline;
      const url = depthMapSource(depthMap);
      return url ? this.depthFieldFromImage(url, this.imageCache.get(url), settings) : null;
    }

    loadTexture(url, image) {
      if (!this.gl || !image || this.textureCache.has(url)) return this.textureCache.get(url) || null;
      try {
        const texture = this.gl.createTexture();
        this.gl.bindTexture(this.gl.TEXTURE_2D, texture);
        this.gl.pixelStorei(this.gl.UNPACK_FLIP_Y_WEBGL, true);
        this.gl.texParameteri(this.gl.TEXTURE_2D, this.gl.TEXTURE_MIN_FILTER, this.gl.LINEAR);
        this.gl.texParameteri(this.gl.TEXTURE_2D, this.gl.TEXTURE_MAG_FILTER, this.gl.LINEAR);
        this.gl.texParameteri(this.gl.TEXTURE_2D, this.gl.TEXTURE_WRAP_S, this.gl.CLAMP_TO_EDGE);
        this.gl.texParameteri(this.gl.TEXTURE_2D, this.gl.TEXTURE_WRAP_T, this.gl.CLAMP_TO_EDGE);
        this.gl.texImage2D(this.gl.TEXTURE_2D, 0, this.gl.RGBA, this.gl.RGBA, this.gl.UNSIGNED_BYTE, image);
        this.textureCache.set(url, texture);
        return texture;
      } catch (error) {
        this.textureCache.set(url, null);
        return null;
      }
    }

    draw() {
      if (!this.renderer || !this.width) return;
      if (this.renderer === 'webgl') this.drawWebGL();
      else this.draw2D();
    }

    surfaceGeometry(scan, image) {
      const aspect = image && image.width && image.height ? image.width / image.height : 16 / 9;
      const surfaceHeight = 3.4;
      const surfaceWidth = surfaceHeight * aspect;
      const grid = scan && (scan.meshGrid || scan.mesh);
      const field = this.depthField(scan);
      let sourceVertices = null;
      let sourceIndices = null;
      let depthAt = () => 0;

      if (grid && Array.isArray(grid.vertices) && grid.vertices.length >= 4) {
        const settings = grid && typeof grid === 'object' ? grid : {};
        const scaleValue = Number(settings.scale != null ? settings.scale : settings.depthScale);
        const offsetValue = Number(settings.offset != null ? settings.offset : settings.depthOffset);
        const scale = Number.isFinite(scaleValue) ? scaleValue : 1;
        const offset = Number.isFinite(offsetValue) ? offsetValue : 0;
        sourceVertices = grid.vertices.slice(0, 4096).map((vertex) => {
          const x = Number(vertex && (vertex.x != null ? vertex.x : vertex.u));
          const y = Number(vertex && (vertex.y != null ? vertex.y : vertex.v));
          const z = Number(vertex && vertex.z);
          if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return null;
          return { x: clamp(x, 0, 1), y: clamp(y, 0, 1), z: z * scale + offset, u: Number.isFinite(Number(vertex.u)) ? clamp(Number(vertex.u), 0, 1) : clamp(x, 0, 1), v: Number.isFinite(Number(vertex.v)) ? clamp(Number(vertex.v), 0, 1) : clamp(y, 0, 1) };
        });
        if (sourceVertices.some((vertex) => !vertex)) sourceVertices = null;
        sourceIndices = Array.isArray(grid.indices) ? grid.indices : (Array.isArray(grid.faces) ? grid.faces.reduce((all, face) => all.concat(face), []) : null);
        if (!sourceIndices && Number(grid.columns) >= 2 && Number(grid.rows) >= 2) {
          sourceIndices = this.gridIndices(Math.floor(Number(grid.columns)), Math.floor(Number(grid.rows)));
        }
        if (sourceVertices && sourceIndices) {
          depthAt = (x, y) => sourceVertices.reduce((best, vertex) => {
            const distance = Math.abs(vertex.x - x) + Math.abs(vertex.y - y);
            return distance < best.distance ? { distance, value: vertex.z } : best;
          }, { distance: Infinity, value: 0 }).value;
        }
      } else if (field) {
        const columns = Math.min(64, Math.max(2, Math.floor(Number(field.columns))));
        const rows = Math.min(64, Math.max(2, Math.floor(Number(field.rows))));
        if (field.values && field.values.length >= columns * rows) {
          sourceVertices = [];
          for (let row = 0; row < rows; row += 1) {
            for (let column = 0; column < columns; column += 1) {
              const x = column / (columns - 1);
              const y = row / (rows - 1);
              sourceVertices.push({ x, y, z: field.values[row * columns + column] || 0, u: x, v: y });
            }
          }
          sourceIndices = this.gridIndices(columns, rows);
          depthAt = (x, y) => this.fieldValue(field, x, y);
        }
      }

      if (!sourceVertices || !sourceIndices || sourceIndices.length < 3) {
        sourceVertices = [
          { x: 0, y: 1, z: 0, u: 0, v: 1 }, { x: 1, y: 1, z: 0, u: 1, v: 1 }, { x: 0, y: 0, z: 0, u: 0, v: 0 }, { x: 1, y: 0, z: 0, u: 1, v: 0 }
        ];
        sourceIndices = [0, 1, 2, 2, 1, 3];
        depthAt = () => 0;
      }

      const positions = [];
      const uvs = [];
      for (let index = 0; index + 2 < sourceIndices.length; index += 3) {
        const a = sourceVertices[Math.floor(Number(sourceIndices[index]))];
        const b = sourceVertices[Math.floor(Number(sourceIndices[index + 1]))];
        const c = sourceVertices[Math.floor(Number(sourceIndices[index + 2]))];
        if (!a || !b || !c) continue;
        [a, b, c].forEach((vertex) => {
          positions.push((vertex.x - 0.5) * surfaceWidth, (0.5 - vertex.y) * surfaceHeight, vertex.z);
          uvs.push(vertex.u, 1 - vertex.v);
        });
      }
      return { positions, uvs, count: positions.length / 3, depthAt, hasDepth: positions.some((value, index) => index % 3 === 2 && value !== 0) };
    }

    gridIndices(columns, rows) {
      const indices = [];
      const safeColumns = Math.min(64, Math.max(2, columns));
      const safeRows = Math.min(64, Math.max(2, rows));
      for (let row = 0; row < safeRows - 1; row += 1) {
        for (let column = 0; column < safeColumns - 1; column += 1) {
          const topLeft = row * safeColumns + column;
          const topRight = topLeft + 1;
          const bottomLeft = topLeft + safeColumns;
          const bottomRight = bottomLeft + 1;
          indices.push(topLeft, topRight, bottomLeft, bottomLeft, topRight, bottomRight);
        }
      }
      return indices;
    }

    drawWebGL() {
      const gl = this.gl;
      gl.viewport(0, 0, this.canvas.width, this.canvas.height);
      gl.clearColor(0.027, 0.067, 0.118, 1);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      const scan = this.selected();
      this.projectedAnchors = [];
      this.updateWebglMessage(scan);
      if (!scan) return;

      const image = scan.image && this.imageCache.get(scan.image);
      const texture = image ? this.loadTexture(scan.image, image) : null;
      const surface = this.surfaceGeometry(scan, image);
      this.currentSurface = surface;
      const aspect = image && image.width && image.height ? image.width / image.height : 16 / 9;
      const surfaceHeight = 3.4;
      const surfaceWidth = surfaceHeight * aspect;
      const distance = 5 / this.zoom;
      const eye = [this.panX + Math.sin(this.yaw) * distance, this.panY + Math.sin(this.pitch) * distance, Math.cos(this.yaw) * Math.cos(this.pitch) * distance];
      const view = lookAtMat4(eye, [this.panX, this.panY, 0], [0, 1, 0]);
      const projection = perspectiveMat4(Math.PI / 4, this.width / this.height, 0.1, 100);
      const mvp = multiplyMat4(projection, view);
      gl.useProgram(this.glProgram);
      gl.uniformMatrix4fv(this.glMvp, false, mvp);
      gl.uniform1i(this.glUseTexture, texture ? 1 : 0);
      gl.uniform4f(this.glColor, 0.10, 0.22, 0.34, 1);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.uniform1i(this.glTexture, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.glPositionBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(surface.positions), gl.STATIC_DRAW);
      gl.vertexAttribPointer(this.glPosition, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.glUvBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(surface.uvs), gl.STATIC_DRAW);
      gl.vertexAttribPointer(this.glUv, 2, gl.FLOAT, false, 0, 0);
      gl.drawArrays(gl.TRIANGLES, 0, surface.count);

      anchorsFor(scan).forEach((anchor) => {
        const x = (anchor.x - 0.5) * surfaceWidth + this.panX;
        const y = (0.5 - anchor.y) * surfaceHeight + this.panY;
        const point = projectPoint(mvp, x, y, surface.depthAt(anchor.x, anchor.y) + 0.02, this.width, this.height);
        if (point) this.projectedAnchors.push({ anchor, point });
      });
      this.renderAnchorButtons(scan);
      this.hud.style.display = 'block';
      this.hudTitle.textContent = scan.label || scan.id || 'Photo scan';
      const surfaceLabel = surface.hasDepth ? 'depth surface' : 'flat surface';
      this.hudMeta.textContent = `${this.renderer} · ${surfaceLabel} · orbit ${Math.round(this.yaw * 100)} · zoom ${this.zoom.toFixed(1)}× · shift-drag to pan`;
    }

    updateWebglMessage(scan) {
      if (!this.message) return;
      if (this.anchorLayer) this.anchorLayer.innerHTML = '';
      if (scan) {
        this.message.style.display = 'none';
        return;
      }
      this.hud.style.display = 'none';
      this.message.style.display = 'grid';
      this.message.textContent = 'No photo scans configured';
    }

    renderAnchorButtons() {
      if (!this.anchorLayer) return;
      this.anchorLayer.innerHTML = '';
      this.projectedAnchors.forEach(({ anchor, point }) => {
        if (!point.visible) return;
        const button = global.document.createElement('button');
        button.type = 'button';
        button.textContent = '●';
        button.title = anchor.label || anchor.id;
        button.setAttribute('aria-label', anchor.label || anchor.id);
        Object.assign(button.style, { position: 'absolute', left: `${point.x}px`, top: `${point.y}px`, transform: 'translate(-50%, -50%)', width: '22px', height: '22px', padding: '0', border: '0', borderRadius: '50%', color: '#6bd59e', background: 'rgba(4, 11, 21, .55)', font: '18px system-ui, sans-serif', lineHeight: '18px', cursor: 'pointer', pointerEvents: 'auto', textShadow: '0 0 10px #6bd59e' });
        button.addEventListener('pointerdown', (event) => event.stopPropagation());
        button.addEventListener('click', (event) => {
          event.stopPropagation();
          this.anchorClick(anchor, this.selected());
        });
        this.anchorLayer.appendChild(button);
      });
    }

    draw2D() {
      this.context.clearRect(0, 0, this.width, this.height);
      this.drawBackground();
      const scan = this.selected();
      if (!scan) {
        this.drawMessage('No photo scans configured', 'Add local scan images to the manifest.');
        return;
      }
      this.loadImage(scan);
      const image = scan.image && this.imageCache.get(scan.image);
      if (image) this.drawImageCover(image);
      this.drawScene();
      this.drawAnchors2D(scan, image);
      this.drawHud(scan);
    }

    drawBackground() {
      const gradient = this.context.createLinearGradient(0, 0, 0, this.height);
      gradient.addColorStop(0, '#122741');
      gradient.addColorStop(0.55, '#0c1b2c');
      gradient.addColorStop(1, '#07111e');
      this.context.fillStyle = gradient;
      this.context.fillRect(0, 0, this.width, this.height);
    }

    drawImageCover(image) {
      const scale = Math.max(this.width / image.width, this.height / image.height);
      const width = image.width * scale;
      const height = image.height * scale;
      this.context.save();
      this.context.globalAlpha = 0.28;
      this.context.drawImage(image, (this.width - width) / 2, (this.height - height) / 2, width, height);
      this.context.restore();
    }

    drawScene() {
      const ctx = this.context;
      const horizon = this.height * (0.36 + this.pitch * 0.12);
      const center = this.width / 2 + this.yaw * 90 + this.panX * 30;
      const floor = this.height * 0.92;
      ctx.save();
      ctx.globalAlpha = 0.55;
      ctx.strokeStyle = 'rgba(129, 168, 212, .2)';
      ctx.lineWidth = 1;
      for (let i = -8; i <= 8; i += 1) {
        const bottomX = center + i * 82 * this.zoom;
        ctx.beginPath(); ctx.moveTo(center + i * 8, horizon); ctx.lineTo(bottomX, floor); ctx.stroke();
      }
      for (let i = 0; i < 8; i += 1) {
        const t = i / 8;
        const y = horizon + Math.pow(t, 1.7) * (floor - horizon);
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(this.width, y); ctx.stroke();
      }
      const leftTop = center - 18 * this.zoom;
      const rightTop = center + 18 * this.zoom;
      const leftBottom = center - 150 * this.zoom;
      const rightBottom = center + 150 * this.zoom;
      ctx.globalAlpha = 0.95;
      ctx.strokeStyle = '#d5e7f6';
      ctx.lineWidth = 3;
      ctx.beginPath(); ctx.moveTo(leftTop, horizon); ctx.lineTo(leftBottom, floor); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(rightTop, horizon); ctx.lineTo(rightBottom, floor); ctx.stroke();
      ctx.strokeStyle = '#718ca9';
      ctx.lineWidth = 2;
      for (let i = 0; i < 10; i += 1) {
        const t = i / 10;
        const y = horizon + Math.pow(t, 1.65) * (floor - horizon);
        const left = leftTop + (leftBottom - leftTop) * Math.pow(t, 1.65);
        const right = rightTop + (rightBottom - rightTop) * Math.pow(t, 1.65);
        ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke();
      }
      ctx.restore();
    }

    drawAnchors2D(scan, image) {
      const anchors = anchorsFor(scan);
      const scale = image ? Math.max(this.width / image.width, this.height / image.height) : 1;
      const imageWidth = image ? image.width * scale : this.width;
      const imageHeight = image ? image.height * scale : this.height;
      const offsetX = image ? (this.width - imageWidth) / 2 : 0;
      const offsetY = image ? (this.height - imageHeight) / 2 : 0;
      this.projectedAnchors = anchors.map((anchor) => ({
        anchor,
        point: { x: offsetX + anchor.x * imageWidth, y: offsetY + anchor.y * imageHeight, visible: true }
      }));
      const ctx = this.context;
      this.projectedAnchors.forEach(({ point }) => {
        ctx.save();
        ctx.fillStyle = '#6bd59e';
        ctx.shadowColor = '#6bd59e';
        ctx.shadowBlur = 16;
        ctx.beginPath(); ctx.arc(point.x, point.y, 6, 0, Math.PI * 2); ctx.fill();
        ctx.restore();
      });
    }

    drawHud(scan) {
      const ctx = this.context;
      ctx.save();
      ctx.fillStyle = 'rgba(4, 11, 21, .68)';
      ctx.fillRect(14, 14, Math.min(280, this.width - 28), 54);
      ctx.fillStyle = '#edf5ff';
      ctx.font = '600 12px system-ui, sans-serif';
      ctx.fillText(scan.label || scan.id, 26, 36);
      ctx.fillStyle = '#9fb3cb';
      ctx.font = '10px system-ui, sans-serif';
      ctx.fillText(`2d fallback · orbit ${Math.round(this.yaw * 100)} · zoom ${this.zoom.toFixed(1)}× · shift-drag to pan`, 26, 54);
      ctx.restore();
    }

    drawMessage(title, detail) {
      const ctx = this.context;
      ctx.save(); ctx.textAlign = 'center'; ctx.fillStyle = '#edf5ff'; ctx.font = '600 14px system-ui, sans-serif';
      ctx.fillText(title, this.width / 2, this.height / 2 - 5); ctx.fillStyle = '#9fb3cb'; ctx.font = '10px system-ui, sans-serif';
      ctx.fillText(detail, this.width / 2, this.height / 2 + 16); ctx.restore();
    }

    pointerDown(event) {
      if (!this.canvas || event.button > 2) return;
      this.dragging = true;
      this.moved = false;
      this.interaction = event.button === 2 || event.shiftKey || event.altKey ? 'pan' : 'orbit';
      this.lastPointer = { x: event.clientX, y: event.clientY };
      if (this.canvas.setPointerCapture) this.canvas.setPointerCapture(event.pointerId);
    }

    pointerMove(event) {
      if (!this.dragging || !this.lastPointer) return;
      const dx = event.clientX - this.lastPointer.x;
      const dy = event.clientY - this.lastPointer.y;
      if (Math.abs(dx) + Math.abs(dy) > 2) this.moved = true;
      if (this.interaction === 'pan') {
        const scale = (5 / this.zoom) * 0.003;
        this.panX -= dx * scale;
        this.panY += dy * scale;
      } else {
        this.yaw += dx / 240;
        this.pitch = clamp(this.pitch + dy / 600, -0.8, 0.8);
      }
      this.lastPointer = { x: event.clientX, y: event.clientY };
      this.draw();
    }

    pointerUp(event) {
      if (this.dragging && !this.moved && event) {
        const rect = this.canvas.getBoundingClientRect();
        this.pickAnchor(event.clientX - rect.left, event.clientY - rect.top);
      }
      this.dragging = false;
      this.lastPointer = null;
      this.interaction = null;
    }

    pickAnchor(x, y) {
      const target = this.projectedAnchors.find(({ point }) => Math.hypot(point.x - x, point.y - y) <= 16);
      if (target) this.anchorClick(target.anchor, this.selected());
    }

    anchorClick(anchor, scan) {
      if (typeof this.options.onAnchorClick === 'function') this.options.onAnchorClick(anchor, scan);
      const targetId = anchor && anchor.scanId ? anchor.scanId : scan && scan.id;
      if (targetId && targetId !== this.selectedId) this.setSelected(targetId);
      if (targetId && typeof this.options.onSelect === 'function') this.options.onSelect(targetId, scan);
    }

    wheel(event) {
      event.preventDefault();
      this.zoom = clamp(this.zoom - event.deltaY / 1000, 0.7, 2.5);
      this.draw();
    }

    switchTo2D() {
      if (!this.host || this.renderer === '2d') return;
      this.renderer = null;
      this.glProgram = null;
      this.force2d = true;
      this.build();
    }

    removeCanvasListeners() {
      if (!this.canvas) return;
      this.canvas.removeEventListener('pointerdown', this._onPointerDown);
      this.canvas.removeEventListener('pointermove', this._onPointerMove);
      this.canvas.removeEventListener('pointerup', this._onPointerUp);
      this.canvas.removeEventListener('pointercancel', this._onPointerUp);
      this.canvas.removeEventListener('wheel', this._onWheel);
      this.canvas.removeEventListener('contextmenu', this._onContextMenu);
      this.canvas.removeEventListener('webglcontextlost', this._onWebglLost);
    }

    destroy() {
      this.removeCanvasListeners();
      global.removeEventListener('resize', this._onResize);
      if (this.resizeObserver) this.resizeObserver.disconnect();
      if (this.gl) this.textureCache.forEach((texture) => { if (texture) this.gl.deleteTexture(texture); });
      if (this.host) this.host.innerHTML = '';
    }
  }

  global.ScanViewer = ScanViewer;
  if (typeof module !== 'undefined' && module.exports) module.exports = { ScanViewer };
}(typeof window !== 'undefined' ? window : globalThis));
