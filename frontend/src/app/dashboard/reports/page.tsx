"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Download, Calendar } from "lucide-react";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

// -- Mock data --

const trendData = [
  { date: "Mar 1", correctness: 0.81, relevance: 0.78, helpfulness: 0.74, safety: 0.92 },
  { date: "Mar 4", correctness: 0.83, relevance: 0.79, helpfulness: 0.76, safety: 0.93 },
  { date: "Mar 7", correctness: 0.8, relevance: 0.82, helpfulness: 0.75, safety: 0.91 },
  { date: "Mar 10", correctness: 0.85, relevance: 0.8, helpfulness: 0.78, safety: 0.94 },
  { date: "Mar 13", correctness: 0.82, relevance: 0.81, helpfulness: 0.77, safety: 0.93 },
  { date: "Mar 16", correctness: 0.86, relevance: 0.83, helpfulness: 0.79, safety: 0.95 },
  { date: "Mar 19", correctness: 0.84, relevance: 0.82, helpfulness: 0.8, safety: 0.94 },
  { date: "Mar 22", correctness: 0.87, relevance: 0.84, helpfulness: 0.78, safety: 0.95 },
  { date: "Mar 25", correctness: 0.87, relevance: 0.82, helpfulness: 0.78, safety: 0.95 },
];

const comparisonData = [
  { metric: "Correctness", "Eval #45": 0.84, "Eval #47": 0.87 },
  { metric: "Relevance", "Eval #45": 0.79, "Eval #47": 0.82 },
  { metric: "Helpfulness", "Eval #45": 0.75, "Eval #47": 0.78 },
  { metric: "Coherence", "Eval #45": 0.88, "Eval #47": 0.91 },
  { metric: "Safety", "Eval #45": 0.93, "Eval #47": 0.95 },
  { metric: "Tone", "Eval #45": 0.7, "Eval #47": 0.73 },
];

const volumeData = [
  { date: "Mar 1", conversations: 120 },
  { date: "Mar 4", conversations: 85 },
  { date: "Mar 7", conversations: 200 },
  { date: "Mar 10", conversations: 150 },
  { date: "Mar 13", conversations: 175 },
  { date: "Mar 16", conversations: 300 },
  { date: "Mar 19", conversations: 250 },
  { date: "Mar 22", conversations: 120 },
  { date: "Mar 25", conversations: 150 },
];

interface ChartTooltipPayloadItem {
  color: string;
  name: string;
  value: number;
}

function ScoreTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: ChartTooltipPayloadItem[];
  label?: string;
}) {
  if (active && payload && payload.length) {
    return (
      <div className="rounded-lg border border-border bg-card px-3 py-2 shadow-md">
        <p className="mb-1 text-sm font-medium">{label}</p>
        {payload.map((entry, i) => (
          <p key={i} className="text-xs" style={{ color: entry.color }}>
            {entry.name}: {(entry.value * 100).toFixed(1)}%
          </p>
        ))}
      </div>
    );
  }
  return null;
}

export default function ReportsPage() {
  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Reports</h1>
          <p className="text-muted-foreground">
            Track quality trends and compare evaluation runs
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm">
            <Calendar className="mr-2 h-4 w-4" />
            Last 30 days
          </Button>
          <Button variant="outline" size="sm">
            <Download className="mr-2 h-4 w-4" />
            Export Report
          </Button>
        </div>
      </div>

      {/* Trend chart */}
      <Card>
        <CardHeader>
          <CardTitle>Quality Trends</CardTitle>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={350}>
            <LineChart
              data={trendData}
              margin={{ top: 5, right: 20, left: 0, bottom: 5 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                className="stroke-border"
                vertical={false}
              />
              <XAxis
                dataKey="date"
                tick={{ fill: "hsl(215, 16%, 47%)", fontSize: 12 }}
                axisLine={{ stroke: "hsl(214, 32%, 91%)" }}
                tickLine={false}
              />
              <YAxis
                domain={[0.6, 1]}
                tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                tick={{ fill: "hsl(215, 16%, 47%)", fontSize: 12 }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip content={<ScoreTooltip />} />
              <Legend />
              <Line
                type="monotone"
                dataKey="correctness"
                stroke="#2563eb"
                strokeWidth={2}
                dot={{ r: 3 }}
                name="Correctness"
              />
              <Line
                type="monotone"
                dataKey="relevance"
                stroke="#7c3aed"
                strokeWidth={2}
                dot={{ r: 3 }}
                name="Relevance"
              />
              <Line
                type="monotone"
                dataKey="helpfulness"
                stroke="#d97706"
                strokeWidth={2}
                dot={{ r: 3 }}
                name="Helpfulness"
              />
              <Line
                type="monotone"
                dataKey="safety"
                stroke="#059669"
                strokeWidth={2}
                dot={{ r: 3 }}
                name="Safety"
              />
            </LineChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Comparison chart */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Run Comparison</CardTitle>
              <div className="flex gap-2">
                <Badge variant="info">Eval #45</Badge>
                <Badge variant="success">Eval #47</Badge>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart
                data={comparisonData}
                margin={{ top: 5, right: 20, left: 0, bottom: 5 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  className="stroke-border"
                  vertical={false}
                />
                <XAxis
                  dataKey="metric"
                  tick={{ fill: "hsl(215, 16%, 47%)", fontSize: 11 }}
                  axisLine={{ stroke: "hsl(214, 32%, 91%)" }}
                  tickLine={false}
                />
                <YAxis
                  domain={[0.5, 1]}
                  tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                  tick={{ fill: "hsl(215, 16%, 47%)", fontSize: 12 }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip content={<ScoreTooltip />} />
                <Bar
                  dataKey="Eval #45"
                  fill="#2563eb"
                  radius={[4, 4, 0, 0]}
                  maxBarSize={24}
                  opacity={0.6}
                />
                <Bar
                  dataKey="Eval #47"
                  fill="#059669"
                  radius={[4, 4, 0, 0]}
                  maxBarSize={24}
                />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Volume chart */}
        <Card>
          <CardHeader>
            <CardTitle>Evaluation Volume</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart
                data={volumeData}
                margin={{ top: 5, right: 20, left: 0, bottom: 5 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  className="stroke-border"
                  vertical={false}
                />
                <XAxis
                  dataKey="date"
                  tick={{ fill: "hsl(215, 16%, 47%)", fontSize: 12 }}
                  axisLine={{ stroke: "hsl(214, 32%, 91%)" }}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fill: "hsl(215, 16%, 47%)", fontSize: 12 }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  contentStyle={{
                    borderRadius: "8px",
                    border: "1px solid hsl(214, 32%, 91%)",
                    fontSize: "12px",
                  }}
                />
                <Bar
                  dataKey="conversations"
                  fill="#2563eb"
                  radius={[4, 4, 0, 0]}
                  maxBarSize={32}
                  name="Conversations"
                />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
