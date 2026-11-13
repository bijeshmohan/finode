// Fails when src/api/schema.d.ts is not what openapi.json generates (someone changed the API and forgot to regenerate).
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const fresh = join(mkdtempSync(join(tmpdir(), "finode-api-")), "schema.d.ts");
execFileSync("npx", ["openapi-typescript", "openapi.json", "-o", fresh], { stdio: "ignore" });
if (readFileSync(fresh, "utf8") !== readFileSync("src/api/schema.d.ts", "utf8")) {
  console.error("src/api/schema.d.ts is out of date: run npm run gen:api");
  process.exit(1);
}
