# Calculator source extracts

Small offline test inputs extracted from the source cache fetched on 2026-11-14 (02:01:54 UTC).
No battle outcomes were generated. Runtime test cache timestamps are set when the test writes the cache.

- `gamemaster.json`: PvPoke master game master, three species (Metagross, Snubbull, Kirlia)
  and all 20 moves referenced by their species lists. Base stats, types, moves and flags retain source values.
  Source: https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/gamemaster.json
- `event-info.json`: active Fairy female grunt entry 14. Encounters are restricted to the two
  included Rocket species. All other encounters are omitted; the third slot is empty.
  Source: https://raw.githubusercontent.com/WatWowMap/event-info/main/grunts/formatted.json

These are test subsets, not a complete current lineup or game master. The moving-master URL carries no commit identifier in the cache envelope.
WatWowMap event-info is MIT licensed. PvPoke's MIT notice follows and applies to the extracted data.

```text
MIT License

Copyright (c) 2019 pvpoke

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
