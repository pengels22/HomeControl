# Apartment model specification — 21-inch monitor

## Source and coordinate convention
Derived from the user's updated hand-drawn floor plan provided October 27, 2026. It is a **rough reference**, not a measured building plan. The arrow on the drawing indicates **north toward the left** when displayed in landscape orientation. The current SVG uses viewBox 1180 x 740 and keeps north pointing left.

## Physical floor plan (approximate)
- Upper-left of displayed drawing: Bedroom, with bed and side tables.
- Lower-left: Office, with work desk and office furnishing.
- Between these and the main living space: Bathroom and a hallway with closets/storage.
- Center/right upper side: Living room, open to dining/kitchen transition.
- Center/right lower side: Kitchen/dining with cabinetry, cooking counter, sink and fridge placeholders.
- Upper-right: Patio, outside the apartment envelope (dashed external boundary).
- Lower-right: Laundry.
- The apartment's entry and interior swing doors should be refined when more details are available; **do not invent exact openings**.
- The far-right **MEDIA / ALARM / ACTIVE TIMERS** rectangles in the hand sketch are dashboard UI, NOT apartment rooms.

## Modeling instructions
1. Treat geometry as editable data: stable room IDs, 2D polygon footprints, wall openings, floor heights and anchor points.
2. Build 3D wall heights and furniture as actual meshes (not SVG or simple perspective distortion). Deliver top-down and angled cameras with touch/click selection.
3. Model doors/windows using only grounded approximate positions, clearly mark unknown/undetermined placements in config.
4. Indicate true light fixture states from validated backend entities when integration is added. While disconnected, show explicit preview/unavailable status.
5. Keep model separate from HCM's 7-inch native PNL implementation. Do not connect directly from renderer to relay hardware.
6. Confirm measured Pi hardware model, GPU support and native screen resolution before selecting WebGL implementation. Provide low-detail settings or graceful fallback.
7. Validate room adjacency in view and inspect screenshots on target aspect ratio before live deployment.

## Current limitations
The branch's SVG has been corrected to the approximate placement above; it is still a **2D demo**, not a 3D room scene. The sketch's precise internal door locations, laundry orientation, window/entry boundaries, furnishings and dimensions require later refinement. Buttons remain preview-only.
