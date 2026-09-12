"use client";

import { useEffect, useState } from "react";
import { Check, Circle, Clock3, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/shared/page-header";
import { SectionHeader } from "@/components/shared/section-header";
import { StatusBadge } from "@/components/shared/status-badge";
import { changes, todayChangeIds } from "@/lib/mock/changes";
import { getEntityLabel, formatMockTime } from "@/lib/mock/selectors";
import { tasks, todayTaskIds } from "@/lib/mock/tasks";
import { captureTypes } from "@/lib/mock/ui";
import type { Direction, Task } from "@/lib/types";
import { cn } from "@/lib/utils";

const TASK_STORAGE_KEY = "w40.today.completed-tasks";
const CAPTURE_STORAGE_KEY = "w40.today.captures";

type CaptureType = (typeof captureTypes)[number];
type Capture = { id: string; type: CaptureType; text: string; createdAt: string };

const directionLabels: Record<Direction, string> = {
  positive: "正面",
  negative: "负面",
  neutral: "中性",
};

export function TodayDashboard() {
  const todayChanges = todayChangeIds.map((id) => changes.find((change) => change.id === id)).filter((change) => change !== undefined);
  const todayTasks = todayTaskIds.map((id) => tasks.find((task) => task.id === id)).filter((task) => task !== undefined);
  const [completed, setCompleted] = useState<string[]>([]);
  const [captureType, setCaptureType] = useState<CaptureType>("Note");
  const [captureText, setCaptureText] = useState("");
  const [captures, setCaptures] = useState<Capture[]>([]);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const restore = window.setTimeout(() => {
      try {
        setCompleted(JSON.parse(localStorage.getItem(TASK_STORAGE_KEY) ?? "[]"));
        setCaptures(JSON.parse(localStorage.getItem(CAPTURE_STORAGE_KEY) ?? "[]"));
      } catch {
        setCompleted([]);
        setCaptures([]);
      }
    }, 0);

    return () => window.clearTimeout(restore);
  }, []);

  function toggleTask(id: string) {
    setCompleted((current) => {
      const next = current.includes(id) ? current.filter((item) => item !== id) : [...current, id];
      localStorage.setItem(TASK_STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  }

  function saveCapture() {
    const text = captureText.trim();
    if (!text) return;
    const next: Capture[] = [{ id: crypto.randomUUID(), type: captureType, text, createdAt: new Date().toISOString() }, ...captures].slice(0, 5);
    setCaptures(next);
    localStorage.setItem(CAPTURE_STORAGE_KEY, JSON.stringify(next));
    setCaptureText("");
    setSaved(true);
    window.setTimeout(() => setSaved(false), 1600);
  }

  return (
    <section className="today-page">
      <PageHeader className="today-heading" eyebrow="TODAY" title="今日" subtitle="今天有什么值得我处理？" updatedAt={<div className="today-date"><Clock3 size={14} /><span>SEP 10 · WED</span></div>} />

      <section className="today-section signals-section" aria-labelledby="signals-heading">
        <SectionHeader eyebrow="SIGNALS" title="重要变化" id="signals-heading" action={<span>3 ITEMS</span>} />
        <div className="signal-list">
          {todayChanges.map((change) => (
            <article className="signal-row" key={change.id}>
              <span className={cn("direction-rail", `direction-${change.direction}`)} />
              <div className="signal-object"><strong>{getEntityLabel(change.relatedType, change.relatedId)}</strong><time>{formatMockTime(change.happenedAt)}</time></div>
              <div className="signal-copy"><h3>{change.title}</h3><p>{change.description}</p></div>
              <StatusBadge tone={change.direction}>{directionLabels[change.direction]}</StatusBadge>
            </article>
          ))}
        </div>
      </section>

      <div className="today-grid">
        <section className="today-section" aria-labelledby="tasks-heading">
          <SectionHeader eyebrow="FOCUS" title="今日任务" id="tasks-heading" action={<span>{completed.length} / {todayTasks.length} DONE</span>} />
          <div className="task-list">
            {todayTasks.map((task) => {
              const isDone = completed.includes(task.id);
              return (
                <button className={cn("task-row", isDone && "task-complete")} key={task.id} onClick={() => toggleTask(task.id)} aria-pressed={isDone}>
                  <span className="task-check">{isDone ? <Check size={14} /> : <Circle size={14} />}</span>
                  <span className="task-copy"><strong>{task.title}</strong><small>{getTaskContextLabel(task)}</small></span>
                  <span className={cn("priority", `priority-${task.priority.toLowerCase()}`)}>{task.priority}</span>
                </button>
              );
            })}
          </div>
        </section>

        <section className="today-section capture-section" aria-labelledby="capture-heading">
          <SectionHeader eyebrow="CAPTURE" title="快速记录" id="capture-heading" action={<span>LOCAL</span>} />
          <div className="capture-types" role="group" aria-label="记录类型">
            {captureTypes.map((type) => <button key={type} className={cn(captureType === type && "capture-type-active")} onClick={() => setCaptureType(type)} aria-pressed={captureType === type}>{type}</button>)}
          </div>
          <textarea value={captureText} onChange={(event) => setCaptureText(event.target.value)} placeholder="记录想法、问题、链接或研究线索…" aria-label="快速记录内容" />
          <div className="capture-footer">
            <span>{captures.length ? `已保存 ${captures.length} 条本地记录` : "记录仅保存在当前设备"}</span>
            <Button size="sm" onClick={saveCapture} disabled={!captureText.trim()}><Save size={14} />{saved ? "已保存" : "保存记录"}</Button>
          </div>
        </section>
      </div>
    </section>
  );
}

function getTaskContextLabel(task: Task) {
  if (task.relatedType === "Topic") return "RESEARCH";
  if (task.relatedType === "Content") return "CREATE";
  return getEntityLabel(task.relatedType, task.relatedId);
}
