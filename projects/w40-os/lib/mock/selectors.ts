import { assets } from "@/lib/mock/assets";
import { contents } from "@/lib/mock/contents";
import { assetTopicLinks } from "@/lib/mock/relations";
import { topics } from "@/lib/mock/topics";
import type { EntityType } from "@/lib/types";

export function getAsset(id: string) {
  const asset = assets.find((item) => item.id === id);
  if (!asset) throw new Error(`Unknown asset: ${id}`);
  return asset;
}

export function getTopic(id: string) {
  const topic = topics.find((item) => item.id === id);
  if (!topic) throw new Error(`Unknown topic: ${id}`);
  return topic;
}

export function getTopicsForAsset(assetId: string) {
  const topicIds = assetTopicLinks.filter((link) => link.assetId === assetId).map((link) => link.topicId);
  return topics.filter((topic) => topicIds.includes(topic.id as (typeof topicIds)[number]));
}

export function getAssetsForTopic(topicId: string) {
  const assetIds = assetTopicLinks.filter((link) => link.topicId === topicId).map((link) => link.assetId);
  return assets.filter((asset) => assetIds.includes(asset.id as (typeof assetIds)[number]));
}

export function getEntityLabel(type: EntityType, id: string | null) {
  if (type === "Asset" && id) return getAsset(id).ticker;
  if (type === "Topic" && id) return getTopic(id).name;
  if (type === "Content" && id) return contents.find((item) => item.id === id)?.title ?? "内容";
  return "手动创建";
}

export function getSourcePath(type: EntityType) {
  if (type === "Asset") return "/invest";
  if (type === "Topic") return "/research";
  return null;
}

export function getContentSourceLabel(type: EntityType) {
  if (type === "Asset") return "INVEST";
  if (type === "Topic") return "RESEARCH";
  return "MANUAL";
}

export function formatMockTime(iso: string) {
  return iso.slice(11, 16);
}

export function formatMockDate(iso: string) {
  const date = new Date(iso);
  return date.toLocaleDateString("en-US", { month: "short", day: "2-digit", timeZone: "Asia/Shanghai" }).toUpperCase();
}
