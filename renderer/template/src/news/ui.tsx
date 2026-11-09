// ui.tsx — small shared pieces for the NewsShort template: source resolving,
// Bangla digits, the brand-coloured background, header row and image card.
import React from "react";
import { AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";
import type { NewsShortProps } from "./schema";

export type Colors = NewsShortProps["brand"]["colors"];

// Portal sends URLs; presets use /public paths. Both work everywhere.
export const resolveSrc = (s: string) => (/^(https?:|data:|blob:)/.test(s) ? s : staticFile(s));

const BN_DIGITS = ["০", "১", "২", "৩", "৪", "৫", "৬", "৭", "৮", "৯"];
export const toBanglaDigits = (n: number | string) =>
  String(n).replace(/\d/g, (d) => BN_DIGITS[Number(d)]);

// Hex → rgba string (for translucent tints of brand colours).
export const alpha = (hex: string, a: number) => {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  const n = parseInt(full.slice(0, 6), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
};

// Brand-coloured hero background — same drifting radial lights as BgOrange,
// but colours come from props so a different brand/series can retheme it.
export const NewsBg: React.FC<{ colors: Colors }> = ({ colors }) => {
  const frame = useCurrentFrame();
  const d1 = Math.sin(frame / 60) * 60;
  const d2 = Math.cos(frame / 75) * 45;
  return (
    <AbsoluteFill style={{ background: colors.hero }}>
      <div
        style={{
          position: "absolute",
          width: 1500,
          height: 1500,
          borderRadius: "50%",
          top: -500 + d2,
          left: -300 + d1,
          filter: "blur(60px)",
          background: "radial-gradient(circle, rgba(255,255,255,0.14), transparent 62%)",
        }}
      />
      <div
        style={{
          position: "absolute",
          width: 1300,
          height: 1300,
          borderRadius: "50%",
          bottom: -550 - d1 * 0.5,
          right: -450 - d2,
          filter: "blur(70px)",
          background: `radial-gradient(circle, ${alpha(colors.heroDark, 0.8)}, transparent 65%)`,
        }}
      />
    </AbsoluteFill>
  );
};

// Light background for the outro.
export const NewsBgPaper: React.FC<{ colors: Colors }> = ({ colors }) => {
  const frame = useCurrentFrame();
  const d = Math.sin(frame / 80) * 40;
  return (
    <AbsoluteFill style={{ background: colors.paper }}>
      <div
        style={{
          position: "absolute",
          width: 1400,
          height: 1400,
          borderRadius: "50%",
          top: -700 + d,
          left: -200,
          filter: "blur(80px)",
          background: `radial-gradient(circle, ${alpha(colors.hero, 0.16)}, transparent 60%)`,
        }}
      />
    </AbsoluteFill>
  );
};

// Persistent header during story scenes: series chip (left) + logo watermark (right).
// Sits at y≈260, just inside the 9:16 safe zone.
export const Header: React.FC<{ series: string; logo?: string; colors: Colors; delay?: number }> = ({
  series,
  logo,
  colors,
  delay = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: theme.spring.smooth });
  return (
    <div
      style={{
        position: "absolute",
        top: 250,
        left: 60,
        right: 60,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        opacity: p,
        transform: `translateY(${interpolate(p, [0, 1], [-20, 0])}px)`,
      }}
    >
      <div
        style={{
          fontFamily: theme.fonts.display,
          fontWeight: 700,
          fontSize: 34,
          lineHeight: 1,
          color: colors.white,
          background: "rgba(255,255,255,0.18)",
          border: "1.5px solid rgba(255,255,255,0.35)",
          borderRadius: 999,
          padding: "16px 28px 20px",
          letterSpacing: "-0.01em",
        }}
      >
        {series}
      </div>
      {logo ? (
        <div
          style={{
            width: 72,
            height: 72,
            borderRadius: 20,
            background: colors.white,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxShadow: "0 12px 24px -10px rgba(0,0,0,0.35)",
          }}
        >
          <Img src={resolveSrc(logo)} style={{ width: 52, height: 52, objectFit: "contain" }} />
        </div>
      ) : null}
    </div>
  );
};

// Image card with Ken Burns. `direction` alternates per scene so consecutive
// shots don't all zoom the same way.
export const ImageCard: React.FC<{
  src?: string;
  width: number;
  height: number;
  direction: 1 | -1;
  colors: Colors;
  style?: React.CSSProperties;
}> = ({ src, width, height, direction, colors, style }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const t = interpolate(frame, [0, durationInFrames], [0, 1], {
    easing: theme.ease.inOut,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  // The whole photo is shown (news photos are 16:9, the card is not), over a blurred copy that fills the card.
  const scale = direction === 1 ? interpolate(t, [0, 1], [1, 1.05]) : interpolate(t, [0, 1], [1.05, 1]);
  const pan = interpolate(t, [0, 1], [0, -10 * direction]);
  return (
    <div
      style={{
        width,
        height,
        borderRadius: 40,
        overflow: "hidden",
        background: alpha(colors.heroDark, 0.5),
        boxShadow: "0 50px 90px -30px rgba(0,0,0,0.55), 0 12px 24px -12px rgba(0,0,0,0.3)",
        border: "1px solid rgba(255,255,255,0.14)",
        // force a clean rounded clip of the transformed image (Chrome corner leak)
        WebkitMaskImage: "-webkit-radial-gradient(white, black)",
        isolation: "isolate",
        ...style,
      }}
    >
      {src ? (
        <>
          <Img
            src={resolveSrc(src)}
            style={{
              position: "absolute",
              width: "100%",
              height: "100%",
              objectFit: "cover",
              filter: "blur(36px) brightness(0.75)",
              transform: "scale(1.2)",
            }}
          />
          <Img
            src={resolveSrc(src)}
            style={{
              position: "absolute",
              width: "100%",
              height: "100%",
              objectFit: "contain",
              transform: `scale(${scale}) translateX(${pan}px)`,
            }}
          />
        </>
      ) : (
        // No image supplied → a quiet brand-tinted plate so the layout holds.
        <AbsoluteFill
          style={{
            background: `linear-gradient(160deg, ${alpha(colors.white, 0.18)}, ${alpha(colors.heroDark, 0.5)})`,
          }}
        />
      )}
      {/* Bottom gradient so a chip or credit stays readable over any photo */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          height: "38%",
          background: "linear-gradient(180deg, transparent, rgba(0,0,0,0.42))",
        }}
      />
    </div>
  );
};

// Stamp-style entrance scaling down from large around its CENTRE (SlamIn in
// components/Text scales from the left edge, which suits left-aligned type only).
export const StampIn: React.FC<{ delay?: number; from?: number; children: React.ReactNode }> = ({
  delay = 0,
  from = 2,
  children,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: theme.spring.slam });
  const blur = interpolate(p, [0, 0.7, 1], [10, 2, 0]);
  return (
    <div
      style={{
        opacity: interpolate(p, [0, 0.3], [0, 1], { extrapolateRight: "clamp" }),
        transform: `scale(${interpolate(p, [0, 1], [from, 1])})`,
        filter: `blur(${Math.max(0, blur)}px)`,
        transformOrigin: "center",
      }}
    >
      {children}
    </div>
  );
};

// Small white pill used for category / division / "দাবি" labels.
export const Chip: React.FC<{ text: string; colors: Colors; delay?: number; style?: React.CSSProperties }> = ({
  text,
  colors,
  delay = 0,
  style,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: theme.spring.snappy });
  return (
    <div
      style={{
        display: "inline-block",
        fontFamily: theme.fonts.display,
        fontWeight: 700,
        fontSize: 32,
        lineHeight: 1,
        color: colors.heroDeep,
        background: colors.white,
        borderRadius: 999,
        padding: "14px 26px 18px",
        boxShadow: "0 14px 30px -12px rgba(0,0,0,0.45)",
        opacity: p,
        transform: `translateY(${interpolate(p, [0, 1], [16, 0])}px) scale(${interpolate(p, [0, 1], [0.85, 1])})`,
        transformOrigin: "left center",
        ...style,
      }}
    >
      {text}
    </div>
  );
};
