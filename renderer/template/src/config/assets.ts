// assets.ts — files bundled with the template (paths relative to /public).
// Brand files here are only DEFAULTS; the portal can override logo, app icon
// and badges per video through the props (see src/news/schema.ts).
export const assets = {
  brand: {
    appIcon: "assets/brand/glimpse-app-icon.png",
    logoMark: "assets/brand/glimpse-logo-mark.png",
    playBadgeBn: "assets/brand/google-play-badge-bn.png",
    appStoreBadgeBn: "assets/brand/app-store-badge-bn.png",
  },
  // Synthesized, royalty-free SFX kit (deterministic). The portal only toggles / scales them.
  audio: {
    music: "assets/audio/music-bed.wav", // 120 BPM bed, used by the demo story only
    whoosh: "assets/audio/sfx-whoosh.wav",
    whooshSoft: "assets/audio/sfx-whoosh-soft.wav",
    slam: "assets/audio/sfx-slam.wav",
    pop: "assets/audio/sfx-pop.wav",
    click: "assets/audio/sfx-click.wav",
    ding: "assets/audio/sfx-ding.wav",
    riser: "assets/audio/sfx-riser.wav",
    marker: "assets/audio/sfx-marker.wav",
    flip: "assets/audio/sfx-flip.wav",
  },
  fonts: {
    notoSansBengali: "assets/fonts/NotoSansBengali.ttf", // variable wght 100–900
    hindBold: "assets/fonts/HindSiliguri-Bold.ttf",
    hindSemi: "assets/fonts/HindSiliguri-SemiBold.ttf",
    hindMedium: "assets/fonts/HindSiliguri-Medium.ttf",
    poppinsExtraBold: "assets/fonts/Poppins-ExtraBold.ttf",
    poppinsBold: "assets/fonts/Poppins-Bold.ttf",
    poppinsSemi: "assets/fonts/Poppins-SemiBold.ttf",
    poppinsMedium: "assets/fonts/Poppins-Medium.ttf",
    poppinsBoldItalic: "assets/fonts/Poppins-BoldItalic.ttf",
    poppinsExtraBoldItalic: "assets/fonts/Poppins-ExtraBoldItalic.ttf",
  },
} as const;
