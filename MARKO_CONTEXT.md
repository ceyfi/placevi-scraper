# Marko — Developer Context

Ovaj fajl kopiraj u svaki novi projekat i reci Claudeu: "pročitaj MARKO_CONTEXT.md".

---

## Stack koji znam i koristim

- **React** (Create React App) — frontend, funkcionalne komponente, hooks
- **Supabase** — baza podataka, auth (email/password, password reset), RLS politike, SQL editor
- **Vercel** — deployment, environment variables, serverless API routes (`/api/*.js`)
- **GitHub** — git, push/pull, auto-deploy na Vercel pri svakom pushu
- **Claude API** (Anthropic) — AI pozivi kroz Vercel API route proxy
- **Lemon Squeezy** — subscription plaćanje ($5/mesec), webhook integracija
- **Express.js** — osnovno, koristio za lokalni proxy server
- **CSS-in-JS** — inline stilovi i template string CSS unutar React fajlova

## Alati i okruženje

- **Editor**: Cursor (sa Claudeom)
- **OS**: Windows
- **Terminal**: PowerShell u Cursoru
- **Cowork**: Claude desktop app za asistenciju pri kodiranju

## Workflow

1. Kod se piše lokalno u `C:\Apps\[projekat]`
2. Git repo je na GitHubu (github.com/ceyfi)
3. Vercel je povezan sa GitHubom — svaki `git push` = automatski deploy
4. API ključevi idu SAMO u Vercel Environment Variables, nikad u kod
5. Claude (Cowork) direktno menja fajlove u folderu

## Git rutina

```
cd C:\Apps\[projekat-folder]
git add .
git commit -m "opis promene"
git push
```

Na novom kompu prvo:
```
git config --global http.sslVerify false
git clone https://github.com/ceyfi/[repo]
cd [repo]
```

## Šta znam da napravim (iz iskustva)

- Auth sistem sa login/signup/password reset
- Multi-user app sa RLS (svaki user vidi samo svoje podatke)
- AI feedback kroz Claude API
- Subscription paywall (freemium model)
- Serverless API route kao proxy za tajne ključeve
- Supabase tabele, politike, trigeri
- Webhook handler (Lemon Squeezy → Supabase update)
- File upload + Claude vision (image parsing)

## Važne napomene

- Srbija nije podržana za Stripe — koristiti **Lemon Squeezy** (isplata na PayPal)
- Supabase free plan: limit 3 emaila/sat za auth
- Vercel API routes: fajlovi u `/api/*.js` se automatski hostuju
- `REACT_APP_` prefix obavezan za env varijable u CRA frontendu
- Service role key (Supabase) zaobilazi RLS — koristiti SAMO na serveru

## Projekti

- **trade-journal** — AI trejding dnevnik, live na trade-journal-zeta-seven.vercel.app
- **SatoshiSafe** — kripto info sajt, može biti marketing page za trade-journal
