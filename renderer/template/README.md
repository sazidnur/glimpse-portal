# Glimpse News Shorts

Data-driven 1080 × 1920 news videos for Facebook/Instagram, built with Remotion.
One template, four series, **everything supplied from outside as input props** —
the web portal (or a script) sends JSON, Remotion renders the video.

| Composition id    | Series                 | Extra touch                              |
|-------------------|------------------------|------------------------------------------|
| `NewsTop5`        | টপ ডেইলি ৫             | rank badge counting down per scene       |
| `NewsRumorCheck`  | গুজব না সত্য?          | verdict stamp (গুজব / সত্য / বিভ্রান্তিকর) |
| `NewsDivision`    | বিভাগের খবর            | location chip                            |
| `NewsGeneric`     | any single story       | —                                        |

Each video = intro (series name, intro line, date) → one scene per story
(image with slow zoom, label chip, headline, optional supporting line, word-synced
captions) → outro (app icon, CTA, store badges, website, source line). Length is
computed from the props, so a longer story simply makes a longer video.

## Quick start

```bash
npm install
npx remotion studio                       # open a composition, edit props live
node scripts/make-news.mjs inbox/demo-top5 --no-tts    # silent preview render
```

For a real story with voice: copy `.env.example` to `.env`, add your ElevenLabs key
and a Bengali-capable voice id, create `inbox/<story>/story.json` (start from
`inbox/demo-top5/story.json`), drop the photos next to it, then

```bash
node scripts/make-news.mjs inbox/<story>
# → out/news/<story>/<story>.mp4 + cover.png + props.json
```

The script makes one ElevenLabs request (model `eleven_v3`; Bengali is not
supported by the multilingual/flash models), converts the character alignment into
word timings, sizes each scene to where its narration ends, and renders.

If Remotion can't download its headless Chrome, point it at one:
`--browser-executable=/path/to/chrome-headless-shell`. On macOS keep the project
out of `~/Downloads`, `~/Documents` and `~/Desktop` (privacy protection breaks the
browser's helper processes there).

## The contract (what the portal sends)

Defined in `src/news/schema.ts`; exported as JSON Schema to `docs/news-short.schema.json`
with one example payload per series in `docs/examples/` (`npm run news:schema` regenerates).

```jsonc
{
  "series":  { "id": "top5", "name": "টপ ডেইলি ৫", "intro": "আজকের সেরা ৫ খবর", "date": "৯ নভেম্বর ২০২৬" },
  "brand":   { "logo": "https://…/logo.png", "colors": { "hero": "#E24A2A" } },   // all optional
  "scenes":  [ { "title": "…", "text": "…", "label": "বাংলাদেশ", "image": "https://…/1.jpg",
                 "imageCredit": "ছবি: বাসস", "rank": 5, "durationSeconds": 4.2 } ],
  "voice":   { "src": "https://…/voice.mp3", "durationMs": 18200,
               "words": [ { "text": "ঢাকায়", "startMs": 0, "endMs": 310 } ] },
  "music":   { "src": "https://…/bed.mp3", "volume": 0.18 },                       // optional
  "sfx":     { "enabled": true, "volume": 0.7 },
  "captions":{ "enabled": true, "position": "low", "maxWordsPerPage": 4 },
  "outro":   { "cta": "এখনই ডাউনলোড করুন!", "source": "সূত্র: প্রথম আলো" }
}
```

Images, voice, music and logo may be https URLs or paths inside `public/`.
Scene `kind` defaults from the series (`list` / `verdict` / `story`); `verdict` is
`true | false | misleading | unverified`. Omitted fields take the Glimpse defaults.

## Rendering from code (portal worker)

```ts
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";
const serveUrl = await bundle({ entryPoint: "src/index.ts" });
const composition = await selectComposition({ serveUrl, id: "NewsTop5", inputProps });
await renderMedia({ composition, serveUrl, codec: "h264", crf: 17, inputProps, outputLocation: "out/x.mp4" });
```

`selectComposition` runs `calculateMetadata`, so the duration follows the props.
A 20 s video takes ~1–2 min on a 4 vCPU server (CPU-bound, no GPU needed).

## Layout

```
src/
  index.ts, Root.tsx           composition registration (4 series)
  news/schema.ts               props contract + defaults + frame layout
  news/presets.ts              per-series defaults / example payloads
  news/NewsShort.tsx           template: intro → scenes → outro, audio, captions
  news/Intro.tsx, StoryScene.tsx, Outro.tsx, Captions.tsx, NewsAudio.tsx, ui.tsx
  components/Layers.tsx, Text.tsx   backgrounds, grain, entrances (shared motion kit)
  theme.ts, fonts.ts, config/assets.ts
scripts/make-news.mjs          story folder → voice → props → render
scripts/export-schema.mjs      JSON Schema + examples for the portal
public/assets/{audio,brand,fonts}, public/news/demo (placeholder stills)
```
