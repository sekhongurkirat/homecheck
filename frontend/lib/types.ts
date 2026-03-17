// ── Priority categories ─────────────────────────────────────────────────────

export type Priority =
  | "highway"
  | "rail"
  | "industrial"
  | "meat_processing"
  | "landfill"
  | "airport";

export const ALL_PRIORITIES: Priority[] = [
  "highway",
  "rail",
  "industrial",
  "meat_processing",
  "landfill",
  "airport",
];

export const PRIORITY_LABELS: Record<Priority, string> = {
  highway: "Highways & Major Roads",
  rail: "Rail Lines",
  industrial: "Industrial Facilities",
  meat_processing: "Meat Processing Plants",
  landfill: "Landfills & Transfer Stations",
  airport: "Airports & Airstrips",
};

export const DEFAULT_THRESHOLDS: Record<Priority, number> = {
  highway: 300,
  rail: 300,
  industrial: 500,
  meat_processing: 1000,
  landfill: 1000,
  airport: 3000,
};

// ── Flag status ─────────────────────────────────────────────────────────────

export type FlagStatus = "red" | "yellow" | "green";

// ── Hazard flag ─────────────────────────────────────────────────────────────

export interface HazardFlag {
  priority: Priority;
  status: FlagStatus;
  distance_m: number;
  threshold_m: number;
  name: string | null;
  subcategory: string;
  source: string;
  geojson: Record<string, unknown>;
}

// ── Flood zone ──────────────────────────────────────────────────────────────

export interface FloodZone {
  zone_code: string;
  flood_label: string;
  in_zone: boolean;
}

// ── Development flag ────────────────────────────────────────────────────────

export interface DevelopmentFlag {
  dev_type: string;
  status: string;
  distance_m: number;
  name: string | null;
  formed_year: number | null;
  last_bond_year: number | null;
  bond_amount_usd: number | null;
  summary: string;
  geojson: Record<string, unknown>;
}

// ── Report response ─────────────────────────────────────────────────────────

export interface ReportResponse {
  address: string;
  lat: number;
  lng: number;
  flags: HazardFlag[];
  flood_zone: FloodZone | null;
  development: DevelopmentFlag[];
}
