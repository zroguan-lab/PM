export type EntityType = "Asset" | "Topic" | "Content" | "Manual";
export type Direction = "positive" | "negative" | "neutral";

export interface Asset {
  id: string;
  ticker: string;
  name: string;
  type: "equity" | "crypto" | "index";
  price: string;
  dayChange: string;
  fundamentalStatus: string;
  viewpoint: string;
  action: string;
  position: string;
  updatedAt: string;
}

export interface Metric {
  id: string;
  assetId: string;
  name: string;
  value: string;
  change: string;
  note: string;
  updatedAt: string;
}

export interface Change {
  id: string;
  relatedType: "Asset" | "Topic";
  relatedId: string;
  title: string;
  description: string;
  direction: Direction;
  type: string;
  happenedAt: string;
}

export interface Topic {
  id: string;
  name: string;
  thesis: string;
  updatedAt: string;
}

export interface Evidence {
  id: string;
  topicId: string;
  side: "support" | "counter";
  title: string;
  source: string;
  date: string;
  note: string;
}

export interface Decision {
  id: string;
  assetId: string;
  action: string;
  position: string;
  reason: string;
  result: "正确" | "错误" | "未验证";
  note: string;
  createdAt: string;
}

export interface Content {
  id: string;
  title: string;
  body: string;
  status: "DRAFT" | "PUBLISHED";
  sourceType: EntityType;
  sourceId: string | null;
  createdAt: string;
  updatedAt: string;
  publishedAt?: string;
}

export interface Task {
  id: string;
  title: string;
  status: "pending" | "completed";
  priority: "HIGH" | "MEDIUM" | "LOW";
  relatedType: EntityType;
  relatedId: string | null;
  createdAt: string;
}
