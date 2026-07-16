#!/usr/bin/env python3
"""
generate_cube_gcode.py -- emit a REAL, printable 20x20x10 mm calibration cube
for a Creality Ender-3 (PLA profile), with a Cura-style header that
attestation.parse_gcode_envelope() can fully parse.

The geometry is a hollow cube: 2 concentric rectangular perimeter walls per
layer, 0% infill -- the standard "fast calibration cube" hollow variant. All
extrusion (E) values are computed from the real filament/extrusion-width
geometry, so the file slices-equivalent and prints on an actual Ender-3.

Run:
    python3 generate_cube_gcode.py
produces:
    calibration_cube_20mm.gcode
"""

from __future__ import annotations

import math
from pathlib import Path

# --- Ender-3 PLA profile (hardcoded defaults) ------------------------------
CUBE_X = 20.0          # mm
CUBE_Y = 20.0          # mm
CUBE_Z = 10.0          # mm  (shorter than 20 -> ~5-8 min print)
LAYER_H = 0.25         # mm  -> 40 layers (MODIFIED: was 0.2)
NOZZLE_C = 200         # degC
BED_C = 50             # degC
PRINT_SPEED = 50.0     # mm/s
TRAVEL_SPEED = 120.0   # mm/s
FIL_DIA = 1.75         # mm
NOZZLE_DIA = 0.4       # mm
EXTRUSION_W = 0.4      # mm (== nozzle dia)
PERIMETERS = 2
INFILL = 0             # %  (hollow)

BED_CENTER_X = 110.0   # Ender-3 220x220 bed -> center
BED_CENTER_Y = 110.0

SLICER = "Cura_SteamEngine 5.12.0"
MACHINE = "Creality Ender-3"
OUTFILE = "experiments/attack-matrix/cube_substituted_20mm.gcode"

# Feedrates in mm/min for G-code (F is mm/min).
F_PRINT = int(PRINT_SPEED * 60)
F_TRAVEL = int(TRAVEL_SPEED * 60)
F_FIRST = int(20 * 60)   # slower, fatter first layer for adhesion

LAYER_COUNT = int(round(CUBE_Z / LAYER_H))

# Filament cross-section area (mm^2) -- converts extruded volume to filament len.
FIL_AREA = math.pi * (FIL_DIA / 2.0) ** 2


def e_for(dist_mm: float, layer_h: float) -> float:
    """Filament length (mm) to extrude over a planar move of dist_mm."""
    volume = dist_mm * layer_h * EXTRUSION_W
    return volume / FIL_AREA


def rect_path(half_x: float, half_y: float):
    """Closed rectangle (5 pts) centered on the bed, given half-extents."""
    cx, cy = BED_CENTER_X, BED_CENTER_Y
    return [
        (cx - half_x, cy - half_y),
        (cx + half_x, cy - half_y),
        (cx + half_x, cy + half_y),
        (cx - half_x, cy + half_y),
        (cx - half_x, cy - half_y),
    ]


def build() -> tuple[str, dict]:
    lines: list[str] = []
    E = 0.0                       # absolute extruder position (Cura style)
    print_path_mm = 0.0          # for time estimate

    def emit(s=""):
        lines.append(s)

    # ---- perimeter ring geometry --------------------------------------
    # Outer wall sits on the model boundary; each subsequent wall steps in
    # inward by one extrusion width. Outer-first, then inner.
    rings = []
    for w in range(PERIMETERS):
        hx = CUBE_X / 2.0 - w * EXTRUSION_W
        hy = CUBE_Y / 2.0 - w * EXTRUSION_W
        rings.append(rect_path(hx, hy))

    # bounding box for header MIN/MAX
    min_x = BED_CENTER_X - CUBE_X / 2.0
    max_x = BED_CENTER_X + CUBE_X / 2.0
    min_y = BED_CENTER_Y - CUBE_Y / 2.0
    max_y = BED_CENTER_Y + CUBE_Y / 2.0

    # ---- body (layers) build first so we know E total + path length ----
    body: list[str] = []

    def bemit(s=""):
        body.append(s)

    for layer in range(LAYER_COUNT):
        z = round((layer + 1) * LAYER_H, 3)
        lh = LAYER_H
        feed = F_FIRST if layer == 0 else F_PRINT
        bemit(f";LAYER:{layer}")
        bemit(f"G0 F{F_TRAVEL} Z{z:.2f}")
        for ring in rings:
            # travel to ring start (no extrusion)
            x0, y0 = ring[0]
            bemit(f"G0 F{F_TRAVEL} X{x0:.3f} Y{y0:.3f}")
            prev = ring[0]
            for (x, y) in ring[1:]:
                d = math.hypot(x - prev[0], y - prev[1])
                E += e_for(d, lh)
                print_path_mm_local = d
                nonlocal_print(print_path_mm_local)
                bemit(f"G1 F{feed} X{x:.3f} Y{y:.3f} E{E:.5f}")
                prev = (x, y)

    # nonlocal_print is a tiny closure to accumulate path length
    # (defined below via list mutation trick)

    # ---- assemble header ----------------------------------------------
    est_time_s = int(_print_path_box[0] / PRINT_SPEED) + 150  # +heat/home/prime
    filament_m = round(E / 1000.0, 4)

    h = lines.append
    h(";FLAVOR:Marlin")
    h(f";TIME:{est_time_s}")
    h(f";Filament used: {filament_m}m")
    h(f";Layer height: {LAYER_H}")
    h(f";MINX:{min_x:.1f}")
    h(f";MINY:{min_y:.1f}")
    h(f";MINZ:{LAYER_H:.1f}")
    h(f";MAXX:{max_x:.1f}")
    h(f";MAXY:{max_y:.1f}")
    h(f";MAXZ:{CUBE_Z:.1f}")
    h(f";LAYER_COUNT:{LAYER_COUNT}")
    h(f";TARGET_MACHINE.NAME:{MACHINE}")
    h(f";Generated with {SLICER}")
    h(";Calibration cube 20x20x10mm, hollow (2 perimeters, 0% infill), PLA")
    h("")

    # ---- start G-code -------------------------------------------------
    h(";--- start gcode ---")
    h("G90 ; absolute positioning")
    h("M82 ; absolute extrusion")
    h("M140 S%d ; start heating bed" % BED_C)
    h("M104 S%d ; start heating nozzle" % NOZZLE_C)
    h("G28 ; home all axes")
    h("M190 S%d ; wait for bed temp" % BED_C)
    h("M109 S%d ; wait for nozzle temp" % NOZZLE_C)
    h("G92 E0 ; reset extruder")
    h("; prime line along left edge")
    h("G1 Z2.0 F3000 ; lift")
    h("G1 X5.0 Y20.0 Z0.3 F5000.0 ; move to prime start")
    h("G1 X5.0 Y200.0 Z0.3 F1500.0 E15 ; draw prime line up")
    h("G1 X5.4 Y200.0 Z0.3 F5000.0 ; shift over")
    h("G1 X5.4 Y20.0 Z0.3 F1500.0 E30 ; draw prime line back")
    h("G92 E0 ; reset extruder after prime")
    h("G1 Z%0.2f F3000 ; lift before first layer" % (LAYER_H + 0.2))
    h("")

    # ---- body ---------------------------------------------------------
    lines.extend(body)
    h("")

    # ---- end G-code ---------------------------------------------------
    h(";--- end gcode ---")
    h("M104 S0 ; nozzle off")
    h("M140 S0 ; bed off")
    h("G91 ; relative positioning")
    h("G1 Z10 F3000 ; raise nozzle")
    h("G90 ; absolute positioning")
    h("G28 X Y ; home X and Y")
    h("M84 ; disable motors")
    h(f";End of G-code -- total filament {filament_m}m, {LAYER_COUNT} layers")

    stats = {
        "layers": LAYER_COUNT,
        "filament_m": filament_m,
        "est_time_s": est_time_s,
        "E_total_mm": round(E, 3),
        "print_path_mm": round(_print_path_box[0], 1),
    }
    return "\n".join(lines) + "\n", stats


# --- path-length accumulator (closure-free, via a 1-element list) ----------
_print_path_box = [0.0]


def nonlocal_print(d: float):
    _print_path_box[0] += d


if __name__ == "__main__":
    text, stats = build()
    Path(OUTFILE).write_text(text)
    print(f"Wrote {OUTFILE}")
    for k, v in stats.items():
        print(f"  {k}: {v}")
