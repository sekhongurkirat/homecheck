"use client";

import { ALL_PRIORITIES, PRIORITY_LABELS, type Priority } from "@/lib/types";

interface PriorityPickerProps {
  priorities: Priority[];
  thresholds: Record<Priority, number>;
  onChange: (priorities: Priority[], thresholds: Record<Priority, number>) => void;
}

// Slider bounds per priority (metres)
const SLIDER_CONFIG: Record<
  Priority,
  { min: number; max: number; step: number }
> = {
  highway: { min: 50, max: 2000, step: 50 },
  rail: { min: 50, max: 2000, step: 50 },
  industrial: { min: 100, max: 5000, step: 100 },
  meat_processing: { min: 100, max: 5000, step: 100 },
  landfill: { min: 100, max: 5000, step: 100 },
  airport: { min: 500, max: 10000, step: 500 },
};

const PRIORITY_ICONS: Record<Priority, string> = {
  highway: "🛣",
  rail: "🚆",
  industrial: "🏭",
  meat_processing: "🥩",
  landfill: "♻️",
  airport: "✈️",
};

function formatM(m: number): string {
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${m} m`;
}

export default function PriorityPicker({
  priorities,
  thresholds,
  onChange,
}: PriorityPickerProps) {
  function togglePriority(p: Priority) {
    const next = priorities.includes(p)
      ? priorities.filter((x) => x !== p)
      : [...priorities, p];
    onChange(next, thresholds);
  }

  function setThreshold(p: Priority, value: number) {
    onChange(priorities, { ...thresholds, [p]: value });
  }

  return (
    <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-4">
      <h2 className="text-white font-semibold text-sm mb-3 uppercase tracking-wider">
        Deal-breaker settings
      </h2>
      <ul className="space-y-3">
        {ALL_PRIORITIES.map((p) => {
          const active = priorities.includes(p);
          const cfg = SLIDER_CONFIG[p];
          const threshold = thresholds[p] ?? cfg.min;

          return (
            <li key={p} className="space-y-1.5">
              {/* Checkbox + label */}
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={active}
                  onChange={() => togglePriority(p)}
                  className="w-4 h-4 rounded accent-blue-500 cursor-pointer"
                />
                <span className="text-sm">
                  {PRIORITY_ICONS[p]}{" "}
                  <span className={active ? "text-white" : "text-slate-500"}>
                    {PRIORITY_LABELS[p]}
                  </span>
                </span>
              </label>

              {/* Threshold slider — only shown when checked */}
              {active && (
                <div className="pl-6 flex items-center gap-3">
                  <input
                    type="range"
                    min={cfg.min}
                    max={cfg.max}
                    step={cfg.step}
                    value={threshold}
                    onChange={(e) => setThreshold(p, Number(e.target.value))}
                    className="flex-1 accent-blue-500 cursor-pointer"
                    aria-label={`${PRIORITY_LABELS[p]} threshold`}
                  />
                  <span className="text-xs text-slate-400 w-14 text-right tabular-nums">
                    {formatM(threshold)}
                  </span>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
