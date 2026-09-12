import { cn } from "@/lib/utils";

export function TickerItem({ symbol, price, dayChange }: { symbol: string; price: string; dayChange: string }) {
  const negative = dayChange.startsWith("-");
  return <span className="ticker"><b>{symbol}</b><span>{price.replace("$", "")}</span><em className={cn(negative && "value-negative")}>{dayChange}</em></span>;
}
