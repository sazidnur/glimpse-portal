// Captions.tsx — word-synced subtitles driven by `voice.words`. Pages of 2–4
// words; the word being spoken is highlighted. Rendered once at the root so it
// follows the voice across scene cuts.
import React, { useMemo } from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";
import type { NewsShortProps, Word } from "./schema";

type Page = { startMs: number; endMs: number; words: Word[] };

// Group words into pages: break on maxWords or on a pause > 650 ms.
export const paginate = (words: Word[], maxWords: number): Page[] => {
  const pages: Page[] = [];
  let cur: Word[] = [];
  const flush = () => {
    if (cur.length) pages.push({ startMs: cur[0].startMs, endMs: cur[cur.length - 1].endMs, words: cur });
    cur = [];
  };
  words.forEach((w, i) => {
    const prev = words[i - 1];
    if (cur.length >= maxWords || (prev && w.startMs - prev.endMs > 650)) flush();
    cur.push(w);
  });
  flush();
  return pages;
};

export const Captions: React.FC<{ p: NewsShortProps; voiceStartFrame: number }> = ({ p, voiceStartFrame }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const c = p.brand.colors;
  const words = p.voice?.words ?? [];
  const pages = useMemo(() => paginate(words, p.captions.maxWordsPerPage), [words, p.captions.maxWordsPerPage]);
  if (!p.captions.enabled || !pages.length) return null;

  const nowMs = ((frame - voiceStartFrame) / fps) * 1000;
  const idx = pages.findIndex((pg, i) => {
    const next = pages[i + 1];
    const until = next ? next.startMs : pg.endMs + 500; // hold last page half a second
    return nowMs >= pg.startMs - 80 && nowMs < until;
  });
  if (idx < 0) return null;
  const page = pages[idx];
  const pageStartFrame = voiceStartFrame + Math.round((page.startMs / 1000) * fps);
  const inP = spring({ frame: frame - pageStartFrame + 2, fps, config: theme.spring.snappy });

  const top = p.captions.position === "low" ? 1500 : 980;
  return (
    <div
      style={{
        position: "absolute",
        left: 60,
        right: 60,
        top,
        display: "flex",
        justifyContent: "center",
        opacity: inP,
        transform: `translateY(${interpolate(inP, [0, 1], [18, 0])}px) scale(${interpolate(inP, [0, 1], [0.96, 1])})`,
      }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          gap: "0px 18px",
          maxWidth: 960,
          background: "rgba(17,17,17,0.72)",
          borderRadius: 28,
          padding: "16px 34px 22px",
          backdropFilter: "blur(6px)",
        }}
      >
        {page.words.map((w, i) => {
          const active = nowMs >= w.startMs - 40 && nowMs < (page.words[i + 1]?.startMs ?? w.endMs + 400);
          const spoken = nowMs >= w.endMs;
          return (
            <span
              key={i}
              style={{
                fontFamily: theme.fonts.display,
                fontWeight: 700,
                fontSize: 50,
                lineHeight: 1.25,
                color: active ? c.highlight : spoken ? c.white : "rgba(255,255,255,0.72)",
                transform: active ? "scale(1.06)" : "scale(1)",
                display: "inline-block",
                padding: "0.04em 0",
              }}
            >
              {w.text}
            </span>
          );
        })}
      </div>
    </div>
  );
};
