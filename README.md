# WTFTD — War Thunder Full Test Drive

> **Beta** — it works, but some features are still untested in game (see *Known limits*). Feedback and bug
> reports are welcome in the issues.
>
> **Disclaimer** — I'm not a professional developer: WTFTD is a hobby project, built with the help of AI
> tools. The code is open and tested, but expect rough edges, and check it yourself if in doubt.
> I first made it for myself and I'm sharing it completely openly. I'm the only one testing it, so if you
> find a bug, don't hesitate to [report it](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/issues/new/choose):
> I'll fix it quickly.

[![Latest release](https://img.shields.io/github/v/release/StonewarP/WTFTD-War_Thunder_Full_Test_Drive?include_prereleases&label=download)](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/releases)
[![Tests](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/actions/workflows/tests.yml/badge.svg)](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Support on Ko-fi](https://img.shields.io/badge/Support-Ko--fi-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/stonewarp)

Test drive **any** War Thunder vehicle — ground, aircraft, helicopters, boats, ships — with the
loadout, ammunition, map, targets and conditions you choose, even vehicles you don't own. Hang any weapon
of the game on any pylon, or **make your own weapons**: more explosive, more thrust, 100 G missiles, nuclear
Sidewinders…

WTFTD takes an **official Test Drive / Test Flight mission** from the game files (with its targets,
triggers and respawn logic), puts your vehicle and setup in it, and writes it to
`War Thunder/UserMissions/`. In game: **Single missions → User missions**.

![A tour of WTFTD: vehicles, stats, custom pylons with your own weapons, the Weapons page, the weapon editor, maps, the scenario editor](docs/demo.gif)

## Download

**[⬇ Download WTFTD-&lt;version&gt;.exe](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/releases)** (Windows 10/11) or
**WTFTD-&lt;version&gt;.zip** (macOS, Apple silicon) — nothing to install: double-click it, the app opens in its own
window and finds your game by itself (Steam or standalone). Close the window to quit.

- **First launch**: a welcome screen says where WTFTD keeps its files and what it downloads from where, and
  asks where the game data should come from. Nothing starts before you accept.
  - *Read my installed game*: no download. WTFTD unpacks the game's own files on your PC (≈650 MB on disk, about
    3 minutes), always at your game's exact version, offline.
  - *Download the community datamine*: ≈1 GB from the community
    [War Thunder datamine](https://github.com/gszabi99/War-Thunder-Datamine) (2–5 minutes). It works without the
    game, but it's community data and can be ahead of or behind your game. If Git isn't installed, the official
    portable MinGit (git-for-windows) is fetched automatically.

  Either way WTFTD builds its database on your PC (no game data is shipped with it), and updates it after each game
  patch. Change the source at any time in **Settings → Game data**.
- Your settings, missions and the game database live in `%LOCALAPPDATA%\WTFTD` (Windows) or
  `~/Library/Application Support/WTFTD` (macOS).
- The apps are not code-signed: if Windows SmartScreen warns you, click **More info → Run anyway**. On macOS,
  unzip `WTFTD-<version>.zip`, move `WTFTD.app` to *Applications*, open it once, then allow it in **System Settings →
  Privacy & Security → Open Anyway**. Both are built by GitHub Actions from the released source code, and each
  release lists their **SHA-256**: check your download with `Get-FileHash WTFTD-<version>.exe` in PowerShell or
  `shasum -a 256 WTFTD-<version>.zip` in Terminal.
- The app window uses Edge or Chrome (on macOS: Chrome, Edge, Brave or Chromium) in app mode; without one,
  WTFTD opens in your default browser.
- When a new version is released, the app tells you (a *New version* button at the top) — download the new version
  and replace the old one; your settings and missions are kept.

## How it works

1. **Pick a vehicle** (*Vehicles*: list or research trees, filters by category, type — light / heavy tank,
   fighter, bomber… —, nation, rank, BR, stats, carried weapons).
2. **Pick a map** (*Maps*: every official test drive / test flight scenario, with the game's tactical map).
3. **Set it up** in the vehicle panel: loadout (pylon by pylon), ammunition, modifications, cheats, fuel —
   and the map in the scenario editor (targets, allies, your start).
4. **Create mission**, start War Thunder (button in the app), open *Single missions → User missions*.

In the scenario editor, a switch turns the flat map into **the real level in 3D**, read from your own game: place units
and the game's assets on its relief and turn them the way you want. Vehicles and weapons have a **3D view** too.

While you fly (Windows), the **In flight** menu puts your own overlay over the game, beeps before your aircraft
breaks, and records the flight: live curves, a flight report, a cockpit window for a second screen, the battle log.

![Vehicle browser](docs/screenshots/01-browse.png)

| Research trees | Stats: tanks over 60 km/h, best turret armor first |
|---|---|
| ![Research tree](docs/screenshots/02-tree.png) | ![Stats filters](docs/screenshots/07-stats.png) |

| Carrying the AIM-9L, fastest first, vehicle stats | Weapon picker: vehicles carrying given weapons |
|---|---|
| ![Weapon search and stats](docs/screenshots/08-stats-drawer.png) | ![Weapon picker](docs/screenshots/09-weapon-picker.png) |

![Vehicle comparison](docs/screenshots/10-compare.png)

| Pylon editor: your own weapons next to the game's | Cheats: invulnerable, unbreakable airframe, super mobility, no reload |
|---|---|
| ![Pylon editor](docs/screenshots/03-pylons.png) | ![Cheats](docs/screenshots/04-cheats.png) |

![Maps and scenarios](docs/screenshots/13-maps.png)

| Scenario editor on the real map, with ground heights | Test flight: your start and the scenario's targets |
|---|---|
| ![Scenario editor](docs/screenshots/05-editor.png) | ![Air scenario](docs/screenshots/06-editor-air.png) |

| Weapons page: IR missiles ranked for dogfight, R-73 details and community view | Comparing weapons side by side |
|---|---|
| ![Weapons page](docs/screenshots/11-weapons.png) | ![Weapon comparison](docs/screenshots/12-weapons-compare.png) |

| My weapons: an AIM-9L at 100 G and thrust ×5, a nuclear AIM-9M, a 10-tonne Mk 82 | The weapon editor: Simple… |
|---|---|
| ![My weapons](docs/screenshots/14-my-weapons.png) | ![Weapon editor](docs/screenshots/15-weapon-editor.png) |

![…and Advanced: every value of the weapon's file, explained](docs/screenshots/16-weapon-editor-advanced.png)

## Features

- **3,700+ vehicles** with images from the [War Thunder wiki](https://wiki.warthunder.com/), grid or
  research-tree view, filters (category, **vehicle type** — light / medium / heavy tank, tank destroyer, SPAA,
  fighter, bomber, attacker, helicopter, drone, destroyer… with the game's own names —, nation, rank, BR in AB/RB/SB,
  favorites, premium/event, non-playable units), **sort by rarity** with badges (premium, squadron, pack, event,
  removed, hidden)
- **Stats & fine search**: each vehicle's performance — top / reverse speed, power-to-weight, engine power,
  turret / hull armor, turret traverse, gun caliber, AP and HEAT penetration, reload; for aircraft turn time, roll rate,
  climb rate, ceiling, thrust-to-weight, wing loading; for ships displacement — shown on its card, with a
  **Stock / All upgrades** switch (stock values from the modules' penalties, estimated for aircraft), **sortable**
  (fastest, best turning, best armored…) and **filterable with min / max** values. **Weapon picker**: pick carried
  weapons by their game icon (missiles, bombs, rockets, nuclear, guns, shells — or a shell type like “any
  APFSDS”), with how many vehicles carry each; vehicles must carry all the picked weapons
- **Weapons page**: every missile, bomb, rocket and torpedo (~870) by category — IR / radar air-to-air,
  surface-to-air, ATGM, air-to-surface, guided bombs, bombs, **nuclear bombs** (yield from 5 kt to 1.6 Mt, and the
  ground battles' instant-win killstreak nukes), rockets, torpedoes — with stats from the game files
  (motor speed, max G, lock angle, IRCCM, seeker range, penetration, TNT equivalent…), **"best for" rankings**
  (dogfight, head-on, flare resistance, beyond visual range, killing tanks, stand-off…), a short guide per
  category, community notes on well-known weapons, side-by-side comparison and the vehicles that carry each one. The
  search also finds a weapon by what carries it: `S-300` finds the 5V55R.
  **Bombing a target**: pick a base or an airfield, and see its HP from the game's mission templates, what one weapon
  takes off it and how many it takes
- **3D view** (prototype): a vehicle's or a weapon's model with its textures and paint, with a weapon's positions (stowed,
  deployed, in its container) and its parts (booster, fins, caps), which can be left out one by one. Read from your own game
  files: nothing is stored or exported, and no model or texture is in this project. The paint is an approximation
- **Compare up to 5 vehicles side by side** (button next to the favorite star): BR, every stat with the best
  value highlighted, guns with their caliber, shell types, pylon weapons
- **Penetration by distance** (vehicle panel → Ammunition): a curve for every shell and guided missile of the gun,
  with the values at 10, 100, 500, 1000 and 2000 m
- **Research and purchase cost**: each vehicle's RP and SL to sort, filter and compare, and a *Research path* that
  adds them up along the line, from the first vehicle to the one you picked
- **Breaking limits** in the vehicle panel of aircraft and helicopters: speed, Mach, gear, flaps, variable sweep
- **Maps tab**: 100+ official scenarios with the game's own tactical map — firing range, Fulda, naval
  range, airfields, heli ranges, carriers, seaplane bases… plus the **hangar maps** (regular, winter,
  Halloween, Lunar New Year, anniversary); the ones that fit your vehicle first
- **Loadout**: every official preset, or a **pylon editor** laid out like the game's (presets as rows,
  pylons as columns, game icons). Turn on **non-standard weapons** to mount any of the game's ~2,300 air
  weapons on any pylon — missiles, bombs, rockets, torpedoes, pods, and **nuclear bombs** (RN-28, RN-40,
  B61, AN-52, KB-1, RDS-4, RDS-37) — and the **missiles, rockets and guns of ground vehicles and ships** (S-300, Pantsir,
  Aster, Smerch...: the Aster-30 is checked in game, the others not yet), with a warning when the aircraft lacks the radar / laser designator /
  guidance the weapon needs. Pylons fire one at a time, as in the game
- **My weapons**: your own versions of the game's missiles, bombs, rockets and torpedoes (see below), on
  your pylons and on AI aircraft
- **Ammunition**: 4 shell slots with round counts for tanks; belts per gun for aircraft, helicopters and ships; the
  game's own shell and belt icons; **flares / chaff split** for countermeasure launchers (beta, see *Known limits*)
- **Modifications** (custom vehicles): engine power, mass, top speed, brakes, turret speed, thrust,
  reload, ammo capacity, shell velocity / mass / explosive / penetration… On aircraft: another radar or warning receiver,
  another aircraft's engine, avionics on or off. On tanks and ships: another weapon in place of a gun. For all: the crew's
  language and voices. Not checked in game yet
- **Scenario editor** on the level's real tactical map, read from the game files, or **in 3D**:
  - drag any unit (and your start) to move it — ground units are put **on the ground** using the map's heightmap;
  - **turn what you place**: drag a selected unit's arrow, or use its heading slider. Several selected turn together, and the
    scenario's own vehicles keep the heading you give them;
  - move the map with the mouse, or **Z Q S D** on a French keyboard, **W A S D** on an English one;
  - add ground, air or naval units as **allies or enemies**, non-playable ones too (S-300 launcher and radars, carriers,
    trains...), **objects** (AA guns, trucks, buildings, radars, infantry), remove units, swap their vehicle;
  - **assets**: the game's own set pieces, about 500 of them, from a crate to a whole camp or an airfield, as its own missions
    place them. Not checked in game yet;
  - the units of the game's templates (test flight targets) can change vehicle too;
  - **vehicles by BR**: enemies, allies or a selection get vehicles of their own kind at your vehicle's BR (they
    follow it when you take another one) or at a BR you pick, from the nations you choose;
  - behaviour: still, aggressive, return fire or passive; enemies can **hunt you**, allies can **escort you**;
  - **routes** drawn on the map, shared by the units selected for a convoy, and **waves of enemies**, each one coming when
    the one before is destroyed. Not checked in game yet;
  - shows where the scenario really spawns you (runway / start area), the units it teleports and its zones at their real size;
  - **the real map in 3D** (prototype), one switch away, read from your own game files: the relief of the whole level, air
    maps included, the ground in its real colours, water, buildings, trees with their leaves, your units as their real models
    and the zones as volumes. Add, select, move and turn units as on the flat map; right drag turns the view, the wheel zooms
- **Ground battle maps**: the game's Domination layouts (79 on 55 maps) from either side's spawn, with the capture
  zones and the other side's spawn in the editor (a solo sandbox: no AI, score or capture)
- **Conditions**: time of day, weather, air start with altitude / speed (a speed that suits the aircraft by
  default), **fuel load** (% of the tanks)
- **Cheats**: invulnerable, unbreakable airframe (no wings torn off by overspeed or G), super mobility
  (engine power ×3–4, tighter turns), unlimited ammo, no reload, unlimited fuel, auto repair / rearm,
  passive targets, no collisions, expert / ace crew, **targets come back**; **in-mission keys**: switch
  invulnerability, instant reload and passive targets, repair, bring the targets back or go back to the start
  while you play (the game's Quick radio messages)
- **Custom sights** for ground vehicles: a sight of your UserSights folder or a `.blk` file you add
- **My overlay** (Windows, off until you turn it on; per aircraft or type if you like, for jets, propeller aircraft, tanks
  and ships): your own lines over the game
  in a click-through window (speed against the limit, altitude, fuel, any value the game sends), limits as speeds,
  percentages or both, placed on a picture of your screen with the game's HUD or your own screenshot; and beeps near
  your aircraft's breaking speeds with your thresholds and sounds or your own (mp3, wav...), on the sound output you
  choose, with a glow around the screen if you like, of the colour and size you want and flashing or not; they stop when you crash.
  Any line can have its own alert on any value (`fuel < 15 %`, `G > 9`) and show under conditions of its own, in up to
  four text blocks with columns, a frame and a background, with an outline and its own colours for names, values and
  units. A key mutes the alarms, another hides the overlay. A line can also show **the name of what you're in**, and **your
  stats**: kills per death, win rate and battles from *My battles*, and your kills and deaths in the battle under way. It reads the game's local data about your own
  vehicle and your own line of the battle log only, nothing is added to the game
- **Fighter HUD** (My overlay → HUD, Windows, off until you turn it on): a fighter's head-up display over the game, drawn
  from your own aircraft's numbers: heading, a pitch ladder that turns with the bank, the flight path marker, speed and altitude,
  vertical speed, G, Mach, angle of attack, throttle and fuel. Three styles, picked by the aircraft's nation: **American / NATO**
  (knots and feet, scrolling scales), **Russian** (km/h and metres in the corners, a moving horizon, angle of attack and G scales)
  and **Chinese**; every other nation gets the NATO style, and any aircraft can have another one. Its words are in the style's
  language, or in English, Russian or Chinese if you prefer. Turn the overlay on, then HUD → *Show it*: on jets and helicopters,
  or always. Units, colour, size, place and each part are yours. It has two places, one for the cockpit view and one for the
  outside view, and a key switches them: the game doesn't say which view you're in. A speed alarm lights its speed. It reads
  the game about 40 times a second and draws between readings, so the scales scroll smoothly. Where the game sends no pitch or
  bank (aircraft without an artificial horizon, such as the J-16), they're worked out from the climb, the angle of attack, the
  roll rate and the turn. Your own aircraft only, nothing about anybody else. Inspired by real HUDs, not a copy of one
- **Minimap** (My overlay → Minimap, Windows, off until you turn it on): the game's own map in the overlay, bigger than the
  game's and zoomable around you, with your aircraft, its trail, and what never moves: airfields, capture zones, bases, and
  the distance and heading to your nearest airfield. **Never another aircraft or vehicle**: the game's map data also lists the
  enemies it has spotted and your allies, and WTFTD drops them as soon as it reads them. Drag it on the picture of your
  screen like the text blocks, and resize it, or a text block, by the grip in its corner; it has its own opacity
- **Flight data** (Windows): live curves of what the game reports, in flight and in tanks and ships (speed, altitude, G, turn time, fuel use...),
  and a recorder: CSV logs for Excel, replayed in the app, with a **flight report** (top speed, best climb, best
  sustained turn, time to climb, fuel used) and an **export for Tacview**; saved views, and the curves as a picture
- **Test bench** (Windows): hard numbers on an aircraft or helicopter instead of the stat card. Pick a test, a loadout and the fuel: WTFTD
  writes a mission (air start, clear weather, an open map, nobody else) with the test in its description. You fly it, the app only reads
  the game's local data, and it keeps the valid stretches by itself and says why it refused the others: throttle, flaps, bank, height
  or speed not held, game paused. Top speed by altitude, climb rate and time to altitude, sustained turn (360° time, radius, G by speed),
  acceleration between two speeds, speed lost in a hard turn, slowest level flight. Results are saved by aircraft, loadout and game
  version, as curves you can lay over each other, next to the stat card's numbers. They show in *Compare* and in the vehicle panel, and a
  run opens in Flight data with its report and Tacview file. Every result states its fuel, loadout, altitude and modifications; a custom
  vehicle or a run with cheats is marked as not comparable and stays out of Compare
- **Cockpit window** (Windows): your aircraft's instruments as dials, or the fighter HUD filling it, in a window of their own for a
  second screen
- **Battle**: the game's chat and battle log, live, in their own tab, with a filter, and saved to a text file if you like
- **Economy**: what a vehicle costs and earns, for the game mode you choose: repair cost stock and with all upgrades, Silver Lions and
  Research Points rewards, free repairs, research and purchase cost. In the vehicle panel, as sort and range filters, in the comparison
  and along the research path, worked out as the game's own card does
- **Skins and sounds**: skins by vehicle, in the Vehicles menu and in each vehicle's panel, installed from a `.zip` or a folder you pick, and
  shown on the vehicle in the 3D view. Sound mods from a `.zip`, with a clear on/off switch. WTFTD removes only what it installed. It
  doesn't browse or download mods: they come from third parties, and the game warns when one stops working. The switch is off by default
- **My hangar**: what you own, marked by you in one click on a card, the tree or the panel, or by whole rank or nation; the vehicles of My
  battles are offered, never assumed. Named lineups per nation and game mode, with the rating they play at and can meet, by the official
  wiki's matchmaking rules, a warning on a vehicle far below the top, the total repair cost and rewards, and a test drive in one click.
  A research plan: goals in order, the research path minus what you own, with the RP and SL left
- **What changed**: a real comparison between two game versions, in the Vehicles menu. Each time the game data is rebuilt for a
  new version, WTFTD compares the old database with the new one: new and removed vehicles, battle ratings, performance, costs,
  ammunition, loadouts, Weapons tab items, maps, each with its old and new value. The official notes list the key changes, this
  shows everything that moved in the numbers. Filters by name, nation, vehicle type, game mode and your own vehicles; a vehicle
  opens its panel, a weapon its row, a map its map. It starts with the next game update, and keeps the last 30 patches
- **Challenges**: scored missions for the vehicle you picked: firing range, moving targets, waves of tanks or fighters, a course of gates,
  bombing, missile evasion, helicopter and naval ranges. A goal in the game's objectives, a timer, a real win or failure, three
  difficulties, no cheats; your best times stay in the tab, a result plays again in one click and a challenge can be shared. Results
  come in while WTFTD is open.
- **My battles**: your own history from the replays the game saves: date, map, game mode, vehicle, result, kills, deaths,
  assists, score, damage; totals and a summary by vehicle; filters by game mode, vehicle, map, dates and result. A vehicle
  opens its panel, a map opens that map. Your name and squadron tag stand in the top bar like an account name. Only your own line is read,
  with one exception: a teammate who shot you down is kept by name, on your PC only, from what the battle log and the replay
  say together (needs My overlay on). Enemies and everybody else are neither kept nor shown. A replay doesn't hold the result of a battle you left before the end, and the game keeps its last 100 autosaved
  replays (rename one in the game to keep it)
- **Feedback** button: write a few words and GitHub's bug or idea form opens filled in; you read it and send it with
  your own account
- **11 languages**: English, Français, Deutsch, Русский, Polski, Español, Português, Italiano, Čeština,
  简体中文, 日本語 — picked from your Windows language on first launch (or on the welcome screen), vehicle,
  weapon and map names follow the game's own translations. UI translations
  other than English were machine-assisted and may contain mistakes: corrections are welcome. Some of the newest texts
  are still in English in the languages other than French
- **Uninstall** from Settings: everything, or only some parts (custom vehicle files in the game, missions, the skins and sound mods
  WTFTD installed, cache, game database, your settings and library, the app itself); War Thunder itself is never touched: only
  what WTFTD added to it goes, and `config.blk` goes back as it was
- **Your library**: *My vehicles* (saved setups), *My maps* (scenario variants from the editor) and *My weapons*, each
  under its menu, and *My missions* (saved vehicle + map pairs and the missions created)
- **Share** a vehicle setup, a map or a mission with a friend: a short code to paste, or a `.wtftd` file — they
  import it (or drop the file on the window) and get the same thing: vehicle, loadout, ammo, map, editor
  changes, cheats. User missions are single-player, so each of you plays it on your own PC
- Dark / light theme, `.blk` preview, launch War Thunder; on Windows the app can start minimized, go to the notification
  area and close with the game

## Custom vehicles (on by default)

War Thunder only opens a user mission if you own its vehicle. With **custom vehicles** (Settings),
WTFTD uses the game's `userVehicles` mechanism (from the CDK, popularised by Ask3lad):

- the mission uses `unit_class:t="userVehicles/<host>"`, where `<host>` is a vehicle you own (US reserve
  vehicles by default: M2A4, PT-6, USS Litchfield — helicopters have no reserve, pick one you own).
  Aircraft get their own new file in `content/pkg_user` and need no host;
- WTFTD writes files that `include` the real vehicle and apply your **modifications**,
  **pylon-by-pylon loadouts** and **your own weapons** with `@override:` lines.

Rules: only new files are written (never a path that replaces a game file), every file is listed in
`user/cdk_manifest.json`, and **Settings → Remove custom vehicle files** deletes them (do it before
playing online if you want a clean install). One custom vehicle per type at a time: the last mission you
create defines it. This is not endorsed by Gaijin — use at your own risk.

## My weapons (custom weapons)

In the **Weapons** tab, **Modify** on a missile, bomb, rocket or torpedo makes your own version of it, kept in
**My weapons**; put it on a pylon from the vehicle panel (*Loadout → Custom pylons → a pylon → My weapons*).

- **Simple**: explosive, a **nuclear charge** (kilotons, like the game's nuclear bombs — it works on missiles
  too), motor thrust, burn time, top speed, max G, range, weight, each next to the game's value, with quick
  settings (×2, ×10, *Absurd*, *Nuclear 20 kt*). The explosion shown follows the new charge.
- **Advanced**: every value of the weapon's file — guidance, seeker, autopilot, fuse, damage, penetration… —
  block by block, searchable, each explained on hover.
- A weapon you edit later flies as it is now on every pylon that holds it; in game it keeps its own name.

How: WTFTD writes a new file per weapon (`content/pkg_user/gameData/Weapons/wtftd/…`) that `include`s the
game's own and overrides your values — never the game's file, so only your custom vehicles use it. Checked in
game (F-14B): 100 G turns, thrust ×5, 10 t of explosive, nuclear AIM-9M and Mk 84. The blast radius of
ordinary explosive grows as the cube root of the charge (×115 explosive ≈ ×5 radius): for a wide area, use a
nuclear charge.

## Map backgrounds & ground heights

The editor draws the level's tactical maps (full map + detailed ground-battle map) straight from the
game's texture packs (`content/base/res/*.dxp.bin`). They are Oodle-compressed: WTFTD uses the official
Oodle runtime (`oo2core_<n>_win64.dll` on Windows, `liboo2core*.dylib` on macOS, version 6+) that many other
games ship (Battlefield, Call of Duty, Cyberpunk…) — it is found automatically in your Steam / Epic / game
folders, or set it in **Settings**. On macOS few games ship one, so map backgrounds usually come from the
capture described below.
Ground heights come the same way from the level's heightmap (`levels/<map>.bin`, ground-battle maps);
older air maps have no heightmap and heights are estimated there, until you open them in 3D: their relief then
comes from the level's ground mesh. Without Oodle, a scenario's map is captured from the game (localhost:8111)
the first time you play it with WTFTD open.

## The 3D views

The 3D views read your own game on your PC: models from its `.grp` packs, textures from its `.dxp.bin` packs, materials
from `dynModelDesc.bin` and `riDesc.bin`, levels from `levels/<map>.bin`, assets from `aces.vromfs.bin`. The server only
finds them; the page decodes them, with its own decoder (`web/lzdecode.js`) instead of the Oodle runtime. Nothing is
stored, nothing can be exported, and no model or texture is in this project.

They need the game on this PC, whichever data source you chose, and Python 3.14+ (the packaged apps have it). The app
lists the game's models and textures in the background when it starts. On a map, the relief and the ground take a few
seconds, the objects of a big level about a minute, and you can work on the map meanwhile.

## FAQ

**Can I get banned for this?**
User missions are a normal feature of the game (*Single missions → User missions*), and WTFTD only uses
the game's own files and mechanisms. Custom vehicles add files to the game's `content` folder (the CDK
`userVehicles` mechanism modders use) — never replacing a game file, and only used by your offline missions.
There are no known bans for it, but it isn't endorsed by Gaijin: use it at your own risk, and remove the
custom vehicle files (**Settings → Remove custom vehicle files**) before playing online if you want a clean install.

WTFTD doesn't change the game's settings, with one exception you turn on yourself: **Use sound mods** adds the line `enable_mod:b=yes` to the
`sound` block of `config.blk`, the game's own way, and no other byte. It's off by default, refused while the game runs, and turning it
off or uninstalling puts the file back. Skins are the game's own feature and only you see them. Sound mods come from third parties: the
game warns when one stops working, can turn them off, and some game modes don't allow them.

The **In flight** tools only read what the game publishes on your own PC (`localhost:8111`): your aircraft's values, and
the chat and battle log you see in game. No enemy position is used. The overlay is a separate window: nothing is
injected and nothing touches the game. It isn't endorsed by Gaijin either. The **fighter HUD** is drawn in that same window
from your own aircraft's values: no target, no threat, no other aircraft. The **minimap** shows the game's own map, your
aircraft and the objects that never move; it drops every other unit, enemy or ally, as soon as it reads the map. Gaijin's
staff said overlays built on this local data are fine, and that enemy markers on one can count as an ESP overlay
([forum, 2024](https://forum.warthunder.com/t/tools-using-data-provided-on-port-8111/106664/197)): WTFTD never shows them.

The **Test bench** presses no key and sends no input of any kind: you fly, it reads the same local values, your own aircraft's only.

**My battles** only reads the replays on your PC, after the battle, and keeps your own line: no enemy's name, nobody's stats, and
the only other names it keeps are teammates who shot you down, on your PC, for you to report them in the game if you want. In
the overlay, the numbers of the battle under way count only the battle log lines that name you.

The **3D views** only read your own game's files on your PC to show them: nothing is copied, exported or sent. They aren't
endorsed by Gaijin either.

**Can I play my mission online or with friends?**
No: user missions are single-player. Send your friends the setup instead (**Share** → a code or a `.wtftd`
file); they import it and play the same mission on their PC.

**Why does Windows / macOS / my antivirus warn me about the app?**
The exe isn't code-signed yet, so SmartScreen shows *Windows protected your PC* (**More info → Run anyway**).
Apps packaged with PyInstaller are also sometimes flagged by mistake by antivirus software. The exe is built
by GitHub Actions from the public source code and its SHA-256 is listed in each release; you can also
[run WTFTD from source](#run-from-source). On macOS, Gatekeeper blocks unsigned apps the first time: open
**System Settings → Privacy & Security** and click **Open Anyway** next to WTFTD.

**Do I need to own the vehicle?**
No, with custom vehicles on (default). Without them, the game only opens user missions with vehicles you own.

**The game was updated, did WTFTD break?**
The game data rebuilds itself after each patch (checked every 3 hours and at start-up), or by hand with
**Settings → Update game data**. If a mission stops working, [report it](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/issues/new/choose)
with your setup's share code.

**Where are my files? How do I uninstall?**
Settings, setups and the game database: `%LOCALAPPDATA%\WTFTD` (Windows) or `~/Library/Application Support/WTFTD`
(macOS). Missions: `UserMissions` in the game folder (on macOS inside
`WarThunderLauncher.app/Contents/WarThunder.app/Contents/Resources/game`; **Open folder** in the app shows it).
To uninstall: **Settings → Uninstall WTFTD…** removes everything, or only the parts you tick (custom vehicle
files in the game, missions, cache, game database, your settings and library, the app itself).

**Does WTFTD collect anything?**
No: no account, no telemetry. It downloads the datamine (unless you read your installed game instead), wiki images
and this repository's release list, and sends nothing. The **Feedback** button only opens GitHub's form in your
browser: you read it and send it yourself. See [SECURITY.md](SECURITY.md).

## Run from source

Needs Python 3.10+ (no extra packages); reading the installed game instead of the datamine, and the 3D views, need
Python 3.14+.
Double-click **`start.bat`** (Windows) or **`start.command`** (macOS), or:

```bash
python -m wtftd
```

`python -m wtftd --browser` uses your default browser instead of an app window.

To build `dist\WTFTD-<version>.exe` yourself, run **`build_exe.bat`** on Windows (from a branch other than
`main`, the branch is added: `WTFTD-<version>-<branch>.exe`); for `dist/WTFTD.app` (and `dist/WTFTD-<version>.zip`),
run **`./build_app.sh`** on a Mac. Both install PyInstaller in `.cache/build-venv`. The app carries the Python it's
built with: use a full Python 3.14+ (reading the installed game needs it, the overlay needs its tkinter).
`build_exe.bat` refuses anything less, `build_app.sh` warns.

## Game data & automatic updates

The game database (`data/`, not in this repository) is generated on your PC from one of two sources, chosen on
the welcome screen and in **Settings → Game data** (`dataSource` in `user/settings.json`):

- **The installed game**: WTFTD reads `aces`, `char`, `lang` and `mis.vromfs.bin` (never writing to them) and unpacks
  what it needs into `.cache/gamefiles` (≈650 MB). No network, no Git, and always your game's version. Built from the
  same game version, the database is identical to the datamine's. Needs Python 3.14+ (the packaged apps have it).
- **The community datamine** ([gszabi99/War-Thunder-Datamine](https://github.com/gszabi99/War-Thunder-Datamine)):
  first download ≈1 GB into `.cache/datamine`, with your Git or an automatically fetched MinGit (Windows). On macOS,
  WTFTD uses Homebrew's Git or Apple's, and offers to install Apple's Command Line Tools if there is none. It works
  without the game, and it follows the datamine's latest build, which can be ahead of or behind your game.

Every 3 hours (and at start-up) WTFTD checks the version of its source and rebuilds after a patch. Switching source
rebuilds the database and keeps your setups, missions and settings; the datamine copy stays until you remove it in
Settings. Manual update: **Settings → Update game data**, or `python -m wtftd.builder` (`--game` for the installed
game).

## Translations

UI text lives in `web/locales/<code>.json`. The non-English files were machine-assisted: native speakers'
corrections are very welcome — see [CONTRIBUTING.md](CONTRIBUTING.md#translations).

## Known limits

- Stats come from the game's own stat cards (aircraft, armor) or are computed from the vehicle files (tank top
  speed from the gearbox, ±10 %). Armor-piercing penetration is the shell's own table when its file has one,
  else computed from the shell's file with the formulas the game uses (DeMarre, Lanz-Odermatt) and the speed left at
  each distance: within 1 mm of the official wiki on the shells compared.
- Without custom vehicles, aircraft use the official presets and the vehicle must be owned.
- For aircraft and ships, belts are matched to gun groups in order (best effort).
- SAM batteries (FSAF SAMP/T, NASAMS, Buk-M3...): the launchers are units of their own, so Unlimited ammo doesn't refill
  them, and the game limits each one to its real load (8 Aster-30 on the SAMP/T).
- A ground missile made of several parts (Aster-30, CAMM, Pantsir...) on an aircraft's pylon: in flight its parts sit inside
  each other, its fins stay folded and its booster stays on. The game only sets them right when a launcher fires it.
- A few scenarios pick their spawn / enemies from your vehicle's nation (Mozdok heli / UCAV, Denmark
  hydrobase); the editor shows their default branch.
- Missions and custom vehicles are local: they can't be played together online (custom battles / co-op use
  Gaijin's servers and the official vehicle files). Share the setup instead.
- "Non-playable units" come from the game files (AI, removed, unreleased) and may not load or behave oddly.
- My weapons: a weapon carried in a launcher of its own (pods, multiple racks) can't be modified yet, nor
  ground-launched missiles on the vehicles that carry them (on a pylon, they can). The Advanced values are the game's own and not all of them have
  been tried in game: change one thing at a time ([checklist](docs/ingame-checklist.md)).
- Research path: modules, crew training and the rank requirements are not counted.
- 3D views (prototypes): the paint is an approximation, the game's shaders being private. Tracks and wheels stay at rest and
  weapons don't show on pylons. On the map, the ground stays soft up close, the game's detail layers and grass not being
  drawn, and some levels' colours look mottled without them.
- Zones in 3D: a sphere's or a cylinder's size is read as its radius and a cylinder's height as centred on its point, which
  wasn't checked in game. A zone you move keeps its altitude, as in the mission.
- Assets: about 40 of the 500 have nothing to show on the 3D map and keep their marker, an asset's trees have no leaves, and
  a very large one (an airfield holds up to 5,000 objects) may slow the view. Their side, enemy by default, may make them
  targets in game.
- In flight: My overlay, the alarms, Flight data and the Cockpit window are Windows only. They were mostly flown on jets
  in test flights: helicopters, propeller aircraft, real battles and the other game languages are less tested
  ([checklist](docs/ingame-checklist.md)). Variable-sweep wings show the swept-back limit (the game doesn't send the wing
  position), and thrust/weight reads a little high when loaded (the game doesn't tell the weapons' mass).
- Fighter HUD: it isn't lined up with the game's horizon or its sights. The overlay can't know where the game's camera looks or how
  far it zooms, so the pitch ladder and the flight path marker are drawn at a fixed scale around the middle of the HUD. Its size
  brings them closer. Worked-out pitch and bank (J-16...) can lag a fast roll by a moment. There's no G alarm: the game gives no
  G limit per aircraft. Barely flown yet ([checklist](docs/ingame-checklist.md))
- Minimap: the map's picture shows when the game sends it as PNG (it can send a JPEG, then the marks show on a dark square).
  Tk only shrinks or grows a picture by whole numbers, so its size comes out near the one you set, not exactly. Barely
  flown yet, and not in Simulator battles ([checklist](docs/ingame-checklist.md))
- Test bench: helicopters get top speed, climb and acceleration only. Its stall speed is where level flight at idle gives way, not the
  wing's stall: the game's instructor can hold the nose up. It hasn't been flown in the game yet ([checklist](docs/ingame-checklist.md)).
- macOS support is new and less tested than Windows. The packaged app is built for Apple silicon; on an Intel
  Mac, [run from source](#run-from-source).

## Layout

```
start.bat / build_exe.bat   run from source / build WTFTD-<version>.exe (Windows)
start.command / build_app.sh run from source / build WTFTD.app (macOS)
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
  alarms.py / flightlog.py  in-flight values, alarms and overlay (Windows) / CSV flight logs, report, Tacview export
  hud.py                    the fighter HUD's three styles, drawn as shapes for the overlay and the cockpit window
  minimap.py                the minimap: the game's map, your aircraft and the fixed objects only
  battle.py                 the game's chat and battle log
  replays.py                My battles: the player's own results, from the game's replay files
  patches.py                What changed: the comparison of two game versions, kept in user/patches.json
  hangar.py                 My hangar: owned vehicles, lineups and research plan, kept in user/hangar.json
  bench.py                  Test bench: finds the valid stretches of a recorded test, results in user/bench.json
  mods.py                   Skins and sounds: untrusted archives, what WTFTD installed, config.blk's one line
  challenges.py             Challenges: what's where on each map, results in user/challenges.json
  waveout.py / tray.py      sound on the output you pick / the app window: its place, minimized, notification area (Windows)
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
[CHANGELOG.md](CHANGELOG.md). Security problem: [SECURITY.md](SECURITY.md).

## Support

WTFTD is free and always will be. If you enjoy it, you can support its development on
**[Ko-fi](https://ko-fi.com/stonewarp)** ❤ (also the heart button in the app).

## License

[MIT](LICENSE) — free to use, modify and share, keeping the copyright notice. `web/lzdecode.js` is a port of an MIT-licensed
decoder, with its notice. War Thunder and its data belong
to Gaijin Entertainment; WTFTD is a fan-made tool, not affiliated with or endorsed by Gaijin.
