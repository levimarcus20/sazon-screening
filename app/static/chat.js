// Candidate chat: sends messages to the API and renders replies + the demo side panel.
// Exposes window.Chat so voice.js can reuse the same rendering and API calls.
(function () {
  const messagesEl = document.getElementById("messages");
  const typingEl = document.getElementById("typing");
  const form = document.getElementById("composer");
  const input = document.getElementById("input");
  const sendBtn = document.getElementById("send");
  const presence = document.getElementById("presence");

  const FIELD_LABELS = [
    ["full_name", "Full name"], ["license_status", "Driving license"], ["vehicle_type", "Vehicle"],
    ["city", "City"], ["country", "Country"], ["zone", "Zone"], ["availability", "Availability"],
    ["preferred_schedule", "Schedule"], ["experience_years", "Experience (years)"],
    ["experience_platforms", "Platforms"], ["start_date", "Start date"],
  ];
  const STATUS_LABELS = {
    in_progress: "In progress", qualified: "Qualified", disqualified: "Disqualified",
    withdrawn: "Withdrawn", needs_review: "Needs review",
  };

  const timeNow = () => new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  // voice: true marks a message spoken on a call (📞 next to the time)
  function addBubble(role, text, time, voice) {
    const div = document.createElement("div");
    div.className = "bubble " + role;
    div.textContent = text;
    if (time) {
      const t = document.createElement("time");
      t.textContent = (voice ? "📞 " : "") + time;
      div.appendChild(t);
    }
    messagesEl.insertBefore(div, typingEl);
    scrollDown();
  }

  function addNote(text, extraClass) {
    const note = document.createElement("div");
    note.className = "closed-note" + (extraClass ? " " + extraClass : "");
    note.textContent = text;
    messagesEl.insertBefore(note, typingEl);
    scrollDown();
  }

  function scrollDown() { messagesEl.scrollTop = messagesEl.scrollHeight; }

  function setBusy(busy, label) {
    typingEl.classList.toggle("show", busy);
    presence.textContent = busy ? (label || "escribiendo…") : "online";
    input.disabled = busy;
    sendBtn.disabled = busy;
    if (!busy && !form.hidden) input.focus();
    scrollDown();
  }

  function renderPanel(state) {
    Chat.state = state;
    const status = document.getElementById("p-status");
    status.className = "badge " + state.status;
    status.textContent = STATUS_LABELS[state.status] || state.status;
    document.getElementById("p-stage").textContent = "stage: " + state.stage;
    document.getElementById("p-lang").textContent = "lang: " + state.language;

    const fields = document.getElementById("p-fields");
    fields.innerHTML = "";
    for (const [key, labelText] of FIELD_LABELS) {
      let value = state.data[key];
      if (Array.isArray(value)) value = value.join(", ");
      const k = document.createElement("span");
      k.textContent = labelText;
      const v = document.createElement("strong");
      const empty = value === null || value === undefined || value === "";
      v.textContent = empty ? "—" : String(value);
      if (empty) v.className = "empty-val";
      fields.append(k, v);
    }
    if (state.interview_at) {
      const k = document.createElement("span");
      k.textContent = "Interview";
      const v = document.createElement("strong");
      v.textContent = new Date(state.interview_at).toLocaleString();
      fields.append(k, v);
    }

    const flags = document.getElementById("p-flags");
    flags.innerHTML = "";
    if (state.flags && state.flags.length) {
      const h = document.createElement("h3");
      h.textContent = "Flags for recruiter";
      h.style.marginTop = "16px";
      const ul = document.createElement("ul");
      ul.className = "flags";
      state.flags.forEach(f => { const li = document.createElement("li"); li.textContent = f; ul.appendChild(li); });
      flags.append(h, ul);
    }
    document.getElementById("p-json").textContent = JSON.stringify(state, null, 2);

    if (state.closed) {
      document.getElementById("call-btn").hidden = true;
      if (!messagesEl.querySelector(".closed-note.finished")) addNote("Screening finished", "finished");
    }
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    if (tag === "button") node.type = "button";
    return node;
  }

  // Calendar card under a slot offer (on WhatsApp this would be a Flow): one tab per
  // working day, that day's times (taken or too-soon ones greyed out), then Confirm.
  // Confirming sends the slot's label as the visible message plus a payload naming
  // the slot, which the server handles without the LLM.
  function fillSlotPicker(card, picker) {
    let dayIdx = Math.max(0, picker.days.findIndex(d => d.slots.some(s => s.payload)));
    let chosen = null;
    const tabs = el("div", "picker-days"), grid = el("div", "picker-times");
    const confirm = el("button", "picker-confirm"), none = el("button", "picker-none", picker.none);

    function render() {
      tabs.innerHTML = "";
      grid.innerHTML = "";
      picker.days.forEach((d, i) => {
        const tab = el("button", "picker-day" + (i === dayIdx ? " active" : ""));
        tab.append(el("strong", "", d.name), el("span", "", d.date));
        if (!d.slots.some(s => s.payload)) tab.classList.add("full");
        tab.addEventListener("click", () => { dayIdx = i; render(); });
        tabs.appendChild(tab);
      });
      const day = picker.days[dayIdx];
      if (!day.slots.some(s => s.payload)) grid.appendChild(el("div", "picker-empty", picker.empty));
      day.slots.forEach(s => {
        const b = el("button", "picker-time" + (chosen === s ? " selected" : ""), s.time);
        if (s.payload) b.addEventListener("click", () => { chosen = s; render(); });
        else b.disabled = true;
        grid.appendChild(b);
      });
      confirm.disabled = !chosen;
      confirm.textContent = chosen ? `${picker.confirm}: ${chosen.label}` : picker.confirm;
    }

    confirm.addEventListener("click", () => chosen && Chat.onSlotPick(chosen.label, chosen.payload));
    none.addEventListener("click", () => Chat.onSlotPick(picker.none, picker.none_payload));
    card.append(el("div", "picker-title", "📅 " + picker.title), tabs, grid, confirm, none);
    render();
  }

  function addSlotPicker(picker) {
    clearSlotPickers();  // only the latest calendar is live
    if (!picker) return;
    const card = el("div", "slot-picker");
    fillSlotPicker(card, picker);
    messagesEl.insertBefore(card, typingEl);
    scrollDown();
  }

  function clearSlotPickers() {
    messagesEl.querySelectorAll(".slot-picker").forEach(node => node.remove());
  }

  async function postJSON(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || data.detail || "Request failed");
    return data;
  }

  // Sends one candidate turn. Returns the API response (replies + candidate state).
  function postMessage(text, payload, channel) {
    return postJSON(`/api/chat/${window.CANDIDATE_ID}/messages`,
      { text, payload: payload || null, channel: channel || "chat" });
  }

  async function send(text, payload) {
    clearSlotPickers();  // any new message makes an open calendar stale
    addBubble("candidate", text, timeNow());
    setBusy(true);
    try {
      const body = await postMessage(text, payload);
      body.replies.forEach(r => {
        addBubble("agent", r.content, timeNow());
        addSlotPicker(r.slot_picker);
      });
      renderPanel(body.candidate);
    } catch (err) {
      addBubble("error", "⚠️ " + (err.message || "Connection problem. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    send(text);
  });

  const Chat = window.Chat = {
    state: null,
    timeNow, addBubble, addNote, addSlotPicker, clearSlotPickers, setBusy, renderPanel, postJSON, postMessage,
    onSlotPick: send,  // voice.js swaps this during a call
    sendTyped: send,
  };

  // Calendar rendered by the server (page reloaded while slots were on offer)
  messagesEl.querySelectorAll(".slot-picker[data-picker]").forEach(card => {
    fillSlotPicker(card, JSON.parse(card.dataset.picker));
  });
  renderPanel(window.INITIAL_STATE);
  scrollDown();
})();
