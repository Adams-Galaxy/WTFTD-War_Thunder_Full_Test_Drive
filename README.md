# WTFTD - War Thunder Full Test Drive

> **Beta** - it works, but some features are still untested in game (see *Known limits*). Feedback and bug
> reports are welcome in the issues.
>
> **Disclaimer** - I'm not a professional developer: WTFTD is a hobby project, built with the help of AI
> tools. The code is open and tested, but expect rough edges, and check it yourself if in doubt.
> I first made it for myself and I'm sharing it completely openly. I'm the only one testing it, so if you
> find a bug, don't hesitate to [report it](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/issues/new/choose):
> I'll fix it quickly.

[![Latest release](https://img.shields.io/github/v/release/StonewarP/WTFTD-War_Thunder_Full_Test_Drive?include_prereleases&label=download)](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/releases)
[![Tests](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/actions/workflows/tests.yml/badge.svg)](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Support on Ko-fi](https://img.shields.io/badge/Support-Ko--fi-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/stonewarp)

Test drive **any** War Thunder vehicle - ground, aircraft, helicopters, boats, ships - with the
loadout, ammunition, map, targets and conditions you choose, even vehicles you don't own. Hang any weapon
of the game on any pylon, or **make your own weapons**: more explosive, more thrust, 100 G missiles, nuclear
Sidewinders…

WTFTD takes an **official Test Drive / Test Flight mission** from the game files (with its targets,
triggers and respawn logic), puts your vehicle and setup in it, and writes it to
`War Thunder/UserMissions/`. In game: **Single missions → User missions**.

**Full guide: [the wiki](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki)** - every feature, where it
is, how to use it, how it works and its limits.

![A tour of WTFTD: vehicles, stats, custom pylons with your own weapons, the Weapons page, the weapon editor, maps, the scenario editor](docs/demo.gif)

## Download

**[⬇ Download WTFTD-&lt;version&gt;.exe](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/releases)** (Windows 10/11),
**WTFTD-&lt;version&gt;.zip** (macOS, Apple silicon) or **WTFTD-&lt;version&gt;-linux.tar.gz** (Linux, x86-64) - nothing to
install: double-click it (on Linux, unpack it and run `./WTFTD`), the app opens in its own window and finds your game by
itself (Steam or standalone). Close the window to quit. On Linux the window needs Chrome, Chromium, Edge or Brave;
without one, WTFTD opens in your default browser.

- **First launch**: a welcome screen says where WTFTD keeps its files and what it downloads from where, and asks where
  the game data comes from. Nothing starts before you accept.
  - *Read my installed game*: no download. WTFTD unpacks the game's own files on your PC (≈650 MB on disk, about
    3 minutes), always at your game's exact version, offline.
  - *Download the community datamine*: ≈1 GB from the community
    [War Thunder datamine](https://github.com/gszabi99/War-Thunder-Datamine) (2-5 minutes). It works without the
    game, but it's community data and can be ahead of or behind your game.

  Either way WTFTD builds its database on your PC (no game data is shipped with it), and updates it after each game
  patch.
- Your settings, missions and the game database live in `%LOCALAPPDATA%\WTFTD` (Windows),
  `~/Library/Application Support/WTFTD` (macOS) or `~/.local/share/WTFTD` (Linux, `$XDG_DATA_HOME/WTFTD` when set).
- The apps are not code-signed: if Windows SmartScreen warns you, click **More info → Run anyway**. On macOS, allow it in
  **System Settings → Privacy & Security → Open Anyway**. All are built by GitHub Actions from the released source
  code, and each release lists their **SHA-256**: check your download with `Get-FileHash WTFTD-<version>.exe` in
  PowerShell, `shasum -a 256 WTFTD-<version>.zip` in Terminal or `sha256sum WTFTD-<version>-linux.tar.gz` on Linux.
- When a new version is released, a *New version* button shows at the top: download it and replace the old one; your
  settings and missions are kept.

Details: [Install and first launch](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Install-and-first-launch).

## How it works

1. **Pick a vehicle** (*Vehicles*: list or research trees, filters, stats, carried weapons).
2. **Pick a map** (*Maps*: every official test drive / test flight scenario, with the game's tactical map).
3. **Set it up** in the vehicle panel: loadout (pylon by pylon), ammunition, modifications, cheats, fuel -
   and the map in the scenario editor (targets, allies, your start), flat or **in 3D**.
4. **Create mission** (the difficulty yours to pick, each of its settings changeable), start War Thunder (button in the app), open *Single missions → User missions*.

While you fly (Windows), the **In flight** menu puts your own overlay over the game (your lines, a **fighter HUD**, a
**minimap**), beeps before your aircraft breaks, and records the flight. Step by step:
[Your first mission](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Your-first-mission).

![Vehicle browser](docs/screenshots/01-browse.png)

| Research trees | Pylon editor: your own weapons next to the game's |
|---|---|
| ![Research tree](docs/screenshots/02-tree.png) | ![Pylon editor](docs/screenshots/03-pylons.png) |

| Scenario editor on the real map, with ground heights | Weapons page: IR missiles ranked for dogfight |
|---|---|
| ![Scenario editor](docs/screenshots/05-editor.png) | ![Weapons page](docs/screenshots/11-weapons.png) |

## Features

Each one links to its page in the wiki.

- **[Vehicles](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Vehicles-and-research-trees)**: 3,700+
  vehicles, grid or research trees, filters by type, nation, rank, BR, stats (stock or all upgrades) and carried
  weapons, a comparison of up to 5, research path, economy.
- **[Loadouts](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Loadouts-and-pylons)**: every
  official preset, or any of the game's ~2,300 air weapons on any pylon - nuclear bombs, the missiles of ground vehicles
  and ships, guns - with several custom loadouts kept per aircraft. **[My weapons](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/My-weapons)**:
  your own versions of the game's missiles, bombs, rockets and torpedoes.
- **[Ammunition](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Ammunition)** with penetration by
  distance, **[Modifications](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Modifications)**,
  **[Cheats and in-mission keys](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Cheats-and-in-mission-keys)**,
  **[Custom sights](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Custom-sights)**.
- **[Maps](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Maps)**: 100+ test scenarios, the hangar
  maps, the game's 131 other maps and its
  [ground battle maps](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Ground-battle-maps).
  **[Scenario editor](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Scenario-editor)**: units,
  routes, waves of enemies, the game's assets, vehicles by BR, your start, the real map in 3D.
- **[Weapons](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Weapons)**: every missile, bomb,
  rocket and torpedo with its stats, "best for" rankings, comparison, carriers, and how many it takes to destroy a base.
- **[Challenges](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Challenges)**: scored missions with
  a goal, a timer and your best times.
- **In flight** (Windows):
  **[My overlay and alarms](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/My-overlay-and-alarms)**,
  **[Fighter HUD](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Fighter-HUD)**,
  **[Minimap](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Minimap)**,
  **[Flight data](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Flight-data)** (curves, logs,
  flight report, Tacview export, cockpit window),
  **[Test bench](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Test-bench)**; and on every
  system, **[Battle](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Battle)** (chat and battle
  log) and **[My battles](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/My-battles)** (your
  history from your replays).
- **[My hangar](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/My-hangar)** (owned vehicles,
  lineups, research plan), **[What changed](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/What-changed)**
  between two game versions, **[Skins and sounds](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Skins-and-sounds)**,
  **[3D views](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/3D-views)** of vehicles, weapons and
  maps.
- **[Your library and sharing](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Setups-and-sharing)**:
  My vehicles, My maps, My weapons, My missions; share a setup as a short code or a `.wtftd` file.
- **11 languages** (English, Français, Deutsch, Русский, Polski, Español, Português, Italiano, Čeština, 简体中文,
  日本語), dark / light theme, and
  **[Uninstall](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Updates-and-uninstall)** from
  Settings.

## Custom vehicles (on by default)

War Thunder only opens a user mission if you own its vehicle. With **custom vehicles** (Settings), WTFTD uses the game's
`userVehicles` mechanism (from the CDK, popularised by Ask3lad): the mission loads your vehicle in place of one you own
(US reserve vehicles by default), from files that `include` the real vehicle and apply your modifications, loadouts and
weapons with `@override:` lines.

Only new files are written (never a path that replaces a game file), every file is listed in `user/cdk_manifest.json`,
and **Settings → Remove custom vehicle files** deletes them (do it before playing online if you want a clean install).
One custom vehicle per type at a time: the last mission you create defines it. This is not endorsed by Gaijin - use at
your own risk. More: [Custom vehicles](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Custom-vehicles).

## Safety and fair play

- **Can I get banned for this?** User missions are a normal feature of the game, and WTFTD only uses the game's own files
  and mechanisms. There are no known bans for it, but it isn't endorsed by Gaijin: use it at your own risk.
- **Game settings**: WTFTD doesn't change them, with one exception you turn on yourself: **Use sound mods** adds the line
  `enable_mod:b=yes` to the `sound` block of `config.blk`, the game's own way, and no other byte. It's off by default,
  refused while the game runs, and turning it off or uninstalling puts the file back.
- **In flight**: the tools only read what the game publishes on your own PC (`localhost:8111`): your own vehicle's
  values, the map's fixed objects and, if you ask, your allies - **never an enemy**. The overlay is a separate window:
  nothing is injected and nothing touches the game. Gaijin's staff said overlays built on this local data are fine, and
  that enemy markers on one can count as an ESP overlay
  ([forum, 2024](https://forum.warthunder.com/t/tools-using-data-provided-on-port-8111/106664/197)): WTFTD never shows
  them. The Test bench sends no input of any kind, and My battles keeps only your own line of a replay.
- **Your data**: no account, no telemetry. WTFTD downloads the datamine (unless you read your installed game), wiki
  images and this repository's release list, and sends nothing. The **Feedback** button only opens GitHub's form in
  your browser: you read it and send it yourself.

More: [Safety and fair play](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/Safety-and-fair-play),
[FAQ and troubleshooting](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki/FAQ-and-troubleshooting),
[SECURITY.md](SECURITY.md).

## Run from source

Needs Python 3.10+ (no extra packages); reading the installed game instead of the datamine, and the 3D views, need
Python 3.14+. Double-click **`start.bat`** (Windows) or **`start.command`** (macOS), or run `python -m wtftd`
(`python3 -m wtftd` on Linux; `--browser` uses your default browser instead of an app window).

To build `WTFTD-<version>.exe`, `WTFTD.app` or the Linux `WTFTD` yourself, run **`build_exe.bat`** on Windows,
**`./build_app.sh`** on a Mac or **`./build_linux.sh`** on Linux, with a full Python 3.14+. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Known limits

WTFTD is in beta. The main limits:

- Several features haven't been checked in game yet: routes, waves and assets in the scenario editor, most
  modifications, ground missiles on pylons other than the Aster-30, Challenges, the Test bench, the fighter HUD and the
  minimap. The [in-game checklist](docs/ingame-checklist.md) lists what's still open.
- My overlay, the alarms, the fighter HUD, the minimap, the cockpit window, Flight data, the Test bench, launching War
  Thunder with WTFTD, Steam's launch line and the app window's options work on Windows and Linux, but for the
  notification area (Windows only). All were mostly flown on jets in test flights, on Windows.
- Missions and custom vehicles are local: they can't be played together online. Share the setup instead.
- Stats come from the game's own stat cards or are computed from the vehicle files (tank top speed ±10 %); computed
  penetration is within 1 mm of the official wiki on the shells compared.
- macOS support is new and less tested than Windows; on an Intel Mac, [run from source](#run-from-source).
- Linux support is newer still: checked on Ubuntu 24.04 with Chromium and the game's files, the in-flight features
  against a stand-in for the game's port 8111, not yet with the game played on Linux. The overlay needs X11 or XWayland
  and a compositor; on a Wayland session a full-screen game may stay above it (play in a borderless window then). Ubuntu's own Chromium is a Snap and wasn't tried: if no window opens, start `./WTFTD --browser`.

Every page of the [wiki](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/wiki) ends with its own limits.

## Layout

```
start.bat / build_exe.bat   run from source / build WTFTD-<version>.exe (Windows)
start.command / build_app.sh run from source / build WTFTD.app (macOS)
build_linux.sh              build WTFTD and WTFTD-<version>-linux.tar.gz (Linux)
wtftd_app.py                entry point of the packaged app
wtftd/                      Python backend (stdlib only)
  server.py                 local HTTP server + API (127.0.0.1 only)
  mission.py                official scenario + your setup -> .blk mission
  cdk.py                    custom vehicle files (userVehicles + @override modifications)
  maptex.py / terrain.py    tactical maps and heightmaps from the game files
  models.py                 the 3D views: models, textures, level data and assets, read from the player's game
  builder.py                datamine or game files -> data/*.json
  vromfs.py                 the game's own files: .vromfs.bin containers, binary BLK
  armament.py               Weapons page data (missiles, bombs, rockets, torpedoes)
  cdk.py + builder.py       sensors, engines, avionics, weapons on pylons of any kind
  alarms.py / flightlog.py  in-flight values, alarms and overlay / CSV flight logs, report, Tacview export
  hud.py                    the fighter HUD's three styles, drawn as shapes for the overlay and the cockpit window
  minimap.py / mappaint.py  the minimap: what it shows (never an enemy) / the minimap and the overlay's text painted by
                            Windows (GDI+): the map turned and cut round, smooth letters with a halo
  x11.py / xoverlay.py /    Linux: X11 through ctypes (the window in front, the screen, keys, see-through windows) /
  cairopaint.py             the overlay's loop there / its HUD, text, minimap and glow painted by cairo
  xwindow.py                Linux: the app window through X11 (its place, minimized, closed with the game)
  battle.py                 the game's chat and battle log
  replays.py                My battles: the player's own results, from the game's replay files
  patches.py                What changed: the comparison of two game versions, kept in user/patches.json
  hangar.py                 My hangar: owned vehicles, lineups and research plan, kept in user/hangar.json
  bench.py                  Test bench: finds the valid stretches of a recorded test, results in user/bench.json
  mods.py                   Skins and sounds: untrusted archives, what WTFTD installed, config.blk's one line
  challenges.py             Challenges: what's where on each map, results in user/challenges.json
  waveout.py / tray.py      sound on the output you pick (winmm, PulseAudio) / the app window: its place, minimized,
                            notification area (Windows)
  uninstall.py              Settings → Uninstall
  blk.py, game.py, paths.py BLK writer, install detection, file locations
web/                        UI (HTML/CSS/JS, no build step), web/locales = translations, stats.js = stats & search,
                            weapons.js / myweapons.js = Weapons and My weapons, loadout.js = pylon editor,
                            overlay.js / flight.js / battle.js / history.js = In flight, cockpit.html = the cockpit window,
                            hud.js = the HUD's drawing in the page and the cockpit window,
                            changes.js = What changed, hangar.js = My hangar, mods.js = Skins and sounds, bench.js = Test bench,
                            challenges.js = Challenges,
                            editor.js = scenario editor, model3d.js / map3d.js / lzdecode.js = the 3D views
data/                       game database, generated on first launch (not versioned)
tests/                      automated tests (python -m unittest discover -s tests -t .)
docs/screenshots/           README images (docs/demo.gif: the tour above)
docs/ingame-checklist.md    what still needs checking in game
```

## Feedback

Found a bug or have an idea? The **Feedback** button at the top of the app opens GitHub's form filled in with your
versions, vehicle and setup's **share code**: read it and send it with your GitHub account. You can also open an
[issue](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/issues/new/choose) yourself: for bugs, paste your
share code, it lets us rebuild your exact setup. Questions: [Discussions](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/discussions).

Want to help (code, translations)? See [CONTRIBUTING.md](CONTRIBUTING.md). What changed in each version:
[CHANGELOG.md](CHANGELOG.md). Security problem: [SECURITY.md](SECURITY.md). Everyone taking part follows the
[code of conduct](CODE_OF_CONDUCT.md).

## Support

WTFTD is free and always will be. If you enjoy it, you can support its development on
**[Ko-fi](https://ko-fi.com/stonewarp)** ❤ (also the heart button in the app).

## License

[MIT](LICENSE) - free to use, modify and share, keeping the copyright notice. `web/lzdecode.js` is a port of an MIT-licensed
decoder, with its notice. War Thunder and its data belong
to Gaijin Entertainment; WTFTD is a fan-made tool, not affiliated with or endorsed by Gaijin.
