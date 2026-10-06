import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";

import type { ComparisonPoint } from "../types/scan";

interface ComparisonChartProps {
  data: ComparisonPoint[];
}

function ComparisonChart({ data }: ComparisonChartProps) {
  return (
    <ResponsiveContainer height="100%" width="100%">
      <BarChart data={data} margin={{ top: 5, right: 4, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="#e9edef" strokeDasharray="3 5" vertical={false} />
        <XAxis dataKey="stage" hide />
        <YAxis domain={[0, 100]} hide />
        <Bar dataKey="score" fill="#10a88b" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export default ComparisonChart;
