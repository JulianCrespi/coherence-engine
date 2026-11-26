"use strict";

const day = document.querySelector("#day");
const form = document.querySelector("#ask-form");
const question = document.querySelector("#question");
const ask = document.querySelector("#ask");
const status = document.querySelector("#ask-status");
const watch = document.querySelector("#watch");
const rule = document.querySelector("#rule");
const observations = document.querySelector("#observations");
const baseline = document.querySelector("#baseline");
const connected = document.querySelector("#connected");
let snapshot;

async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "The North demo is unavailable.");
  return data;
}

function dayOf(isoDate) {
  return Number(isoDate.slice(8, 10));
}

function element(tag, value, className) {
  const node = document.createElement(tag);
  node.textContent = value;
  if (className) node.className = className;
  return node;
}

function resetResult(panel, message) {
  panel.querySelector(".answer-text").textContent = message;
  panel.querySelector(".answer-usage").textContent = "";
  panel.querySelector(".answer-evidence").replaceChildren();
}

function renderTimeline(data) {
  const finding = data.relate.activity.find((run) => run.observation);
  const latest = data.relate.activity.at(-1);
  watch.textContent = finding
    ? `Day ${dayOf(finding.scheduled_at)} · ${finding.scheduled_at.slice(11, 16)} simulation time. Commercial Ops surfaced the signed amendment and notified Maya’s agent.`
    : `Day ${dayOf(latest.scheduled_at)} · ${latest.scheduled_at.slice(11, 16)} simulation time. The scheduled check found no new signed amendment.`;
  const current = data.relate.rule;
  rule.textContent = `Deadline at this cutoff: ${current.hours} hours · In effect from Day ${dayOf(current.effective_from)}.`;
  observations.replaceChildren(...data.relate.observations.map((item) => {
    const row = element("li", "");
    const source = data.sources.find((record) => record.source === item.source);
    const effective = item.effective_from ? ` · Effective Day ${dayOf(item.effective_from)}` : "";
    row.append(
      element("strong", item.statement),
      element("p", `${item.author} · Happened Day ${dayOf(item.happened_on)} · Recorded Day ${dayOf(item.recorded_on)}${effective}`, "observation-meta"),
      element("p", `${item.source} · ${item.span} · v${item.version}`, "observation-meta"),
    );
    if (source) {
      const detail = element("details", "");
      detail.append(element("summary", "Read source"), element("p", source.passage));
      row.append(detail);
    }
    return row;
  }));
}

function renderResult(panel, result, sources) {
  resetResult(panel, result.error || result.answer);
  if (result.error) return;
  const usage = result.usage;
  panel.querySelector(".answer-usage").textContent =
    `${result.seconds}s · ${usage.input_tokens.toLocaleString()} input / ${usage.output_tokens.toLocaleString()} output tokens`;
  const items = result.citations.map((id) => sources.find((source) => source.source === id)).filter(Boolean);
  panel.querySelector(".answer-evidence").append(...items.map((source) => {
    const detail = element("details", "");
    detail.append(element("summary", `${source.source} · ${source.span}`), element("p", source.passage));
    return detail;
  }));
}

async function load() {
  ask.disabled = true;
  day.disabled = true;
  status.textContent = "";
  resetResult(baseline, "Maya’s permitted source records.");
  resetResult(connected, "The same records, with temporal observations and their graph connections.");
  try {
    snapshot = await request(`/api/north?day=${day.value}`);
    if (!question.value) question.value = snapshot.question;
    renderTimeline(snapshot);
    ask.disabled = false;
  } catch (error) {
    watch.textContent = error.message;
    rule.textContent = "";
    observations.replaceChildren();
  } finally {
    day.disabled = false;
  }
}

day.addEventListener("change", load);
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = question.value.trim();
  if (!snapshot || !text) return;
  ask.disabled = true;
  day.disabled = true;
  question.readOnly = true;
  status.textContent = "Sol Low is answering both sides…";
  resetResult(baseline, "Waiting for the live answer.");
  resetResult(connected, "Waiting for the live answer.");
  try {
    const pair = await request("/api/ask", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({day: snapshot.day, question: text}),
    });
    renderResult(baseline, pair.baseline, snapshot.sources);
    renderResult(connected, pair.relate, snapshot.sources);
    status.textContent = pair.baseline.error || pair.relate.error
      ? "A live answer is unavailable. You can try again."
      : `Both answers complete · Day ${pair.day}`;
  } catch (error) {
    status.textContent = error.message;
    resetResult(baseline, "Answer unavailable.");
    resetResult(connected, "Answer unavailable.");
  } finally {
    ask.disabled = false;
    day.disabled = false;
    question.readOnly = false;
  }
});

load();
