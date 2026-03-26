import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(date: string | Date): string {
  const d = typeof date === "string" ? new Date(date) : date;
  return d.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDateShort(date: string | Date): string {
  const d = typeof date === "string" ? new Date(date) : date;
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

export function formatScore(score: number): string {
  return (score * 100).toFixed(1) + "%";
}

export function formatScoreRaw(score: number): string {
  return score.toFixed(2);
}

export function getScoreColor(score: number): string {
  if (score >= 0.8) return "text-success";
  if (score >= 0.6) return "text-warning";
  return "text-danger";
}

export function getScoreBgColor(score: number): string {
  if (score >= 0.8) return "bg-success/10 text-success";
  if (score >= 0.6) return "bg-warning/10 text-warning";
  return "bg-danger/10 text-danger";
}

export function getStatusColor(
  status: string
): "default" | "success" | "warning" | "danger" | "info" {
  switch (status.toLowerCase()) {
    case "completed":
    case "connected":
    case "active":
    case "healthy":
      return "success";
    case "running":
    case "syncing":
    case "pending":
      return "warning";
    case "failed":
    case "error":
    case "disconnected":
      return "danger";
    default:
      return "default";
  }
}

export function truncate(str: string, length: number): string {
  if (str.length <= length) return str;
  return str.slice(0, length) + "...";
}
