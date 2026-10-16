# Changelog

## 1.1.0 (unreleased)

Works with Aniimo build 3732728.

- Second floors. Rooms that have an upstairs are outlined and tagged 2F on the map.
- On the page, a Ground / Upper switch shows the game's own picture of the upper floors. A line under it says
  which floor the eggs, the keys and the door are on. On every map so far: all on the ground floor.
- On the overlay, each second floor is drawn next to its room with a red arrow from the room to it, so both
  floors are in one map. The *Second floors* button on the page turns this off if you want the map bigger.
- Locked rooms can have an egg. Inside a locked room the game puts a nest in some runs only, and the map now
  shows it with how often: 16% to 25% on Normal, 25% to 50% on Hard, 21% to 50% on Nightmare and Chaos. On
  Chaos these are the only nests shown. Thanks to the player who reported it.
- On Hard map 20045 and Nightmare / Chaos maps 20032, 20034, 20037, 20039 and 20040, one locked room had no key
  on the map. Fixed: every locked room shows its key.
- The first start after updating reads the map pictures again (about 20 seconds): it now keeps the upper floors
  too.

## 1.0.4 (2026-10-15)

Works with Aniimo build 3732728.

- Aniimo updated on 2026-10-15 and 1.0.3 stopped, as it should. This version works with the new game build.
  The Egg Heist maps did not change in that update.
- If the page still names the old build after you update, start the game once, then start the tool again: the
  game only notes its new build number when it starts.

## 1.0.3 (2026-10-14)

Works with Aniimo build 3714366.

- Aniimo updated on 2026-10-14 and 1.0.2 stopped, as it should. This version works with the new game build.
  The Egg Heist maps did not change in that update.
- If the page still names the old build after you update, start the game once, then start the tool again: the
  game only notes its new build number when it starts.

## 1.0.2 (2026-10-10)

Works with Aniimo build 3668494.

- Aniimo updated on 2026-10-09 and 1.0.1 stopped, as it should. This version works with the new game build.
  The Egg Heist maps did not change in that update.
- If the page still names the old build after you update, start the game once, then start the tool again: the
  game only notes its new build number when it starts.

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
