// portal.tsx — the Glimpse portal's render props (portal/video/api.py render_props) turned into NewsShort props.
// The portal's script opens with a spoken greeting and ends with a spoken sign-off: the greeting plays over the
// intro card, each story scene keeps its exact voice timing, and the sign-off plays over the outro.
import React from "react";
import type { CalculateMetadataFunction } from "remotion";
import { z } from "zod";
import { NEWS_FPS, NEWS_HEIGHT, NEWS_WIDTH, NewsShort } from "./NewsShort";
import { layoutFrames, normalize, type NewsShortInput } from "./schema";
import { resolveSrc } from "./ui";

const portalScene = z.object({
  narration: z.string(),
  caption: z.string(),
  imageUrl: z.string().nullable(),
  imageSource: z.string().nullable().optional(),
  images: z.array(z.object({ url: z.string(), source: z.string() })).optional(),
  sources: z.array(z.string()),
  start: z.number(),
  end: z.number(),
});

export const portalSchema = z
  .object({
    series: z.string(),
    title: z.string(),
    publishAt: z.string().optional(),
    verdict: z.enum(["false", "misleading", "true", "none"]).optional(),
    durationInSeconds: z.number(),
    audioUrl: z.string().nullable(),
    musicUrl: z.string().nullable(),
    musicVolume: z.number(),
    logoUrl: z.string().nullable(),
    scenes: z.array(portalScene).min(1),
    words: z.array(z.object({ text: z.string(), start: z.number(), end: z.number() })),
    // Where to cut the voice before each scene (seconds), found in the audio by calculateMetadata.
    voiceCuts: z.array(z.number()).optional(),
    // The series' "Template props" in the admin, passed through as NewsShort overrides.
    brand: z.record(z.string(), z.unknown()).optional(),
    captions: z.record(z.string(), z.unknown()).optional(),
    sfx: z.record(z.string(), z.unknown()).optional(),
  })
  .passthrough();

export type PortalProps = z.infer<typeof portalSchema>;
export type PortalSeries = "top5" | "rumor" | "generic";

// Each series' own music bed, used when the series has none uploaded in the admin.
const MUSIC: Record<PortalSeries, string> = {
  top5: "assets/audio/music/daily.mp3",
  rumor: "assets/audio/music/fact-check.mp3",
  generic: "assets/audio/music/pocket.mp3",
};

const VERDICT_TEXT = { false: "গুজব", misleading: "বিভ্রান্তিকর", true: "সত্য" } as const;

const banglaDate = (iso?: string) =>
  iso
    ? new Intl.DateTimeFormat("bn-BD", { day: "numeric", month: "long", year: "numeric", timeZone: "Asia/Dhaka" }).format(
        new Date(iso),
      )
    : undefined;

const ctaStart = (words: PortalProps["words"], from: number, to: number) => {
  const spoken = words.filter((w) => w.start >= from && w.start < to);
  const at = spoken.findIndex((w) => w.text.includes("Glimpse"));
  const end = at >= 0 ? at : spoken.length - 1;
  for (let i = end - 1; i >= 0; i--) {
    if (/[।?!]$/.test(spoken[i].text)) return spoken[i + 1].start;
  }
  return from;
};

// Below this level (about -48 dB) the voice counts as silent.
const QUIET = 0.004;

// The alignment marks a sentence a little after its sound starts, so the voice is cut at the middle of the longest
// silence in the 0.8 seconds before each scene, measured in the decoded audio.
const findCuts = async (src: string, starts: number[]): Promise<number[] | undefined> => {
  try {
    const file = await (await fetch(resolveSrc(src))).arrayBuffer();
    const audio = await new OfflineAudioContext(1, 1, 44100).decodeAudioData(file);
    const samples = audio.getChannelData(0);
    const rate = audio.sampleRate;
    const step = Math.round(rate / 100);
    const quiet = (from: number) => {
      let sum = 0;
      for (let i = from; i < from + step && i < samples.length; i++) sum += samples[i] ** 2;
      return Math.sqrt(sum / step) < QUIET;
    };
    return starts.map((t, n) => {
      if (n === 0) return 0;
      let best = { at: 0, length: 0 };
      let run = { at: 0, length: 0 };
      for (let i = Math.max(0, Math.round((t - 0.8) * rate)); i < Math.round((t + 0.05) * rate); i += step) {
        run = quiet(i) ? { at: run.length ? run.at : i, length: run.length + 1 } : { at: 0, length: 0 };
        if (run.length > best.length) best = run;
      }
      return best.length ? (best.at + (best.length * step) / 2) / rate : t - 0.15;
    });
  } catch {
    return undefined;
  }
};

// The intro card plays on its own with the music; the voice starts after it.
const INTRO_SECONDS = 2.2;
// Seconds of silence after each scene, so separate stories don't run into each other.
const SCENE_GAP: Record<PortalSeries, number> = { top5: 1, rumor: 0, generic: 0 };

// Which scenes are shown and where each starts in the voice (seconds), plus where the outro's voice starts.
const plan = (p: PortalProps) => {
  const framed = p.scenes.length >= 3;
  const closing = framed ? p.scenes[p.scenes.length - 1] : null;
  // The outro card starts with the sentence inviting people to the app ("…Glimpse অ্যাপে।"). Anything the closing
  // scene says before it stays on screen as one more scene, but only when it is about a story of its own.
  const cta = closing ? ctaStart(p.words, closing.start, closing.end) : 0;
  const lead = closing && closing.sources.length && cta - closing.start >= 1 ? [{ ...closing, end: cta }] : [];
  const shown = framed ? [...p.scenes.slice(0, -1), ...lead] : p.scenes;
  const starts = [...shown.map((s) => s.start), ...(closing ? [lead.length ? cta : closing.start] : [])];
  return { framed, closing, shown, starts };
};

export const toNewsShort = (series: PortalSeries, input: PortalProps): NewsShortInput => {
  const p = portalSchema.parse(input);
  const { framed, closing, shown, starts } = plan(p);
  const isStory = (i: number) => !framed || (i > 0 && i < p.scenes.length - 1);
  const storyNumber = (i: number) => (framed ? i : i + 1);

  // Pieces of the voice file and where each plays, in voice time, with a gap after every scene shown before the
  // outro. The cuts sit in the real silence before each scene (see findCuts).
  const gap = SCENE_GAP[series];
  const cuts = p.voiceCuts?.length === starts.length ? p.voiceCuts : starts.map((t, i) => (i === 0 ? 0 : t - 0.15));
  const segments = cuts.map((from, i) => ({ from, to: cuts[i + 1] ?? p.durationInSeconds, at: from + i * gap }));
  const shift = (t: number) => {
    const seg = [...segments].reverse().find((g) => t >= g.from) ?? segments[0];
    return t + seg.at - seg.from;
  };
  const outroFrom = closing ? cuts[cuts.length - 1] : p.durationInSeconds;

  const verdict = p.verdict && p.verdict !== "none" ? p.verdict : undefined;
  const firstStory = shown.findIndex((_, i) => isStory(i));
  const sources = [...new Set(p.scenes.flatMap((s) => s.sources))];

  return {
    series: {
      id: series,
      name: p.series,
      intro: p.title || undefined,
      date: banglaDate(p.publishAt),
      introSeconds: INTRO_SECONDS,
    },
    brand: { ...p.brand, ...(p.logoUrl ? { logo: p.logoUrl } : {}) },
    scenes: shown.map((s, i) => {
      const ranked = series === "top5" && isStory(i);
      const stamped = series === "rumor" && i === firstStory && verdict;
      return {
        kind: ranked ? "list" : stamped ? "verdict" : "story",
        title: s.caption,
        image: s.imageUrl ?? undefined,
        imageCredit: s.imageUrl && s.imageSource ? `ছবি: ${s.imageSource}` : undefined,
        label: s.sources.slice(0, 2).join(" · ") || undefined,
        rank: ranked ? storyNumber(i) : undefined,
        ...(stamped ? { verdict, verdictText: VERDICT_TEXT[verdict] } : {}),
        durationSeconds: segments[i].to - segments[i].from + (closing || i < shown.length - 1 ? gap : 0),
      };
    }),
    voice: p.audioUrl
      ? {
          src: p.audioUrl,
          words: p.words.map((w) => ({ text: w.text, startMs: shift(w.start) * 1000, endMs: shift(w.end) * 1000 })),
          durationMs: (p.durationInSeconds + segments.length * gap) * 1000,
          startAtSeconds: INTRO_SECONDS,
          segments,
        }
      : null,
    music: { src: p.musicUrl ?? MUSIC[series], volume: p.musicVolume },
    ...(p.captions ? { captions: p.captions } : {}),
    ...(p.sfx ? { sfx: p.sfx } : {}),
    outro: {
      source: sources.length ? `সূত্র: ${sources.join(", ")}` : undefined,
      ...(closing ? { seconds: p.durationInSeconds - outroFrom + 1.5 } : {}),
    },
  } as NewsShortInput;
};

const pixels = (url: string) =>
  new Promise<number>((resolve) => {
    const image = new Image();
    const timer = setTimeout(() => resolve(0), 10_000);
    image.onload = () => {
      clearTimeout(timer);
      resolve(image.naturalWidth * image.naturalHeight);
    };
    image.onerror = () => {
      clearTimeout(timer);
      resolve(0);
    };
    image.src = url;
  });

// Each scene shows the largest of its stories' photos, measured in the browser before the render starts.
const pickSharpest = async (p: PortalProps): Promise<PortalProps> => ({
  ...p,
  scenes: await Promise.all(
    p.scenes.map(async (scene) => {
      if (!scene.images || scene.images.length < 2) return scene;
      const sizes = await Promise.all(scene.images.map((image) => pixels(image.url)));
      const best = scene.images[sizes.indexOf(Math.max(...sizes))];
      return { ...scene, imageUrl: best.url, imageSource: best.source };
    }),
  ),
});

export const portalComposition = (series: PortalSeries) => {
  const Component: React.FC<PortalProps> = (props) => <NewsShort {...toNewsShort(series, props)} />;
  const calculateMetadata: CalculateMetadataFunction<PortalProps> = async ({ props }) => {
    const sharp = await pickSharpest(props);
    const voiceCuts = sharp.audioUrl ? await findCuts(sharp.audioUrl, plan(sharp).starts) : undefined;
    const picked = { ...sharp, voiceCuts };
    return {
      props: picked,
      durationInFrames: layoutFrames(normalize(toNewsShort(series, picked)), NEWS_FPS).total,
      fps: NEWS_FPS,
      width: NEWS_WIDTH,
      height: NEWS_HEIGHT,
    };
  };
  return { Component, calculateMetadata };
};

// What Remotion Studio shows; the portal sends the same shape with a real script and voice.
export const portalExample: PortalProps = {
  series: "আজকের পাঁচ খবর",
  title: "ঢাকায় দুই দিনে অন্তত ১৫ জায়গায় ককটেল বিস্ফোরণ",
  publishAt: "2026-11-09T14:00:00Z",
  verdict: "none",
  durationInSeconds: 14,
  audioUrl: null,
  musicUrl: null,
  musicVolume: 0.15,
  logoUrl: null,
  scenes: [
    { narration: "আজকের পাঁচ খবরে স্বাগতম।", caption: "আজকের পাঁচ খবর", imageUrl: null, sources: [], start: 0, end: 2.5 },
    { narration: "ঢাকায় দুই দিনে অন্তত ১৫ জায়গায় ককটেল বিস্ফোরণ।", caption: "ঢাকায় ১৫ জায়গায় বিস্ফোরণ", imageUrl: "news/demo/metro.jpg", imageSource: "প্রথম আলো", sources: ["প্রথম আলো"], start: 2.5, end: 7 },
    { narration: "অক্টোবরে মূল্যস্ফীতি কমে ৮ দশমিক ২৭ শতাংশ।", caption: "মূল্যস্ফীতি কিছুটা কমেছে", imageUrl: "news/demo/market.jpg", imageSource: "দ্য বিজনেস স্ট্যান্ডার্ড", sources: ["দ্য বিজনেস স্ট্যান্ডার্ড"], start: 7, end: 11 },
    { narration: "বিস্তারিত পড়ুন Glimpse অ্যাপে।", caption: "বিস্তারিত অ্যাপে", imageUrl: null, sources: [], start: 11, end: 14 },
  ],
  words: [],
};
