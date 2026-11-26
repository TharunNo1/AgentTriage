"use strict";

const byId = (id) => document.getElementById(id);
const statuses = ["NEW", "TRIAGING", "AWAITING_APPROVAL", "REMEDIATING", "VERIFYING", "MANUAL", "ESCALATED", "RESOLVED", "SUPPRESSED"];
const eventLimit = 50;
const time = (value) => new Date(value).toLocaleString();
const message = (value) => { byId("message").textContent = value; };
let token = "";
let session;
let controller;
let cursor;
let filters;
let current;
let proposal;
let eventCursor;

for (const status of statuses) byId("filter-status").add(new Option(status.replaceAll("_", " "), status));

function signOut() {
  controller?.abort();
  controller = undefined;
  token = "";
  session = undefined;
  cursor = undefined;
  current = undefined;
  proposal = undefined;
  for (const id of ["identity", "mode", "incidents", "title", "metadata", "summary", "ticket", "action", "approval-expiry", "events"]) {
    byId(id).replaceChildren();
  }
  for (const id of ["sign-in", "filters", "approval", "transition"]) byId(id).reset();
  for (const id of ["workspace", "sign-out", "selected", "more-incidents", "more-events"]) byId(id).hidden = true;
  byId("select-incident").hidden = false;
  byId("sign-in").hidden = false;
  message("");
}
byId("sign-out").addEventListener("click", () => { signOut(); byId("key").focus(); });
window.addEventListener("pagehide", signOut);

async function run(task) {
  if (controller) return;
  const operation = new AbortController();
  controller = operation;
  document.body.setAttribute("aria-busy", "true");
  message("");
  try {
    await task(operation.signal);
  } catch (error) {
    if (!operation.signal.aborted) {
      if (error.status === 401 || !session) signOut();
      message(error.message || "Request failed.");
    }
  } finally {
    if (controller === operation) controller = undefined;
    if (!controller) document.body.removeAttribute("aria-busy");
  }
}

async function api(path, signal, body) {
  const headers = { Authorization: `Bearer ${token}` };
  if (body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers,
    body: body && JSON.stringify(body),
    cache: "no-store",
    credentials: "omit",
    redirect: "error",
    signal,
  });
  if (!response.ok) {
    const problem = await response.json().catch(() => null);
    signal.throwIfAborted();
    const detail = problem?.detail || (response.status >= 500
      ? "The incident API is unavailable. Try again shortly."
      : `Request failed (${response.status}).`);
    throw Object.assign(new Error(detail), { status: response.status });
  }
  const data = await response.json();
  signal.throwIfAborted();
  return data;
}

async function refreshHealth(signal) {
  let checks = {};
  try {
    const response = await fetch("/readyz", { cache: "no-store", credentials: "omit", signal });
    if (response.ok || response.status === 503) checks = (await response.json()).checks || {};
  } catch {
    signal.throwIfAborted();
  }
  signal.throwIfAborted();
  for (const name of ["database", "redis"]) byId(name).textContent = checks[name] || "Unknown";
}

async function loadIncidents(signal, append = false) {
  const query = new URLSearchParams(filters);
  if (append && cursor) query.set("cursor", cursor);
  const page = await api(`/v1/incidents?${query}`, signal);
  const list = byId("incidents");
  if (!append) list.replaceChildren();
  for (const incident of page.items) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    const description = document.createElement("span");
    button.type = "button";
    button.textContent = incident.title;
    button.dataset.id = incident.id;
    button.setAttribute("aria-pressed", String(current?.id === incident.id));
    description.className = "hint";
    description.textContent = `${incident.severity} / ${incident.service} / ${incident.status.replaceAll("_", " ")}`;
    button.append(description);
    button.addEventListener("click", () => run((signal) => loadDetail(incident.id, signal)));
    item.append(button);
    list.append(item);
  }
  if (!append && !page.items.length) {
    const item = document.createElement("li");
    item.textContent = "No incidents match these filters.";
    list.append(item);
  }
  cursor = page.next_cursor;
  byId("more-incidents").hidden = !cursor;
}

async function loadEvents(id, signal) {
  const rows = await api(`/v1/incidents/${id}/events?after_id=${eventCursor}&limit=${eventLimit}`, signal);
  for (const event of rows) {
    const item = document.createElement("li");
    item.textContent = `${time(event.created_at)} / ${event.actor} / ${event.type.replaceAll("_", " ")}`;
    if (event.to_status) item.append(` / ${event.to_status.replaceAll("_", " ")}`);
    if (typeof event.data?.note === "string" && event.data.note) item.append(` / ${event.data.note}`);
    byId("events").append(item);
    eventCursor = event.id;
  }
  if (!rows.length && !eventCursor) {
    const item = document.createElement("li");
    item.textContent = "No events recorded.";
    byId("events").append(item);
  }
  byId("more-events").hidden = rows.length < eventLimit;
}

async function loadDetail(id, signal) {
  byId("selected").hidden = true;
  byId("select-incident").hidden = false;
  current = undefined;
  proposal = undefined;
  const incident = await api(`/v1/incidents/${id}`, signal);
  if (incident.status === "AWAITING_APPROVAL") proposal = await api(`/v1/incidents/${id}/approval`, signal);
  eventCursor = 0;
  byId("events").replaceChildren();
  await loadEvents(id, signal);
  current = incident;
  for (const button of byId("incidents").querySelectorAll("button")) {
    button.setAttribute("aria-pressed", String(button.dataset.id === id));
  }
  byId("title").textContent = incident.title;
  byId("metadata").textContent = `${incident.service} / ${incident.severity} / ${incident.status.replaceAll("_", " ")} / ${incident.occurrence_count} signals / last seen ${time(incident.last_signal_at)}`;
  byId("summary").textContent = incident.rca_summary || "No root cause analysis recorded.";
  byId("ticket").textContent = incident.ticket_id ? `Ticket ${incident.ticket_id}` : "";
  byId("proposal").hidden = !proposal;
  byId("approval").hidden = !proposal || !session.can_decide_approval;
  byId("approval").reset();
  updateReason();
  if (proposal) {
    byId("approval-expiry").textContent = `Expires ${time(proposal.expires_at)}`;
    byId("action").textContent = JSON.stringify({ action: proposal.action_type, parameters: proposal.params }, null, 2);
  }
  byId("transition").reset();
  byId("transition").hidden = !session.can_transition || ["RESOLVED", "SUPPRESSED"].includes(incident.status);
  for (const option of byId("target").options) option.disabled = option.value === incident.status;
  byId("select-incident").hidden = true;
  byId("selected").hidden = false;
}

function updateReason() {
  const rejecting = byId("decision").value === "reject";
  byId("reason-field").hidden = !rejecting;
  byId("reason").required = rejecting;
}
byId("decision").addEventListener("change", updateReason);

byId("sign-in").addEventListener("submit", (event) => {
  event.preventDefault();
  run(async (signal) => {
    token = byId("key").value.trim();
    byId("sign-in").reset();
    session = await api("/v1/dashboard/session", signal);
    byId("identity").textContent = session.name;
    byId("mode").textContent = session.remediation_mode.replaceAll("_", " ");
    byId("workspace").hidden = false;
    byId("sign-out").hidden = false;
    byId("sign-in").hidden = true;
    byId("main").focus();
    filters = {};
    await Promise.all([refreshHealth(signal), loadIncidents(signal)]);
  });
});

byId("filters").addEventListener("submit", (event) => {
  event.preventDefault();
  run(async (signal) => {
    const params = new URLSearchParams();
    const status = byId("filter-status").value;
    const service = byId("filter-service").value.trim();
    if (status) params.set("status", status);
    if (service) params.set("service", service);
    const previous = filters;
    filters = params;
    try {
      await loadIncidents(signal);
    } catch (error) {
      if (!signal.aborted) filters = previous;
      throw error;
    }
    await refreshHealth(signal);
    if (current) await loadDetail(current.id, signal);
  });
});
byId("more-incidents").addEventListener("click", () => run((signal) => loadIncidents(signal, true)));
byId("more-events").addEventListener("click", () => run((signal) => loadEvents(current.id, signal)));

async function submitAction(path, body, signal) {
  const { id } = current;
  await api(`/v1/incidents/${id}/${path}`, signal, body);
  try {
    await loadDetail(id, signal);
    await loadIncidents(signal);
  } catch (error) {
    if (signal.aborted || error.status === 401) throw error;
    message(`Change saved. Refresh failed: ${error.message}`);
    return;
  }
  message("Change saved.");
}

byId("approval").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!session?.can_decide_approval || !current || !proposal) return;
  const decision = byId("decision").value;
  const reason = decision === "reject" ? byId("reason").value : null;
  run((signal) => submitAction("approval", {
    approval_id: proposal.approval_id, decision, reason, note: byId("approval-note").value || null,
  }, signal));
});
byId("transition").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!session?.can_transition || !current) return;
  run((signal) => submitAction("transition", {
    status: byId("target").value, note: byId("transition-note").value || null,
  }, signal));
});
