import { Bell, Search, UserRound } from "lucide-react";
import { assets, commandBarAssetIds } from "@/lib/mock/assets";
import { Button } from "@/components/ui/button";
import { TickerItem } from "@/components/shared/ticker-item";

export function CommandBar() {
  const tickers = commandBarAssetIds.map((id) => assets.find((asset) => asset.id === id)).filter((asset) => asset !== undefined);
  return (
    <header className="command-bar">
      <label className="search-box">
        <Search size={16} />
        <input aria-label="全局搜索" placeholder="搜索资产、研究或内容…" />
        <kbd>⌘ K</kbd>
      </label>
      <div className="ticker-bar" aria-label="市场行情示例">
        {tickers.map((ticker) => <TickerItem key={ticker.id} symbol={ticker.ticker} price={ticker.price} dayChange={ticker.dayChange} />)}
      </div>
      <div className="command-actions">
        <Button variant="ghost" size="icon" aria-label="通知"><Bell size={17} /></Button>
        <Button variant="ghost" size="icon" aria-label="用户"><UserRound size={17} /></Button>
      </div>
    </header>
  );
}
