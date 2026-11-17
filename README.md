# Meal Recommendation

A personalised meal recommender with a **web interface**: the engine looks at
your taste tags, diet, allergies, medical conditions and the time of day, then
suggests a dish (plus a matching side) together with your daily macro targets.

```
meal recommend/
├── recommendation_meal/          # this repository
│   ├── datasets/custom/          # datasets used by the prototype
│   └── backend/                  # Django backend + web interface  ← run this
│       ├── config/               # settings, urls, wsgi/asgi
│       ├── core/                 # models, views, recommendation engine, data, UI
│       └── scripts/
│           └── generate_users.py # creates demo users for collaborative filtering
└── recommendmeal_backend/        # previous (untidy) copy of the backend, kept for reference
```

---

## The user interface

The backend serves a complete graphical web app - no separate frontend build
is needed. Open it in a browser after starting the server.

| Screen | URL | What it does |
| ------ | --- | ------------ |
| Home | `/` | Landing page: what the app does, sign up / sign in calls to action |
| Sign up | `/signup/` | One form for account + health profile (age, height, weight, activity, diet, conditions, allergies, taste tags) |
| Sign in | `/signin/` | Logs you in, stores the JWT in the browser |
| Dashboard | `/dashboard/` | The main screen, see below |

**Dashboard** (requires sign-in, otherwise it redirects to `/signin/`):

- **Meal time picker** - Breakfast / Lunch / Dinner chips; the heading and the
  recommendation follow the selection.
- **Recommendation card** - the main dish, its companion (e.g. a curry for a
  staple), full description, ingredient tags, serving size, diet badge and the
  nutrition of the dish (kcal, carbs, fat, protein). Above the card a note
  explains **how the pick was made** (taste tags, similar users, or the
  cold-start fallback).
- **Star rating** - rate a pick from 1 to 5; it is written to your history so
  the same dish is not suggested again soon.
- **Daily targets** - calories, carbohydrate, fat and protein ranges computed
  from your profile (Harris-Benedict equation + activity factor).
- **History table** - everything you have rated, newest first.
- **Profile** - edit your details at any time, or delete the account
  (removes the database rows *and* the CSV records).

The interface is plain HTML/CSS/JavaScript served by Django
(`backend/core/templates/` and `backend/core/static/`), so it works offline
and talks to the JSON API with `fetch()`.

---

## How to run

Requirements: **Python 3.10+** and `pip`.

```bash
cd backend
pip install -r requirements.txt     # django, djangorestframework, simplejwt, pandas, scikit-learn ...
python manage.py migrate            # creates db.sqlite3
python scripts/generate_users.py    # optional: add 40 demo users + their ratings
python manage.py runserver          # http://127.0.0.1:8000
```

Then:

1. Open <http://127.0.0.1:8000/> and create an account (or use **Sign up**).
2. You land on the dashboard - pick a time of day and press
   **Get recommendation**.
3. Rate the dish; check your history and macro targets on the same page.

Optional: `python manage.py createsuperuser` then visit `/admin/` to manage
users and profiles.

### Demo data for collaborative filtering

Collaborative filtering needs a community of users who have rated dishes, so
the repository ships a generator that invents that community:

```bash
cd backend
python scripts/generate_users.py                 # add 40 demo users + ~400 ratings
python scripts/generate_users.py --count 60      # a bigger community
python scripts/generate_users.py --seed 42       # reproducible output
python scripts/generate_users.py --force         # delete old demo users first, then regenerate
python scripts/generate_users.py --remove        # only delete the demo users
```

* Each demo user gets a random profile (age, height, weight, activity), 3-6
  taste tags taken from real dish and ingredient words, a diet and
  occasionally an allergy or a medical condition.
* Each one rates 6-14 dishes - mostly dishes that match their own tags, while
  respecting their diet and allergies. That is exactly the taste structure
  collaborative filtering needs to discover "users who like the same things".
* Generated rows are appended to `core/data/user_info.csv` and
  `core/data/user_data.csv`; generated usernames start with `demo_`.
* Demo users exist **only in the CSV files** - they are not Django accounts
  and cannot sign in. Their ratings exist so that real users get sensible
  collaborative recommendations from their very first request.

The repository is delivered with 40 demo users and their ratings already
generated (47 users / 439 ratings in total).

Environment variables (all optional, sensible development defaults):

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `DJANGO_SECRET_KEY` | dev key | **set this in production** |
| `DJANGO_DEBUG` | `True` | `False` in production |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | comma separated |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000,...` | only if the UI is served from another origin |

---

## JSON API

All endpoints are prefixed with `/api/`. Everything except sign-up/sign-in
requires `Authorization: Bearer <access token>` (JWT).

| Method | Path | Description |
| ------ | ---- | ----------- |
| POST | `/api/signup` | create account + profile |
| POST | `/api/signin` | returns `access` / `refresh` tokens |
| POST | `/api/signout` | client deletes its tokens |
| POST | `/api/recommended` | body `{"time": "breakfast\|lunch\|dinner"}` -> recommended food + macro targets + `recommendation method` |
| POST | `/api/ratemeal` | body `{"food": ..., "rating": 1-5, "time": ...}` |
| GET | `/api/gethistory` | rated meals of the signed-in user |
| GET/PUT/DELETE | `/api/userdetails` | read / update / delete the profile |
| GET | `/api/profiles`, `/api/users` | list profiles / users |
| POST | `/api/token`, `/api/token/refresh` | standard SimpleJWT endpoints |

Example:

```bash
curl -X POST http://127.0.0.1:8000/api/signin \
     -H "Content-Type: application/json" \
     -d '{"username": "bishal", "password": "..."}'

curl -X POST http://127.0.0.1:8000/api/recommended \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer <access token>" \
     -d '{"time": "lunch"}'
```

---

## How the recommendation works

The ranker is a **hybrid of three signals**, blended into one score for every
dish in the catalogue:

| # | Signal | Needs | Used when |
| - | ------ | ----- | --------- |
| 1 | **Content-based** - cosine similarity between the user's taste tags and a bag-of-words document of each dish (`name + description + ingredients + diet`) | taste tags | the profile has usable tags |
| 2 | **Collaborative filtering** - users are compared on their rating history (mean-centred user-user cosine similarity); a dish's score is the rating the similar users would give it | at least one comparable rater and some ratings from this user | the user has rated meals before |
| 3 | **Popularity** - Bayesian average rating of the dish over the whole community | any ratings at all | cold start: no tags *and* no ratings |

Blending: `0.6 x content + 0.4 x collaborative` when both exist, otherwise the
single available signal, otherwise the cold-start fallback. The chosen signal
is returned in the response as `recommendation method` and shown in the
dashboard, so the user always knows *why* a dish was picked.

After ranking, the hard filters are applied:

1. no non-vegetarian dishes for vegetarian users,
2. no dish containing an allergen or an ingredient that conflicts with a
   medical condition,
3. only dishes that fit the selected meal time,
4. the 5 most recent recommendations are not repeated.

The top dish is then paired with its companion (staple + curry) and returned
with the user's daily macro ranges.

Data lives in CSV files in `backend/core/data/` (`food.csv`, `user_info.csv`,
`user_data.csv`, `disease_list.csv`, `ingredients_list.csv`), read and written
by `backend/core/recommendation.py`. The original prototype is kept unchanged
in `app/recommendation.py`.

---

