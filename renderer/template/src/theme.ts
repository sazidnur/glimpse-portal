// theme.ts — single source of truth for colours, fonts, easings, springs.
// Components NEVER inline a hex colour or an easing; they read from here.
import { Easing } from "remotion";

export const theme = {
  colors: {
    // Sampled from the supplied Glimpse app icon (#E24A2A) and logo mark (#D15538).
    hero: "#E24A2A", // app-icon orange — full-bleed background in the opening half
    heroDeep: "#D15538", // logo-mark orange — text accent on light backgrounds
    heroDark: "#B93E22", // shadows / gradient corner of the orange background
    tintLight: "#F9DDD8", // from the logo mark's back cards
    tintMid: "#F4BBB1",
    white: "#FFFFFF",
    paper: "#FAFAFA", // light-section background (matches the app's card colour)
    ink: "#111111", // charcoal headline colour on light backgrounds
    inkSoft: "#8A8A8A", // "ALL IN" / "CURATED FROM" style secondary words
    phoneBody: "#1B1B1F",
    phoneEdge: "#3A3A42",
    highlight: "#FFE066", // marker highlight sweep over the summary text
  },
  fonts: {
    // Poppins handles Latin (brand name, URL); Bangla falls through to Noto Sans Bengali
    // (variable, weights 100–900, full conjunct/matra/phala shaping) then Hind Siliguri.
    display: "'Noto Sans Bengali', 'Poppins', 'Hind Siliguri', sans-serif",
    latin: "'Poppins', 'Noto Sans Bengali', sans-serif",
    bangla: "'Noto Sans Bengali', 'Hind Siliguri', sans-serif",
    banglaSoft: "'Hind Siliguri', 'Noto Sans Bengali', sans-serif",
  },
  ease: {
    out: Easing.bezier(0.16, 1, 0.3, 1), // easeOutExpo — entrances
    inOut: Easing.bezier(0.83, 0, 0.17, 1), // easeInOutQuint — moves
    in: Easing.bezier(0.7, 0, 0.84, 0), // exits only
    outBack: Easing.bezier(0.34, 1.56, 0.64, 1), // slight overshoot for slams
  },
  spring: {
    snappy: { damping: 14, stiffness: 160, mass: 0.6 },
    smooth: { damping: 20, stiffness: 90, mass: 1 },
    bouncy: { damping: 11, stiffness: 170, mass: 0.7 },
    slam: { damping: 18, stiffness: 320, mass: 0.5 },
    heavy: { damping: 26, stiffness: 70, mass: 1.2 },
  },
} as const;
