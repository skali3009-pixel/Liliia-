import React from "react";
import { AbsoluteFill, Composition, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

const Title: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame, fps, config: { damping: 12 } });
  const words = ["Она", "не", "сломалась."];
  return (
    <AbsoluteFill style={{ background: "#111", justifyContent: "center", alignItems: "center", fontFamily: "DejaVu Sans" }}>
      <div style={{ color: "white", fontSize: 110, fontWeight: 800, transform: `scale(${s})`, textAlign: "center" }}>
        {words.map((w, i) => (
          <span key={i} style={{ opacity: interpolate(frame, [i * 8, i * 8 + 8], [0, 1], { extrapolateRight: "clamp" }) }}>{w} </span>
        ))}
      </div>
      <div style={{ position: "absolute", bottom: 300, color: "#e8b04a", fontSize: 60, letterSpacing: 12 }}>SCALIA</div>
    </AbsoluteFill>
  );
};

export const Root: React.FC = () => (
  <Composition id="Test" component={Title} durationInFrames={90} fps={30} width={1080} height={1920} />
);
