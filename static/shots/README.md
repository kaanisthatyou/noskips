# Screenshots the landing page looks for

The landing page references these three by name and **removes the `<img>`
if the file isn't there** (`onerror="this.remove()"`), so the page is never
broken by a missing shot — it just loses a picture. Drop the real ones in and
they appear.

| file | what it should show |
|---|---|
| `widget-desk.png` | the widget floating over a *real* desktop — an actual screenshot with a wallpaper behind it, not a mockup in a browser frame. The whole pitch is that it sits on top of your work. |
| `first-press.png` | the widget's first-press state — the moment it says nobody has rated this yet. |
| `trace.gif` | the needle drawing the waveform while a track plays, then the stamp landing and the trace freezing onto the card. This is the one that travels; give it real space. |

Keep them under a megabyte each — they're served from the same function as the
pages, and the front page shouldn't cost anyone a slow first load.
