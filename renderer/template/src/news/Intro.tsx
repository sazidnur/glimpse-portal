// Intro.tsx — series title card: logo mark pops with rings, series name slams
// in, intro line + date rise. Exits by scaling down into the first story.
import React from "react";
import { AbsoluteFill, Img, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";
import { Finish } from "../components/Layers";
import { HeroText, RiseIn, SlamIn } from "../components/Text";
import type { NewsShortProps } from "./schema";
import { NewsBg, alpha, resolveSrc } from "./ui";

export const Intro: React.FC<{ p: NewsShortProps }> = ({ p }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const c = p.brand.colors;

  const logo = spring({ frame: frame - 2, fps, config: theme.spring.bouncy });
  const rings = [3, 9].map((d) => spring({ frame: frame - d, fps, config: theme.spring.smooth }));
  const out = interpolate(frame, [durationInFrames - 9, durationInFrames - 1], [0, 1], {
    easing: theme.ease.in,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const breathe = 1 + Math.sin(frame / 14) * 0.01;

  return (
    <AbsoluteFill>
      <NewsBg colors={c} />
      <AbsoluteFill
        style={{
          alignItems: "center",
          justifyContent: "center",
          opacity: 1 - out,
          transform: `scale(${1 - out * 0.12}) translateY(${-out * 60}px)`,
        }}
      >
        {rings.map((r, i) => (
          <div
            key={i}
            style={{
              position: "absolute",
              top: 640,
              width: 300,
              height: 300,
              borderRadius: "50%",
              border: `3px solid ${alpha(c.white, interpolate(r, [0, 0.2, 1], [0, 0.85 - i * 0.35, 0]))}`,
              transform: `scale(${interpolate(r, [0, 1], [0.4, 2.4 + i * 0.9])})`,
            }}
          />
        ))}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 36, marginTop: -120 }}>
          <div
            style={{
              width: 300,
              height: 300,
              borderRadius: 64,
              background: c.white,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              boxShadow: "0 40px 70px -20px rgba(0,0,0,0.35)",
              opacity: logo,
              transform: `rotateY(${interpolate(logo, [0, 1], [-150, 0])}deg) scale(${interpolate(logo, [0, 1], [0.5, 1]) * breathe})`,
            }}
          >
            <Img src={resolveSrc(p.brand.logo)} style={{ width: 200, height: 200, objectFit: "contain" }} />
          </div>
          <SlamIn delay={10} from={1.5}>
            <HeroText size={112} weight={800} align="center" color={c.white} lineHeight={1.15} style={{ maxWidth: 960 }}>
              {p.series.name}
            </HeroText>
          </SlamIn>
          {p.series.intro ? (
            <RiseIn delay={18}>
              <HeroText size={46} weight={600} align="center" color={alpha(c.white, 0.9)}>
                {p.series.intro}
              </HeroText>
            </RiseIn>
          ) : null}
          {p.series.date ? (
            <RiseIn delay={24}>
              <div
                style={{
                  fontFamily: theme.fonts.display,
                  fontWeight: 600,
                  fontSize: 32,
                  lineHeight: 1,
                  color: c.white,
                  background: "rgba(255,255,255,0.18)",
                  border: "1.5px solid rgba(255,255,255,0.35)",
                  borderRadius: 999,
                  padding: "14px 28px 18px",
                }}
              >
                {p.series.date}
              </div>
            </RiseIn>
          ) : null}
        </div>
      </AbsoluteFill>
      <Finish />
    </AbsoluteFill>
  );
};
