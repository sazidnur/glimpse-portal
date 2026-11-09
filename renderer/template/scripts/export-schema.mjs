// export-schema.mjs — writes the portal contract as JSON Schema + example payloads.
//   node --experimental-strip-types scripts/export-schema.mjs   (Node 22; flag optional on 23+)
// Output: docs/news-short.schema.json and docs/examples/<Composition>.json
import { mkdir, writeFile } from "node:fs/promises";
import { z } from "zod";
import { newsShortSchema } from "../src/news/schema.ts";
import { presets } from "../src/news/presets.ts";

await mkdir("docs/examples", { recursive: true });
const schema = z.toJSONSchema(newsShortSchema, { target: "draft-7" });
schema.title = "NewsShort props";
schema.description =
  "Payload for the Glimpse NewsShort Remotion compositions (NewsTop5, NewsRumorCheck, NewsDivision, NewsGeneric). " +
  "Pass as --props / inputProps. Omitted fields take the defaults in src/news/schema.ts.";
await writeFile("docs/news-short.schema.json", JSON.stringify(schema, null, 2));
for (const [id, example] of Object.entries(presets)) {
  await writeFile(`docs/examples/${id}.json`, JSON.stringify({ composition: id, ...example }, null, 2));
}
console.log("wrote docs/news-short.schema.json and docs/examples/*.json");
