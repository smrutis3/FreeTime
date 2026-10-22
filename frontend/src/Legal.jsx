export function Privacy() {
  return (
    <section className="note">
      <h1>Privacy</h1>
      <p>FreeTime is a hackathon prototype (Build for Everyone, 21 Oct 2026). It asks for a date of birth only to let k-ID decide the age tier and, for children, obtain a parent's consent. We store no date of birth ourselves; k-ID returns an age status and a set of permissions.</p>
      <p>Requests you type, your weather, and your free windows are sent to Claude to pick three activities. For teens, thumbs votes and quiz answers are kept in server memory only while the server runs. For adults, pasted notes and calendars are kept the same way. Nothing is written to disk and nothing is shared with third parties beyond k-ID, Open-Meteo, Anthropic, and (if voice is on) Modulate and Inworld.</p>
      <p>Contact: see the submission form for the team email.</p>
    </section>
  );
}

export function Terms() {
  return (
    <section className="note">
      <h1>Terms</h1>
      <p>Prototype provided as-is for demonstration. Suggestions are ideas, not bookings or safety advice. Children's suggestions require a parent's approval before they are shown as a plan.</p>
    </section>
  );
}
