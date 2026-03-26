"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

interface MetricChartData {
  name: string;
  score: number;
}

interface MetricChartProps {
  data: MetricChartData[];
  title?: string;
}

function getBarColor(score: number): string {
  if (score >= 0.8) return "#059669";
  if (score >= 0.6) return "#d97706";
  return "#dc2626";
}

interface TooltipPayloadItem {
  value: number;
  payload: MetricChartData;
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string;
}) {
  if (active && payload && payload.length) {
    return (
      <div className="rounded-lg border border-border bg-card px-3 py-2 shadow-md">
        <p className="text-sm font-medium">{label}</p>
        <p className="text-sm text-muted-foreground">
          Score: {(payload[0].value * 100).toFixed(1)}%
        </p>
      </div>
    );
  }
  return null;
}

export function MetricChart({ data, title }: MetricChartProps) {
  return (
    <div className="w-full">
      {title && (
        <h3 className="mb-4 text-sm font-medium text-muted-foreground">
          {title}
        </h3>
      )}
      <ResponsiveContainer width="100%" height={300}>
        <BarChart
          data={data}
          margin={{ top: 5, right: 20, left: 0, bottom: 5 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            className="stroke-border"
            vertical={false}
          />
          <XAxis
            dataKey="name"
            className="text-xs"
            tick={{ fill: "hsl(215, 16%, 47%)", fontSize: 12 }}
            axisLine={{ stroke: "hsl(214, 32%, 91%)" }}
            tickLine={false}
          />
          <YAxis
            domain={[0, 1]}
            tickFormatter={(value: number) => `${(value * 100).toFixed(0)}%`}
            className="text-xs"
            tick={{ fill: "hsl(215, 16%, 47%)", fontSize: 12 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip content={<CustomTooltip />} />
          <Bar dataKey="score" radius={[4, 4, 0, 0]} maxBarSize={48}>
            {data.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={getBarColor(entry.score)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
