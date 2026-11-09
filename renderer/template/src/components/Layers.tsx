import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { theme } from "../theme";

// Orange hero background — never flat: a slow-drifting lighter core and darker corners.
export const BgOrange: React.FC = () => {
  const frame = useCurrentFrame();
  const d1 = Math.sin(frame / 60) * 60;
  const d2 = Math.cos(frame / 75) * 45;
  return (
    <AbsoluteFill style={{ background: theme.colors.hero }}>
      <div
        style={{
          position: "absolute",
          width: 1500,
          height: 1500,
          borderRadius: "50%",
          top: -500 + d2,
          left: -300 + d1,
          filter: "blur(60px)",
          background: `radial-gradient(circle, rgba(255,255,255,0.14), transparent 62%)`,
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
          background: `radial-gradient(circle, ${theme.colors.heroDark}CC, transparent 65%)`,
        }}
      />
    </AbsoluteFill>
  );
};

// Light background for the product section.
export const BgPaper: React.FC = () => {
  const frame = useCurrentFrame();
  const d = Math.sin(frame / 80) * 40;
  return (
    <AbsoluteFill style={{ background: theme.colors.paper }}>
      <div
        style={{
          position: "absolute",
          width: 1400,
          height: 1400,
          borderRadius: "50%",
          top: -700 + d,
          left: -200,
          filter: "blur(80px)",
          background: `radial-gradient(circle, ${theme.colors.tintLight}AA, transparent 60%)`,
        }}
      />
    </AbsoluteFill>
  );
};

// Procedural film grain, no asset file.
export const Grain: React.FC<{ opacity?: number; blend?: React.CSSProperties["mixBlendMode"] }> = ({
  opacity = 0.05,
  blend = "multiply",
}) => {
  const frame = useCurrentFrame();
  const noise = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='220' height='220'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='220' height='220' filter='url(%23n)' opacity='0.5'/%3E%3C/svg%3E")`;
  return (
    <AbsoluteFill
      style={{
        pointerEvents: "none",
        backgroundImage: noise,
        backgroundSize: "220px",
        backgroundPosition: `${(frame * 7) % 220}px ${(frame * 13) % 220}px`,
        opacity,
        mixBlendMode: blend,
      }}
    />
  );
};

export const Vignette: React.FC<{ strength?: number }> = ({ strength = 0.22 }) => (
  <AbsoluteFill
    style={{
      pointerEvents: "none",
      background: `radial-gradient(ellipse at center, transparent 58%, rgba(0,0,0,${strength}) 100%)`,
    }}
  />
);

// Soft top/bottom grade to unify screenshots with the graphics.
export const Grade: React.FC<{ light?: boolean }> = ({ light }) => (
  <AbsoluteFill style={{ pointerEvents: "none" }}>
    <AbsoluteFill
      style={{
        background: light
          ? "linear-gradient(180deg, rgba(0,0,0,0.04), transparent 25%, transparent 78%, rgba(0,0,0,0.06))"
          : "linear-gradient(180deg, rgba(0,0,0,0.10), transparent 28%, transparent 72%, rgba(0,0,0,0.16))",
      }}
    />
  </AbsoluteFill>
);

// Convenience stack for the top of every scene.
export const Finish: React.FC<{ light?: boolean }> = ({ light }) => (
  <>
    <Grade light={light} />
    <Grain opacity={light ? 0.045 : 0.06} blend={light ? "multiply" : "overlay"} />
    <Vignette strength={light ? 0.1 : 0.2} />
  </>
);
