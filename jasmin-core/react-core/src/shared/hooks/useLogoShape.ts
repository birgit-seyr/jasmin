import { useEffect, useState } from "react";

export type LogoShape = "circle" | "square" | "rectangle-wide" | "rectangle-tall";

export function useLogoShape(logoUrl: string | null | undefined) {
  const [logoShape, setLogoShape] = useState<LogoShape>("circle");
  const [logoAspectRatio, setLogoAspectRatio] = useState(1);

  useEffect(() => {
    if (!logoUrl) return;
    // Guard against a stale load resolving after logoUrl changed (tenant
    // switch mid-load) or after unmount: ignore the late onload so it can't
    // overwrite state for a newer URL or warn about setState-after-unmount.
    let cancelled = false;
    const img = new Image();
    img.src = logoUrl;
    img.onload = () => {
      if (cancelled) return;
      const aspectRatio = img.width / img.height;
      setLogoAspectRatio(aspectRatio);
      if (aspectRatio > 1.2) setLogoShape("rectangle-wide");
      else if (aspectRatio < 0.8) setLogoShape("rectangle-tall");
      else setLogoShape("square");
    };
    return () => {
      cancelled = true;
      img.onload = null;
    };
  }, [logoUrl]);

  return { logoShape, logoAspectRatio };
}
