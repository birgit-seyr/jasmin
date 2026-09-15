import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

import PictureUploadField, {
  RASTER_PICTURE_ACCEPT,
} from "../PictureUploadField";

function fileInput(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("file input not rendered");
  return input;
}

describe("PictureUploadField", () => {
  it("offers any image type by default", () => {
    const { container } = render(
      <PictureUploadField uploading={false} onUpload={vi.fn()} />,
    );

    expect(fileInput(container).accept).toBe("image/*");
  });

  it("narrows the file picker to the given accept list", () => {
    const { container } = render(
      <PictureUploadField
        uploading={false}
        onUpload={vi.fn()}
        accept={RASTER_PICTURE_ACCEPT}
      />,
    );

    expect(fileInput(container).accept).toBe(RASTER_PICTURE_ACCEPT);
  });

  it("never offers SVG for the raster picture fields", () => {
    expect(RASTER_PICTURE_ACCEPT).not.toMatch(/svg/i);
    expect(RASTER_PICTURE_ACCEPT.split(",")).toEqual([
      "image/png",
      "image/jpeg",
      "image/webp",
      "image/gif",
    ]);
  });
});
