"use client";

import { useState } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
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
import {
  Key,
  Plus,
  Trash2,
  Bell,
  Building,
  Beaker,
  Copy,
  Eye,
  EyeOff,
} from "lucide-react";
import { formatDate } from "@/lib/utils";

// -- Mock data --

const orgSettings = {
  org_name: "Acme Corp",
  plan: "Pro",
};

const apiKeys = [
  {
    id: "key-001",
    name: "Production API Key",
    prefix: "cev_prod_****a3f2",
    created_at: "2026-01-15T10:00:00Z",
    last_used: "2026-03-25T08:30:00Z",
  },
  {
    id: "key-002",
    name: "Staging API Key",
    prefix: "cev_stg_****b7d1",
    created_at: "2026-02-01T14:00:00Z",
    last_used: "2026-03-24T16:00:00Z",
  },
  {
    id: "key-003",
    name: "CI/CD Pipeline",
    prefix: "cev_ci_****c9e4",
    created_at: "2026-03-10T09:00:00Z",
    last_used: null,
  },
];

const defaultMetrics = [
  "correctness",
  "relevance",
  "helpfulness",
  "coherence",
  "safety",
  "tone",
];

const alertRules = [
  {
    id: "alert-001",
    name: "Low Correctness Alert",
    metric: "correctness",
    threshold: 0.7,
    operator: "lt" as const,
    enabled: true,
  },
  {
    id: "alert-002",
    name: "Safety Score Drop",
    metric: "safety",
    threshold: 0.9,
    operator: "lt" as const,
    enabled: true,
  },
  {
    id: "alert-003",
    name: "High Failure Rate",
    metric: "overall",
    threshold: 0.6,
    operator: "lt" as const,
    enabled: false,
  },
];

const operatorLabels: Record<string, string> = {
  lt: "less than",
  gt: "greater than",
  lte: "at most",
  gte: "at least",
};

export default function SettingsPage() {
  const [showKey, setShowKey] = useState<Record<string, boolean>>({});

  const toggleShowKey = (id: string) => {
    setShowKey((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">
          Manage organization, API keys, and evaluation defaults
        </p>
      </div>

      {/* Organization settings */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Building className="h-5 w-5 text-muted-foreground" />
            <div>
              <CardTitle>Organization</CardTitle>
              <CardDescription>
                General organization settings
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="text-sm font-medium text-foreground">
                Organization Name
              </label>
              <input
                type="text"
                defaultValue={orgSettings.org_name}
                className="mt-1.5 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus:border-primary focus:ring-1 focus:ring-ring"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-foreground">
                Plan
              </label>
              <div className="mt-1.5 flex items-center gap-2">
                <Badge variant="info">{orgSettings.plan}</Badge>
                <Button variant="link" size="sm" className="h-auto p-0">
                  Upgrade
                </Button>
              </div>
            </div>
          </div>
          <div className="mt-4">
            <Button size="sm">Save Changes</Button>
          </div>
        </CardContent>
      </Card>

      {/* API Keys */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Key className="h-5 w-5 text-muted-foreground" />
              <div>
                <CardTitle>API Keys</CardTitle>
                <CardDescription>
                  Manage API keys for programmatic access
                </CardDescription>
              </div>
            </div>
            <Button size="sm">
              <Plus className="mr-2 h-3.5 w-3.5" />
              Create Key
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Key</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Last Used</TableHead>
                <TableHead className="w-[100px]">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {apiKeys.map((key) => (
                <TableRow key={key.id}>
                  <TableCell className="font-medium">{key.name}</TableCell>
                  <TableCell>
                    <code className="rounded bg-muted px-2 py-1 text-xs">
                      {showKey[key.id]
                        ? key.prefix.replace("****", "abcd1234")
                        : key.prefix}
                    </code>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDate(key.created_at)}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {key.last_used ? formatDate(key.last_used) : "Never"}
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => toggleShowKey(key.id)}
                        title={showKey[key.id] ? "Hide" : "Reveal"}
                      >
                        {showKey[key.id] ? (
                          <EyeOff className="h-4 w-4" />
                        ) : (
                          <Eye className="h-4 w-4" />
                        )}
                      </Button>
                      <Button variant="ghost" size="icon" title="Copy">
                        <Copy className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        title="Delete"
                        className="text-danger hover:text-danger"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Alert Rules */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Bell className="h-5 w-5 text-muted-foreground" />
              <div>
                <CardTitle>Alert Rules</CardTitle>
                <CardDescription>
                  Configure alerts for quality thresholds
                </CardDescription>
              </div>
            </div>
            <Button size="sm">
              <Plus className="mr-2 h-3.5 w-3.5" />
              Add Rule
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {alertRules.map((rule) => (
              <div
                key={rule.id}
                className="flex items-center justify-between rounded-lg border border-border p-4"
              >
                <div className="flex items-center gap-3">
                  <div
                    className={`h-2.5 w-2.5 rounded-full ${
                      rule.enabled ? "bg-success" : "bg-muted-foreground/30"
                    }`}
                  />
                  <div>
                    <p className="text-sm font-medium">{rule.name}</p>
                    <p className="text-xs text-muted-foreground">
                      Alert when{" "}
                      <span className="font-medium">{rule.metric}</span> is{" "}
                      {operatorLabels[rule.operator]}{" "}
                      <span className="font-medium">
                        {(rule.threshold * 100).toFixed(0)}%
                      </span>
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant={rule.enabled ? "success" : "default"}>
                    {rule.enabled ? "Active" : "Disabled"}
                  </Badge>
                  <Button variant="ghost" size="sm">
                    Edit
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Eval Defaults */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Beaker className="h-5 w-5 text-muted-foreground" />
            <div>
              <CardTitle>Evaluation Defaults</CardTitle>
              <CardDescription>
                Default settings for new evaluation runs
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium text-foreground">
                Default Metrics
              </label>
              <div className="mt-2 flex flex-wrap gap-2">
                {defaultMetrics.map((metric) => (
                  <Badge key={metric} variant="info" className="cursor-pointer">
                    {metric}
                  </Badge>
                ))}
                <Button
                  variant="outline"
                  size="sm"
                  className="h-6 rounded-full px-2 text-xs"
                >
                  <Plus className="mr-1 h-3 w-3" />
                  Add
                </Button>
              </div>
            </div>

            <div>
              <label className="text-sm font-medium text-foreground">
                Judge Model
              </label>
              <select
                defaultValue="gpt-4o"
                className="mt-1.5 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus:border-primary focus:ring-1 focus:ring-ring sm:w-64"
              >
                <option value="gpt-4o">GPT-4o</option>
                <option value="gpt-4o-mini">GPT-4o Mini</option>
                <option value="claude-3.5-sonnet">Claude 3.5 Sonnet</option>
                <option value="claude-3-haiku">Claude 3 Haiku</option>
              </select>
            </div>

            <div>
              <label className="text-sm font-medium text-foreground">
                Pass Threshold
              </label>
              <div className="mt-1.5 flex items-center gap-2">
                <input
                  type="number"
                  defaultValue="0.7"
                  min="0"
                  max="1"
                  step="0.05"
                  className="w-24 rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus:border-primary focus:ring-1 focus:ring-ring"
                />
                <span className="text-sm text-muted-foreground">
                  (0.0 - 1.0)
                </span>
              </div>
            </div>

            <div>
              <Button size="sm">Save Defaults</Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
