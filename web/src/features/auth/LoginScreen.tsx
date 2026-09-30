"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Fragment, useEffect, useId, useRef, useState, type CSSProperties, type FormEvent, type KeyboardEvent } from "react";
import { SignalField } from "@/components/auth/SignalField";
import { ThemeSwitcher } from "@/components/shell/ThemeSwitcher";
import { Icon } from "@/components/ui/Icon";
import { isApiError, NetworkError } from "@/lib/api/client";
import { useLogin, useMe, useProviders } from "@/lib/api/queries";
import { authErrorMessage, googleStartHref, type AuthMessage } from "@/lib/auth";
import { cx } from "@/lib/cx";
import { useMediaQuery } from "@/lib/interaction";
import { safeNext } from "@/lib/nav";

const FACTS = [
  { icon: "pulse" as const, text: "Real CGMacros v1.0.0 recordings: Dexcom CGM, Fitbit, logged meals, baseline labs." },
  { icon: "fingerprint" as const, text: "Every estimate is traceable to its model version, source data and moment." },
  { icon: "shield" as const, text: "Research prototype. Model-estimated associations, not medical advice." },
];

const HEADLINE = "How one person’s glucose responds to meals.";

const USERNAME = /^[A-Za-z0-9_.@-]{3,64}$/;

function Mark({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 22 22" aria-hidden="true">
      <rect x="0.75" y="0.75" width="20.5" height="20.5" rx="6" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M4 13.5c2-5 4-5 5.5-1.5S13 17 14.5 9.5 17 6 18 7" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/** Google's "G" mark, as its sign-in branding guidelines require for this button. */
function GoogleG() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" className="google-g">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62Z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18Z" />
      <path fill="#FBBC05" d="M3.97 10.72A5.4 5.4 0 0 1 3.68 9c0-.6.1-1.18.29-1.72V4.95H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.05l3.01-2.33Z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58Z" />
    </svg>
  );
}

function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}

function Message({ msg, id }: { msg: AuthMessage; id?: string }) {
  return (
    <div id={id} className={cx("login__msg", `login__msg--${msg.tone}`)} role={msg.tone === "error" ? "alert" : "status"}>
      <Icon name={msg.tone === "error" ? "alert" : "info"} size={16} />
      <div>
        <p className="login__msg-title">{msg.title}</p>
        {msg.body && <p className="login__msg-body">{msg.body}</p>}
      </div>
    </div>
  );
}

function GoogleOption({ next }: { next: string }) {
  const providers = useProviders();
  const [leaving, setLeaving] = useState(false);
  const enabled = providers.data?.google === true;
  const helpId = useId();
  if (enabled) {
    return (
      <div className="login__alt">
        <a
          className={cx("btn btn--lg btn--block btn--google", leaving && "is-pending")}
          href={googleStartHref(next)}
          onClick={() => setLeaving(true)}
          aria-describedby={helpId}
        >
          {leaving ? <Spinner /> : <GoogleG />}
          {leaving ? "Opening Google…" : "Continue with Google"}
        </a>
        <p id={helpId} className="login__hint">
          Only Google accounts linked by an administrator can sign in.
        </p>
      </div>
    );
  }
  const note = providers.isPending
    ? "Checking available sign-in methods…"
    : providers.isError
      ? "Google sign-in status is unavailable right now."
      : "Google sign-in isn’t configured on this server.";
  return (
    <div className="login__alt">
      <button type="button" className="btn btn--lg btn--block btn--google" disabled aria-describedby={helpId}>
        <GoogleG />
        Continue with Google
      </button>
      <p id={helpId} className="login__hint">
        {note}
      </p>
    </div>
  );
}

export function LoginScreen() {
  const router = useRouter();
  const params = useSearchParams();
  const me = useMe();
  const login = useLogin();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [touched, setTouched] = useState({ username: false, password: false });
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const [failures, setFailures] = useState(0);
  const userRef = useRef<HTMLInputElement>(null);
  const passRef = useRef<HTMLInputElement>(null);
  const ids = { user: useId(), pass: useId(), userErr: useId(), passErr: useId(), caps: useId(), server: useId() };

  const next = safeNext(params.get("next"));
  const compact = useMediaQuery("(max-width: 1023px)");

  // Already signed in (e.g. the back button, a bookmarked /login): go straight on, no form flash.
  const signedIn = me.isSuccess;
  useEffect(() => {
    if (signedIn) router.replace(next);
  }, [signedIn, next, router]);

  const userErr = touched.username
    ? !username.trim()
      ? "Enter your username."
      : !USERNAME.test(username.trim())
        ? "Usernames use 3–64 letters, digits and . _ @ - only."
        : null
    : null;
  const passErr = touched.password && !password ? "Enter your password." : null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTouched({ username: true, password: true });
    if (!username.trim() || !USERNAME.test(username.trim())) return userRef.current?.focus();
    if (!password) return passRef.current?.focus();
    login.mutate(
      { username: username.trim(), password },
      {
        onSuccess: () => router.replace(next),
        onError: (err) => {
          if (isApiError(err, "UNAUTHENTICATED")) {
            setFailures((n) => n + 1);
            setPassword("");
            passRef.current?.focus();
          }
        },
      },
    );
  };

  const onPasswordKey = (e: KeyboardEvent<HTMLInputElement>) => setCapsLock(e.getModifierState?.("CapsLock") ?? false);

  // one message area: the most relevant thing to say
  let message: AuthMessage | null = null;
  if (login.error) {
    if (login.error instanceof NetworkError)
      message = { tone: "error", title: "The server couldn’t be reached", body: "Check that the API is running, then try again." };
    else if (isApiError(login.error, "UNAUTHENTICATED"))
      message = {
        tone: "error",
        title: "Username or password not recognised",
        body:
          failures >= 3
            ? "After 5 failed attempts the account is locked for 15 minutes. Check Caps Lock, or ask an administrator."
            : "Check both and try again. Accounts are provisioned by an administrator.",
      };
    else if (isApiError(login.error, "VALIDATION_ERROR"))
      message = { tone: "error", title: "That username isn’t valid", body: "Usernames use letters, digits and . _ @ - only." };
    else message = { tone: "error", title: "Sign-in failed on the server", body: "Try again in a moment." };
  } else if (params.get("auth_error")) {
    message = authErrorMessage(params.get("auth_error"));
  } else if (params.get("expired") === "1") {
    message = { tone: "notice", title: "Your session ended", body: "Sign in again to continue where you were." };
  } else if (params.get("signed_out") === "1") {
    message = { tone: "notice", title: "You’re signed out" };
  }

  const checking = me.isPending || signedIn;
  const busy = login.isPending || login.isSuccess;

  return (
    <main className="login">
      <section className="login__intro" aria-labelledby="login-product">
        <div className="login__brand">
          <Mark />
          <span id="login-product">Glycemic Twin</span>
        </div>
        <div className="login__pitch">
          <h1 className="login__headline">
            <span className="sr-only">{HEADLINE}</span>
            {/* the headline reveals word by word; the words carry the order as a CSS index */}
            <span aria-hidden="true">
              {HEADLINE.split(" ").map((word, i) => (
                <Fragment key={i}>
                  <span className="login__word" style={{ "--i": i } as CSSProperties}>
                    {word}
                  </span>{" "}
                </Fragment>
              ))}
              <span className="login__caret" />
            </span>
          </h1>
          <p className="login__lede">
            A per-person model for prediabetes and type 2 diabetes: the estimated chance that a logged meal takes glucose
            above 180&nbsp;mg/dL within two hours, what the estimate rests on, and how it learns from each meal.
          </p>
        </div>
        <SignalField compact={compact} />
        <ul className="login__facts">
          {FACTS.map((f, i) => (
            <li key={f.text} style={{ "--i": i } as CSSProperties}>
              <Icon name={f.icon} />
              <span>{f.text}</span>
            </li>
          ))}
        </ul>
        <p className="login__source">CGMacros v1.0.0 · PhysioNet · CC BY-NC-SA 4.0</p>
      </section>

      <section className="login__panel" aria-label="Sign in">
        <div className="login__theme">
          <ThemeSwitcher />
        </div>

        <div className={cx("login__card", checking && "is-checking")}>
          {checking ? (
            <div className="login__checking" role="status" aria-live="polite">
              <Spinner />
              <span>{signedIn ? `Signed in as ${me.data?.username}. Opening the workspace…` : "Checking your session…"}</span>
            </div>
          ) : (
            <>
              <div className="login__head">
                <h2>Sign in</h2>
                <p>Clinician workspace. Accounts are provisioned by an administrator.</p>
              </div>

              {message && <Message msg={message} id={ids.server} />}

              <form className="login__form" onSubmit={submit} noValidate aria-busy={busy}>
                <div className={cx("field", userErr && "field--invalid")}>
                  <label htmlFor={ids.user} className="field__label">
                    Username
                  </label>
                  <input
                    ref={userRef}
                    id={ids.user}
                    className="input input--lg"
                    name="username"
                    autoComplete="username"
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    onBlur={() => username && setTouched((t) => ({ ...t, username: true }))}
                    aria-invalid={userErr ? true : undefined}
                    aria-describedby={userErr ? ids.userErr : undefined}
                    disabled={busy}
                    required
                  />
                  {userErr && (
                    <p id={ids.userErr} className="field__error">
                      {userErr}
                    </p>
                  )}
                </div>

                <div className={cx("field", passErr && "field--invalid")}>
                  <label htmlFor={ids.pass} className="field__label">
                    Password
                  </label>
                  <div className="input-affix">
                    <input
                      ref={passRef}
                      id={ids.pass}
                      className="input input--lg"
                      name="password"
                      type={showPassword ? "text" : "password"}
                      autoComplete="current-password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      onKeyDown={onPasswordKey}
                      onKeyUp={onPasswordKey}
                      onBlur={() => {
                        setCapsLock(false);
                        if (password) setTouched((t) => ({ ...t, password: true }));
                      }}
                      aria-invalid={passErr ? true : undefined}
                      aria-describedby={[passErr && ids.passErr, capsLock && ids.caps].filter(Boolean).join(" ") || undefined}
                      disabled={busy}
                      required
                    />
                    <button
                      type="button"
                      className="input-affix__btn"
                      onClick={() => setShowPassword((v) => !v)}
                      aria-pressed={showPassword}
                      aria-controls={ids.pass}
                      aria-label={showPassword ? "Hide password" : "Show password"}
                      disabled={busy}
                    >
                      <Icon name={showPassword ? "eyeOff" : "eye"} size={16} />
                    </button>
                  </div>
                  {passErr && (
                    <p id={ids.passErr} className="field__error">
                      {passErr}
                    </p>
                  )}
                  {capsLock && (
                    <p id={ids.caps} className="field__hint">
                      <Icon name="alert" size={12} /> Caps Lock is on
                    </p>
                  )}
                </div>

                <button type="submit" className={cx("btn btn--primary btn--lg btn--block", busy && "is-pending")} disabled={busy}>
                  {busy && <Spinner />}
                  {login.isSuccess ? "Signed in" : login.isPending ? "Signing in…" : "Sign in"}
                </button>
              </form>

              <div className="login__or" role="separator" aria-label="or">
                <span>or</span>
              </div>

              <GoogleOption next={next} />

              <p className="login__fine">
                Sessions use a secure HttpOnly cookie and end after 8 hours or when you sign out. Five failed attempts lock the
                account for 15 minutes.
              </p>
            </>
          )}
        </div>
      </section>
    </main>
  );
}
