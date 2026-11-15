// Square (1080x1080) news cards for photo posts: a news photo, a label, a headline and a source line,
// signed with the Glimpse logo. Orange is the accent; the backgrounds are photo, paper or night.
import React from "react";
import { AbsoluteFill, Img } from "remotion";
import { theme } from "../theme";
import { Finish } from "../components/Layers";
import { HeroText } from "../components/Text";
import { DEFAULTS } from "../news/schema";
import { resolveSrc } from "../news/ui";
import { NIGHT } from "./Reel";

export const CARD_SIZE = 1080;
export type CardProps = { image: string; chip: string; headline: string; credit?: string };
export type CardLook = "photo" | "paper" | "quote";

export const CARD_EXAMPLE: CardProps = {
  image: "news/demo/handshake.jpg",
  chip: "রাজনীতি",
  headline: "নির্বাচনের আগে সংলাপে বসতে রাজি প্রধান দলগুলো, আলোচনা শুরু আগামী সপ্তাহে",
  credit: "সূত্র: প্রথম আলো",
};

const C = DEFAULTS.brand.colors;
// Longer headlines get a smaller size so every card keeps the same footprint.
const fit = (text: string, big: number) => (text.length > 110 ? big * 0.72 : text.length > 70 ? big * 0.85 : big);

const Chip: React.FC<{ text: string; bg?: string; fg?: string }> = ({ text, bg = C.hero, fg = C.white }) => (
  <div style={{ display: "inline-block", fontFamily: theme.fonts.display, fontWeight: 700, fontSize: 30, lineHeight: 1, color: fg, background: bg, borderRadius: 999, padding: "13px 24px 17px" }}>
    {text}
  </div>
);

// Logo on the left, the store badges on the right, so people see it is an app they can install.
const Signature: React.FC<{ color: string }> = ({ color }) => (
  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24 }}>
    <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
      <div style={{ width: 56, height: 56, borderRadius: 16, background: C.white, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 8px 18px -8px rgba(0,0,0,0.35)" }}>
        <Img src={resolveSrc(DEFAULTS.brand.logo)} style={{ width: 40, height: 40, objectFit: "contain" }} />
      </div>
      <HeroText size={32} weight={700} latin color={color}>
        Glimpse
      </HeroText>
    </div>
    <div style={{ display: "flex", gap: 20 }}>
      <Img src={resolveSrc(DEFAULTS.brand.badges.playStore)} style={{ height: 46, display: "block" }} />
      <Img src={resolveSrc(DEFAULTS.brand.badges.appStore)} style={{ height: 46, display: "block" }} />
    </div>
  </div>
);

const Credit: React.FC<{ text?: string; color: string }> = ({ text, color }) =>
  text ? <div style={{ fontFamily: theme.fonts.display, fontWeight: 600, fontSize: 26, color }}>{text}</div> : null;

// The photo fills the card; the headline sits on a dark fade at the bottom.
const PhotoCard: React.FC<CardProps> = (c) => (
  <AbsoluteFill style={{ background: NIGHT }}>
    <Img src={resolveSrc(c.image)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
    <AbsoluteFill style={{ background: `linear-gradient(180deg, ${NIGHT}66 0%, transparent 22%, transparent 36%, ${NIGHT}E6 70%, ${NIGHT} 100%)` }} />
    <div style={{ position: "absolute", top: 56, left: 56 }}>
      <Chip text={c.chip} />
    </div>
    <div style={{ position: "absolute", left: 56, right: 56, bottom: 56, display: "flex", flexDirection: "column", gap: 26 }}>
      <div style={{ width: 96, height: 8, borderRadius: 4, background: C.hero }} />
      <HeroText size={fit(c.headline, 60)} weight={800} color={C.white} lineHeight={1.3}>
        {c.headline}
      </HeroText>
      <Credit text={c.credit} color="rgba(255,255,255,0.7)" />
      <Signature color={C.white} />
    </div>
    <Finish />
  </AbsoluteFill>
);

// Light editorial card: the photo framed at the top, the headline in ink below.
const PaperCard: React.FC<CardProps> = (c) => (
  <AbsoluteFill style={{ background: C.paper }}>
    <div style={{ position: "absolute", top: 48, left: 48, right: 48, height: 560, borderRadius: 32, overflow: "hidden", boxShadow: "0 30px 60px -30px rgba(0,0,0,0.45)" }}>
      <Img src={resolveSrc(c.image)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
    </div>
    <div style={{ position: "absolute", top: 580, left: 80 }}>
      <Chip text={c.chip} />
    </div>
    <div style={{ position: "absolute", top: 660, left: 64, right: 64, bottom: 48, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <HeroText size={fit(c.headline, 54)} weight={800} color={C.ink} lineHeight={1.3}>
          {c.headline}
        </HeroText>
        <Credit text={c.credit} color={theme.colors.inkSoft} />
      </div>
      <div style={{ borderTop: `3px solid ${C.hero}`, paddingTop: 22 }}>
        <Signature color={C.ink} />
      </div>
    </div>
    <Finish light />
  </AbsoluteFill>
);

// A quote on night: big orange quote mark, the words in white, the speaker's photo in an orange ring.
const QuoteCard: React.FC<CardProps> = (c) => (
  <AbsoluteFill style={{ background: NIGHT }}>
    <div style={{ position: "absolute", width: 1100, height: 1100, borderRadius: "50%", top: -620, right: -520, filter: "blur(90px)", background: `radial-gradient(circle, ${C.hero}66, transparent 62%)` }} />
    <div style={{ position: "absolute", top: 20, left: 56, fontFamily: theme.fonts.latin, fontWeight: 800, fontSize: 300, lineHeight: 1, color: C.hero }}>“</div>
    <div style={{ position: "absolute", top: 250, left: 64, right: 64 }}>
      <HeroText size={fit(c.headline, 62)} weight={700} color={C.white} lineHeight={1.35}>
        {c.headline.replace(/^[“"]|[”"]$/g, "")}
      </HeroText>
    </div>
    <div style={{ position: "absolute", left: 64, right: 64, bottom: 150, display: "flex", alignItems: "center", gap: 28 }}>
      <div style={{ width: 150, height: 150, borderRadius: "50%", padding: 6, background: C.hero, flexShrink: 0 }}>
        <Img src={resolveSrc(c.image)} style={{ width: "100%", height: "100%", borderRadius: "50%", objectFit: "cover", display: "block" }} />
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <HeroText size={40} weight={700} color={C.white} lineHeight={1.25}>
          {c.chip}
        </HeroText>
        <Credit text={c.credit} color="rgba(255,255,255,0.6)" />
      </div>
    </div>
    <div style={{ position: "absolute", left: 64, right: 64, bottom: 48 }}>
      <Signature color={C.white} />
    </div>
    <Finish />
  </AbsoluteFill>
);

export const CARDS: Record<CardLook, React.FC<CardProps>> = { photo: PhotoCard, paper: PaperCard, quote: QuoteCard };
