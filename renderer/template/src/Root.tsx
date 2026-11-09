import React from "react";
import { Composition } from "remotion";
import { loadFonts } from "./fonts";
import { NEWS_FPS, NEWS_HEIGHT, NEWS_WIDTH, NewsShort, calculateNewsMetadata } from "./news/NewsShort";
import { newsShortSchema } from "./news/schema";
import { presets, seriesCompositions, type NewsCompositionId } from "./news/presets";
import { portalComposition, portalExample, portalSchema, type PortalSeries } from "./news/portal";

loadFonts();

// One composition per series. All share the NewsShort template; the portal picks
// the composition id and sends the props JSON (contract: src/news/schema.ts).
// Duration is derived from the props by calculateMetadata — the value below is a placeholder.
// DailyFive, FactCheck and Pocket take the Glimpse portal's render props (see news/portal.tsx).
const PORTAL_SERIES: Record<string, PortalSeries> = { DailyFive: "top5", FactCheck: "rumor", Pocket: "generic" };

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
  </>
);
