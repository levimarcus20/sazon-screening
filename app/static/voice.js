// Voice mode: a hands-free "call" with Sofía, inside the same conversation.
//
// Speech-to-text and text-to-speech run in the browser (Web Speech API). Each
// recognized utterance is sent to the same /messages endpoint as typed chat, with
// channel "voice", so the screening logic, validation and storage are identical.
// Half-duplex like a walkie-talkie: the mic is off while Sofía speaks (no echo),
// and a short silence after the candidate speaks ends their turn.
(function () {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const synth = window.speechSynthesis;
  const $ = (id) => document.getElementById(id);
  const callBtn = $("call-btn"), callbar = $("callbar"), composer = $("composer"), typing = $("typing");
  const statusEl = $("call-status"), interimEl = $("call-interim"), dot = $("call-dot");
  const langBtn = $("call-lang"), muteBtn = $("call-mute"), hangupBtn = $("call-hangup"), presence = $("presence");

  const END_OF_TURN_MS = 1300;  // silence after the candidate's last words that ends their turn
  const MAX_SILENT_RESTARTS = 6; // ~45 s of silence -> pause the mic instead of listening forever

  const TEXT = {
    es: {
      connecting: "Llamando…", speaking: "Sofía está hablando…", listening: "Te escucho…",
      thinking: "Sofía está pensando…", muted: "Micrófono en pausa · pulsa 🎙️ para hablar",
      started: "Llamada de voz con Sofía", ended: "Llamada finalizada", oncall: "en llamada",
      retry: "Perdona, he tenido un problema. ¿Me lo repites?",
      mic: "No hay acceso al micrófono. Permítelo en el navegador para hablar con Sofía.",
      network: "El reconocimiento de voz no está disponible ahora mismo. Puedes seguir por escrito.",
      unsupported: "Las llamadas de voz necesitan Chrome o Edge. Puedes seguir por escrito.",
    },
    en: {
      connecting: "Calling…", speaking: "Sofía is speaking…", listening: "Listening…",
      thinking: "Sofía is thinking…", muted: "Mic paused · tap 🎙️ to talk",
      started: "Voice call with Sofía", ended: "Call ended", oncall: "on call",
      retry: "Sorry, I had a problem there. Could you say that again?",
      mic: "No microphone access. Allow it in your browser to talk to Sofía.",
      network: "Speech recognition isn't available right now. You can keep chatting by text.",
      unsupported: "Voice calls need Chrome or Edge. You can keep chatting by text.",
    },
  };

  let call = null;  // { lang, muted, phase, rec, endTimer, clock, startedAt, silentRestarts, fatal }
  const L = () => TEXT[call ? call.lang : Chat.state.language] || TEXT.es;

  if (!SR || !synth) {
    callBtn.addEventListener("click", () => Chat.addNote(L().unsupported));
    return;
  }

  // ------------------------------------------------------------ speaking (TTS)

  // Spanish accent follows the candidate's country once we know it.
  const locale = (lang) => lang === "en" ? "en-US" : (Chat.state.data.country === "MX" ? "es-MX" : "es-ES");

  let voices = synth.getVoices();
  synth.onvoiceschanged = () => { voices = synth.getVoices(); };

  // Best available voice for the locale: neural ("Natural" in Edge) > Google > any; female names preferred.
  const FEMALE = /elvira|dalia|helena|laura|sabina|paloma|ximena|lucia|sofia|jenny|aria|zira|monica|paulina|samantha/i;
  function pickVoice(tag) {
    const want = tag.toLowerCase();
    let best = null, bestScore = -1;
    for (const v of voices) {
      const vl = v.lang.toLowerCase().replace("_", "-");
      if (!vl.startsWith(want.slice(0, 2))) continue;
      const score = (vl === want ? 8 : 0) + (/natural|neural/i.test(v.name) ? 4 : 0)
        + (/google/i.test(v.name) ? 2 : 0) + (FEMALE.test(v.name) ? 1 : 0);
      if (score > bestScore) { best = v; bestScore = score; }
    }
    return best;
  }

  // Chat text -> something pleasant to hear: no emojis, no list numbering, line breaks as pauses.
  function speakable(text) {
    return text
      .replace(/^\s*\d+[).]\s*/gm, "")
      .replace(/[\p{Extended_Pictographic}️‍]/gu, "")
      .replace(/([^.!?:;,\s])[ \t]*\n+\s*/g, "$1. ")
      .replace(/\s*\n+\s*/g, " ")
      .trim();
  }

  function speak(text) {
    return new Promise((resolve) => {
      const clean = speakable(text);
      if (!clean || !call) return resolve();
      const tag = locale(call.lang), voice = pickVoice(tag);
      // One utterance per sentence: Chrome cuts long utterances short.
      const parts = clean.match(/[^.!?]+[.!?]+|[^.!?]+$/g) || [clean];
      let done = false;
      const finish = () => { if (!done) { done = true; clearTimeout(guard); resolve(); } };
      const guard = setTimeout(finish, 4000 + clean.length * 90);  // in case onend never fires
      synth.cancel();
      parts.forEach((p, i) => {
        const u = new SpeechSynthesisUtterance(p.trim());
        u.lang = tag;
        if (voice) u.voice = voice;
        u.rate = 1.05;
        if (i === parts.length - 1) u.onend = u.onerror = finish;
        synth.speak(u);
      });
    });
  }

  // ---------------------------------------------------------- listening (STT)

  function listen() {
    if (!call) return;
    if (call.muted) return setPhase("muted");
    const rec = new SR();
    rec.lang = locale(call.lang);
    rec.continuous = true;      // we decide when the turn ends (END_OF_TURN_MS of silence)
    rec.interimResults = true;  // live captions while they talk
    let finalText = "", interim = "";
    call.rec = rec;

    rec.onresult = (e) => {
      interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) finalText += e.results[i][0].transcript + " ";
        else interim += e.results[i][0].transcript;
      }
      interimEl.textContent = (finalText + interim).trim();
      call.silentRestarts = 0;
      clearTimeout(call.endTimer);
      call.endTimer = setTimeout(() => rec.stop(), END_OF_TURN_MS);  // stop() still delivers pending words
    };
    rec.onerror = (e) => {
      if (["not-allowed", "service-not-allowed", "audio-capture"].includes(e.error)) call.fatal = "mic";
      else if (e.error === "network") call.fatal = "network";
      // "no-speech" / "aborted": handled in onend
    };
    rec.onend = () => {
      if (!call || call.rec !== rec) return;  // hung up, or replaced on purpose
      clearTimeout(call.endTimer);
      call.rec = null;
      if (call.fatal) {
        const msg = L()[call.fatal];
        hangUp();
        return Chat.addBubble("error", "⚠️ " + msg);
      }
      const text = (finalText + interim).trim();
      if (text) return takeTurn(text);
      if (++call.silentRestarts >= MAX_SILENT_RESTARTS) { setMuted(true); return; }
      listen();  // silence: keep listening
    };

    try {
      rec.start();
      setPhase("listening");
    } catch (err) {
      call.rec = null;
      hangUp();
      Chat.addBubble("error", "⚠️ " + L().mic);
    }
  }

  function stopListening() {
    if (!call || !call.rec) return;
    const rec = call.rec;
    call.rec = null;  // onend ignores a recognizer that is no longer current
    clearTimeout(call.endTimer);
    rec.abort();
    interimEl.textContent = "";
  }

  // ------------------------------------------------------------- call flow

  async function takeTurn(text, payload) {
    Chat.clearQuickReplies();
    Chat.addBubble("candidate", text, Chat.timeNow(), true);
    interimEl.textContent = "";
    setPhase("thinking");
    let body;
    try {
      body = await Chat.postMessage(text, payload, "voice");
    } catch (err) {
      if (!call) return;
      Chat.addBubble("error", "⚠️ " + (err.message || "Connection problem."));
      setPhase("speaking");
      await speak(L().retry);
      return listen();
    }
    await handleReplies(body);
  }

  async function handleReplies(body) {
    Chat.renderPanel(body.candidate);
    if (call) {
      call.lang = body.candidate.language;  // follow the language the screening detected
      langBtn.textContent = call.lang.toUpperCase();
    }
    for (const r of body.replies) {
      Chat.addBubble("agent", r.content, Chat.timeNow(), !!call);
      Chat.addQuickReplies(r.quick_replies);
      if (call) {
        setPhase("speaking");
        await speak(r.content);
      }
    }
    if (!call) return;
    if (body.candidate.closed) return hangUp();  // Sofía said goodbye
    listen();
  }

  async function startCall() {
    if (call) return;
    call = { lang: Chat.state.language, muted: false, phase: "", rec: null, endTimer: null,
             startedAt: Date.now(), silentRestarts: 0, fatal: null };
    synth.cancel();
    synth.speak(new SpeechSynthesisUtterance(""));  // unlock audio inside the click gesture
    composer.hidden = true;
    callbar.hidden = false;
    callBtn.hidden = true;
    langBtn.textContent = call.lang.toUpperCase();
    muteBtn.classList.remove("on");
    Chat.addNote("📞 " + L().started);
    Chat.onQuickReply = (label, payload) => { stopListening(); synth.cancel(); takeTurn(label, payload); };
    call.clock = setInterval(updatePresence, 1000);
    updatePresence();
    setPhase("connecting");
    try {
      const body = await Chat.postJSON(`/api/chat/${window.CANDIDATE_ID}/call`);
      Chat.clearQuickReplies();
      await handleReplies(body);
    } catch (err) {
      hangUp();
      Chat.addBubble("error", "⚠️ " + (err.message || "Connection problem."));
    }
  }

  function hangUp() {
    if (!call) return;
    const ended = call;
    stopListening();
    call = null;
    clearInterval(ended.clock);
    synth.cancel();
    typing.classList.remove("show");
    callbar.hidden = true;
    composer.hidden = false;
    callBtn.hidden = !!Chat.state.closed;
    presence.textContent = "online";
    Chat.onQuickReply = Chat.sendTyped;
    Chat.addNote(`📞 ${TEXT[ended.lang].ended} · ${mmss(Date.now() - ended.startedAt)}`);
  }

  function setMuted(muted) {
    if (!call) return;
    call.muted = muted;
    muteBtn.classList.toggle("on", muted);
    if (muted && call.phase === "listening") { stopListening(); setPhase("muted"); }
    if (!muted && call.phase === "muted") { call.silentRestarts = 0; listen(); }
  }

  // ------------------------------------------------------------------- UI

  function setPhase(phase) {
    if (!call) return;
    call.phase = phase;
    statusEl.textContent = L()[phase];
    dot.className = "call-dot " + phase;
    typing.classList.toggle("show", phase === "thinking" || phase === "connecting");
    if (phase !== "listening") interimEl.textContent = "";
  }

  const mmss = (ms) => {
    const s = Math.floor(ms / 1000);
    return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  };
  function updatePresence() {
    if (call) presence.textContent = `${L().oncall} · ${mmss(Date.now() - call.startedAt)}`;
  }

  callBtn.addEventListener("click", startCall);
  hangupBtn.addEventListener("click", hangUp);
  muteBtn.addEventListener("click", () => call && setMuted(!call.muted));
  langBtn.addEventListener("click", () => {
    // Manual override in case the recognizer is listening for the wrong language.
    if (!call) return;
    call.lang = call.lang === "es" ? "en" : "es";
    langBtn.textContent = call.lang.toUpperCase();
    if (call.phase === "listening") { stopListening(); listen(); }
    else if (call.phase === "muted") setPhase("muted");
  });
  window.addEventListener("beforeunload", () => synth.cancel());
})();
