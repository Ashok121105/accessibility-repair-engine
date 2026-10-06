import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { DashboardMetrics } from "../../types/api";

export default function BeforeAfterComparison({
  before,
  after,
}: {
  before: DashboardMetrics | null;
  after: DashboardMetrics | null;
}) {
  if (!before || !after) {
    return (
      <section className="dashboard-chart-card" aria-label="Before and after violation count chart">
        <h3>Before vs after violations</h3>
        <p>No completed repair comparison yet.</p>
      </section>
    );
  }
  const data = [
    { stage: "Before", violations: before.total_violations },
    { stage: "After", violations: after.total_violations },
  ];
  return (
    <section className="dashboard-chart-card" aria-label="Before and after violation count chart">
      <h3>Before vs after violations</h3>
      <div className="dashboard-chart" role="img" aria-label={`Before ${before.total_violations}; after ${after.total_violations} actual violations`}>
        <ResponsiveContainer height="100%" width="100%">
          <BarChart data={data} margin={{ top: 8, right: 10, left: -18, bottom: 0 }}>
            <CartesianGrid stroke="#e4e9eb" strokeDasharray="3 4" vertical={false} />
            <XAxis dataKey="stage" />
            <YAxis allowDecimals={false} />
            <Tooltip />
            <Bar dataKey="violations" fill="#19a68a" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
