// fonts.ts — loads the bundled TTFs via the FontFace API and blocks rendering
// until they are ready, so no frame is ever drawn with a fallback font.
import { continueRender, delayRender, staticFile } from "remotion";
import { assets } from "./config/assets";

type Face = { family: string; file: string; weight: string; style?: string };

const faces: Face[] = [
  { family: "Noto Sans Bengali", file: assets.fonts.notoSansBengali, weight: "100 900" },
  { family: "Hind Siliguri", file: assets.fonts.hindBold, weight: "700" },
  { family: "Hind Siliguri", file: assets.fonts.hindSemi, weight: "600" },
  { family: "Hind Siliguri", file: assets.fonts.hindMedium, weight: "500" },
  { family: "Poppins", file: assets.fonts.poppinsExtraBold, weight: "800" },
  { family: "Poppins", file: assets.fonts.poppinsBold, weight: "700" },
  { family: "Poppins", file: assets.fonts.poppinsSemi, weight: "600" },
  { family: "Poppins", file: assets.fonts.poppinsMedium, weight: "500" },
  { family: "Poppins", file: assets.fonts.poppinsBoldItalic, weight: "700", style: "italic" },
  { family: "Poppins", file: assets.fonts.poppinsExtraBoldItalic, weight: "800", style: "italic" },
];

let started = false;

export const loadFonts = () => {
  if (started || typeof window === "undefined" || !("FontFace" in window)) return;
  started = true;
  const handle = delayRender("Loading Glimpse ad fonts");
  Promise.all(
    faces.map(async (f) => {
      const face = new FontFace(f.family, `url(${staticFile(f.file)})`, {
        weight: f.weight,
        style: f.style ?? "normal",
      });
      await face.load();
      (document.fonts as unknown as Set<FontFace>).add(face);
    }),
  )
    .then(() => continueRender(handle))
    .catch((err) => {
      console.error("Font load failed", err);
      continueRender(handle);
    });
};
