import { useEffect, useState } from 'react';
import { api, store, Icon } from './api.jsx';
import LinkModal from './LinkModal.jsx';

export default function RightPanel({ user }) {
  return (
    <aside className="right">
      {!user && <div className="ph"><h2>Who's this?</h2><p>Pass the k-ID gate in the middle. A parent approves a child from their own device at <b>/parent</b>.</p></div>}
      {user?.tier === 'child' && <ChildPanel user={user} />}
      {user && user.tier !== 'child' && <Context user={user} />}
      {user && <WhatChanged user={user} />}
    </aside>
  );
}

function ChildPanel({ user }) {
  const [ctx, setCtx] = useState(null);
  useEffect(() => { const load = () => api.me(user.id).then(setCtx).catch(() => {}); load(); const id = setInterval(load, 4000); return () => clearInterval(id); }, [user.id]);
  if (!ctx) return <div className="ph"><h2>My grown-up</h2></div>;
  const r = ctx.rules || {};
  return (
    <>
      <div className="ph"><h2>My grown-up</h2><p>{user.parent_email} said yes</p></div>
      <div className="sec">
        <div className="family"><div className="av parent">{(user.parent_email || '?')[0].toUpperCase()}</div><div><b>{user.parent_email.split('@')[0]}</b><small>Approves on their own device</small></div></div>
        <p className="h">I can explore</p>
        <div className="topics">{(ctx.topics || []).filter((t) => r.allowed_topics?.includes(t.id)).map((t) => <div key={t.id} className="topic on"><span className="e">{t.emoji}</span><span>{t.label}<small>{t.blurb}</small></span></div>)}</div>
        <div className="tags">{(r.allowed_categories || []).map((k) => <span key={k} className="tag">{k}</span>)}</div>
        <div className="rule"><span>Free time left today</span><b>{ctx.budget.remaining} min</b></div>
        {r.require_approval && <div className="rule"><span>Ideas need a yes first</span><b>on</b></div>}
      </div>
    </>
  );
}

export function Family({ email, user, parentName }) {
  const [d, setD] = useState(null);
  const [reqs, setReqs] = useState([]);
  const [modal, setModal] = useState(false);
  const [draft, setDraft] = useState({ topics: ['education', 'entertainment', 'hobby'], cats: null, budget: 90, voice: true });
  const [err, setErr] = useState('');
  const load = () => Promise.all([api.parent(email), api.mockChallenges(email).catch(() => [])]).then(([p, c]) => { setD(p); setReqs(c); setDraft((x) => ({ ...x, cats: x.cats ?? p.settings.allowed_categories })); }).catch((e) => setErr(e.message));
  useEffect(() => { load(); const id = setInterval(load, 3000); return () => clearInterval(id); }, [email]);
  useEffect(() => { const n = reqs.length + (d?.pending?.length || 0) + (d?.unread || 0); document.title = n ? `(${n}) FreeTime · Parent` : 'FreeTime · Parent'; return () => { document.title = 'FreeTime'; }; }, [reqs.length, d?.pending?.length, d?.unread]);
  const save = (patch) => api.parentSettings(email, patch).then(load);
  const toggle = (xs, v) => xs.includes(v) ? xs.filter((x) => x !== v) : [...xs, v];
  const consent = (c, ok) => api.mockApprove({ challengeId: c.challengeId, decision: ok ? 'PASS' : 'FAIL', voice: draft.voice, allowed_topics: draft.topics, allowed_categories: draft.cats, daily_budget_min: draft.budget }).then(load).catch((e) => setErr(e.message));
  const decide = (s, ok) => api.approve({ parent_email: email, suggestion_id: s.id, decision: ok ? 'approved' : 'rejected' }).then(load);
  const s = d?.settings, child = d?.child;
  const childVoice = child?.permissions?.find((p) => p.name === 'ai-voice-mode')?.enabled;

  return (
    <>
      <div className="ph"><h2>{parentName ? `${parentName}'s family` : 'Family'}</h2><p>{email}{d?.unread ? ` · ${d.unread} new notification${d.unread > 1 ? 's' : ''}` : ''}</p></div>
      <div className="sec">
        {reqs.length > 0 && <div className="waitbox live">🔔 {reqs.length === 1 ? `${reqs[0].name || 'A child'} is waiting for your approval` : `${reqs.length} children are waiting for your approval`}</div>}
        {!reqs.length && !d?.children?.length && <div className="waitbox"><div className="typing" style={{ padding: 0, justifyContent: 'center' }}><i /><i /><i /></div>Waiting for a child to connect. On their screen they choose <b>I want ideas</b>, enter their age, and pick <b>{email}</b> or enter the code you'll see here.</div>}
        {(d?.children || []).map((k) => <div className="family" key={k.id}><div className="av child">{k.name[0]}</div><div><b>{k.name} · {k.age}</b><small>Consent granted · {k.budget.remaining} min left today</small>{k.chosen?.length > 0 && <small>Chose: {k.chosen.map((c) => `${c.title} ${c.start}`).join(' · ')}</small>}</div></div>)}
        {!d?.children?.length && <div className="family"><div className="av parent">{(email || '?')[0].toUpperCase()}</div><div><b>No child linked yet</b><small>Waiting for a request</small></div></div>}
        <button className="add" style={{ width: '100%', padding: 10, marginBottom: 12 }} onClick={() => setModal(true)}>Link a child with their code</button>
        {err && <p className="err">{err}</p>}
        <p className="h">Requests</p>
      </div>
      <div className="plist">
        {reqs.map((c) => (
          <div className="req" key={c.challengeId}>
            <div className="hd"><div className="av child" style={{ width: 38, height: 38, fontSize: 15 }}>{(c.name || '?')[0]}</div><div><h4>{c.name || 'A child'} wants to connect</h4><p>{c.real ? 'k-ID emailed you a Family Connect link to verify you.' : 'Choose what they can explore, then approve.'}</p></div></div>
            <div className="topics">{d?.topics.map((t) => <label key={t.id} className={`topic ${draft.topics.includes(t.id) ? 'on' : ''}`} onClick={() => setDraft({ ...draft, topics: toggle(draft.topics, t.id) })}><span className="e">{t.emoji}</span><span>{t.label}<small>{t.blurb}</small></span></label>)}</div>
            <div className="tags">{d?.categories.map((k) => <span key={k} className="tag" style={{ cursor: 'pointer', opacity: draft.cats?.includes(k) ? 1 : .4 }} onClick={() => setDraft({ ...draft, cats: toggle(draft.cats || [], k) })}>{k}</span>)}</div>
            <div className="rule"><span>Free time per day</span><input type="range" min="30" max="240" step="15" value={draft.budget} onChange={(e) => setDraft({ ...draft, budget: +e.target.value })} /><b>{draft.budget}m</b></div>
            <div className="rule"><span>Voice <small>k-ID ai-voice-mode</small></span><button className={`toggle ${draft.voice ? 'on' : ''}`} onClick={() => setDraft({ ...draft, voice: !draft.voice })} /></div>
            <div className="row" style={{ marginTop: 10 }}><button className="no" onClick={() => consent(c, false)}>Decline</button><button className="ok" onClick={() => consent(c, true)}>Approve</button></div>
          </div>
        ))}
        {d?.pending.map((p) => (
          <div className="req" key={p.id}><div className="hd"><div><h4>{p.title}</h4><p>{p.why} · {p.duration_min} min · {p.topic}</p></div></div>
            <div className="row"><button className="no" onClick={() => decide(p, false)}>Not today</button><button className="ok" onClick={() => decide(p, true)}>Approve</button></div></div>
        ))}
        {!reqs.length && !d?.pending?.length && <div className="empty">Nothing to approve</div>}
      </div>
      {d?.notifications?.length > 0 && (
        <div className="sec" style={{ marginTop: 14 }}><p className="h"><Icon n="bell" /> Notifications</p>
          <div className="ctxpanel" style={{ padding: 0 }}>{d.notifications.slice(0, 4).map((n) => <div key={n.id} className={`notif ${n.category}`}><b>{n.category}</b> · {n.child} asked “{n.text}”<small>{n.reason}</small></div>)}</div>
          {d.unread > 0 && <button className="link" onClick={() => api.notificationsRead(email).then(load)}>mark read</button>}
        </div>
      )}
      {s && child && (
        <div className="rules"><p className="h">Rules for {child.name}</p>
          <div className="rule"><span>Free time today</span><b>{s.daily_budget_min - s.used_today_min} / {s.daily_budget_min} min</b></div>
          <div className="rule"><span>Approve every idea first</span><button className={`toggle ${s.require_approval ? 'on' : ''}`} onClick={() => save({ require_approval: !s.require_approval })} /></div>
          {d.topics.map((t) => <div className="rule" key={t.id}><span>{t.emoji} {t.label}</span><button className={`toggle ${s.allowed_topics?.includes(t.id) ? 'on' : ''}`} onClick={() => save({ allowed_topics: toggle(s.allowed_topics || [], t.id) })} /></div>)}
          {d.categories.map((k) => <div className="rule" key={k}><span style={{ textTransform: 'capitalize' }}>{k}</span><button className={`toggle ${s.allowed_categories.includes(k) ? 'on' : ''}`} onClick={() => save({ allowed_categories: toggle(s.allowed_categories, k) })} /></div>)}
          <div className="rule"><span>Only with a grown-up</span><button className={`toggle ${s.adult_required_only ? 'on' : ''}`} onClick={() => save({ adult_required_only: !s.adult_required_only })} /></div>
          <div className="rule"><span>Voice <small>k-ID ai-voice-mode</small></span><button className={`toggle ${childVoice ? 'on' : ''}`} onClick={() => api.mockPermission({ user_id: child.id, name: 'ai-voice-mode', enabled: !childVoice }).then(load)} /></div>
          <div className="rule"><span>Free time per day</span><input type="range" min="30" max="240" step="15" value={s.daily_budget_min} onChange={(e) => save({ daily_budget_min: +e.target.value })} /></div>
        </div>
      )}
      {modal && <LinkModal email={email} onClose={() => { setModal(false); load(); }} />}
    </>
  );
}

function Context({ user }) {
  const [ctx, setCtx] = useState(null);
  const [notes, setNotes] = useState(null);
  const [quiz, setQuiz] = useState(null);
  useEffect(() => {
    const load = (first) => api.me(user.id).then((c) => { setCtx(c); if (first) { setNotes(c.user.notes || ''); setQuiz(c.user.prefs || {}); } }).catch(() => {});
    load(true); const on = () => load(false); window.addEventListener('ft-calendar', on); const id = setInterval(on, 8000);
    return () => { window.removeEventListener('ft-calendar', on); clearInterval(id); };
  }, [user.id]);
  if (!ctx) return <div className="ph"><h2>Your context</h2></div>;
  const memory = user.permissions.find((p) => p.name === 'ai-memory')?.enabled;
  return (
    <>
      <div className="ph"><h2>Your context</h2><p>What FreeTime is using right now</p></div>
      <div className="ctxpanel">
        <p className="h" style={{ marginTop: 6 }}>Today</p>
        {merge(ctx.calendar, ctx.windows).map((e, i) => <div key={i} className={`ev ${e.free ? 'free' : ''}`}><i style={e.added ? { background: 'var(--orange)' } : undefined} /><div>{e.title}{e.added ? ' · added by FreeTime' : ''}<small>{e.start} – {e.end}</small></div></div>)}
        {user.tier === 'adult' && memory && <><p className="h" style={{ marginTop: 10 }}>From your notes</p>
          <div className="note"><Icon n="doc" style={{ marginRight: 6 }} />{ctx.user.about_me}<textarea value={notes} onChange={(e) => setNotes(e.target.value)} onBlur={() => api.contextAdult({ user_id: user.id, notes_text: notes })} /></div></>}
        {user.tier === 'teen' && memory && quiz && <><p className="h" style={{ marginTop: 10 }}>Your picks</p>
          {ctx.quiz.map((q) => <div key={q.id} className="note"><b style={{ color: 'var(--text)' }}>{q.q}</b><div className="tags" style={{ marginTop: 6 }}>{q.options.map((o) => { const on = q.multi ? (quiz[q.id] || []).includes(o) : quiz[q.id] === o; return <span key={o} className="tag" style={{ cursor: 'pointer', background: on ? 'var(--blue)' : undefined, color: on ? '#fff' : undefined }} onClick={() => { const n = { ...quiz, [q.id]: q.multi ? ((quiz[q.id] || []).includes(o) ? quiz[q.id].filter((x) => x !== o) : [...(quiz[q.id] || []), o]) : o }; setQuiz(n); api.onboardTeen({ user_id: user.id, answers: n }); }}>{o}</span>; })}</div></div>)}</>}
        {!memory && <div className="note">Memory is off in k-ID (<code>ai-memory</code>), so nothing is kept between asks.</div>}
      </div>
    </>
  );
}

function merge(cal, windows) {
  const all = [...cal.map((e) => ({ ...e, free: false })), ...windows.map((w) => ({ title: 'Free window', start: w.start, end: w.end, free: true }))];
  return all.sort((a, b) => a.start.localeCompare(b.start));
}

function WhatChanged({ user }) {
  const [a, setA] = useState(null);
  useEffect(() => { api.me(user.id).then((c) => setA(c.adaptation)).catch(() => {}); }, [user.id, user.permissions]);
  if (!a) return null;
  return (
    <div className="changed" style={{ marginTop: 18 }}>
      <p className="h"><Icon n="shield" /> What changed for you</p>
      <ul style={{ paddingLeft: 18, margin: 0 }}>
        <li>{a.age_source}: <b style={{ color: 'var(--text)' }}>{a.age_status}</b> at {a.age} in {a.city || a.jurisdiction} ({a.jurisdiction}, consent age {a.consent_age})</li>
        <li>Gate: {a.gate}</li>
        <li>Approval: {a.approval}</li>
        <li>Filters: {a.filters.join('; ')}</li>
        <li>Tone: {a.tone}</li>
        <li>Memory: {a.memory} · Connectors: {a.connectors}</li>
        <li>k-ID: {a.permissions.map((p) => `${p.enabled ? '✓' : '✗'} ${p.name}`).join(' · ')}</li>
      </ul>
    </div>
  );
}
