import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, hasPerm, Icon } from './api.jsx';
import { JURIS } from './Gate.jsx';

const BAND = { child: 'Child · parent consent granted', teen: 'Teen · no connectors', adult: 'Adult · verified by k-ID' };

export default function Sidebar({ user, users, current, onSwitch, onAdd, onForget, theme, setTheme, health }) {
  const [ctx, setCtx] = useState(null);
  useEffect(() => {
    if (!user?.id) { setCtx(null); return; }
    const load = () => api.me(user.id).then(setCtx).catch(() => {});
    load(); const id = setInterval(load, 5000); return () => clearInterval(id);
  }, [user?.id]);

  const w = ctx?.weather, win = ctx?.windows?.[0];
  const freeMin = ctx?.windows?.reduce((a, x) => a + x.minutes, 0) || 0;
  const ring = user?.tier === 'child' && ctx?.budget ? ctx.budget.remaining / ctx.budget.total : Math.min(1, freeMin / 240);
  const place = user?.city ? `${user.city} · ${user.jurisdiction}` : user?.jurisdiction;
  const voice = hasPerm(user, 'ai-voice-mode'), memory = hasPerm(user, 'ai-memory');

  if (user?.tier === 'child') {
    return (
      <aside className="side kid">
        <div className="brand"><svg className="mark" viewBox="0 0 100 100"><use href="#logo" /></svg><div>FreeTime<small>What shall we do?</small></div></div>
        <div className="user"><div className="av child">{user.name[0]}</div><div><b>{user.name} · {user.age}</b><small>{user.parent_email ? `${user.parent_email.split('@')[0]} said yes` : ''}</small></div></div>
        {ctx?.budget && <div className="ring-card"><div className="ring" style={{ '--p': `${Math.round(ring * 100)}%` }} /><div><b>{ctx.budget.remaining} min</b><small>of play time left today</small></div></div>}
        {w && <span className="chip"><Icon n={w.rain_prob > 60 ? 'rain' : w.summary.startsWith('Clear') ? 'sun' : 'cloud'} />{w.rain_prob > 60 ? 'Rainy' : w.summary.startsWith('Clear') ? 'Sunny' : 'Cloudy'} today</span>}
        <div className="sidefoot"><a href="/" onClick={(e) => { e.preventDefault(); onAdd(); }}>Bye for now 👋</a></div>
      </aside>
    );
  }
  return (
    <aside className="side">
      <div className="brand"><svg className="mark" viewBox="0 0 100 100"><use href="#logo" /></svg><div>FreeTime<small>What to do with your free time</small></div></div>

      <div>
        <p className="h">Sessions on this device</p>
        <div className="seg">
          {users.map((u) => <button key={u.id} className={current === u.id ? 'active' : ''} onClick={() => onSwitch(u.id)} onDoubleClick={() => onForget(u.id)} title="click to resume, double-click to forget">{u.name} · {u.age}</button>)}
          <button onClick={onAdd} title="New session through the k-ID gate">+ New</button>
        </div>
      </div>

      {user && (
        <div className="user"><div className={`av ${user.tier}`}>{user.name[0]}</div><div><b>{user.name} · {user.age}</b><small>{BAND[user.tier]} · {user.age_status}</small>
          {user.tier === 'child' && user.parent_email && <span className="linked"><Icon n="shield" />Linked to {user.parent_email.split('@')[0]}</span>}</div></div>
      )}

      {user && (
        <div className="ring-card"><div className="ring" style={{ '--p': `${Math.round(ring * 100)}%` }} /><div>
          <b>{user.tier === 'child' && ctx?.budget ? `${ctx.budget.remaining} min left` : `${Math.floor(freeMin / 60)}h ${freeMin % 60}m free`}</b>
          <small>{user.tier === 'child' ? 'Today, set by your parent' : 'Today, from your calendar'}</small></div></div>
      )}

      {user && (
        <div><p className="h">Right now</p><div className="ctx">
          {w && <span className="chip"><Icon n={w.rain_prob > 60 ? 'rain' : w.summary.startsWith('Clear') ? 'sun' : 'cloud'} />{w.summary}, {Math.round(w.temp_c)}°</span>}
          {win && <span className="chip"><Icon n="cal" />Free {win.start}–{win.end}</span>}
          <span className="chip"><Icon n="pin" />{place}</span>
          {user.tier === 'teen' && <span className="chip"><Icon n="moon" />Home by 9</span>}
        </div></div>
      )}

      <div>
        <p className="h">Settings</p>
        <div className="setting"><div className="l"><span className="ico" style={{ background: '#5856d6' }}><Icon n="moon" /></span><div>Dark mode</div></div><button className={`toggle ${theme === 'dark' ? 'on' : ''}`} onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} /></div>
        <div className="setting"><div className="l"><span className="ico" style={{ background: '#ff375f' }}><Icon n="wave" /></span><div>Modulate<small>Voice input · k-ID ai-voice-mode</small></div></div><button className={`toggle locked ${voice ? 'on' : ''}`} title="Managed through k-ID, not here" /></div>
        <div className="setting"><div className="l"><span className="ico" style={{ background: '#ff9f0a' }}><Icon n="speaker" /></span><div>Inworld<small>Read aloud · k-ID ai-voice-mode</small></div></div><button className={`toggle locked ${voice ? 'on' : ''}`} title="Managed through k-ID, not here" /></div>
        <div className="setting"><div className="l"><span className="ico" style={{ background: '#64d2ff' }}><Icon n="doc" /></span><div>Memory<small>Likes, notes · k-ID ai-memory</small></div></div><button className={`toggle locked ${memory ? 'on' : ''}`} title="Managed through k-ID, not here" /></div>
        <div className="setting"><div className="l"><span className="ico" style={{ background: '#30d158' }}><Icon n="key" /></span><div>k-ID<small>{health ? (health.kid_mock ? 'Test rules, no key yet' : 'Live test API') : '…'}</small></div></div><button className={`toggle locked ${health?.ok ? 'on' : ''}`} /></div>
      </div>

      <div className="sidefoot"><a href="/" onClick={async (e) => { e.preventDefault(); if (confirm('Reset the whole demo? Parents, children and notifications on the server are cleared too.')) { await api.reset().catch(() => {}); localStorage.clear(); location.href = '/'; } }}>Reset demo</a><Link to="/parent"><Icon n="users" /> Parent login</Link><Link to="/compare"><Icon n="globe" /> Same person, other countries</Link><Link to="/privacy">Privacy</Link><Link to="/terms">Terms</Link></div>
    </aside>
  );
}
