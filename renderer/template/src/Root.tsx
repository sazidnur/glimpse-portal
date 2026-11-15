import React from "react";
import { Composition, Still } from "remotion";
import { loadFonts } from "./fonts";
import { NEWS_FPS, NEWS_HEIGHT, NEWS_WIDTH, NewsShort, calculateNewsMetadata } from "./news/NewsShort";
import { newsShortSchema } from "./news/schema";
import { presets, seriesCompositions, type NewsCompositionId } from "./news/presets";
import { portalComposition, portalExample, portalSchema, type PortalSeries } from "./news/portal";

import { FPS, GOAL, PARLIAMENT, reel, reelFrames, type Look, type ReelProps } from "./social/Reel";
import { CARDS, CARD_EXAMPLE, CARD_SIZE, type CardLook } from "./social/Cards";

loadFonts();

// One composition per series. All share the NewsShort template; the portal picks
// the composition id and sends the props JSON (contract: src/news/schema.ts).
// Duration is derived from the props by calculateMetadata — the value below is a placeholder.
// DailyFive, FactCheck and Pocket take the Glimpse portal's render props (see news/portal.tsx).
const PORTAL_SERIES: Record<string, PortalSeries> = { DailyFive: "top5", FactCheck: "rumor", Pocket: "generic" };

// Composition ids the portal offers for social posts (SocialPost.Template).
const REELS: Record<string, Look> = { ReelPaper: "paper", ReelNight: "night", ReelOrange: "orange", ReelVertical: "vertical" };
const CARD_IDS: Record<string, CardLook> = { CardPhoto: "photo", CardPaper: "paper", CardQuote: "quote" };

export const RemotionRoot: React.FC = () => (
  <>
    {Object.entries(PORTAL_SERIES).map(([id, series]) => {
      const { Component, calculateMetadata } = portalComposition(series);
      return (
        <Composition
          key={id}
          id={id}
          component={Component}
          schema={portalSchema}
          defaultProps={{ ...portalExample, verdict: series === "rumor" ? "false" : "none" }}
          calculateMetadata={calculateMetadata}
          durationInFrames={30 * 20}
          fps={NEWS_FPS}
          width={NEWS_WIDTH}
          height={NEWS_HEIGHT}
        />
      );
    })}
    {(Object.keys(seriesCompositions) as NewsCompositionId[]).map((id) => (
      <Composition
        key={id}
        id={id}
        component={NewsShort}
        schema={newsShortSchema}
        defaultProps={presets[id]}
        calculateMetadata={calculateNewsMetadata}
        durationInFrames={30 * 20}
        fps={NEWS_FPS}
        width={NEWS_WIDTH}
        height={NEWS_HEIGHT}
      />
    ))}
    {/* Social posts (portal admin: Social posts). Reels take an uploaded clip; the examples need public/clip.mp4. */}
    {(Object.entries(REELS) as [string, Look][]).map(([id, look]) => (
      <Composition
        key={id}
        id={id}
        component={reel(look)}
        defaultProps={(id === "ReelNight" ? GOAL : PARLIAMENT) as ReelProps}
        calculateMetadata={({ props }) => ({ durationInFrames: reelFrames(props) })}
        durationInFrames={reelFrames(PARLIAMENT)}
        fps={FPS}
        width={1080}
        height={1920}
      />
    ))}
    {(Object.entries(CARD_IDS) as [string, CardLook][]).map(([id, look]) => (
      <Still key={id} id={id} component={CARDS[look]} defaultProps={CARD_EXAMPLE} width={CARD_SIZE} height={CARD_SIZE} />
    ))}
  </>
);
