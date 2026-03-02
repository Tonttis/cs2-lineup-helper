# CS2 Lineup Helper - Complete Installation Guide

## Step 1: Download the Original Code

1. Go to the [UnknownCheats forum post](https://www.unknowncheats.me/forum/counter-strike-2-a/740935-lineup-helper.html)
2. Scroll down to the second code block (lines 1-744)
3. Copy the entire Python code
4. Save it as `main.py` in your project folder

## Step 2: Add F6 Recording Feature

You need to add **2 code snippets** to enable lineup recording:

### ✅ Snippet 1: Add F6 Detection in main loop

**Location:** In the `LineupThread.run()` method  
**Line:** After line 623 (after `held_type = WEAPON_MAP.get(weapon_id, "Unknown")`)

```python
# Line 623: held_type = WEAPON_MAP.get(weapon_id, "Unknown")

# ⬇️ ADD THIS CODE HERE (after line 623):
held_type = WEAPON_MAP.get(weapon_id, "Unknown")

# F6 Recording Detection
if win32api.GetAsyncKeyState(0x75) & 0x8000:  # VK_F6 = 0x75
    if not hasattr(self, '_f6_pressed') or not self._f6_pressed:
        self._f6_pressed = True
        self._record_lineup(map_name, pos_np.tolist(), held_type)
    time.sleep(0.2)  # Debounce
else:
    self._f6_pressed = False

# Line 625: visible = []
```

**Visual Reference:**[screenshot:1]
```
Line 623:     held_type = WEAPON_MAP.get(weapon_id, "Unknown")
Line 624:     
              <--- INSERT F6 CODE HERE
Line 625:     visible = []
```

---

### ✅ Snippet 2: Add Recording Method

**Location:** In the `LineupThread` class  
**Line:** After the `reload_json()` method (around line 570)

```python
def reload_json(self):
    if os.path.exists(self.json_path):
        try:
            with open(self.json_path, 'r') as f:
                self.lineups_data = json.load(f)
            self.last_map = ""
            print(f"[Lineup] Loaded {self.json_path}")
        except Exception as e:
            print(f"[Lineup] Error loading JSON: {e}")
    else:
        print(f"[Lineup] lineups.json not found at: {self.json_path}")

# ⬇️ ADD THIS NEW METHOD HERE:
def _record_lineup(self, map_name, origin, grenade_type):
    """Record a new lineup at current position + view angles"""
    try:
        # Read current view angles
        view_bytes = self.pm.read_bytes(
            self.client + self.offsets['dwViewAngles'], 12
        )
        if not view_bytes:
            print("[Lineup] Failed to read view angles")
            return
        
        angles = struct.unpack("<3f", view_bytes)
        
        # Create lineup entry
        new_lineup = {
            "name": f"Custom {grenade_type}",
            "type": grenade_type,
            "origin": origin,
            "angles": [angles[0], angles[1]]  # pitch, yaw
        }
        
        # Add to data
        self.lineups_data.setdefault(map_name, [])
        self.lineups_data[map_name].append(new_lineup)
        
        # Save to JSON
        with open(self.json_path, 'w') as f:
            json.dump(self.lineups_data, f, indent=2)
        
        # Reload current map
        self.current_map_lineups = self.lineups_data.get(map_name, [])
        
        msg = f"[Lineup] ✅ Saved {grenade_type} on {map_name} at {origin[:2]}"
        print(msg)
        self.status_update.emit(msg)
        
    except Exception as e:
        print(f"[Lineup] ❌ Error recording: {e}")

def run(self):
    # existing run method continues...
```

---

## Step 3: Update Offsets (Optional but Recommended)

The code auto-fetches offsets from cs2-dumper, but if the fetch fails it uses `NaN` fallbacks.

**To set manual fallback offsets:**

Find the `_fallback_offsets()` function (line ~382) and replace `NaN` with current values:

```python
def _fallback_offsets():
    return {
        'dwLocalPlayerPawn': 0x1817748,      # Update these
        'dwViewMatrix': 0x1920590,
        'dwViewAngles': 0x19B03F0,
        'dwGlobalVars': 0x181A4D0,
        'm_iTeamNum': 0x3E3,
        'm_vOldOrigin': 0x1324,
        'm_pClippingWeapon': 0x1310,
        'm_AttributeManager': 0x1148,
        'm_Item': 0x50,
        'm_iItemDefinitionIndex': 0x1AA,
    }
```

**Get latest offsets:**
- Visit [cs2-dumper](https://github.com/a2x/cs2-dumper/blob/main/output/offsets.json)
- Copy values from `client.dll` section

---

## Step 4: Create lineups.json

Create an empty JSON file in the same folder as `main.py`:

```json
{
  "mirage": [],
  "dust2": [],
  "inferno": [],
  "nuke": [],
  "vertigo": [],
  "anubis": [],
  "ancient": []
}
```

---

## Step 5: Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Step 6: Run

```bash
python main.py  # Must run as Administrator
```

---

## Testing F6 Recording

1. Launch CS2
2. Run `python main.py` as Admin
3. Join offline server: `map de_mirage`
4. Give yourself nades: `sv_cheats 1; give weapon_smokegrenade`
5. Walk to a lineup position
6. Aim at the correct point
7. **Press F6**
8. Check console - should see: `[Lineup] ✅ Saved Smoke on mirage at [x, y]`
9. Check `lineups.json` - new entry should appear

---

## Quick Reference: Offset Variables

**The code DOES use offsets!** They're critical for reading:

| Offset | Purpose |
|--------|--------|
| `dwLocalPlayerPawn` | Find your player entity |
| `dwViewAngles` | Read/write view angles (for auto-aim + recording) |
| `dwViewMatrix` | Convert 3D world to 2D screen (overlay circles) |
| `m_vOldOrigin` | Player position (for distance checks) |
| `m_pClippingWeapon` | Current held weapon |
| `m_iItemDefinitionIndex` | Weapon ID (43=Flash, 45=Smoke, etc.) |
| `dwGlobalVars` | Current map name |

All offsets are stored in `self.offsets` dictionary and auto-fetched from GitHub on startup.

---

## Troubleshooting

### "NaN" errors
- Offset fetch failed + fallbacks are `NaN`
- Update `_fallback_offsets()` with real values

### F6 does nothing
- Check console for errors
- Make sure you're holding a grenade (Smoke/Flash/Molotov/HE)
- Check `lineups.json` was created

### Lineups not showing
- Must be within 300 units of saved position
- Must hold the matching grenade type
- Check map name in console matches JSON key

---

## File Structure

```
cs2-lineup-helper/
├── main.py              # Main script (with 2 snippets added)
├── lineups.json        # Your saved lineups
├── requirements.txt    # Python dependencies
├── hijack_cache.json   # Auto-generated handle cache
└── README.md
```

Done! You now have a fully working CS2 lineup helper with F6 recording. 🎯
