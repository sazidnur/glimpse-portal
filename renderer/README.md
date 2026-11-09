# News video renderer

Renders the news videos the portal writes and voices (admin: Videos). It asks the portal for the next queued video, renders it with the Remotion template, and uploads the MP4 and a thumbnail. It only talks to the portal's API, so it runs the same on the VPS or the home server.

## The template

`renderer/template/` is the Remotion project (Saad's Glimpse News Shorts). Its compositions `DailyFive`
(আজকের পাঁচ খবর), `FactCheck` (গুজব না সত্য?) and `Pocket` (আপনার পকেট), the IDs in each series' **Template**
field, take the portal's props below and turn them into the NewsShort template's props (`src/news/portal.tsx`):

- the script's first scene, the spoken greeting, plays over the intro card with the series name, the video title
  and the date; its last scene, the sign-off, plays over the outro with the app badges and the sources;
- every other scene is a story: its caption as the headline, its image, its sources as the label, and its exact
  voice timing. Daily stories get a rank badge; a fact-check's first story gets the verdict stamp;
- music is the series' upload in the admin, or else the template's own bed for that series
  (`public/assets/audio/music/`, see the licence there);
- the series' **Template props** (JSON in the admin) can override `brand` (colours, logo), `captions` and `sfx`.

The template's own `NewsTop5`, `NewsRumorCheck`, `NewsDivision` and `NewsGeneric` compositions remain for
Remotion Studio and Saad's `scripts/make-news.mjs`.

Props for every video:

```json
{
  "series": "আজকের পাঁচ খবর",
  "title": "Video title",
  "publishAt": "2026-11-09T14:00:00+00:00",
  "verdict": "none",
  "durationInSeconds": 64.2,
  "audioUrl": "https://glimpseapp.net/portal/media/video/audio/….mp3",
  "musicUrl": "https://glimpseapp.net/portal/media/video/music/….mp3",
  "musicVolume": 0.15,
  "logoUrl": "https://glimpseapp.net/portal/media/video/logo/….png",
  "scenes": [
    {
      "narration": "What the voice says",
      "caption": "On-screen text, up to 6 words",
      "imageUrl": "https://… or null",
      "imageSource": "প্রথম আলো",
      "sources": ["প্রথম আলো", "দ্য বিজনেস স্ট্যান্ডার্ড"],
      "start": 0.0,
      "end": 4.8
    }
  ],
  "words": [{"text": "আজ", "start": 0.12, "end": 0.41}]
}
```

`verdict` is `false`, `misleading` or `true` for a fact-check and `none` otherwise. `musicUrl`, `logoUrl`,
`imageUrl` and `imageSource` can be null. Scenes run back to back from 0 to `durationInSeconds`; `words` gives
each spoken word's time for the word-by-word captions.

To test the template with a real video's props in Remotion Studio, fetch them with the renderer token:

```sh
curl -H "Authorization: Token $RENDERER_TOKEN" https://glimpseapp.net/portal/api/video-renders/<video id>/
```

## Running it

1. In the admin, create a user `renderer` with the permission "Can change news video", and a token for it (Auth Token).
2. Add `RENDERER_TOKEN=<token>` to the server's `.env`.
3. `docker compose --profile renderer up -d --build renderer`

It renders one video at a time on one CPU (`cpus: 1.0` in `docker-compose.yml`), so the portal keeps the other CPU.

On the home server, build this folder and run it with `PORTAL_URL=https://glimpseapp.net/portal` and `RENDERER_TOKEN`, plus `--shm-size=1g`.
