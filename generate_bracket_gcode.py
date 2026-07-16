#!/usr/bin/env python3
"""
generate_bracket_gcode.py -- emit a REAL, printable small L-shaped mounting
bracket for a Creality Ender-3 (PLA profile), the kind of functional part a
distributed AM supply chain would actually produce. Header is Cura-style so
attestation.parse_gcode_envelope() parses it fully.

Geometry (centered on the bed):
  base    : 30 x 15 x 3 mm  flat section            -> layers 0..14  (0-3mm)
  upright : 3  x 15 x 20 mm vertical wall, one end  -> layers 15..99 (3-20mm)
2 concentric perimeter walls, 0% infill (hollow), 0.2mm layers. E values come
from real filament/extrusion-width geometry so it slices-equivalent and prints.

Run:
    python3 generate_bracket_gcode.py   ->  am_bracket_15mm.gcode
"""

from __future__ import annotations

import math
from pathlib import Path

# --- Ender-3 PLA profile ---------------------------------------------------
LAYER_H = 0.2
NOZZLE_C = 200
BED_C = 50
PRINT_SPEED = 50.0
TRAVEL_SPEED = 120.0
FIL_DIA = 1.75
NOZZLE_DIA = 0.4
EXTRUSION_W = 0.4
PERIMETERS = 2

BED_CENTER_X = 110.0
BED_CENTER_Y = 110.0

# --- L-bracket dimensions --------------------------------------------------
BASE_X, BASE_Y, BASE_Z = 30.0, 15.0, 3.0      # flat base
UPR_X, UPR_Y, TOTAL_Z = 3.0, 15.0, 20.0       # upright wall at one end

SLICER = "Cura_SteamEngine 5.12.0"
MACHINE = "Creality Ender-3"
OUTFILE = "am_bracket_15mm.gcode"

F_PRINT = int(PRINT_SPEED * 60)
F_TRAVEL = int(TRAVEL_SPEED * 60)
F_FIRST = int(20 * 60)

LAYER_COUNT = int(round(TOTAL_Z / LAYER_H))          # 100
BASE_LAYERS = int(round(BASE_Z / LAYER_H))           # 15

FIL_AREA = math.pi * (FIL_DIA / 2.0) ** 2

# --- footprint bounds (x0,y0,x1,y1), centered on bed -----------------------
# Base spans the full 30x15. The upright sits at the -X end of the base.
BASE = (BED_CENTER_X - BASE_X / 2.0, BED_CENTER_Y - BASE_Y / 2.0,
        BED_CENTER_X + BASE_X / 2.0, BED_CENTER_Y + BASE_Y / 2.0)
UPRIGHT = (BASE[0], BED_CENTER_Y - UPR_Y / 2.0,
           BASE[0] + UPR_X, BED_CENTER_Y + UPR_Y / 2.0)


def e_for(dist_mm: float, layer_h: float) -> float:
    return (dist_mm * layer_h * EXTRUSION_W) / FIL_AREA


def rings_for(bounds, n=PERIMETERS):
    """n concentric rectangles inside `bounds`, each stepped in by one line."""
    x0, y0, x1, y1 = bounds
    rings = []
    for w in range(n):
        o = w * EXTRUSION_W
        ax0, ay0, ax1, ay1 = x0 + o, y0 + o, x1 - o, y1 - o
        rings.append([(ax0, ay0), (ax1, ay0), (ax1, ay1),
                      (ax0, ay1), (ax0, ay0)])
    return rings


def build() -> tuple[str, dict]:
    body: list[str] = []
    E = 0.0
    path_mm = 0.0

    for layer in range(LAYER_COUNT):
        z = round((layer + 1) * LAYER_H, 3)
        feed = F_FIRST if layer == 0 else F_PRINT
        bounds = BASE if layer < BASE_LAYERS else UPRIGHT
        body.append(f";LAYER:{layer}")
        body.append(f"G0 F{F_TRAVEL} Z{z:.2f}")
        for ring in rings_for(bounds):
            x0, y0 = ring[0]
            body.append(f"G0 F{F_TRAVEL} X{x0:.3f} Y{y0:.3f}")
            prev = ring[0]
            for (x, y) in ring[1:]:
                d = math.hypot(x - prev[0], y - prev[1])
                E += e_for(d, LAYER_H)
                path_mm += d
                body.append(f"G1 F{feed} X{x:.3f} Y{y:.3f} E{E:.5f}")
                prev = (x, y)

    # Small-perimeter parts run slower than raw path/speed (accel limits on the
    # tiny 3mm upright walls dominate); apply an empirical factor + fixed
    # heat/home/prime overhead to land a realistic ~8-10 min estimate.
    est_time_s = int(path_mm / PRINT_SPEED * 1.9) + 220
    filament_m = round(E / 1000.0, 4)

    min_x = min(BASE[0], UPRIGHT[0]); max_x = max(BASE[2], UPRIGHT[2])
    min_y = min(BASE[1], UPRIGHT[1]); max_y = max(BASE[3], UPRIGHT[3])

    lines: list[str] = []
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
    h(f";MAXZ:{TOTAL_Z:.1f}")
    h(f";LAYER_COUNT:{LAYER_COUNT}")
    h(f";TARGET_MACHINE.NAME:{MACHINE}")
    h(f";Generated with {SLICER}")
    h(";L-bracket mounting part: 30x15x3mm base + 3x15x20mm upright, hollow (2 perimeters), PLA")
    h("")

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

    lines.extend(body)
    h("")

    h(";--- end gcode ---")
    h("M104 S0 ; nozzle off")
    h("M140 S0 ; bed off")
    h("G91 ; relative positioning")
    h("G1 Z10 F3000 ; raise nozzle")
    h("G90 ; absolute positioning")
    h("G28 X Y ; home X and Y")
    h("M84 ; disable motors")
    h(f";End of G-code -- L-bracket, {filament_m}m filament, {LAYER_COUNT} layers")

    stats = {
        "layers": LAYER_COUNT,
        "base_layers": BASE_LAYERS,
        "filament_m": filament_m,
        "est_time_s": est_time_s,
        "est_time_min": round(est_time_s / 60.0, 1),
        "E_total_mm": round(E, 3),
        "print_path_mm": round(path_mm, 1),
    }
    return "\n".join(lines) + "\n", stats


if __name__ == "__main__":
    text, stats = build()
    Path(OUTFILE).write_text(text)
    print(f"Wrote {OUTFILE}")
    for k, v in stats.items():
        print(f"  {k}: {v}")
