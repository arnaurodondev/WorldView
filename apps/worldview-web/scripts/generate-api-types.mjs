/**
 * scripts/generate-api-types.mjs — OpenAPI type generation script
 *
 * WHY THIS EXISTS: Generates TypeScript types from the committed S9 OpenAPI
 * spec snapshot (infra/contracts/s9-openapi.json). Running this script keeps
 * types/generated/api.ts in sync with the live API contract.
 *
 * HOW TO RUN: pnpm --filter worldview-web generate-types
 *
 * DESIGN NOTE: S9 is a proxy API — most response bodies are untyped at the
 * OpenAPI layer (FastAPI's generic Response returns {}). The generated file
 * primarily captures the path surface, query parameters, and the 8 named
 * component schemas. Domain response shapes live in types/api.ts (hand-written)
 * until S9 routes adopt Pydantic response_model annotations.
 */

import { execSync } from "node:child_process";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { existsSync } from "node:fs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, "../../..");
const specPath = resolve(repoRoot, "infra/contracts/s9-openapi.json");
const outPath = resolve(__dirname, "../types/generated/api.ts");
const binPath = resolve(__dirname, "../node_modules/.bin/openapi-typescript");

if (!existsSync(specPath)) {
  console.error(`ERROR: spec not found at ${specPath}`);
  console.error("Run: curl http://localhost:8000/openapi.json > infra/contracts/s9-openapi.json");
  process.exit(1);
}

console.log(`Generating types from: ${specPath}`);
console.log(`Output:               ${outPath}`);

try {
  execSync(`${binPath} ${specPath} -o ${outPath}`, {
    stdio: "inherit",
    cwd: resolve(__dirname, ".."),
  });
  console.log("✓ types/generated/api.ts generated");
} catch (err) {
  console.error("Generation failed:", err.message);
  process.exit(1);
}
