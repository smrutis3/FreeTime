import { useState } from 'react';
import { api, Icon } from './api.jsx';

export default function LinkModal({ email, onClose }) {
  const [code, setCode] = useState('');
  const [step, setStep] = useState(1);
  const [err, setErr] = useState('');
  const go = async () => {
    if (step === 1) {
      setErr('');
      try { await api.linkByCode({ code, parent_email: email }); setStep(2); setTimeout(() => setStep(3), 1200); }
      catch (e) { setErr(e.message); }
    } else onClose();
  };
  return (
    <div className="modal" onClick={(e) => e.target.className === 'modal' && onClose()}>
      <div className="dialog">
        <svg className="mark" style={{ width: 56, height: 56 }} viewBox="0 0 100 100"><use href="#logo" /></svg>
        <h2>Link a child</h2>
        <p>{step === 1 ? "Enter the 6-digit code shown on your child's screen." : step === 2 ? 'k-ID is verifying you as a trusted adult…' : 'The request is in your Family panel. Choose topics and approve.'}</p>
        {step === 1 && <div className="codein"><input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="000000" inputMode="numeric" autoFocus /></div>}
        {step === 2 && <div className="typing" style={{ justifyContent: 'center' }}><i /><i /><i /></div>}
        {step === 3 && <div className="done-badge"><Icon n="check" /> Code accepted</div>}
        {err && <p className="err">{err}</p>}
        <button className="primary" onClick={go} disabled={step === 1 && code.length < 6}>{step === 1 ? 'Verify with k-ID' : step === 2 ? 'Verifying…' : 'Done'}</button>
        <p className="fine">k-ID verifies you as a trusted adult. FreeTime never sees your ID or your child's date of birth, only an age band and a consent status.</p>
      </div>
    </div>
  );
}
