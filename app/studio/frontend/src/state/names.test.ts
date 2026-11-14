import { describe, expect, it } from "vitest";
import { caseTitle, fileTitle, runTitle, shortDay, shortDuration, targetName } from "./names";

describe("names", () => {
  it("names a project the way people say it", () => {
    expect(targetName("local:shop_app")).toBe("Demo app");
    expect(targetName("aidev:yusufkaraaslan/Skill_Seekers@5b5d8df")).toBe("Skill_Seekers");
    expect(targetName(null)).toBe("");
  });

  it("titles a run by its project, its kind and the day it started", () => {
    const run = { name: "20261102_demo_feature_agentic", target: "local:shop_app", kind: "v2", started: "2026-11-02T06:00:32+00:00" };
    expect(runTitle(run)).toBe(`Demo app · agent team · ${shortDay(run.started)}`);
    expect(runTitle({ ...run, kind: "v1", started: null })).toBe("Demo app · Phase 1 sweep");
    expect(runTitle({ name: "watch", target: null, kind: "watch", path: "raw/watch_demo/watch" })).toBe("watch_demo · watch");
  });

  it("titles results files and case studies", () => {
    expect(fileTitle("main_table.csv")).toBe("Main table");
    expect(fileTitle("aidev_funnel.png")).toBe("AIDev funnel");
    expect(caseTitle("skill-seekers-abl-no_research", "aidev:o/Skill_Seekers@1")).toBe("Skill_Seekers · ablation: no research");
    expect(caseTitle("skill-seekers-safe", "aidev:o/Skill_Seekers@1")).toBe("Skill_Seekers · safe");
    expect(caseTitle("proj_a", "local:proj_a")).toBe("proj_a");
  });

  it("writes short durations", () => {
    expect(shortDuration(2533)).toBe("42m 13s");
    expect(shortDuration(13.2)).toBe("13s");
    expect(shortDuration(3725)).toBe("1h 2m");
  });
});
