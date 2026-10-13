// DeliveryStationMap draws each station as a dot inside a Leaflet ``divIcon``,
// titled with the station's name. That name comes from a contact record other
// users can edit, so it has to reach the page as text, never as markup.

import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import DeliveryStationMap from "../DeliveryStationMap";
import type { DeliveryStationMapMarker } from "../DeliveryStationMap";

function station(
  overrides: Partial<DeliveryStationMapMarker> = {},
): DeliveryStationMapMarker {
  return {
    id: "station-1",
    lat: 48.2082,
    lon: 16.3738,
    label: "Hofladen Gruber",
    ...overrides,
  };
}

function stationDots(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>(".jasmin-station-marker"),
  );
}

function stationDot(container: HTMLElement, title: string): HTMLElement {
  const dot = stationDots(container).find(
    (candidate) => candidate.title === title,
  );
  if (!dot) throw new Error(`No station dot titled "${title}"`);
  return dot;
}

describe("DeliveryStationMap", () => {
  it("titles a dot whose name looks like markup with the literal name", () => {
    const label = 'x"><img src=x onerror=alert(1)>';
    const { container } = render(
      <DeliveryStationMap markers={[station({ label })]} />,
    );

    const dots = stationDots(container);
    expect(dots).toHaveLength(1);
    expect(dots[0]).toHaveAttribute("title", label);
    expect(dots[0].childNodes).toHaveLength(0);
    expect(container.querySelector(".leaflet-marker-pane img")).toBeNull();
    expect(container.querySelector("[onerror]")).toBeNull();
  });

  it("keeps quotes and ampersands in a name verbatim", () => {
    const label = 'Café "Zur Linde" & Söhne &amp; Co';
    const { container } = render(
      <DeliveryStationMap markers={[station({ label })]} />,
    );

    const dots = stationDots(container);
    expect(dots).toHaveLength(1);
    expect(dots[0]).toHaveAttribute("title", label);
  });

  it("marks the selected and the disabled station with their modifiers", () => {
    const { container } = render(
      <DeliveryStationMap
        markers={[
          station({ id: "open", label: "Open" }),
          station({ id: "picked", label: "Picked", lat: 48.3, selected: true }),
          station({ id: "full", label: "Full", lat: 48.4, disabled: true }),
        ]}
      />,
    );

    expect(stationDot(container, "Open")).toHaveClass("jasmin-station-marker", {
      exact: true,
    });
    expect(stationDot(container, "Picked")).toHaveClass(
      "jasmin-station-marker jasmin-station-marker--selected",
      { exact: true },
    );
    expect(stationDot(container, "Full")).toHaveClass(
      "jasmin-station-marker jasmin-station-marker--disabled",
      { exact: true },
    );
  });

  it("centres each dot on its station and draws the selected one larger", () => {
    const { container } = render(
      <DeliveryStationMap
        markers={[
          station({ id: "open", label: "Open" }),
          station({ id: "picked", label: "Picked", lat: 48.3, selected: true }),
        ]}
      />,
    );

    // The icon box Leaflet wraps around the dot carries the size and anchor;
    // without a class of its own it also skips Leaflet's white default square.
    const openIcon = stationDot(container, "Open").parentElement;
    const pickedIcon = stationDot(container, "Picked").parentElement;
    expect(openIcon).toHaveStyle({
      width: "20px",
      height: "20px",
      marginLeft: "-10px",
      marginTop: "-10px",
    });
    expect(pickedIcon).toHaveStyle({
      width: "24px",
      height: "24px",
      marginLeft: "-12px",
      marginTop: "-12px",
    });
    expect(openIcon).toHaveClass("leaflet-marker-icon");
    expect(openIcon).not.toHaveClass("leaflet-div-icon");
  });

  it("selects a station on click, but not a disabled one", () => {
    const onSelect = vi.fn();
    const { container } = render(
      <DeliveryStationMap
        markers={[
          station({ id: "open", label: "Open" }),
          station({ id: "full", label: "Full", lat: 48.4, disabled: true }),
        ]}
        onSelect={onSelect}
      />,
    );

    fireEvent.click(stationDot(container, "Full"));
    expect(onSelect).not.toHaveBeenCalled();

    fireEvent.click(stationDot(container, "Open"));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith("open");
  });

  it("opens a station's popup on click instead of selecting it", () => {
    const onSelect = vi.fn();
    const { container } = render(
      <DeliveryStationMap
        markers={[station({ popup: <span>Pick a delivery day</span> })]}
        onSelect={onSelect}
      />,
    );

    fireEvent.click(stationDot(container, "Hofladen Gruber"));

    expect(screen.getByText("Pick a delivery day")).toBeInTheDocument();
    expect(onSelect).not.toHaveBeenCalled();
  });
});
