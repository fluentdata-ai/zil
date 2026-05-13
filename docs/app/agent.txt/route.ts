import { readFileSync } from "fs";
import { join } from "path";

export function GET() {
  const filePath = join(process.cwd(), "agent-content.txt");
  const content = readFileSync(filePath, "utf-8");

  return new Response(content, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=3600",
    },
  });
}
