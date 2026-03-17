"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";

import FlagCard, { DevelopmentFlagCard } from "@/components/FlagCard";
import PriorityPicker from "@/components/PriorityPicker";
import { fetchReport } from "@/lib/api";
import {
  ALL_PRIORITIES,
  DEFAULT_THRESHOLDS,
  type DevelopmentFlag,
  type HazardFlag,
  type Priority,
  type ReportResponse,
} from "@/lib/types";

// MapView uses maplibre-gl which needs browser APIs — disable SSR
const MapView = dynamic(() => import("@/components/MapView"), { ssr: false });

// ── Street View modal ─────────────────────────────────────────────────────────
function StreetViewModal({
  lat,
  lng,
  onClose,
}: {
  lat: number;
  lng: number;
  onClose: () => void;
}) {
  const src = `https://www.google.com/maps/embed/v1/streetview?key=${
    process.env.NEXT_PUBLIC_GOOGLE_MAPS_KEY ?? "YOUR_GOOGLE_MAPS_KEY"
  }&location=${lat},${lng}&fov=80&heading=0&pitch=0`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-3xl aspect-video bg-slate-900 rounded-2xl overflow-hidden shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <iframe
          title="Street View"
          src={src}
          className="w-full h-full border-0"
          allowFullScreen
        />
        <button
          onClick={onClose}
          className="absolute top-3 right-3 w-8 h-8 rounded-full bg-black/60 text-white
                     flex items-center justify-center hover:bg-black/80 transition"
          aria-label="Close Street View"
        >
          ✕
        </button>
      </div>
    </div>
  );
}

// ── Flood zone badge ──────────────────────────────────────────────────────────
function FloodBadge({ report }: { report: ReportResponse }) {
  if (!report.flood_zone) return null;
  const { zone_code, flood_label, in_zone } = report.flood_zone;
  return (
    <div
      className={`rounded-xl border p-3 text-sm ${
        in_zone
          ? "bg-red-500/10 border-red-500/20 text-red-300"
          : "bg-green-500/10 border-green-500/20 text-green-300"
      }`}
    >
      <span className="font-semibold">Flood Zone {zone_code}</span>
      {" — "}
      {flood_label}
    </div>
  );
}

// ── Main report content ───────────────────────────────────────────────────────
function ReportContent() {
  const searchParams = useSearchParams();
  const address = searchParams.get("address") ?? "";

  const [priorities, setPriorities] = useState<Priority[]>(ALL_PRIORITIES);
  const [thresholds, setThresholds] =
    useState<Record<Priority, number>>(DEFAULT_THRESHOLDS);

  const [report, setReport] = useState<ReportResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedFlag, setSelectedFlag] = useState<HazardFlag | null>(null);
  const [showStreetView, setShowStreetView] = useState(false);

  const runReport = useCallback(
    async (p: Priority[], t: Record<Priority, number>) => {
      if (!address) return;
      setLoading(true);
      setError(null);
      try {
        const result = await fetchReport({
          address,
          priorities: p,
          thresholds: t,
        });
        setReport(result);
        setSelectedFlag(null);
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Unknown error");
      } finally {
        setLoading(false);
      }
    },
    [address]
  );

  // Initial load
  useEffect(() => {
    runReport(priorities, thresholds);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handlePickerChange(
    newPriorities: Priority[],
    newThresholds: Record<Priority, number>
  ) {
    setPriorities(newPriorities);
    setThresholds(newThresholds);
    runReport(newPriorities, newThresholds);
  }

  const hazardCount = report?.flags.length ?? 0;
  const devCount = report?.development?.length ?? 0;

  return (
    <div className="min-h-screen bg-slate-900 flex flex-col">
      {/* ── Topbar ── */}
      <header className="flex-shrink-0 h-14 bg-slate-800 border-b border-slate-700 flex items-center px-6 z-10">
        {/* Left: Back link */}
        <a
          href="/"
          className="flex items-center gap-1.5 text-slate-400 hover:text-white text-sm transition-colors duration-150 min-w-[80px]"
        >
          <svg
            className="w-4 h-4"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          Back
        </a>

        {/* Center: Brand */}
        <div className="flex-1 flex justify-center">
          <span className="text-white font-bold text-lg tracking-tight select-none">
            HomeCheck
          </span>
        </div>

        {/* Right: Summary pill + Street View */}
        <div className="flex items-center gap-3 min-w-[80px] justify-end">
          {loading && (
            <span className="text-blue-400 text-xs animate-pulse">
              Analysing…
            </span>
          )}
          {report && !loading && (
            <>
              <span className="hidden sm:inline-flex items-center gap-1.5 text-xs bg-slate-700 text-slate-200 px-3 py-1 rounded-full font-medium">
                <span className="text-red-400">{hazardCount} hazard{hazardCount !== 1 ? "s" : ""}</span>
                <span className="text-slate-500">·</span>
                <span className="text-purple-400">{devCount} development</span>
              </span>
              <button
                onClick={() => setShowStreetView(true)}
                className="text-xs bg-slate-700 hover:bg-slate-600 text-slate-200
                           px-3 py-1.5 rounded-lg transition"
              >
                Street View
              </button>
            </>
          )}
        </div>
      </header>

      {/* ── Body ── */}
      <div className="flex flex-1 overflow-hidden">
        {/* ── Left sidebar ── */}
        <aside className="w-80 flex-shrink-0 bg-slate-900 border-r border-slate-800 flex flex-col overflow-y-auto">
          <div className="p-4 space-y-4">
            {/* Priority picker */}
            <PriorityPicker
              priorities={priorities}
              thresholds={thresholds}
              onChange={handlePickerChange}
            />

            {/* Error */}
            {error && (
              <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-red-400 text-sm">
                {error}
              </div>
            )}

            {/* Loading skeleton */}
            {loading && !report && (
              <div className="space-y-3 animate-pulse">
                {[...Array(3)].map((_, i) => (
                  <div
                    key={i}
                    className="h-20 rounded-xl bg-slate-800"
                  />
                ))}
              </div>
            )}

            {/* Report results */}
            {report && (
              <>
                <FloodBadge report={report} />

                {/* Hazard flags */}
                {report.flags.length === 0 ? (
                  <p className="text-slate-400 text-sm text-center py-6">
                    No hazards found within your thresholds.
                  </p>
                ) : (
                  <div className="space-y-2">
                    <p className="text-slate-500 text-xs uppercase tracking-wide font-medium">
                      Hazards ({report.flags.length})
                    </p>
                    {report.flags.map((flag, i) => (
                      <FlagCard
                        key={i}
                        flag={flag}
                        isSelected={selectedFlag === flag}
                        onSelect={(f) => setSelectedFlag(f)}
                      />
                    ))}
                  </div>
                )}

                {/* Development flags */}
                {report.development && report.development.length > 0 && (
                  <div className="space-y-2">
                    <p className="text-slate-500 text-xs uppercase tracking-wide font-medium mt-4">
                      Future Development ({report.development.length})
                    </p>
                    {report.development.map((flag: DevelopmentFlag, i: number) => (
                      <DevelopmentFlagCard key={i} flag={flag} onSelect={() => {}} />
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </aside>

        {/* ── Map panel ── */}
        <main className="flex-1 relative">
          {report ? (
            <MapView
              lat={report.lat}
              lng={report.lng}
              flags={report.flags}
              selectedFlag={selectedFlag}
              thresholds={thresholds}
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-slate-600">
              {loading ? "Loading map…" : "Enter an address to see results."}
            </div>
          )}
        </main>
      </div>

      {/* ── Street View modal ── */}
      {showStreetView && report && (
        <StreetViewModal
          lat={report.lat}
          lng={report.lng}
          onClose={() => setShowStreetView(false)}
        />
      )}
    </div>
  );
}

// Wrap in Suspense for useSearchParams
export default function ReportPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-slate-900 flex items-center justify-center text-slate-400">
          Loading…
        </div>
      }
    >
      <ReportContent />
    </Suspense>
  );
}
