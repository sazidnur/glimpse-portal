#!/usr/bin/env node
// make-news.mjs — story folder → finished news short.
//
//   node scripts/make-news.mjs inbox/<story>            # TTS + props + render
//   node scripts/make-news.mjs inbox/<story> --no-tts   # skip ElevenLabs (silent preview)
//   node scripts/make-news.mjs inbox/<story> --no-render  # only write props.json
//
// inbox/<story>/story.json = the NewsShort props (see src/news/schema.ts) plus:
//   "composition": "NewsTop5" | "NewsRumorCheck" | "NewsDivision" | "NewsGeneric"
//   scenes[].narration : what the voice says for that scene (defaults to title + text)
//   scenes[].image     : a file next to story.json, a /public path, or an https URL
//   "tts": { "voiceId", "modelId", "speed", "stability" }   (optional overrides)
//
// Needs ELEVENLABS_API_KEY (and optionally ELEVENLABS_VOICE_ID) in .env.
// The same steps, minus the shell, are what the portal's render worker will run.
import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { basename, dirname, extname, join, resolve } from "node:path";
import { spawn } from "node:child_process";
import "dotenv/config";

const args = process.argv.slice(2);
const storyArg = args.find((a) => !a.startsWith("--"));
if (!storyArg) {
  console.error("usage: node scripts/make-news.mjs <inbox/story-folder | story.json> [--no-tts] [--no-render]");
  process.exit(1);
}
const noTts = args.includes("--no-tts");
const noRender = args.includes("--no-render");

const storyPath = storyArg.endsWith(".json") ? resolve(storyArg) : resolve(storyArg, "story.json");
const storyDir = dirname(storyPath);
const slug = basename(storyDir).replace(/[^a-z0-9_-]+/gi, "-").toLowerCase() || "story";
const story = JSON.parse(await readFile(storyPath, "utf8"));
const { composition = "NewsGeneric", tts = {}, ...props } = story;

const publicDir = join("public", "news", slug);
const outDir = join("out", "news", slug);
await mkdir(publicDir, { recursive: true });
await mkdir(outDir, { recursive: true });

// 1. Images: copy local files next to story.json into /public so Remotion can serve them.
for (const sc of props.scenes) {
  if (!sc.image || /^(https?:|data:)/.test(sc.image) || /^(assets|news)\//.test(sc.image)) continue;
  const src = resolve(storyDir, sc.image);
  const dest = join(publicDir, basename(sc.image));
  await copyFile(src, dest);
  sc.image = `news/${slug}/${basename(sc.image)}`;
}

// 2. Voice: one ElevenLabs request for the whole script, with character timestamps.
const narrations = props.scenes.map((sc) => (sc.narration ?? [sc.title, sc.text].filter(Boolean).join("। ")).trim());
if (!noTts && !props.voice) {
  const apiKey = process.env.ELEVENLABS_API_KEY;
  if (!apiKey) throw new Error("ELEVENLABS_API_KEY missing (put it in .env) — or pass --no-tts");
  const voiceId = tts.voiceId ?? process.env.ELEVENLABS_VOICE_ID;
  if (!voiceId) throw new Error("No voice id: set tts.voiceId in story.json or ELEVENLABS_VOICE_ID in .env");
  const text = narrations.join("\n\n");
  console.log(`TTS: ${text.length} chars → ElevenLabs (${tts.modelId ?? "eleven_v3"})`);
  const res = await fetch(
    `https://api.elevenlabs.io/v1/text-to-speech/${voiceId}/with-timestamps?output_format=mp3_44100_128`,
    {
      method: "POST",
      headers: { "xi-api-key": apiKey, "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        model_id: tts.modelId ?? "eleven_v3", // Bengali needs v3 or v4
        language_code: "bn",
        seed: 42,
        voice_settings: { stability: tts.stability ?? 0.5, similarity_boost: 0.75, speed: tts.speed ?? 1.0 },
      }),
    },
  );
  if (!res.ok) throw new Error(`ElevenLabs ${res.status}: ${await res.text()}`);
  const data = await res.json();
  await writeFile(join(publicDir, "voice.mp3"), Buffer.from(data.audio_base64, "base64"));

  const al = data.alignment ?? data.normalized_alignment;
  const words = charsToWords(al.characters, al.character_start_times_seconds, al.character_end_times_seconds);
  const durationMs = Math.round(al.character_end_times_seconds.at(-1) * 1000);

  // 3. Scene lengths from the words: scene i owns the next N words of its narration.
  let wi = 0;
  let prevEnd = 0;
  props.scenes.forEach((sc, i) => {
    const n = narrations[i].split(/\s+/).filter(Boolean).length;
    const last = words[Math.min(wi + n, words.length) - 1];
    wi += n;
    const endS = last ? last.endMs / 1000 : prevEnd + 3;
    const isLast = i === props.scenes.length - 1;
    const tail = isLast ? 0.9 : 0.45; // breathing room after the last word
    sc.durationSeconds = Math.max(2.5, +(endS + tail - prevEnd).toFixed(2));
    prevEnd = endS + tail;
  });
  props.voice = { src: `news/${slug}/voice.mp3`, words, durationMs };
  console.log(`voice: ${(durationMs / 1000).toFixed(1)} s, ${words.length} words`);
}

// 4. Props for the renderer (narration/tts are pipeline-only fields).
for (const sc of props.scenes) delete sc.narration;
const propsPath = join(outDir, "props.json");
await writeFile(propsPath, JSON.stringify(props, null, 2));
console.log(`props → ${propsPath}`);

// 5. Render video + cover still.
if (!noRender) {
  const mp4 = join(outDir, `${slug}.mp4`);
  await run("npx", ["remotion", "render", "src/index.ts", composition, mp4, `--props=${propsPath}`, "--codec", "h264", "--crf", "17", "--overwrite"]);
  const coverFrame = Math.round(((props.series?.introSeconds ?? 2.2) + 1.2) * 30);
  await run("npx", ["remotion", "still", "src/index.ts", composition, join(outDir, "cover.png"), `--props=${propsPath}`, `--frame=${coverFrame}`, "--overwrite"]);
  console.log(`done → ${mp4}`);
}

// ---- helpers ------------------------------------------------------------------

// ElevenLabs gives one timestamp per character; group into words on whitespace.
function charsToWords(chars, starts, ends) {
  const words = [];
  let cur = "";
  let s = 0;
  let e = 0;
  const flush = () => {
    if (cur) words.push({ text: cur, startMs: Math.round(s * 1000), endMs: Math.round(e * 1000) });
    cur = "";
  };
  chars.forEach((ch, i) => {
    if (/\s/.test(ch)) return flush();
    if (!cur) s = starts[i];
    cur += ch;
    e = ends[i];
  });
  flush();
  return words;
}

function run(cmd, cmdArgs) {
  return new Promise((res, rej) => {
    const child = spawn(cmd, cmdArgs, { stdio: "inherit", shell: process.platform === "win32" });
    child.on("exit", (code) => (code === 0 ? res() : rej(new Error(`${cmd} ${cmdArgs[1]} exited ${code}`))));
  });
}
