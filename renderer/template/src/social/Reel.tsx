// Reels for the portal's social posts: an uploaded clip in a Glimpse frame, the clip's own audio, optional
// word-paged Bangla subtitles and a source credit, then the silent Glimpse install end card.
// Looks: "paper" (light, orange accents), "night" (dark, orange accents), "orange" (the daily videos' full
// orange) for a 16:9 clip in a card, and "vertical" for a 9:16 clip that fills the screen.
import React from "react";
import { AbsoluteFill, Img, OffthreadVideo, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";
import { Finish } from "../components/Layers";
import { HeroText, RiseIn } from "../components/Text";
import { Captions } from "../news/Captions";
import { Outro } from "../news/Outro";
import { DEFAULTS, type NewsShortProps, type Word } from "../news/schema";
import { NewsBg, NewsBgPaper, resolveSrc } from "../news/ui";

export const FPS = 30;
export const OUTRO_SECONDS = 4.5;
export const NIGHT = "#141210"; // the Glimpse app's dark background

type Cue = [number, number, string]; // [startSec, endSec, text]
// Source-pixel crop window (1920x1080 source) reached at second `at`; the window eases between entries.
type Crop = { at: number; x: number; y: number; w: number };
export type Look = "paper" | "night" | "orange" | "vertical";
export type ReelProps = {
  clip: string; // URL or public/ path
  seconds: number; // clip length; the renderer measures it when the portal leaves it out
  chip: string;
  headline: string;
  credit?: string;
  words?: Word[]; // subtitles; none means no subtitles
  crops?: Crop[];
};

// shortcut: word times are spread across each cue by character length, not forced-aligned. Only for hand-written examples.
const toWords = (cues: Cue[]): Word[] =>
  cues.flatMap(([s, e, text]) => {
    const ws = text.split(" ");
    const total = ws.reduce((n, w) => n + w.length, 0);
    let t = s * 1000;
    return ws.map((w, i) => {
      const d = ((e - s) * 1000 * w.length) / total;
      const word = { text: w, startMs: Math.round(t), endMs: Math.round(t + d), last: i === ws.length - 1 };
      t += d;
      return word;
    });
  });

export const PARLIAMENT: ReelProps = {
  clip: "clip.mp4",
  seconds: 68.3,
  chip: "জাতীয় সংসদ থেকে",
  headline: "“কোনো দেশের কোনো এজেন্সির সাথে বসার ইতিহাস আমাদের নেই”",
  credit: "সূত্র: সংসদ টিভি",
  words: toWords([
    [0.9, 2.1, "মাননীয় স্পিকার,"],
    [4.4, 7.6, "একজন ব্যক্তি চব্বিশ ঘণ্টা আমাদের পিছনে"],
    [7.9, 10.4, "তিনি খেদমত দিয়ে যাচ্ছেন।"],
    [10.4, 13.0, "আমরা তাকে কোনো বেতন বা মজুরি দিতে পারছি না বলে দুঃখিত।"],
    [17.2, 20.5, "তিনি সন্ধ্যায় একটা বলেন, রাতে একটা বলেন,"],
    [20.5, 22.6, "পরেরদিন সকালে একটা বলেন, দুপুরে একটা বলেন,"],
    [22.6, 24.2, "এটা উনি চালিয়ে যাচ্ছেন।"],
    [25.1, 27.2, "সেই রকম একটা ফালতু লোককে রেফার করে"],
    [29.7, 33.4, "যদি বলা হয়, আমাদেরকে ইঙ্গিত করে,"],
    [33.7, 35.4, "উনি তো নামই নিয়েছেন,"],
    [35.8, 39.8, "আমাদেরকে ইঙ্গিত করে যদি বলা হয় যে ওই ধরনের কোনো এজেন্সির সাথে বসেছি,"],
    [40.1, 44.8, "তাহলে এই সারা তিনশো সদস্যের হাউজে আজকে স্পষ্টভাবে বলছি,"],
    [45.7, 49.5, "কোনো দেশের কোনো এজেন্সির সাথে বসার কোনো ইতিহাস আমাদের নেই।"],
    [52.5, 54.9, "আমরা কোনো এজেন্সির সাথে বসবো কেন?"],
    [54.9, 57.1, "আমরা একটা রাজনৈতিক দল।"],
    [57.35, 59.7, "আমরা বসবো রাজনৈতিক প্রতিপক্ষের সাথে,"],
    [61.1, 63.6, "বন্ধুদের সাথে, যদি কোনো জায়গায় বন্ধু থাকে।"],
    [65.1, 67.4, "আমরা এজেন্সির সাথে বসার তো কোনো প্রশ্নই ওঠে না।"],
  ]),
};

// Keeps a TV score bar, channel logo and corner ad out of frame by zooming in on the source.
export const GOAL: ReelProps = {
  clip: "clip2.mp4",
  seconds: 32,
  chip: "সাফ চ্যাম্পিয়নশিপ · বাংলাদেশ বনাম শ্রীলঙ্কা",
  headline: "দেশের মাটিতে অভিষেকেই ফারহান আলি ওয়াহিদের দুর্দান্ত গোল!",
  credit: "সূত্র: T Sports",
  crops: [
    { at: 0, x: 310, y: 200, w: 1564 },
    { at: 26.8, x: 310, y: 200, w: 1564 },
    { at: 27.3, x: 400, y: 195, w: 1200 },
  ],
  words: toWords([
    [0.2, 1.3, "ফারহান আলি ওয়াহিদ,"],
    [1.4, 3.2, "নিজেই নেবেন কিনা, কাট করে ইনসাইডে"],
    [3.4, 5.2, "চমৎকার ফারহান আলি ওয়াহিদ!"],
    [5.2, 7.1, "হোয়াট আ গোল!"],
    [8.0, 11.2, "ফারহান আলি ওয়াহিদ, সিঙ্গেল মাস্টারক্লাস!"],
    [11.9, 14.2, "ফারহান আলি ওয়াহিদ যেভাবে ঢুকলেন,"],
    [14.4, 16.0, "যেভাবে ফিনিশ করলেন,"],
    [16.3, 20.5, "দেশের মাটিতে এর থেকে ড্রিম ডেবিউ আর কতজনের হয়!"],
    [21.8, 24.2, "অবিশ্বাস্য, অসাধারণ!"],
    [25.2, 27.0, "আমরা আসলে কী দেখলাম?"],
    [27.0, 29.6, "আমরা যা দেখলাম, তা বারবার আমাদেরকে দেখতে হবে!"],
    [29.6, 31.6, "ফারহান আলি ওয়াহিদ, তিনি কাঁধেই থাকবেন!"],
  ]),
};

const C = DEFAULTS.brand.colors;
// Text and accent colours per look. Orange stays the brand accent; only the "orange" look is orange all over.
const LOOKS = {
  paper: { text: C.ink, soft: theme.colors.inkSoft, chipBg: C.hero, chipFg: C.white, cardBorder: `6px solid ${C.white}`, light: true },
  night: { text: C.white, soft: "rgba(255,255,255,0.6)", chipBg: C.hero, chipFg: C.white, cardBorder: "2px solid rgba(255,255,255,0.14)", light: false },
  orange: { text: C.white, soft: "rgba(255,255,255,0.85)", chipBg: "rgba(255,255,255,0.18)", chipFg: C.white, cardBorder: `6px solid ${C.white}`, light: false },
  vertical: { text: C.white, soft: "rgba(255,255,255,0.75)", chipBg: C.hero, chipFg: C.white, cardBorder: "none", light: false },
} as const;

const props = (words: Word[]) =>
  ({
    brand: { ...DEFAULTS.brand, name: "Glimpse", website: "", showWatermark: true }, // the store badges replace the URL
    voice: { src: "", words, volume: 1, startAtSeconds: 0 },
    captions: { enabled: words.length > 0, position: "mid", maxWordsPerPage: 4 },
    outro: { enabled: true, cta: "আজই ইনস্টল করুন Glimpse অ্যাপ", seconds: OUTRO_SECONDS, showBadges: true, badgeHeight: 77 },
  }) as unknown as NewsShortProps; // Captions/Outro only read these fields

const Background: React.FC<{ look: Look }> = ({ look }) => {
  const frame = useCurrentFrame();
  if (look === "orange") return <NewsBg colors={C} />;
  if (look === "paper") return <NewsBgPaper colors={C} />;
  const d = Math.sin(frame / 70) * 50;
  return (
    <AbsoluteFill style={{ background: NIGHT }}>
      <div style={{ position: "absolute", width: 1400, height: 1400, borderRadius: "50%", top: -760 + d, left: -260, filter: "blur(90px)", background: `radial-gradient(circle, ${C.hero}55, transparent 62%)` }} />
    </AbsoluteFill>
  );
};

const TopBar: React.FC<{ chip: string; look: Look }> = ({ chip, look }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const l = LOOKS[look];
  const p = spring({ frame, fps, config: theme.spring.smooth });
  return (
    <div style={{ position: "absolute", top: 250, left: 60, right: 60, display: "flex", alignItems: "center", justifyContent: "space-between", opacity: p, transform: `translateY(${interpolate(p, [0, 1], [-20, 0])}px)` }}>
      {/* The label is optional; the empty div keeps the logo on the right. */}
      {chip.trim() ? (
        <div style={{ fontFamily: theme.fonts.display, fontWeight: 700, fontSize: 34, lineHeight: 1, color: l.chipFg, background: l.chipBg, borderRadius: 999, padding: "16px 28px 20px", maxWidth: 820, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {chip}
        </div>
      ) : <div />}
      <LogoTile size={72} />
    </div>
  );
};

const LogoTile: React.FC<{ size: number }> = ({ size }) => (
  <div style={{ width: size, height: size, borderRadius: size * 0.28, background: C.white, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 12px 24px -10px rgba(0,0,0,0.35)", flexShrink: 0 }}>
    <Img src={resolveSrc(DEFAULTS.brand.logo)} style={{ width: size * 0.72, height: size * 0.72, objectFit: "contain" }} />
  </div>
);

// Logo and name, then small store badges, so people see it is an app they can install.
const BrandLine: React.FC<{ color: string }> = ({ color }) => (
  <div style={{ position: "absolute", bottom: 210, left: 0, right: 0, display: "flex", justifyContent: "center", alignItems: "center", gap: 18 }}>
    <LogoTile size={56} />
    <HeroText size={36} weight={700} latin color={color}>
      Glimpse
    </HeroText>
    <div style={{ display: "flex", gap: 16, marginLeft: 22 }}>
      <Img src={resolveSrc(DEFAULTS.brand.badges.playStore)} style={{ height: 48, display: "block" }} />
      <Img src={resolveSrc(DEFAULTS.brand.badges.appStore)} style={{ height: 48, display: "block" }} />
    </div>
  </div>
);

const fadeOut = (durationInFrames: number) => (f: number) =>
  interpolate(f, [durationInFrames - 15, durationInFrames - 1], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

// A 16:9 clip in a card under the headline.
const CardScene: React.FC<{ r: ReelProps; p: NewsShortProps; look: Exclude<Look, "vertical"> }> = ({ r, p, look }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const l = LOOKS[look];
  const card = spring({ frame: frame - 4, fps, config: theme.spring.smooth });
  const crops = r.crops ?? [{ at: 0, x: 0, y: 0, w: 1920 }];
  const at = crops.map((c) => c.at * fps);
  const ease = { easing: theme.ease.inOut, extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
  const pick = (k: "x" | "y" | "w") => (crops.length > 1 ? interpolate(frame, at, crops.map((c) => c[k]), ease) : crops[0][k]);
  const scale = 1000 / pick("w");
  return (
    <AbsoluteFill>
      <Background look={look} />
      <TopBar chip={r.chip} look={look} />
      <div style={{ position: "absolute", top: 380, left: 60, right: 60 }}>
        <RiseIn delay={6}>
          <HeroText size={62} weight={800} color={l.text} lineHeight={1.3}>
            {r.headline}
          </HeroText>
        </RiseIn>
      </div>
      <div
        style={{
          position: "absolute", top: 640, left: 40, width: 1000, height: 563, borderRadius: 36, overflow: "hidden",
          border: l.cardBorder, background: "#000", boxShadow: "0 50px 90px -30px rgba(0,0,0,0.55)", opacity: card,
          transform: `translateY(${interpolate(card, [0, 1], [60, 0])}px) scale(${interpolate(card, [0, 1], [0.92, 1])})`,
        }}
      >
        <OffthreadVideo
          src={resolveSrc(r.clip)}
          volume={fadeOut(durationInFrames)}
          style={{ position: "absolute", width: 1920 * scale, height: 1080 * scale, left: -pick("x") * scale, top: -pick("y") * scale, objectFit: "cover" }}
        />
      </div>
      {r.credit ? (
        <div style={{ position: "absolute", top: 1218, right: 50, fontFamily: theme.fonts.display, fontWeight: 600, fontSize: 28, color: l.soft }}>{r.credit}</div>
      ) : null}
      {/* Captions sits at y=980 ("mid"); push it below the video card. */}
      <AbsoluteFill style={{ transform: "translateY(300px)" }}>
        <Captions p={p} voiceStartFrame={0} />
      </AbsoluteFill>
      <BrandLine color={l.text} />
      <Finish light={l.light} />
    </AbsoluteFill>
  );
};

// A 9:16 clip filling the screen, the headline over a dark fade at the top.
const VerticalScene: React.FC<{ r: ReelProps; p: NewsShortProps }> = ({ r, p }) => {
  const { durationInFrames } = useVideoConfig();
  const l = LOOKS.vertical;
  return (
    <AbsoluteFill style={{ background: NIGHT }}>
      <OffthreadVideo src={resolveSrc(r.clip)} volume={fadeOut(durationInFrames)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      <AbsoluteFill style={{ background: `linear-gradient(180deg, ${NIGHT}E6 0%, ${NIGHT}99 28%, transparent 46%, transparent 62%, ${NIGHT}CC 88%)` }} />
      <TopBar chip={r.chip} look="vertical" />
      <div style={{ position: "absolute", top: 370, left: 60, right: 60, borderLeft: `8px solid ${C.hero}`, paddingLeft: 26 }}>
        <RiseIn delay={6}>
          <HeroText size={56} weight={800} color={l.text} lineHeight={1.3} style={{ textShadow: "0 4px 18px rgba(0,0,0,0.5)" }}>
            {r.headline}
          </HeroText>
        </RiseIn>
        {r.credit ? (
          <div style={{ marginTop: 14, fontFamily: theme.fonts.display, fontWeight: 600, fontSize: 28, color: l.soft }}>{r.credit}</div>
        ) : null}
      </div>
      {/* "mid" captions sit at y=980; move them to the lower third, above the brand line. */}
      <AbsoluteFill style={{ transform: "translateY(460px)" }}>
        <Captions p={p} voiceStartFrame={0} />
      </AbsoluteFill>
      <BrandLine color={l.text} />
    </AbsoluteFill>
  );
};

export const reelFrames = (r: ReelProps) => Math.round((r.seconds + OUTRO_SECONDS) * FPS);

export const reel = (look: Look): React.FC<ReelProps> => {
  const Reel: React.FC<ReelProps> = (r) => {
    const p = props(r.words ?? []);
    return (
      <AbsoluteFill style={{ background: NIGHT }}>
        <Sequence durationInFrames={Math.round(r.seconds * FPS)}>
          {look === "vertical" ? <VerticalScene r={r} p={p} /> : <CardScene r={r} p={p} look={look} />}
        </Sequence>
        <Sequence from={Math.round(r.seconds * FPS)}>
          <Outro p={p} />
        </Sequence>
      </AbsoluteFill>
    );
  };
  return Reel;
};
