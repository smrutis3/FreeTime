const BASE = '/api';

export const deviceId = (() => { try { let d = localStorage.getItem('ft_device'); if (!d) { d = Math.random().toString(36).slice(2, 10); localStorage.setItem('ft_device', d); } return d; } catch { return 'nodev'; } })();

async function req(method, path, body, opts = {}) {
  const r = await fetch(BASE + path, {
    method,
    headers: { 'X-Device': deviceId, ...(body && !(body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? (body instanceof FormData ? body : JSON.stringify(body)) : undefined,
    ...opts,
  });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    const err = new Error(msg); err.status = r.status; throw err;
  }
  const ct = r.headers.get('content-type') || '';
  return ct.includes('application/json') ? r.json() : r.blob();
}

export const api = {
  health: () => req('GET', '/health'),
  cities: () => req('GET', '/cities'),
  parentLogin: (b) => req('POST', '/parent/login', b),
  parentChat: (b) => req('POST', '/parent/chat', b),
  ageGate: (b) => req('POST', '/kid/age-gate', b),
  challenge: (id) => req('GET', `/kid/challenge/${id}`),
  claim: (b) => req('POST', '/kid/claim', b),
  mockChallenges: (email) => req('GET', `/kid/mock-challenges${email ? `?email=${encodeURIComponent(email)}` : ''}`),
  linkSuggestions: () => req('GET', '/kid/link-suggestions'),
  linkRequest: (b) => req('POST', '/kid/link-request', b),
  linkByCode: (b) => req('POST', '/kid/link-by-code', b),
  mockApprove: (b) => req('POST', '/kid/mock-approve', b),
  mockPermission: (b) => req('POST', '/kid/mock-permission', b),
  me: (uid) => req('GET', `/me/${uid}`),
  suggest: (b) => req('POST', '/suggest', b),
  pending: (uid) => req('GET', `/child/${uid}/pending`),
  parent: (email) => req('GET', `/parent/${encodeURIComponent(email)}`),
  parentSettings: (email, b) => req('PUT', `/parent/${encodeURIComponent(email)}/settings`, b),
  approve: (b) => req('POST', '/approve', b),
  notificationsRead: (email) => req('POST', `/parent/${encodeURIComponent(email)}/notifications/read`),
  feedback: (b) => req('POST', '/feedback', b),
  onboardTeen: (b) => req('POST', '/onboard/teen', b),
  contextAdult: (b) => req('POST', '/context/adult', b),
  transcribe: (uid, blob) => { const f = new FormData(); const ext = (blob.type || 'audio/webm').includes('mp4') ? 'mp4' : 'webm'; f.append('audio', blob, `clip.${ext}`); return req('POST', `/transcribe?user_id=${uid}`, f); },
  compare: (b) => req('POST', '/compare', b),
  addToCalendar: (b) => req('POST', '/calendar/add', b),
  speak: (b) => req('POST', '/speak', b),
  reset: () => req('POST', '/dev/reset'),
};

export const store = {
  get users() { try { return JSON.parse(localStorage.getItem('ft_users') || '[]'); } catch { return []; } },
  set users(xs) { localStorage.setItem('ft_users', JSON.stringify(xs)); },
  get currentId() { return localStorage.getItem('ft_current'); },
  set currentId(id) { id ? localStorage.setItem('ft_current', id) : localStorage.removeItem('ft_current'); },
  get user() { const id = this.currentId; return this.users.find((u) => u.id === id) || null; },
  upsert(u) { const xs = this.users.filter((x) => x.id !== u.id); xs.push(u); this.users = xs; this.currentId = u.id; },
  remove(id) { this.users = this.users.filter((x) => x.id !== id); if (this.currentId === id) this.currentId = null; },
  get challenge() { try { return JSON.parse(localStorage.getItem('ft_challenge') || 'null'); } catch { return null; } },
  set challenge(c) { c ? localStorage.setItem('ft_challenge', JSON.stringify(c)) : localStorage.removeItem('ft_challenge'); },
  get theme() { return localStorage.getItem('ft_theme') || 'dark'; },
  set theme(t) { localStorage.setItem('ft_theme', t); },
};

export const hasPerm = (user, name) => !!user?.permissions?.find((p) => p.name === name && p.enabled);
export const Icon = ({ n, style }) => <svg style={style}><use href={`#i-${n}`} /></svg>;
