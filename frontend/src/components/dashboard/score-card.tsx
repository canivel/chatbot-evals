import { cn, getScoreBgColor, formatScore } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";
import { TrendingUp, TrendingDown, Minus, type LucideIcon } from "lucide-react";

interface ScoreCardProps {
  label: string;
  value: number | string;
  subtitle?: string;
  trend?: "up" | "down" | "flat";
  trendValue?: string;
  icon?: LucideIcon;
  isScore?: boolean;
}

export function ScoreCard({
  label,
  value,
  subtitle,
  trend,
  trendValue,
  icon: Icon,
  isScore = false,
}: ScoreCardProps) {
  const TrendIcon =
    trend === "up" ? TrendingUp : trend === "down" ? TrendingDown : Minus;

  const trendColor =
    trend === "up"
      ? "text-success"
      : trend === "down"
        ? "text-danger"
        : "text-muted-foreground";

  return (
    <Card>
      <CardContent className="p-6">
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <p className="text-sm font-medium text-muted-foreground">{label}</p>
            <div className="mt-2 flex items-baseline gap-2">
              <span
                className={cn(
                  "text-2xl font-bold",
                  isScore && typeof value === "number"
                    ? getScoreBgColor(value) + " rounded-md px-2 py-0.5"
                    : ""
                )}
              >
                {isScore && typeof value === "number"
                  ? formatScore(value)
                  : value}
              </span>
              {trend && trendValue && (
                <span className={cn("flex items-center text-xs", trendColor)}>
                  <TrendIcon className="mr-0.5 h-3 w-3" />
                  {trendValue}
                </span>
              )}
            </div>
            {subtitle && (
              <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>
            )}
          </div>
          {Icon && (
            <div className="rounded-lg bg-primary/10 p-2.5">
              <Icon className="h-5 w-5 text-primary" />
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
