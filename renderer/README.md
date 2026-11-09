# News video renderer

Renders the news videos the portal writes and voices (admin: Videos). It asks the portal for the next queued video, renders it with the Remotion template, and uploads the MP4 and a thumbnail. It only talks to the portal's API, so it runs the same on the VPS or the home server.

## The template

Put the Remotion project in `renderer/template/` (its `package.json` and `src/index.ts` at the top). It needs:

- One composition per series, with the ID set in the series' **Template** field: `DailyFive` (আজকের ৫ খবর), `FactCheck` (গুজব না সত্য), `Pocket` (আপনার পকেটে).
- 1080×1920 at 30 fps, and `calculateMetadata` that sets the length from `durationInSeconds`.
- Everything below read from props, nothing hard-coded. The series' **Template props** (JSON in the admin) are merged in at the top level, for colours, intro text and the like.
- Its own fonts (Noto Serif Bengali / Noto Sans Bengali), loaded from the project.

Props for every video:

```json
{
  "series": "আজকের ৫ খবর",
  "title": "Video title",
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
      "sources": ["প্রথম আলো", "দ্য বিজনেস স্ট্যান্ডার্ড"],
      "start": 0.0,
      "end": 4.8
    }
  ],
  "words": [{"text": "আজ", "start": 0.12, "end": 0.41}]
}
```

`musicUrl`, `logoUrl` and `imageUrl` can be null. Scenes run back to back from 0 to `durationInSeconds`; `words` gives each spoken word's time for word-by-word captions.

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
