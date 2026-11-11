# Contributing to WTFTD

Thanks for helping! Bug reports, ideas, translation fixes and code are all welcome.

- **Bugs and ideas**: open an [issue](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/issues/new/choose) (use the forms).
  For a bug, paste your setup's **share code** (My vehicles → Share): it lets us rebuild your exact setup.
- **Questions**: ask in [Discussions](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/discussions).
- **Security problems**: don't open a public issue, see [SECURITY.md](SECURITY.md).
- Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).

## Run from source

Windows 10/11, macOS or Linux, Python 3.10+ - no extra package needed (standard library only). Reading the installed game
needs Python 3.14+ (`compression.zstd`, in the standard library from that version): below it the app runs as usual and
the option is shown disabled. The apps are built with a full 3.14 (the exe carries its Python, the overlay needs its tkinter): `build_exe.bat` refuses less, `build_app.sh` and `build_linux.sh` warn.

```bash
git clone https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive.git
cd WTFTD-War_Thunder_Full_Test_Drive
python -m wtftd
```

The first launch asks where the game data comes from: the installed game (unpacked into `.cache/gamefiles`) or the
community [War Thunder datamine](https://github.com/gszabi99/War-Thunder-Datamine) (≈1 GB into `.cache/datamine`),
then builds `data/`. Rebuild the data by hand with `python -m wtftd.builder --no-pull` (without downloading) or
`python -m wtftd.builder` (with an update); add `--game` to use the installed game.

`python -m wtftd --browser` opens the app in your default browser, handy with the browser's developer tools.

## Code layout

| Path | What it does |
|---|---|
| `wtftd/server.py` | Local HTTP server and API (127.0.0.1 only) |
| `wtftd/builder.py` | Datamine or game files → `data/*.json` (vehicles, scenarios, trees, translations) |
| `wtftd/vromfs.py` | The game's own files: `.vromfs.bin` containers and binary BLK → the datamine's JSON |
| `wtftd/armament.py` | Weapons page data (missiles, bombs, rockets, torpedoes) |
| `wtftd/mission.py` | Official scenario + your setup → `.blk` user mission |
| `wtftd/cdk.py` | Custom vehicle files (`userVehicles` + `@override`) |
| `wtftd/alarms.py` | In-flight values (`reader()`), alarms and overlay (`available()`), Windows and Linux: game's `/state` + flight model limits; UI in `web/overlay.js`. Linux draws the overlay in `xoverlay.py` (X11 windows from `x11.py`, painted by `cairopaint.py`) |
| `wtftd/flightlog.py` | CSV flight logs (`user/logs`); curves in `web/flight.js` |
| `wtftd/battle.py` | The game's chat and battle log; UI in `web/battle.js` |
| `wtftd/replays.py` | My battles: the player's own results from the game's replays, indexed in `.cache/battles.json`; UI in `web/history.js` |
| `wtftd/patches.py` | What changed: compares the old database with the new one at each new game version, keeps the last patches in `user/patches.json`. Its `FIELDS` table says what's compared: a new value takes one line there. UI in `web/changes.js` |
| `wtftd/hangar.py` | My hangar: owned vehicles, lineups and research plan in `user/hangar.json`, checked on the way in and out; UI and the matchmaking rule in `web/hangar.js` |
| `wtftd/bench.py` | Test bench: the player flies a guided test in a generated mission, `analyse()` keeps the valid stretches of the recording and says why it refused the rest, results in `user/bench.json`. `TESTS` says what each test checks and how it finds a result: a new test takes one line there and one function. It reads, never sends: no input of any kind goes to the game. UI in `web/bench.js` |
| `wtftd/mods.py` | Skins and sounds: untrusted `.zip` and folders, `user/mods_manifest.json`, the one line of `config.blk`. It's the only code that changes a game setting: see `SECURITY.md`. UI in `web/mods.js`, skin textures in `web/model3d.js` |
| `wtftd/challenges.py` | Challenges: scored missions, what stands where on each map, results in `user/challenges.json` from the game's `/mission.json` and the replays. The rules are `mission.apply_challenge`; UI in `web/challenges.js` |
| `wtftd/blk.py` | BLK text format writer / reader |
| `web/` | UI: plain HTML / CSS / JavaScript, no build step |
| `web/locales/` | UI translations |
| `tests/` | Automated tests |

When a change adds fields the app needs to `data/*.json`, bump `SCHEMA` in `wtftd/builder.py`: installed data
is then rebuilt automatically.

## Tests

```bash
python -m unittest discover -s tests -t .
```

They run on GitHub for every push and pull request. Tests that need the real game files
(`tests/test_game_data.py`, the comparison in `tests/test_vromfs.py`) only run on a PC that has them, the comparison
with Python 3.14. Add a test with any fix to the data extraction: a reference value from the game files is enough.

## Translations

UI texts live in `web/locales/<code>.json`; `en.json` is the reference. Vehicle, weapon and map names come
from the game's own translations and don't need translating.

- **Fix a wording**: edit the file on GitHub (pencil icon) and propose the change, or open a *Suggestion*
  issue with the key and the correct text.
- **Add a language**: copy `en.json` to `<code>.json`, translate the values (keep the keys and the
  `{placeholders}`), and add the language to `web/locales/index.json`.

## Pull requests

- One topic per pull request, with a short description of what changes for the player.
- Match the style of the surrounding code; no new dependencies (the app is standard-library Python and plain JS).
- UI text: English in `en.json`, plus the other languages if you can (otherwise English is used as fallback).
- Never commit game files (`data/`, `.cache/`) or anything from your `user/` folder.

## Releases

1. Bump `__version__` in `wtftd/__init__.py` and add the version to `CHANGELOG.md`.
2. Commit, push, then publish a release with the tag `v<version>-beta` (notes = the changelog entry).
3. GitHub Actions builds `WTFTD-<version>-windows.exe`, `WTFTD-<version>-macos.zip` and `WTFTD-<version>-linux.tar.gz`
   from that tag and attaches them to the release with their SHA-256.
