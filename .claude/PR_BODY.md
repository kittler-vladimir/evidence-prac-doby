## Description

Adds a dedicated home/menu page at the root URL (`/`) that greets logged-in users with role-aware tiles linking to the app's main modules. Anonymous visitors are redirected to the login page. The navbar brand now points to this menu instead of directly to the dashboard, creating a natural entry point for the application.

## Changes

- **accounts/views.py**: New `home` view with `@login_required` decorator rendering `accounts/home.html`
- **accounts/urls.py**: Added `path("", views.home, name="home")` as the first URL pattern
- **templates/accounts/home.html**: New template with role-based tile grid (Docházka, Žádosti a stavy, Přítomnost for all; Ke schválení and Tým for managers; Zaměstnanci for staff)
- **templates/base.html**: Navbar brand `href` changed from `timetracking:dashboard` to `accounts:home`
- **config/settings.py**: `LOGIN_REDIRECT_URL` updated from `timetracking:dashboard` to `accounts:home`

## How to Test

1. **Anonymous user** — visit `http://127.0.0.1:8010/` → redirects to login with `?next=/`
2. **Regular employee** — log in and land on `/` → see Docházka, Žádosti a stavy, Přítomnost tiles only
3. **Department manager** — should also see Ke schválení and Tým tiles
4. **Admin/staff** — should also see Zaměstnanci tile
5. **Navbar** — click the "Docházka" brand from any page → returns to home menu
6. **Dashboard** — verify `timetracking:dashboard` still works at its original URL via the Docházka tile

## Issue

Closes #7
