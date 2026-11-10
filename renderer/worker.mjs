// Claims queued news videos from the portal, renders them with the Remotion template, and uploads the MP4 and thumbnail.
import {bundle} from '@remotion/bundler';
import {renderMedia, renderStill, selectComposition} from '@remotion/renderer';
import {execFile} from 'node:child_process';
import {openAsBlob} from 'node:fs';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {setTimeout as sleep} from 'node:timers/promises';
import {promisify} from 'node:util';

const portal = process.env.PORTAL_URL.replace(/\/$/, '');
const headers = {Authorization: `Token ${process.env.RENDERER_TOKEN}`};
const pollMs = Number(process.env.POLL_SECONDS ?? 30) * 1000;
const concurrency = Number(process.env.RENDER_CONCURRENCY ?? 1);

// The template's music beds and sound effects are balanced for a voice at this loudness; a quieter voice gets
// quieter music and effects, so the voice always sits the same distance above them.
const REFERENCE_LUFS = -16;
const DEFAULT_SFX_VOLUME = 0.7;
// Facebook and YouTube play at -14 LUFS.
const TARGET_LUFS = -14;
const MAX_PEAK_DB = -1.5;

const serveUrl = await bundle({entryPoint: path.resolve(process.env.REMOTION_ENTRY ?? 'src/index.ts')});
console.log('Template bundled, waiting for videos');

for (;;) {
  const job = await claim();
  if (job) {
    await render(job);
  } else {
    await sleep(pollMs);
  }
}

async function claim() {
  try {
    const response = await fetch(`${portal}/api/video-renders/claim/`, {method: 'POST', headers});
    if (response.status === 204) return null;
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${(await response.text()).slice(0, 300)}`);
    return await response.json();
  } catch (error) {
    console.error('Claim failed:', error.message);
    return null;
  }
}

async function render({id, composition: compositionId, props}) {
  const dir = await mkdtemp(path.join(tmpdir(), `video-${id}-`));
  const result = new FormData();
  try {
    console.log(`Video ${id}: rendering ${compositionId}`);
    if (props.audioUrl) {
      const voice = (await loudness(props.audioUrl)).lufs;
      const music = props.musicUrl ? (await loudness(props.musicUrl)).lufs : REFERENCE_LUFS;
      const sfx = props.sfx ?? {};
      props = {
        ...props,
        musicVolume: Math.min(1, props.musicVolume * 10 ** ((voice - music) / 20)),
        sfx: {...sfx, volume: Math.min(1, (sfx.volume ?? DEFAULT_SFX_VOLUME) * 10 ** ((voice - REFERENCE_LUFS) / 20))},
      };
    }
    const composition = await selectComposition({serveUrl, id: compositionId, inputProps: props});
    const video = path.join(dir, 'video.mp4');
    const thumbnail = path.join(dir, 'thumbnail.jpg');
    let logged = 0;
    await renderMedia({
      composition, serveUrl, codec: 'h264', outputLocation: video, inputProps: props, concurrency,
      chromiumOptions: {enableMultiProcessOnLinux: true},
      onProgress: ({progress}) => {
        if (progress - logged >= 0.1) {
          logged = progress;
          console.log(`Video ${id}: ${Math.round(progress * 100)}%`);
        }
      },
    });
    // One gain for the whole video, so pauses stay quiet, and never so much that the loudest peak clips.
    const levelled = path.join(dir, 'levelled.mp4');
    const measured = await loudness(video);
    const gain = Math.min(TARGET_LUFS - measured.lufs, MAX_PEAK_DB - measured.peak);
    await ffmpeg(['-v', 'error', '-y', '-i', video, '-af', `volume=${gain.toFixed(2)}dB`,
      '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', levelled]);
    await renderStill({
      composition, serveUrl, output: thumbnail, inputProps: props, imageFormat: 'jpeg',
      frame: Math.min(composition.fps * 2, composition.durationInFrames - 1),
    });
    result.append('video', await openAsBlob(levelled), 'video.mp4');
    result.append('thumbnail', await openAsBlob(thumbnail), 'thumbnail.jpg');
  } catch (error) {
    console.error(`Video ${id} failed:`, error);
    result.append('error', String(error?.message ?? error).slice(0, 1000));
  }
  try {
    const response = await fetch(`${portal}/api/video-renders/${id}/`, {method: 'POST', headers, body: result});
    console.log(`Video ${id}: reported, HTTP ${response.status}`);
  } catch (error) {
    // The portal hands the video out again once the render counts as lost.
    console.error(`Video ${id}: report failed:`, error.message);
  } finally {
    await rm(dir, {recursive: true, force: true});
  }
}

function ffmpeg(args) {
  return promisify(execFile)('npx', ['remotion', 'ffmpeg', ...args], {maxBuffer: 16 * 1024 * 1024});
}

// Integrated loudness (LUFS) and true peak (dBTP) of a local file or URL.
async function loudness(src) {
  const {stderr} = await ffmpeg(['-hide_banner', '-nostats', '-i', src, '-vn', '-af', 'loudnorm=print_format=json', '-f', 'null', '-']);
  const json = stderr.slice(stderr.lastIndexOf('{'), stderr.lastIndexOf('}') + 1);
  const {input_i: lufs, input_tp: peak} = JSON.parse(json);
  if (!Number.isFinite(Number(lufs))) throw new Error(`Could not measure the loudness of ${src}`);
  return {lufs: Number(lufs), peak: Number(peak)};
}
