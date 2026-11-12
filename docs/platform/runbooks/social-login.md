# Runbook: social sign-in (Google, Microsoft, Apple) on the Supabase pilot

Adds "Continue with Google / Microsoft / Apple" to the sign-in page of the Supabase pilot
(`https://mgr-ibm-bomagent.fly.dev`, Supabase project ref `wdjhfugsduoymelipimq`). All steps
are done by the owner in the provider consoles and the Supabase dashboard; Claude Code never
does them (CLAUDE.md §6). No provider credential belongs in the repository: they live only
in the Supabase dashboard.

The browser performs OAuth with PKCE against Supabase Auth; Supabase talks to the provider
and returns to `https://mgr-ibm-bomagent.fly.dev/auth/callback?code=...`. A button appears
only when its provider is listed in `BOMAGENT_SOCIAL_PROVIDERS` (step 6), so you can set up
the providers one at a time.

The only URL the providers need is Supabase's callback:

```
https://wdjhfugsduoymelipimq.supabase.co/auth/v1/callback
```

## 0. Supabase URL configuration (once)

Authentication -> URL Configuration: **Site URL** `https://mgr-ibm-bomagent.fly.dev`,
**Redirect URLs** add `https://mgr-ibm-bomagent.fly.dev/auth/callback` (and
`http://localhost:5173/auth/callback` for local work). Keep Authentication -> Sign In /
Providers -> Email -> **"Confirm email" ON** and do **not** enable manual linking (see
"Security notes").

## 1. Google (free)

1. Google Cloud Console -> create or pick a project -> APIs & Services -> OAuth consent
   screen: user type External, app name, support e-mail, authorised domain
   `mgr-ibm-bomagent.fly.dev`; scopes `openid`, `.../auth/userinfo.email`,
   `.../auth/userinfo.profile`. Publish the app (Testing mode only allows listed test users).
2. APIs & Services -> Credentials -> Create credentials -> **OAuth client ID** -> application
   type **Web application**.
3. Authorised JavaScript origins: `https://mgr-ibm-bomagent.fly.dev`.
   Authorised redirect URIs: `https://wdjhfugsduoymelipimq.supabase.co/auth/v1/callback`.
4. Copy the **Client ID** and **Client secret**.
5. Supabase -> Authentication -> Sign In / Providers -> **Google**: enable, paste Client ID
   and Client secret, save.

## 2. Microsoft (Entra ID; free)

1. Microsoft Entra admin center -> App registrations -> New registration. Name
   "BOM Agent". Supported account types: **Accounts in any organizational directory and
   personal Microsoft accounts** (multi-tenant + personal).
2. Redirect URI: platform **Web**,
   `https://wdjhfugsduoymelipimq.supabase.co/auth/v1/callback`.
3. Certificates & secrets -> New client secret; copy the **Value** immediately (it is shown
   once; note the expiry, max 24 months, and renew before it).
4. Overview: copy the **Application (client) ID**.
5. Token configuration -> Add optional claim -> token type **ID** -> **`xms_edov`** (and
   `email`); accept the Microsoft Graph permission prompt. This tells the application whether
   the e-mail domain is verified (see the security note a).
6. Supabase -> Authentication -> Sign In / Providers -> **Azure (Microsoft)**: enable, paste
   the Application (client) ID and the secret value; **Azure Tenant URL**: leave empty for
   multi-tenant + personal accounts (Supabase then uses the `common` endpoint); save.

## 3. Apple (requires a paid Apple Developer Program account, 99 USD/year)

1. developer.apple.com -> Certificates, Identifiers & Profiles -> Identifiers -> **App IDs**:
   register an App ID with the **Sign in with Apple** capability (primary App ID).
2. Identifiers -> **Services IDs** -> register one (for example `pl.example.bomagent.web`);
   this identifier is the **Client ID** for Supabase. Enable Sign in with Apple -> Configure:
   primary App ID from step 1, **Domains** `wdjhfugsduoymelipimq.supabase.co`, **Return URLs**
   `https://wdjhfugsduoymelipimq.supabase.co/auth/v1/callback`.
3. Keys -> register a new key with **Sign in with Apple** enabled (primary App ID); download
   the `.p8` file once (it cannot be downloaded again) and note the **Key ID**.
4. Note your **Team ID** (Membership details).
5. Apple does not give a static secret: the client secret is a **JWT signed with the `.p8`
   key** (ES256; header `kid` = Key ID; claims `iss` = Team ID, `sub` = Services ID, `aud` =
   `https://appleid.apple.com`, `iat`, `exp` at most 6 months). Generate it on your machine
   with the generator linked from the Supabase Apple guide (Authentication -> Providers ->
   Apple -> docs) or any ES256 JWT tool; never paste the `.p8` into a web page you do not
   trust.
6. Supabase -> Authentication -> Sign In / Providers -> **Apple**: enable; **Client IDs** =
   the Services ID; **Secret Key** = the generated JWT; save.
7. **Rotation:** Apple caps the JWT at 6 months. Put a calendar reminder at about 5 months,
   generate a new JWT from the same key and paste it into the same field. An expired secret
   makes the Apple button fail with a provider error until replaced.

## 4. Enable the buttons

Set the Fly environment and redeploy (owner machine):

```
BOMAGENT_SOCIAL_PROVIDERS = "google,azure,apple"   # only the ones you finished above
```

In `deploy/supabase/fly.toml` the line is present but commented out; uncomment it (or set it
with `fly secrets`/`fly config`) and redeploy with your usual command. `/config.json` then
returns `"providers": [...]` and the SPA shows the buttons in that order. Removing a provider
from the list hides its button without touching Supabase.

## 5. Check

1. Open the app in a private window, click each button, finish the provider sign-in; you land
   on `/start`. A first sign-in creates the Supabase user; the API creates the account on
   first use.
2. Cancel on the provider page: the sign-in page's callback shows a friendly message with a
   link back to `/login`.
3. Password recovery: request a reset e-mail; the link opens "Set a new password".

## Security notes (also in `docs/DECISIONS_LOG.md`)

a. **API trust and nOAuth.** `services/api/src/bomagent_api/auth.py`
   `require_verified_email` trusts Supabase's `email_confirmed_at`. Microsoft/Entra can
   return an e-mail the tenant admin never verified (the "nOAuth" class of attacks: an
   attacker with their own tenant sets someone else's address). Mitigations: (1) the
   optional claim `xms_edov` (step 2.5) lets Supabase/the app see whether the domain is
   verified; (2) register the app **tenant-specific** (single tenant) when only one company
   needs Microsoft sign-in, instead of multi-tenant; (3) in Supabase keep **"Confirm email"
   ON** and **do not enable manual linking**, so an identity from a provider is not merged
   into an existing e-mail account without proof of control of that mailbox. If you cannot
   accept the residual risk, do not list `azure` in `BOMAGENT_SOCIAL_PROVIDERS`.
b. **Apple private relay.** A user who chooses "Hide my e-mail" gets a
   `...@privaterelay.appleid.com` address. It will not match an invitation sent to the real
   address: invite that relay address instead, or ask the user to share their e-mail.
c. **Enforced-SSO organisations.** Organisations with enforced SSO require a Cognito
   identities claim; Supabase users have none, so they fail closed (cannot access such an
   organisation). This is intended: SSO exists only in the AWS deployment.
