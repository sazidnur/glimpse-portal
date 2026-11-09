// presets.ts — one preset per series. These are the `defaultProps` of each
// composition (what Remotion Studio shows) AND working example payloads for the
// portal. The portal sends the same shape with real content.
import type { NewsShortInput } from "./schema";

export const seriesCompositions = {
  NewsTop5: "top5",
  NewsRumorCheck: "rumor",
  NewsDivision: "division",
  NewsGeneric: "generic",
} as const;

export type NewsCompositionId = keyof typeof seriesCompositions;

// Placeholder stills shipped in /public/news/demo (replace with real photos; any
// https URL works too — the portal will send URLs).
const demoImage = (name: string) => `news/demo/${name}.jpg`;

export const presets: Record<NewsCompositionId, NewsShortInput> = {
  NewsTop5: {
    series: { id: "top5", name: "টপ ডেইলি ৫", intro: "আজকের সেরা ৫ খবর", date: "৯ নভেম্বর ২০২৬" },
    scenes: [
      { title: "ঢাকায় মেট্রোরেলের নতুন রুট চালু", label: "বাংলাদেশ", image: demoImage("metro") },
      { title: "ডলারের দাম আবার বাড়ল", label: "অর্থনীতি", image: demoImage("dollar") },
      { title: "বিশ্বকাপ বাছাইয়ে বাংলাদেশের জয়", label: "খেলা", image: demoImage("cricket") },
      { title: "চট্টগ্রামে ভারী বৃষ্টির সতর্কতা", label: "আবহাওয়া", image: demoImage("rain") },
      { title: "নতুন শিক্ষাক্রম নিয়ে সিদ্ধান্ত", label: "শিক্ষা", image: demoImage("school") },
    ],
    outro: { source: "সূত্র: প্রথম আলো, বাসস, ডেইলি স্টার" },
  },
  NewsRumorCheck: {
    series: { id: "rumor", name: "গুজব না সত্য?", intro: "ভাইরাল দাবি যাচাই", date: "৯ নভেম্বর ২০২৬" },
    scenes: [
      {
        title: "“সোমবার সব স্কুল বন্ধ ঘোষণা”",
        text: "ফেসবুকে ছড়িয়ে পড়া একটি পোস্টের দাবি",
        label: "দাবি",
        image: demoImage("school2"),
        verdict: "false",
        verdictText: "গুজব",
      },
      {
        title: "“ঢাকায় ডেঙ্গু রোগী দ্বিগুণ”",
        text: "স্বাস্থ্য অধিদপ্তরের সাপ্তাহিক প্রতিবেদন",
        label: "দাবি",
        image: demoImage("hospital"),
        verdict: "true",
        verdictText: "সত্য",
      },
    ],
    outro: { source: "যাচাই: গ্লিম্পস ফ্যাক্ট চেক টিম" },
  },
  NewsDivision: {
    series: { id: "division", name: "বিভাগের খবর", intro: "চট্টগ্রাম বিভাগ", date: "৯ নভেম্বর ২০২৬" },
    scenes: [
      { title: "কর্ণফুলী টানেলে যান চলাচল বাড়ছে", label: "চট্টগ্রাম", image: demoImage("tunnel") },
      { title: "কক্সবাজারে পর্যটকের ঢল", label: "কক্সবাজার", image: demoImage("beach") },
      { title: "কুমিল্লায় নতুন হাসপাতাল উদ্বোধন", label: "কুমিল্লা", image: demoImage("clinic") },
    ],
  },
  NewsGeneric: {
    series: { id: "generic", name: "Glimpse News", intro: "সংক্ষেপে খবর" },
    scenes: [
      {
        title: "বাংলাদেশ–জাপান নতুন বাণিজ্য চুক্তি",
        text: "আগামী বছর থেকে কার্যকর হবে",
        label: "রাজনীতি",
        image: demoImage("handshake"),
      },
      { title: "কী বদলাবে সাধারণ মানুষের জন্য?", label: "বিশ্লেষণ", image: demoImage("market") },
    ],
    outro: { source: "সূত্র: বাসস" },
  },
};
