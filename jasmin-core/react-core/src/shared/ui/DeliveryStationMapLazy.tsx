import { Spin } from "antd";
import { Suspense, lazy } from "react";

import type { DeliveryStationMapProps } from "./DeliveryStationMap";

// Leaflet (+ react-leaflet + its CSS) weighs ~45 kB gzip. The @shared/ui
// barrel sits on the app-boot path (App.tsx imports it), so a plain re-export
// of DeliveryStationMap would drag Leaflet into the entry chunk for EVERY
// page — that blew the entry-chunk size budget in CI. This wrapper defers the
// whole map bundle into its own async chunk, fetched only when a map actually
// renders (type-only imports above are erased at build time and pull nothing).
const LazyInner = lazy(() => import("./DeliveryStationMap"));

export default function DeliveryStationMapLazy(props: DeliveryStationMapProps) {
  return (
    <Suspense
      fallback={
        <div
          className="jasmin-station-map-loading"
          style={{
            height: props.height ?? 320,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Spin />
        </div>
      }
    >
      <LazyInner {...props} />
    </Suspense>
  );
}
