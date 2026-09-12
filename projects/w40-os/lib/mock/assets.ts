import type { Asset } from "@/lib/types";

export const assets: ReadonlyArray<Asset> = [
  { id: "asset-mrvl", ticker: "MRVL", name: "Marvell Technology", type: "equity", price: "$74.60", dayChange: "+2.4%", fundamentalStatus: "增强", viewpoint: "看多", action: "持有", position: "6%", updatedAt: "2026-09-10 09:40" },
  { id: "asset-mu", ticker: "MU", name: "Micron Technology", type: "equity", price: "$125.00", dayChange: "+2.1%", fundamentalStatus: "观察", viewpoint: "中性", action: "观察", position: "0%", updatedAt: "2026-09-10 09:40" },
  { id: "asset-nvda", ticker: "NVDA", name: "NVIDIA", type: "equity", price: "$118.42", dayChange: "+1.3%", fundamentalStatus: "持有", viewpoint: "看多", action: "持有", position: "0%", updatedAt: "2026-09-10 09:40" },
  { id: "asset-tsla", ticker: "TSLA", name: "Tesla", type: "equity", price: "$226.17", dayChange: "-0.8%", fundamentalStatus: "观察", viewpoint: "中性", action: "观察", position: "0%", updatedAt: "2026-09-10 09:40" },
  { id: "asset-btc", ticker: "BTC", name: "Bitcoin", type: "crypto", price: "$63,248", dayChange: "+1.8%", fundamentalStatus: "关注", viewpoint: "中性", action: "观察", position: "0%", updatedAt: "2026-09-10 09:40" },
  { id: "asset-gev", ticker: "GEV", name: "GE Vernova", type: "equity", price: "$281.30", dayChange: "+0.6%", fundamentalStatus: "研究中", viewpoint: "中性", action: "观察", position: "0%", updatedAt: "2026-09-10 09:40" },
  { id: "asset-etn", ticker: "ETN", name: "Eaton", type: "equity", price: "$336.80", dayChange: "+0.4%", fundamentalStatus: "研究中", viewpoint: "中性", action: "观察", position: "0%", updatedAt: "2026-09-10 09:40" },
  { id: "asset-vst", ticker: "VST", name: "Vistra", type: "equity", price: "$92.45", dayChange: "+0.9%", fundamentalStatus: "研究中", viewpoint: "中性", action: "观察", position: "0%", updatedAt: "2026-09-10 09:40" },
  { id: "asset-ndx", ticker: "NDX", name: "Nasdaq 100", type: "index", price: "17,084", dayChange: "+0.7%", fundamentalStatus: "", viewpoint: "", action: "", position: "", updatedAt: "2026-09-10 09:40" },
  { id: "asset-sox", ticker: "SOX", name: "PHLX Semiconductor", type: "index", price: "4,982", dayChange: "+1.4%", fundamentalStatus: "", viewpoint: "", action: "", position: "", updatedAt: "2026-09-10 09:40" },
];

export const commandBarAssetIds = ["asset-btc", "asset-ndx", "asset-sox", "asset-mu", "asset-mrvl"] as const;
export const investAssetIds = ["asset-mrvl", "asset-mu", "asset-nvda", "asset-tsla", "asset-btc"] as const;
export const primaryInvestAssetId = "asset-mrvl";
