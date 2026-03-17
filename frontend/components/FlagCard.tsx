"use client";

import type { HazardFlag, DevelopmentFlag, FlagStatus } from "@/lib/types";

// ── HazardFlag card ─────────────────────────────────────────────────────────

interface FlagCardProps {
  flag: HazardFlag;
  isSelected?: boolean;
  onSelect: (flag: HazardFlag) => void;
}

const STATUS_COLORS: Record<FlagStatus, string> = {
  red: "bg-red-500",
  yellow: "bg-yellow-400",
  green: "bg-green-500",
};

const STATUS_RING: Record<FlagStatus, string> = {
  red: "ring-red-500/30",
  yellow: "ring-yellow-400/30",
  green: "ring-green-500/30",
};

const STATUS_BG: Record<FlagStatus, string> = {
  red: "bg-red-500/10 border-red-500/20",
  yellow: "bg-yellow-400/10 border-yellow-400/20",
  green: "bg-green-500/10 border-green-500/20",
};

const SOURCE_LABEL: Record<string, string> = {
  osm: "OSM",
  epa_tri: "EPA",
  usda_fsis: "USDA",
};

function formatDistance(m: number): string {
  if (m >= 1000) return `${(m / 1000).toFixed(2)} km`;
  return `${Math.round(m)} m`;
}

// ── DevelopmentFlagCard ──────────────────────────────────────────────────────

interface DevelopmentFlagCardProps {
  flag: DevelopmentFlag;
  isSelected?: boolean;
  onSelect: (flag: DevelopmentFlag) => void;
}

function formatBondAmount(amount: number): string {
  if (amount >= 1_000_000_000) return `$${(amount / 1_000_000_000).toFixed(1)}B`;
  if (amount >= 1_000_000) return `$${(amount / 1_000_000).toFixed(0)}M`;
  if (amount >= 1_000) return `$${(amount / 1_000).toFixed(0)}K`;
  return `$${amount.toLocaleString()}`;
}

const DEV_TYPE_LABEL: Record<string, string> = {
  mud_district: "Utility District",
  bond_issuance: "Bond Issuance",
  tif_district: "TIF District",
};

export function DevelopmentFlagCard({
  flag,
  isSelected = false,
  onSelect,
}: DevelopmentFlagCardProps) {
  const typeLabel = DEV_TYPE_LABEL[flag.dev_type] ?? flag.dev_type.replace(/_/g, " ");
  const displayName = flag.name ?? typeLabel;

  return (
    <button
      onClick={() => onSelect(flag)}
      className={[
        "w-full text-left rounded-xl border p-4 transition-all duration-150",
        "hover:brightness-110 focus:outline-none focus:ring-2",
        STATUS_BG[flag.status as FlagStatus] ?? "bg-purple-500/10 border-purple-500/20",
        `focus:${STATUS_RING[flag.status as FlagStatus] ?? "ring-purple-500/30"}`,
        isSelected
          ? "ring-2 " + (STATUS_RING[flag.status as FlagStatus] ?? "ring-purple-500/30")
          : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div className="flex items-start gap-3">
        {/* Crystal ball icon for future development */}
        <span
          className="mt-0.5 flex-shrink-0 text-base leading-none"
          aria-label="Future development"
        >
          {"\uD83D\uDD2E"}
        </span>

        <div className="flex-1 min-w-0">
          {/* Top row: name + type badge */}
          <div className="flex items-center justify-between gap-2">
            <p className="text-white font-semibold text-sm truncate capitalize">
              {displayName}
            </p>
            <span className="flex-shrink-0 text-xs font-bold px-1.5 py-0.5 rounded bg-slate-700 text-slate-300">
              {typeLabel}
            </span>
          </div>

          {/* Formation year + status */}
          <p className="text-slate-400 text-xs mt-0.5 capitalize">
            {flag.formed_year ? `Est. ${flag.formed_year}` : "Formation year unknown"} ·{" "}
            <span className="text-slate-300">{flag.status}</span>
          </p>

          {/* Distance + bond amount */}
          <p className="text-slate-300 text-xs mt-2 leading-relaxed">
            {flag.name && (
              <>
                <span className="font-semibold">{flag.name}</span>{" "}
              </>
            )}
            {flag.formed_year && (
              <>formed {flag.formed_year} — </>
            )}
            <span
              className={
                flag.status === "red"
                  ? "text-red-400 font-semibold"
                  : flag.status === "yellow"
                  ? "text-yellow-400 font-semibold"
                  : "text-green-400 font-semibold"
              }
            >
              {formatDistance(flag.distance_m)}
            </span>{" "}
            away.
            {flag.bond_amount_usd != null && (
              <span className="text-slate-200">
                {" "}
                Active bond issuance: {formatBondAmount(flag.bond_amount_usd)}.
              </span>
            )}
          </p>
        </div>
      </div>
    </button>
  );
}

// ── Default export (HazardFlag) ───────────────────────────────────────────────

export default function FlagCard({ flag, isSelected = false, onSelect }: FlagCardProps) {
  const sourceLabel = SOURCE_LABEL[flag.source] ?? flag.source.toUpperCase();
  const displayName = flag.name ?? flag.subcategory.replace(/_/g, " ");

  return (
    <button
      onClick={() => onSelect(flag)}
      className={[
        "w-full text-left rounded-xl border p-4 transition-all duration-150",
        "hover:brightness-110 focus:outline-none focus:ring-2",
        STATUS_BG[flag.status],
        `focus:${STATUS_RING[flag.status]}`,
        isSelected ? "ring-2 " + STATUS_RING[flag.status] : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div className="flex items-start gap-3">
        {/* Status dot */}
        <span
          className={`mt-1 flex-shrink-0 w-3 h-3 rounded-full ${STATUS_COLORS[flag.status]}`}
          aria-label={`Status: ${flag.status}`}
        />

        <div className="flex-1 min-w-0">
          {/* Top row: name + source badge */}
          <div className="flex items-center justify-between gap-2">
            <p className="text-white font-semibold text-sm truncate capitalize">
              {displayName}
            </p>
            <span className="flex-shrink-0 text-xs font-bold px-1.5 py-0.5 rounded bg-slate-700 text-slate-300">
              {sourceLabel}
            </span>
          </div>

          {/* Subcategory */}
          <p className="text-slate-400 text-xs mt-0.5 capitalize">
            {flag.subcategory.replace(/_/g, " ")} ·{" "}
            <span className="text-slate-300">{flag.priority.replace(/_/g, " ")}</span>
          </p>

          {/* Distance sentence */}
          <p className="text-slate-300 text-xs mt-2 leading-relaxed">
            <span className="font-semibold capitalize">{displayName}</span> is{" "}
            <span
              className={
                flag.status === "red"
                  ? "text-red-400 font-semibold"
                  : flag.status === "yellow"
                  ? "text-yellow-400 font-semibold"
                  : "text-green-400 font-semibold"
              }
            >
              {formatDistance(flag.distance_m)}
            </span>{" "}
            away. Your threshold was{" "}
            <span className="text-slate-200 font-medium">
              {formatDistance(flag.threshold_m)}
            </span>
            .
          </p>
        </div>
      </div>
    </button>
  );
}
