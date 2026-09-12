import test from "node:test";
import assert from "node:assert/strict";

function localDate(date){const y=date.getFullYear();const m=String(date.getMonth()+1).padStart(2,"0");const d=String(date.getDate()).padStart(2,"0");return `${y}-${m}-${d}`}
function dueDate(from,horizon,custom){if(horizon==="custom")return custom||from;const date=new Date(`${from}T12:00:00`);if(horizon==="1y")date.setFullYear(date.getFullYear()+1);else date.setDate(date.getDate()+Number(horizon.replace("d","")));return localDate(date)}
function statusOf(row,today){if(row.outcome)return "已复盘";return row.due_date<=today?"待复盘":"验证中"}

test("预设周期正确计算到期日",()=>{assert.equal(dueDate("2026-08-30","30d"),"2026-09-29");assert.equal(dueDate("2024-02-29","1y"),"2025-03-01")});
test("自定义到期日原样保存",()=>assert.equal(dueDate("2026-08-30","custom","2026-10-01"),"2026-10-01"));
test("状态随日期和复盘动态计算",()=>{assert.equal(statusOf({due_date:"2026-08-31",outcome:null},"2026-08-30"),"验证中");assert.equal(statusOf({due_date:"2026-08-30",outcome:null},"2026-08-30"),"待复盘");assert.equal(statusOf({due_date:"2026-08-20",outcome:"correct"},"2026-08-30"),"已复盘")});
