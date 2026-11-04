## What changes for the player

<!-- One topic per pull request. What does it do, in a few lines? Link the issue if there is one: "Fixes #12". -->

## How it was checked

<!-- The tests you ran, and what you tried in the app or in the game (vehicle, map, mode). Screenshots welcome. -->

- [ ] `python -m unittest discover -s tests -t .` passes, with a test for any new logic or fix
- [ ] Tried in the app
- [ ] Tried in the game, or it doesn't need the game

## Before you send it

- [ ] No new dependency: standard-library Python and plain JS only
- [ ] UI text in `web/locales/en.json` (other languages if you can, English is the fallback)
- [ ] Nothing from `data/`, `.cache/` or your `user/` folder, no game files
- [ ] Writes to the game folder only through new paths, never a file that replaces one of the game's
- [ ] Anything shown in flight comes from your own vehicle: no enemy, nothing that gives an edge online
- [ ] A line in `CHANGELOG.md` if players will notice it

By sending this, you agree to follow the [code of conduct](https://github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive/blob/main/CODE_OF_CONDUCT.md).
