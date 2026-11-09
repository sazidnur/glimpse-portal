import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";

type Base = {
  children: React.ReactNode;
  size: number;
  color?: string;
  weight?: number;
  italic?: boolean;
  latin?: boolean; // use the Latin-first stack (brand name, URL)
  align?: "left" | "center" | "right";
  style?: React.CSSProperties;
  lineHeight?: number;
  letterSpacing?: string;
};

const baseStyle = (p: Base): React.CSSProperties => ({
  fontFamily: p.latin ? theme.fonts.latin : theme.fonts.display,
  fontWeight: p.weight ?? 800,
  fontSize: p.size,
  lineHeight: p.lineHeight ?? 1.18,
  letterSpacing: p.letterSpacing ?? "-0.01em",
  color: p.color ?? theme.colors.white,
  textAlign: p.align ?? "left",
  // Bangla has no italic; a gentle skew gives the "WANT" slant from the reference
  transform: p.italic ? "skewX(-9deg)" : undefined,
  whiteSpace: "pre-wrap",
  margin: 0,
  padding: "0.08em 0.12em", // room for matras/descenders — never clip glyphs
  ...p.style,
});

export const HeroText: React.FC<Base> = (p) => <div style={baseStyle(p)}>{p.children}</div>;

// Outlined (hollow) text — used for the "A NEWS APP" / echo lines.
export const OutlineText: React.FC<Base & { stroke?: number; strokeColor?: string }> = (p) => (
  <div
    style={{
      ...baseStyle(p),
      color: "transparent",
      WebkitTextStroke: `${p.stroke ?? 2.5}px ${p.strokeColor ?? theme.colors.white}`,
    }}
  >
    {p.children}
  </div>
);

// ---- Animation wrappers -------------------------------------------------------

// Slam: scales down from large with a blur, like a stamp hitting the page.
export const SlamIn: React.FC<{ delay?: number; children: React.ReactNode; from?: number }> = ({
  delay = 0,
  children,
  from = 1.7,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: theme.spring.slam });
  const blur = interpolate(p, [0, 0.7, 1], [12, 2, 0]);
  return (
    <div
      style={{
        opacity: interpolate(p, [0, 0.35], [0, 1], { extrapolateRight: "clamp" }),
        transform: `scale(${interpolate(p, [0, 1], [from, 1])})`,
        filter: `blur(${Math.max(0, blur)}px)`,
        transformOrigin: "left center",
      }}
    >
      {children}
    </div>
  );
};

// Rise: fade + translateY + slight scale (the workhorse entrance).
export const RiseIn: React.FC<{
  delay?: number;
  children: React.ReactNode;
  distance?: number;
  config?: { damping: number; stiffness: number; mass: number };
  style?: React.CSSProperties;
}> = ({ delay = 0, children, distance = 46, config = theme.spring.smooth, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config });
  return (
    <div
      style={{
        opacity: p,
        transform: `translateY(${interpolate(p, [0, 1], [distance, 0])}px) scale(${interpolate(p, [0, 1], [0.94, 1])})`,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

// Horizontal motion-blur reveal, like "ACTUALLY" streaking in.
export const StreakIn: React.FC<{ delay?: number; children: React.ReactNode; fromX?: number }> = ({
  delay = 0,
  children,
  fromX = -160,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: theme.spring.snappy });
  const x = interpolate(p, [0, 1], [fromX, 0]);
  const stretch = interpolate(p, [0, 0.6, 1], [1.6, 1.05, 1]);
  const blur = interpolate(p, [0, 0.7, 1], [18, 3, 0]);
  return (
    <div
      style={{
        opacity: interpolate(p, [0, 0.3], [0, 1], { extrapolateRight: "clamp" }),
        transform: `translateX(${x}px) scaleX(${stretch})`,
        transformOrigin: "left center",
        filter: `blur(${Math.max(0, blur)}px)`,
      }}
    >
      {children}
    </div>
  );
};

// Wipe-reveal using clip-path — for swapping one hero word for another.
export const WipeIn: React.FC<{ delay?: number; duration?: number; children: React.ReactNode }> = ({
  delay = 0,
  duration = 12,
  children,
}) => {
  const frame = useCurrentFrame();
  const t = interpolate(frame, [delay, delay + duration], [0, 1], {
    easing: theme.ease.out,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <div style={{ clipPath: `inset(0 ${(1 - t) * 100}% 0 0)`, opacity: t > 0 ? 1 : 0 }}>{children}</div>
  );
};

export const WipeOut: React.FC<{ at: number; duration?: number; children: React.ReactNode }> = ({
  at,
  duration = 10,
  children,
}) => {
  const frame = useCurrentFrame();
  const t = interpolate(frame, [at, at + duration], [0, 1], {
    easing: theme.ease.in,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return <div style={{ clipPath: `inset(0 0 0 ${t * 100}%)`, opacity: t >= 1 ? 0 : 1 }}>{children}</div>;
};

// Scene-level exit: everything lifts and fades in the last frames.
export const useExit = (durationInFrames: number, len = 10) => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [durationInFrames - len, durationInFrames - 1], [1, 0], {
    easing: theme.ease.in,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const y = interpolate(frame, [durationInFrames - len, durationInFrames - 1], [0, -40], {
    easing: theme.ease.in,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return { opacity: o, transform: `translateY(${y}px)` } as React.CSSProperties;
};

// Idle breathing for anything on screen longer than ~2 s.
export const useBreathe = (amount = 0.012, speed = 22) => {
  const frame = useCurrentFrame();
  return 1 + Math.sin(frame / speed) * amount;
};
