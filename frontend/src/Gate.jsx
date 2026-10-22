import { useEffect, useState } from 'react';
import { api, store, Icon } from './api.jsx';

export const JURIS = [['US-CA', 'California'], ['US-NY', 'New York'], ['GB', 'United Kingdom'], ['DE', 'Germany'], ['FR', 'France'], ['BR', 'Brazil'], ['AU', 'Australia']];

export default function Gate({ onUser, onCancel }) {
  const params = new URLSearchParams(window.location.search);
  const [age, setAge] = useState(null);
  const [touched, setTouched] = useState(false);
  const [name, setName] = useState('');
  const [cities, setCities] = useState([]);
  const [city, setCity] = useState(() => localStorage.getItem('ft_city') || 'San Francisco');
  useEffect(() => { api.cities().then(setCities).catch(() => {}); }, []);
  const [email, setEmail] = useState('');
  const [parentEmail, setParentEmail] = useState('');
  const [challenge, setChallenge] = useState(store.challenge);
  const [state, setState] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const submit = async (e) => {
    e?.preventDefault(); setErr(''); setBusy(true);
    try {
      localStorage.setItem('ft_city', city);
      const r = await api.ageGate({ age, city: age >= 16 ? city : undefined, name: name.trim(), email: age >= 16 && email ? email : undefined, parent_email: age < 18 && parentEmail ? parentEmail : undefined });
      if (r.status === 'PASS') return onUser(r.user);
      if (r.status === 'CHALLENGE') { store.challenge = { ...r.challenge, name, age }; setChallenge(store.challenge); setState('PENDING'); return; }
      setState('PROHIBITED');
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  useEffect(() => {
    if (!challenge?.challengeId) return;
    let stop = false;
    const tick = async () => {
      try { const r = await api.challenge(challenge.challengeId); if (stop) return;
        if (r.state === 'PASS' && r.user) return onUser(r.user);
        setState(r.state === 'FAIL' || r.state === 'EXPIRED' ? r.state : 'PENDING'); } catch {}
    };
    tick(); const id = setInterval(tick, 3000); return () => { stop = true; clearInterval(id); };
  }, [challenge?.challengeId]);

  const reset = () => { store.challenge = null; setChallenge(null); setState(null); };

  if (challenge && state !== 'FAIL' && state !== 'EXPIRED') return <LinkToGrownUp challenge={challenge} onReset={reset} />;
  if (state === 'FAIL' || state === 'EXPIRED') return <div className="gate"><h2>A grown-up said not right now.</h2><button className="primary" onClick={reset}>Try again</button></div>;
  if (state === 'PROHIBITED') return <div className="gate"><h2>FreeTime isn't available for your age yet.</h2><button className="primary" onClick={() => setState(null)}>Back</button></div>;

  return (
    <form className="gate" onSubmit={submit}>
      <svg className="mark" style={{ width: 56, height: 56 }} viewBox="0 0 100 100"><use href="#logo" /></svg>
      <h2>Who's this?</h2>
      <p>k-ID decides your age band for your city's country. FreeTime never stores your age, only the band and a consent status.</p>
      <label>How old are you?</label>
      <span className="agebig">{age === null ? '—' : age >= 35 ? '35+' : age}</span>
      <input type="range" min="3" max="35" value={age ?? 18} onChange={(e) => { setAge(+e.target.value); setTouched(true); }} />
      {age !== null && age >= 16 ? <><label>Which city?</label>
      <select value={city} onChange={(e) => setCity(e.target.value)}>{cities.map((c) => <option key={c.city} value={c.city}>{c.city}</option>)}</select></>
      : age !== null && <p className="fine">Under 16: your grown-up's city and country will be yours too.</p>}
      <label>Name</label>
      <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name" required />
      {age !== null && age < 18 && <><label>A parent's email (optional) · they're alerted only if you ask something dangerous</label><input type="email" value={parentEmail} onChange={(e) => setParentEmail(e.target.value)} placeholder="parent's email" /></>}
      {age !== null && age >= 16 && <><label>Email (lets a child on this device pick your account)</label><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="your email" /></>}
      <button className="primary" type="submit" disabled={age === null || !touched || !name.trim() || busy}>{busy ? 'Checking with k-ID…' : 'Continue'}</button>
      {err && <p className="err">{err}</p>}
      {onCancel && <button type="button" className="link" onClick={onCancel}>Cancel</button>}
    </form>
  );
}

function LinkToGrownUp({ challenge, onReset }) {
  const [accounts, setAccounts] = useState(null);
  const [lan, setLan] = useState(null);
  useEffect(() => { api.health().then((h) => setLan(h.lan_ip)).catch(() => {}); }, []);
  const parentUrl = `http://${lan && !['localhost', '127.0.0.1'].includes(location.hostname) ? location.hostname : (lan || location.hostname)}:${location.port || 80}/parent`;
  const [email, setEmail] = useState('');
  const [parentEmail, setParentEmail] = useState('');
  const [sent, setSent] = useState(challenge.parent_email || '');
  const [err, setErr] = useState('');
  useEffect(() => { api.linkSuggestions().then((r) => setAccounts(r.accounts)).catch(() => setAccounts([])); }, []);
  const ask = async (to) => {
    setErr('');
    try { await api.linkRequest({ challengeId: challenge.challengeId, parent_email: to }); store.challenge = { ...store.challenge, parent_email: to }; setSent(to); }
    catch (e) { setErr(e.message); }
  };
  const code = (challenge.oneTimePassword || '').split('');

  return (
    <div className="gate">
      <svg className="mark" style={{ width: 56, height: 56 }} viewBox="0 0 100 100"><use href="#logo" /></svg>
      <h2>{sent ? `Waiting for ${sent.split('@')[0]}…` : 'Connect to a grown-up'}</h2>
      <p>{sent ? `We asked ${sent}. They choose what ${challenge.name || 'you'} can explore. This page updates by itself.` : `Under 16, a grown-up has to say yes first and choose what you can explore. You'll share their city.`}</p>
      {sent ? <div className="typing" style={{ justifyContent: 'center' }}><i /><i /><i /></div> : (
        <>
          <div className="accounts">
            {accounts === null && <div className="spinner" />}
            {accounts?.length === 0 && <p className="fine">No grown-up has signed in on this device or Wi-Fi yet.</p>}
            {accounts?.map((a) => <button key={a.email} className="account" onClick={() => ask(a.email)}><span className="av parent">{(a.name || a.email)[0].toUpperCase()}</span><span><b>{a.name}</b><small>{a.email} · seen on {a.via}</small></span></button>)}
          </div>
          <div className="row"><input className="field2" type="email" placeholder="their email" value={email} onChange={(e) => setEmail(e.target.value)} /><button className="cta" disabled={!email} onClick={() => ask(email)}>Ask</button></div>
        </>
      )}
      {code.length > 0 && <><p className="fine">Your grown-up opens this on their own phone or laptop (same Wi-Fi) and enters the code</p><div className="field2" style={{ fontFamily: 'var(--display-font)', fontWeight: 600, fontSize: 17, margin: '8px 0' }}>{parentUrl}</div><div className="code">{code.map((c, i) => <span key={i}>{c}</span>)}</div></>}
      {err && <p className="err">{err}</p>}
      {sent && <button className="link" onClick={() => { store.challenge = { ...store.challenge, parent_email: null }; setSent(''); }}>Pick a different grown-up</button>}
      <button className="link" onClick={onReset}>Start over</button>
    </div>
  );
}
