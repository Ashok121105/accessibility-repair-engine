import { Activity, Repeat2, RotateCcw, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

import type { HindsightSummary } from "../../types/api";

export default function LearningSummary({ summary }: { summary: HindsightSummary }) {
  return (
    <div className="hindsight-summary-grid" aria-label="Historical accessibility metrics">
      <Metric icon={<Activity size={14} />} label="Scans analyzed" value={summary.total_scans_analyzed} />
      <Metric icon={<Repeat2 size={14} />} label="Issues analyzed" value={summary.total_issues_analyzed} />
      <Metric icon={<ShieldCheck size={14} />} label="Successfully repaired" value={summary.successful_repairs} />
      <Metric icon={<RotateCcw size={14} />} label="Returned after repair" value={summary.returned_after_repair} />
    </div>
  );
}

function Metric({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: number;
}) {
  return (
    <div className="hindsight-metric">
      <span>{icon}{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
