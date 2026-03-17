"use client";

import { useState, useRef, useEffect, useCallback, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { fetchAddressSuggestions, type AddressSuggestion } from "@/lib/api";

const EXAMPLE_ADDRESSES = [
  "2201 N Lamar Blvd, Austin TX 78705",
  "3900 Parmer Ln, Austin TX 78727",
];

const FEATURES = [
  {
    icon: (
      <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 6.75V15m6-6v8.25m.503-9.998l4.875 2.437c.381.19.622.58.622 1.006V17.25a1.125 1.125 0 01-1.125 1.125H4.125A1.125 1.125 0 013 17.25V9.375c0-.426.24-.815.622-1.006l4.875-2.437A1.125 1.125 0 019.75 5.85v.9m4.5 0v-.9a1.125 1.125 0 00-.628-1.013L9.75 5.85" />
      </svg>
    ),
    title: "Hazard Detection",
    body: "Highways, rail lines, industrial facilities, landfills — we check proximity to 6 categories of nuisance.",
  },
  {
    icon: (
      <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 18L9 11.25l4.306 4.307a11.95 11.95 0 015.814-5.519l2.74-1.22m0 0l-5.94-2.28m5.94 2.28l-2.28 5.941" />
      </svg>
    ),
    title: "Future Development",
    body: "Municipal utility districts and bond issuances reveal what&apos;s planned for vacant land near your home.",
  },
  {
    icon: (
      <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 10.5a3 3 0 11-6 0 3 3 0 016 0z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-9.5 11.25S1.5 17.642 1.5 10.5a8 8 0 0117 0z" />
      </svg>
    ),
    title: "No Guessing",
    body: "Every flag shows the exact distance and your personal threshold. Red means it violates your limit. Green means you&apos;re clear.",
  },
];

export default function HomePage() {
  const router = useRouter();
  const [address, setAddress] = useState("");
  const [error, setError] = useState("");
  const [suggestions, setSuggestions] = useState<AddressSuggestion[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const fetchSuggestions = useCallback(async (query: string) => {
    if (query.trim().length < 3) {
      setSuggestions([]);
      return;
    }
    const results = await fetchAddressSuggestions(query);
    setSuggestions(results);
    setShowSuggestions(results.length > 0);
    setActiveIndex(-1);
  }, []);

  function handleInputChange(value: string) {
    setAddress(value);
    if (error) setError("");
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => fetchSuggestions(value), 300);
  }

  function selectSuggestion(suggestion: AddressSuggestion) {
    setAddress(suggestion.address);
    setSuggestions([]);
    setShowSuggestions(false);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (!showSuggestions || suggestions.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => (i < suggestions.length - 1 ? i + 1 : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => (i > 0 ? i - 1 : suggestions.length - 1));
    } else if (e.key === "Enter" && activeIndex >= 0) {
      e.preventDefault();
      selectSuggestion(suggestions[activeIndex]);
    } else if (e.key === "Escape") {
      setShowSuggestions(false);
    }
  }

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const trimmed = address.trim();
    if (!trimmed) {
      setError("Please enter a full street address.");
      return;
    }
    setError("");
    setShowSuggestions(false);
    const params = new URLSearchParams({ address: trimmed });
    router.push(`/report?${params.toString()}`);
  }

  function handleExample(example: string) {
    setAddress(example);
    setError("");
    setSuggestions([]);
    setShowSuggestions(false);
  }

  return (
    <div className="min-h-screen bg-slate-900 flex flex-col">

      {/* ── Hero ── */}
      <section className="flex-1 flex items-center justify-center px-4 py-20">
        <div className="w-full max-w-2xl">

          {/* App name */}
          <div className="text-center mb-10">
            <div className="inline-flex items-center gap-3 mb-5">
              <div className="w-10 h-10 rounded-xl bg-blue-600 flex items-center justify-center shadow-lg shadow-blue-600/30">
                <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 12l8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25" />
                </svg>
              </div>
              <h1 className="text-4xl font-extrabold tracking-tight text-white">
                HomeCheck
              </h1>
            </div>

            <p className="text-2xl sm:text-3xl font-bold text-white leading-tight mb-4">
              Know what&apos;s really around your next home.
            </p>
            <p className="text-slate-400 text-base sm:text-lg leading-relaxed max-w-xl mx-auto">
              Before you buy, check for highways, industrial sites, flood zones, rail lines, and future development — using real government data.
            </p>
          </div>

          {/* Search card */}
          <div className="bg-slate-800/60 border border-slate-700 rounded-2xl p-6 sm:p-8 shadow-2xl">
            <form onSubmit={handleSubmit} className="flex flex-col gap-3">
              <div ref={wrapperRef} className="relative">
                <input
                  id="address-input"
                  type="text"
                  value={address}
                  onChange={(e) => handleInputChange(e.target.value)}
                  onKeyDown={handleKeyDown}
                  onFocus={() => {
                    if (suggestions.length > 0) setShowSuggestions(true);
                  }}
                  placeholder="123 Main St, Austin, TX 78701"
                  className="w-full px-4 py-3.5 rounded-xl bg-slate-900 text-white placeholder-slate-500
                             border border-slate-600 focus:outline-none focus:ring-2 focus:ring-blue-500
                             focus:border-transparent text-base transition"
                  autoComplete="off"
                  autoFocus
                  role="combobox"
                  aria-expanded={showSuggestions}
                  aria-autocomplete="list"
                  aria-controls="address-suggestions"
                  aria-activedescendant={activeIndex >= 0 ? `suggestion-${activeIndex}` : undefined}
                />
                {showSuggestions && suggestions.length > 0 && (
                  <ul
                    id="address-suggestions"
                    role="listbox"
                    className="absolute z-50 left-0 right-0 mt-1 bg-slate-800 border border-slate-600
                               rounded-xl overflow-hidden shadow-2xl"
                  >
                    {suggestions.map((s, i) => (
                      <li
                        key={i}
                        id={`suggestion-${i}`}
                        role="option"
                        aria-selected={i === activeIndex}
                        className={`px-4 py-3 text-sm cursor-pointer transition-colors duration-100
                          ${i === activeIndex
                            ? "bg-blue-600 text-white"
                            : "text-slate-200 hover:bg-slate-700"
                          }`}
                        onMouseDown={() => selectSuggestion(s)}
                        onMouseEnter={() => setActiveIndex(i)}
                      >
                        <span className="flex items-center gap-2">
                          <svg className="w-4 h-4 flex-shrink-0 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M15 10.5a3 3 0 11-6 0 3 3 0 016 0z" />
                            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S2 17.642 2 10.5a8 8 0 0117 0z" />
                          </svg>
                          {s.address}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              {error && (
                <p className="text-red-400 text-sm -mt-1">{error}</p>
              )}
              <button
                type="submit"
                className="w-full py-3.5 rounded-xl bg-blue-600 hover:bg-blue-500 active:bg-blue-700
                           text-white font-semibold text-base transition-colors duration-150 shadow-lg
                           shadow-blue-600/20 focus:outline-none focus:ring-2 focus:ring-blue-400
                           focus:ring-offset-2 focus:ring-offset-slate-900"
              >
                Check this address &rarr;
              </button>
            </form>

            {/* Example chips */}
            <div className="mt-4">
              <p className="text-slate-500 text-xs mb-2">Try these examples:</p>
              <div className="flex flex-wrap gap-2">
                {EXAMPLE_ADDRESSES.map((ex) => (
                  <button
                    key={ex}
                    type="button"
                    onClick={() => handleExample(ex)}
                    className="text-xs px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600
                               text-slate-300 hover:text-white border border-slate-600 hover:border-slate-500
                               transition-colors duration-150"
                  >
                    {ex}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Feature grid ── */}
      <section className="px-4 pb-20 max-w-5xl mx-auto w-full">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {FEATURES.map((f) => (
            <div
              key={f.title}
              className="bg-slate-800 border border-slate-700 rounded-2xl p-6 flex flex-col gap-3"
            >
              <div className="w-10 h-10 rounded-lg bg-slate-700 flex items-center justify-center text-blue-400 flex-shrink-0">
                {f.icon}
              </div>
              <h3 className="text-white font-semibold text-base">{f.title}</h3>
              <p
                className="text-slate-400 text-sm leading-relaxed"
                dangerouslySetInnerHTML={{ __html: f.body }}
              />
            </div>
          ))}
        </div>
      </section>

      {/* ── Data sources bar ── */}
      <footer className="border-t border-slate-800 py-5 px-4">
        <p className="text-center text-slate-600 text-xs">
          Powered by OpenStreetMap &middot; EPA TRI &middot; USDA FSIS &middot; TCEQ &middot; FEMA NFHL &middot; MSRB EMMA
        </p>
      </footer>
    </div>
  );
}
