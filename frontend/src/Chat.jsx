import { useEffect, useRef, useState } from 'react';
import { api, hasPerm, Icon } from './api.jsx';
import Gate from './Gate.jsx';
import { Link } from 'react-router-dom';

const SUB = { child: 'Three fun things, picked for you.', teen: 'Cheap, close, and before curfew.', adult: 'Three ideas that fit your free window' };
const QUICK = { child: ["I'm bored", "Let's go outside", 'Something quiet'], teen: [], adult: [] };
const MOODS = [['😴 tired', 'tired'], ['😐 meh', 'meh'], ['🙂 good', 'good'], ['🔥 hyped', 'hyped']];
const PLACEHOLDER = { child: 'What do you feel like doing?', teen: "I'm bored, anything cheap?", adult: 'What do you feel like doing?' };
const PIC = { outdoor: ['🌳', '🛝'], sports: ['⚽', '🏃'], learning: ['🔬', '🦈'], creative: ['🎨', '✂️'], culture: ['🎭', '🖼️'], games: ['🎲', '🎮'], social: ['👯', '🎉'], food: ['🍪', '🥐'] };
const PICK = { 'a20': ['🦖', '🖍️'], 'a23': ['🦈', '🐠'], 'a22': ['🦁', '🐧'], 'a19': ['🏰', '🛋️'], 'a21': ['🍪', '🧁'], 'a27': ['📖', '🧸'], 'a29': ['💃', '🎶'], 'a30': ['🧦', '🎭'], 'a25': ['🍂', '🐞'], 'a26': ['⚽', '🥅'], 'a28': ['🏊', '💦'], 'a1': ['🛝', '🌳'], 'a5': ['📚', '🐻'], 'a2': ['🔬', '🧪'], 'a3': ['🐠', '🦋'], 'a4': ['🏖️', '🐚'], 'a24': ['🎨', '🎬'], 'a6': ['🕹️', '🎪'] };
const TILE = { outdoor: ['run', 't-green'], sports: ['run', 't-green'], learning: ['art', 't-violet'], creative: ['art', 't-violet'], culture: ['art', 't-violet'], games: ['film', 't-blue'], social: ['film', 't-blue'], food: ['film', 't-blue'] };
const now = () => new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

export default function Chat({ user, onUser, onExit, theme, setTheme, onCancelAdd }) {
  const [msgs, setMsgs] = useState([]);
  const [text, setText] = useState('');
  const [mood, setMood] = useState(null);
  const [typing, setTyping] = useState(false);
  const [slow, setSlow] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [quiz, setQuiz] = useState(null); // teen: questions until answered
  const [live, setLive] = useState(false); // dictation in progress
  const [entered, setEntered] = useState(false); // past the landing chooser
  const [toast, setToast] = useState('');
  const outer = useRef(null);
  const tier = user?.tier;

  useEffect(() => {
    if (!user) return;
    setQuiz(null);
    setMsgs([{ role: 'bot', text: { child: `Hi ${user.name}! What do you feel like doing?`, teen: `hey ${user.name}. what are you in the mood for?`, adult: `Hi ${user.name}. What do you feel like doing today?` }[user.tier] }]);
    if (user.tier === 'teen' && hasPerm(user, 'ai-memory')) {
      api.me(user.id).then((c) => { if (!c.quiz_done) { setQuiz({ q: c.quiz, a: {} }); setMsgs((ms) => [...ms, { role: 'bot', text: 'first time here. five quick ones so I actually know you:' }, { role: 'quiz' }]); } }).catch(() => {});
    }
  }, [user?.id]);
  useEffect(() => { outer.current && (outer.current.scrollTop = outer.current.scrollHeight); }, [msgs, typing]);

  // Child with "approve every idea" on: watch for the parent's decisions.
  useEffect(() => {
    if (tier !== 'child') return;
    const tick = () => api.pending(user.id).then((r) => {
      const by = Object.fromEntries(r.suggestions.map((s) => [s.id, s]));
      setMsgs((ms) => ms.map((m) => m.cards ? { ...m, cards: m.cards.map((c) => by[c.id] ? { ...c, status: by[c.id].status } : c) } : m));
      r.suggestions.filter((s) => s.status === 'approved' && !spokenRef.current.has(s.id)).forEach((s) => { spokenRef.current.add(s.id); setMsgs((ms) => [...ms, { role: 'bot', text: `A grown-up said yes to “${s.title}”.` }]); speak(`Yes! ${s.title}. ${s.why}`); });
    }).catch(() => {});
    const id = setInterval(tick, 3000); return () => clearInterval(id);
  }, [tier, user?.id]);
  const spokenRef = useRef(new Set());

  const speak = async (t) => {
    if (!hasPerm(user, 'ai-voice-mode')) return;
    setSpeaking(true);
    try { const blob = await api.speak({ user_id: user.id, text: t }); const a = new Audio(URL.createObjectURL(blob)); a.onended = () => setSpeaking(false); await a.play(); }
    catch (e) { setSpeaking(false); if ('speechSynthesis' in window) { const u = new SpeechSynthesisUtterance(t); u.rate = tier === 'child' ? 0.9 : 1; speechSynthesis.speak(u); } setToast('Inworld: ' + e.message); }
  };

  const send = async (q) => {
    const t = (q ?? text).trim(); if (!t) return;
    setText(''); setMsgs((ms) => [...ms, { role: 'user', text: t }]); setTyping(true); setSlow(false);
    const slowTimer = setTimeout(() => setSlow(true), 4000);
    try {
      const r = await api.suggest({ user_id: user.id, text: t, mood });
      const reply = r.flag?.message || (r.searched ? { teen: 'looked it up. three real options:', adult: 'Three options I found online that fit your day.' }[tier] : { child: 'I found three fun things.', teen: "Here's what's actually worth doing right now.", adult: `Three options that fit your ${r.windows?.[0] ? `${r.windows[0].start}–${r.windows[0].end}` : 'free'} window.` }[tier]);
      setMsgs((ms) => [...ms, { role: 'bot', text: reply, flag: r.flag?.category, alerted: r.flag?.alerted }, { role: 'cards', cards: r.suggestions }]);
      if (tier === 'child') speak(`${reply} ${r.suggestions.map((s) => s.title.replace(/[^\p{L}\p{N} .,'!?-]/gu, '')).join('. ')}`);
    } catch (e) { setMsgs((ms) => [...ms, { role: 'bot', text: e.message }]); }
    finally { clearTimeout(slowTimer); setTyping(false); setSlow(false); }
  };

  const addCal = async (c) => {
    try {
      const r = await api.addToCalendar({ user_id: user.id, suggestion_id: c.id });
      if (tier !== 'child') { const blob = new Blob([r.ics], { type: 'text/calendar' }); const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `${c.title.replace(/[^\w]+/g, '-')}.ics`; a.click(); }
      const note = { child: `Yay! “${c.title}” is on your day at ${r.event.start}. Have fun!`, teen: `locked in: ${c.title}, ${r.event.start}–${r.event.end}. calendar file downloading.`, adult: `Added “${c.title}” ${r.event.start}–${r.event.end} to today. The .ics is downloading for your calendar app.` }[tier];
      setMsgs((ms) => [...ms, { role: 'bot', text: note }].map((m) => m.cards ? { ...m, cards: m.cards.map((x) => x.id === c.id ? { ...x, status: 'added' } : x) } : m));
      if (tier === 'child') speak(note);
      window.dispatchEvent(new Event('ft-calendar'));
    } catch (e) { setToast(e.message); }
  };

  const answer = (q, o) => setQuiz((z) => ({ ...z, a: { ...z.a, [q.id]: q.multi ? ((z.a[q.id] || []).includes(o) ? z.a[q.id].filter((x) => x !== o) : [...(z.a[q.id] || []), o]) : o } }));
  const finishQuiz = async () => {
    try { await api.onboardTeen({ user_id: user.id, answers: quiz.a }); setQuiz({ ...quiz, done: true }); setMsgs((ms) => [...ms.filter((m) => m.role !== 'quiz'), { role: 'bot', text: 'got it. ask me anything, or hit a mood.' }]); window.dispatchEvent(new Event('ft-calendar')); }
    catch (e) { setToast(e.message); }
  };

  const vote = async (c, v) => {
    try { await api.feedback({ user_id: user.id, suggestion_id: c.id, vote: v }); setMsgs((ms) => ms.map((m) => m.cards ? { ...m, cards: m.cards.map((x) => x.id === c.id ? { ...x, vote: v } : x) } : m)); }
    catch (e) { setToast(e.message); }
  };

  if (!user) {
    return <main className="main"><div className="stream">{entered ? <Gate onUser={onUser} onCancel={() => setEntered(false)} /> : <Landing onEnter={() => setEntered(true)} />}</div></main>;
  }
  const voice = hasPerm(user, 'ai-voice-mode');
  return (
    <main className="main">
      <div className="topbar"><div><h1>Hi {user.name}</h1><p>{SUB[tier]}{speaking ? ' · 🔊 speaking' : ''}</p></div>
        <div className="row"><button className="cta ghost" onClick={onExit} title="Leave this chat. Your name stays in the sessions list.">Exit</button><button className="btn" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}><Icon n={theme === 'dark' ? 'sun' : 'moon'} /></button></div></div>
      <div className="stream" ref={outer}><div className="inner">
        <div className="ts">Today {now()}</div>
        {msgs.map((m, i) => m.role === 'cards'
          ? <div className="cards" key={i}>{m.cards.map((c) => <Card key={c.id} c={c} tier={tier} onVote={vote} onAddCal={addCal} canVote={hasPerm(user, 'ai-memory')} onSpeak={() => speak(`${c.title}. ${c.why}`)} canSpeak={voice} />)}</div>
          : m.role === 'quiz' && quiz ? <div className="quiz" key={i}>{quiz.q.map((q) => <div key={q.id} className="qq"><b>{q.q}</b><div className="quick">{q.options.map((o) => { const on = q.multi ? (quiz.a[q.id] || []).includes(o) : quiz.a[q.id] === o; return <button key={o} className={on ? 'on' : ''} onClick={() => answer(q, o)}>{o}</button>; })}</div></div>)}<button className="cta" disabled={Object.keys(quiz.a).length < quiz.q.length} onClick={finishQuiz}>done</button></div>
          : m.role === 'user' ? <div key={i}><div className="msg user tail sent">{m.text}</div><div className="status">Delivered</div></div>
          : <div key={i} className={`msg bot tail ${m.flag === 'concerning' || m.flag === 'dangerous' ? 'flag' : ''}`}>{m.text}{m.alerted && <div style={{ fontSize: 12, opacity: .7, marginTop: 4 }}>{tier === 'child' ? 'A grown-up has been told.' : 'A parent has been notified.'}</div>}</div>)}
        {typing && <div className="msg bot tail typing"><i /><i /><i />{slow && tier !== 'child' && <span className="searching">checking the web for what's on…</span>}</div>}
      </div></div>
      <div className="composer-wrap"><div className="composer">
        {tier === 'child' && <div className="quick">{QUICK.child.map((q) => <button key={q} onClick={() => send(q)}>{q}</button>)}</div>}
        {tier === 'teen' && <div className="quick">{MOODS.map(([l, m]) => <button key={m} className={mood === m ? 'on' : ''} onClick={() => setMood(mood === m ? null : m)}>{l}</button>)}</div>}
        <div className="row">
          <div className="field"><input value={text} onChange={(e) => setText(e.target.value)} placeholder={PLACEHOLDER[tier]} onKeyDown={(e) => e.key === 'Enter' && send()} />
            {text.trim() && !live ? <button className="mic send" onClick={() => send()}><Icon n="send" /></button> : <Mic user={user} enabled={voice} onText={(t) => { setLive(false); send(t); }} onInterim={(t) => { setLive(true); setText(t); }} onError={(m) => { setLive(false); setText(''); setToast(m); }} />}
          </div>
        </div>
      </div></div>
      {toast && <div className="msg bot" style={{ position: 'fixed', bottom: 16, left: '50%', transform: 'translateX(-50%)', fontSize: 13 }} onClick={() => setToast('')}>{toast}</div>}
    </main>
  );
}

function Card({ c, tier, onVote, onAddCal, canVote, onSpeak, canSpeak }) {
  const [ico, tile] = TILE[c.category] || ['film', 't-blue'];
  if (tier === 'child') {
    const [e1, e2] = PICK[c.activity_id] || PIC[c.category] || ['✨', '🎈'];
    return (
      <div className={`card pic ${c.category} ${c.status === 'pending' ? 'pending' : c.status === 'approved' ? 'approved' : c.status === 'rejected' ? 'rejected' : ''}`}>
        <div className="picture"><span>{e1}</span><span>{e2}</span></div>
        <div className="body">
          <h4>{c.title}</h4>
          <div className="why">{c.why}</div>
          <div className="tags"><span className="tag">⏱ {c.duration_min} min</span><span className="tag">{c.indoor ? '🏠 inside' : '🌤 outside'}</span>{c.needs_adult && <span className="tag">🧑‍🤝‍🧑 with a grown-up</span>}</div>
          <div className="ctarow">{c.status === 'added' ? <button className="cta on" disabled>On my day ✓</button> : <button className="cta" onClick={() => onAddCal(c)}>Yes! 🎉</button>}{canSpeak && <button className="cta ghost" onClick={onSpeak} title="Read it to me"><Icon n="speaker" /></button>}</div>
        </div>
      </div>
    );
  }
  const tags = tier === 'adult' ? [c.when || c.window, `${c.duration_min} min`, c.cost_usd ? `$${c.cost_usd}` : 'Free', c.indoor ? 'Indoor' : 'Outdoor', c.area]
    : tier === 'teen' ? [c.when, c.with === 'friends' ? 'With friends' : 'Solo', c.cost_usd ? `$${c.cost_usd}` : 'Free', c.area]
    : [`About ${c.duration_min} min`, c.indoor ? 'Inside' : 'Outside'];
  return (
    <div className={`card ${c.status === 'pending' ? 'pending' : c.status === 'approved' ? 'approved' : c.status === 'rejected' ? 'rejected' : ''}`}>
      <div className={`tile ${tile}`}><Icon n={ico} /></div>
      <div className="body">
        <h4>{c.title}</h4>
        <div className="why">{c.why}</div>
        <div className="tags">{tags.filter(Boolean).map((t) => <span className="tag" key={t}>{t}</span>)}{c.source_url && <a className="tag src" href={c.source_url} target="_blank" rel="noreferrer">via {new URL(c.source_url).hostname.replace('www.', '')}</a>}</div>
        <div className="ctarow">
          {tier === 'teen' && (c.status === 'added' ? <button className="cta on" disabled><Icon n="check" /> in</button> : <button className="cta" onClick={() => onAddCal(c)}>I'm in</button>)}
          {tier === 'teen' && canVote && <><button className={`cta ${c.vote === 'up' ? 'on' : 'ghost'}`} onClick={() => onVote(c, 'up')}>👍</button><button className={`cta ${c.vote === 'down' ? 'on' : 'ghost'}`} onClick={() => onVote(c, 'down')}>👎</button></>}
          {tier === 'adult' && (c.status === 'added' ? <button className="cta on" disabled><Icon n="check" /> Added</button> : <button className="cta" onClick={() => onAddCal(c)}>Add to calendar</button>)}
          {canSpeak && <button className="cta ghost" onClick={onSpeak} title="Read aloud with Inworld"><Icon n="speaker" /></button>}
        </div>
      </div>
    </div>
  );
}

function Mic({ user, enabled, onText, onError, onInterim }) {
  const [rec, setRec] = useState(null);
  const [secs, setSecs] = useState(0);
  const [phase, setPhase] = useState('idle'); // idle | listening | transcribing
  const liveRef = useRef('');
  const start = async () => {
    if (!enabled) { onError('Voice is off in k-ID permissions'); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/mp4';
      const r = new MediaRecorder(stream, { mimeType: mime }); const chunks = [];
      // Live words while you speak (browser speech API), Modulate gives the final transcript.
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition; let sr = null; liveRef.current = '';
      if (SR) { sr = new SR(); sr.continuous = true; sr.interimResults = true; sr.lang = 'en-US';
        sr.onresult = (e) => { let t = ''; for (const res of e.results) t += res[0].transcript + ' '; liveRef.current = t.trim(); onInterim(liveRef.current); };
        try { sr.start(); } catch {} }
      r.ondataavailable = (e) => chunks.push(e.data);
      r.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop()); try { sr?.stop(); } catch {}
        setPhase('transcribing'); onInterim(liveRef.current ? liveRef.current + ' …' : 'transcribing…');
        const blob = new Blob(chunks, { type: mime });
        const t0 = Date.now();
        try { const { text } = await api.transcribe(user.id, blob); const final = text || liveRef.current; if (final) onText(final); else onError("Modulate didn't hear anything"); }
        catch (e) { if (liveRef.current) onText(liveRef.current); else onError('Modulate: ' + e.message); }
        finally { setPhase('idle'); console.log('modulate ms', Date.now() - t0); }
      };
      r.start(250); setRec(r); setPhase('listening'); setSecs(0);
    } catch (e) { onError('Mic: ' + e.message); }
  };
  useEffect(() => { if (phase !== 'listening') return; const id = setInterval(() => setSecs((x) => x + 1), 1000); return () => clearInterval(id); }, [phase]);
  const stop = () => { rec?.stop(); setRec(null); };
  return (
    <>
      {phase === 'listening' && <span className="livetag"><i /> listening {String(Math.floor(secs / 60))}:{String(secs % 60).padStart(2, '0')} · tap to stop</span>}
      {phase === 'transcribing' && <span className="livetag">Modulate…</span>}
      <button className={`mic ${phase === 'listening' ? 'listening' : ''} ${enabled ? '' : 'off'}`} onClick={phase === 'listening' ? stop : phase === 'idle' ? start : undefined} title={enabled ? 'Speak (Modulate)' : 'Voice off in k-ID'}><Icon n={phase === 'listening' ? 'wave' : 'mic'} /></button>
    </>
  );
}

function Landing({ onEnter }) {
  return (
    <div className="gate landing">
      <svg className="mark" style={{ width: 64, height: 64 }} viewBox="0 0 100 100"><use href="#logo" /></svg>
      <h2>FreeTime</h2>
      <p>What to do with your free time, shaped by your age and your city. Who's here?</p>
      <Link className="primary bigbtn" to="/parent">👪 I'm a parent<small>Create the family account, approve a child, set what they can explore</small></Link>
      <button className="primary bigbtn alt" onClick={onEnter}>✨ I want ideas<small>Child, teen or adult. Under 16 connects to a parent first</small></button>
      <p className="fine">Step 1: a parent creates the account here or on their phone. Step 2: the child opens FreeTime on their own screen and picks that parent. Step 3: the parent approves and chooses the activities.</p>
    </div>
  );
}
