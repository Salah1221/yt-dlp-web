"use strict";

const el = (id) => document.getElementById(id);
const show = (node) => node.classList.remove("hidden");
const hide = (node) => node.classList.add("hidden");

let currentUrl = "";
let jobId = null;
let socket = null;
let pollTimer = null;

function fail(text) {
  el("message").textContent = text;
  show(el("message"));
}

function clearFail() {
  hide(el("message"));
}

function humanSize(bytes) {
  if (!bytes) return "";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return value.toFixed(1) + " " + units[index];
}

function humanTime(seconds) {
  if (seconds === null || seconds === undefined) return "";
  const whole = Math.round(seconds);
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return minutes + "m " + String(rest).padStart(2, "0") + "s";
}

async function sendJson(method, path, body) {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "the request failed");
  return data;
}

async function postJson(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "the request failed");
  return data;
}

el("probe-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  clearFail();
  hide(el("video"));
  hide(el("formats"));
  hide(el("job"));
  el("check").disabled = true;
  el("check").textContent = "Checking";
  try {
    currentUrl = el("url").value.trim();
    const info = await postJson("/api/probe", { url: currentUrl });
    el("title").textContent = info.title;
    el("duration").textContent = info.duration ? humanTime(info.duration) : "";
    if (info.thumbnail) {
      el("thumb").src = info.thumbnail;
      show(el("thumb"));
    } else {
      hide(el("thumb"));
    }
    fillQualities(info.qualities);
    fillFormats(info.formats);
    show(el("video"));
  } catch (error) {
    fail(error.message);
  } finally {
    el("check").disabled = false;
    el("check").textContent = "Check";
  }
});

function fillQualities(qualities) {
  const select = el("quality");
  const list = qualities || [];
  select.textContent = "";
  const best = document.createElement("option");
  best.value = "";
  best.textContent = "Best quality";
  select.appendChild(best);
  list.forEach((item) => {
    const option = document.createElement("option");
    option.value = String(item.height);
    // The size is an estimate. A site that reports none gives the height alone.
    option.textContent = item.filesize
      ? `${item.label}, about ${humanSize(item.filesize)}`
      : item.label;
    select.appendChild(option);
  });
  // A disabled control that offers one choice is noise. Hide the whole row
  // when the site reports no height at all.
  if (list.length) {
    show(el("quality-field"));
  } else {
    hide(el("quality-field"));
  }
}

function fillFormats(formats) {
  const body = el("format-rows");
  const labels = ["Format", "Type", "Size", ""];
  body.textContent = "";
  (formats || []).forEach((item) => {
    const row = document.createElement("tr");
    const kind = item.vcodec && item.vcodec !== "none"
      ? (item.acodec && item.acodec !== "none" ? "video and audio" : "video only")
      : "audio only";
    const cells = [
      `${item.resolution} ${item.ext}${item.fps ? " " + item.fps + "fps" : ""}`,
      kind,
      humanSize(item.filesize) || "unknown",
    ];
    cells.forEach((text, index) => {
      const cell = document.createElement("td");
      cell.setAttribute("data-label", labels[index]);
      cell.textContent = text;
      row.appendChild(cell);
    });
    const action = document.createElement("td");
    action.setAttribute("data-label", labels[3]);
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Get";
    button.addEventListener("click", () => startJob("format", item.format_id));
    action.appendChild(button);
    row.appendChild(action);
    body.appendChild(row);
  });
}

el("toggle-formats").addEventListener("click", () => {
  el("formats").classList.toggle("hidden");
});

document.querySelectorAll("[data-mode]").forEach((button) => {
  button.addEventListener("click", () => startJob(button.dataset.mode, null));
});

async function startJob(mode, formatId) {
  clearFail();
  stopWatching();
  hide(el("download"));
  el("fill").style.width = "0";
  el("state").textContent = "Starting";
  el("stats").textContent = "";
  show(el("job"));
  const body = { url: currentUrl, mode: mode, format_id: formatId };
  if (mode === "video") {
    const chosen = parseInt(el("quality").value, 10);
    if (chosen > 0) body.max_height = chosen;
  }
  try {
    const data = await postJson("/api/jobs", body);
    jobId = data.job_id;
    watch(jobId);
    el("job").scrollIntoView({ block: "nearest" });
  } catch (error) {
    fail(error.message);
    hide(el("job"));
  }
}

function watch(id) {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${scheme}://${window.location.host}/ws/${id}`);
  socket.onmessage = (event) => render(JSON.parse(event.data));
  socket.onclose = () => {
    socket = null;
    if (jobId === id && !pollTimer) startPolling(id);
  };
  socket.onerror = () => { if (socket) socket.close(); };
}

function startPolling(id) {
  pollTimer = setInterval(async () => {
    const response = await fetch(`/api/jobs/${id}`);
    if (!response.ok) { stopWatching(); return; }
    render(await response.json());
  }, 2000);
}

function stopWatching() {
  if (socket) { socket.onclose = null; socket.close(); socket = null; }
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

const STATE_TEXT = {
  queued: "Waiting",
  downloading: "Downloading",
  converting: "Converting with ffmpeg",
  ready: "Ready",
  error: "Failed",
  expired: "Expired",
};

function render(job) {
  el("state").textContent = STATE_TEXT[job.state] || job.state;
  el("fill").style.width = (job.percent || 0) + "%";
  if (job.state === "downloading") {
    const parts = [Math.round(job.percent) + "%"];
    if (job.speed) parts.push(humanSize(job.speed) + "/s");
    if (job.eta) parts.push(humanTime(job.eta) + " left");
    el("stats").textContent = parts.join("  ");
  } else if (job.state === "ready") {
    el("stats").textContent = job.filename || "";
    const link = el("download");
    link.href = `/api/jobs/${job.id}/file`;
    show(link);
    stopWatching();
  } else if (job.state === "error") {
    el("stats").textContent = "";
    fail(job.error || "the download failed");
    stopWatching();
  } else {
    el("stats").textContent = "";
  }
}

el("cancel").addEventListener("click", async () => {
  if (!jobId) return;
  stopWatching();
  await fetch(`/api/jobs/${jobId}`, { method: "DELETE" });
  jobId = null;
  hide(el("job"));
});

el("download").addEventListener("click", () => {
  // The server deletes the file after it sends. One download is possible.
  setTimeout(() => { hide(el("job")); jobId = null; }, 1500);
});

// The session cookie is HttpOnly, so the server has to say whether a login
// is in use. Without a login the button stays hidden.
fetch("/api/config").then((response) => response.json()).then((data) => {
  if (data.login) show(el("logout"));
}).catch(() => {});

el("logout").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" });
  window.location.replace("/login");
});

// --- The settings panel ---------------------------------------------------

function whenText(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(undefined,
    { year: "numeric", month: "short", day: "numeric" });
}

function renderCookies(state) {
  const node = el("cookie-state");
  node.classList.remove("bad");
  el("cookie-clear").disabled = state.source !== "pasted";
  if (state.source === "pasted") {
    const many = state.count === 1 ? "cookie" : "cookies";
    const parts = [`${state.count} ${many} saved ${whenText(state.saved)}`];
    if (state.domains.length) {
      const names = state.domains.join(", ");
      parts.push(state.more_domains
        ? `for ${names} and ${state.more_domains} more`
        : `for ${names}`);
    }
    // The soonest expiry is the day the site starts asking again.
    if (state.expires) parts.push(`the first expires ${whenText(state.expires)}`);
    node.textContent = parts.join(", ") + ".";
    return;
  }
  if (state.source === "file") {
    node.textContent = "The server is using a cookie file that the operator "
      + "placed. Saving here replaces it, and Remove puts it back.";
    return;
  }
  if (state.source === "broken") {
    node.textContent = "The saved file no longer reads as cookies. Save a "
      + "fresh export over it, or press Remove.";
    return;
  }
  node.textContent = state.writable
    ? "No cookies saved. The server sends none."
    : "No cookies saved, and this server cannot write the file. Its folder "
      + "belongs to another user.";
}

async function loadCookies() {
  try {
    renderCookies(await (await fetch("/api/cookies")).json());
  } catch (error) {
    el("cookie-state").textContent = "The settings did not load.";
    el("cookie-state").classList.add("bad");
  }
}

el("settings-toggle").addEventListener("click", () => {
  const panel = el("settings");
  const open = panel.classList.toggle("hidden") === false;
  el("settings-toggle").setAttribute("aria-expanded", String(open));
  if (open) loadCookies();
});

el("cookie-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  // Reading the file keeps the tabs, which a paste through some fields
  // turns into spaces. The format needs the tabs.
  el("cookie-text").value = await file.text();
  event.target.value = "";
});

el("cookie-save").addEventListener("click", async () => {
  const button = el("cookie-save");
  button.disabled = true;
  button.textContent = "Saving";
  try {
    const state = await sendJson("PUT", "/api/cookies",
                                 { text: el("cookie-text").value });
    // The page holds no copy of a credential longer than it must.
    el("cookie-text").value = "";
    renderCookies(state);
    clearFail();
  } catch (error) {
    el("cookie-state").textContent = error.message;
    el("cookie-state").classList.add("bad");
  } finally {
    button.disabled = false;
    button.textContent = "Save";
  }
});

el("cookie-clear").addEventListener("click", async () => {
  const response = await fetch("/api/cookies", { method: "DELETE" });
  if (response.ok) renderCookies(await response.json());
});
