import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { afterModel } from "../state/beforeAfter";
import type { StudioEvent } from "../state/fold";
import { exportHtml } from "./ExportReport";

function exported(name: string): string {
  const base = new URL(`../../../../../demo/replay/${name}/`, import.meta.url);
  const events: StudioEvent[] = readFileSync(new URL("events.jsonl", base), "utf8").trim().split("\n").map((l) => JSON.parse(l));
  const report = JSON.parse(readFileSync(new URL("report.json", base), "utf8"));
  const model = afterModel(events, report.stats.final_diff, null, { target: null, report });
  return exportHtml(model, { name, target: events[0].payload.repo_id, mode: "safe", model: events[0].payload.model, started: events[0].ts || null });
}

describe("the exported report", () => {
  it("is one self-contained HTML page: inline styles, no scripts, nothing fetched", () => {
    const html = exported("20261102_demo_feature_agentic");
    expect(html.startsWith("<!doctype html>")).toBe(true);
    expect(html).toMatch(/<style>[^<]*--st-kept: #00744f/);
    for (const outside of ["<script", "<link", 'src="', "http://", "https://", "/api/", "url("]) expect(html, outside).not.toContain(outside);
  });

  it("holds the before / after, the trees, every diff and the verdict", () => {
    const html = exported("20261102_demo_feature_agentic");
    expect(html).toContain("<title>CleanSweep cleanup: shop_app</title>");
    expect(html).toContain("everything runs");
    expect(html).toMatch(/229<\/b>.*182<\/b>/s);
    expect(html).toContain("<del>inventory_old.py</del>");
    expect(html).toContain("normalize_isbn");
    expect(html).toContain("1 removed: isbn_checksum_ok");
    // 16 found: 5 kept, 1 rolled back, 10 left as suggestions
    expect(html).toContain("Left for a person (10)");
    expect(html).toContain("qwen36-35b-a3b (LLM-judged)");
    expect(html).toContain("Behavior that nothing tests isn&#x27;t covered");
  });

  it("says when no LLM was used", () => {
    expect(exported("20261101_toy_clean_offline")).toContain("No LLM was used");
  });
});
