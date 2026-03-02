# CS2 Lineup Helper (External)

External grenade lineup helper for Counter-Strike 2 with **in-game lineup recording** via F6 keybind.

Based on the [original lineup helper by Gajoo](https://www.unknowncheats.me/forum/counter-strike-2-a/740935-lineup-helper.html) from UnknownCheats.

## Features

✅ **Full external overlay** — PyQt5 transparent window over CS2  
✅ **F6 to record new lineups** — Stand at position, look at aim point, press F6 to save  
✅ **Auto lineup detection** — Shows nearby lineups with 3D circles and auto-aim assist  
✅ **Handle hijacking** — Stealthy memory reading without direct `OpenProcess`  
✅ **Auto offsets** — Fetches latest CS2 offsets from cs2-dumper on startup  
✅ **Per-map JSON storage** — Lineups organized by map name  

## Installation

### Requirements
- Python 3.9+  
- Windows 10/11  
- CS2 running  

### Setup

```bash
git clone https://github.com/Tonttis/cs2-lineup-helper.git
cd cs2-lineup-helper
pip install -r requirements.txt
```

### Run (as Administrator)

```bash
python main.py
```

The script will:
1. Request administrator privileges (required for memory reading)
2. Attach to CS2 process
3. Hijack a handle for stealthy mem access
4. Load lineups from `lineups.json`
5. Show overlay with lineup circles

## Usage

### Recording New Lineups

1. **Join a practice server** (offline or with `sv_cheats 1`)
2. **Stand at the lineup position** where you want to throw from
3. **Select the grenade** (smoke/flash/molotov/HE)
4. **Look at the correct aim point**
5. **Press F6** — lineup will be saved to `lineups.json` for the current map

💡 The script captures:
- Your current position (`m_vOldOrigin`)
- View angles (pitch/yaw)
- Current grenade type
- Current map name

### Using Saved Lineups

- Walk near a saved lineup (within 300 units)
- Hold the matching grenade type
- The overlay shows a **3D circle** at the lineup position
- When you're within 5 units, the circle turns **green**
- **Auto-aim assist** will adjust your view angles to the saved angles
- After 1.5 seconds of holding position+angles correctly, a progress arc fills

### Lineup JSON Format

```json
{
  "mirage": [
    {
      "name": "A Site Smoke [LClick Jump]",
      "type": "Smoke",
      "origin": [1422.96875, -55.96063232421875, -167.96875],
      "angles": [-20.6479434967041, -168.48341369628906]
    }
  ],
  "dust2": [...]
}
```

## Configuration

### Keybinds

- **F6** — Record new lineup at current position

### Distance Thresholds (in `LineupThread.run`)

```python
if dist < 300:  # Show lineup overlay
if dist < 5.0:  # Activate auto-aim
```

## Technical Details

### Handle Hijacking

The script uses **handle duplication** instead of direct `OpenProcess` to avoid some anti-cheat detection:

1. Enumerates all open handles via `NtQuerySystemInformation`
2. Finds a handle to `cs2.exe` from another process (steam.exe, lsass.exe, etc.)
3. Duplicates that handle into the Python process
4. Uses the duplicated handle for `ReadProcessMemory`

### Offsets

Auto-fetched from [cs2-dumper](https://github.com/a2x/cs2-dumper):
- `dwLocalPlayerPawn`
- `dwViewAngles`
- `dwViewMatrix`
- `m_vOldOrigin`
- `m_pClippingWeapon`
- `m_iItemDefinitionIndex`

Fallback offsets are in `_fallback_offsets()` if online fetch fails.

## Troubleshooting

### "CS2 not found"

- Make sure CS2 is running
- Run the script as Administrator

### "Hijack failed"

- Try running CS2 via Steam (the hijack prioritizes `steam.exe` handles)
- The script falls back to standard `OpenProcess` if hijacking fails

### "Unable to load page" on GitHub

- GitHub web editor can be unstable for large files
- Use `git clone` and edit locally

### No lineups showing

- Check `lineups.json` exists in the same folder as `main.py`
- Press F6 to record your first lineup
- Check console output for current map name

## Credits

- **Original code**: [Gajoo @ UnknownCheats](https://www.unknowncheats.me/forum/counter-strike-2-a/740935-lineup-helper.html)
- **F6 recording feature**: Added in this fork
- **CS2 offsets**: [a2x/cs2-dumper](https://github.com/a2x/cs2-dumper)

## Disclaimer

⚠️ **This is for educational purposes only.** Using external memory readers in online games may violate the game's terms of service and result in bans. Use at your own risk, preferably in offline/practice servers only.

## License

MIT
