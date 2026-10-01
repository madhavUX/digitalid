import Link from "next/link";

export default function HomePage() {
  return (
    <main className="home-shell">
      <p className="eyebrow">Public booking</p>
      <h1>BookAnything</h1>
      <p className="lede">
        Open a location booking page at{" "}
        <code>/book/&lt;location-slug&gt;</code>.
      </p>
      <p className="muted">
        Example:{" "}
        <Link href="/book/downtown">/book/downtown</Link>
      </p>
    </main>
  );
}
