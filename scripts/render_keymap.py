#!/usr/bin/env python3
"""Render keymap.c into a keymap-drawer YAML + SVG diagram.

Parses the QMK `LAYOUT(...)` blocks straight out of keymap.c (no qmk_firmware
or qmk CLI needed) and emits keymap-drawer/keymap.yaml. The physical layout
comes from the local QMK sofle/rev1 info (keymap-drawer/sofle_layout.json),
whose key order matches the LAYOUT macro argument order.

Usage:
    python3 scripts/render_keymap.py                    # QWERTY only (default)
    python3 scripts/render_keymap.py QWERTY LOWER       # specific layers
    python3 scripts/render_keymap.py all                # every layer
    keymap draw keymap-drawer/keymap.yaml -o keymap-drawer/keymap.svg

CI runs the same two commands (.github/workflows/draw-keymap.yml) from the
repo root; qmk_info_json paths inside the YAML resolve against the CWD.
"""
import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KEYMAP_C = REPO / "keymap.c"
OUT_DIR = REPO / "keymap-drawer"
OUT_YAML = OUT_DIR / "keymap.yaml"
LAYOUT_JSON = OUT_DIR / "sofle_layout.json"

EXPECTED_KEYS = 60  # sofle/rev1 LAYOUT including two encoder slots

# Legends: QMK keycode -> dict of keymap-drawer LayoutKey fields
# (t=tap center, s=shifted top, h=hold bottom). Unmapped codes fall back to
# the raw name (e.g. KC_F5 -> F5), so new keycodes never break the render.
LEGENDS = {
    "KC_ESC": {"t": "Esc"},
    "KC_TAB": {"t": "Tab"},
    "KC_BSPC": {"t": "Bksp"},
    "KC_ENT": {"t": "Enter"},
    "KC_SPC": {"t": ""},
    "KC_MUTE": {"t": "Mute"},
    "KC_GRV": {"t": "`", "s": "~"},
    "KC_MINS": {"t": "-", "s": "_"},
    "KC_EQL": {"t": "=", "s": "+"},
    "KC_PLUS": {"t": "+"},
    "KC_EXLM": {"t": "!"},
    "KC_AT": {"t": "@"},
    "KC_HASH": {"t": "#"},
    "KC_DLR": {"t": "$"},
    "KC_PERC": {"t": "%"},
    "KC_CIRC": {"t": "^"},
    "KC_AMPR": {"t": "&"},
    "KC_ASTR": {"t": "*"},
    "KC_LPRN": {"t": "("},
    "KC_RPRN": {"t": ")"},
    "KC_LBRC": {"t": "["},
    "KC_RBRC": {"t": "]"},
    "KC_LCBR": {"t": "{"},
    "KC_RCBR": {"t": "}"},
    "KC_BSLS": {"t": "\\", "s": "|"},
    "KC_PIPE": {"t": "|"},
    "KC_SCLN": {"t": ";", "s": ":"},
    "KC_COLN": {"t": ":"},
    "KC_QUOT": {"t": "'", "s": '"'},
    "KC_COMM": {"t": ",", "s": "<"},
    "KC_DOT": {"t": ".", "s": ">"},
    "KC_SLSH": {"t": "/", "s": "?"},
    "KC_INS": {"t": "Ins"},
    "KC_DEL": {"t": "Del"},
    "KC_PSCR": {"t": "PrtSc"},
    "KC_APP": {"t": "Menu"},
    "KC_CAPS": {"t": "Caps"},
    "KC_PGUP": {"t": "PgUp"},
    "KC_PGDN": {"t": "PgDn"},
    "KC_UP": {"t": "\u2191"},
    "KC_DOWN": {"t": "\u2193"},
    "KC_LEFT": {"t": "\u2190"},
    "KC_RGHT": {"t": "\u2192"},
    "KC_LSFT": {"h": "Shift"},
    "KC_RSFT": {"h": "Shift"},
    "KC_LCTL": {"h": "Ctrl"},
    "KC_RCTL": {"h": "Ctrl"},
    "KC_LALT": {"h": "Alt"},
    "KC_RALT": {"h": "Alt"},
    "KC_LGUI": {"h": "GUI"},
    "KC_RGUI": {"h": "GUI"},
    "TL_LOWR": {"h": "Lower"},
    "TL_UPPR": {"h": "Raise"},
    # custom keycodes (process_record_user in keymap.c)
    "KC_PRVWD": {"t": "Word\u2190"},
    "KC_NXTWD": {"t": "Word\u2192"},
    "KC_LSTRT": {"t": "Home"},
    "KC_LEND": {"t": "End"},
    "C(KC_BSPC)": {"t": "\u2303Bksp"},
    "C(KC_Z)": {"t": "Undo"},
    "C(KC_X)": {"t": "Cut"},
    "C(KC_C)": {"t": "Copy"},
    "C(KC_V)": {"t": "Paste"},
    "KC_QWERTY": {"t": "QWERTY"},
    "KC_COLEMAK": {"t": "COLEMAK"},
    "QK_BOOT": {"t": "Boot"},
    "CG_TOGG": {"t": "Mac/Win"},
    "KC_VOLD": {"t": "Vol-"},
    "KC_VOLU": {"t": "Vol+"},
    "KC_MPRV": {"t": "Prev"},
    "KC_MPLY": {"t": "Play"},
    "KC_MNXT": {"t": "Next"},
    "_______": {"t": "\u25bd"},  # transparent
    "XXXXXXX": {"t": ""},  # KC_NO
}

DIGIT_SHIFT = {
    "1": "!", "2": "@", "3": "#", "4": "$", "5": "%",
    "6": "^", "7": "&", "8": "*", "9": "(", "0": ")",
}


def legend(keycode: str) -> dict:
    """Map one QMK keycode string to a keymap-drawer LayoutKey dict."""
    if keycode in LEGENDS:
        return dict(LEGENDS[keycode])
    if keycode.startswith("KC_F") and keycode[3:].isdigit():
        return {"t": keycode[3:]}  # F1..F24
    m = re.fullmatch(r"KC_([A-Z])", keycode)
    if m:
        letter = m.group(1)
        return {"t": letter.lower(), "s": letter}
    m = re.fullmatch(r"KC_(\d)", keycode)
    if m:
        d = m.group(1)
        return {"t": d, "s": DIGIT_SHIFT[d]}
    return {"t": keycode.replace("KC_", "")}


def yq(s: str) -> str:
    """Quote a string for YAML output."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def parse_layers(src: str):
    """Extract [(name, [keycodes...])] in declaration order."""
    layers = []
    for m in re.finditer(r"\[(_\w+)\]\s*=\s*LAYOUT\s*\(", src):
        i, depth, buf = m.end(), 1, []
        while depth:
            c = src[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            if depth:
                buf.append(c)
            i += 1
        block = re.sub(r"/\*.*?\*/|//[^\n]*", "", "".join(buf), flags=re.S)
        keys = [k.strip() for k in block.split(",") if k.strip()]
        layers.append((m.group(1)[1:], keys))
    return layers


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Render keymap.c layers into keymap-drawer YAML")
    ap.add_argument(
        "layers", nargs="*",
        help="layer names to render (default: QWERTY; 'all' = every layer)")
    args = ap.parse_args()

    src = KEYMAP_C.read_text()
    all_layers = parse_layers(src)
    if not all_layers:
        print("error: no LAYOUT() blocks found in keymap.c", file=sys.stderr)
        return 1

    names = [n for n, _ in all_layers]
    wanted = args.layers or ["QWERTY"]
    if wanted == ["all"]:
        wanted = names
    unknown = [n for n in wanted if n not in names]
    if unknown:
        print(f"error: unknown layer(s) {unknown}; available: {names}",
              file=sys.stderr)
        return 1
    layers = [(n, k) for n, k in all_layers if n in wanted]

    with open(LAYOUT_JSON) as f:
        n_layout_keys = len(json.load(f)["layouts"]["LAYOUT"]["layout"])

    # visual row grouping of the LAYOUT macro args (12/12/12/14 + 5/5 thumbs)
    row_sizes = [12, 12, 12, 14, 5, 5]
    out = ["# Generated by scripts/render_keymap.py from keymap.c -- do not edit.",
           "layout:",
           "  qmk_info_json: keymap-drawer/sofle_layout.json",
           "layers:"]
    for name, keys in layers:
        if len(keys) != EXPECTED_KEYS or len(keys) != n_layout_keys:
            print(f"error: layer {name} has {len(keys)} keys, "
                  f"expected {EXPECTED_KEYS} (layout json: {n_layout_keys})",
                  file=sys.stderr)
            return 1
        out.append(f"  {name}:")
        i = 0
        for size in row_sizes:
            row = keys[i:i + size]
            i += size
            cells = ", ".join(
                ("''" if not lg.get("t") and not lg.get("s") and not lg.get("h")
                 else (yq(lg["t"]) if set(lg) == {"t"}
                       else "{" + ", ".join(
                           f"{k}: {yq(v)}" for k, v in lg.items()) + "}"))
                for lg in (legend(k) for k in row))
            out.append(f"    - [{cells}]")
    has_transparent = any(
        lg.get("t") == "\u25bd" for _, keys in layers
        for lg in (legend(k) for k in keys))
    footer = "  \u00b7  ".join(
        ["sofle v2"]
        + (["\u25bd = transparent"] if has_transparent else [])
        + ["hold Lower+Raise = ADJUST"])
    out += [
        "draw_config:",
        f"  footer_text: {yq(footer)}",
    ]

    OUT_DIR.mkdir(exist_ok=True)
    OUT_YAML.write_text("\n".join(out) + "\n")
    print(f"wrote {OUT_YAML.relative_to(REPO)} "
          f"(layers: {', '.join(n for n, _ in layers)}; "
          f"{EXPECTED_KEYS} keys each)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
