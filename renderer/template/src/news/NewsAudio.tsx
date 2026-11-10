// NewsAudio.tsx — voice track, optional music bed (URL from props) and the SFX
// cue sheet. SFX files are the project's own synthesized kit; the portal only
// toggles them / sets their volume.
import React from "react";
import { Audio, Sequence, staticFile, interpolate } from "remotion";
import { assets } from "../config/assets";
import type { NewsShortProps } from "./schema";
import { layoutFrames } from "./schema";
import { resolveSrc } from "./ui";
import { stampFrame } from "./StoryScene";

const Sfx: React.FC<{ at: number; src: string; volume: number }> = ({ at, src, volume }) => (
  <Sequence from={Math.max(0, at - 2)} durationInFrames={90} name={`sfx@${at}`}>
    <Audio src={staticFile(src)} volume={volume} />
  </Sequence>
);

export const NewsAudio: React.FC<{ p: NewsShortProps; fps: number }> = ({ p, fps }) => {
  const lf = layoutFrames(p, fps);
  const a = assets.audio;
  const v = p.sfx.volume;
  const voiceStart = p.voice ? Math.round(p.voice.startAtSeconds * fps) : 0;

  return (
    <>
      {/* voice */}
      {p.voice?.segments ? (
        p.voice.segments.map((seg, i) => (
          <Sequence key={i} from={voiceStart + Math.round(seg.at * fps)} name={`voice ${i + 1}`}>
            <Audio
              src={resolveSrc(p.voice!.src)}
              volume={p.voice!.volume}
              trimBefore={Math.round(seg.from * fps)}
              trimAfter={Math.round(seg.to * fps)}
            />
          </Sequence>
        ))
      ) : p.voice ? (
        <Sequence from={voiceStart} name="voice">
          <Audio src={resolveSrc(p.voice.src)} volume={p.voice.volume} />
        </Sequence>
      ) : null}

      {/* music bed — fades in over the intro, out over the last second */}
      {p.music.src ? (
        <Audio
          src={resolveSrc(p.music.src)}
          loop={p.music.loop}
          volume={(f) =>
            p.music.volume *
            interpolate(f, [0, 20, lf.total - fps, lf.total - 1], [0, 1, 1, 0], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            })
          }
        />
      ) : null}

      {p.sfx.enabled ? (
        <>
          {/* intro */}
          <Sfx at={0} src={a.slam} volume={0.8 * v} />
          <Sfx at={4} src={a.whooshSoft} volume={0.5 * v} />
          <Sfx at={10} src={a.pop} volume={0.6 * v} />
          <Sfx at={lf.intro - 14} src={a.riser} volume={0.35 * v} />

          {/* one cue set per story scene */}
          {lf.scenes.map((s, i) => {
            const sc = p.scenes[i];
            return (
              <React.Fragment key={i}>
                <Sfx at={s.start} src={i % 2 === 0 ? a.whoosh : a.whooshSoft} volume={0.6 * v} />
                {sc.label ? <Sfx at={s.start + 10} src={a.click} volume={0.45 * v} /> : null}
                {sc.kind === "list" ? <Sfx at={s.start + 8} src={a.pop} volume={0.6 * v} /> : null}
                {sc.kind === "verdict" && sc.verdict ? (
                  <Sfx at={s.start + stampFrame(s.duration)} src={a.slam} volume={0.85 * v} />
                ) : null}
              </React.Fragment>
            );
          })}

          {/* outro */}
          {p.outro.enabled ? (
            <>
              <Sfx at={lf.outroStart} src={a.flip} volume={0.65 * v} />
              <Sfx at={lf.outroStart + 14} src={a.pop} volume={0.55 * v} />
              <Sfx at={lf.outroStart + 20} src={a.ding} volume={0.5 * v} />
            </>
          ) : null}
        </>
      ) : null}
    </>
  );
};
