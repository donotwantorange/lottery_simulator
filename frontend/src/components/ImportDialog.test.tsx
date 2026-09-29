import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ImportDialog } from "./ImportDialog";

describe("ImportDialog", () => {
  it("passes the original JSON text through without parsing large integers in the browser", async () => {
    const raw = '{"format_version":1,"parameters":{"seed":900719925474099312345678901234567890}}';
    const onImport = vi.fn().mockResolvedValue(undefined);
    render(<ImportDialog label="导入JSON" onImport={onImport} />);
    const file = new File([raw], "experiment.json", { type: "application/json" });
    Object.defineProperty(file, "text", { value: async () => raw });
    fireEvent.change(screen.getByLabelText("导入JSON"), { target: { files: [file] } });
    await waitFor(() => expect(onImport).toHaveBeenCalledWith(raw));
  });
});
