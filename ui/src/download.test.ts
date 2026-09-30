import { it, expect, vi } from "vitest";
import { pb, downloadFile } from "./api";
it("does not save a protected response after logout or unmount", async () => {
  for (const mode of ["logout", "unmount"]) {
    pb.authStore.save(
      "eyJhbGciOiJIUzI1NiJ9." +
        btoa(JSON.stringify({ exp: 9999999999 })) +
        ".signature",
      null,
    );
    const token = vi
      .spyOn(pb.files, "getToken")
      .mockResolvedValue("temporary-file-token");
    let release!: (r: Response) => void;
    let started!: () => void;
    const ready = new Promise<void>((r) => (started = r));
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(() => {
      started();
      return new Promise((r) => (release = r));
    });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    const controller = new AbortController();
    const job = downloadFile(
      "documents",
      "fixture00000001",
      "fixture.txt",
      controller.signal,
    );
    await ready;
    if (mode === "logout") pb.authStore.clear();
    else controller.abort();
    release(new Response("synthetic protected body"));
    await expect(job).rejects.toThrow("Session changed");
    expect(click).not.toHaveBeenCalled();
    token.mockRestore();
    fetcher.mockRestore();
    click.mockRestore();
    pb.authStore.clear();
  }
});
