import { useEffect, useState } from 'react';
import { Link, Route, Routes } from 'react-router-dom';
import { api, store } from './api.jsx';
import Sidebar from './Sidebar.jsx';
import Chat from './Chat.jsx';
import RightPanel from './RightPanel.jsx';
import Compare from './Compare.jsx';
import { Privacy, Terms } from './Legal.jsx';
import ParentPage from './ParentPage.jsx';

// Demo mode: every page open starts clean. Judges create the users themselves at the gate.
store.users = []; store.currentId = null; store.challenge = null;

export default function App() {
  const [user, setUserState] = useState(null);
  const [users, setUsers] = useState([]);
  const [adding, setAdding] = useState(false);
  const [theme, setTheme] = useState(store.theme);
  const [health, setHealth] = useState(null);

  useEffect(() => { document.documentElement.dataset.theme = theme; store.theme = theme; }, [theme]);
  useEffect(() => { document.documentElement.dataset.tier = user?.tier || 'none'; }, [user?.tier]);
  useEffect(() => { api.health().then(setHealth).catch(() => setHealth({ ok: false })); }, []);

  // Re-read permissions from k-ID when the tab regains focus (a parent may have changed them).
  useEffect(() => {
    if (!user?.id) return;
    const refresh = () => api.claim({ user_id: user.id }).then((r) => update(r.user)).catch(() => {});
    window.addEventListener('focus', refresh);
    const id = setInterval(refresh, 5000);
    return () => { window.removeEventListener('focus', refresh); clearInterval(id); };
  }, [user?.id]);

  // silent permission refresh: never changes which screen is showing
  const update = (u) => { if (store.currentId === u.id) { store.upsert(u); setUserState(u); setUsers(store.users); } };
  const exit = () => { store.currentId = null; setUserState(null); setAdding(true); };
  const select = (u) => { store.upsert(u); store.challenge = null; setUserState(u); setUsers(store.users); setAdding(false); };
  const switchTo = (id) => { store.currentId = id; setUserState(store.user); setAdding(false); };
  const forget = (id) => { store.remove(id); setUserState(store.user); setUsers(store.users); };

  const childMode = !adding && user?.tier === 'child';
  const main = (
    <div className={`app ${childMode ? 'childmode' : ''}`}>
      <Sidebar user={adding ? null : user} users={users} current={adding ? null : user?.id} onSwitch={switchTo} onAdd={exit} onForget={forget} theme={theme} setTheme={setTheme} health={health} />
      <Chat user={adding ? null : user} onUser={select} onExit={exit} theme={theme} setTheme={setTheme} onCancelAdd={user && adding ? () => setAdding(false) : null} />
      {!childMode && <RightPanel user={adding ? null : user} />}
    </div>
  );
  return (
    <Routes>
      <Route path="/" element={main} />
      <Route path="/parent" element={<ParentPage onUser={select} />} />
      <Route path="/compare" element={<div className="page"><p><Link to="/">← back</Link></p><Compare /></div>} />
      <Route path="/privacy" element={<div className="page"><Privacy /></div>} />
      <Route path="/terms" element={<div className="page"><Terms /></div>} />
    </Routes>
  );
}
