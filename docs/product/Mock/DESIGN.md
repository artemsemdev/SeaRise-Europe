# Design System: The Precision Observatory

## 1. Overview & Creative North Star
**Creative North Star: The Precision Observatory**
This design system is built to transform complex geospatial data into an authoritative, editorial experience. It eschews the "cluttered dashboard" trope in favor of a sophisticated, layered environment where scientific caution is reflected through intentional white space and tonal depth.

We move beyond standard UI by treating the screen as a digital lens. The aesthetic is "The Precision Observatory"—a high-contrast, map-centric interface that feels like a high-end physical tool. We break the rigid grid through **intentional asymmetry**: information panels are weighted to one side, allowing the "subject" (the map) to breathe, while overlapping elements and glassmorphism create a sense of focused, three-dimensional exploration.

## 2. Colors & Surface Philosophy
The palette is rooted in the depth of the North Atlantic, utilizing high-contrast tones to ensure technical data remains the focal point.

### The "No-Line" Rule
To achieve a premium, seamless feel, **1px solid borders are prohibited for sectioning.** Structural boundaries must be defined exclusively through background color shifts or tonal transitions.
- Use `surface` (#0f1418) for the base map environment.
- Use `surface_container_low` (#171c20) for primary sidebar containers.
- Use `surface_container_high` (#262b2f) for interactive child elements.

### Surface Hierarchy & Nesting
Treat the UI as a series of stacked sheets. 
- **Base Level:** `surface` (The Map).
- **Secondary Level:** `surface_container` (Primary UI panels).
- **Tertiary Level:** `surface_container_highest` (Floating cards or active states).

### The Glass & Gradient Rule
Floating map controls must utilize **Glassmorphism**. Apply `surface_container_highest` with 60% opacity and a `20px` backdrop-blur. 
For primary Action Buttons or high-level climate indicators, use a subtle **Signature Gradient**:
- From: `primary` (#9dcaff) 
- To: `on_primary_container` (#5294d6) at a 135-degree angle. This adds "visual soul" and prevents the data from feeling sterile.

## 3. Typography
We utilize a dual-typeface system to balance editorial authority with scientific legibility.

- **Editorial/Display:** **Manrope** is used for `display`, `headline`, and `title` scales. Its modern, geometric construction feels architectural and premium. Use `headline-lg` (2rem) for location names to create a strong visual anchor.
- **Technical/Data:** **Inter** is used for all `body` and `label` scales. Inter’s high x-height and neutral character make it the gold standard for reading technical sea-level metrics (e.g., "0.85m Rise by 2100").

**Hierarchy Tip:** Use `label-sm` (Inter, 0.6875rem) in uppercase with 0.05em letter spacing for metadata tags to evoke the feel of a precision instrument.

## 4. Elevation & Depth
Hierarchy is achieved through **Tonal Layering** rather than drop shadows.

- **The Layering Principle:** Instead of a shadow, place a `surface_container_lowest` (#0a0f13) card on a `surface_container_low` (#171c20) background. This creates a "recessed" look that feels more scientifically grounded than a "floating" look.
- **Ambient Shadows:** Only use shadows for high-priority modal overlays. Use a wide, 40px blur at 8% opacity using the `on_background` color.
- **The "Ghost Border":** If accessibility requires a border, use `outline_variant` (#42474d) at 15% opacity. It should be felt, not seen.

## 5. Components

### Minimalist Result Cards
Forbid divider lines. Use `spacing-6` (1.3rem) of vertical white space to separate data points.
- **Background:** `surface_container_low`.
- **Corner Radius:** `md` (0.375rem) for a crisp, professional edge.
- **Metric Emphasis:** Place the primary sea-level value in `title-lg` (Inter) colored with `primary` (#9dcaff).

### Map Location Markers
- **Style:** A double-ringed "Precision Target."
- **Outer Ring:** `primary` (#9dcaff) at 30% opacity.
- **Inner Dot:** Solid `primary`.
- **Active State:** The outer ring pulses and expands, while the color shifts to `tertiary` (#ffba38) if an exposure alert is active.

### Control Toggles (Scenarios/Time Horizons)
- **Container:** `surface_container_highest`.
- **Selected State:** Use the `primary_container` (#002b4b) background with `primary` text.
- **Interaction:** A subtle `0.2s` ease-in-out transition on background color shifts. No heavy shadows on toggle buttons.

### Exposure Alerts
- Use the **Amber Alert System**: `tertiary` (#ffba38) for warning text.
- **Container:** `tertiary_container` (#392500) with `on_tertiary_container` (#bf8500) text. This provides a "cautious" warning that is highly legible without being "alarmist" (avoiding bright reds).

## 6. Do's and Don'ts

### Do
- **Do** use `spacing-12` (2.75rem) to separate major UI sections. Large gaps signal confidence and clarity.
- **Do** use `surface_bright` (#353a3e) for hover states on dark components to create a "light-up" effect.
- **Do** align technical data to a tabular mono-spaced setting if possible (using Inter’s features) to ensure numbers align vertically in lists.

### Don't
- **Don't** use 100% white (#FFFFFF) for text. Use `on_surface` (#dfe3e9) to reduce eye strain in high-contrast dark environments.
- **Don't** use `none` or `full` roundedness for primary UI panels. Stick to `md` (0.375rem) or `lg` (0.5rem) to maintain a modern, balanced silhouette.
- **Don't** use "Alert Red" for scientific risks. Use the `tertiary` (Amber) scale to maintain a tone of "Scientific Caution" rather than "Panic."