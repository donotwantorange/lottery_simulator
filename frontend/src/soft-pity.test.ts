import { describe, expect, it } from "vitest";
import { softPityText, softStartFromMisses, formatPoints } from "./formatters";
import { makeRuleDocument } from "./test-fixtures";

describe("soft pity presentation", () => {
  it("keeps the internal start offset and safe limits", () => {
    expect(softStartFromMisses(65)).toBe(66);
    expect(softStartFromMisses(50)).toBe(51);
    expect(softStartFromMisses(0)).toBe(1);
    for (const value of [-1, 0.5, true, Number.MAX_SAFE_INTEGER]) {
      expect(() => softStartFromMisses(value as number)).toThrow();
    }
  });
  it("uses current rarity, scope, higher-tier reset and tiny positive steps", () => {
    const rarity = makeRuleDocument().rarities[2];
    expect(softPityText(rarity, true)).toContain("连续65次");
    expect(softPityText(rarity, true)).toContain("5.0000个百分点");
    expect(softPityText({ ...rarity, name: "特别干员" }, false, "赠送池")).toContain("特别干员或更高档");
    expect(softPityText({ ...rarity, soft_enabled: false }, true)).toBe("软保底未启用");
    expect(formatPoints(1e-12)).not.toBe("0.0000");
  });
});
