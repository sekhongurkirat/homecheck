"use client";

import { useEffect, useRef, useCallback } from "react";
import type { HazardFlag, Priority } from "@/lib/types";

// MapLibre is loaded dynamically to avoid SSR issues
let maplibregl: typeof import("maplibre-gl") | null = null;

interface MapViewProps {
  lat: number;
  lng: number;
  flags: HazardFlag[];
  selectedFlag?: HazardFlag | null;
  thresholds: Record<Priority, number>;
}

const STATUS_LINE_COLOR: Record<string, string> = {
  red: "#ef4444",
  yellow: "#facc15",
  green: "#22c55e",
};

const STATUS_CIRCLE_COLOR: Record<string, string> = {
  red: "#ef4444",
  yellow: "#facc15",
  green: "#22c55e",
};

// Buffer circle colours (per priority, semi-transparent)
const PRIORITY_BUFFER_COLOR: Record<string, string> = {
  highway: "#ef444433",
  rail: "#8b5cf633",
  industrial: "#f9731633",
  meat_processing: "#ec489933",
  landfill: "#14b8a633",
  airport: "#3b82f633",
};

// OpenFreeMap — free, no token, built for MapLibre GL, OSM data
const MAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";

// Generate a geodesic buffer polygon as GeoJSON
function bufferGeoJSON(
  lat: number,
  lng: number,
  radiusM: number,
  steps = 64
): GeoJSON.Feature<GeoJSON.Polygon> {
  const coords: [number, number][] = [];
  const earthRadius = 6371000;
  const angularRadius = radiusM / earthRadius;
  const latRad = (lat * Math.PI) / 180;
  const lngRad = (lng * Math.PI) / 180;

  for (let i = 0; i <= steps; i++) {
    const bearing = (i / steps) * 2 * Math.PI;
    const pLat = Math.asin(
      Math.sin(latRad) * Math.cos(angularRadius) +
        Math.cos(latRad) * Math.sin(angularRadius) * Math.cos(bearing)
    );
    const pLng =
      lngRad +
      Math.atan2(
        Math.sin(bearing) * Math.sin(angularRadius) * Math.cos(latRad),
        Math.cos(angularRadius) - Math.sin(latRad) * Math.sin(pLat)
      );
    coords.push([(pLng * 180) / Math.PI, (pLat * 180) / Math.PI]);
  }

  return {
    type: "Feature",
    geometry: { type: "Polygon", coordinates: [coords] },
    properties: { radiusM },
  };
}

export default function MapView({
  lat,
  lng,
  flags,
  selectedFlag,
  thresholds,
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<import("maplibre-gl").Map | null>(null);
  const markerRef = useRef<import("maplibre-gl").Marker | null>(null);
  const initialised = useRef(false);

  const initMap = useCallback(async () => {
    if (!containerRef.current || initialised.current) return;
    initialised.current = true;

    // Dynamic import to avoid SSR crash
    const ml = await import("maplibre-gl");
    maplibregl = ml;

    const map = new ml.Map({
      container: containerRef.current,
      style: MAP_STYLE,
      center: [lng, lat],
      zoom: 14,
      attributionControl: true,
    });

    mapRef.current = map;

    map.on("load", () => {
      // ── Address marker ───────────────────────────────────────────────────
      const el = document.createElement("div");
      el.className =
        "w-6 h-6 rounded-full bg-blue-500 border-2 border-white shadow-lg";
      markerRef.current = new ml.Marker({ element: el })
        .setLngLat([lng, lat])
        .addTo(map);

      // ── Buffer rings ──────────────────────────────────────────────────────
      const addedPriorities = new Set<string>();
      for (const [priority, radiusM] of Object.entries(thresholds)) {
        if (addedPriorities.has(priority)) continue;
        addedPriorities.add(priority);
        const sourceId = `buffer-${priority}`;
        const fillId = `buffer-fill-${priority}`;
        const strokeId = `buffer-stroke-${priority}`;

        map.addSource(sourceId, {
          type: "geojson",
          data: bufferGeoJSON(lat, lng, radiusM) as GeoJSON.Feature,
        });
        map.addLayer({
          id: fillId,
          type: "fill",
          source: sourceId,
          paint: {
            "fill-color": PRIORITY_BUFFER_COLOR[priority] ?? "#3b82f633",
            "fill-opacity": 0.25,
          },
        });
        map.addLayer({
          id: strokeId,
          type: "line",
          source: sourceId,
          paint: {
            "line-color": PRIORITY_BUFFER_COLOR[priority]?.slice(0, 7) ?? "#3b82f6",
            "line-width": 1.5,
            "line-dasharray": [4, 2],
          },
        });
      }

      // ── Hazard feature layers ─────────────────────────────────────────────
      flags.forEach((flag, idx) => {
        const sourceId = `flag-${idx}`;
        const layerId = `flag-layer-${idx}`;

        map.addSource(sourceId, {
          type: "geojson",
          data: {
            type: "Feature",
            geometry: flag.geojson as GeoJSON.Geometry,
            properties: {
              status: flag.status,
              name: flag.name ?? flag.subcategory,
              distance_m: flag.distance_m,
            },
          } as GeoJSON.Feature,
        });

        const gtype = flag.geojson.type;
        if (gtype === "Point") {
          map.addLayer({
            id: layerId,
            type: "circle",
            source: sourceId,
            paint: {
              "circle-radius": 7,
              "circle-color": STATUS_CIRCLE_COLOR[flag.status] ?? "#fff",
              "circle-stroke-width": 2,
              "circle-stroke-color": "#fff",
              "circle-opacity": 0.9,
            },
          });
        } else {
          // LineString, Polygon, MultiPolygon
          map.addLayer({
            id: layerId,
            type: "line",
            source: sourceId,
            paint: {
              "line-color": STATUS_LINE_COLOR[flag.status] ?? "#fff",
              "line-width": 3,
              "line-opacity": 0.85,
            },
          });
        }

        // Popup on click
        map.on("click", layerId, (e) => {
          const props = e.features?.[0]?.properties ?? {};
          new ml.Popup({ closeButton: true, maxWidth: "240px" })
            .setLngLat(e.lngLat)
            .setHTML(
              `<div class="text-sm font-medium">${props.name ?? "Hazard"}</div>
               <div class="text-xs text-gray-500">${Math.round(props.distance_m)} m away</div>`
            )
            .addTo(map);
        });
        map.on("mouseenter", layerId, () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", layerId, () => {
          map.getCanvas().style.cursor = "";
        });
      });
    });
  }, [lat, lng, flags, thresholds]);

  // Initialise once
  useEffect(() => {
    initMap();
    return () => {
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
        initialised.current = false;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Fly to selected flag
  useEffect(() => {
    if (!mapRef.current || !selectedFlag) return;
    const g = selectedFlag.geojson;
    let center: [number, number] | null = null;

    if (g.type === "Point") {
      center = g.coordinates as [number, number];
    } else if (g.type === "LineString") {
      const mid = Math.floor(g.coordinates.length / 2);
      center = g.coordinates[mid] as [number, number];
    }

    if (center) {
      mapRef.current.flyTo({ center, zoom: 15, speed: 1.4 });
    }
  }, [selectedFlag]);

  return (
    <div
      ref={containerRef}
      className="w-full h-full rounded-xl overflow-hidden"
      aria-label="Hazard map"
    />
  );
}
