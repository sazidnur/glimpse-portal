// portal.tsx — the Glimpse portal's render props (portal/video/api.py render_props) turned into NewsShort props.
// The portal's script opens with a spoken greeting and ends with a spoken sign-off: the greeting plays over the
// intro card, each story scene keeps its exact voice timing, and the sign-off plays over the outro.
import React from "react";
import type { CalculateMetadataFunction } from "remotion";
import { z } from "zod";
import { NEWS_FPS, NEWS_HEIGHT, NEWS_WIDTH, NewsShort } from "./NewsShort";
import { layoutFrames, normalize, type NewsShortInput } from "./schema";

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

const lastSentenceStart = (words: PortalProps["words"], from: number, to: number) => {
  const spoken = words.filter((w) => w.start >= from && w.start < to);
  for (let i = spoken.length - 2; i >= 0; i--) {
    if (/[।?!]$/.test(spoken[i].text)) return spoken[i + 1].start;
  }
  return from;
};

export const toNewsShort = (series: PortalSeries, input: PortalProps): NewsShortInput => {
  const p = portalSchema.parse(input);
  const framed = p.scenes.length >= 3;
  const opening = framed ? p.scenes[0] : null;
  const closing = framed ? p.scenes[p.scenes.length - 1] : null;
  // The outro card waits for the sign-off's last sentence ("…Glimpse অ্যাপে।"); whatever the closing scene says
  // before it stays on screen as one more story scene.
  const lastSentence = closing ? lastSentenceStart(p.words, closing.start, closing.end) : 0;
  const lead = closing && lastSentence - closing.start >= 1 ? [{ ...closing, end: lastSentence }] : [];
  const outroStart = lead.length ? lastSentence : (closing?.start ?? 0);
  const stories = framed ? [...p.scenes.slice(1, -1), ...lead] : p.scenes;
  const isSignOff = (i: number) => lead.length > 0 && i === stories.length - 1;
  const verdict = p.verdict && p.verdict !== "none" ? p.verdict : undefined;
  const sources = [...new Set(p.scenes.flatMap((s) => s.sources))];

  return {
    series: {
      id: series,
      name: p.series,
      intro: p.title || undefined,
      date: banglaDate(p.publishAt),
      ...(opening ? { introSeconds: Math.max(opening.end, 1) } : {}),
    },
    brand: { ...p.brand, ...(p.logoUrl ? { logo: p.logoUrl } : {}) },
    scenes: stories.map((s, i) => ({
      kind: series === "top5" && !isSignOff(i) ? "list" : series === "rumor" && i === 0 && verdict ? "verdict" : "story",
      title: s.caption,
      image: s.imageUrl ?? undefined,
      imageCredit: s.imageUrl && s.imageSource ? `ছবি: ${s.imageSource}` : undefined,
      label: s.sources.slice(0, 2).join(" · ") || undefined,
      rank: series === "top5" && !isSignOff(i) ? i + 1 : undefined,
      ...(series === "rumor" && i === 0 && verdict ? { verdict, verdictText: VERDICT_TEXT[verdict] } : {}),
      durationSeconds: s.end - s.start,
    })),
    voice: p.audioUrl
      ? {
          src: p.audioUrl,
          words: p.words.map((w) => ({ text: w.text, startMs: w.start * 1000, endMs: w.end * 1000 })),
          durationMs: p.durationInSeconds * 1000,
          startAtSeconds: opening ? 0 : undefined,
        }
      : null,
    music: { src: p.musicUrl ?? MUSIC[series], volume: p.musicVolume },
    ...(p.captions ? { captions: p.captions } : {}),
    ...(p.sfx ? { sfx: p.sfx } : {}),
    outro: {
      source: sources.length ? `সূত্র: ${sources.join(", ")}` : undefined,
      ...(closing ? { seconds: p.durationInSeconds - outroStart + 1.5 } : {}),
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
    const picked = await pickSharpest(props);
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
