# Photo-scan / 3D viewer

The frontend exposes a dependency-free `ScanViewer` module in
`frontend/scan_viewer.js`. It renders a scan image as a perspective WebGL
surface when WebGL is available, with orbit, zoom, pan, and clickable anchors.
When a scan supplies `depthMap` or `meshGrid`, the WebGL surface becomes a
triangulated perspective/depth surface instead of a single flat quad.
Browsers without WebGL or with failed shader initialization use a navigable 2D
canvas fallback automatically. If a particular image cannot be uploaded as a
texture, the WebGL surface remains available as an untextured planning surface.

## Manifest contract

The dashboard passes an array of scan objects to the viewer:

```json
[
  {
    "id": "west-yard-01",
    "label": "West yard overview",
    "description": "Photo scan from the west approach",
    "image": "/scans/west-yard-01.jpg",
    "anchor": { "x": 0.52, "y": 0.48 }
  }
]
```

Required fields are `id` and, for a textured surface, `image`. `label` and
`description` are optional display text. `image` is a browser-loadable URL,
including a controller-relative path or a browser-session object URL. The
legacy singular `anchor` field is supported and represents one point in image
coordinates. `x` and `y` are normalized values from `0` to `1`, measured from
the image's top-left corner; values outside that range are clamped.

For multiple points, use `anchors` instead of `anchor`:

```json
{
  "id": "west-yard-01",
  "image": "/scans/west-yard-01.jpg",
  "anchors": [
    { "id": "platform-1", "label": "Platform 1", "x": 0.32, "y": 0.61 },
    { "id": "signal-west", "label": "West signal", "x": 0.78, "y": 0.39 }
  ]
}
```

Depth is optional. A depth map can be a browser-loadable grayscale image; red
channel values are treated as normalized depth samples. `0` is the far side and
`1` is the near side by default. `scale` controls the world-space relief and
`offset` moves the surface along the camera-facing axis. `invert` reverses the
grayscale convention. The viewer samples at most a 64 × 64 grid and quietly
uses the flat surface if the depth image cannot be loaded or read.

```json
{
  "id": "west-yard-01",
  "image": "/scans/west-yard-01.jpg",
  "depthMap": {
    "image": "/scans/west-yard-01-depth.png",
    "scale": 0.9,
    "offset": -0.45,
    "invert": false
  }
}
```

For generated or already-decoded data, `depthMap` may instead contain a
JSON-safe row-major `data` or `values` array with `width` and `height` (at
least 2 × 2). Values may be normalized `0`–`1` or 8-bit `0`–`255` samples.

A mesh grid may be supplied directly with normalized image coordinates and
triangles. `z` is a displacement toward the viewer; `scale` and `offset` are
optional and default to `1` and `0` for explicit vertices:

```json
{
  "id": "west-yard-mesh",
  "image": "/scans/west-yard-01.jpg",
  "meshGrid": {
    "vertices": [
      { "x": 0, "y": 0, "z": 0 },
      { "x": 1, "y": 0, "z": 0.12 },
      { "x": 0, "y": 1, "z": 0.04 },
      { "x": 1, "y": 1, "z": 0.18 }
    ],
    "indices": [0, 1, 2, 2, 1, 3],
    "scale": 1,
    "offset": 0
  }
}
```

Regular grids can omit `vertices` and `indices` by providing `columns`,
`rows`, and a row-major `depth` or `depths` array. Their samples use the same
normalized depth convention as a depth map and can set `depthScale`,
`depthOffset`, and `invert`. A mesh grid takes precedence over `depthMap` if
both are present. Depth data never replaces the image: an absent image still
produces a colored 3D surface, while an absent or invalid depth source leaves
the existing flat WebGL surface intact.

Anchor buttons are rendered over the projected WebGL surface. Applications can
pass `onAnchorClick(anchor, scan)` in the viewer options to receive the
normalized anchor object and its containing scan. An anchor may also include
`scanId`; clicking it selects that scan and invokes the existing `onSelect(id)`
callback. Manifest data should remain JSON-safe: callbacks belong in viewer
options, not in the manifest.

## Controls and limitations

- Drag to orbit; the vertical orbit is clamped to keep the surface upright.
- Use the wheel to zoom. Shift-drag, Alt-drag, middle-drag, or right-drag to pan.
- Without depth data, the WebGL renderer is a single flat textured quad. With a
  valid depth map or mesh grid, it draws a triangulated displaced surface with
  real perspective and projects anchors onto their sampled surface depth. It
  does not reconstruct missing geometry, correct lens distortion, stitch
  images, or provide photogrammetry-grade occlusion. The 2D fallback remains
  the existing navigable image/canvas view.
- Cross-origin images must allow browser canvas/WebGL access with suitable CORS
  headers. If the image cannot load or be uploaded as a texture, a solid WebGL
  surface is shown and the 2D fallback remains available for unsupported
  browsers.
- `setManifest(manifest)`, `setSelected(id)`, and `selected()` are the public
  viewer methods used by `frontend/app.js`. `destroy()` removes listeners and
  releases WebGL textures.

The dashboard provides two ingestion paths: **Link scan** stores a URL or
controller-relative image path in the layout manifest, while **Use local photo**
creates a browser-session preview from an image file. Local previews are not
copied into the repository; link a stable asset path when a scan should survive
a reload or be shared with another controller instance.

The local controller serves `/scans/*` from `data/scans/` with path traversal
protection. Keep large or private media out of source control; the layout stores
the manifest reference, not the image bytes.
