## Description
Django admin (`/admin/`) was already mounted but no page in the app linked to it — a staff user had to type the URL directly. This adds an "Administrace" link to the user dropdown in the top navbar, visible only to `is_staff` users.

## Changes
- `templates/base.html`: new dropdown item "Administrace" (gear icon, links to `{% url 'admin:index' %}`), gated on `user.is_staff`, positioned above "Profil" with its own divider so it stays visible even for a staff user without an `Employee` profile.
- `accounts/tests.py`: new `AdministraceOdkazVNavbaruTests` covering a staff user without a profile (sees the link), a non-staff user with a profile (doesn't), and a non-staff user without a profile (doesn't).

## How to test
1. `venv/Scripts/python.exe manage.py test accounts` — 3/3 pass (full suite: 110/110)
2. Log in as an `is_staff` user, open the user dropdown — "Administrace" appears above "Profil" and navigates to `/admin/`

## Issue
Closes #45

🤖 Generated with [Claude Code](https://claude.com/claude-code)
