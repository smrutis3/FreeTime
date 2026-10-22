import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Family } from './RightPanel.jsx';
import { api } from './api.jsx';

export default function ParentPage({ onUser }) {
  const nav = useNavigate();
  const [age, setAge] = useState(() => +localStorage.getItem('ft_parent_age') || 35);
  const [err, setErr] = useState('');
  const [email, setEmail] = useState(() => localStorage.getItem('ft_parent_login') || '');
  const [draft, setDraft] = useState(email);
  const [name, setName] = useState('');
  const [city, setCity] = useState(() => localStorage.getItem('ft_parent_city') || 'San Francisco');
  const [cities, setCities] = useState([]);
  useEffect(() => { api.cities().then(setCities).catch(() => {}); }, []);
  const [theme] = useState(() => localStorage.getItem('ft_theme') || 'dark');
  useEffect(() => { document.documentElement.dataset.theme = theme; document.documentElement.dataset.tier = 'adult'; }, [theme]);
  const login = async (e) => { e.preventDefault(); if (!draft.includes('@')) return; try { await api.parentLogin({ email: draft, name: name || undefined, city, age }); } catch {} localStorage.setItem('ft_parent_age', String(age)); localStorage.setItem('ft_parent_login', draft); localStorage.setItem('ft_parent_city', city); localStorage.setItem('ft_parent_name', name); setEmail(draft); };
  const logout = () => { localStorage.removeItem('ft_parent_login'); setEmail(''); };
  if (!email) {
    return (
      <div className="page"><form className="gate" onSubmit={login}>
        <svg className="mark" style={{ width: 56, height: 56 }} viewBox="0 0 100 100"><use href="#logo" /></svg>
        <h2>Create your parent account</h2>
        <p>Your child will pick this account from their screen, or you'll enter their code here. Requests, approvals, rules and safety notifications live on this page.</p>
        <label>Email</label><input type="email" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="your email" autoFocus />
        <label>Your name</label><input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="shown to your child" />
        <label>Your age · {age}</label><input type="range" min="18" max="80" value={age} onChange={(e) => setAge(+e.target.value)} />
        <label>Your city · your child shares it</label><select value={city} onChange={(e) => setCity(e.target.value)}>{cities.map((c) => <option key={c.city} value={c.city}>{c.city}</option>)}</select>
        <button className="primary" type="submit" disabled={!draft.includes('@') || !name.trim()}>Create account</button>
        <p className="fine">With a live k-ID key, you'd verify yourself as an adult in Family Connect first.</p>
        <Link className="link" to="/">← back to FreeTime</Link>
      </form></div>
    );
  }
  return (
    <div className="parentpage">
      <div className="topbar"><div><h1>FreeTime · Parent</h1><p>{email} · {localStorage.getItem('ft_parent_city') || ''}</p></div><div className="row"><button className="cta" onClick={async () => { setErr(''); try { await api.parentLogin({ email, city: localStorage.getItem('ft_parent_city') || undefined, age, name: localStorage.getItem('ft_parent_name') || undefined }); const r = await api.parentChat({ email }); onUser(r.user); nav('/'); } catch (e) { setErr(e.message); } }}>My chat</button><button className="cta ghost" onClick={logout}>Sign out</button></div></div>
      {err && <p className="err" style={{ textAlign: 'center' }}>{err}</p>}
      <div className="parentcols"><Family email={email} parentName={localStorage.getItem('ft_parent_name') || ''} /></div>
    </div>
  );
}
