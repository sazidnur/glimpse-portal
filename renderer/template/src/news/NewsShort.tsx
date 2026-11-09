// NewsShort.tsx — the data-driven news video. Intro → story scenes → outro,
// with voice, captions, music and SFX. The component receives the portal's raw
// JSON (`NewsShortInput`), validates it and fills defaults via normalize().
// Duration is computed from the props by calculateMetadata (no hard-coded length).
import React, { useMemo } from "react";
import { AbsoluteFill, Sequence, type CalculateMetadataFunction } from "remotion";
import { Captions } from "./Captions";
import { Intro } from "./Intro";
import { NewsAudio } from "./NewsAudio";
import { Outro } from "./Outro";
import { StoryScene } from "./StoryScene";
import { layoutFrames, normalize, type NewsShortInput } from "./schema";

export const NEWS_FPS = 30;
export const NEWS_WIDTH = 1080;
export const NEWS_HEIGHT = 1920;

export const calculateNewsMetadata: CalculateMetadataFunction<NewsShortInput> = ({ props }) => {
  const p = normalize(props);
  return { durationInFrames: layoutFrames(p, NEWS_FPS).total, fps: NEWS_FPS, width: NEWS_WIDTH, height: NEWS_HEIGHT };
};

export const NewsShort: React.FC<NewsShortInput> = (input) => {
  const p = useMemo(() => normalize(input), [input]);
  const lf = layoutFrames(p, NEWS_FPS);
  const voiceStartFrame = p.voice ? Math.round(p.voice.startAtSeconds * NEWS_FPS) : 0;

  return (
    <AbsoluteFill style={{ background: p.brand.colors.hero }}>
      <Sequence from={0} durationInFrames={lf.intro} name="Intro">
        <Intro p={p} />
      </Sequence>
      {lf.scenes.map((s, i) => (
        <Sequence key={i} from={s.start} durationInFrames={s.duration} name={`Story ${i + 1}`}>
          <StoryScene p={p} scene={p.scenes[i]} index={i} />
        </Sequence>
      ))}
      {p.outro.enabled ? (
        <Sequence from={lf.outroStart} durationInFrames={lf.outro} name="Outro">
          <Outro p={p} />
        </Sequence>
      ) : null}
      {/* captions live above every scene but only during story time */}
      <Sequence from={lf.intro} durationInFrames={lf.outroStart - lf.intro} name="Captions">
        <Captions p={p} voiceStartFrame={voiceStartFrame - lf.intro} />
      </Sequence>
      <NewsAudio p={p} fps={NEWS_FPS} />
    </AbsoluteFill>
  );
};
