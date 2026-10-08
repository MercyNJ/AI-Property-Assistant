const EXAMPLES = [
  "Find me a furnished 3-bedroom apartment in Ruiru under KES 80,000.",
  "I need somewhere around Ruiru for a family, preferably 3 bedrooms, and my budget is 80k.",
  "What's available in Kilimani with a swimming pool?",
  "Which areas do you have listings in?",
];

export function Welcome({ onPick }: { onPick: (text: string) => void }) {
  return (
    <section className="welcome">
      <h2>Find your next home</h2>
      <p>
        Monthly rentals across Nairobi, Kiambu and Machakos: Westlands, Kilimani, Kasarani, Ruiru, Ruaka,
        Kiambu Town, Thika and Syokimau.
      </p>
      <div className="examples">
        {EXAMPLES.map((text) => (
          <button key={text} type="button" className="example" onClick={() => onPick(text)}>
            {text}
          </button>
        ))}
      </div>
    </section>
  );
}
