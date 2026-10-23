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

  // Tap-to-choose buttons under a message (interview slots). Tapping sends the
  // label as the visible message plus a payload the server handles without the LLM.
  function fillQuickReplies(container, replies) {
    replies.forEach(r => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = r.label;
      btn.addEventListener("click", () => Chat.onQuickReply(r.label, r.payload));
      container.appendChild(btn);
    });
  }

  function addQuickReplies(replies) {
    if (!replies || !replies.length) return;
    const container = document.createElement("div");
    container.className = "quick-replies";
    fillQuickReplies(container, replies);
    messagesEl.insertBefore(container, typingEl);
    scrollDown();
  }

  function clearQuickReplies() {
    messagesEl.querySelectorAll(".quick-replies").forEach(el => el.remove());
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
    clearQuickReplies();  // any new message makes older buttons stale
    addBubble("candidate", text, timeNow());
    setBusy(true);
    try {
      const body = await postMessage(text, payload);
      body.replies.forEach(r => {
        addBubble("agent", r.content, timeNow());
        addQuickReplies(r.quick_replies);
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
    timeNow, addBubble, addNote, addQuickReplies, clearQuickReplies, setBusy, renderPanel, postJSON, postMessage,
    onQuickReply: send,  // voice.js swaps this during a call
    sendTyped: send,
  };

  // Buttons rendered by the server (page reloaded while slots were on offer)
  messagesEl.querySelectorAll(".quick-replies[data-replies]").forEach(el => {
    fillQuickReplies(el, JSON.parse(el.dataset.replies));
  });
  renderPanel(window.INITIAL_STATE);
  scrollDown();
})();
