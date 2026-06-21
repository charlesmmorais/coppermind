# Recorded KiCAD fixtures

Each `*.json` file is a snapshot of a KiCAD board's state in a small,
human-readable schema (coordinates in **mm**, layers by name):

```json
{
  "nets": ["GND", "VCC"],
  "footprints": [{"id","reference","value","footprint":"lib:name","x","y","layer"}],
  "tracks": [{"id","net","start":[x,y],"end":[x,y],"width","layer"}]
}
```

The `fake_kipy` test fixture (see `tests/conftest.py`) replays these against the
real `IPCBackend` code with no KiCAD running, so the IPC mapping is exercised
end-to-end. To capture a fixture from a **real** KiCAD board:

```bash
# with KiCAD running, the IPC API enabled, and a board open:
python scripts/record_kicad_fixture.py > tests/fixtures/my_board.json
```
