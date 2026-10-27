# Apartment model specification — 21-inch monitor

## Source and coordinate convention
Derived from the user's updated hand-drawn floor plan provided October 27, 2026. It is a **rough reference**, not a measured building plan. The arrow on the drawing indicates **north toward the left** when displayed in landscape orientation. The static furnished asset uses viewBox 1200 x 760 and keeps north pointing left.

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
1. Treat geometry as editable data: stable room IDs, 2D polygon footprints and lighting-zone anchors in `static_apartment_config.js`.
2. Use the local furnished `apartment_render.svg` as the fixed overhead/isometric-style rendering. Keep room hit polygons and light masks in the separate configuration/overlay layer.
3. Model doors/windows using only grounded approximate positions, clearly mark unknown/undetermined placements in config.
4. Indicate true light fixture states from validated backend entities when integration is added. While disconnected, show explicit preview/unavailable status.
5. Keep model separate from HCM's 7-inch native PNL implementation. Do not connect directly from renderer to relay hardware.
6. Keep the display path dependency-free and raster/SVG based so it remains smooth on the Raspberry Pi 2B without WebGL.
7. Validate room adjacency in view and inspect screenshots on target aspect ratio before live deployment.

## Current limitations and assumptions
The supplied sketch is approximate, so internal door openings, window/entry boundaries, laundry orientation, furnishings and dimensions are represented as editable assumptions rather than a measured survey. The static asset preserves the documented room arrangement and keeps the patio outside the apartment envelope. Backend lighting is not authenticated on this branch; controls therefore show preview state and never send Home Assistant commands.
