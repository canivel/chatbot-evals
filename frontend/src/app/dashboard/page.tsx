"use client";

import { ScoreCard } from "@/components/dashboard/score-card";
import { MetricChart } from "@/components/dashboard/metric-chart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  ClipboardCheck,
  MessageSquare,
  Activity,
  Plug,
  AlertTriangle,
} from "lucide-react";
import { formatDate, formatScore, getStatusColor } from "@/lib/utils";
import Link from "next/link";

// -- Mock data --

const stats = {
  total_evals: 47,
  total_conversations: 2834,
  health_score: 0.82,
  active_connectors: 3,
};

const recentEvals = [
  {
    id: "eval-001",
    name: "Weekly Production Eval",
    status: "completed" as const,
    conversations_count: 150,
    overall_score: 0.84,
    created_at: "2026-03-24T14:30:00Z",
  },
  {
    id: "eval-002",
    name: "Regression Check - v2.1",
    status: "running" as const,
    conversations_count: 75,
    overall_score: 0.0,
    created_at: "2026-03-25T09:00:00Z",
  },
  {
    id: "eval-003",
    name: "New FAQ Coverage Test",
    status: "completed" as const,
    conversations_count: 200,
    overall_score: 0.71,
    created_at: "2026-03-23T11:15:00Z",
  },
  {
    id: "eval-004",
    name: "Post-Deploy Validation",
    status: "failed" as const,
    conversations_count: 50,
    overall_score: 0.0,
    created_at: "2026-03-22T16:45:00Z",
  },
  {
    id: "eval-005",
    name: "Sentiment Analysis Baseline",
    status: "completed" as const,
    conversations_count: 300,
    overall_score: 0.91,
    created_at: "2026-03-21T08:00:00Z",
  },
];

const metricScores = [
  { name: "Correctness", score: 0.87 },
  { name: "Relevance", score: 0.82 },
  { name: "Helpfulness", score: 0.78 },
  { name: "Coherence", score: 0.91 },
  { name: "Safety", score: 0.95 },
  { name: "Tone", score: 0.73 },
];

const topIssues = [
  {
    id: 1,
    type: "Hallucination",
    count: 12,
    severity: "danger" as const,
    description: "Bot fabricated product features not in knowledge base",
  },
  {
    id: 2,
    type: "Incomplete Answer",
    count: 8,
    severity: "warning" as const,
    description: "Responses missing key details for refund policy questions",
  },
  {
    id: 3,
    type: "Tone Mismatch",
    count: 5,
    severity: "warning" as const,
    description: "Overly formal tone in casual conversation contexts",
  },
  {
    id: 4,
    type: "Safety Flag",
    count: 2,
    severity: "danger" as const,
    description: "Bot disclosed internal system details when probed",
  },
];

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">
          Overview of your chatbot evaluation performance
        </p>
      </div>

      {/* Overview cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <ScoreCard
          label="Total Evaluations"
          value={stats.total_evals}
          subtitle="12 this week"
          trend="up"
          trendValue="+8%"
          icon={ClipboardCheck}
        />
        <ScoreCard
          label="Conversations Analyzed"
          value={stats.total_conversations.toLocaleString()}
          subtitle="Across all evals"
          trend="up"
          trendValue="+23%"
          icon={MessageSquare}
        />
        <ScoreCard
          label="Health Score"
          value={stats.health_score}
          isScore
          subtitle="Avg across all metrics"
          trend="up"
          trendValue="+2.1%"
          icon={Activity}
        />
        <ScoreCard
          label="Active Connectors"
          value={stats.active_connectors}
          subtitle="2 sources, 1 webhook"
          trend="flat"
          trendValue="No change"
          icon={Plug}
        />
      </div>

      {/* Charts and tables */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Metric health chart */}
        <Card>
          <CardHeader>
            <CardTitle>Metric Health</CardTitle>
          </CardHeader>
          <CardContent>
            <MetricChart data={metricScores} />
          </CardContent>
        </Card>

        {/* Top issues */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-warning" />
              Top Issues
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {topIssues.map((issue) => (
                <div
                  key={issue.id}
                  className="flex items-start justify-between rounded-lg border border-border p-3"
                >
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <Badge variant={issue.severity}>{issue.type}</Badge>
                      <span className="text-xs text-muted-foreground">
                        {issue.count} occurrences
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {issue.description}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Recent eval runs */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Recent Evaluation Runs</CardTitle>
            <Link
              href="/dashboard/evals"
              className="text-sm font-medium text-primary hover:underline"
            >
              View all
            </Link>
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Conversations</TableHead>
                <TableHead>Score</TableHead>
                <TableHead>Date</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {recentEvals.map((evalRun) => (
                <TableRow key={evalRun.id}>
                  <TableCell>
                    <Link
                      href={`/dashboard/evals/${evalRun.id}`}
                      className="font-medium text-foreground hover:text-primary hover:underline"
                    >
                      {evalRun.name}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Badge variant={getStatusColor(evalRun.status)}>
                      {evalRun.status}
                    </Badge>
                  </TableCell>
                  <TableCell>{evalRun.conversations_count}</TableCell>
                  <TableCell>
                    {evalRun.status === "completed" ? (
                      <span className="font-medium">
                        {formatScore(evalRun.overall_score)}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">--</span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDate(evalRun.created_at)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
