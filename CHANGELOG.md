# Changelog

What changed in each version of WTFTD. Downloads: [Releases](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/releases)
(only the latest version is kept there; from 0.19.0 on, each version's code stays available through its git tag).
Versions follow `major.minor.patch`; "beta" until 1.0.

## 0.25.4 - 2026-11-05

- **WTFTD opens with War Thunder from Steam** (Windows): Settings gives the line to paste in Steam's launch options for
  War Thunder (*Copy*). Steam then starts WTFTD with the game's own command line: WTFTD starts the game, opens (or brings
  forward the one running), and waits for the game to close, so that Steam still counts your play time. WTFTD doesn't
  touch Steam's files: emptying the field in Steam stops it.
- **War Thunder can start with WTFTD** (Settings, App window, off by default; Windows): when WTFTD opens and the game isn't
  running yet. Started from Steam, the game is already on its way: it isn't launched twice.

- **What changed compares your game with the dev server**: *Compare with the dev server* downloads the community datamine
  (about 1 GB the first time) and builds its newest version apart, in its own process and its own folder, in a few
  minutes; it then shows as one more entry, *Dev server … ↔ your game …*, with the same tabs. Your game data and your
  patch history stay as they are. The datamine follows the dev server while one is open (2.60 against the game's 2.59 on
  2026-11-05); *Update* and *Remove* are next to it. With the datamine as the game data's source there is nothing to
  compare: it's offered when WTFTD reads your installed game.
- **The datamine as the source, ahead of your game, is said**: a banner tells that its vehicles and BRs are the dev
  server's, with a way to read the installed game instead.
- **Your game's data and the datamine's, both kept, switched at the top**: the Data button says where the data comes from
  (*your game*, *datamine*, or *dev server (datamine)*) and opens a menu with both, their version and date; one click
  switches at once, nothing rebuilt (the two folders swap places). The one missing is built apart on request, whichever
  source the app reads. In Settings, *Game data* is two boxes to tick, one or both: saving builds the one ticked apart and
  removes the one unticked (the one in use once the app has switched to the other); which one is in use is picked at the top.
- **The game's pill at the top says whether War Thunder runs** (green *Game running*, red *Game closed*, checked every 5 s)
  and, closed, launches it with a click: it replaces the *Launch War Thunder* button. The Data button shows its menu's
  arrow, and both stay on narrow screens, smaller, instead of going away.
- **The datamine isn't always the dev server's**: it follows the newest version there is. *Dev server* is only said when
  it's a whole version ahead of your game (2.60 against 2.59); a patch ahead is a patch you haven't installed, behind is no
  dev server open.
- **What changed**: a new vehicle shows its flag, type and BR even when only the dev server has it.
- **A dev server client as your game is recognized** (Gaijin's markers: a `matchingdevmode` file in its folder, or
  `curCircuit "dev"` in its `config.blk`, read only and that key alone): the Data button says *your game · dev server*, a
  patch built from it says *dev client*, and What changed doesn't offer to download what your game already is.

## 0.25.3 - 2026-11-05

- **BR filters go up to the highest BR in the game data** (15.0 now): they stopped at 14.3, written in the code. A
  filter set to the whole range stays whole when the top goes up.
- **What changed reads better on a big patch**: one row per vehicle, weapon or shell instead of one per value. Battle ratings
  show AB, RB and SB side by side, before, after and by how much (a mode that didn't move shows its BR, greyed), with how
  many vehicles went up and down; other changes are listed together under their vehicle. Groups count vehicles, not values,
  and are tabs instead of folding lists; the tabs and the table's headers stay in view while you scroll.
- **What changed compares every value of the missiles, bombs, rockets and torpedoes**, not only the Weapons tab's columns:
  drag, seeker field of view, fuse delay and arming distance, thrust and burn time of each stage, the IRCCM type, and every
  other number or switch of the weapon's file (how it looks and sounds left out). The best known have a name, the others
  show where they are in the file. WTFTD keeps them in `data/weapon_values.json` (3 MB) from this version on: the data is
  rebuilt once, and the next game patch is the first one they show for.
- **Starting WTFTD while it runs brings it to the front** instead of a second copy (a second server, a second overlay, and
  a page on another port that lost its settings). Started while it's closing, the new one waits for its port. On macOS,
  its page opens in the browser.
- **With automatic updates off, WTFTD says when the game was patched**: a banner offers *Update now*, so the BRs and
  everything else follow the game. It only looks at the installed game's files; with the datamine as the source, nothing
  is checked on the network without automatic updates.

## 0.25.2 — 2026-11-05

- **Minimap**: each kind of mark has its own size, from 50 to 400 % of the usual one: your aircraft, your allies, the
  airfields, and the zones and bases (My overlay → Minimap → *Size of the marks*).

## 0.25.1 — 2026-11-04

- **Minimap**: allied aircraft and allied AI units (vehicles and ships, the AI in an air battle) each have their own switch,
  both off by default. The game doesn't say who's an AI: they're told apart by what they are.
- **Minimap**: easier to read on the map. Each mark has a dark edge, aircraft and vehicles are bigger, and the map is
  darkened, 30 % by default (*Map darker*, from 0 to 80 %).
- **Minimap**: airfields show big enough to see: a runway is drawn at least a tenth of the minimap long, and thick, along its way.
- **Minimap**: the map's picture came sometimes never when WTFTD was started during a battle. It's read from memory now, no
  file another WTFTD still closing could hold, and asked again every 2 seconds until the game gives it.
- **My overlay's text reads on a light sky**: Windows draws it now (GDI+), with smooth letters and, when no outline is set, a
  soft dark halo round them; backgrounds are truly see-through instead of dotted. Tk drew it against a colour made
  transparent, which left ragged edges.

## 0.25.0 — 2026-11-04

- **Minimap** (My overlay → Minimap, Windows): the game's own map in the overlay, bigger than the game's and zoomable around
  you (×2, ×4, ×8), square or round, north up or your nose up. Your aircraft glides smoothly between the game's readings, with
  its trail if you want it; what never moves shows too (airfields, capture zones, bases), with the distance and heading to
  your nearest airfield. Your allies if you turn them on, told apart by their colour: the game doesn't say a unit's team.
  **Never an enemy**: the game's map data also lists the ones it has spotted, and they're dropped as soon as it's read. Off by
  default; its place, size and opacity are its own. Windows draws it (GDI+): the map turns with you and shows as the game
  sends it, JPEG or PNG.
- **My overlay**: the text blocks and the minimap are placed and resized on the picture of your screen, by dragging them and
  by the grip in their corner.
- **The app window reopens where you closed it** (Windows), at its size, maximized or not, on the same screen, at once rather
  than somewhere it then leaves. Edge lost it: it keeps an app window's place under its address, and the dots of 127.0.0.1
  broke that. WTFTD keeps it now, in `user/window.json`; a place on a screen that's gone is left for the default one.

## 0.24.0 — 2026-11-04

- **Fighter HUD** (My overlay → HUD, Windows): a fighter's head-up display over the game, from your own aircraft's numbers:
  heading, a pitch ladder that turns with the bank, the flight path marker, speed and altitude, vertical speed, G, Mach, angle of
  attack, throttle and fuel. Three styles picked by the aircraft's nation, **American / NATO** (knots and feet), **Russian** and
  **Chinese** (km/h and metres); the other nations get the NATO style, and any aircraft can have another one. Its words follow the
  style (English, Russian, Chinese) or the language you pick. **Off by default**: turn the overlay on, then HUD → *Show it*, on jets
  and helicopters or always. Units, colour, size, place and each part are yours. One place for the cockpit view, one for the
  outside view, and a key to switch them: the game doesn't say which view you're in. A speed alarm lights the speed. It reads the
  game about 40 times a second and draws between readings, so the scales scroll smoothly. Where the game sends no pitch or bank
  (the J-16 and other aircraft without an artificial horizon), they're worked out from the climb, the angle of attack, the roll
  rate and the turn: within a degree most of the time on a recorded F-15A flight. It isn't lined up with the game's horizon: the
  overlay can't know where the camera looks.
- **Cockpit window**: a HUD button fills it with the same HUD, for a second screen.

## 0.23.1 — 2026-11-01

- **Fuel time, consumption and range in the overlay** follow the throttle in seconds instead of half a minute: about 4 s when
  the afterburner lights, 9 to 18 s when it's cut. They also hold steadier in cruise.
- **Hide the overlay while the aircraft is unknown** (My overlay, Behaviour): nothing shows until the aircraft is recognised.
  Off by default. Set it on the overlay for all aircraft, the one an unknown aircraft uses; your own lines' alerts still sound.

## 0.23.0 — 2026-11-01

- **Challenges** (My missions menu): scored missions for the picked vehicle, each with a goal in the game's objectives, a timer
  and a real win or failure. Tanks: firing range at known distances, moving targets, waves. Aircraft: a course of gates against
  the clock, bombing, waves of fighters, missile evasion. Helicopters and ships: their own range. Pick a map and a difficulty,
  create the mission as usual, no cheats. Your best time by challenge, vehicle and difficulty comes back in the tab while WTFTD
  is open, from the game's local data on your own mission, exact when the game saved a replay. A result creates the mission again
  in one click, a challenge goes in a share code, and finished ones show in My battles with the test missions. Nothing of it
  has been played yet: the in-game checklist has the list. The game's race triggers are left out: only its multiplayer missions
  use them, so the gates are its single missions' waypoints.
- **My battles** (In flight menu): your own battle history, read from the replays the game saves on your PC. Date, map, game
  mode, vehicle, result, time played, kills, deaths, assists, score and damage, newest first; totals (battles, win rate, kills
  per death, time played) and a summary by vehicle for what the filters show. Filter by game mode, vehicle, map, dates and
  result. A vehicle opens its panel, a map opens that map. Test drives and missions stay hidden behind a switch. Only your own
  line is read out of a replay: nobody else's name or numbers are kept or shown. Replays are read once, then the page opens
  at once. Needs **Autosave Replays** in the game's options; the game keeps the last 100, so older battles leave the list.
- **Your stats in the overlay** (My overlay, values *My stats*): kills per death, win rate, battles, kills and deaths from My
  battles, and kills, deaths and kills per death of the battle under way, counted from the battle log lines that name you. They
  go in any line. Only your own: nobody else's numbers. Data schema 31 (the battle log's verbs in every language): the data is
  rebuilt once.
- **Crash detection**: your name now comes from your replays, so a break-up in the air stops the alarms the first time too, not
  only after a first crash has shown which name is yours. It also stands in the top bar, like an account name, after your
  squadron's tag if you have one: a click opens My battles.
- **Teamkills** (My battles): the teammates who shot you down, how many times, when and where. The game's log doesn't mark a
  teamkill: it says who shot you down, then your replay says which team they were on. So it counts from now on, not on past
  battles, and takes My overlay on and Autosave Replays. This is the only other players' name WTFTD keeps: enemies are dropped,
  and it stays on your PC.
- **What changed** (Vehicles menu): a real comparison between two game versions. Each time the game data is rebuilt for a new
  version, WTFTD compares the old database with the new one and keeps the result, because old versions can't be rebuilt: the
  official notes list the key changes, this shows everything that moved in the numbers. One patch at a time, newest first, with
  counts on top, then new and removed vehicles, battle ratings, performance, costs, ammunition, loadouts and weapons, the items of
  the Weapons tab, maps and scenarios. Each row gives the old and the new value, in colour only where better is really known.
  Filter by name, nation, vehicle type, game mode for battle ratings, and your favorites and saved vehicles. A vehicle opens its
  panel, a weapon its row in the Weapons tab, a map its map. The update banner links to it with the number of changes, the sub-tab
  counts what you haven't seen, and a vehicle's panel says so when it changed in the latest patch. It starts with the next game
  update: nothing can be compared before. The last 30 patches stay in `user/patches.json`, so a rebuild or removing the cache
  leaves them; *Your settings and library* in Uninstall removes them. Going back to an older version after changing the data
  source is marked as such, not shown as a patch.
- **Economy**: what a vehicle costs and earns, in the screens you already use. The vehicle panel has an Economy block: research and
  purchase cost, repair cost stock and with all upgrades, Silver Lions and Research Points rewards, free repairs, for the AB / RB /
  SB mode you choose there or in the filters. The numbers sort and filter like the other stats, stand in the comparison with the
  best one marked, and What changed lists them. The research path shows each vehicle's Research Points reward. They are worked out as
  the game's own card does, rounding included, and match the official wiki on the 26 vehicles checked. A premium vehicle's reward
  includes its premium bonus: the wiki's 2 x 172 % is 344 % here. No estimate of battles to research a vehicle, and no repair bill in My
  battles: a replay doesn't say what was earned or paid. Data schema 33: the data is rebuilt once.
- **My hangar** (Vehicles menu): what you own, your lineups and what to research next. The game doesn't tell the app what you own, so
  you mark it: one click on a card, in the tree or in the vehicle panel, or a whole rank or nation at once in a table of what you own,
  with Undo. Vehicles found in My battles are offered, never marked for you. An *Owned only* filter joins the others, and the tree shows
  what's yours at a glance. **Lineups**, named, per nation and game mode, from what you own or from any vehicle if you're planning: the
  rating they play at, what they can meet, by the official wiki's Matchmaking page (the highest vehicle, the Air Arcade average, the
  aircraft chosen in Air Realistic, the naval limit, and Simulator's own lists), a warning on a vehicle 1.0 or more below the top, as the
  game warns in a squad, and the total repair cost and rewards. A vehicle opens its panel, and Test drive creates its mission. **Research
  plan**: goals in order, with the research path minus what you own, and the RP and SL left. No estimate of battles: a replay doesn't
  say what was earned. Custom vehicles in Settings list what you own first and warn about a host that isn't, and What changed's *my
  vehicles* filter includes the hangar. It's kept in `user/hangar.json`, and goes with *Your settings and library* in Uninstall. A file
  nothing can read is kept aside as `user/hangar.bad.json`, and the app says so.
- **Skins and sounds** (Vehicles menu): your skins by vehicle, in a page and in each vehicle's panel, installed from a `.zip` or a folder you
  pick, removed, and shown on the vehicle in the 3D view from their `.tga` or `.dds`. WTFTD works out the vehicle from the skin's files
  and asks when it can't tell. Sound mods install from a `.zip`, with a clear on/off switch, off by default. Turning it on adds one
  line to the game's `config.blk`, `enable_mod:b=yes`, and no other byte; a copy of the file stays in `user/`, turning it off puts the file
  back, and it's refused while the game runs, which may write the file as it exits. This is the one setting of the game WTFTD changes,
  only on request, and the README and `SECURITY.md` say so. WTFTD doesn't browse or download mods. Archives are untrusted: paths that leave
  their folder, links, executables and scripts, oversized or over-compressed files refuse the whole archive, and nothing is written
  outside `UserSkins` and `sound/mod`. What you installed by hand is shown and never touched. Uninstall has a part for this.
- **Vehicle name in the overlay** (My overlay, value *Vehicle name*): a line can show what you're in, aircraft, helicopter, tank
  or ship, by the name the app gives it, in your language. A custom vehicle shows its real vehicle's name. What the app can't
  recognise shows the id the game gives. It's your choice: the default lines don't have it.
- **No more sound for an unknown aircraft**: the overlay still says so, in words, and only real alarms make a sound.
- **Glow colour** (My overlay, Glow): the glow around the screen can have its own colour, for all aircraft or per aircraft or
  type. Until you pick one it stays the alert colour, so nothing changes.
- **Test bench** (In flight menu, Windows): hard numbers instead of the stat card, measured in the game. Pick an aircraft or helicopter,
  from the page or a button in its panel, a loadout and the fuel, then a test: top speed, climb, sustained turn, acceleration, hard turn,
  stall speed. WTFTD writes a user mission for it (air start at the right height and speed, clear weather, an open map, nobody else), with the
  test in its description. You fly: no key or input of any kind goes to the game, the app only reads its local data. While you fly the page
  says what to do and what holds (throttle, gear, flaps, bank, height, speed); when you leave, it finds the valid stretches of the recording by
  itself and says why it refused the rest. Results are saved by aircraft, loadout and game version in `user/bench.json`, as curves in the look of
  Flight data: top speed by altitude, climb by altitude, turn time by speed, several runs laid over each other, with the stat card next
  to them. *Compare* gets measured rows, the vehicle panel a quiet Measured block, and a run opens in Flight data with its report and Tacview
  file. Each result states its fuel, loadout, altitude and modifications; a custom vehicle or a run with cheats is marked as not comparable
  and stays out of Compare. Helicopters get top speed, climb and acceleration. Not flown in the game yet: see the checklist.
- **Translations**: the research path, research cost and purchase cost are now translated in every language.
- **Motor burn** (Weapons): read from the motor format the game now uses for more and more missiles, such as the R-60 from 2.60 on,
  which had lost the value. Data schema 32: the data is rebuilt once.

## 0.22.1 — 2026-11-01

- **Security**: a shared map or mission could run a script in the app when opened in the scenario editor. Its values are now
  checked, and the page only runs the app's own scripts. **Update, and don't import a share from someone you don't trust in an
  older version.**
- **Security**: the game folder and the Oodle runtime can no longer be on a network path. A mapped drive letter still works.
- A shared map's side, count, route speed and BR are read as what they should be, and pylon counts too.

## 0.22.0 — 2026-11-01

- **Ground missiles**: SPAA missiles were missing in missions. SAM launchers and ATGMs now start on a named missile set, as
  in the game's own missions, not on the default set the game hides (Crotale NG, Strela-10, Chaparral...). A missile beside
  the gun gets a slot of its own, full (Gepard 1A2, BMP-2...). Rebuilds the data once.
- **SAM batteries** (FSAF SAMP/T, NASAMS, Buk-M3, IRIS-T SLM, Sky Sabre...): the radar vehicle holds its launchers' missiles,
  as in the game: 16 Aster-30 on the SAMP/T (checked in game). In game, deploy a launcher with the *Deploy launcher* key to
  fire. Unlimited ammo doesn't reach the launchers: the battery has its 16 missiles (see Known limits).
- **Pantsir-SM**: its missiles are read at last (they sit on pylons).
- **Glow around the screen** (My overlay, off until you turn it on): during an alarm, a soft glow in the alert colour
  around the screen, on top of the beeps. Choose its size and make it flash, at the speed you like. Clicks go through it,
  and it never takes the focus from the game.
- **Alerts on any value** (My overlay → a line's Options): a line can have its own alert (`fuel % < 15`, `G > 9`, `AoA > 20`...)
  that turns it to the alert colour, beeps and lights the glow, and can show only under a condition of its own, or hide when
  a value is `N/A`. Lines can flash with their alarm.
- **Text blocks**: up to four blocks of lines at different places of the screen, each at its own size.
- **Text**: italic, line spacing, an outline in the colour you choose.
- **Sounds**: a volume, your own `.wav` sounds for each alarm and alert, a key to mute the alarms, beeps only when the game
  is in front, no beeps with the engines stopped.
- A key to hold to hide the overlay, and how often the game is read and the curves and logs are written.
- **Your own alarm sound**: each alarm and alert has *Choose a file…*: mp3, wav, ogg and what else your browser reads,
  kept as a short .wav (15 s at most). And a **sound output** of your choice (Alarms → Sounds).
- **Colours by part**: names, values and units in their own colours, for the whole overlay or a line.
- **Several conditions** (AND / OR) on a line's showing and its alert.
- **Text blocks** (a tab of their own): columns, a frame, a background.
- **Overlays for jets and propeller aircraft**, after the aircraft's own and its type's.
- **Gear and flaps %** can show even when they are retracted. The alarms still only follow them out.
- My overlay is laid out as tabs of cards under the preview: Lines, Blocks, Look, Alarms, Behaviour.
- **Every weapon on your pylons** (Loadout → non-standard weapons): the missiles and rockets of ground vehicles and ships
  (S-300, Pantsir, Aster, Smerch...), rewritten as an aircraft's in a file of their own, and every gun of the game. Aircraft
  without pylons get one, at their gun's muzzle. Data schema 27. A missile with two models is folded on the pylon and
  unfolded in flight. One whose model holds its launch tube (Aster-30, IRIS-T SLM, CAMM...) hangs without tube and covers
  (Aster-30 checked in game, the others not). Not checked in game yet for the rest.
- **Build your aircraft** (vehicle panel → Modifications): swap its radar and warning receivers for any others of the game,
  add those it lacks, give it another aircraft's engine (jets from jets, propellers from propellers), and switch its avionics:
  laser designator, point of interest, helmet sight, CCIP and CCRP. Not checked in game yet.
- **Tanks and ships**: replace a gun with any other ground or ship weapon (Modifications). Not checked in game yet.
- **Voices** (Modifications): the crew's language through the mission's country, the cockpit's warning voice (Betty, Rita,
  Xiao906) and the six special crew voices. WTFTD doesn't touch the game's sound options. Not checked in game yet.
- **My weapons**: the missiles of ground vehicles and ships can be modified too, on a pylon.
- **Scenario editor**: every non-playable unit can be added, such as the S-300 launcher and its radars, and 198 units the
  game leaves unnamed: carriers, trains, transports. A new *Objects* tab places AA guns, trucks, buildings, radars and infantry.
  Not checked in game yet.
- **3D view** (prototype): the cube button of a vehicle, and *View in 3D* on a weapon, show its model with its textures and
  paint, read from your own game files: nothing is stored, nothing can be exported. Needs your game on this PC, and Python
  3.14 for the materials (the app has it). The app lists the game's models and textures in the background when it starts, so
  the first view has nothing to wait for; the model shows at once, and its textures join it. The paint is an approximation,
  the game's shaders being private. Data schema 29.
- **The real map in 3D** (prototype): the scenario editor still opens on the flat map, and its 2D / 3D switch turns it into the
  level from your own game files: its relief over the whole level, air maps included, its ground in its land classes' colours,
  water and placed objects (buildings, bridges, walls, trees with their leaves), with your units as their real models. Add,
  select and move them as on the flat map; right drag turns the view, the wheel zooms. Close up the ground stays soft, the
  game's detail layers and grass not being drawn, and some levels' colour maps look mottled without them. The zones stand as
  volumes, their height read from the mission, their outline laid on the ground.
- **Scenario editor**: a battle area is drawn at its real size on the flat map: it showed twice too wide. A zone is now clicked
  anywhere in its real shape. Z Q S D on a French keyboard, W A S D on an English one, move the map, in 2D and in 3D.
- **Turning what you place**: a selected vehicle or asset has an arrow to drag, in 2D and in 3D, and a heading slider; several
  selected turn together. The scenario's own vehicles keep the heading you give them.
- **Assets on the map**: *Add asset* places the game's own set pieces, the 500-odd object groups its missions use: crates,
  barricades, trenches, tents, camps, airfields. They stand on the 3D map, and rebuild the data once. Not checked in game yet.
- **Positions of a weapon** in the 3D view: stowed, deployed or in its container when the game has them, and its parts
  (booster, fins, caps) can be left out one by one.
- **Routes in the scenario editor**: pick *Route* as a unit's movement and draw its way on the map, with a speed and what it
  does at the end. Select several units and they share it: a convoy that keeps the gaps of its start. Not checked in game yet.
- **Waves of enemies**: give enemies a wave number. The first wave is there at the start, each next one comes when the one
  before is destroyed, and the last can lead back to the first. *Targets come back* leaves them alone, since a wave only ends
  when it is destroyed. Not checked in game yet.
- **Tanks and ships in flight tools**: curves, logs and an overlay of their own (*All ground vehicles*, *All ships*). Not checked
  in game yet.
- **Weapons**: the search also finds a weapon by what carries it (`S-300` finds the 5V55R), and goes to its category.
- **Flight data**: save the values you picked as a named view, and the curves as a picture.
- **Battle**: save the chat and the battle log to a text file (`user/logs`), off by default.
- **App window** (Settings, Windows): start minimized, minimize to the notification area, close WTFTD when the game closes.
  Data schema 25.
- The overlay no longer shows up now and then in the menus: in the hangar the game reports 0 or 1 km/h for the aircraft
  on show, which looked like a flight.

## 0.21.0 — 2026-10-31

- **Feedback button** (top bar): write a few words, and GitHub opens with the bug or idea form filled in (WTFTD and game
  versions, vehicle, setup code). You read it and send it with your own account: WTFTD posts nothing by itself.
- **Penetration by distance** (vehicle panel → Ammunition): a curve for every shell of the gun, with the values at 10,
  100, 500, 1000 and 2000 m: armor-piercing of all kinds, HE, HEAT, HESH and guided missiles. From the shell's own table
  when its file has one, else computed from its speed, mass and drag with the game's formulas (marked ≈): within 1 mm
  of the official wiki on the shells compared.
- **APCR, APDS and steel darts** now have a penetration, computed like the game does: in the ammunition list, the
  curves, *Best AP penetration*, the sort and the comparison. Armor-piercing values are now the game's at 10 m, not at
  the muzzle. Aircraft and machine gun belts show what their best round pierces, fragments included.
- **Pitch** now reads positive nose up in the overlay, the curves and the logs: the game sends it the other way round.
  Logs recorded before keep the old sign.
- **Research and purchase cost** (vehicle panel, sort, filter and comparison): the game's own RP and SL cost of each
  vehicle, and a *Research path* that adds them up along the line, from the first vehicle to the one you picked.
  Modules, crew training and the rank requirements are not counted.
- **Bombing a target** (Weapons → bombs, guided bombs, air-to-surface, rockets): pick a base that doesn't come back, a
  base that respawns or an airfield, arcade or not, and the battle's BR: the target's HP from the game's mission
  templates, and two new columns: what one weapon takes off it, from its TNT equivalent and the game's explosion table,
  and how many it takes. That table isn't proportional, so several small bombs beat one big one, as in game. Napalm and
  incendiary bombs hurt a zone through their own multiplier and get no count. Data schema 24.
- **Flight report** (In flight → Flight data, with a recorded log picked): top speed, Mach, altitude, best climb rate,
  highest G, best turn rate, best **sustained turn** (level, speed steady, over 1.5 G, 3 s or more), time to climb to
  1 000 … 11 000 m and fuel used, each with the speed and altitude it happened at. Fly a test, record it, read it.
- **Export for Tacview** (Flight data, a recorded log picked): your flight as a Tacview `.txt.acmi` file, your own
  aircraft only. Logs now also keep your place on the map (the game's own map marker: position and heading); logs
  recorded before have none and say so. The roll isn't exported (the game's sign isn't checked); the pitch comes from
  the climb angle plus the angle of attack.
- **Cockpit window** (Flight data → Cockpit window): your aircraft's speed, altitude, climb rate and G as dials, plus
  Mach, angle of attack, heading, throttle, fuel, gear and flaps, updated four times a second. For a second screen.
  It shows what the game reports about your own aircraft, nothing else.
- **A shorter top menu**: Vehicles, Maps, Weapons, My missions and In flight. Your own vehicles, maps and weapons are
  now sub-tabs of those menus, and My overlay, Flight data and Battle sit under In flight.
- **My overlay** (In flight, Windows, off until you turn it on there): while you fly, WTFTD beeps near your aircraft's
  breaking speeds and shows what you choose in a small click-through window over the game, hidden in the hangar and
  when the game isn't in front. By default: your speed against each limit, `IAS 1284 / 1540 km/h`, Mach, and gear and
  flaps when they are out.
  - Everything is yours: write the lines (`ALT {alt} m  {margin} km/h left`, 30 values one click away, and any field
    the game sends), when each one shows, its size and colour, which alarm turns it to the alert colour.
  - Limits as speeds, as percentages, or both, in one click.
  - Drag the text on a to-scale picture of your screen, with an outline of the game's HUD or your own screenshot (pick
    it or paste it with Ctrl+V), or show it on your real screen with sample values. Font, size, colours, opacity, a
    show / hide key.
  - Each alarm (airframe, gear, flaps): on or off, threshold (93 %, 90 %, 90 % by default), pitch, length, with a Test
    button, and how often they repeat.
  - Speeds come from the game's `/state`. The aircraft comes from the mission WTFTD generated, then from the game's
    `/indicators`, and as a fallback when that one is blank (seen on 2.59 until a game restart) from its fuel capacity,
    engines and the model the game saved (read only): in doubt the overlay says `AIRCRAFT UNKNOWN` and stays silent,
    it never guesses. Variable-sweep wings: the limit shown is the swept-back one (the game doesn't send the wing
    position). Unbreakable airframe: the overlay says so, no alarm.
- **Flight data** (In flight, Windows): what the game reports in flight, as live curves, one strip per value on a shared
  time axis, with the value under the mouse. **Record** a flight to a CSV file that opens in Excel (`user/logs`, also
  from a key in flight), replay it here, delete it.
- New values for the overlay, the curves and the logs: turn time, rate and radius, horizontal speed, acceleration,
  specific excess power, total thrust, thrust/weight, fuel use, fuel time and range left, pitch, bank. The mass leaves
  the weapons out (the game doesn't tell it), so thrust/weight reads a little high when loaded. Pitch, bank and heading
  come from `/indicators`: `N/A` while it's blank. A `REC` line shows while recording.
- **Battle** (In flight): the game's chat and battle log, live, in their own tab: filter, text size. WTFTD only reads
  them.
- **Overlays per aircraft or type** (My overlay): an aircraft's own overlay comes first, then its type's (fighters,
  attackers, bombers, helicopters), then the one for all aircraft, with their own lines, look and alarms. The right
  one loads by itself when the aircraft is recognised.
- **Crash detection**: when the aircraft hits the ground the alarms stop at once, and the overlay can hide too (My
  overlay → Hide the overlay after a crash). It watches what the game's numbers do at an impact: every engine's RPM and
  throttle at 0 from one reading to the next, on the ground or in water. Landings, belly landings and 11 G pulls don't
  trigger it. An aircraft breaking up in the air keeps its engines running: there the battle log tells, once your first
  impact of the session has shown which name is yours, so another player's crash never silences your alarms.
- **Breaking limits** in the vehicle panel of aircraft and helicopters (speed, Mach, gear, flaps, variable sweep), and a
  sheet of the aircraft you're flying in Flight data.
- Tornado and some F-16 AM (21 aircraft) lost their mass, fuel and thrust stats, and "Unbreakable airframe" did
  nothing on them: their flight model's path is spelled differently in the game files.
- **Read the installed game instead of downloading the datamine**: on the welcome screen and in Settings → Game data,
  choose where the game data comes from. *Read my installed game* needs no download, no Git and no network: WTFTD
  unpacks the game's own files on your PC (≈650 MB, about 3 minutes), stays at your game's exact version, and rebuilds
  by itself after a game patch. The community datamine stays available (it works without the game), and stays the
  source of existing installs unless you change it. Built from the same game version, both give the same database.
- Switching source rebuilds the database and keeps your setups, missions and settings. The datamine copy stays until
  you remove it (Settings → Game data). If the game is updating or a file is damaged, the update stops with a message
  and the data you have keeps working.
- The apps are now built with Python 3.14. From source, reading the game needs Python 3.14 or newer; on an older one
  the datamine works as before and the option is shown disabled.

## 0.20.0 — 2026-10-13

- **In-mission keys** (Cheats → In-mission keys): switch options while you play with the game's *Quick radio
  messages* (give them keys in the game's controls): #1 invulnerable, #2 no reload, #3 passive targets, #4 repair,
  #5 targets back, #6 back to the start, #9 shows the keys. The hints in game are in the app's language.
- **Targets come back** (Cheats): destroyed targets of the scenario and the ones added in the map editor are
  repaired and brought back every 20 s.
- **Ground battle maps** (Maps): the game's Domination layouts (79 layouts on 55 maps), from either side's spawn,
  for ground vehicles, helicopters and aircraft (air start over the spawn); the capture zones A / B / C, the other
  side's spawn and the battle area are drawn in the editor. A solo sandbox: no AI, score or capture.
- **Custom sights** (ground vehicles, Ammunition step): pick a sight of your UserSights folder or add a `.blk`
  sight file; WTFTD copies it as `wtftd` for the vehicle the game loads (the custom vehicle's host, and the
  vehicle itself): pick `wtftd` once in the game's sight settings. Settings → Remove custom vehicle files removes
  those copies too. WTFTD never changes the game's settings files.
- **Armor-piercing penetration**: shells show their penetration in the Ammunition step (AP / APCBC / APHE /
  APFSDS), and a new stat *Best AP penetration* (sortable, filterable, in the comparison): the game's own table
  when the shell has one, else the formulas the game uses (DeMarre for full-calibre shells, Lanz-Odermatt for
  long rods), about ±5 %. APCR / APDS without a table are not shown.
- **Drones**: the game's FPV / recon drones are listed (non-playable units) with a *Drone* type.
- **Downloads named after the version**: `WTFTD-0.20.0.exe` (Windows) and `WTFTD-0.20.0.zip` (macOS), each with
  its `.sha256`. Built from a branch other than `main`, the branch is added to the name.
- Air starts on the bare and battle maps use a speed that suits the aircraft: drones 100 km/h, helicopters 150,
  propeller planes 450, early jets (rank V and below) 700, later jets 1000.

## 0.19.0 — 2026-10-09

- **My weapons** (new tab, right of Weapons): make your own versions of the game's missiles, bombs, rockets and
  torpedoes from the Weapons tab (**Modify** on a row) and hang them on your pylons (vehicle panel → Loadout →
  Custom pylons → a pylon → My weapons), on your aircraft or on AI aircraft. **Simple**: explosive, a nuclear
  charge (kilotons, like the game's nuclear bombs: it works on missiles too), motor thrust, burn time, top speed,
  max G, range, weight, with quick settings (×2, ×10, Absurd, Nuclear 20 kt). **Advanced**: every value of the
  weapon's file (guidance, seeker, autopilot, fuse, damage…), searchable, block by block, each explained on hover.
  A weapon edited later flies as it is now on every pylon that holds it. In game it keeps its own name.
  Checked in game (F-14B): 100 G turns, thrust ×5, 500 kg / 10 t explosive, nuclear AIM-9M and Mk 84.
- The Weapons tab: every air-launched missile, bomb, rocket and torpedo can be modified (747 of 866; the
  others are fired from the ground), also when its name differs from its file's (PL-5EII…).
- Header: stays on one line with the new tab on smaller screens and in every language (the subtitle, the
  status pills and the Launch button's text make room).
- Fix: non-standard pylon weapons fired two at a time (every pylon with that trigger at once); they now fire one
  pylon at a time, as the game's own presets (`separate`).

## 0.18.0 — 2026-10-09

- **First launch asks first**: nothing is downloaded before you click *Accept and download*. The welcome screen
  says where WTFTD keeps its files (its own folder, with the path; in the game folder only your missions and the
  custom vehicle files), what it downloads and from where (the community War Thunder datamine on GitHub, portable
  Git if missing, pictures from War Thunder's encyclopedia and wiki, the check for a newer WTFTD), and that
  Settings → Uninstall removes it all. Game-data updates after patches still run on their own.
- Fix: on a first launch the app window could show "127.0.0.1 refused to connect": Edge handed its window to
  another of its processes, and WTFTD took that for the window closing and quit. It now serves as long as its
  page is open (the page pings it, and says goodbye when it closes).
- Faster pictures: the Maps tab and the map window show a small copy of each map (the 4096 px ones weighed
  10 MB each, 64 MB once shown), two at a time, so a first visit (each map is decoded once, 1–8 s) no longer
  holds up the other pictures, such as the Weapons tab's icons (5 s → at once). Those icons are also fetched in
  the background as soon as the game data is there, and again after an update.
- Uninstall: a spinner shows while the files are removed (it can take a minute), so WTFTD doesn't look frozen.
- Uninstall: WTFTD closes its window and quits, then removes the app (and its folder) once, a few seconds
  later, in the background: no console window, no retries left running (they removed an exe rebuilt meanwhile).

## 0.17.0 — 2026-10-09

- **Uninstall** (Settings): remove what WTFTD put on this PC, everything or part by part: the custom vehicle
  files it added to the game, the missions it created, the cache (datamine copy, pictures, maps), the game
  database, your settings and library, and the app itself (WTFTD.exe / WTFTD.app, once it has closed). War
  Thunder itself is never touched. Each part shows its size; a second click confirms. On macOS, WTFTD.app opened
  straight from Downloads runs from a temporary copy: it asks you to move it to the Trash yourself.

## 0.16.0 — 2026-10-09

- Map editor: a click on the map itself clears the selection (a drag still moves the map).
- `start.bat` (running from source) no longer keeps a console window open: it starts WTFTD with `pythonw` and
  closes; with options (`--browser`, `--port`…) it keeps the console as before. Messages go to `.cache/wtftd.log`.
- The vehicle + map bar keeps its size when a vehicle or a map is picked.
- **Map editor**: fills the window (4K too), its side panel no longer scrolls sideways. The vehicle picker shows
  every vehicle of the kind, by BR, with the Vehicles menu's filters: nations, rank, battle rating
  (its AB / RB / SB mode), type.
- Fix: an AI unit's Configure from the Maps window left that window over the vehicle panel; it now steps aside and
  comes back when the editor closes.
- New cheat **Super mobility** (custom vehicles): ground vehicles get engine power ×4, top speed ×2, brakes ×3;
  aircraft roll, pitch and turn much faster (less inertia, bigger and quicker controls, more lift), half the drag,
  engine power / thrust ×3 and 40 % less weight. A value set under Modifications wins.
- Fix: the **Thrust** modification of jets did nothing (the game takes their maximum thrust from the flight
  model's thrust table, which it now scales).
- **Invulnerable**: AI aircraft now attack you too (it used the game's spawn protection, which they respect).
- New cheat **Unbreakable airframe** (aircraft, helicopters, custom vehicles): no wings torn off by overspeed or g
  (Mach limit included), gear, flaps and canopy don't break.
- **Mission description** (mission options): shown under the mission in the game's list (it showed
  "missions//objective").
- **Map editor**: the vehicles the scenario brings into its zones show as markers (triangle: aircraft,
  square: ground, diamond: ships, dashed white outline) at every zoom; zone outlines are off by default
  (Zones button), drawn at their real size (too small to see: left out), and hiding them keeps those markers.
  Clicking a unit in the list brings it into view and highlights it alone (a unit the scenario places in game:
  the zones it may appear in). **Vehicles by BR**: every enemy, ally or selected unit gets a vehicle of its own
  kind (fighter, bomber, tank, SPAA…) from the research trees at the BR closest to your vehicle's or to a BR
  you choose, from the nations you tick (one, several or all, in turn). With your vehicle's BR, those units **follow your vehicle**: take
  another one and they get vehicles near its BR (when the editor opens and when the mission is created); a
  vehicle picked by hand for a unit stops it following.
- **Template units can change vehicle**: the units a scenario takes from a game template it imports directly (the
  targets of the test flights) get the vehicle picker, a loadout and Vehicles by BR. The mission then declares
  that template's units itself; the templates' scripts stay imported as the game wrote them (the data keeps the
  templates: it is rebuilt once). Units of nested templates (the bases' AA) keep their vehicle.
- **Vehicles by BR → Fire: Attacks**: the units it sets also fire at you (test flight and test drive targets are
  passive). Template units set to Attacks in the editor now stay so: the templates' scripts made them passive
  again when they respawned them, WTFTD sets them back every 3 s.
- **Vehicles by BR** only picks vehicles that fire on their own (not a SAM battery's radar or launcher: AI ones
  don't fire); with Fire: Attacks, enemy aircraft also hunt you. Template units hunting you are told again every
  10 s (their scripts bring them in later, on a route of their own).
- **Hunts me**: the order is given again every 10 s for every unit (at mission start you may not be there yet: on
  test flights the game's scripts spawn you a moment later and the order was lost).
- **Test flights**: the targets and airfield follow your vehicle's rank (high from rank V), as when the game starts
  them from the hangar (a user mission kept the low ones: a dirt strip).
- The map settings' **Training targets** (scenario / my BR / a BR) are gone: Vehicles by BR in the map editor
  replaces them (nations, allies and added units too, follows your vehicle).
- **Map editor**: **right click** on the map: the useful actions right there (on a unit: loadout, side,
  movement, copy, duplicate, remove; on the map: paste here, add a ground unit / aircraft / ship here, start
  here, centre). **Paste** drops the copied units centred on the pointer; the Paste button
  lets them follow the pointer until a click places them. **Cancel** next to Done puts the map back as it was
  when the editor opened.
- **Map editor**: zones say what the scenario puts there (your start, the vehicles it brings in, with
  pictures) and are coloured by side; the map is shaded, labels sit on dark pills, a tip names whatever is
  under the pointer, scenery can be hidden. **Several units at once**: Ctrl / Shift + click or Shift + drag
  to select, then change side, vehicle, count, fire, movement, altitude or speed for all; drag them together;
  Ctrl+C / Ctrl+V / Ctrl+D copy, paste and duplicate; each click can place up to 20 units side by side.
  **Vehicle picker with pictures**, and **My vehicles**: a saved vehicle becomes an AI unit, its loadout
  included. **AI loadouts**: Configure opens the unit in the vehicle panel (loadout, ammo) as for your own
  vehicle; aircraft with custom pylons get a custom aircraft of their own.
- **Ground starts without a jump**: on test flights you are parked on a runway of your own at the start set
  in the editor; on tank test drives the scenario's respawn point follows your start. Templates that never
  move you no longer get the extra respawn.
- **Map editor**: the scenario's **zones** show on the map (those its scripts use, to spawn, respawn or send
  units, highlighted) and can be moved: what the game puts there moves with them. **Your start**: on the
  ground or in the air, altitude, speed and compass heading (an arrow on the map, its tip can be dragged); it
  holds even when the scenario's templates respawn you in a zone of theirs, after a crash too. On test flights, an air start moves and turns
  the scenario's own start zone: you spawn there straight away, no jump. These left
  the vehicle panel (its last step keeps the fuel) and the map window. Template units can be made to
  **attack** too (not only "never shoots").
- The map editor no longer shows units that never appear: units the scenario keeps delayed (an AV-8B on
  Afghanistan) are "placed in game", template ships are dropped on maps without water.
- Fix: the map editor drew the units of the game templates a scenario imports at the template's own
  coordinates, which mean nothing on that map (Afghanistan: off the map, far from where they appear). WTFTD
  now follows the scenario's scripts across the whole import chain: units moved to a known zone show there,
  units the game places while the mission runs (asleep at start, zone picked by a variable, often at random)
  are listed as "placed in game" and not drawn.
- The flares / chaff counts follow the slider live.
- **All the game's maps**: the Maps tab shows the test-drive maps, then the game's 131 other maps.
  On those, a bare start (you alone, no targets) for each kind of vehicle the map suits, placed where the
  game's own missions (battles, training…) put that kind of vehicle; aircraft start in the air. Add targets
  with Edit on the map. Ground, air and naval starts checked in game.
- **Your library**, three tabs, everything shareable (code or .wtftd file, imported into the right tab):
  **My maps** (saved map variants), **My vehicles** (saved vehicle setups: Choose puts one in the bottom bar
  without opening it) and **My missions** (vehicle + map pairs saved with the bar's save button, ready to
  Choose or Create, and the mission files created in the game). Old share codes import as missions.
  Tabs follow the bar: Vehicles · My vehicles · Maps · My maps · My missions · Weapons. The vehicle filters
  show in Vehicles and My vehicles only (and filter both); the vehicle + map bar shows in the four first tabs.
- **Vehicle + map**: a new **Maps** tab shows every map (the game's own tactical map as picture). Click one:
  a window lists its variants (scenarios), to choose one or edit it on the map (move, add, remove units) as
  in the vehicle panel, even before picking a vehicle. A bar at the bottom holds the vehicle and the map of
  the mission, picked in any order, and creates it. Edited variants can be **saved** under a name (Save…), then
  chosen again with any vehicle, edited, updated, renamed or deleted (`user/variants.json`).
- The map's settings moved from the vehicle panel to the map window: enemy units (as in the scenario / don't
  shoot back / shoot), time of day, weather and start heading. They go
  with any vehicle and are kept in saved variants. The vehicle panel no longer has a Map & scenario step;
  **Save setup** keeps the vehicle's own setup (loadout, ammo, modifications, cheats, start) for any map.
- The vehicle panel's main button is **Select vehicle** (puts it in the bottom bar); **Create mission** is in the
  bar only. Opening panels just browses: each vehicle keeps its own setup, and the mission uses the selected
  vehicle's. Loading a saved setup or a mission selects its vehicle.
- Mission type, title and file name moved to a **Mission** window (gear of the bottom bar): they belong to
  the vehicle + map. Title and file name stay automatic until changed, and a custom one only applies to the
  vehicle and map it was written for. The picked map and its edits follow from one vehicle to
  the next when it suits it; a vehicle opened again keeps its setup.
- **Ammunition icons**: shells, aircraft / helicopter / ship belts and flares / chaff show the game's own
  icons (from its icon table, so they follow game updates). The game data rebuilds itself once at first launch.
- **Flares / chaff split**: for countermeasure launchers that take both, choose how many of each (the sum is
  the launcher's capacity). Checked in game on the F-14B, MiG-29SMT and Su-25.
- Fix: aircraft ammo slots are written the way the game spawns aircraft (each tagged with its weapon),
  with countermeasure counts per launcher: flares / chaff were ignored on some aircraft (F-14B, Su-25).
  Reloading a mission with mixed flares / chaff no longer shows empty counts.
- Fix: with "Invulnerable" on, some aircraft (MiG-29SMT) could not take off: the repair applied every second
  restarted their engines. Aircraft and helicopters now stay invulnerable without it. Re-create older
  aircraft missions to get the fix.
- **Targets shoot** (map settings): the scenario's enemies that hold their fire (test-drive targets) fire at
  will, to test invulnerability and countermeasures. Units set in the map editor keep their setting.
- Loadout: aircraft with fixed presets only (most low-BR aircraft) show them as a grid laid out like the
  game's hangar (13 columns, heaviest weapons in the middle), with the weapons' icons. Preset names read
  like the game's ("SC50 ×4"). (Weapon masses added to the game data.)
- **Custom loadout for fixed-preset aircraft** (custom vehicles): the grid switches to one column per
  attachment point found in the aircraft's presets; mix the official weapons or put any weapon of the game on
  a point. Written as a preset of plain weapons, like the game's own. Beta, see `docs/ingame-checklist.md`.
- First launch: the language picker no longer overlaps the logo; the progress bar shows a translated step
  instead of the English log (the log appears only on error).
- Opening a vehicle: every setup step starts closed.
- Fix: the app could start half-broken (comparison and weapons page not wired up) when the local server
  answered faster than the browser loaded its last scripts.
- The app window no longer offers to translate the page (Edge ignored the old setting).
- Fix: My missions shows the right vehicle (picture, name, Load) for missions saved under a custom file name.

## 0.15.0 — 2026-10-08

- **macOS**: WTFTD runs on macOS too. It finds War Thunder (Steam or standalone, inside
  `WarThunderLauncher.app`), launches it, and opens the UI in a Chrome / Edge / Brave app window. It quits
  when the window closes. Data lives in `~/Library/Application Support/WTFTD`. Git comes from Homebrew or
  Apple's Command Line Tools. Oodle runtimes are `liboo2core*.dylib`.
- Releases also ship `WTFTD-macOS.zip` (WTFTD.app, Apple silicon), built by GitHub Actions with its SHA-256;
  `build_app.sh` / `start.command` build / run it locally.
- Tests run on Linux, Windows and macOS.
- Fix: release notes lost their line breaks when GitHub Actions added the exe's SHA-256, so the whole text
  showed as one big heading. The macOS zip's SHA-256 is now always added too.

## 0.14.4 — 2026-10-08

- The exe is built by GitHub Actions from the released code and published with its SHA-256, so anyone can
  check that a download matches the source.
- Automated tests (BLK format, weapon stats, custom-vehicle file safety, local server) run on every change.
- Fix: BLK files with a comment after a value on the same line (`a:i=1 // note`) couldn't be read.
- FAQ in the README; CONTRIBUTING, SECURITY and this changelog.

## 0.14.3 — 2026-10-08

- Security: the local server refuses data reads that don't come from WTFTD's own page (a malicious website
  could in theory read settings, saved setups and the game folder path through DNS rebinding).
- Ko-fi "Sponsor" button on the repository page.

## 0.14.2 — 2026-10-08

- Weapons page: **nuclear bombs** category — yield from the game files (5 kt to 1.6 Mt), burst height,
  "raw power" and "yield per kg" rankings. The ground battles' killstreak nukes (Mark 6, Mark 7…) are
  listed with an "Instant win" badge (the game gives them no yield).

## 0.14.1 — 2026-10-08

- IRCCM: both mechanisms are detected — flare rejection (AIM-9M) and narrow tracking gate (R-73, Magic 2,
  R-27T…), which was missed — graded and explained in the badge.
- Speeds: ~130 rockets and ATGMs had none, and recent missiles (AIM-54…) showed the game's speed cap:
  speed now comes from the motor (thrust, burn time, mass), capped by the game's limits.
- Radar missiles' "Close range" ranks by max G, lock angle and the new *Acceleration off the rail*.
- Penetration: only HEAT or kinetic; high-explosive warheads no longer show their fragments' penetration.
- Mavericks, RB 75, GROM and other heavy guided missiles moved from *Anti-tank* to *Air-to-surface*.
- Scores: 100 = the best weapon of the category, in the table and in the comparison.

## 0.14.0 — 2026-10-08

- **Weapons page**: ~860 missiles, bombs, rockets and torpedoes from the game files, by category, with
  stats, "best for" rankings, a guide per category, community notes, comparison and carriers.
- **Stock / All upgrades** switch on vehicle stats and in the vehicle comparison.
- Filter by **vehicle type** (light / heavy tank, fighter, bomber…); **sort by rarity** with badges.
- Language picked from Windows on first launch, and selectable on the welcome screen.
- Ko-fi support button (top bar and Settings).
- Fix: heavy tanks, wheeled vehicles and some ships (≈250) were hidden as non-playable.

## 0.13.0 — 2026-10-08

- **Compare up to 5 vehicles** side by side: BR, every stat (best highlighted), guns, shells, pylon weapons.
- **New version alert**: the app checks the releases and shows a *New version* button.
- *Report a bug* / *Suggest an idea* from Settings, with GitHub issue forms.

## 0.12.0 — 2026-10-08

- **Share a setup**: a short code to paste or a `.wtftd` file; a friend imports it and gets the same mission.

## 0.11.0 — 2026-10-08

- **Weapon picker** with the game's icons: find vehicles carrying given missiles, bombs, guns or shell types.
- Layout for smaller screens; aircraft stats name power-to-weight (propeller) vs thrust-to-weight (jet).

## 0.10.0 — 2026-10-08

- **Vehicle stats** on each card (speed, power-to-weight, armor, traverse, penetration, reload, turn time,
  climb…), sort by any stat, min / max filters, search by weapon.
- MIT license.

## 0.9.0 — 2026-10-08 — first public beta

- Test drive any vehicle (ground, aircraft, helicopters, boats, ships) in the official Test Drive / Test
  Flight scenarios and hangar maps, as a user mission.
- Vehicle browser (grid and research trees, wiki images), loadouts (pylon editor, non-standard weapons,
  nuclear bombs), ammunition, modifications, cheats, conditions, training targets.
- Custom vehicles through the CDK `userVehicles` mechanism, to drive vehicles you don't own.
- Scenario editor on the level's real tactical map with ground heights.
- 11 languages; Windows exe; game data built on first launch from the community datamine (progress bar),
  updated automatically after game patches.
