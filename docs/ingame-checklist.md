# In-game checklist

What can only be checked with War Thunder installed (Windows). Written on 2026-10-08 after work done on a
Mac without the game. Tick each line, note what you see, then fix or remove the item.

Setup: `python -m wtftd` from this repository (or the exe built from `main`), custom vehicles on (default).
After a mission is created: start War Thunder → **Single missions → User missions**.
Test missions are named here by their title in that list (file name in brackets); from 2026-10-09 on, the test
to do is also written in the mission's description, shown under it in the game.

## 1. Countermeasures: flares / chaff split

**What was built.** In the Ammunition step, an aircraft whose countermeasure launcher takes both flares and
chaff shows two counts (flares, chaff) and a slider. Their sum is the launcher's capacity (`cap × n`
launchers); they move by steps of `n`.

**Findings (2026-10-08, Windows, F-14B / MiG-29SMT / Su-25, CDK custom units)**

Untagged `bullets<i>` (what official missions use) bind to weapons in an order of the game's own that
differs between aircraft: F-14B launcher = slots 0-1, MiG-29SMT = slots 1-2, Su-25 = 0-1 (Gaijin's own
Su-25 missions). No rule from the datamine (wpcost order, `getLinkedGunIdx` with 6 sets, group order with
pairs) matched all the runs. Probe results that settled it: F-14B `bullets0="" 17` + `bullets1=chaff 43`
→ 17 / 43; MiG `bullets1="" 7` + `bullets2=chaff 23` → 14 / 46 (counts are **per launcher**). A pair whose
counts don't fit the launcher falls back to the game's default (full of flares, or of the named kind).
Gun belts (Stealth) were applied from any slot.

How the game itself spawns an aircraft (`gui.vromfs.bin_u/scripts/respawn/respawn.nut`): active bullet
groups one after the other, `bullets<i>` = set name (`""` for a default set), `bulletCount<i>` = count per
gun × `maxCntPerPilon`, and **`bulletsWeapon<i>` = the weapon's blk name** (`countermeasure_split_launcher_jet`,
`cannonM61A1`); 6 sets (`BULLETS_SETS_QUANTITY`), empty ones `""`. A split launcher is two groups (flares,
chaff) on the same weapon; a group at 0 is left out.

**Round 4: fix** (`mission.py` `write_bullets`, aircraft / helicopters only): same layout, with
`bulletsWeapon<i>` from `details.json` `am[].p`, counts per launcher. Missions do read `bulletsWeapon<i>`
(no official mission uses it).

| Aircraft | Set | Written (`bullets` / count / `bulletsWeapon`) | Expect |
|---|---|---|---|
| F-14B | 40 + 20, Stealth | 0: `M60_stealth` 676 `cannonM61A1`; 1: `""` 40 launcher; 2: chaff 20 launcher | 40 / 20, no tracers |
| MiG-29SMT | 20 + 40, Stealth | 0: Stealth 150 `cannonGSh_301`; 1: `""` 10; 2: chaff 20 | 20 / 40, no tracers |
| Su-25 | 200 + 56, Stealth | 0: Stealth 250 `cannonGSh_30_2`; 1: `""` 50; 2: chaff 14 | 200 / 56, no tracers |

- [x] Round 4 checked in game (2026-10-08): all three exactly as expected, Stealth belts included.
- [x] Round 5: F-14B all chaff → 60 chaff; Su-25 all flares → 256 flares; Rafale C F3, two launcher types
  (small 12 + 24, large 8 + 8) → 20 flares / 32 chaff in the HUD (it adds both launcher types).
- [x] MiG-29SMT (CDK custom unit, ground start on Sinai): the engines kept cutting out, it could not take
  off. Round 5: no cheats / immortal without the 1 s `unitRestore` full repair / other cheats → all take off.
  Cause: the immortal cheat's full repair every second restarts the engines. Fix (`mission.py`
  `apply_cheats`): aircraft and helicopters keep `isImmortal` + `invulnerabilityTimer` (+ raised hit points
  in custom vehicles), without the repair loop; ground vehicles and ships unchanged.
- [x] MiG-29SMT with the fix (`wtftd_cmtest_mig_29smt_9_19`, immortal, targets shooting): takes off.
- [x] Stays invulnerable under fire (copy of that mission with Sinai's targets switched from `hold_fire`
  to `fire_at_will`: the test-flight scenarios' targets never shoot, whatever WTFTD's passive option).

## 2. Gun belts on aircraft

- [x] Stealth belts applied on the MiG-29SMT from slots 0, 3 and 4 (rounds 1, 3, probe d).
- [x] With `bulletsWeapon`: Stealth belts on the F-14B, MiG-29SMT and Su-25 (round 4).

## 2b. Custom loadouts on fixed-preset aircraft (new)

772 aircraft (most low-BR ones) have no WeaponSlots, only fixed presets: lists of
`Weapon{trigger, blk, emitter, bullets}`. WTFTD reads every emitter those presets use (`builder.py`
`legacy_pylons` → `details.json` `lp`, presets' `ls`) and writes a custom loadout as a preset of plain weapons
on those emitters (`cdk.py`, `weapons:t="wtftd_custom"`).

| Mission | Loadout | Expect |
|---|---|---|
| `wtftd_legacy_fw190_mix` | Fw 190 A-5/U2: SC500 + 4 SC50 + 2 BR 21 (official weapons, no official preset has all three) | all carried and dropped / fired |
| `wtftd_legacy_bf109_nonstd` | Bf 109 E-3: SC250 + 2 SC50 + BR 21 rockets on points 4-5 (never on this aircraft) | rockets under the wings, fire |

- [x] Fw 190 mix (2026-10-08, works in game).
- [x] Bf 109 non-standard (2026-10-08, works in game).

## 2c. The game's other maps (new, beta)

131 maps have no official test drive. WTFTD writes a bare mission on them (`builder.py`
`build_free_scenarios`, `free_<level>_<kind>` scenarios): the player alone, at the spot where the game's own
missions put a tank / ship of the player's side (else any side), facing the same way; aircraft at 1500 m
or higher above an air unit of those missions (else the map centre), 450 km/h.

| Mission | Vehicle / map | Check |
|---|---|---|
| `wtftd_free_m1_ash_river` | M1 Abrams, Ash River (`avg_ireland`), ground | spawns on the ground, can drive |
| `wtftd_free_f14b_el_alamein` | F-14B, El Alamein (`air_africa_desert`), air start | flies away, doesn't fall |
| `wtftd_free_ship_ireland_bay` | Fletcher, Ireland bay (`avn_ireland_bay`) | spawns on water, sails |

- [x] Ground start (2026-10-09, works in game).
- [x] Air start (2026-10-09, works in game).
- [x] Naval start (2026-10-09, works in game).

## 2d. Map editor: start, zones, template units firing (new)

`wtftd_editor_test_afghan` (F-14B, Afghanistan): start set in the editor (air, 3034 m = 1500 m above the
ground, 600 km/h, heading east), the enemy base zones `bdt_t2_bomb_zone_mid_01..04` moved 3 km east, the
bases' AA (`bdt_t2_aaa_unit`, a template unit) set to Attacks.

- [x] Round 1: start ignored (2600 m, 500 km/h, heading 025): the test-flight template respawns the player in
  `spawn_area01` (its height, heading; its scripts set 500 km/h). The editor's heading was a maths angle
  (0 = east), the game shows a compass heading (0 = north). The bases' AA did engage (it is fire-at-will in
  the template already, brought in by the scripts), the aircraft was just too fast for it.
- [x] Round 2 (fix: `wtftd_start` zone + respawn into it 1 s in, speed set; compass heading in the editor;
  2 ZSU-23-4 added, fire at will): spawn at the scenario's start, a few seconds later moved to the right
  heading, speed and altitude; the ZSU-23-4 fire at you. After a crash: back at the scenario's start.
- [x] Round 3 (fix: `wtftd_dead` set when killed, back to `wtftd_start` 1 s after being alive again):
  after a crash, back at the WTFTD start (2026-10-09).
- [x] Round 4 (test flights, air start: the mission asks for an air start and the scenario's own zone
  `spawn_area0<air_spawn_point>` and its variants are moved / turned to the editor's start; only the speed
  is set 1 s in): spawn straight at ~3034 m, heading 090, no jump; 600 km/h; same after a crash: no jump (2026-10-09).
- [x] The enemy bases appear ~3 km east of where they were. OK (2026-10-09).

## 2e. Ground starts without a jump, AI units with loadouts (new)

Data schema 14: `{sid}.zones.json` now says what each zone gets (`builder.zone_roles`: units the scripts put
there, the zones the player is respawned / teleported into). Ground starts: a test flight gets a runway of its
own (`addAirfield` at the start, the template's `airfield_spawn` variable kept on it, as the template itself
does for seaplanes); a tank test drive's respawn zone (`spawn01`) is moved to the start. AI units: preset +
belts written on the unit, an aircraft with custom pylons gets a custom aircraft of its own
(`pkg_user`, `wtftd_<id>_ai<n>`).

- [x] `wtftd_r6_ground_afghan` (F-14B): parked on the Afghan runway between its two spawn points, facing NNE
  (towards the airfield centre), no jump; after a crash: same place. 2026-10-09: on the ground, roughly facing a
  runway, OK for the user; not the airfield expected (WTFTD's own runway at the editor's start).
- [x] `wtftd_r6_tank_tft` (T-72A, firing range): starts 150 m north of the usual start, facing south, no jump. OK (2026-10-09).
- [x] (also played 2026-10-09: looks right; and 2i) `wtftd_r6_ai_loadouts` (F-14B, air start 1500 m above the start, 600 km/h): 2 enemy Rafale (the saved
  "Rafale C F3 · Custom": Magic / MICA + a pod) and a MiG-29 9.13 with R-73s hunt you, 3 Fw 190 C east.
  Check the Rafale / MiG fire missiles (their loadout is used), the Rafale carry the custom pylons.

## 2f. Template units given another vehicle (new)

Data schema 15 keeps the game templates the scenarios import (`data/templates/`).

**First try (2026-10-09), failed:** the mission carried the templates' whole content (`inline_imports`). The map
loaded, the bombing sites were there, but no enemy and no airfield: the datamine's JSON groups an action used
several times in a trigger (`varSetString` ×4 in `init_rank_settings`), so their order with the other actions is
lost and the rank-based target picking broke. Templates' scripts are therefore never rewritten.

**Now:** the templates stay imported (their scripts run as the game wrote them). The units of a template the
mission imports directly (without imports of its own: `test_flight_unit_template`) are declared by the mission
itself when one of them gets another vehicle, and that import gets `importUnits: no`
(`mission.take_over_units`). Units of nested templates (the bases' Bofors) can't change vehicle.

- [x] `wtftd_r7_tpl_swap` (F-14B, Afghanistan test flight, the template's targets set by "Vehicles by BR" at 12.7):
  the airfield and the enemies are there; the targets are the new vehicles; they come back after being destroyed
  (2026-10-09). Found: a dirt airfield (the file's `target_rank_index` 1: the hangar passes your rank, a user mission
  doesn't) and SAM "AA" that were only their battery's radar (`*_fcs`, unarmed: the research tree's slot).
- [x] Same mission, regenerated: high-rank airfield and target zones (`target_rank_index` follows your vehicle);
  SAM launchers are there (2026-10-09). They did not fire: the template's targets are `hold_fire` / `dont_aim`, and
  its scripts set the aircraft `cannotShoot` each time they spawn them.
- [x] Same mission, regenerated with Vehicles by BR → Fire: Attacks (every target `attack: fire_at_will`; WTFTD's
  `wtftd_attack` trigger sets `attack_type: fire_at_will, cannotShoot: no` on them every 3 s): the SAM launchers
  (with their radar 30 m away), tanks, SPAA and aircraft shoot at you, also after they respawn.
  First run (2026-10-09): the HQ-11 (a SAM with its own radar) fires; shot down before seeing the rest.
  Invulnerable run (2026-10-09): HQ-11, Spyder and tanks fire; the SAM batteries' launchers don't (even with their
  radar 30 m away: dropped, Vehicles by BR now picks vehicles that fire on their own), the aircraft don't.
- [x] Regenerated (invulnerable): HQ-11, Spyder and tanks fire (no Pantsir seen); the template's aircraft, told
  to hunt you every 10 s (`wtftd_hunt`), neither came at you nor fired (2026-10-09). Same `unitAttackTarget` as
  Gaijin's missions. Open: their scripts' route wins, or AI aircraft leave a player alone while the invulnerable
  cheat's `invulnerabilityTimer` (spawn protection) is on.
- [x] **WTFTD r7b: aircraft hunting you (not invulnerable)** (`wtftd_r7_air_hunt`, 2026-10-09): no MiG-29 seen,
  shot down by the SAM. (r7b and r7c: the MiG-29 were written by hand as `mig-29_9_13`, not a game unit (it is
  `mig_29_9_13`): the game dropped them; the editor only offers real ids.) The 2 MiG-29 were in the mission ~7 km from the real start (`spawn_area01`); their hunt order
  was only given at mission start, before the templates' scripts spawn you: lost. Now every hunt order (added and
  scenario units too) is given again every 10 s (`wtftd_hunt`).
- [x] **WTFTD r7c: aircraft hunting you, ground passive** (`wtftd_r7_air_hunt`, 2026-10-09): a template F-4E
  came at the player and shot them down: Hunts me works for aircraft once the order is repeated (every 10 s).
  The earlier invulnerable run already repeated it for the template's aircraft and none attacked: the invulnerable
  cheat (`isImmortal` + `invulnerabilityTimer`, spawn protection) most likely makes AI aircraft leave you alone.
  Seen live (game web UI, port 8111): shot down again and again by F-4E AUP and F-2A (template aircraft), and by
  HQ-11 / Spyder standing in for template targets that Gaijin's template already sets to fire at will.
- [x] **WTFTD r7d: 2 MiG-29 + target aircraft hunt you, ground silent** (`wtftd_r7_air_hunt`, 2026-10-09, watched
  live on the game's web UI, port 8111): "MiG-29 shot down StonewarP"; after the respawn the 2 MiG-29 closed from
  3.6 to 1.3 km in 15 s, 2 target fighters (F-4E AUP / F-2A) from 19 to 16 km; the 2 AV-8B (attack aircraft) stayed
  7-10 km away. Hunts me works for added and template aircraft.

## 2g. Invulnerable without spawn protection, unbreakable airframe (new)

Invulnerable no longer sets `invulnerabilityTimer` (the spawn protection: AI aircraft left the player alone, 2f),
only `isImmortal` (+ the custom vehicle's hit points ×1000). A crash into the ground still kills you (a revive
after it was dropped at the user's request). New cheat **Unbreakable airframe** (aircraft / helicopters, custom vehicles): the
flight model's breaking limits raised (`Vne`, `VneMach`, `Strength/VNE` and `MNE` → 100000 km/h / Mach 100; `CritOverload`,
`WingCritOverload` ×100; gear, flaps, airbrake, canopy breaking speeds → 100000).

- [x] First r8 with thrust ×20 (2026-10-09): no more power. Jets take their maximum thrust from the flight model's
  `ThrustMax` table (`ThrustMax0` × coefficients by altitude / speed), not `Main/Thrust`, which was all the Thrust
  mod changed: it never worked. Fixed: `ThrustMax0` of every engine type scaled too.
- [x] r8 with the thrust fixed (2026-10-09, live: Mach 3.49, 2806 km/h IAS at 6600 m): power OK, but the wings
  broke with speed: each wing's `Strength` block also has `MNE` (Mach limit, 0.96 on the F-14B), not raised.
  Fixed (`MNE`, and `VneHeli`, `chuteRipSpeed`).
- [x] **WTFTD r8b: invulnerable, unbreakable airframe (Mach limit too), hunted** (`wtftd_r8_invulnerable`): past
  Mach 1 up to Mach 3+ and pulling hard, the wings stay on; the aircraft come at you and fire, you don't die. All good (2026-10-09).
- [x] (superseded by r8b) **WTFTD r8: invulnerable, unbreakable airframe, hunted** (`wtftd_r8_invulnerable`, F-14B, Afghanistan; the
  test is in its description): the MiG-29 and the target fighters still come at you and fire, you don't die;
  past the speed limit (thrust ×20 to get there fast) and pulling hard the wings stay on, gear and flaps don't
  break.

## 2h. Super mobility cheat (new)

Custom vehicles. Ground vehicles: `engine/horsePowers` ×4, `mechanics/mainGearRatio` ÷2 (top speed ×2),
`mechanics/maxBrakeForce` ×3. Aircraft: jets `ThrustMax0` ×3, piston engines `Main/Power` and the compressor's
`Power<n>` / `PowerConstRPM<n>` / `PowerAtCeiling<n>` ×3; `Mass/EmptyMass` ×0.6. A value set under Modifications
wins. (The ground modifications themselves had never been checked in game.) Aircraft handling too (`cdk._handling_overrides`):
`MomentOfInertia` ×0.4, `Areas/Aileron|Elevator|Rudder` ×1.5, `*EffectiveSpeed` and `*MaxDv` ×2, the wing's
`ClCritHigh` / `ClCritLow` ×1.3 (NoFlaps / FullFlaps, WingPlane* / FlapsPolar*), every `CdMin` ×0.5.

- [x] **WTFTD r9a: super mobility, T-72A** (`wtftd_r9_mobility_tank`, tank test drive): much faster acceleration,
  top speed about 120 km/h instead of 60, still turns and brakes well.
- [x] **WTFTD r9b: super mobility, Bf 109 F-4** (`wtftd_r9_mobility_air`, Afghanistan test flight): roll, pitch, turn
  time, acceleration and climb far better (3510 hp instead of 1170, 40 % lighter, half the drag); still flyable;
  the engine runs normally.
- [x] **WTFTD r9c: super mobility + unbreakable airframe, F-14B** (`wtftd_r9_mobility_jet`): roll, pitch, turn time
  and acceleration far better than a normal F-14B; still flyable; the wings stay on in hard turns.
  r9a, r9b, r9c all good (2026-10-09).

## 2i. AI units with a custom (pylon by pylon) loadout (new test)

An AI aircraft's Configure opens the vehicle panel with the pylon-by-pylon loadout; with custom pylons the server
writes a custom aircraft of its own for that unit (`wtftd_<id>_ai<n>`, `pkg_user`). Presets were confirmed in game
(2026-10-09); custom pylons too (r10, 2026-10-09). (Also fixed: from the Maps window, Configure left that window over the
vehicle panel.)

- [x] **WTFTD r10: AI with a custom loadout (Rafale)** (`wtftd_r10_ai_custom`, invulnerable): 2 enemy Rafale C F3
  with the saved "Rafale C F3 · Custom" pylons (5) hunt you: they carry those pylons and fire their missiles. Works (2026-10-09).

## 2j. Uninstall (Settings) with the packaged app (new)

`wtftd/uninstall.py`. Checked from the source tree (sizes, choices, confirm, the final screen; nothing removed)
and on throwaway files. 0.17.0 had a post-exit script retrying for 10 minutes: it opened a visible console (ping)
and, the window's profile staying locked, it removed an exe rebuilt meanwhile in `dist` (2026-10-09). Now WTFTD
closes its own window (`close_app_window`: the processes running its profile), quits, and a hidden script removes
the app and the folder once, 6 s later (checked on throwaway files: removed once, a rebuild afterwards kept).

- [ ] With an exe built from `main`: back up `%LOCALAPPDATA%\WTFTD` first (it holds your settings and library),
  then Settings → Uninstall WTFTD… → Everything → Remove, click again. The window says WTFTD was removed; once it
  is closed, `WTFTD.exe` and `%LOCALAPPDATA%\WTFTD` are gone within a few seconds, the game's `wtftd_*` missions
  and custom vehicle files too, nothing else in the game folder. Restore the backup afterwards.
- [ ] macOS, with WTFTD.app moved to Applications (back up `~/Library/Application Support/WTFTD`): the same,
  WTFTD.app and that folder gone once the window is closed. The shell script itself runs in the macOS and Linux
  tests (`AfterExitShell`, 2026-10-09). Opened straight from Downloads (App Translocation), "The app itself" is
  greyed out and asks to move WTFTD.app to the Trash.

## 2k. Modified pylon weapons (new test)

A pylon weapon with changes (`{"w": key, "n": count, "mod": {...}}`, no UI yet) gets a file of its own,
`gameData/Weapons/wtftd/<vehicle>_p<pylon>.blk`: `include` of the game's weapon + overrides of its `rocket` / `bomb`
block (`cdk._custom_weapon`); the pylon's preset uses it. Launchers (LAU-7…) are not handled yet. Unknown: whether
the game loads a weapon from that folder at all, and which values drive a missile's turn (G).

- [ ] **WTFTD r11: custom weapons (F-14B)** (`wtftd_r11_custom_weapons`, Afghanistan test flight, invulnerable,
  enemies passive): AIM-9L on pylons 1 and 8 at 100 G (`loadFactorMax`, autopilot `reqAccelMax`, `finsLatAccel` 150),
  thrust ×5 (54 000 N) for 10 s, Mach 6; AIM-9M on pylons 2 and 7 with 500 kg of explosive (3.6); Mk 82 on pylons 4
  and 5 with 10 t of explosive (87 kg). Played 2026-10-09: all carried and fired; the AIM-9L much faster (thrust
  works). But the HUD names made no sense (the game names a weapon after its file: `weapons/<file name>`), the
  missiles left two by two (one file per pylon = two weapons firing together), the Mk 82 blast looked ordinary (the
  effect is the weapon's own, `explosionFx`), the AIM-9M did not hit (blast not seen).
- [ ] **WTFTD r11b: custom weapons, names fixed (F-14B)** (same file): one file per weapon + changes, named as the
  game's (`wtftd/f_14b_<n>/us_aim9l_sidewinder.blk`), the explosion effect of a weapon that size (`BOMB_FX`,
  `ROCKET_FX`; past 220 kg a missile also gets a bomb's `explosionFx`, a new value in its block). Check: real names;
  one missile per press; AIM-9L tight turns off-boresight; big AIM-9M / Mk 82 blasts, tanks killed far from the
  impact. Also tells whether a same-named copy clashes with the real weapon (the test flight's AI F-14B carries it).
  Played 2026-10-09 (with instant reload): AIM-9L very fast (the same-named copy keeps its changes); AIM-9M "heavy"
  with a big blast; Mk 82 blast bigger; real names in the HUD; much tighter turns at 100 G. But still two missiles
  / bombs per press (the game's pylon presets mark each weapon `separate:b=yes`; ours did not), and the Mk 82 at
  10 t kills only a little farther (blast radius grows as the cube root of the charge: x115 → about x5).
- [x] **WTFTD r11c: one at a time, nuclear charges (F-14B)** (same file): `separate:b=yes` on every pylon weapon;
  `kt` = a nuclear charge as the game's nuclear bombs (`yield`, `splashFallBySquare`, `nuclearExplosionFx`
  under 15 kt): AIM-9M (pylons 2, 7) 5 kt, Mk 84 (pylon 5) 20 kt, Mk 82 (pylon 4) 10 t. Check: one per press; a
  nuclear explosion from the missile? from the Mk 84? tanks destroyed far around. Works (2026-10-09): one per
  press, the AIM-9M makes a nuclear explosion, the Mk 84 too and destroys tanks far around.

- [ ] **My weapons from the page** (tab My weapons, Weapons → Modify): make a weapon with Simple + one Advanced
  value (e.g. AIM-9L, Absurd, `rocket/guidance/workTime` 60), put it on two pylons of an aircraft (Loadout →
  Custom pylons → My weapons) and on an AI aircraft's loadout, create the mission and play it: the changes are
  there, one per press; edit the weapon, create again: the new values are used.

## 2l. Experimental branch (new tests)

Checked out of game: unit tests (`tests/test_experimental.py`), the app's panels and the editor (2026-10-11).

- [ ] **In-mission keys**: in the game's controls give keys to Quick radio messages #1–#6 and #9. Create a mission
  with Cheats → In-mission keys (+ Invulnerable on) on a tank test drive and play it: the hint "WTFTD keys…" after
  3 s; #9 shows the list; #1 says "Invulnerable: off" and a hit now damages you, #1 again turns it back on; #2
  switches instant reload; #3 makes the targets stop / start firing (with "Targets shoot"); #4 repairs; #6 puts you
  back at the start. Unknown: whether a key held a little long switches twice, whether the radio message also shows
  in the chat.
- [ ] Same on a test flight (aircraft): #6 puts you back in the air at the start's speed; #4 repairs (may restart
  the engine).
- [ ] **Targets come back**: add 3 enemy tanks in the editor, destroy them: they come back within 20 s
  (`unitRestore` with `ressurectIfDead` on AI units: unknown), and #5 brings them back at once.
- [ ] **Ground battle maps**: Maps → Ground battle maps → Poland → Ground, side A: you start in team A's spawn
  facing the zones; side B: the other end. An aircraft (air start) and a helicopter on the same map.
- [ ] **Custom sights**: put a sight in UserSights/all_tanks (or add a `.blk` in the Ammunition step), pick it for a
  tank, create the mission: `UserSights/us_m2a4/wtftd.blk` (custom vehicle host) and `UserSights/<tank>/wtftd.blk`
  exist. In the hangar select the M2A4, Options → … → Sight settings → Reticle → "wtftd", save. Play the mission:
  is the sight used with the custom vehicle (the host's sight, or the tank's own folder)?
- [ ] **AP penetration**: compare a few values with the game's X-ray / hangar shell card (M62, DM63, BR-471, a
  modern APFSDS): within a few %?
- [ ] **Drones**: UAV Raven's Eye and the FPV strike drone on a bare map (air start, 100 km/h): do they load?

## 2m. Flight alarms and overlay (new)

Checked out of game: unit tests (`tests/test_alarms.py`), the limits of every flight model, the overlay window against
a fake `/state` (click-through, keeps the focus, hides, closes cleanly). `.cache/wtftd.log` (packaged app) or the
console lists each recognition: `Alarms: Mfuel0=…, reported=…, saved model=…, limits=…`.

Turn them on first: In flight → My overlay → Turn on the overlay and alarms (off by default).

- [x] **Real values in flight** (2026-10-30): captured on screen in a flight, `IAS 1154 / 1540 km/h`, `MACH 1.92 / 2.10`,
  with a custom font and opacity.
- [ ] **Off by default**: on a fresh install no beep and no overlay in flight until the switch is on.
- [ ] **My overlay**: a line per condition (gear, flaps, airbrake, during an alarm) comes and goes at the right time;
  a line's own colour and size; the alert colour only on the line of that alarm; `{margin}` falls to 0 at the limit.
- [ ] **Show / hide key** (Ctrl+F12 for instance) with the game in front; the beeps go on while the window is hidden.
- [ ] **Each alarm's** threshold, pitch and length heard in flight; switched off, no beep and no alert colour.
- [ ] **Position**: placed in the tab, it lands at the same spot in game (full screen and windowed).
- [x] **`/indicators` format**: answers again after a game restart (2026-10-30, Su-30MKK at 1,284 km/h): `"valid": true,
  "army": "air", "type": "su_30mkk"`, the vehicle id. What makes it go blank (seen on 2.59) is unknown.
- [ ] When it answers, `reported=` wins over the fallback, including on a look-alike and with external tanks. When it's
  blank, `reported=None` and the fallback does the work.
- [ ] **Su-30MKK and J-10C** recognised: full tank, then a partial fuel load (Mfuel0 should stay the capacity).
- [ ] **Change aircraft in the hangar**, fly again: is the new one recognised? (When does the game write
  `global.blk`? It didn't change during a 10-minute flight.)
- [ ] **Spawn on another slot in a battle**, the hangar selection unchanged: `AIRCRAFT UNKNOWN`, or the wrong aircraft?
  Worst case: the new one has the same fuel and engines as the old one (391 of 1,134 aircraft have such a look-alike)
  but other limits: then the old one's limits would be kept without warning. If so, `/hudmsg` is the lead to follow.
- [ ] **External fuel tanks**: does `Mfuel0` change? If it does, the aircraft becomes `AIRCRAFT UNKNOWN`.
- [ ] **Alarms heard at the right threshold**: airframe (dive, 93 %, high beep), gear (90 %), flaps (90 %, low beep).
  The flap limit is interpolated between the flight model's points: an interpretation of the data, to confirm.
- [ ] **Menus**: nothing shows in the hangar, whatever aircraft is on show (the game flickers between 0 and 1 km/h there).
- [ ] **Glow** (My overlay → Glow around the screen): shows with an alarm, goes with it, not after a crash, never takes the
  focus, clicks go through it, and fits a borderless game (not an exclusive fullscreen one).
- [ ] **Glow's size and flash**: both follow the settings during a real alarm, and the first flash doesn't stall the overlay.
- [ ] **Glow's colour**: its own colour during a real alarm, the alert colour again once cleared, and a profile's colour on its
  aircraft. The window itself was read on screen out of game; the game in front wasn't checked.
- [ ] **A line's own alert** (say fuel % under 15): colour, beep and glow, gone with it; a condition hides and shows a line.
- [ ] **Sounds**: volume heard, a `.wav` per alarm plays and comes back to the beep if its file is removed, mute key, beeps
  only with the game in front, none with the engines stopped.
- [ ] **Value `{vehicle}`** (My overlay → Vehicle name): the right name in a jet, a helicopter, a tank and a ship, in the app's
  language; a custom vehicle from a WTFTD mission shows its real vehicle's name. A long name stays on its line in the overlay's window.
- [ ] **`AIRCRAFT UNKNOWN`**: the note shows without any sound, and `{vehicle}` gives the id the game reports.
- [ ] **Text blocks and outline**: readable on a bright sky, blocks at their places, a blinking line doesn't move the text.
- [ ] **Your own sound**: an mp3 picked for an alarm plays in flight, on the sound output chosen, and a long one doesn't
  slow the overlay.
- [ ] **Colours, columns, frame, background**: as on the preview, the background see-through at 25 to 75 %.
- [ ] **Jets and propeller aircraft** overlays load by themselves, and a helicopter takes neither.
- [ ] **App window**: starts minimized; minimized, it leaves the taskbar for the notification area and a click brings it
  back; WTFTD closes when the game does, not during a loading screen.
- [ ] **SPAA missile on a pylon** (Su-30MKK with a 5V55R, then an IR and a beam-riding one): the mission loads, the loadout
  shows it, the aircraft locks and fires it, it guides and hits. A failure there says if the rewritten file needs more.
- [ ] **Another radar** (Su-30MKK with an F-15's): it locks, its own range and modes; a radar added to an aircraft without one.
- [ ] **Another engine** (a jet with another jet's): thrust and fuel use follow, it doesn't flame out or crash the mission.
- [ ] **Avionics**: a laser designator or CCIP switched on where the aircraft has none: does the sight show it?
- [ ] **Guns on pylons**: a tank gun under a wing fires, and rounds count; an aircraft without pylons fires from its muzzle.
- [ ] **A tank with an S-300 launcher instead of its gun**: does the mission load, does it aim, does it fire?
- [ ] **Objects on a map**: AA gun, truck, building, radar, infantry, each loads; a carrier, a train.
- [ ] **Overlay in a tank and a ship**: its profile loads, `{speed}` shows; which other values /indicators gives there.
- [ ] **Voices**: with the game's Crew language on Crew country, does the mission's country change the crew's language, on
  an aircraft and on a tank (a custom tank may speak its host vehicle's language)? Rita in place of Betty; a special crew voice.
- [ ] **Routes**: a tank, a truck, a ship and an aircraft follow their points at the speed asked, stop at the end or go round
  again. Three units sharing a route keep their gaps. Does a ground unit get stuck on a straight line across a slope or a river?
- [ ] **Waves**: wave 2 is absent at the start, comes at its place 5 s after wave 1 is destroyed, with the hint; a delayed unit
  with a route drives it; aircraft come in at their height and speed; with *First wave again*, the first comes back, twice.
  Do Hold fire and Stays still hold on coming in, and do passive enemies of the Targets setting stay passive?
- [ ] **Non-playable units on a map**: an S-300 launcher and its radars load in a mission, and fire or not; which others do.
- [ ] **Overlay**: shown in flight, gone on Alt+Tab, back afterwards, never takes the focus, clicks go through it.
  Beeps go on during an Alt+Tab.
- [ ] **A-4 or Mirage III** (take-off rockets counted out of the engines): recognised? How many `throttle` fields
  does `/state` send with the rockets fitted?
- [ ] **Variable sweep (F-14, MiG-23, Tornado)**: the IAS line says `(swept limit)`; no alarm wings forward.
- [ ] **Helicopter**: airframe line and alarm; the gear line on fixed skids: useful or noise?
- [ ] **WTFTD mission with a custom vehicle**, with changed fuel: recognised through the mission.
- [ ] **Unbreakable airframe** in that mission: the overlay says so, no beep. Then a real battle on another map with
  the same aircraft: alarms are back.
- [ ] **Packaged exe**, not only the sources: overlay shown, and no crash message on closing WTFTD.

## 2n. Flight data and recording (new)

Checked in a real flight on 2026-10-30 (Su-30MKK): live curves, a recording (BOM, columns, values), its replay and
deletion, dark and light themes, a 1280 px wide window.

- [ ] **Turn time** against the game: hold a level turn at a steady G and time a full circle with a stopwatch. It
  assumes a level turn; climbing or diving it's only indicative.
- [ ] **Fuel use and fuel time left**: without unlimited fuel, the minutes left against what really happens. The burn
  is an average over 30 s.
- [ ] **Thrust/weight**: compare with the stat card; the mass leaves out weapons and ammunition.
- [ ] **SEP and acceleration** in a level acceleration and a climb: sensible signs and sizes?
- [ ] **Record key** (My overlay): starts and stops in flight, `REC` shows on the overlay while it records.
- [ ] A **CSV opened in Excel**: accents fine; with a French Excel, does it need Data → From text (comma separator)?
- [ ] A **recording across two flights**: the curve breaks between them rather than joining them.
- [ ] **Helicopter**: the values it doesn't send show N/A, nothing breaks.

## 2o. Battle, overlays per aircraft (new)

Checked in a real flight on 2026-10-30 (Su-30MKK): the battle log (131 lines, the game's icons removed), the sheet of the
aircraft flown, an overlay per type then per aircraft picked up live. The game had no chat lines at the time.

- [ ] **Chat** in a real battle: team, all, squad lines, the sender, enemy names in their colour.
- [ ] **Battle log** with kills and damage, in French and in English, and `events` lines (never seen so far).
- [ ] **Restart the game** with the tab open: the numbering starts over, the old lines go and the new ones come.
- [ ] A **second screen**: the app's Battle tab next to the game.
- [ ] **Profile by type**: bomber, attacker and helicopter each take their own overlay on spawn, on a slot change too.
- [ ] **Custom vehicle** with a profile: which overlay does it take (the vehicle's id comes from the mission)?

## 2p. Crash detection (new)

Worked out on real flights on 2026-10-31 (Su-30MKK, 10 readings a second): at an impact every engine's RPM and throttle
fall to 0 from one reading to the next, and `/state` stays valid until the next spawn. Replayed on those recordings and
checked against the game's own log (`onAircraftDead`, `water_explosion_big`): 2 impacts on the ground and 1 in a lake
found within 0.1 s; no false alarm on a landing, a belly landing, 11 G pulls and 20 minutes of flying.

A break-up in the air (wings gone at 1,607 km/h, 23 G) keeps the engines running: the battle log (`/hudmsg`, live) tells
it, from `NET_PLAYER_HAS_CRASHED` in the game's language files. The log names everybody and the game's API doesn't give the
player's name: it comes from the replays (My battles), and from the line that comes with an impact of ours; only that name
counts. Replayed on the same flight: the name learnt 0.4 s after the first impact, the beeps of the break-up stopped.

- [x] **Into water**: same numbers, at high speed in the Surobi lake (Afghanistan).
- [ ] **Slowly into water**: when the aircraft floats, then sinks?
- [ ] **Propeller aircraft and multi-engine ones**: single engine, four engines.
- [ ] **Helicopter**: does `RPM` read above 500 at all? Below that nothing is detected.
- [ ] **Engine shot out, then gliding to the ground**: no engine left to fall to 0, so no detection: acceptable?
- [ ] **Hide the overlay after a crash** on: gone at the impact, back at the next spawn.
- [ ] **Hide the overlay while the aircraft is unknown** on: nothing at a spawn the app can't recognise, the lines back as soon as it does.
- [ ] **Break-up in the air** as the first crash of the session: with a replay on the PC the beeps stop at once; without one, no
  name yet, so they go on for those few seconds.
- [ ] **A real battle**: another player's crash, in the same aircraft too, doesn't silence the alarms.
- [ ] The game in **another language** (English, Russian, Japanese): the name gets learnt.

## 2q. Penetration by distance (new)

Checked out of game on 2.59.0.92: unit tests with reference values, then the official wiki's tables on whole vehicles (T-80U,
T-72A, Object 435, Tiger H1, M1A2, Centurion Mk 10: 137 of 138 values identical, the last one 1 mm off) and on aircraft
and machine gun belts (P-47D-28, Bf 109 F-4, La-7, Yak-9T, Fw 190 A-8, F-4E, M1A2: 150 of 150 on the belts compared). Never
compared with the game itself.

- [ ] **Hangar shell cards** against the panel, shells marked `≈`: a DeMarre shell (BR-471D), a long rod (M829A2), an APCR
  (M93), an APDS (L28A1), a steel dart (3BM4), an HE (3OF26: 42 mm flat; Sprgr L/4.5: 18 down to 13 mm). The wiki may follow
  another game version than the one installed.
- [ ] **MGM-166 LOSAT**: WTFTD shows the game file's table, 70, 150, 443, 775, 729, 675 mm at 10 to 2000 m; the wiki says
  20, 124, 416, 764, 688, 619. Which one does the hangar card show? Does a hit near 1000 m pierce 775 mm?
- [ ] **Shells whose file gives no drag** use `Cx` 0.35: M79, M318 and M74B1 match the wiki, the 260 others weren't compared.
- [ ] **Belts**: the belt shows the curve of its best round at 10 m. Known gaps: Yak-9T UBS, Universal, Air targets and Tracers
  1 mm off at 1000-1500 m (AP-I and API-T tie at 10 m); Fw 190 A-8 MG 131 HEI-only belt: 2 mm flat here, the wiki says
  4, 4, 4, 4, 0, 0. Does a round stop piercing past some distance (self-destruct)?
- [ ] **Fragments**: a shell with explosive pierces at least what its fragments do (`explosiveTypeToShattersParams`, picked by
  explosive / shell mass; none under 5 g of TNT). Worked out from the MG 151's APHE and FI-T and the ShVAK's FI-T, not read
  from a rule of the game. Try other small cannons (MK 108, Type 99, Hispano HE).
- [ ] **Ship and boat guns**, **helicopter guns**: never compared with anything.
- [ ] **Look**: the graph in the Ammunition step in both themes, with 6 or more shells, and the missile launcher's graph on a
  tank that has one. Its numbers were read from the page, the drawing wasn't looked at since all shells went in.

## 2r. Bombing a target (new)

Worked out from the game's mission templates (HP by balance level), `explosive.blkx` (damage by TNT equivalent) and what
players report, not measured in game. The reports fit: 3 Mk 83 for a base, 6 for one that respawns at the top (25,900 HP);
9 x 60 kg but not one 800 kg bomb at 10,000 HP; 28 SC50 + 2 SC250 for an airfield at BR 2, not in an uptier. One misses by
0.4 %: 5 x 250 lb (5,975 damage) on a 6,000 HP base, reported as destroyed.

- [ ] **BR = 1 + level / 3** is a deduction (balance level = economic rank). Is it the battle's top BR? Check around 2.3, 3.7,
  5.0 and 6.7, where the HP change.
- [ ] **Respawns**: outside arcade the templates multiply HP by the mission's `missionGetMaxRespawns` (4 when unlimited). The
  reports fit × 1, the panel's default. What does it return in Air RB and in Simulator?
- [ ] **Which maps use what**: only 55 of the 661 `historical/bfd` missions import these templates directly. What sets the
  others' bases?
- [ ] **Counts in a real battle**: a base with the panel's count, all bombs inside the zone; a near miss (does damage fall
  with distance from the centre?); the fire after the hit (`hpFireMult`, `fireSpeed`), which may finish a base early.
- [ ] **Napalm and incendiary**: shown with no count. The zone's multiplier is × 13, but a report shows a base kill with almost
  no TNT on the scoreboard. How much does one take off?
- [ ] **Rockets and missiles**: counted like bombs, from the same table. A salvo of HVAR, a Maverick, a guided bomb.
- [ ] **Airfields**: HP + 20 % on maps without bases (`isBombingZonesAffect`), not counted. Arcade multipliers.
- [ ] A **user mission** could measure all this: `missionSetBombingArea` with a known HP, `missionGetBombingAreaHP` shown after
  each bomb.

## 2s. Flight report, Tacview, cockpit window, pitch (new)

Checked on a real flight on 2026-10-31 (Su-30MKK): a 16 s log, its report and its `.txt.acmi` file, position on the map (scale
within 1 % of the speed, heading equal to the compass), the cockpit window's values against `/state`.

- [ ] **Pitch**: the game's `aviahorizon_pitch` is negative nose up (-7.4 in a 7.4° climb); the app now flips it. Only seen in
  one steady climb: check a dive and inverted flight. Logs recorded before keep the old sign.
- [ ] **Bank**: which way round is `aviahorizon_roll`? Bank right and read the sign. Tacview gets no roll until this is known.
- [ ] **Sustained turn**: hold a level turn at full power, time a circle with a stopwatch, compare with the report. Thresholds
  to confirm: under 2 m/s of climb, under 0.5 m/s² of acceleration, over 1.5 G, 3 s or more.
- [ ] **Time to climb**: counted from the start of the log; a full climb from take-off to 9,000 m.
- [ ] **A long report**: a whole flight, with a respawn in the middle.
- [ ] **Tacview**: open the `.txt.acmi` in Tacview itself (never done): track, height, heading, pitch, time. Another map than
  Afghanistan for the scale. A helicopter is exported as a fixed-wing aircraft.
- [ ] **Cockpit window** from the button, in the exe's app window: does it open as a window of its own? On a second screen,
  during a flight; gear and flaps turn red past their limit; the text says "Not flying" with no empty dials. English only.
- [ ] **Packaged exe**: `cockpit.html` and `cockpit.js` are in; first launch rebuilds the data (schema 24), once.
- [ ] **Datamine source**: the same bombing and penetration data as with the installed game (only the installed game was built).

## 2t. Research path, session recap (new)

- [ ] **Research path** against the game's tree: M1A2 gives 16 vehicles, 1,710,000 RP, 4,830,100 SL. Vehicles in a folder, and
  the first vehicle of a line, whose cost shows as `—`.
- [ ] **Session recap** (not built yet): the battle log's kill line is `=FrEB= StonewarP (␗Su-30MKK) détruit [ai] MiG-15bis`;
  the line where you get killed by someone was never seen. Note it, in French and in English.

## 2u. My battles (new)

Checked on 107 real replays of game 2.59.0.92, all Air RB and test drives. To check with other replays:

- [ ] An Arcade and a Simulator battle show AB and SB: only RB (low nibble 5 of the header's byte 688) was seen.
- [ ] A Ground and a Naval battle: their mode, vehicles (a tank + an aircraft), kills, and the damage column.
- [ ] A custom battle and an event: a mode that isn't in `cta/planes`, `tanks`, `ships` or `helicopters` shows only its difficulty.
- [ ] A replay being written during a battle: counted as not read, listed once the battle ends.

Stats in the overlay (My overlay → My stats). Only tested on made-up battle log lines: the kill lines' real format comes from the
game's language files and from one line seen in game. In a real battle, with `{kd} {winrate} {live_kills}/{live_deaths}` on a line:

- [ ] A kill and a death of yours are counted once each, and compare with the game's scoreboard at the end.
- [ ] A crash, and being shot down then crashing: one death each.
- [ ] A kill by someone else, and an AI vehicle you destroy: not counted (the replays' kills are players only).
- [ ] A Ground battle: tanks, and a respawn in an aircraft. A new battle starts the live numbers at 0.
- [ ] With the game in another language than English.
- [ ] An account whose name has a suffix in the replay (`@steam`, `@psn`): its lines are recognised, or the live numbers stay at 0.
- [ ] The past numbers take in the last battle at the start of the next one.

Teamkills. Only tested on made-up battles: a real one is rare, a custom battle with a friend is the way to get one.

- [ ] A teammate shoots you down: listed in My battles once back in the hangar (the replay has to be written first).
- [ ] An enemy shoots you down: nothing listed, nothing in `user/teamkills.json`.
- [ ] A teammate's name with a tag, with special characters, and a console one (`@psn`).
- [ ] Leaving the battle at once after the teamkill: the replay's time still covers it.

## 2v. What changed (new)

Checked on real data, 2.59.0.92 to 2.60.0.21 built one after the other. What only a real game update can show:

- [ ] At the next game update, with the installed game as the source: the banner links to the page with the number of changes, the
      page reloads by itself after a few seconds and the link stays.
- [ ] The sub-tab counts the changes until the page has been opened, not after.
- [ ] Spot-check a few rows against the game: a battle rating, a shell's penetration, a missile's range.

## 2w. Economy (new)

Repair costs and rewards match the official wiki on 26 vehicles, read at 2.59.0.92. What only the game can show:

- [ ] A vehicle's card in the game's shop shows the panel's numbers, stock and with all modules, in each mode.
- [ ] A premium vehicle's free repairs: 30 in the panel, a bought vehicle of the tree 10. The wiki doesn't list them.

## 2x. My hangar (new)

The rating and range come from the official wiki's Matchmaking page. What only the game can show:

- [ ] A ground lineup's rating here is the one shown under "To Battle!", in each mode.
- [ ] A lineup in Air Arcade: the same, with three aircraft of different ratings (A/2 + B/4 + C/4, rounded up).
- [ ] Test drive on a lineup's vehicle: the mission starts with that vehicle, ground, air and naval.
- [ ] A host vehicle chosen from the *Owned* group in Settings works in a custom vehicle mission.

## 2y. Skins and sounds (new)

Everything was checked in a made-up game folder: nothing below has run on a real install. On a real one:

- [ ] A skin installed from a `.zip` shows in the game's Customization, in the vehicle's user skins list.
- [ ] A skin of a ground vehicle in the 3D view: the camouflage on the second texture coordinates (only an aircraft was seen so far).
- [ ] A `.dds` skin in the 3D view, right way up.
- [ ] A real sound mod: Use sound mods on, the game starts and shows "Sound modification enabled".
- [ ] Turn it off, then compare `config.blk` with `user/config.blk.bak` taken before: same bytes, or only what the game saved since.
- [ ] Game running: the switch is locked, and turning on or off is refused. Close the game: it works.
- [ ] A game that exits with the line on keeps it, and the switch still turns it off.
- [ ] Uninstall, part *Skins and sound mods*: what WTFTD installed goes, what you added by hand stays, `config.blk` is back.
- [ ] macOS: the game's folders and config.blk at these paths (the running check is Windows only).

## 2z. Test bench (new)

**What was built.** In flight → Test bench writes a mission on Archipelago, the player alone in the air, and records the flight by itself once the
aircraft is in the air on that map. Checked without the game with a stand-in for port 8111 (whole flow, top speed and turn; tests on synthetic logs for each
kind of invalid run). Field names checked against a live /state on 2026-11-01: throttle reads 110 in afterburner, height and speeds are whole numbers.
Nothing has been flown yet. In game the missions are in Single missions → User missions, titled as below in the app's language (aircraft and values
are the ones picked): each one's test is in its description.

- [ ] **Test bench: Bf 109 F-4, Top speed, 6,000 m** (`wtftd_bench_bf-109f-4.blk`): the mission starts in the air, alone, clear sky, near 6,000 m and 600 km/h. Is `speed` IAS or TAS in the game? Hold level with WEP until a result shows. Does the throttle read above 100 with WEP on a propeller aircraft? Is it a realistic start, or does the game ask for a difficulty?
- [ ] Same test on a jet with afterburner: does the steady speed settle within a few minutes? `TOP_SEP` may be too strict or too loose.
- [ ] **Test bench: Bf 109 F-4, Climb, 300 m**: hold the speed asked up to 3,000 m. Does a hand-held speed pass the check (`STEADY`)? Compare the climb rate with the stat card's.
- [ ] **Test bench: Bf 109 F-4, Sustained turn, 1,000 m**: one or two full circles: does the 360° time agree with a stopwatch? Does `/indicators` give `compass` and `aviahorizon_roll` in a turn? With them blank, the map marker's heading stands in: check its direction in a turn.
- [ ] **Test bench: Bf 109 F-4, Acceleration, 500 m**: from 300 to 500 km/h: is the time close to a stopwatch's?
- [ ] **Test bench: Bf 109 F-4, Hard turn, 1,000 m**: from 450 km/h, half a circle: is 2.5 G (`HARD_G`) a fair threshold, and is 150 m (`BLEED_DH`) possible by hand?
- [ ] **Test bench: Bf 109 F-4, Stall speed, 2,000 m**: with mouse aim, then with instructor off: does the aircraft sink as expected, is the speed near the game's stall warning?
- [ ] Linux, the game played there: the game's button at the top says *Game running* (its `aces` process), Flight data draws the flight and a test above
  gives its result as on Windows. Checked so far in Ubuntu 24.04 (WSL) against a stand-in for port 8111, and with a process named `aces`.
- [ ] Linux, My overlay turned on, the game full screen: the text, the HUD, the minimap and the glow show over the game (X11 session, then
  Wayland), clicks go through, the keys and a joystick button work, the beeps play on the output picked. Checked so far in WSL's XWayland:
  the windows drawn and read back, sounds played silent; never over the game.
- [ ] Linux on a desktop (GNOME, KDE): the app window reopens where it was closed (maximized too), *Start minimized* minimizes it, *Close WTFTD
  when the game closes* closes it. WSL's window manager ignores minimizing, and counts a move from the window's corner (put back exactly all
  the same); the rest was checked there.
- [ ] Linux, Steam's launch line from Settings pasted in War Thunder's launch options: the game starts, WTFTD opens, and once the game is closed
  Steam stops counting play time even with WTFTD still open (WTFTD runs through `systemd-run --user`). Checked only with the command line mocked.
- [ ] A helicopter, **Test bench: <helicopter>, Top speed, 500 m**: air start at low speed, does `/state` send a throttle, and does the check make sense on a helicopter?
- [ ] Pause during a run (Esc): do the readings freeze, and does the time paused stay out of the result? A settled aircraft must not read as paused.
- [ ] Crash and respawn: the bare map respawns the player at 1,500 m, not at the test's height. The results keep the height flown; say if that gets in the way.
- [ ] Custom vehicle or cheats in the aircraft's setup: the page warns, the result shows the chips, it stays out of Compare.
- [ ] A real battle with a test armed, same aircraft: nothing is recorded (another map), and on the same map? Rare, but `mission_on_map` is all that tells them apart.
- [ ] Several results in several game languages: the title and description read well in the game's mission list.

## 2aa. Challenges (new)

No mission here has been played: the blocks are copied from the game's own missions, the rest is the game's to show. Before starting:
keep WTFTD open, turn **Autosave Replays** on, pick the vehicle in the app, then My missions → Challenges → *Create mission*. Missions are
under Single missions → User missions, titled `Challenge: <name> (<difficulty>) - <vehicle> - <map>`, in the app's language.

**First, on one mission**: `Challenge: Firing range (Normal) - T-72A - Shooting Range`. Destroy the 4 trucks straight ahead.

- [ ] It loads, on the Shooting Range, facing the trucks, no respawn screen.
- [ ] The objective's text shows as written in the app, and in Russian or Chinese too (app language changed, mission created again).
- [ ] The hint comes 3 s in. The timer counts down from 2:30. The HUD counts the targets left.
- [ ] All trucks destroyed: the objective is ticked, the game's victory screen 3 s later.
- [ ] In the app, a few seconds later: the row's chip says *Best …*, and My results has it. **If nothing comes**, the game names the objective otherwise: read `http://127.0.0.1:8111/mission.json` during the mission and note its `text`.
- [ ] Play again, let the timer run out: objective failed, failure screen, one more try in My results.
- [ ] Again, get destroyed (or leave the tank to burn): same failure at once, no respawn.
- [ ] Quick radio message 7 restarts the mission, and the timer starts over. Does the pause menu offer Restart too, and the failure screen?
- [ ] My battles, switch *Test drives and missions*: the mission is there, with the T-72A and *Won* or *Lost*, not *Left*.
- [ ] **Close WTFTD**, win once, open it again: does the win show? Yes means replays hold a result for a mission that ends (`status`): note it. No means WTFTD must stay open.
- [ ] A pause of 30 s in a mission: is the replay's time without it? Compare My results with the timer.

**Then one mission each.** *Normal*, in the vehicle you like, unless said.

| Mission title starts with | Do | Expect |
|---|---|---|
| `Challenge: Moving targets` | Shoot the 3 trucks crossing ahead | They drive 600 m back and forth at 30 km/h, without stopping or going off the road of their route |
| `Challenge: Hold the line` | Stay put, destroy what comes | 2 tanks of your battle rating drive at you from 1400 m and fire; next wave 5 s after, with a hint; the third wave destroyed wins. No win at the start |
| `Challenge: Gate course` | Fly to the marker | One marker at a time, on the HUD and map; 8 gates at about 1200 m; each gives a hint; the last one wins. Try it in a jet and a slow aircraft: is the time allowed fair? |
| `Challenge: Bombing run` | Destroy the 6 trucks 8 km ahead | They stand on the ground, not in the air or buried, and are marked |
| `Challenge: Air defence` | Shoot down what comes | Fighters of your battle rating come at your height 6 km out and attack; next wave 5 s after each |
| `Challenge: Missile evasion` | Break away, use flares | 2 MiG-29 turn on you and **fire missiles**: the core of it. Alive after 1:30 wins. If they only use guns, note it |
| `Challenge: Helicopter range` | Lift off, destroy the 4 trucks | Starts on the ground, engine as in a bare map; the same site as the Firing range |
| `Challenge: Naval gunnery` | Sink the 3 boats, in a ship and in a boat | The boats float, hold still, don't fire; on Port and on the fjord (the two maps) |

- [ ] The other maps of Firing range, Rocky Canyon and Falkland Islands: trucks on the ground in sight? The heights come from the game's heightmaps, trees and buildings don't.
- [ ] A truck dropped from too high or stuck in the ground: note the map and the distance.
- [ ] Hard: 10 gates, 200 m wide: reachable?

## 2ab. Fighter HUD (new)

**What was built.** My overlay → HUD draws a fighter's HUD in the overlay window from /state and /indicators. Checked without the game:
shapes for the three styles, the Tk drawing on a hidden window, the cockpit window's HUD button, the settings. The signs come from
a recorded F-15A flight (pitch > 0 nose up, bank > 0 left wing down). Nothing has been flown with it yet. Turn the overlay on, then HUD → Show it → On jets and helicopters (off by default).

- [ ] **A jet, cockpit view** (F-15A or any): the HUD shows, small, in the middle. Heading, speed in knots, altitude in feet.
- [ ] Bank left then right: the horizon line turns the same way as the game's horizon, not the other way.
- [ ] Climb and dive: the ladder moves the right way; the flight path marker drops below the nose as the angle of attack grows.
- [ ] Press the HUD key: it moves to its outside place. Go to the outside view: is the size right? Set both places to taste.
- [ ] **A MiG-29 or Su-27**: the Russian style, km/h and metres. **A J-10**: the Chinese style.
- [ ] A propeller aircraft: no HUD. Set *Show it* to *Always*: it shows.
- [ ] A tank: no HUD.
- [ ] Over the gear's speed with the gear down: the speed turns to the alert colour and flashes.
- [ ] With the HUD it reads the game every 25 ms and draws at about 60 images a second: does the game lose frames? Does the HUD still flash black?
- [ ] **A J-16** (no artificial horizon in /indicators): the ladder shows. Roll left and right, hold a turn: does it follow the real horizon
  within a few degrees, and settle back after a fast roll?
- [ ] HUD language: Russian and Chinese words show, Chinese characters included, in the overlay and the cockpit window.
- [ ] Cockpit window on a second screen, HUD button: the HUD fills it and moves with the aircraft.

## 2ac. Minimap (new)

**What was built.** My overlay → Minimap reads /map_info.json, /map_obj.json and /map.img 4 times a second and keeps your aircraft and
the objects of type airfield, capture_zone, bombing_point and defending_point only. Those type names come from memory of the API, not from
a battle: if a kind of object is missing, read `http://127.0.0.1:8111/map_obj.json` during the battle and note its `type`.

- [ ] An air battle: the map shows, your arrow points where you fly, the trail follows. No other aircraft, enemy or ally.
- [ ] Airfields as runways, ours blue and the enemy's red; `AF … km …°` leads to ours (fly that heading: does it?).
- [ ] A ground battle in a plane: capture zones show, with their colour. Bases (bombing points) in an air battle.
- [ ] Zoom ×4: the map follows you, and stops at the edge of the map.
- [ ] Round, nose up: the map turns as you turn, your arrow stays up, N shows where north is. Smooth, at about 30 images a second?
- [ ] Allied aircraft on: your team's aircraft show, in blue (squad in green); never a red one. With a colour-blind palette too?
- [ ] Allied AI units on, in an air battle: the allied artillery, SPAA and ships show, and only with that switch.
- [ ] The map picture shows, PNG or JPEG (GDI+ reads both). A dark map with marks only means it couldn't read it.
- [ ] A Simulator battle: does the minimap show your position where the game's own map doesn't? If so it must be turned off there.

## 2ad. Alarms on the lines, G load, AoA, WEP (new)

**What was built.** Every alarm lives on its line: one of the aircraft's limits in % of it (airframe, gear, flaps, G load, angle of
attack) or a condition on a value, each with its red and beep thresholds, beeps closing in up to one continuous sound at the break, its
sound, colour, flashing parts, repeat and delay. The G limit is 2 x the flight model's wing load (`CritOverload`, one wing's) over the
weight at empty mass + fuel: an estimate (an Su-30MKK pulled 11 G whole on 2026-10-31, one wing's load alone gives 6.6). Nothing of this
was heard in a real flight.

- [ ] The beeps close in: spaced at the threshold, closer and closer, continuous at 100 %. No gap at the break (beeps as long as two readings)?
- [ ] G load: a hard pull in a jet, light then loaded. Do the wings break near 100 %? Note the G shown and the G limit, with and without weapons.
- [ ] Angle of attack: a slow, high-AoA turn. Does the stall come near 100 %? Flaps out: does the limit move as the game's?
- [ ] Gear past its speed: torn off in the game, and its alarm quiet until the next spawn? Flaps the same.
- [ ] WEP left (an aircraft with water or methanol injection, the A-26B): does the throttle read past 100 % with WEP, and does the time match the game's?
- [ ] An alarm with *Only after* 500 ms: a short pull doesn't beep, a held one does.
- [ ] Sheet key held: the aircraft's sheet in place of the lines, its values right.
- [ ] A block showing the chat, one the battle log: the lines come as the game shows them, no markup.
- [ ] Keys: a mouse side button, a joystick button (the field waits for it while focused) as the show / hide key.
- [ ] Next overlay key: goes through the overlays, back to the aircraft's own at the next spawn.
- [ ] The hangar: no overlay with the Swiss F/A-18C or the F-2A ADTW (they read fuel there), nor any other aircraft.

## 3. Ammunition icons (UI only)

Shell icons (tanks), belt icons (aircraft, helicopters, ships) and flare / chaff icons come from the game's own
table (`aces.vromfs.bin_u/config/gui.blkx` → `bullet_icons`, written to `data/bullet_icons.json`). Data schema
went from 7 to 8: an installed copy rebuilds itself at first launch. Check: the rebuild happens once, the icons
match the hangar's.

- [x] 2026-10-08, Windows: rebuild to schema 8 OK (game v2.59.0.60, 58 s), icons show in the Ammunition step.
- [x] Icons compared with the hangar's (2026-10-08).

## 4. Windows regressions from the macOS work (v0.15.0)

- [x] The app opens in its Edge / Chrome app window and **quits when that window is closed** (Windows still uses
  `proc.wait()`; the close beacon is macOS only). Checked from source (`python -m wtftd`), not the exe.
- [x] Game detection (Steam), **Launch War Thunder**, **Open folder** (UserMissions).
- [x] Standalone (Gaijin launcher): simulated install in `tests/test_platform.py` (found in
  `%LOCALAPPDATA%\WarThunder` without Steam, started with its `launcher.exe`). [ ] A real standalone install.
- [x] Settings: game folder and Oodle placeholders show Windows paths.
- [x] First launch (fresh copy from source, French system): language picker above the logo, translated step
  and time left under the progress bar, no raw log; datamine download + build in 2 min 26 s; a reload does
  not start it again.
- [x] Opening a vehicle: every setup step starts closed.
- [x] Found and fixed on the way: `boot()` could run before `compare.js` / `weapons.js` were loaded
  (`bindCompare` / `bindWeapons is not defined`), and My missions guessed the vehicle from the file name.

## 5. macOS (needs a Mac with the game)

Never run with the game: detection inside `WarThunderLauncher.app`, launch, missions in `UserMissions`
inside the bundle, custom vehicle files (the CDK wiki says the Mac game may reset `content/` at launch).
