import { cn } from "@/lib/utils";

type VoiceBarsProps = {
  active?: boolean;
  compact?: boolean;
  className?: string;
};

const heights = [18, 30, 42, 24, 54, 36, 20, 46, 28, 16];

export function VoiceBars({ active = true, compact = false, className }: VoiceBarsProps) {
  return (
    <div
      className={cn(
        "speaking-bars flex items-center justify-center gap-1 text-[var(--accent)]",
        compact ? "h-8" : "h-16",
        !active && "opacity-40",
        className,
      )}
      aria-hidden="true"
    >
      {heights.map((height, index) => (
        <span
          key={`${height}-${index}`}
          className={cn(
            "block w-1 rounded-full bg-current",
            !active && "[animation-play-state:paused]",
          )}
          style={{ height: compact ? Math.max(8, height / 2) : height }}
        />
      ))}
    </div>
  );
}
