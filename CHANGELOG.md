# Changelog

## 1.0.1 (2026-10-01)

Works with Aniimo build 3634150.

- A log file, `log.txt` next to `Start.bat`: what the tool found at start, and for every M press the picture it
  saved and what it did with it (map shown, which maps it could be, or not a map). If something goes wrong,
  send this file. It keeps itself small (about 1 MB, plus one older file).
- Pressing M to close the map could switch the page to a wrong map. Fixed.
- After a capture that was not the map, the next maps could be read worse for the rest of the session. Fixed.
- Captures now go in a `captures` folder next to `Start.bat` (not your Pictures folder); only the newest 10 stay.
- If the game is not in your Steam libraries, a *Choose the Aniimo folder* button lets you point at it.
- The overlay now also starts after choosing the game folder on the page.

## 1.0.0 (2026-10-01)

First public version. Works with Aniimo build 3634150.

- Press M in an Operation: Egg Heist Team Mode run and the page shows which of the 21 maps you are on, in the
  game's own map art: spawn, door, the rooms where an egg can be, keys and reward rooms.
- Tell it what you are playing (Normal, Hard, Nightmare / Chaos). Some maps look the same at the start; knowing
  the difficulty tells them apart. If it is not sure yet, it shows the maps it could be.
- Overlay for one monitor: drag where the map should sit over the game, set how see-through it is, F8 hides it.
- After a game update it does nothing and asks you to get a newer version here, so it never shows a wrong map.
