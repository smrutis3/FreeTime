import { useEffect, useState } from 'react';
import { api } from './api.jsx';
import { JURIS } from './Gate.jsx';

const AGES = [8, 14, 30];
const TIER_COLOR = { child: '#ff7a1a', teen: '#7c3aed', adult: '#0f766e' };

export default function Compare() {
  const [data, setData] = useState(null);
  const [juris, setJuris] = useState(['US-CA', 'GB', 'DE', 'BR']);
  const [ages, setAges] = useState(AGES);
  const [err, setErr] = useState('');

  useEffect(() => { api.compare({ ages, jurisdictions: juris }).then(setData).catch((e) => setErr(e.message)); }, [juris.join(), ages.join()]);

  const cell = (a, j) => data?.cells.find((c) => c.age === a && c.jurisdiction === j);

  return (
    <section>
      <h1>Same person, different country</h1>
      <p className="muted">One product. k-ID tells us the age status for each jurisdiction, and FreeTime reshapes itself. Source: {data?.source || '…'}</p>
      <div className="quick">{JURIS.map(([v, l]) => <button key={v} className={`${juris.includes(v) ? 'on' : ''}`} onClick={() => setJuris((xs) => xs.includes(v) ? xs.filter((x) => x !== v) : [...xs, v])}>{l}</button>)}</div>
      <div className="quick">ages {[6, 8, 12, 14, 16, 17, 30].map((a) => <button key={a} className={`${ages.includes(a) ? 'on' : ''}`} onClick={() => setAges((xs) => xs.includes(a) ? xs.filter((x) => x !== a) : [...xs, a].sort((p, q) => p - q))}>{a}</button>)}</div>
      {err && <p className="error">{err}</p>}
      <div className="matrix" style={{ gridTemplateColumns: `90px repeat(${juris.length}, 1fr)` }}>
        <div />
        {juris.map((j) => <div key={j} className="head">{JURIS.find(([v]) => v === j)?.[1] || j}</div>)}
        {ages.map((a) => (
          <Row key={a} a={a} cells={juris.map((j) => cell(a, j))} />
        ))}
      </div>
      <p className="muted small">Consent ages differ: 13 in the US and UK, 16 in Germany, 15 in France, 12 in Brazil. A 14-year-old is a teen in California and a child in Berlin.</p>
    </section>
  );
}

function Row({ a, cells }) {
  return (
    <>
      <div className="head">age {a}</div>
      {cells.map((c, i) => c ? (
        <div key={i} className="cell" style={{ borderTopColor: TIER_COLOR[c.tier] || '#999' }}>
          <strong style={{ color: TIER_COLOR[c.tier] }}>{c.tier || c.status}</strong>
          <div className="small">{c.age_status}</div>
          <ul>
            <li>{c.needs_parent ? '🔒 parent consent first' : '✅ straight in'}</li>
            <li>{c.approval ? '👪 parent approves each idea' : '🙋 own choices'}</li>
            <li>{c.memory ? '🧠 remembers likes' : '🚫 remembers nothing'}</li>
            <li>{c.connectors ? '📅 calendar + notes' : '📅 no connectors'}</li>
          </ul>
        </div>
      ) : <div key={i} className="cell"><div className="spinner" /></div>)}
    </>
  );
}
