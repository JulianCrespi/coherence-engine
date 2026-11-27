"use strict";

const scenes = [
  { id: "remember", label: "Remember", roles: [["delivery", "Delivery"]] },
  { id: "respond", label: "Respond", roles: [
    ["delivery", "Delivery"], ["legal", "Legal"], ["verifier", "Verifier"],
  ] },
  { id: "discover", label: "Discover", roles: [["product", "Product"]] },
];

const map = document.querySelector("#map");
const canvas = document.querySelector("#links");
const nodes = document.querySelector("#nodes");
const roleList = document.querySelector("#roles");
const evidence = document.querySelector("#evidence");
const sceneTitle = document.querySelector("#scene-title");
const sceneSummary = document.querySelector("#scene-summary");
const status = document.querySelector("#run-status");
const mapStatus = document.querySelector("#map-status");
const relationships = document.querySelector("#relationship-items");
const previous = document.querySelector("#previous");
const next = document.querySelector("#next");
const actButtons = [...document.querySelectorAll(".act")];
let scene = 0;
let role = "delivery";
let selected = "";
let view;
let requestId = 0;
const nodeButtons = new Map();

function textElement(tag, value, className = "") {
  const element = document.createElement(tag);
  element.textContent = value;
  if (className) element.className = className;
  return element;
}

function factList(entries) {
  const facts = document.createElement("dl");
  facts.className = "facts";
  for (const [label, value] of entries) {
    const row = document.createElement("div");
    row.append(textElement("dt", label), textElement("dd", value));
    facts.append(row);
  }
  return facts;
}

function inspect(id) {
  const node = view.nodes.find(item => item.id === id);
  if (!node) return;
  selected = id;
  for (const [key, button] of nodeButtons) {
    button.setAttribute("aria-pressed", String(key === id));
  }
  const parts = [
    textElement("h3", node.title),
    textElement("p", node.kind, "kind"),
    textElement("p", node.detail, "detail"),
  ];
  if (node.facts.length) parts.push(factList(node.facts));
  for (const result of node.readback ?? []) {
    const record = document.createElement("section");
    record.className = "readback-record";
    record.append(textElement("h4", result.title), textElement("p", result.detail));
    if (result.facts) record.append(factList(result.facts));
    parts.push(record);
  }
  evidence.replaceChildren(...parts);
  draw();
}

function render(nextView) {
  view = nextView;
  sceneTitle.textContent = view.title;
  sceneSummary.textContent = view.summary;
  nodes.replaceChildren();
  nodeButtons.clear();
  for (const node of view.nodes) {
    const button = document.createElement("button");
    button.className = "graph-node";
    button.dataset.kind = node.kind.toLowerCase();
    button.style.left = node.x + "%";
    button.style.top = node.y + "%";
    button.append(textElement("span", node.kind, "kind"), textElement("strong", node.title));
    button.addEventListener("click", () => inspect(node.id));
    nodeButtons.set(node.id, button);
    nodes.append(button);
  }
  const titles = Object.fromEntries(view.nodes.map(node => [node.id, node.title]));
  relationships.replaceChildren(...view.edges.map(link => textElement(
    "li", titles[link.start] + " · " + link.label + " · " + titles[link.end],
  )));
  inspect(view.focus);
}

function draw() {
  const width = map.clientWidth;
  const height = map.clientHeight;
  if (!width || !height) return;
  const ratio = window.devicePixelRatio || 1;
  const ctx = canvas.getContext("2d");
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  ctx.scale(ratio, ratio);
  if (!view) return;

  const points = new Map(view.nodes.map(node => {
    const button = nodeButtons.get(node.id);
    return [node.id, {
      x: node.x * width / 100,
      y: node.y * height / 100,
      rx: button.offsetWidth / 2 + 2,
      ry: button.offsetHeight / 2 + 2,
    }];
  }));
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.font = "600 11px Avenir Next, Segoe UI, sans-serif";
  for (const [index, link] of view.edges.entries()) {
    const a = points.get(link.start);
    const b = points.get(link.end);
    const length = Math.hypot(b.x - a.x, b.y - a.y);
    const ux = (b.x - a.x) / length;
    const uy = (b.y - a.y) / length;
    const start = Math.min(a.rx / Math.abs(ux), a.ry / Math.abs(uy));
    const end = Math.min(b.rx / Math.abs(ux), b.ry / Math.abs(uy));
    if (start + end >= length) continue;
    const sx = a.x + ux * start;
    const sy = a.y + uy * start;
    const tx = b.x - ux * end;
    const ty = b.y - uy * end;
    const mx = (sx + tx) / 2;
    const my = (sy + ty) / 2;
    const bend = index % 2 === 0 ? 7 : -7;
    const cx = mx - uy * bend;
    const cy = my + ux * bend;
    const active = link.start === selected || link.end === selected;
    ctx.strokeStyle = active ? "#58479c" : "#6c859b";
    ctx.fillStyle = ctx.strokeStyle;
    ctx.lineWidth = active ? 1.8 : 1.15;
    ctx.setLineDash(link.copy ? [5, 4] : []);
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.quadraticCurveTo(cx, cy, tx, ty);
    ctx.stroke();
    ctx.setLineDash([]);
    const arrow = Math.atan2(ty - cy, tx - cx);
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(tx - 7 * Math.cos(arrow - 0.47), ty - 7 * Math.sin(arrow - 0.47));
    ctx.lineTo(tx - 7 * Math.cos(arrow + 0.47), ty - 7 * Math.sin(arrow + 0.47));
    ctx.fill();
    if (width >= 475 && length - start - end > 37) {
      const along = link.copy ? 0.27 : 0.5;
      const rest = 1 - along;
      const lx = rest * rest * sx + 2 * rest * along * cx + along * along * tx;
      const ly = rest * rest * sy + 2 * rest * along * cy + along * along * ty;
      const labelWidth = ctx.measureText(link.label).width + 7;
      ctx.fillStyle = "#edf4f8";
      ctx.fillRect(lx - labelWidth / 2, ly - 8, labelWidth, 16);
      ctx.fillStyle = active ? "#4b3987" : "#3b566e";
      ctx.fillText(link.label, lx, ly);
    }
  }
}

function updateControls() {
  for (const button of actButtons) {
    if (button.dataset.scene === scenes[scene].id) button.setAttribute("aria-current", "step");
    else button.removeAttribute("aria-current");
  }
  previous.disabled = scene === 0;
  next.textContent = scene === scenes.length - 1 ? "Restart walkthrough" : "Next · " + scenes[scene + 1].label;
  roleList.replaceChildren(...scenes[scene].roles.map(([id, label]) => {
    const button = textElement("button", label, "role");
    button.setAttribute("aria-pressed", String(id === role));
    button.addEventListener("click", () => selectView(scene, id, true));
    return button;
  }));
}

async function selectView(index, selectedRole, keepRoleFocus = false) {
  scene = index;
  role = selectedRole || scenes[scene].roles[0][0];
  const request = ++requestId;
  updateControls();
  if (keepRoleFocus) roleList.querySelector('[aria-pressed="true"]').focus();
  // Clear the previous viewpoint while loading the requested role.
  view = null;
  selected = "";
  nodes.replaceChildren();
  nodeButtons.clear();
  relationships.replaceChildren();
  sceneTitle.textContent = scenes[scene].label;
  sceneSummary.textContent = "";
  evidence.replaceChildren(textElement("p", "Select a graph node.", "placeholder"));
  mapStatus.textContent = "Loading graph";
  mapStatus.hidden = false;
  map.setAttribute("aria-busy", "true");
  draw();
  try {
    const url = new URL("/api/view", window.location.origin);
    url.searchParams.set("scene", scenes[scene].id);
    url.searchParams.set("role", role);
    const response = await fetch(url);
    if (!response.ok) throw new Error("View unavailable");
    const result = await response.json();
    if (request !== requestId) return;
    render(result);
    mapStatus.hidden = true;
    status.removeAttribute("data-error");
    status.textContent = "Verified replay";
  } catch (error) {
    if (request !== requestId) return;
    status.dataset.error = "";
    status.textContent = "Replay unavailable";
    mapStatus.textContent = "Start the local judge replay and refresh this page.";
  } finally {
    if (request === requestId) map.removeAttribute("aria-busy");
  }
}

for (const button of actButtons) {
  button.addEventListener("click", () => selectView(scenes.findIndex(item => item.id === button.dataset.scene)));
}
previous.addEventListener("click", () => selectView(scene - 1));
next.addEventListener("click", () => selectView((scene + 1) % scenes.length));
new ResizeObserver(draw).observe(map);
selectView(0);
