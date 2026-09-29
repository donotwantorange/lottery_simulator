import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DownloadForm } from "./DownloadForm";

const { currentCsrfToken } = vi.hoisted(() => ({ currentCsrfToken: vi.fn() }));
vi.mock("../api/client", () => ({ currentCsrfToken, errorMessage: () => "无法获取令牌" }));

afterEach(() => { cleanup(); vi.restoreAllMocks(); currentCsrfToken.mockReset(); });

it("opens the download tab during the click and submits a native CSRF form", async () => {
  let release!: (value: string) => void;
  currentCsrfToken.mockReturnValue(new Promise<string>((resolve) => { release = resolve; }));
  const opened = { close: vi.fn() };
  const popup = vi.spyOn(window, "open").mockReturnValue(opened as unknown as Window);
  const submit = vi.spyOn(HTMLFormElement.prototype, "submit").mockImplementation(() => undefined);
  render(<DownloadForm runId="run-1" filters={{ rarity: 6, source: "main" }} />);
  fireEvent.click(screen.getByRole("button", { name: /下载 Trace/ }));
  expect(popup).toHaveBeenCalledOnce();
  expect(submit).not.toHaveBeenCalled();
  release("csrf-current");
  await waitFor(() => expect(submit).toHaveBeenCalledOnce());
  const form = screen.getByRole("button", { name: /下载 Trace/ }).closest("form")!;
  expect(form.method).toBe("post");
  expect(form.target).toMatch(/^trace-download-/);
  expect((form.elements.namedItem("csrfmiddlewaretoken") as HTMLInputElement).value).toBe("csrf-current");
  expect((form.elements.namedItem("filters") as HTMLInputElement).value).toBe('{"rarity":6,"source":"main"}');
});
