# Supplied application logo

The user-supplied black/cyan train-and-node design is used in the application
header, favicon and Windows executable icons.

Assets: `frontend/assets/logo.png` (RGBA transparency) and
`frontend/assets/logo.ico` (multiple Windows icon sizes).

The built-in image editor could not access the attachment because its file helper
failed. The user explicitly approved local background removal instead.
`scripts/prepare_logo.py` removes the white background, recovers antialiasing on
neutral black edges, preserves cyan artwork, trims empty margins and creates icons.
It requires Pillow only when regenerating these committed assets.

Original editing instruction: “Remove only the white background to actual alpha
transparency, including white negative-space holes in the circular nodes. Preserve
the black branching track/node symbol, train illustration, pale cyan shapes and
fine cyan linework; no new elements, text or redesign.”
