import type { Priority, ReportResponse } from "./types";

interface FetchReportParams {
  address: string;
  priorities?: Priority[];
  thresholds?: Record<Priority, number>;
}

export async function fetchReport(
  params: FetchReportParams
): Promise<ReportResponse> {
  const res = await fetch("/api/report", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Request failed (${res.status})`);
  }

  return res.json();
}
