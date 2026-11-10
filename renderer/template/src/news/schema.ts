// schema.ts — the ONLY contract between the web portal and the NewsShort template.
// Everything the portal sends is validated here; nothing visual is hard-coded.
// `normalize()` fills defaults so components can rely on every field existing.
import { z } from "zod";

// One spoken word with absolute timestamps inside the voice file (ElevenLabs
// alignment → words; same shape as @remotion/captions `Caption`).
export const wordSchema = z.object({
  text: z.string(),
  startMs: z.number(),
  endMs: z.number(),
});

export const sceneSchema = z.object({
  // story   = headline + image (default)
  // list    = ranked item (Top Daily 5) — shows `rank` big
  // verdict = rumour check — stamps `verdict` over the image near the end
  kind: z.enum(["story", "list", "verdict"]).optional(),
  title: z.string().min(1), // hero headline, keep to 2–6 words
  text: z.string().optional(), // one supporting line under the headline
  image: z.string().optional(), // https URL or a path inside /public
  imageCredit: z.string().optional(), // tiny credit under the image
  label: z.string().optional(), // chip: category / division / "দাবি"
  rank: z.number().int().optional(), // list kind: 5 … 1
  verdict: z.enum(["true", "false", "misleading", "unverified"]).optional(),
  verdictText: z.string().optional(), // overrides the stamp word (e.g. "গুজব")
  durationSeconds: z.number().positive().optional(), // explicit scene length
});

export const brandColorsSchema = z.object({
  hero: z.string().optional(), // main background colour
  heroDeep: z.string().optional(), // darker accent of hero
  heroDark: z.string().optional(), // shadow corner of hero gradient
  ink: z.string().optional(), // text on light surfaces
  paper: z.string().optional(), // light surface (outro)
  highlight: z.string().optional(), // active caption word
  white: z.string().optional(),
});

export const newsShortSchema = z.object({
  series: z.object({
    id: z.enum(["top5", "rumor", "division", "generic"]).optional(),
    name: z.string().min(1), // "টপ ডেইলি ৫"
    intro: z.string().optional(), // line under the series name
    date: z.string().optional(), // "৯ নভেম্বর ২০২৬" — shown small in the intro
    introSeconds: z.number().positive().optional(),
  }),
  brand: z
    .object({
      name: z.string().optional(),
      logo: z.string().optional(), // transparent mark (URL or /public path)
      appIcon: z.string().optional(),
      website: z.string().optional(),
      showWatermark: z.boolean().optional(), // small logo top-right during scenes
      colors: brandColorsSchema.optional(),
      badges: z
        .object({ playStore: z.string().optional(), appStore: z.string().optional() })
        .optional(),
    })
    .optional(),
  scenes: z.array(sceneSchema).min(1).max(12),
  voice: z
    .object({
      src: z.string(), // mp3/wav URL or /public path
      words: z.array(wordSchema).optional(), // word timings for captions
      volume: z.number().min(0).max(2).optional(),
      durationMs: z.number().positive().optional(), // lets scenes auto-size
      startAtSeconds: z.number().min(0).optional(), // default: after the intro
      // Play the file in pieces: seconds `from`–`to` of the file at `at` seconds after the voice starts, which leaves
      // pauses between stories. Word times are then in that same voice time.
      segments: z.array(z.object({ from: z.number(), to: z.number(), at: z.number() })).optional(),
    })
    .nullable()
    .optional(),
  music: z
    .object({
      src: z.string().nullable().optional(), // null/omitted = no music
      volume: z.number().min(0).max(1).optional(),
      loop: z.boolean().optional(),
    })
    .optional(),
  sfx: z.object({ enabled: z.boolean().optional(), volume: z.number().min(0).max(1).optional() }).optional(),
  captions: z
    .object({
      enabled: z.boolean().optional(),
      position: z.enum(["low", "mid"]).optional(),
      maxWordsPerPage: z.number().int().min(1).max(8).optional(),
    })
    .optional(),
  outro: z
    .object({
      enabled: z.boolean().optional(),
      cta: z.string().optional(),
      source: z.string().optional(), // "সূত্র: প্রথম আলো, বাসস"
      seconds: z.number().positive().optional(),
      showBadges: z.boolean().optional(),
    })
    .optional(),
});

export type NewsShortInput = z.infer<typeof newsShortSchema>;
export type Word = z.infer<typeof wordSchema>;
export type SceneInput = z.infer<typeof sceneSchema>;

// ---- Resolved (fully defaulted) props -------------------------------------------

export type Scene = Required<Pick<SceneInput, "kind" | "title">> &
  Omit<SceneInput, "kind" | "title"> & { durationSeconds: number };

export type NewsShortProps = {
  series: Required<Omit<NewsShortInput["series"], "intro" | "date">> & { intro?: string; date?: string };
  brand: {
    name: string;
    logo: string;
    appIcon: string;
    website: string;
    showWatermark: boolean;
    colors: Required<z.infer<typeof brandColorsSchema>>;
    badges: { playStore?: string; appStore?: string };
  };
  scenes: Scene[];
  voice: {
    src: string;
    words: Word[];
    volume: number;
    durationMs?: number;
    startAtSeconds: number;
    segments?: { from: number; to: number; at: number }[];
  } | null;
  music: { src: string | null; volume: number; loop: boolean };
  sfx: { enabled: boolean; volume: number };
  captions: { enabled: boolean; position: "low" | "mid"; maxWordsPerPage: number };
  outro: { enabled: boolean; cta: string; source?: string; seconds: number; showBadges: boolean };
};

export const DEFAULTS = {
  introSeconds: 2.2,
  sceneSeconds: 4.5, // when neither durationSeconds nor voice length is given
  minSceneSeconds: 2.5,
  outroSeconds: 3.2,
  brand: {
    name: "Glimpse News",
    logo: "assets/brand/glimpse-logo-mark.png",
    appIcon: "assets/brand/glimpse-app-icon.png",
    website: "glimpseapp.net",
    badges: { playStore: "assets/brand/google-play-badge-bn.png", appStore: "assets/brand/app-store-badge-bn.png" },
    colors: {
      hero: "#E24A2A",
      heroDeep: "#D15538",
      heroDark: "#B93E22",
      ink: "#111111",
      paper: "#FAFAFA",
      highlight: "#FFE066",
      white: "#FFFFFF",
    },
  },
  cta: "এখনই ডাউনলোড করুন!",
} as const;

// Fill every optional field. Scene lengths: explicit → voice-derived split → default.
export const normalize = (raw: NewsShortInput): NewsShortProps => {
  const input = newsShortSchema.parse(raw);
  const seriesId = input.series.id ?? "generic";
  const defaultKind = seriesId === "top5" ? "list" : seriesId === "rumor" ? "verdict" : "story";
  const introSeconds = input.series.introSeconds ?? DEFAULTS.introSeconds;
  const outroEnabled = input.outro?.enabled ?? true;
  const outroSeconds = outroEnabled ? (input.outro?.seconds ?? DEFAULTS.outroSeconds) : 0;

  // Auto-size scenes that have no explicit duration.
  const explicit = input.scenes.reduce((s, sc) => s + (sc.durationSeconds ?? 0), 0);
  const open = input.scenes.filter((sc) => sc.durationSeconds == null).length;
  let perOpen: number = DEFAULTS.sceneSeconds;
  if (open > 0 && input.voice?.durationMs) {
    const voiceStart = input.voice.startAtSeconds ?? introSeconds;
    const voiceEnd = voiceStart + input.voice.durationMs / 1000;
    const scenesEnd = Math.max(voiceEnd + 0.6, introSeconds + input.scenes.length * DEFAULTS.minSceneSeconds);
    perOpen = Math.max(DEFAULTS.minSceneSeconds, (scenesEnd - introSeconds - explicit) / open);
  }

  const scenes: Scene[] = input.scenes.map((sc, i) => ({
    ...sc,
    kind: sc.kind ?? defaultKind,
    rank: sc.rank ?? (defaultKind === "list" ? input.scenes.length - i : undefined),
    durationSeconds: sc.durationSeconds ?? perOpen,
  }));

  return {
    series: { id: seriesId, name: input.series.name, intro: input.series.intro, date: input.series.date, introSeconds },
    brand: {
      name: input.brand?.name ?? DEFAULTS.brand.name,
      logo: input.brand?.logo ?? DEFAULTS.brand.logo,
      appIcon: input.brand?.appIcon ?? DEFAULTS.brand.appIcon,
      website: input.brand?.website ?? DEFAULTS.brand.website,
      showWatermark: input.brand?.showWatermark ?? true,
      colors: { ...DEFAULTS.brand.colors, ...stripUndefined(input.brand?.colors ?? {}) },
      badges: input.brand?.badges ?? DEFAULTS.brand.badges,
    },
    scenes,
    voice: input.voice
      ? {
          src: input.voice.src,
          words: input.voice.words ?? [],
          volume: input.voice.volume ?? 1,
          durationMs: input.voice.durationMs,
          startAtSeconds: input.voice.startAtSeconds ?? introSeconds,
          segments: input.voice.segments,
        }
      : null,
    music: { src: input.music?.src ?? null, volume: input.music?.volume ?? 0.18, loop: input.music?.loop ?? true },
    sfx: { enabled: input.sfx?.enabled ?? true, volume: input.sfx?.volume ?? 0.7 },
    captions: {
      enabled: input.captions?.enabled ?? true,
      position: input.captions?.position ?? "low",
      maxWordsPerPage: input.captions?.maxWordsPerPage ?? 4,
    },
    outro: {
      enabled: outroEnabled,
      cta: input.outro?.cta ?? DEFAULTS.cta,
      source: input.outro?.source,
      seconds: outroSeconds,
      showBadges: input.outro?.showBadges ?? true,
    },
  };
};

const stripUndefined = <T extends object>(o: T): Partial<T> =>
  Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined)) as Partial<T>;

// Frame layout of the whole video, derived from props (used by calculateMetadata,
// the composition and the SFX cue sheet alike).
export const layoutFrames = (p: NewsShortProps, fps: number) => {
  const intro = Math.round(p.series.introSeconds * fps);
  let cursor = intro;
  const scenes = p.scenes.map((sc) => {
    const start = cursor;
    const duration = Math.round(sc.durationSeconds * fps);
    cursor += duration;
    return { start, duration };
  });
  const outro = Math.round(p.outro.seconds * fps);
  return { intro, scenes, outroStart: cursor, outro, total: cursor + outro };
};
