import L from "leaflet";
import type { LatLngBoundsExpression, LatLngExpression } from "leaflet";
import { useEffect, useMemo } from "react";
import type { ReactNode } from "react";
import { MapContainer, Marker, Popup, TileLayer, useMap } from "react-leaflet";

import "leaflet/dist/leaflet.css";
import "./DeliveryStationMap.css";

// Fallback view (roughly centred on the German-speaking area) for the rare
// case the map renders with no positioned markers.
const DEFAULT_CENTER: LatLngExpression = [50.5, 10.5];
const DEFAULT_ZOOM = 5;
const SINGLE_MARKER_ZOOM = 13;

export interface DeliveryStationMapMarker {
  /** Stable id passed back to ``onSelect`` (station id, or whatever the
   * caller keys on). */
  id: string;
  lat: number;
  lon: number;
  label: string;
  selected?: boolean;
  disabled?: boolean;
  /** Optional popup body. When provided, clicking the marker opens the popup
   * instead of firing ``onSelect`` — the caller drives selection from inside
   * the popup (e.g. one button per delivery day at that station). */
  popup?: ReactNode;
}

export interface DeliveryStationMapProps {
  markers: DeliveryStationMapMarker[];
  /** Fired on marker click for markers WITHOUT a ``popup``. */
  onSelect?: (id: string) => void;
  height?: number | string;
  className?: string;
}

function markerIcon(marker: DeliveryStationMapMarker): L.DivIcon {
  const classes = ["jasmin-station-marker"];
  if (marker.selected) classes.push("jasmin-station-marker--selected");
  if (marker.disabled) classes.push("jasmin-station-marker--disabled");
  const size = marker.selected ? 24 : 20;
  return L.divIcon({
    className: "",
    html: `<div class="${classes.join(" ")}" title="${marker.label}"></div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    popupAnchor: [0, -(size / 2) - 2],
  });
}

/** Pans/zooms the map to enclose every marker whenever the set changes. */
function FitBounds({ points }: { points: [number, number][] }) {
  const map = useMap();
  const key = useMemo(() => JSON.stringify(points), [points]);
  useEffect(() => {
    if (points.length === 0) return;
    if (points.length === 1) {
      map.setView(points[0], SINGLE_MARKER_ZOOM);
      return;
    }
    map.fitBounds(points as LatLngBoundsExpression, { padding: [30, 30] });
    // ``key`` (the serialized points) is the real dependency; ``points`` is a
    // fresh array each render and would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, key]);
  return null;
}

/**
 * Presentational OpenStreetMap (Leaflet) showing delivery-station markers.
 * Purely props-driven — no data fetching — so it stays reusable. Markers use a
 * CSS ``divIcon`` (a coloured circle) which sidesteps Leaflet's default-marker
 * PNG assets that break under the Vite bundler.
 */
export default function DeliveryStationMap({
  markers,
  onSelect,
  height = 320,
  className,
}: DeliveryStationMapProps) {
  const points = useMemo<[number, number][]>(
    () => markers.map((marker) => [marker.lat, marker.lon]),
    [markers],
  );

  const center = points[0] ?? DEFAULT_CENTER;

  return (
    <div
      className={
        className ? `jasmin-station-map ${className}` : "jasmin-station-map"
      }
      style={{ height }}
    >
      <MapContainer
        center={center}
        zoom={points.length ? SINGLE_MARKER_ZOOM : DEFAULT_ZOOM}
        scrollWheelZoom={false}
        style={{ height: "100%", width: "100%" }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds points={points} />
        {markers.map((marker) => (
          <Marker
            key={marker.id}
            position={[marker.lat, marker.lon]}
            icon={markerIcon(marker)}
            eventHandlers={
              marker.popup || marker.disabled
                ? undefined
                : { click: () => onSelect?.(marker.id) }
            }
          >
            {marker.popup ? <Popup>{marker.popup}</Popup> : null}
          </Marker>
        ))}
      </MapContainer>
    </div>
  );
}
