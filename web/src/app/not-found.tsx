import Link from "next/link";

export default function NotFound() {
  return (
    <main className="standalone">
      <div className="state state--center">
        <p className="state__title">Page not found</p>
        <p className="state__body">That address does not exist in this app.</p>
        <div className="state__actions">
          <Link className="btn" href="/patients">
            Go to patients
          </Link>
        </div>
      </div>
    </main>
  );
}
