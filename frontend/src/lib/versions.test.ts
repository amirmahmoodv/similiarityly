import { describe, expect, it } from "vitest";
import { versionsTooFarApart } from "./versions";

describe("versionsTooFarApart", () => {
  it("flags the production case: server 1.12 with client 1.20", () => {
    expect(versionsTooFarApart("1.12.5", "1.20.0")).toBe(true);
  });

  it("allows one minor version of difference either way", () => {
    expect(versionsTooFarApart("1.20.2", "1.20.0")).toBe(false);
    expect(versionsTooFarApart("1.19.0", "1.20.0")).toBe(false);
    expect(versionsTooFarApart("1.21.1", "1.20.0")).toBe(false);
    expect(versionsTooFarApart("1.22.0", "1.20.0")).toBe(true);
  });

  it("flags a different major version", () => {
    expect(versionsTooFarApart("2.0.0", "1.20.0")).toBe(true);
  });

  it("accepts a leading v and stays quiet when a version is unknown", () => {
    expect(versionsTooFarApart("v1.20.1", "1.20.0")).toBe(false);
    expect(versionsTooFarApart(null, "1.20.0")).toBe(false);
    expect(versionsTooFarApart("1.20.0", undefined)).toBe(false);
    expect(versionsTooFarApart("dev", "1.20.0")).toBe(false);
  });
});
