import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExperimentForm, initialParameters, validateParameters } from "./ExperimentForm";

describe("ExperimentForm", () => {
  it("keeps very large seed text exact and validates without numeric conversion", () => {
    let value = { ...initialParameters };
    const seed = "900719925474099312345678901234567890";
    const { rerender } = render(<ExperimentForm value={value} onChange={(next) => {
      value = next;
      rerender(<ExperimentForm value={value} onChange={(updated) => { value = updated; }} />);
    }} />);
    fireEvent.change(screen.getByLabelText("随机种子（可留空）"), { target: { value: seed } });
    expect(value.seed).toBe(seed);
    expect(validateParameters(value)).toBeNull();
  });
});
