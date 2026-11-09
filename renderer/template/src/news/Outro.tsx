// Outro.tsx — light end card: app icon, brand name, CTA, store badges, website,
// optional source line. Mirrors the reel's download scene, driven by brand props.
import React from "react";
import { AbsoluteFill, Img, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";
import { Finish } from "../components/Layers";
import { HeroText, RiseIn, SlamIn, useBreathe } from "../components/Text";
import type { NewsShortProps } from "./schema";
import { NewsBgPaper, resolveSrc } from "./ui";

export const Outro: React.FC<{ p: NewsShortProps }> = ({ p }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const c = p.brand.colors;
  const icon = spring({ frame, fps, config: theme.spring.bouncy });
  const badges = spring({ frame: frame - 14, fps, config: theme.spring.bouncy });
  const breathe = useBreathe(0.01, 16);
  const fade = interpolate(frame, [durationInFrames - 12, durationInFrames - 1], [1, 0], {
    easing: theme.ease.in,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const hasBadges = p.outro.showBadges && (p.brand.badges.playStore || p.brand.badges.appStore);

  return (
    <AbsoluteFill>
      <NewsBgPaper colors={c} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", opacity: fade }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 30, marginTop: -60 }}>
          <div
            style={{
              width: 260,
              height: 260,
              borderRadius: 60,
              overflow: "hidden",
              boxShadow: "0 40px 70px -20px rgba(0,0,0,0.3)",
              opacity: icon,
              transform: `rotateY(${interpolate(icon, [0, 1], [-140, 0])}deg) scale(${interpolate(icon, [0, 1], [0.6, 1]) * breathe})`,
            }}
          >
            <Img src={resolveSrc(p.brand.appIcon)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          </div>
          <RiseIn delay={6}>
            <HeroText size={64} weight={700} latin align="center" color={c.ink} letterSpacing="-0.02em">
              {p.brand.name}
            </HeroText>
          </RiseIn>
          <SlamIn delay={10} from={1.4}>
            <HeroText size={76} weight={800} align="center" color={c.heroDeep} style={{ maxWidth: 940 }}>
              {p.outro.cta}
            </HeroText>
          </SlamIn>
          {hasBadges ? (
            <div
              style={{
                display: "flex",
                gap: 24,
                marginTop: 10,
                opacity: badges,
                transform: `translateY(${interpolate(badges, [0, 1], [30, 0])}px) scale(${interpolate(badges, [0, 1], [0.9, 1])})`,
              }}
            >
              {p.brand.badges.playStore ? (
                <Img src={resolveSrc(p.brand.badges.playStore)} style={{ height: 96, display: "block" }} />
              ) : null}
              {p.brand.badges.appStore ? (
                <Img src={resolveSrc(p.brand.badges.appStore)} style={{ height: 96, display: "block" }} />
              ) : null}
            </div>
          ) : null}
          <RiseIn delay={20}>
            <HeroText size={40} weight={600} latin align="center" color={theme.colors.inkSoft}>
              {p.brand.website}
            </HeroText>
          </RiseIn>
        </div>
      </AbsoluteFill>
      {p.outro.source ? (
        <div style={{ position: "absolute", left: 80, right: 80, top: 1560, textAlign: "center", opacity: fade }}>
          <RiseIn delay={24} distance={20}>
            <div style={{ fontFamily: theme.fonts.display, fontWeight: 500, fontSize: 30, color: theme.colors.inkSoft, lineHeight: 1.4 }}>
              {p.outro.source}
            </div>
          </RiseIn>
        </div>
      ) : null}
      <Finish light />
    </AbsoluteFill>
  );
};
