"use server";
import { randomUUID } from "node:crypto";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";
import { db, getJudgment } from "./db";
import { dueDate } from "./types";

const judgmentSchema = z.object({
  judgment_date: z.string().min(1), symbol: z.string().trim().min(1), asset_type: z.string().min(1),
  thesis: z.string().trim().min(5), evidence: z.string().trim().min(2),
  decision: z.enum(["buy", "add", "hold", "reduce", "sell", "abandon"]),
  confidence: z.coerce.number().int().min(0).max(100), horizon_type: z.enum(["7d", "30d", "90d", "1y", "custom"]),
  custom_due_date: z.string().optional(), reference_price: z.string().optional(), benchmark: z.string().optional(), tags: z.string().optional()
});

function optionalNumber(value: FormDataEntryValue | null) {
  if (value === null || String(value).trim() === "") return null;
  const number = Number(value); return Number.isFinite(number) ? number : null;
}

export async function createJudgment(formData: FormData) {
  const values = judgmentSchema.parse(Object.fromEntries(formData));
  const id = randomUUID(), now = new Date().toISOString();
  const due = dueDate(values.judgment_date, values.horizon_type, values.custom_due_date);
  const insert = db.prepare(`INSERT INTO judgments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)`);
  db.exec("BEGIN");
  try {
    insert.run(id, values.judgment_date, values.symbol.toUpperCase(), values.asset_type, values.thesis,
      values.evidence, values.decision, values.confidence, values.horizon_type, due,
      optionalNumber(formData.get("reference_price")), values.benchmark?.trim() || null, now, now);
    const tagInsert = db.prepare("INSERT OR IGNORE INTO judgment_tags VALUES(?,?)");
    for (const tag of (values.tags || "").split(/[,，]/).map(x => x.trim()).filter(Boolean)) tagInsert.run(id, tag);
    db.exec("COMMIT");
  } catch (error) { db.exec("ROLLBACK"); throw error; }
  revalidatePath("/"); redirect(`/judgments/${id}`);
}

export async function addNote(id: string, formData: FormData) {
  const content = z.string().trim().min(1).parse(formData.get("content"));
  db.prepare("INSERT INTO judgment_notes VALUES(?,?,?,?)").run(randomUUID(), id, content, new Date().toISOString());
  revalidatePath(`/judgments/${id}`);
}

export async function saveReview(id: string, formData: FormData) {
  if (!getJudgment(id)) throw new Error("判断不存在");
  const required = (name: string) => z.string().trim().min(1).parse(formData.get(name));
  const actual = optionalNumber(formData.get("actual_return"));
  const benchmark = optionalNumber(formData.get("benchmark_return"));
  const excess = actual !== null && benchmark !== null ? actual - benchmark : null;
  const reviewId = randomUUID(), now = new Date().toISOString();
  db.prepare(`INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(
    reviewId,id,optionalNumber(formData.get("end_price")),actual,benchmark,excess,required("outcome"),required("result_summary"),
    required("result_reason"),required("original_thesis_valid"),required("attribution"),required("right_points"),required("wrong_points"),
    required("next_change"),String(formData.get("new_rule")||"").trim()||null,now,now);
  revalidatePath("/"); redirect(`/judgments/${id}`);
}
