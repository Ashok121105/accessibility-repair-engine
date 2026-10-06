import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { DashboardMetrics } from "../../types/api";

const impacts = ["critical", "serious", "moderate", "minor"] as const;

export default function ViolationBreakdown({
  before,
  after,
}: {
  before: DashboardMetrics | null;
  after: DashboardMetrics | null;
}) {
  if (!before || !after) {
    return (
      <section className="dashboard-chart-card" aria-label="Severity distribution chart">
        <h3>Severity distribution</h3>
        <p>Severity comparison appears after an isolated before/after rescan.</p>
      </section>
    );
  }
  const data = impacts.map((impact) => ({
    impact: impact[0].toUpperCase() + impact.slice(1),
    Before: before[impact],
    After: after[impact],
  }));
  return (
    <section className="dashboard-chart-card" aria-label="Severity distribution chart">
      <h3>Severity distribution</h3>
      <div className="dashboard-chart" role="img" aria-label="Actual critical, serious, moderate, and minor violations before and after">
        <ResponsiveContainer height="100%" width="100%">
          <BarChart data={data} margin={{ top: 8, right: 10, left: -18, bottom: 0 }}>
            <CartesianGrid stroke="#e4e9eb" strokeDasharray="3 4" vertical={false} />
            <XAxis dataKey="impact" />
            <YAxis allowDecimals={false} />
            <Tooltip />
            <Legend />
            <Bar dataKey="Before" fill="#bb745f" radius={[3, 3, 0, 0]} />
            <Bar dataKey="After" fill="#19a68a" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
