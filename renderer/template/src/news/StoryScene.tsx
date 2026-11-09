// StoryScene.tsx — one news item: image card (Ken Burns) + chip + headline.
// kind "list" adds the rank badge, kind "verdict" slams a verdict stamp over the
// image at ~55 % of the scene. Everything comes from the scene's props.
import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";
import { Finish } from "../components/Layers";
import { RiseIn, useExit } from "../components/Text";
import type { NewsShortProps, Scene } from "./schema";
import { Chip, Header, ImageCard, NewsBg, StampIn, alpha, toBanglaDigits } from "./ui";

// Layout (1080×1920). Critical content stays inside y 240–1680 (platform-safe).
export const L = {
  card: { x: 60, y: 350, w: 960, h: 740 },
  title: { x: 70, y: 1150, w: 940 },
  rank: { size: 180 },
} as const;

// Semantic verdict colours (not brand colours — these must read the same everywhere).
const VERDICT = {
  true: { color: "#1E9E5A", text: "সত্য" },
  false: { color: "#C62828", text: "গুজব" },
  misleading: { color: "#E0A100", text: "বিভ্রান্তিকর" },
  unverified: { color: "#6B7280", text: "অযাচাইকৃত" },
} as const;

export const stampFrame = (durationInFrames: number) => Math.round(durationInFrames * 0.55);

export const StoryScene: React.FC<{ p: NewsShortProps; scene: Scene; index: number }> = ({ p, scene, index }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const c = p.brand.colors;
  const exit = useExit(durationInFrames, 10);

  // card slides in from the right (alternating) with a spring
  const cardIn = spring({ frame, fps, config: theme.spring.smooth });
  const dir = index % 2 === 0 ? 1 : -1;
  const cardX = interpolate(cardIn, [0, 1], [140 * dir, 0]);

  const words = scene.title.split(/\s+/).filter(Boolean);
  const titleSize = words.join(" ").length > 36 ? 64 : 72;

  const verdict = scene.kind === "verdict" && scene.verdict ? VERDICT[scene.verdict] : null;
  const stampAt = stampFrame(durationInFrames);
  const flash = verdict
    ? interpolate(frame, [stampAt - 2, stampAt + 2, stampAt + 14], [0, 0.55, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      })
    : 0;

  return (
    <AbsoluteFill>
      <NewsBg colors={c} />
      <AbsoluteFill style={exit}>
        <Header series={p.series.name} logo={p.brand.showWatermark ? p.brand.logo : undefined} colors={c} />

        {/* image card */}
        <div
          style={{
            position: "absolute",
            left: L.card.x,
            top: L.card.y,
            opacity: cardIn,
            transform: `translateX(${cardX}px) scale(${interpolate(cardIn, [0, 1], [0.96, 1])})`,
          }}
        >
          <ImageCard src={scene.image} width={L.card.w} height={L.card.h} direction={dir as 1 | -1} colors={c} />
          {scene.imageCredit ? (
            <div
              style={{
                position: "absolute",
                left: 12,
                top: L.card.h + 14,
                fontFamily: theme.fonts.display,
                fontWeight: 500,
                fontSize: 24,
                color: alpha(c.white, 0.85),
              }}
            >
              {scene.imageCredit}
            </div>
          ) : null}
          {verdict ? (
            <AbsoluteFill style={{ borderRadius: 40, background: verdict.color, opacity: flash }} />
          ) : null}
        </div>

        {/* category / division / claim chip, bottom-left inside the card */}
        {scene.label ? (
          <Chip
            text={scene.label}
            colors={c}
            delay={10}
            style={{ position: "absolute", left: L.card.x + 32, top: L.card.y + L.card.h - 96 }}
          />
        ) : null}

        {/* rank badge for Top-N lists, bottom-right corner of the card */}
        {scene.kind === "list" && scene.rank != null ? (
          <div style={{ position: "absolute", right: 36, top: L.card.y + L.card.h - L.rank.size / 2 - 40 }}>
            <StampIn delay={8} from={2}>
              <div
                style={{
                  width: L.rank.size,
                  height: L.rank.size,
                  borderRadius: 44,
                  background: c.white,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  boxShadow: "0 30px 60px -20px rgba(0,0,0,0.5)",
                  fontFamily: theme.fonts.display,
                  fontWeight: 800,
                  fontSize: 120,
                  lineHeight: 1,
                  color: c.heroDeep,
                  paddingBottom: 8,
                }}
              >
                {toBanglaDigits(scene.rank)}
              </div>
            </StampIn>
          </div>
        ) : null}

        {/* headline, word by word */}
        <div style={{ position: "absolute", left: L.title.x, top: L.title.y, width: L.title.w }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0px 22px", alignItems: "flex-end" }}>
            {words.map((w, i) => (
              <RiseIn key={i} delay={6 + i * 3} distance={34} config={theme.spring.snappy}>
                <span
                  style={{
                    display: "inline-block",
                    fontFamily: theme.fonts.display,
                    fontWeight: 800,
                    fontSize: titleSize,
                    lineHeight: 1.2,
                    letterSpacing: "-0.01em",
                    color: c.white,
                    padding: "0.06em 0", // room for matras — never clip glyphs
                  }}
                >
                  {w}
                </span>
              </RiseIn>
            ))}
          </div>
          {scene.text ? (
            <RiseIn delay={10 + words.length * 3} distance={26}>
              <div
                style={{
                  marginTop: 14,
                  fontFamily: theme.fonts.display,
                  fontWeight: 500,
                  fontSize: 40,
                  lineHeight: 1.3,
                  color: alpha(c.white, 0.86),
                  padding: "0.06em 0",
                }}
              >
                {scene.text}
              </div>
            </RiseIn>
          ) : null}
        </div>

        {/* verdict stamp */}
        {verdict ? (
          <div
            style={{
              position: "absolute",
              left: L.card.x,
              top: L.card.y,
              width: L.card.w,
              height: L.card.h,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <StampIn delay={stampAt} from={2.4}>
              <div
                style={{
                  transform: "rotate(-8deg)",
                  background: c.white,
                  border: `8px solid ${verdict.color}`,
                  borderRadius: 32,
                  padding: "18px 56px 30px",
                  boxShadow: "0 40px 80px -20px rgba(0,0,0,0.5)",
                  fontFamily: theme.fonts.display,
                  fontWeight: 800,
                  fontSize: 112,
                  lineHeight: 1.1,
                  color: verdict.color,
                  letterSpacing: "-0.01em",
                }}
              >
                {scene.verdictText ?? verdict.text}
              </div>
            </StampIn>
          </div>
        ) : null}
      </AbsoluteFill>
      <Finish />
    </AbsoluteFill>
  );
};
