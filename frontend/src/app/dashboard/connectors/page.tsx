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
import { Plus, Plug, RefreshCw, Trash2 } from "lucide-react";
import { formatDate, getStatusColor } from "@/lib/utils";

// -- Mock data --

interface Connector {
  id: string;
  name: string;
  type: "mavenagi" | "intercom" | "zendesk" | "webhook" | "rest" | "file";
  status: "connected" | "disconnected" | "syncing" | "error";
  last_sync: string | null;
  conversations_synced: number;
  created_at: string;
}

const connectors: Connector[] = [
  {
    id: "conn-001",
    name: "Production MavenAGI",
    type: "mavenagi",
    status: "connected",
    last_sync: "2026-03-25T08:00:00Z",
    conversations_synced: 1250,
    created_at: "2026-01-15T10:00:00Z",
  },
  {
    id: "conn-002",
    name: "Support Intercom",
    type: "intercom",
    status: "connected",
    last_sync: "2026-03-25T07:30:00Z",
    conversations_synced: 890,
    created_at: "2026-02-01T14:00:00Z",
  },
  {
    id: "conn-003",
    name: "Zendesk Tickets",
    type: "zendesk",
    status: "syncing",
    last_sync: "2026-03-24T22:00:00Z",
    conversations_synced: 450,
    created_at: "2026-02-20T09:00:00Z",
  },
  {
    id: "conn-004",
    name: "Staging Webhook",
    type: "webhook",
    status: "connected",
    last_sync: "2026-03-25T09:15:00Z",
    conversations_synced: 244,
    created_at: "2026-03-01T16:00:00Z",
  },
  {
    id: "conn-005",
    name: "Legacy REST Import",
    type: "rest",
    status: "disconnected",
    last_sync: "2026-03-10T12:00:00Z",
    conversations_synced: 0,
    created_at: "2026-01-20T11:00:00Z",
  },
  {
    id: "conn-006",
    name: "Test Data (CSV)",
    type: "file",
    status: "connected",
    last_sync: "2026-03-20T15:00:00Z",
    conversations_synced: 100,
    created_at: "2026-03-20T15:00:00Z",
  },
];

const connectorTypeLabels: Record<Connector["type"], string> = {
  mavenagi: "MavenAGI",
  intercom: "Intercom",
  zendesk: "Zendesk",
  webhook: "Webhook",
  rest: "REST API",
  file: "File Upload",
};

export default function ConnectorsPage() {
  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Connectors</h1>
          <p className="text-muted-foreground">
            Manage your data source connections
          </p>
        </div>
        <Button>
          <Plus className="mr-2 h-4 w-4" />
          Add Connector
        </Button>
      </div>

      {/* Summary cards */}
      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-success/10 p-2">
                <Plug className="h-4 w-4 text-success" />
              </div>
              <div>
                <p className="text-2xl font-bold">
                  {connectors.filter((c) => c.status === "connected").length}
                </p>
                <p className="text-xs text-muted-foreground">Connected</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-warning/10 p-2">
                <RefreshCw className="h-4 w-4 text-warning" />
              </div>
              <div>
                <p className="text-2xl font-bold">
                  {connectors.filter((c) => c.status === "syncing").length}
                </p>
                <p className="text-xs text-muted-foreground">Syncing</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-primary/10 p-2">
                <Plug className="h-4 w-4 text-primary" />
              </div>
              <div>
                <p className="text-2xl font-bold">
                  {connectors
                    .reduce((sum, c) => sum + c.conversations_synced, 0)
                    .toLocaleString()}
                </p>
                <p className="text-xs text-muted-foreground">
                  Total Conversations
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Connectors table */}
      <Card>
        <CardHeader>
          <CardTitle>All Connectors</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Last Sync</TableHead>
                <TableHead>Conversations</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="w-[80px]">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {connectors.map((connector) => (
                <TableRow key={connector.id}>
                  <TableCell className="font-medium">
                    {connector.name}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">
                      {connectorTypeLabels[connector.type]}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant={getStatusColor(connector.status)}>
                      {connector.status === "syncing" && (
                        <RefreshCw className="mr-1 h-3 w-3 animate-spin" />
                      )}
                      {connector.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {connector.last_sync
                      ? formatDate(connector.last_sync)
                      : "Never"}
                  </TableCell>
                  <TableCell>
                    {connector.conversations_synced.toLocaleString()}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDate(connector.created_at)}
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button variant="ghost" size="icon" title="Resync">
                        <RefreshCw className="h-4 w-4" />
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
    </div>
  );
}
