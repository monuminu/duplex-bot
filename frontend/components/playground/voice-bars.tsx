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
        "speaking-bars flex items-center justify-center gap-1 text-cyan-300",
        compact ? "h-8" : "h-16",
        !active && "opacity-45",
        className,
      )}
      aria-hidden="true"
    >
      {heights.map((height, index) => (
        <span
          key={`${height}-${index}`}
          className={cn(
            "block w-1 rounded-full bg-current shadow-[0_0_16px_rgba(0,255,255,0.8)]",
            !active && "[animation-play-state:paused]",
          )}
          style={{ height: compact ? Math.max(8, height / 2) : height }}
        />
      ))}
    </div>
  );
}
