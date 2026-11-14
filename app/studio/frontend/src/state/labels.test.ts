import { describe, expect, it } from "vitest";
import { columnDecimals, formatNumber, headerLabel, isIsoDate, numericColumn, plural, ruleLabel, shortDate, valueLabel } from "./labels";

describe("labels", () => {
  it("writes column names in plain words", () => {
    expect(headerLabel("safe_score")).toBe("Safe score");
    expect(headerLabel("llm_requests_mean")).toBe("LLM requests (mean)");
    expect(headerLabel("lines removed (mean, 95% CI)")).toBe("Lines removed (mean, 95% CI)");
    expect(headerLabel("traps_removed (finished)")).toBe("Traps removed (finished)");
  });

  it("writes snake_case values as words and leaves names and paths alone", () => {
    expect(valueLabel("leftover_file")).toBe("leftover file");
    expect(valueLabel("bookshelf/inventory.py::_print_low_stock")).toBe("bookshelf/inventory.py::_print_low_stock");
    expect(valueLabel("cleansweep-gatekeeper")).toBe("cleansweep-gatekeeper");
    expect(ruleLabel("llm_manager")).toBe("LLM Manager");
  });

  it("shortens dates and separates thousands", () => {
    expect(isIsoDate("2026-11-01T10:05:00+00:00")).toBe(true);
    expect(isIsoDate("seed 1")).toBe(false);
    expect(shortDate("2026-11-01T10:05:00")).toBe("Nov 1, 10:05");
    expect(formatNumber(50427)).toBe("50,427");
    expect(formatNumber(0.81357)).toBe("0.814");
  });

  it("gives a column of numbers one number of decimals", () => {
    expect(columnDecimals([0.107, 14.56, 1.673, 0])).toBe(3);
    expect(columnDecimals([300, 63, "-"])).toBe(0);
    expect(columnDecimals([0.12345])).toBe(3);
    expect(formatNumber(14.56, 3)).toBe("14.560");
  });

  it("finds numeric columns, intervals and ratios included", () => {
    expect(numericColumn([1, 2, "-", null])).toBe(true);
    expect(numericColumn(["0.814 [0.757, 0.857]", "57/70"])).toBe(true);
    expect(numericColumn(["seed 1", "seed 2"])).toBe(false);
  });

  it("counts in the singular and the plural", () => {
    expect(plural(1, "probe case")).toBe("1 probe case");
    expect(plural(24, "probe case")).toBe("24 probe cases");
    expect(plural(1, "clean")).toBe("1 clean");
  });
});
