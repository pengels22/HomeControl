# Architectural background validation

The supplied `HomeControl_Architectural_Sources.zip` was inspected on 2026-10-28.

## Source hierarchy

- `2160 Sandy Shore.ifc` is the primary geometric reference.
- `2160 Sandy Shore.dxf` is retained for 2D cross-checking.
- `2160 Sandy Shore.vwx` and the supplied Vectorworks screenshot are orientation references.
- `2160_Sandy_Shore_3D_model.glb` and `2160_Sandy_Shore_3D_isometric.png` are the supplied preliminary 3D assets.

## IFC checks

The IFC is ASCII IFC4 exported by Vectorworks and contains 26 wall elements (9 `IfcWall` plus 17 `IfcWallStandardCase`), 9 doors, and 10 opening elements. It contains no `IfcSpace` entities, so room volumes cannot be extracted directly from IFC space objects.

The wall extrusions include `2438.4 mm` (8 ft) geometry. The IFC also contains `1219.2 mm` (4 ft) geometry consistent with the kitchen pony-wall requirement. Door entities report a height of `2051 mm`; this is close to, but not exactly, the requested 80 in / `2032 mm`, so the source IFC value is preserved and not silently changed.

## Dashboard integration

The original approved 2D trace remains unchanged as an archival asset. The active dashboard background now uses the supplied DXF-derived 2D plan image, with a separate SVG hit layer and light-effect layer in the supplied `870 × 584` image coordinate space. The preliminary 3D render and its experimental projection are retained but are not exposed in the live kiosk.

The Raspberry Pi serves the DXF-derived 2D image as a static kiosk background. The GLB is retained for a future corrected 3D implementation; it is not used as the active view.

The supplied GLB contains wall extrusion meshes only and no furniture/material scene. The live 3D mode now uses the user-supplied desktop screenshot directly (`apartment-3d-user.png`) rather than the failed preliminary GLB render. The older derived variants remain retained for reference.

## Validation limitation

Because the IFC contains no room-space entities and no Blender/IFC geometry engine is installed in the build environment, the projected 3D room polygons are an initial camera-space overlay derived from the supplied render and cross-checked against the DXF/Vectorworks orientation. They should receive a final touchscreen visual QA pass before being treated as survey-grade geometry.
