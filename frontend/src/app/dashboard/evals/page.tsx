"use client";

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
import { Plus, Search } from "lucide-react";
import { formatDate, formatScore, getStatusColor, getScoreColor } from "@/lib/utils";
import { cn } from "@/lib/utils";
import Link from "next/link";

// -- Mock data --

interface EvalRun {
  id: string;
  name: string;
  status: "pending" | "running" | "completed" | "failed";
  conversations_count: number;
  overall_score: number;
  created_at: string;
  metrics: string[];
}

const evalRuns: EvalRun[] = [
  {
    id: "eval-001",
    name: "Weekly Production Eval",
    status: "completed",
    conversations_count: 150,
    overall_score: 0.84,
    created_at: "2026-03-24T14:30:00Z",
    metrics: ["correctness", "relevance", "helpfulness"],
  },
  {
    id: "eval-002",
    name: "Regression Check - v2.1",
    status: "running",
    conversations_count: 75,
    overall_score: 0,
    created_at: "2026-03-25T09:00:00Z",
    metrics: ["correctness", "safety"],
  },
  {
    id: "eval-003",
    name: "New FAQ Coverage Test",
    status: "completed",
    conversations_count: 200,
    overall_score: 0.71,
    created_at: "2026-03-23T11:15:00Z",
    metrics: ["correctness", "relevance", "helpfulness", "coherence"],
  },
  {
    id: "eval-004",
    name: "Post-Deploy Validation",
    status: "failed",
    conversations_count: 50,
    overall_score: 0,
    created_at: "2026-03-22T16:45:00Z",
    metrics: ["correctness", "safety", "tone"],
  },
  {
    id: "eval-005",
    name: "Sentiment Analysis Baseline",
    status: "completed",
    conversations_count: 300,
    overall_score: 0.91,
    created_at: "2026-03-21T08:00:00Z",
    metrics: ["tone", "helpfulness"],
  },
  {
    id: "eval-006",
    name: "Multi-turn Consistency",
    status: "completed",
    conversations_count: 120,
    overall_score: 0.78,
    created_at: "2026-03-20T10:30:00Z",
    metrics: ["coherence", "correctness", "relevance"],
  },
  {
    id: "eval-007",
    name: "Safety Audit Q1",
    status: "completed",
    conversations_count: 500,
    overall_score: 0.94,
    created_at: "2026-03-19T09:00:00Z",
    metrics: ["safety"],
  },
  {
    id: "eval-008",
    name: "Onboarding Flow Review",
    status: "pending",
    conversations_count: 0,
    overall_score: 0,
    created_at: "2026-03-25T10:00:00Z",
    metrics: ["correctness", "helpfulness", "tone"],
  },
];

export default function EvalsPage() {
  const completed = evalRuns.filter((e) => e.status === "completed").length;
  const running = evalRuns.filter(
    (e) => e.status === "running" || e.status === "pending"
  ).length;
  const failed = evalRuns.filter((e) => e.status === "failed").length;

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Evaluations</h1>
          <p className="text-muted-foreground">
            Run and manage chatbot quality evaluations
          </p>
        </div>
        <Button>
          <Plus className="mr-2 h-4 w-4" />
          New Evaluation
        </Button>
      </div>

      {/* Status summary */}
      <div className="flex gap-4">
        <div className="flex items-center gap-2 rounded-lg border border-border px-3 py-1.5">
          <div className="h-2 w-2 rounded-full bg-success" />
          <span className="text-sm">
            {completed} completed
          </span>
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-border px-3 py-1.5">
          <div className="h-2 w-2 rounded-full bg-warning" />
          <span className="text-sm">
            {running} in progress
          </span>
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-border px-3 py-1.5">
          <div className="h-2 w-2 rounded-full bg-danger" />
          <span className="text-sm">
            {failed} failed
          </span>
        </div>
      </div>

      {/* Search bar */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <input
          type="text"
          placeholder="Search evaluations..."
          className="w-full rounded-lg border border-input bg-background py-2 pl-10 pr-4 text-sm outline-none focus:border-primary focus:ring-1 focus:ring-ring"
        />
      </div>

      {/* Evals table */}
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Conversations</TableHead>
                <TableHead>Score</TableHead>
                <TableHead>Metrics</TableHead>
                <TableHead>Date</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {evalRuns.map((evalRun) => (
                <TableRow key={evalRun.id} className="cursor-pointer">
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {evalRun.id}
                  </TableCell>
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
                  <TableCell>{evalRun.conversations_count || "--"}</TableCell>
                  <TableCell>
                    {evalRun.status === "completed" ? (
                      <span
                        className={cn(
                          "font-semibold",
                          getScoreColor(evalRun.overall_score)
                        )}
                      >
                        {formatScore(evalRun.overall_score)}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">--</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {evalRun.metrics.slice(0, 3).map((m) => (
                        <Badge key={m} variant="outline" className="text-[10px]">
                          {m}
                        </Badge>
                      ))}
                      {evalRun.metrics.length > 3 && (
                        <Badge variant="outline" className="text-[10px]">
                          +{evalRun.metrics.length - 3}
                        </Badge>
                      )}
                    </div>
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
