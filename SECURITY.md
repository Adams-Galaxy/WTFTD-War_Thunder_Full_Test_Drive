# Security

## Reporting a problem

Please **don't open a public issue** for a security problem. Report it privately: on this repository, go to
**Security → Report a vulnerability** (GitHub's private vulnerability reporting). Describe what you found,
how to reproduce it and what it allows; you'll get an answer as soon as possible, and credit in the release
notes if you wish.

Only the latest release is supported: fixes ship in a new version.

## What WTFTD does on your PC

- **Local server only.** The app runs a small web server on `127.0.0.1` (never reachable from the network).
  It only answers WTFTD's own page: requests from other websites are refused, and that page only runs the app's own
  scripts (a Content-Security-Policy, which also stops it from loading or sending anything elsewhere).
- **Files it writes:**
  - `%LOCALAPPDATA%\WTFTD` on Windows, `~/Library/Application Support/WTFTD` on macOS (or the source folder):
    settings, saved setups, flight logs, the chat and battle log if you save them, the sounds you add, game database,
    image cache, the numbers that changed between game versions, the vehicles you mark as owned and your lineups;
  - `War Thunder\UserMissions\`: the missions you create;
  - only when you ask, `War Thunder\UserSkins\` and `War Thunder\sound\mod\`: the skins and sound mods you install. Each file is listed in
    `user\mods_manifest.json`, and only those are ever removed: what you put there by hand is shown and left alone;
  - only when you turn on *Use sound mods*, one line of `War Thunder\config.blk`, `enable_mod:b=yes` in its `sound` block, and no other byte.
    It's the one setting of the game WTFTD changes. A copy of the file stays in `user\config.blk.bak`, it's refused while the game runs,
    and turning the switch off or uninstalling puts the file back;
  - with custom vehicles on: new files under `War Thunder\content\pkg_local` and `content\pkg_user` only —
    never a path that replaces a game file. Every file is listed in `user\cdk_manifest.json` and
    *Settings → Remove custom vehicle files* deletes them.
- **Skin and sound archives are untrusted.** WTFTD doesn't browse or download mods. Nothing from a `.zip` is written until all of it has
  passed: paths that leave their folder, absolute paths, links, password-protected files and file types outside a short list (no
  executables, no scripts) refuse the whole archive, as do too many files, too large a total and compression past 300 to 1. Files
  are written under `UserSkins` and `sound\mod` only. Large files reach the app through one route of its own, which keeps the local page
  check and its own size limits; every other request stays limited to 2 MB.
- **What it reads:** with *Read my installed game*, the game's `aces`, `char`, `lang` and `mis.vromfs.bin` files, read
  only, instead of downloading the datamine; and whether the install is a dev server client: a `matchingdevmode` file, or the
  one `curCircuit` key of `config.blk`, read only, nothing else of that file.
- **The dev server's data:** only when you click *Compare with the dev server* in What changed, the community datamine is
  downloaded and built apart into WTFTD's cache, by a second WTFTD process that ends with it. *Remove* deletes both.
- **What it reads for the 3D views:** the game's `.grp` and `.dxp.bin` packs, `dynModelDesc.bin`, `riDesc.bin`, `levels/*.bin` and
  the asset lists of `aces.vromfs.bin`,
  read only, handed to the app's own page on `127.0.0.1`. Nothing is stored and nothing leaves your PC.
- **What it reads for My battles:** the header and the results at the end of the game's `Replays\*.wrpl` files, read only. A
  replay's results name every player of the battle: only your own name, squadron tag and numbers are kept, in `.cache\battles.json`. The
  one other name kept is a teammate's who shot you down, in `user\teamkills.json`: the battle log's killers stay in memory until
  the replay says which team they were on, and enemies are dropped. Nothing leaves your PC.
- **What it reads while you fly:** the game's local page on `127.0.0.1:8111`, on your PC: your aircraft's values, its
  marker on the map, the chat and the battle log, and for Challenges the state of your mission's objective. On Windows, to recognise the aircraft, one key of the game's
  `global.blk` (the aircraft it saved), read only. The overlay is a separate window: nothing is injected into the game.
- **What it downloads:** unless you read your installed game, the community
  [War Thunder datamine](https://github.com/gszabi99/War-Thunder-Datamine)
  (with your Git, or the official portable MinGit from git-for-windows); vehicle images from the
  [War Thunder wiki](https://wiki.warthunder.com/), and the release list of this repository (new version alert).
- **What it sends:** nothing. No account, no telemetry, no analytics. The Feedback button only opens GitHub's form in
  your browser, with what it lists: you read it and send it with your own account.
- **The apps** (WTFTD-<version>.exe, WTFTD-<version>.zip) are built by GitHub Actions from the released source code; each
  release lists their SHA-256 (check with `Get-FileHash WTFTD-<version>.exe` in PowerShell or
  `shasum -a 256 WTFTD-<version>.zip` in Terminal). They aren't code-signed yet, hence the SmartScreen / Gatekeeper
  warnings.
