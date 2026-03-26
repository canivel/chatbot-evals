"use client";

import { useParams } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { MetricChart } from "@/components/dashboard/metric-chart";
import { ScoreCard } from "@/components/dashboard/score-card";
import {
  ArrowLeft,
  Download,
  FileJson,
  FileText,
  FileCode,
  ClipboardCheck,
  MessageSquare,
  AlertTriangle,
} from "lucide-react";
import {
  formatDate,
  formatScore,
  getStatusColor,
  getScoreColor,
  cn,
} from "@/lib/utils";
import Link from "next/link";

// -- Mock data --

const evalDetail = {
  id: "eval-001",
  name: "Weekly Production Eval",
  status: "completed" as const,
  conversations_count: 150,
  overall_score: 0.84,
  created_at: "2026-03-24T14:30:00Z",
  completed_at: "2026-03-24T15:12:00Z",
  config: {
    metrics: [
      "correctness",
      "relevance",
      "helpfulness",
      "coherence",
      "safety",
      "tone",
    ],
    judge_model: "gpt-4o",
  },
  metric_scores: [
    { metric: "Correctness", score: 0.87, passed: 131, failed: 19, total: 150 },
    { metric: "Relevance", score: 0.82, passed: 123, failed: 27, total: 150 },
    { metric: "Helpfulness", score: 0.78, passed: 117, failed: 33, total: 150 },
    { metric: "Coherence", score: 0.91, passed: 137, failed: 13, total: 150 },
    { metric: "Safety", score: 0.95, passed: 143, failed: 7, total: 150 },
    { metric: "Tone", score: 0.73, passed: 110, failed: 40, total: 150 },
  ],
  conversation_results: [
    {
      id: "cr-001",
      conversation_id: "conv-1042",
      overall_score: 0.92,
      flags: [],
      created_at: "2026-03-24T14:31:00Z",
    },
    {
      id: "cr-002",
      conversation_id: "conv-1043",
      overall_score: 0.45,
      flags: ["Hallucination", "Incomplete Answer"],
      created_at: "2026-03-24T14:31:05Z",
    },
    {
      id: "cr-003",
      conversation_id: "conv-1044",
      overall_score: 0.88,
      flags: [],
      created_at: "2026-03-24T14:31:10Z",
    },
    {
      id: "cr-004",
      conversation_id: "conv-1045",
      overall_score: 0.71,
      flags: ["Tone Mismatch"],
      created_at: "2026-03-24T14:31:15Z",
    },
    {
      id: "cr-005",
      conversation_id: "conv-1046",
      overall_score: 0.96,
      flags: [],
      created_at: "2026-03-24T14:31:20Z",
    },
    {
      id: "cr-006",
      conversation_id: "conv-1047",
      overall_score: 0.33,
      flags: ["Safety Flag", "Hallucination"],
      created_at: "2026-03-24T14:31:25Z",
    },
    {
      id: "cr-007",
      conversation_id: "conv-1048",
      overall_score: 0.85,
      flags: [],
      created_at: "2026-03-24T14:31:30Z",
    },
    {
      id: "cr-008",
      conversation_id: "conv-1049",
      overall_score: 0.79,
      flags: ["Incomplete Answer"],
      created_at: "2026-03-24T14:31:35Z",
    },
  ],
};

export default function EvalDetailPage() {
  const params = useParams();
  const id = params.id as string;

  const chartData = evalDetail.metric_scores.map((m) => ({
    name: m.metric,
    score: m.score,
  }));

  const flaggedCount = evalDetail.conversation_results.filter(
    (r) => r.flags.length > 0
  ).length;

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="mb-2 flex items-center gap-3">
            <Link href="/dashboard/evals">
              <Button variant="ghost" size="icon" className="h-8 w-8">
                <ArrowLeft className="h-4 w-4" />
              </Button>
            </Link>
            <h1 className="text-2xl font-bold tracking-tight">
              {evalDetail.name}
            </h1>
            <Badge variant={getStatusColor(evalDetail.status)}>
              {evalDetail.status}
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground">
            ID: {id} | Judge: {evalDetail.config.judge_model} | Started:{" "}
            {formatDate(evalDetail.created_at)}
            {evalDetail.completed_at &&
              ` | Completed: ${formatDate(evalDetail.completed_at)}`}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm">
            <FileJson className="mr-1.5 h-3.5 w-3.5" />
            JSON
          </Button>
          <Button variant="outline" size="sm">
            <FileText className="mr-1.5 h-3.5 w-3.5" />
            CSV
          </Button>
          <Button variant="outline" size="sm">
            <FileCode className="mr-1.5 h-3.5 w-3.5" />
            HTML
          </Button>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid gap-4 sm:grid-cols-3">
        <ScoreCard
          label="Overall Score"
          value={evalDetail.overall_score}
          isScore
          icon={ClipboardCheck}
        />
        <ScoreCard
          label="Conversations"
          value={evalDetail.conversations_count}
          subtitle={`${flaggedCount} flagged`}
          icon={MessageSquare}
        />
        <ScoreCard
          label="Issues Found"
          value={flaggedCount}
          subtitle={`${((flaggedCount / evalDetail.conversations_count) * 100).toFixed(1)}% flagged rate`}
          icon={AlertTriangle}
        />
      </div>

      {/* Metric scores chart + breakdown */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Metric Scores</CardTitle>
          </CardHeader>
          <CardContent>
            <MetricChart data={chartData} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Metric Breakdown</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {evalDetail.metric_scores.map((m) => (
                <div key={m.metric} className="space-y-1">
                  <div className="flex items-center justify-between text-sm">
                    <span className="font-medium">{m.metric}</span>
                    <span className={cn("font-semibold", getScoreColor(m.score))}>
                      {formatScore(m.score)}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                      <div
                        className={cn(
                          "h-full rounded-full transition-all",
                          m.score >= 0.8
                            ? "bg-success"
                            : m.score >= 0.6
                              ? "bg-warning"
                              : "bg-danger"
                        )}
                        style={{ width: `${m.score * 100}%` }}
                      />
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {m.passed}/{m.total}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Per-conversation results */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Conversation Results</CardTitle>
            <span className="text-sm text-muted-foreground">
              Showing {evalDetail.conversation_results.length} of{" "}
              {evalDetail.conversations_count}
            </span>
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Conversation ID</TableHead>
                <TableHead>Score</TableHead>
                <TableHead>Flags</TableHead>
                <TableHead>Evaluated At</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {evalDetail.conversation_results.map((result) => (
                <TableRow
                  key={result.id}
                  className={cn(
                    result.flags.length > 0 && "bg-danger/5"
                  )}
                >
                  <TableCell className="font-mono text-sm">
                    {result.conversation_id}
                  </TableCell>
                  <TableCell>
                    <span
                      className={cn(
                        "font-semibold",
                        getScoreColor(result.overall_score)
                      )}
                    >
                      {formatScore(result.overall_score)}
                    </span>
                  </TableCell>
                  <TableCell>
                    {result.flags.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {result.flags.map((flag) => (
                          <Badge key={flag} variant="danger">
                            {flag}
                          </Badge>
                        ))}
                      </div>
                    ) : (
                      <span className="text-xs text-muted-foreground">
                        No issues
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDate(result.created_at)}
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
