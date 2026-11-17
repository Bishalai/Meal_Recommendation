/**
 * Shared helpers for the MealMate web interface.
 *
 * Session (JWT access/refresh token + username) is kept in localStorage and
 * every API call sends `Authorization: Bearer <access token>`.
 */
const MealMate = (() => {
  const ACCESS_KEY = 'meal_mate_access';
  const REFRESH_KEY = 'meal_mate_refresh';
  const USER_KEY = 'meal_mate_user';

  const session = () => ({
    access: localStorage.getItem(ACCESS_KEY),
    refresh: localStorage.getItem(REFRESH_KEY),
    username: localStorage.getItem(USER_KEY),
  });

  function saveSession({ access, refresh, username }) {
    localStorage.setItem(ACCESS_KEY, access);
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
    if (username) localStorage.setItem(USER_KEY, username);
    renderNav();
  }

  function clearSession() {
    [ACCESS_KEY, REFRESH_KEY, USER_KEY].forEach((key) => localStorage.removeItem(key));
    renderNav();
  }

  const isLoggedIn = () => Boolean(session().access);

  /**
   * Call the JSON API.
   * @param {string} path      e.g. '/api/recommended'
   * @param {object} options   { method, body, auth }
   * @returns {Promise<object>} parsed JSON (errors are returned as {error})
   */
  async function api(path, { method = 'GET', body, auth = true } = {}) {
    const headers = { 'Content-Type': 'application/json' };
    if (auth && session().access) {
      headers.Authorization = `Bearer ${session().access}`;
    }

    let response;
    try {
      response = await fetch(path, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (err) {
      return { error: 'cannot reach the server - is the backend running?' };
    }

    if (response.status === 401 && auth) {
      clearSession();
      window.location.href = '/signin/';
      return { error: 'session expired, please sign in again' };
    }

    let data = {};
    try {
      data = await response.json();
    } catch (err) {
      data = {};
    }

    if (!response.ok) {
      return { error: data.error || `request failed (${response.status})` };
    }
    return data;
  }

  /** Toggle the sign-in / sign-out parts of the navigation bar. */
  function renderNav() {
    const loggedIn = isLoggedIn();
    document.querySelectorAll('[data-auth="in"]').forEach((el) => {
      el.hidden = !loggedIn;
    });
    document.querySelectorAll('[data-auth="out"]').forEach((el) => {
      el.hidden = loggedIn;
    });
    const name = document.getElementById('nav-username');
    if (name) name.textContent = session().username || '';
  }

  /** Send the user to the sign-in page when there is no valid session. */
  function requireAuth() {
    if (!isLoggedIn()) {
      window.location.href = '/signin/';
      return false;
    }
    return true;
  }

  document.addEventListener('DOMContentLoaded', () => {
    renderNav();
    const signout = document.getElementById('signout-btn');
    if (signout) {
      signout.addEventListener('click', async () => {
        await MealMate.api('/api/signout', { method: 'POST' });
        MealMate.clearSession();
        window.location.href = '/';
      });
    }
  });

  return { api, saveSession, clearSession, isLoggedIn, renderNav, requireAuth, session };
})();
